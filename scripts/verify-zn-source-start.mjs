#!/usr/bin/env node
import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { rpcRequest } from '../apps/desktop/scripts/verify-zn-windows-clean-install.mjs'
import {
  npmInvocation,
  resolveDevHome,
  resolveDevUserData,
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

export function sourceBootstrapPaths(repoRoot, env = process.env, platform = process.platform) {
  const root = path.resolve(repoRoot)
  const devHome = resolveDevHome(root, env)
  const userData = resolveDevUserData(root, env)
  const pythonPath = venvPythonPathFor(path.join(root, '.venv'), platform)
  return {
    devHome,
    userData,
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

async function requireDirectory(directoryPath, label) {
  const stat = await fs.stat(directoryPath)
  if (!stat.isDirectory()) throw new Error(`${label} is not a directory: ${directoryPath}`)
}

async function terminateProcessTree(child) {
  if (!child || !child.pid || child.exitCode !== null) return
  if (process.platform === 'win32') {
    spawnSync('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
  } else {
    child.kill('SIGTERM')
  }
  const deadline = Date.now() + 5_000
  while (child.exitCode === null && Date.now() < deadline) await sleep(100)
  if (child.exitCode === null) child.kill('SIGKILL')
}

export async function verifyZnSourceStart({
  repoRoot = REPO_ROOT,
  env = process.env,
  timeoutMs = Number(env.ZN_DEV_SOURCE_SMOKE_TIMEOUT_MS || 600_000)
} = {}) {
  if (process.platform !== 'win32') {
    throw new Error(`source startup proof requires win32, got ${process.platform}`)
  }
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
    stdio: 'inherit'
  })
  child.once('error', error => { spawnError = error })

  const childState = () => {
    if (spawnError) return spawnError
    if (child.exitCode !== null) return new Error(`npm run dev exited before source Resident became ready (exit ${child.exitCode})`)
    if (child.signalCode) return new Error(`npm run dev exited before source Resident became ready (signal ${child.signalCode})`)
    return null
  }

  try {
    const endpoint = validateSourceEndpoint(
      await waitForJson(paths.endpointPath, timeoutMs, childState),
      { pythonPath: paths.pythonPath },
      process.platform
    )
    await requireDirectory(paths.userData, 'source Electron profile')
    await requireDirectory(path.join(paths.userData, 'session'), 'source Electron sessionData')

    const ping = await rpcRequest(endpoint, 'ping')
    if (!ping || ping.alive !== true || !Number.isInteger(ping.pulse_count) || ping.pulse_count < 1) {
      throw new Error(`source resident ping is invalid: ${JSON.stringify(ping)}`)
    }
    const status = await rpcRequest(endpoint, 'status')
    if (!status || typeof status !== 'object' || Array.isArray(status)) {
      throw new Error('source resident status is invalid')
    }

    await rpcRequest(endpoint, 'shutdown')
    await waitForMissing(paths.endpointPath, Math.min(timeoutMs, 15_000))

    return {
      endpointPath: paths.endpointPath,
      python: endpoint.python,
      instanceId: endpoint.instance_id,
      pulseCount: ping.pulse_count,
      userData: paths.userData
    }
  } finally {
    await terminateProcessTree(child)
  }
}

async function main() {
  const result = await verifyZnSourceStart()
  console.log(`[zn-source-start] endpoint=${result.endpointPath}`)
  console.log(`[zn-source-start] python=${result.python}`)
  console.log(`[zn-source-start] pulse_count=${result.pulseCount}`)
  console.log(`[zn-source-start] instance_id=${result.instanceId}`)
  console.log(`[zn-source-start] electron_profile=${result.userData}`)
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(SCRIPT_PATH)) {
  main().catch(error => {
    const message = error instanceof Error ? error.message : String(error)
    console.error(`[zn-source-start] ${message}`)
    process.exitCode = 1
  })
}
