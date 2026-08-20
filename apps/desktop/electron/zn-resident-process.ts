import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { EventEmitter } from 'node:events'
import readline from 'node:readline'

export type ZnResidentRequest = {
  id?: string
  method: 'ping' | 'status' | 'self' | 'pulses' | 'submit' | 'remember' | 'forget' | 'shutdown'
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
}

type Pending = {
  resolve: (value: unknown) => void
  reject: (error: Error) => void
  timer: NodeJS.Timeout
}

export function defaultZnResidentLaunch(env: NodeJS.ProcessEnv = process.env): ZnResidentLaunch {
  const explicit = (env.ZN_RESIDENT_PYTHON || '').trim()
  const command = explicit || (process.platform === 'win32' ? 'python' : 'python3')
  return {
    command,
    args: ['-m', 'agent.kernel.daemon'],
    env: { ...env, PYTHONUNBUFFERED: '1' }
  }
}

export class ZnResidentProcess extends EventEmitter {
  private child: ChildProcessWithoutNullStreams | null = null
  private sequence = 0
  private pending = new Map<string, Pending>()
  private readyPromise: Promise<unknown> | null = null

  constructor(private readonly launch: ZnResidentLaunch = defaultZnResidentLaunch()) {
    super()
  }

  get running(): boolean {
    return Boolean(this.child && this.child.exitCode === null && !this.child.killed)
  }

  async start(timeoutMs = 15_000): Promise<unknown> {
    if (this.running && this.readyPromise) return this.readyPromise

    const child = spawn(this.launch.command, this.launch.args, {
      cwd: this.launch.cwd,
      env: this.launch.env,
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true
    })
    this.child = child

    this.readyPromise = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('ZN Resident did not become ready in time')), timeoutMs)
      const onReady = (status: unknown) => {
        clearTimeout(timer)
        cleanup()
        resolve(status)
      }
      const onError = (error: Error) => {
        clearTimeout(timer)
        cleanup()
        reject(error)
      }
      const cleanup = () => {
        this.off('ready', onReady)
        this.off('process-error', onError)
      }
      this.once('ready', onReady)
      this.once('process-error', onError)
    })

    const lines = readline.createInterface({ input: child.stdout })
    lines.on('line', line => this.onLine(line))
    child.stderr.on('data', chunk => this.emit('stderr', String(chunk)))
    child.on('error', error => this.emit('process-error', error))
    child.on('exit', (code, signal) => {
      this.child = null
      this.readyPromise = null
      for (const pending of this.pending.values()) {
        clearTimeout(pending.timer)
        pending.reject(new Error(`ZN Resident exited (code=${code}, signal=${signal})`))
      }
      this.pending.clear()
      this.emit('exit', { code, signal })
    })

    return this.readyPromise
  }

  async request(method: ZnResidentRequest['method'], params: Record<string, unknown> = {}, timeoutMs = 120_000): Promise<unknown> {
    if (!this.running) await this.start()
    const child = this.child
    if (!child) throw new Error('ZN Resident process is unavailable')

    const id = `zn-${process.pid}-${Date.now()}-${++this.sequence}`
    const payload: ZnResidentRequest = { id, method, params }
    const response = new Promise<unknown>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new Error(`ZN Resident request timed out: ${method}`))
      }, timeoutMs)
      this.pending.set(id, { resolve, reject, timer })
    })
    child.stdin.write(`${JSON.stringify(payload)}\n`)
    return response
  }

  async stop(): Promise<void> {
    const child = this.child
    if (!child) return
    try {
      await this.request('shutdown', {}, 3_000)
    } catch {
      // Graceful RPC shutdown is best effort.
    }
    if (child.exitCode === null && !child.killed) child.kill('SIGTERM')
  }

  private onLine(line: string): void {
    let message: ZnResidentResponse
    try {
      message = JSON.parse(line) as ZnResidentResponse
    } catch {
      this.emit('protocol-error', new Error(`Invalid ZN Resident JSON: ${line.slice(0, 200)}`))
      return
    }

    if (message.type === 'ready') {
      this.emit('ready', message.status)
      return
    }

    const id = typeof message.id === 'string' ? message.id : ''
    if (!id) {
      this.emit('message', message)
      return
    }
    const pending = this.pending.get(id)
    if (!pending) return
    this.pending.delete(id)
    clearTimeout(pending.timer)
    if (message.ok === false) pending.reject(new Error(message.error || 'ZN Resident request failed'))
    else pending.resolve(message.result)
  }
}