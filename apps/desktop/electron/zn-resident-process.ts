import { spawn } from 'node:child_process'
import { EventEmitter } from 'node:events'
import { promises as fs } from 'node:fs'
import { createConnection, type Socket } from 'node:net'
import { homedir } from 'node:os'
import * as path from 'node:path'
import readline from 'node:readline'

export type ZnResidentRequest = {
  id?: string
  method:
    | 'ping'
    | 'status'
    | 'self'
    | 'provider_settings'
    | 'provider_settings_update'
    | 'work_list'
    | 'work_create'
    | 'work_get'
    | 'work_attach_workspace'
    | 'work_detach_workspace'
    | 'work_start'
    | 'work_progress'
    | 'work_cancel'
    | 'work_submit'
    | 'work_restore_prepare'
    | 'work_restore_approve'
    | 'work_restore_application'
    | 'pulses'
    | 'situations'
    | 'thoughts'
    | 'impasses'
    | 'learning'
    | 'neural'
    | 'perceive'
    | 'world_follow'
    | 'world_focuses'
    | 'world_observe'
    | 'submit'
    | 'remember'
    | 'forget'
    | 'shutdown'
  params?: Record<string, unknown>
}

export type ZnResidentResponse = {
  id?: string | null
  ok?: boolean
  result?: unknown
  error?: string
  type?: string
  status?: unknown
}

export type ZnResidentLaunch = {
  command: string
  args: string[]
  cwd?: string
  env?: NodeJS.ProcessEnv
  endpointPath: string
}

export type ZnResidentRuntimeIdentity = {
  runtimeId: string | null
  python: string | null
}

type ZnResidentEndpoint = {
  version: number
  transport: 'tcp'
  host: string
  port: number
  pid?: number
  instance_id?: string
  started_at?: string
  runtime_id?: string | null
  python?: string | null
}

type Pending = {
  resolve: (value: unknown) => void
  reject: (error: Error) => void
  timer: NodeJS.Timeout
}

export function isZnResidentLoopbackHost(value: unknown): boolean {
  const host = String(value || '').trim().toLowerCase()
  return host === '127.0.0.1' || host === 'localhost' || host === '::1'
}

function expandHome(value: string): string {
  if (value === '~') return homedir()
  if (value.startsWith('~/') || value.startsWith('~\\')) return path.join(homedir(), value.slice(2))
  return value
}

function defaultZnHome(env: NodeJS.ProcessEnv): string {
  const explicit = (env.ZN_AGENT_HOME || env.ZN_HOME || '').trim()
  if (explicit) return path.resolve(expandHome(explicit))
  if (process.platform === 'win32') {
    const local = (env.LOCALAPPDATA || '').trim()
    if (local) return path.join(local, 'znagent')
  }
  return path.join(homedir(), '.znagent')
}

export function defaultZnResidentLaunch(env: NodeJS.ProcessEnv = process.env): ZnResidentLaunch {
  const explicit = (env.ZN_RESIDENT_PYTHON || '').trim()
  const command = explicit || (process.platform === 'win32' ? 'python' : 'python3')
  const home = defaultZnHome(env)
  return {
    command,
    args: ['-m', 'zn_agent.resident'],
    env: { ...env, PYTHONUNBUFFERED: '1' },
    endpointPath: path.join(home, 'kernel', 'resident-endpoint.json')
  }
}

/** Desktop-side connection to the long-lived ZN resident service. */
export class ZnResidentProcess extends EventEmitter {
  private socket: Socket | null = null
  private lines: readline.Interface | null = null
  private sequence = 0
  private pending = new Map<string, Pending>()
  private readyPromise: Promise<unknown> | null = null
  private endpoint: ZnResidentEndpoint | null = null

  constructor(private readonly launch: ZnResidentLaunch = defaultZnResidentLaunch()) {
    super()
  }

  get running(): boolean {
    return Boolean(this.socket && !this.socket.destroyed)
  }

  get runtimeIdentity(): ZnResidentRuntimeIdentity {
    const runtimeId = typeof this.endpoint?.runtime_id === 'string' ? this.endpoint.runtime_id.trim() : ''
    const python = typeof this.endpoint?.python === 'string' ? this.endpoint.python.trim() : ''
    return { runtimeId: runtimeId || null, python: python || null }
  }

  async start(timeoutMs = 15_000): Promise<unknown> {
    if (this.running) return this.requestConnected('status', {}, Math.min(timeoutMs, 5_000))
    if (this.readyPromise) return this.readyPromise
    const promise = this.ensureConnected(timeoutMs)
    this.readyPromise = promise
    try {
      const status = await promise
      this.emit('ready', status)
      return status
    } finally {
      if (this.readyPromise === promise) this.readyPromise = null
    }
  }

  async request(
    method: ZnResidentRequest['method'],
    params: Record<string, unknown> = {},
    timeoutMs = 120_000
  ): Promise<unknown> {
    if (!this.running) await this.start()
    return this.requestConnected(method, params, timeoutMs)
  }

  async stop(): Promise<void> {
    if (!this.running) {
      try { await this.start(3_000) } catch { this.disconnect(); return }
    }
    try { await this.requestConnected('shutdown', {}, 3_000) } catch { void 0 } finally { this.disconnect() }
  }

  async restart(timeoutMs = 15_000): Promise<unknown> {
    await this.stop()
    await this.waitForEndpointRetirement(Math.min(5_000, Math.max(750, Math.floor(timeoutMs / 2))))
    return this.start(timeoutMs)
  }

  disconnect(): void {
    const socket = this.socket
    this.socket = null
    this.endpoint = null
    this.lines?.close()
    this.lines = null
    if (socket && !socket.destroyed) socket.destroy()
    this.rejectPending(new Error('ZN Resident client disconnected'))
  }

  private async waitForEndpointRetirement(timeoutMs: number): Promise<void> {
    const deadline = Date.now() + Math.max(250, timeoutMs)
    while (Date.now() < deadline) {
      try { await fs.access(this.launch.endpointPath) } catch { return }
      await new Promise(resolve => setTimeout(resolve, 100))
    }
  }

  private async ensureConnected(timeoutMs: number): Promise<unknown> {
    const deadline = Date.now() + Math.max(1_000, timeoutMs)
    let lastError: unknown = null
    try {
      await this.connectFromEndpoint(Math.min(1_500, Math.max(500, timeoutMs)))
      return await this.requestConnected('status', {}, 5_000)
    } catch (error) {
      lastError = error
      this.disconnect()
    }
    try { await this.launchDetachedService() } catch (error) { lastError = error }
    while (Date.now() < deadline) {
      try {
        await this.connectFromEndpoint(Math.min(1_500, Math.max(250, deadline - Date.now())))
        return await this.requestConnected('status', {}, Math.min(5_000, Math.max(500, deadline - Date.now())))
      } catch (error) {
        lastError = error
        this.disconnect()
        await new Promise(resolve => setTimeout(resolve, 120))
      }
    }
    const detail = lastError instanceof Error ? `: ${lastError.message}` : ''
    throw new Error(`ZN Resident service did not become reachable${detail}`)
  }

  private async launchDetachedService(): Promise<void> {
    await new Promise<void>((resolve, reject) => {
      const child = spawn(this.launch.command, this.launch.args, {
        cwd: this.launch.cwd,
        env: this.launch.env,
        detached: true,
        stdio: 'ignore',
        windowsHide: true
      })
      const onError = (error: Error) => { child.off('spawn', onSpawn); reject(error) }
      const onSpawn = () => { child.off('error', onError); child.unref(); resolve() }
      child.once('error', onError)
      child.once('spawn', onSpawn)
    })
  }

  private async connectFromEndpoint(timeoutMs: number): Promise<void> {
    const endpoint = await this.readEndpoint()
    if (endpoint.transport !== 'tcp') throw new Error(`Unsupported resident transport: ${endpoint.transport}`)
    await new Promise<void>((resolve, reject) => {
      const socket = createConnection({ host: endpoint.host, port: endpoint.port })
      const timer = setTimeout(() => { socket.destroy(); reject(new Error('Timed out connecting to ZN Resident endpoint')) }, Math.max(250, timeoutMs))
      const onError = (error: Error) => { clearTimeout(timer); socket.destroy(); reject(error) }
      socket.once('error', onError)
      socket.once('connect', () => {
        clearTimeout(timer)
        socket.off('error', onError)
        this.attachSocket(socket, endpoint)
        resolve()
      })
    })
  }

  private async readEndpoint(): Promise<ZnResidentEndpoint> {
    const raw = await fs.readFile(this.launch.endpointPath, 'utf8')
    const parsed = JSON.parse(raw) as Partial<ZnResidentEndpoint>
    const port = Number(parsed.port || 0)
    const host = String(parsed.host || '').trim()
    if (
      parsed.transport !== 'tcp' ||
      !isZnResidentLoopbackHost(host) ||
      !Number.isInteger(port) ||
      port <= 0 ||
      port > 65_535
    ) {
      throw new Error('ZN Resident endpoint file is invalid or non-loopback')
    }
    return {
      version: Number(parsed.version || 1), transport: 'tcp', host, port,
      pid: parsed.pid, instance_id: parsed.instance_id, started_at: parsed.started_at,
      runtime_id: typeof parsed.runtime_id === 'string' ? parsed.runtime_id : null,
      python: typeof parsed.python === 'string' ? parsed.python : null
    }
  }

  private attachSocket(socket: Socket, endpoint: ZnResidentEndpoint): void {
    this.disconnect()
    this.socket = socket
    this.endpoint = endpoint
    this.lines = readline.createInterface({ input: socket })
    this.lines.on('line', line => this.onLine(line))
    socket.on('error', error => { if (this.socket === socket) this.emit('process-error', error) })
    socket.on('close', () => {
      if (this.socket !== socket) return
      this.socket = null
      this.endpoint = null
      this.lines?.close()
      this.lines = null
      this.rejectPending(new Error('ZN Resident service connection closed'))
      this.emit('disconnect')
    })
  }

  private requestConnected(method: ZnResidentRequest['method'], params: Record<string, unknown>, timeoutMs: number): Promise<unknown> {
    const socket = this.socket
    if (!socket || socket.destroyed) return Promise.reject(new Error('ZN Resident service is not connected'))
    const id = `zn-${process.pid}-${Date.now()}-${++this.sequence}`
    const payload: ZnResidentRequest = { id, method, params }
    const response = new Promise<unknown>((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`ZN Resident request timed out: ${method}`)) }, Math.max(250, timeoutMs))
      this.pending.set(id, { resolve, reject, timer })
    })
    socket.write(`${JSON.stringify(payload)}\n`, error => {
      if (!error) return
      const pending = this.pending.get(id)
      if (!pending) return
      this.pending.delete(id)
      clearTimeout(pending.timer)
      pending.reject(error)
    })
    return response
  }

  private rejectPending(error: Error): void {
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer)
      pending.reject(error)
    }
    this.pending.clear()
  }

  private onLine(line: string): void {
    let message: ZnResidentResponse
    try { message = JSON.parse(line) as ZnResidentResponse } catch {
      this.emit('protocol-error', new Error(`Invalid ZN Resident JSON: ${line.slice(0, 200)}`))
      return
    }
    const id = typeof message.id === 'string' ? message.id : ''
    if (!id) { this.emit('message', message); return }
    const pending = this.pending.get(id)
    if (!pending) return
    this.pending.delete(id)
    clearTimeout(pending.timer)
    if (message.ok === false) pending.reject(new Error(message.error || 'ZN Resident request failed'))
    else pending.resolve(message.result)
  }
}
