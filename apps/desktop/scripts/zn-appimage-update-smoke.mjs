#!/usr/bin/env node
import assert from 'node:assert/strict'
import { execFileSync, spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import { promises as fsp } from 'node:fs'
import http from 'node:http'
import https from 'node:https'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'

const [, , installedArg, updateArg, homeArg] = process.argv
if (!installedArg || !updateArg || !homeArg) {
  throw new Error('usage: zn-appimage-update-smoke.mjs <installed-AppImage> <N+1-AppImage> <ZN-home>')
}

const installedPath = path.resolve(installedArg)
const updatePath = path.resolve(updateArg)
const znHome = path.resolve(homeArg)
const oldRuntimeId = process.env.ZN_SMOKE_N_RUNTIME_ID || 'version-0.17.0'
const newRuntimeId = process.env.ZN_SMOKE_N_PLUS_1_RUNTIME_ID || 'version-0.17.1'
const oldVersion = process.env.ZN_SMOKE_N_VERSION || '0.17.0'
const newVersion = process.env.ZN_SMOKE_N_PLUS_1_VERSION || '0.17.1'
const debugPort = Number(process.env.ZN_SMOKE_DEBUG_PORT || 9323)
const markerThread = 'm8-appimage-upgrade-continuity'
const endpointPath = path.join(znHome, 'kernel', 'resident-endpoint.json')
const unitPath = path.join(os.homedir(), '.config', 'systemd', 'user', 'zn-resident.service')

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

async function waitFor(label, probe, timeoutMs = 60_000, intervalMs = 250) {
  const deadline = Date.now() + timeoutMs
  let lastError = null
  while (Date.now() < deadline) {
    try {
      const value = await probe()
      if (value) return value
    } catch (error) {
      lastError = error
    }
    await sleep(intervalMs)
  }
  const detail = lastError instanceof Error ? `: ${lastError.message}` : ''
  throw new Error(`timed out waiting for ${label}${detail}`)
}

async function sha256(filePath) {
  const hash = createHash('sha256')
  const input = fs.createReadStream(filePath)
  for await (const chunk of input) hash.update(chunk)
  return hash.digest('hex')
}

async function readEndpoint() {
  const raw = await fsp.readFile(endpointPath, 'utf8')
  return JSON.parse(raw)
}

async function residentRpc(endpoint, method, params = {}, timeoutMs = 5_000) {
  return await new Promise((resolve, reject) => {
    const socket = net.createConnection({ host: endpoint.host, port: Number(endpoint.port) })
    let buffer = ''
    const timer = setTimeout(() => {
      socket.destroy()
      reject(new Error(`resident RPC timed out: ${method}`))
    }, timeoutMs)

    const finish = (error, value) => {
      clearTimeout(timer)
      socket.destroy()
      if (error) reject(error)
      else resolve(value)
    }

    socket.once('error', error => finish(error))
    socket.once('connect', () => {
      socket.write(`${JSON.stringify({ id: `smoke-${Date.now()}`, method, params })}\n`)
    })
    socket.on('data', chunk => {
      buffer += chunk.toString('utf8')
      const newline = buffer.indexOf('\n')
      if (newline < 0) return
      try {
        const response = JSON.parse(buffer.slice(0, newline))
        if (response.ok === false) finish(new Error(response.error || `resident RPC failed: ${method}`))
        else finish(null, response.result)
      } catch (error) {
        finish(error)
      }
    })
  })
}

function readLocalJson(pathname, timeoutMs = 2_000) {
  return new Promise((resolve, reject) => {
    const request = http.get({
      host: '127.0.0.1',
      port: debugPort,
      path: pathname,
      agent: false,
      headers: { connection: 'close' }
    }, response => {
      let data = ''
      response.setEncoding('utf8')
      response.on('data', chunk => { data += chunk })
      response.on('end', () => {
        const status = response.statusCode ?? 0
        if (status < 200 || status >= 300) {
          reject(new Error(`CDP HTTP ${status} for ${pathname}`))
          return
        }
        try {
          resolve(JSON.parse(data))
        } catch (error) {
          reject(error)
        }
      })
    })
    request.setTimeout(timeoutMs, () => request.destroy(new Error(`CDP HTTP timeout for ${pathname}`)))
    request.on('error', reject)
  })
}

class CdpSession {
  constructor(socket) {
    this.socket = socket
    this.sequence = 0
    this.pending = new Map()
    socket.addEventListener('message', event => {
      let message
      try {
        message = JSON.parse(String(event.data))
      } catch {
        return
      }
      if (!message.id) return
      const pending = this.pending.get(message.id)
      if (!pending) return
      this.pending.delete(message.id)
      clearTimeout(pending.timer)
      if (message.error) pending.reject(new Error(message.error.message || 'CDP command failed'))
      else pending.resolve(message.result)
    })
    socket.addEventListener('close', () => {
      for (const pending of this.pending.values()) {
        clearTimeout(pending.timer)
        pending.reject(new Error('CDP socket closed'))
      }
      this.pending.clear()
    })
  }

  static async connect(url) {
    const socket = new WebSocket(url)
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('CDP WebSocket open timed out')), 10_000)
      socket.addEventListener('open', () => {
        clearTimeout(timer)
        resolve()
      }, { once: true })
      socket.addEventListener('error', event => {
        clearTimeout(timer)
        reject(new Error(`CDP WebSocket error: ${String(event.message || event.type || event)}`))
      }, { once: true })
    })
    return new CdpSession(socket)
  }

  call(method, params = {}, timeoutMs = 15_000) {
    const id = ++this.sequence
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new Error(`CDP command timed out: ${method}`))
      }, timeoutMs)
      this.pending.set(id, { resolve, reject, timer })
      this.socket.send(JSON.stringify({ id, method, params }))
    })
  }

  async evaluate(expression, timeoutMs = 30_000) {
    const result = await this.call('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true
    }, timeoutMs)
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text || 'renderer evaluation failed')
    }
    return result.result?.value
  }

  close() {
    try { this.socket.close() } catch { void 0 }
  }
}

let desktopExit = null

async function connectDesktopCdp() {
  return await waitFor('real Electron renderer CDP target', async () => {
    if (desktopExit) {
      throw new Error(`Electron exited before CDP became ready: code=${desktopExit.code} signal=${desktopExit.signal}`)
    }
    await readLocalJson('/json/version')
    const targets = await readLocalJson('/json/list')
    const target = targets.find(item => item.type === 'page' && item.webSocketDebuggerUrl)
    if (!target) return null
    const cdp = await CdpSession.connect(target.webSocketDebuggerUrl)
    await cdp.call('Runtime.enable')
    const exposed = await cdp.evaluate(`typeof window.znDesktop === 'object'`)
    if (!exposed) {
      cdp.close()
      return null
    }
    return cdp
  }, 45_000, 300)
}

async function startUpdateServer(updateSha, updateSize) {
  const tlsDir = await fsp.mkdtemp(path.join(os.tmpdir(), 'zn-m8-update-tls-'))
  const keyPath = path.join(tlsDir, 'key.pem')
  const certPath = path.join(tlsDir, 'cert.pem')
  execFileSync('openssl', [
    'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
    '-keyout', keyPath, '-out', certPath, '-days', '1',
    '-subj', '/CN=127.0.0.1', '-addext', 'subjectAltName=IP:127.0.0.1'
  ], { stdio: 'ignore' })

  let manifest = null
  const server = https.createServer({
    key: await fsp.readFile(keyPath),
    cert: await fsp.readFile(certPath)
  }, (request, response) => {
    const url = new URL(request.url || '/', 'https://127.0.0.1')
    if (url.pathname === '/stable.json') {
      const body = Buffer.from(JSON.stringify(manifest))
      response.writeHead(200, {
        'content-type': 'application/json',
        'content-length': String(body.length),
        'cache-control': 'no-store'
      })
      response.end(body)
      return
    }
    if (url.pathname === '/ZN-N-plus-1.AppImage') {
      response.writeHead(200, {
        'content-type': 'application/octet-stream',
        'content-length': String(updateSize),
        'cache-control': 'no-store'
      })
      fs.createReadStream(updatePath).pipe(response)
      return
    }
    response.writeHead(404)
    response.end('not found')
  })

  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolve)
  })
  const address = server.address()
  assert.ok(address && typeof address === 'object')
  const baseUrl = `https://127.0.0.1:${address.port}`
  manifest = {
    schema: 1,
    product: 'ZN',
    channel: 'stable',
    version: newVersion,
    release_url: `${baseUrl}/releases/${newVersion}`,
    notes: {
      new: ['M8 real AppImage updater smoke'],
      improvements: [],
      fixes: [],
      impact: ['Resident identity and durable work must survive N to N+1.']
    },
    targets: [{
      platform: 'linux',
      arch: process.arch,
      name: 'ZN-N-plus-1.AppImage',
      url: `${baseUrl}/ZN-N-plus-1.AppImage`,
      size: updateSize,
      sha256: updateSha
    }]
  }
  return { server, tlsDir, channelUrl: `${baseUrl}/stable.json` }
}

async function waitForIdle(cdp) {
  return await waitFor('resident queue to become idle', async () => {
    const status = await cdp.evaluate('window.znDesktop.resident.status()')
    const queueDepth = Number(status?.queue_depth || 0)
    const currentEvent = status?.working_state?.current_event_id
    return queueDepth === 0 && !currentEvent ? status : null
  }, 120_000, 500)
}

let desktop = null
let cdp = null
let updateServer = null
let tlsDir = null
let finalEndpoint = null

try {
  await fsp.mkdir(path.dirname(installedPath), { recursive: true })
  await fsp.mkdir(znHome, { recursive: true })
  await fsp.chmod(installedPath, 0o755)
  await fsp.chmod(updatePath, 0o755)

  const [oldSha, updateSha, updateStat] = await Promise.all([
    sha256(installedPath),
    sha256(updatePath),
    fsp.stat(updatePath)
  ])
  assert.notEqual(oldSha, updateSha, 'N and N+1 AppImages must be distinct artifacts')

  const serverState = await startUpdateServer(updateSha, updateStat.size)
  updateServer = serverState.server
  tlsDir = serverState.tlsDir

  const launchEnv = {
    ...process.env,
    APPIMAGE_EXTRACT_AND_RUN: '1',
    ZN_AGENT_HOME: znHome,
    ZN_HOME: znHome,
    ZN_DESKTOP_UPDATE_CHANNEL_URL: serverState.channelUrl,
    NODE_TLS_REJECT_UNAUTHORIZED: '0'
  }
  desktop = spawn(installedPath, [
    `--remote-debugging-port=${debugPort}`,
    '--remote-debugging-address=127.0.0.1',
    '--disable-gpu',
    '--no-sandbox'
  ], {
    env: launchEnv,
    stdio: ['ignore', 'pipe', 'pipe']
  })
  desktop.stdout?.on('data', chunk => process.stdout.write(`[ZN N stdout] ${chunk}`))
  desktop.stderr?.on('data', chunk => process.stderr.write(`[ZN N stderr] ${chunk}`))
  desktop.once('exit', (code, signal) => {
    desktopExit = { code, signal }
    console.error(`[ZN N exit] code=${code} signal=${signal}`)
  })

  cdp = await connectDesktopCdp()

  const initialEndpoint = await waitFor('N resident endpoint', async () => {
    const endpoint = await readEndpoint()
    if (endpoint.runtime_id !== oldRuntimeId) return null
    await residentRpc(endpoint, 'ping')
    return endpoint
  }, 45_000, 250)
  assert.equal(initialEndpoint.runtime_id, oldRuntimeId)

  await waitFor('N autostart unit', async () => {
    const text = await fsp.readFile(unitPath, 'utf8')
    return text.includes(initialEndpoint.python) ? text : null
  }, 30_000, 300)

  const initialSelf = await cdp.evaluate('window.znDesktop.resident.self()')
  assert.ok(initialSelf?.born_at)
  assert.ok(initialSelf?.name)
  const initialPulseCount = Number(initialSelf?.pulse_count || 0)

  const marker = await cdp.evaluate(`window.znDesktop.resident.workCreate(${JSON.stringify({
    threadId: markerThread,
    title: 'M8 AppImage upgrade continuity marker',
    metadata: { proof: 'same-home', source_runtime: oldRuntimeId }
  })})`)
  assert.equal(marker?.id, markerThread)

  const prepared = await waitFor('N+1 AppImage download and verification', async () => {
    const status = await cdp.evaluate('window.znDesktop.updates.check()', 45_000)
    assert.equal(status?.currentVersion, oldVersion)
    assert.equal(status?.availableVersion, newVersion)
    assert.equal(status?.updateAvailable, true)
    assert.equal(status?.supported, true, status?.message || 'update must be supported')
    return status?.downloadState === 'ready' ? status : null
  }, 120_000, 500)
  assert.equal(prepared.downloadState, 'ready')

  const busyProbe = await cdp.evaluate(`(async () => {
    for (let index = 0; index < 6; index += 1) {
      await window.znDesktop.resident.workStart({
        threadId: 'm8-busy-' + index,
        task: 'Process M8 resident continuity marker ' + index + ' without external cognition.'
      })
    }
    const status = await window.znDesktop.resident.status()
    const apply = await window.znDesktop.updates.apply()
    return {
      queueDepth: status.queue_depth,
      activeRuntimeId: status.desktop_runtime?.activeRuntimeId,
      apply
    }
  })()`, 45_000)
  assert.ok(Number(busyProbe?.queueDepth || 0) > 0, 'busy probe must create durable resident work')
  assert.equal(busyProbe?.activeRuntimeId, oldRuntimeId)
  assert.equal(busyProbe?.apply?.ok, false)
  assert.equal(busyProbe?.apply?.error, 'resident-busy')

  await sleep(750)
  assert.equal(await sha256(installedPath), oldSha, 'BUSY application gate must not replace the running AppImage')
  const busyEndpoint = await readEndpoint()
  assert.equal(busyEndpoint.instance_id, initialEndpoint.instance_id, 'BUSY gate must not retire the N resident')
  assert.equal(busyEndpoint.runtime_id, oldRuntimeId)
  assert.equal(await cdp.evaluate('document.title'), 'ZN', 'BUSY gate must keep the N Electron renderer alive')

  await waitForIdle(cdp)
  const beforeHandoffSelf = await cdp.evaluate('window.znDesktop.resident.self()')
  const beforeHandoffPulseCount = Number(beforeHandoffSelf?.pulse_count || initialPulseCount)
  const beforeStat = await fsp.stat(installedPath)

  const idleApply = await cdp.evaluate('window.znDesktop.updates.apply()', 45_000)
  assert.equal(idleApply?.ok, true, idleApply?.message || 'IDLE application handoff must start')

  await waitFor('AppImage atomic replacement', async () => {
    const current = await fsp.stat(installedPath)
    return current.ino !== beforeStat.ino ? current : null
  }, 45_000, 250)
  assert.equal(await sha256(installedPath), updateSha, 'installed AppImage must become the exact N+1 artifact')

  finalEndpoint = await waitFor('N+1 resident after real Electron relaunch', async () => {
    const endpoint = await readEndpoint()
    if (endpoint.runtime_id !== newRuntimeId || endpoint.instance_id === initialEndpoint.instance_id) return null
    await residentRpc(endpoint, 'ping')
    return endpoint
  }, 90_000, 300)

  const finalSelf = await residentRpc(finalEndpoint, 'self')
  const finalWork = await residentRpc(finalEndpoint, 'work_get', { thread_id: markerThread })
  const finalStatus = await residentRpc(finalEndpoint, 'status')

  assert.equal(finalEndpoint.runtime_id, newRuntimeId)
  assert.notEqual(finalEndpoint.instance_id, initialEndpoint.instance_id)
  assert.equal(finalSelf?.born_at, initialSelf?.born_at, 'living Self born_at must survive N to N+1')
  assert.equal(finalSelf?.name, initialSelf?.name, 'living Self identity must survive N to N+1')
  assert.ok(Number(finalSelf?.pulse_count || 0) >= beforeHandoffPulseCount, 'pulse history must remain monotonic')
  assert.equal(finalWork?.id, markerThread)
  assert.equal(finalWork?.metadata?.proof, 'same-home')
  assert.equal(finalWork?.metadata?.source_runtime, oldRuntimeId)
  assert.equal(Number(finalStatus?.queue_depth || 0), 0)

  const runtimeDirs = await fsp.readdir(path.join(znHome, 'runtime'))
  assert.ok(runtimeDirs.includes(oldRuntimeId), `missing retained N runtime ${oldRuntimeId}`)
  assert.ok(runtimeDirs.includes(newRuntimeId), `missing materialized N+1 runtime ${newRuntimeId}`)

  const finalUnit = await fsp.readFile(unitPath, 'utf8')
  assert.ok(finalUnit.includes(finalEndpoint.python), 'future autostart must target the N+1 resident Python')
  assert.ok(!finalUnit.includes(initialEndpoint.python), 'future autostart must no longer target the N resident Python')

  console.log(JSON.stringify({
    proof: 'ZN Linux AppImage N to N+1 application/runtime continuity',
    installed_appimage: installedPath,
    old_version: oldVersion,
    new_version: newVersion,
    old_runtime_id: oldRuntimeId,
    new_runtime_id: newRuntimeId,
    old_instance_id: initialEndpoint.instance_id,
    new_instance_id: finalEndpoint.instance_id,
    same_home: znHome,
    self_born_at: finalSelf?.born_at,
    work_thread: finalWork?.id,
    busy_gate: 'resident-busy',
    final_queue_depth: finalStatus?.queue_depth,
    appimage_sha256: updateSha
  }, null, 2))
} finally {
  cdp?.close()
  if (finalEndpoint) {
    try { await residentRpc(finalEndpoint, 'shutdown', {}, 3_000) } catch { void 0 }
  }
  if (desktop && desktop.exitCode === null && !desktop.killed) {
    try { desktop.kill('SIGTERM') } catch { void 0 }
  }
  try {
    execFileSync('systemctl', ['--user', 'disable', '--now', 'zn-resident.service'], { stdio: 'ignore' })
  } catch { void 0 }
  try { await fsp.rm(unitPath, { force: true }) } catch { void 0 }
  try { execFileSync('systemctl', ['--user', 'daemon-reload'], { stdio: 'ignore' }) } catch { void 0 }
  if (updateServer) {
    await new Promise(resolve => updateServer.close(resolve))
  }
  if (tlsDir) await fsp.rm(tlsDir, { recursive: true, force: true })
}
