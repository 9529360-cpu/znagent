#!/usr/bin/env node
import { execFile } from 'node:child_process'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { promisify } from 'node:util'
import { pathToFileURL } from 'node:url'

const MAX_SCAN_DEPTH = 8
const PACKAGED_RUNTIME_SMOKE_TIMEOUT_MS = 60_000
const execFileAsync = promisify(execFile)
const RETIRED_PACKAGE_NAME = Buffer.from('6865726d65735f636c69', 'hex').toString('utf8')

const PACKAGED_RUNTIME_SMOKE = `
import os
from pathlib import Path

import zn_agent.resident
from zn_agent.core.browser import BrowserPermissionContext
from zn_agent.core.managed_browser import PlaywrightManagedBrowser
from zn_agent.core.provider_bridge import build_resident_runtime

home = Path(os.environ["ZN_AGENT_HOME"])
home.mkdir(parents=True, exist_ok=True)
resident = build_resident_runtime(config={"model": {}}, store_path=home / "kernel.db")
try:
    pulse = resident.pulse()
    state = resident.life.snapshot()
    assert pulse.sequence >= 1
    assert state.body is not None
    assert state.external_brains == ()
finally:
    resident.store.close()

browser = PlaywrightManagedBrowser()
session = browser.open_session(permission=BrowserPermissionContext(), headless=True)
try:
    observation = browser.observe(session.session_id)
    assert observation.url == "about:blank"
    assert session.profile_scope == "ephemeral"
    assert session.provider == "playwright-chromium"
finally:
    browser.close()
`

function resolveInside(root, relativePath, label) {
  if (typeof relativePath !== 'string' || !relativePath.trim() || path.isAbsolute(relativePath)) {
    throw new Error(`ZN packaged runtime ${label} must be a non-empty relative path`)
  }
  const resolvedRoot = path.resolve(root)
  const target = path.resolve(resolvedRoot, relativePath)
  const relative = path.relative(resolvedRoot, target)
  if (relative.startsWith('..') || path.isAbsolute(relative)) {
    throw new Error(`ZN packaged runtime ${label} escapes runtime root`)
  }
  return target
}

async function requireFile(filePath, label) {
  let stat
  try { stat = await fs.stat(filePath) } catch { throw new Error(`ZN packaged runtime ${label} is missing: ${filePath}`) }
  if (!stat.isFile()) throw new Error(`ZN packaged runtime ${label} is not a file: ${filePath}`)
  return stat
}

async function requireDirectory(dirPath, label) {
  let stat
  try { stat = await fs.stat(dirPath) } catch { throw new Error(`ZN packaged runtime ${label} is missing: ${dirPath}`) }
  if (!stat.isDirectory()) throw new Error(`ZN packaged runtime ${label} is not a directory: ${dirPath}`)
}

function smokeFailureDetail(error) {
  if (error && typeof error === 'object') {
    const stderr = typeof error.stderr === 'string' ? error.stderr.trim() : ''
    if (stderr) return stderr
    const stdout = typeof error.stdout === 'string' ? error.stdout.trim() : ''
    if (stdout) return stdout
    if (error instanceof Error && error.message) return error.message
  }
  return String(error)
}

export async function findPackagedZnRuntimeRoots(releaseDir) {
  const root = path.resolve(releaseDir)
  const found = []
  const queue = [{ dir: root, depth: 0 }]
  while (queue.length) {
    const current = queue.shift()
    let entries
    try { entries = await fs.readdir(current.dir, { withFileTypes: true }) } catch { continue }
    for (const entry of entries) {
      if (!entry.isDirectory()) continue
      const child = path.join(current.dir, entry.name)
      if (entry.name === 'zn-runtime') {
        try {
          const stat = await fs.stat(path.join(child, 'runtime.json'))
          if (stat.isFile()) found.push(child)
        } catch { void 0 }
        continue
      }
      if (current.depth < MAX_SCAN_DEPTH) queue.push({ dir: child, depth: current.depth + 1 })
    }
  }
  return found.sort()
}

export async function verifyPackagedZnRuntime(runtimeRoot, { version, commit }) {
  const manifestPath = path.join(runtimeRoot, 'runtime.json')
  const manifest = JSON.parse(await fs.readFile(manifestPath, 'utf8'))
  if (manifest?.schema !== 1 || manifest?.product !== 'ZN') throw new Error(`unsupported packaged ZN runtime manifest: ${manifestPath}`)
  if (manifest.version !== version) throw new Error(`packaged runtime version mismatch: expected ${version}, got ${manifest.version}`)
  if (manifest.commit !== commit) throw new Error(`packaged runtime commit mismatch: expected ${commit}, got ${manifest.commit}`)
  if (manifest.platform && manifest.platform !== process.platform) throw new Error(`packaged runtime platform mismatch: expected ${process.platform}, got ${manifest.platform}`)
  if (manifest.arch && manifest.arch !== process.arch) throw new Error(`packaged runtime architecture mismatch: expected ${process.arch}, got ${manifest.arch}`)
  const runtimeId = String(manifest.runtime_id || '').trim()
  if (!runtimeId) throw new Error(`packaged runtime id is missing: ${manifestPath}`)
  if (/^[0-9a-f]{40}$/i.test(commit) && runtimeId.toLowerCase() !== commit.toLowerCase()) {
    throw new Error(`packaged runtime id mismatch: expected ${commit.toLowerCase()}, got ${runtimeId}`)
  }
  const python = resolveInside(runtimeRoot, manifest.python, 'python')
  const backendRoot = resolveInside(runtimeRoot, manifest.backend_root, 'backend_root')
  const browserRoot = resolveInside(runtimeRoot, manifest.browser_root, 'browser_root')
  const pythonStat = await requireFile(python, 'python executable')
  if (process.platform !== 'win32' && (pythonStat.mode & 0o111) === 0) throw new Error(`packaged runtime python is not executable: ${python}`)
  await requireDirectory(backendRoot, 'backend root')
  await requireDirectory(browserRoot, 'managed browser root')
  const browserEntries = await fs.readdir(browserRoot)
  if (browserEntries.length === 0) throw new Error(`packaged runtime managed browser root is empty: ${browserRoot}`)
  await requireFile(path.join(backendRoot, 'zn_agent', 'resident.py'), 'resident package entrypoint')
  await requireFile(path.join(backendRoot, 'zn_agent', 'core', 'resident_server.py'), 'resident core entrypoint')
  try {
    await fs.stat(path.join(backendRoot, RETIRED_PACKAGE_NAME))
    throw new Error(`packaged ZN runtime contains forbidden retired package: ${path.join(backendRoot, RETIRED_PACKAGE_NAME)}`)
  } catch (error) {
    if (error instanceof Error && error.message.startsWith('packaged ZN runtime contains')) throw error
  }
  return { runtimeRoot: path.resolve(runtimeRoot), runtimeId, python, backendRoot, browserRoot }
}

export async function smokePackagedZnRuntime(runtime, { run = execFileAsync } = {}) {
  const home = await fs.mkdtemp(path.join(os.tmpdir(), 'zn-packaged-runtime-smoke-'))
  try {
    await run(runtime.python, ['-I', '-c', PACKAGED_RUNTIME_SMOKE], {
      cwd: runtime.runtimeRoot,
      env: {
        ...process.env,
        CI: 'true',
        PYTHONUTF8: '1',
        PYTHONUNBUFFERED: '1',
        ZN_AGENT_HOME: home,
        ZN_RUNTIME_ID: runtime.runtimeId,
        PLAYWRIGHT_BROWSERS_PATH: runtime.browserRoot
      },
      timeout: PACKAGED_RUNTIME_SMOKE_TIMEOUT_MS,
      maxBuffer: 1024 * 1024,
      windowsHide: true
    })
  } catch (error) {
    throw new Error(`packaged ZN runtime smoke failed for ${runtime.runtimeRoot}: ${smokeFailureDetail(error)}`)
  } finally {
    await fs.rm(home, { recursive: true, force: true })
  }
}

export async function verifyPackagedZnRelease({ releaseDir, version, commit }) {
  const roots = await findPackagedZnRuntimeRoots(releaseDir)
  if (roots.length === 0) throw new Error(`no packaged ZN runtime found under ${path.resolve(releaseDir)}`)
  const verified = []
  for (const runtimeRoot of roots) verified.push(await verifyPackagedZnRuntime(runtimeRoot, { version, commit }))
  return verified
}

async function main() {
  const releaseDir = path.resolve(process.argv[2] || 'apps/desktop/release')
  const version = String(process.argv[3] || '').trim()
  const commit = String(process.argv[4] || '').trim()
  if (!version || !commit) throw new Error('usage: verify-zn-packaged-runtime.mjs <release-dir> <version> <commit>')
  const verified = await verifyPackagedZnRelease({ releaseDir, version, commit })
  for (const item of verified) {
    await smokePackagedZnRuntime(item)
    console.log(`[zn-runtime] verified resident and managed Chromium ${item.runtimeId} at ${item.runtimeRoot}`)
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) await main()
