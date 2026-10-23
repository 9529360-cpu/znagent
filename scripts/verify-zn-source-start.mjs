#!/usr/bin/env node
// verify-zn-source-start: prove one-command source startup from a clean state.
//
// Spawns `npm run dev` (scripts/zn-dev.mjs), waits for the isolated Resident
// to publish its authenticated endpoint, validates the endpoint contract,
// performs an authenticated status RPC as a liveness proof, then shuts the
// Resident down and requires its endpoint to retire.
//
// The endpoint/RPC contract is the one the resident engine actually
// implements (runtime/python/zn_agent/core/resident_server.py): version 2
// authenticated TCP loopback endpoint with a per-process session secret
// (scheme session-secret-v1). The newline-delimited JSON RPC protocol
// (authenticate-then-request) is unchanged from the salvage source.
//
// Salvaged from work/dev-bootstrap-quickstart-v2@dbf568c and adapted for the
// post-desktop repository: the RPC client was previously imported from the
// desktop verifier script (deleted with the desktop in #623), so it is
// inlined here; the ping/shutdown RPCs and the desktop profile checks had no
// counterpart in the current resident and were replaced with a status
// liveness check and process-tree shutdown (the resident removes its
// endpoint on SIGTERM / graceful stop).
import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs/promises'
import net from 'node:net'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  npmInvocation,
  resolveDevHome,
  venvPythonPathFor
} from './zn-dev.mjs'

const SCRIPT_PATH = fileURLToPath(import.meta.url)
const SCRIPT_DIR = path.dirname(SCRIPT_PATH)
const REPO_ROOT = path.resolve(SCRIPT_DIR, '..')

function samePath(left, right, platform = process.platform) {
  const normalize = value => {
    const resolved = path.resolve(String(value || ''))
    return platform === 'win32' ? resolved.toLowerCase() : resolved
  }
  return normalize(left) === normalize(right)
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

function processAlive(pid) {
  try {
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

export function sourceBootstrapPaths(repoRoot, env = process.env, platform = process.platform) {
  const root = path.resolve(repoRoot)
  const devHome = resolveDevHome(root, env)
  const pythonPath = venvPythonPathFor(path.join(root, '.venv'), platform)
  return {
    devHome,
    pythonPath,
    endpointPath: path.join(devHome, 'kernel', 'resident-endpoint.json')
  }
}

export function validateSourceEndpoint(endpoint, { pythonPath }, platform = process.platform) {
  if (!endpoint || typeof endpoint !== 'object' || Array.isArray(endpoint)) {
    throw new Error('source resident endpoint must be an object')
  }
  if (endpoint.version !== 2 || endpoint.transport !== 'tcp') {
    throw new Error('source resident endpoint must use version 2 authenticated tcp transport')
  }
  const host = String(endpoint.host || '').trim().toLowerCase()
  if (!['127.0.0.1', 'localhost', '::1'].includes(host)) {
    throw new Error(`source resident endpoint host is not loopback: ${endpoint.host}`)
  }
  if (!Number.isInteger(endpoint.port) || endpoint.port <= 0 || endpoint.port > 65_535) {
    throw new Error(`source resident endpoint port is invalid: ${endpoint.port}`)
  }
  if (!Number.isInteger(endpoint.pid) || endpoint.pid <= 0) {
    throw new Error('source resident endpoint pid is invalid')
  }
  if (typeof endpoint.instance_id !== 'string' || !endpoint.instance_id.trim()) {
    throw new Error('source resident endpoint instance_id is missing')
  }
  const authentication = endpoint.authentication
  if (!authentication || typeof authentication !== 'object' || Array.isArray(authentication)) {
    throw new Error('source resident endpoint authentication metadata is missing')
  }
  if (authentication.scheme !== 'session-secret-v1') {
    throw new Error('source resident endpoint authentication scheme is invalid')
  }
  if (typeof authentication.secret !== 'string' || authentication.secret.length < 32) {
    throw new Error('source resident endpoint authentication secret is invalid')
  }
  if (typeof endpoint.python !== 'string' || !endpoint.python.trim()) {
    throw new Error('source resident endpoint python is missing')
  }
  if (!samePath(endpoint.python, pythonPath, platform)) {
    throw new Error(`source resident python mismatch: expected ${pythonPath}, got ${endpoint.python}`)
  }
  return endpoint
}

export async function rpcRequest(endpoint, method, params = {}, timeoutMs = 5000) {
  return await new Promise((resolve, reject) => {
    const socket = net.createConnection({ host: endpoint.host, port: endpoint.port })
    let buffer = ''
    const authId = `source-start-auth-${process.pid}-${Date.now()}`
    const requestId = `source-start-${process.pid}-${Date.now()}`
    let authenticated = false
    const timer = setTimeout(() => {
      socket.destroy()
      reject(new Error(`resident RPC timed out: ${method}`))
    }, timeoutMs)
    const fail = error => {
      clearTimeout(timer)
      socket.destroy()
      reject(error)
    }
    socket.once('error', fail)
    socket.once('connect', () => {
      socket.write(`${JSON.stringify({
        id: authId,
        method: 'authenticate',
        params: { secret: endpoint.authentication.secret }
      })}\n`)
    })
    socket.on('data', chunk => {
      buffer += chunk.toString('utf8')
      while (true) {
        const newline = buffer.indexOf('\n')
        if (newline < 0) return
        const line = buffer.slice(0, newline)
        buffer = buffer.slice(newline + 1)
        let response
        try { response = JSON.parse(line) } catch (error) { fail(error); return }
        if (!authenticated) {
          if (response.id !== authId) continue
          if (response.ok === false || response.result?.authenticated !== true) {
            fail(new Error(response.error || 'resident authentication failed'))
            return
          }
          authenticated = true
          socket.write(`${JSON.stringify({ id: requestId, method, params })}\n`)
          continue
        }
        if (response.id !== requestId) continue
        clearTimeout(timer)
        socket.end()
        if (response.ok === false) reject(new Error(response.error || `resident RPC failed: ${method}`))
        else resolve(response.result)
        return
      }
    })
  })
}

async function waitForJson(filePath, timeoutMs, childState) {
  const deadline = Date.now() + timeoutMs
  let lastError = null
  while (Date.now() < deadline) {
    const childError = childState()
    if (childError) throw childError
    try {
      return JSON.parse(await fs.readFile(filePath, 'utf8'))
    } catch (error) {
      lastError = error
    }
    await sleep(250)
  }
  const detail = lastError instanceof Error ? `: ${lastError.message}` : ''
  throw new Error(`timed out waiting for source resident endpoint ${filePath}${detail}`)
}

async function waitForMissing(filePath, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      await fs.access(filePath)
    } catch {
      return
    }
    await sleep(200)
  }
  throw new Error(`source resident endpoint did not retire: ${filePath}`)
}

async function terminateProcessTree(child) {
  if (!child || !child.pid || child.exitCode !== null) return
  if (process.platform === 'win32') {
    spawnSync('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
  } else {
    // The child was spawned detached in its own process group so that one
    // signal reaches the whole tree (npm -> node launcher -> resident).
    // Signalling only the top process would orphan the resident.
    try {
      process.kill(-child.pid, 'SIGTERM')
    } catch {
      child.kill('SIGTERM')
    }
  }
  const deadline = Date.now() + 5_000
  while (child.exitCode === null && Date.now() < deadline) await sleep(100)
  if (child.exitCode === null) {
    if (process.platform === 'win32') {
      child.kill('SIGKILL')
    } else {
      try {
        process.kill(-child.pid, 'SIGKILL')
      } catch {
        child.kill('SIGKILL')
      }
    }
  }
}

// Remove an endpoint file only when it is provably ours: the instance id
// matches the one we just verified and its owning pid is dead. A force-killed
// child (Windows taskkill) cannot run the resident's graceful endpoint
// removal, so without this the proof would leave a stale file behind. Never
// touch an endpoint that belongs to another instance.
async function removeOwnStaleEndpoint(endpointPath, instanceId) {
  let raw
  try {
    raw = JSON.parse(await fs.readFile(endpointPath, 'utf8'))
  } catch {
    return false
  }
  if (!raw || typeof raw !== 'object' || raw.instance_id !== instanceId) return false
  if (Number.isInteger(raw.pid) && raw.pid > 0 && processAlive(raw.pid)) return false
  await fs.rm(endpointPath, { force: true })
  return true
}

export async function verifyZnSourceStart({
  repoRoot = REPO_ROOT,
  env = process.env,
  timeoutMs = Number(env.ZN_DEV_SOURCE_SMOKE_TIMEOUT_MS || 600_000)
} = {}) {
  if (!Number.isFinite(timeoutMs) || timeoutMs < 30_000) {
    throw new Error(`source startup timeout is invalid: ${timeoutMs}`)
  }

  const paths = sourceBootstrapPaths(repoRoot, env, process.platform)
  let endpointExists = false
  try {
    await fs.access(paths.endpointPath)
    endpointExists = true
  } catch (error) {
    if (!error || typeof error !== 'object' || error.code !== 'ENOENT') throw error
  }
  if (endpointExists) {
    throw new Error(`refusing to reuse a pre-existing source resident endpoint: ${paths.endpointPath}`)
  }

  const npm = npmInvocation(['run', 'dev'], env, process.platform)
  let spawnError = null
  const child = spawn(npm.command, npm.args, {
    cwd: path.resolve(repoRoot),
    env,
    shell: npm.shell,
    stdio: 'inherit',
    // Own process group on POSIX so terminateProcessTree can signal the
    // whole tree (npm -> node launcher -> resident) with one kill.
    detached: process.platform !== 'win32'
  })
  child.once('error', error => { spawnError = error })

  const childState = () => {
    if (spawnError) return spawnError
    if (child.exitCode !== null) return new Error(`npm run dev exited before source Resident became ready (exit ${child.exitCode})`)
    if (child.signalCode) return new Error(`npm run dev exited before source Resident became ready (signal ${child.signalCode})`)
    return null
  }

  let instanceId = null
  try {
    const endpoint = validateSourceEndpoint(
      await waitForJson(paths.endpointPath, timeoutMs, childState),
      { pythonPath: paths.pythonPath },
      process.platform
    )
    instanceId = endpoint.instance_id

    const status = await rpcRequest(endpoint, 'status')
    if (!status || typeof status !== 'object' || Array.isArray(status)) {
      throw new Error('source resident status is invalid')
    }
    const pulseCount = status?.self?.pulse_count
    if (!Number.isInteger(pulseCount) || pulseCount < 1) {
      throw new Error(`source resident is not pulsing: ${JSON.stringify(pulseCount)}`)
    }

    return {
      endpointPath: paths.endpointPath,
      python: endpoint.python,
      instanceId,
      pulseCount
    }
  } finally {
    await terminateProcessTree(child)
    try {
      await waitForMissing(paths.endpointPath, Math.min(timeoutMs, 15_000))
    } catch (error) {
      if (instanceId && await removeOwnStaleEndpoint(paths.endpointPath, instanceId)) return
      throw error
    }
  }
}

async function main() {
  const result = await verifyZnSourceStart()
  console.log(`[zn-source-start] endpoint=${result.endpointPath}`)
  console.log(`[zn-source-start] python=${result.python}`)
  console.log(`[zn-source-start] pulse_count=${result.pulseCount}`)
  console.log(`[zn-source-start] instance_id=${result.instanceId}`)
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(SCRIPT_PATH)) {
  main().catch(error => {
    const message = error instanceof Error ? error.message : String(error)
    console.error(`[zn-source-start] ${message}`)
    process.exitCode = 1
  })
}
