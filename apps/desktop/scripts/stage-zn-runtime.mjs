#!/usr/bin/env node
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(here, '..')
const repoRoot = path.resolve(desktopRoot, '../..')
const runtimeProject = path.join(repoRoot, 'runtime', 'python')
const runtimeRoot = path.join(desktopRoot, 'build', 'zn-runtime')
const pythonInstallDir = path.join(runtimeRoot, 'python')
const browserInstallDir = path.join(runtimeRoot, 'playwright-browsers')
const chromeDevtoolsMcpVersion = '1.9.0'
const chromeDevtoolsMcpRuntimeDir = path.join(runtimeRoot, 'browser-runtimes', 'chrome-devtools-mcp')
const veteranSourceRoot = path.join(repoRoot, 'vendor', 'veteran-engineer')
const veteranRuntimeDir = path.join(runtimeRoot, 'veteran-engineer')
const retiredPackageName = Buffer.from('6865726d65735f636c69', 'hex').toString('utf8')
const npmCommand = process.platform === 'win32' ? 'npm.cmd' : 'npm'

function run(command, args, options = {}) {
  execFileSync(command, args, {
    cwd: repoRoot,
    env: process.env,
    stdio: 'inherit',
    ...options
  })
}

function capture(command, args, options = {}) {
  return execFileSync(command, args, {
    cwd: repoRoot,
    env: process.env,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'inherit'],
    ...options
  }).trim()
}

function findPortablePython(installDir) {
  const roots = fs
    .readdirSync(installDir, { withFileTypes: true })
    .filter(entry => entry.isDirectory() && !entry.isSymbolicLink())
    .map(entry => path.join(installDir, entry.name))
  const candidates = []
  for (const root of roots) {
    if (process.platform === 'win32') candidates.push(path.join(root, 'python.exe'))
    else {
      candidates.push(path.join(root, 'bin', 'python3.11'))
      candidates.push(path.join(root, 'bin', 'python3'))
      candidates.push(path.join(root, 'bin', 'python'))
    }
  }
  const found = candidates.find(candidate => fs.existsSync(candidate) && fs.statSync(candidate).isFile())
  if (!found) throw new Error(`Could not locate portable Python under ${installDir}`)
  return found
}

function removeWindowsPythonAliases(installDir, pythonPath) {
  if (process.platform !== 'win32') return

  const concreteRoot = path.dirname(pythonPath)
  const concreteReal = fs.realpathSync(concreteRoot).toLowerCase()
  for (const entry of fs.readdirSync(installDir, { withFileTypes: true })) {
    if (!entry.isSymbolicLink()) continue
    const candidate = path.join(installDir, entry.name)
    let resolved
    try {
      resolved = fs.realpathSync(candidate).toLowerCase()
    } catch {
      continue
    }
    if (resolved !== concreteReal) continue
    fs.unlinkSync(candidate)
    console.log(`[zn-runtime] removed portable Python alias ${candidate}`)
  }

  const remainingAliases = fs
    .readdirSync(installDir, { withFileTypes: true })
    .filter(entry => entry.isSymbolicLink())
    .map(entry => entry.name)
  if (remainingAliases.length > 0) {
    throw new Error(`ZN packaged Python contains unsupported top-level aliases: ${remainingAliases.join(', ')}`)
  }
}

function portableRelative(root, target) {
  const relative = path.relative(root, target)
  if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) {
    throw new Error(`Runtime path escapes payload root: ${target}`)
  }
  return relative.split(path.sep).join('/')
}

function gitHead() {
  return capture('git', ['rev-parse', 'HEAD'])
}

fs.rmSync(runtimeRoot, { recursive: true, force: true })
fs.mkdirSync(pythonInstallDir, { recursive: true })

const veteranServer = path.join(veteranSourceRoot, 'mcp', 'server.mjs')
const veteranManifest = path.join(veteranSourceRoot, 'VENDOR.json')
if (!fs.existsSync(veteranServer) || !fs.existsSync(veteranManifest)) {
  throw new Error(`Vendored Veteran runtime is incomplete under ${veteranSourceRoot}`)
}
console.log('[zn-runtime] staging Veteran engineering runtime')
fs.cpSync(veteranSourceRoot, veteranRuntimeDir, {
  recursive: true,
  force: true,
  verbatimSymlinks: true
})

console.log('[zn-runtime] installing portable CPython 3.11')
run('uv', ['python', 'install', '3.11', '--install-dir', pythonInstallDir, '--no-bin'])
const pythonPath = findPortablePython(pythonInstallDir)
removeWindowsPythonAliases(pythonInstallDir, pythonPath)
const stagedPythonInstallArgs = ['--python', pythonPath, '--break-system-packages']

console.log('[zn-runtime] installing ZN-owned Python distribution with managed-browser support')
run('uv', ['pip', 'install', ...stagedPythonInstallArgs, `${runtimeProject}[browser]`])

console.log('[zn-runtime] installing version-bound Playwright Chromium')
fs.mkdirSync(browserInstallDir, { recursive: true })
run(pythonPath, ['-m', 'playwright', 'install', 'chromium'], {
  env: {
    ...process.env,
    PLAYWRIGHT_BROWSERS_PATH: browserInstallDir
  }
})
if (fs.readdirSync(browserInstallDir).length === 0) {
  throw new Error(`Playwright Chromium installation produced an empty browser root: ${browserInstallDir}`)
}

console.log(`[zn-runtime] installing chrome-devtools-mcp@${chromeDevtoolsMcpVersion}`)
fs.mkdirSync(chromeDevtoolsMcpRuntimeDir, { recursive: true })
run(npmCommand, [
  'install',
  '--prefix',
  chromeDevtoolsMcpRuntimeDir,
  '--no-save',
  '--package-lock=false',
  '--omit=dev',
  '--ignore-scripts',
  `chrome-devtools-mcp@${chromeDevtoolsMcpVersion}`
])
const chromeDevtoolsMcpPackageRoot = path.join(
  chromeDevtoolsMcpRuntimeDir,
  'node_modules',
  'chrome-devtools-mcp'
)
const chromeDevtoolsMcpManifestPath = path.join(chromeDevtoolsMcpPackageRoot, 'package.json')
const chromeDevtoolsMcpServer = path.join(
  chromeDevtoolsMcpPackageRoot,
  'build',
  'src',
  'bin',
  'chrome-devtools-mcp.js'
)
if (!fs.existsSync(chromeDevtoolsMcpManifestPath) || !fs.existsSync(chromeDevtoolsMcpServer)) {
  throw new Error(`Pinned Chrome DevTools MCP runtime is incomplete under ${chromeDevtoolsMcpRuntimeDir}`)
}
const chromeDevtoolsMcpManifest = JSON.parse(fs.readFileSync(chromeDevtoolsMcpManifestPath, 'utf8'))
if (
  chromeDevtoolsMcpManifest.name !== 'chrome-devtools-mcp'
  || chromeDevtoolsMcpManifest.version !== chromeDevtoolsMcpVersion
) {
  throw new Error(
    `Chrome DevTools MCP version mismatch: expected ${chromeDevtoolsMcpVersion}, got ${chromeDevtoolsMcpManifest.version || '<missing>'}`
  )
}

// Ask the staged interpreter where zn_agent was actually installed instead of
// assuming a platform-specific site-packages layout. uv's portable Windows
// CPython's generic site-package discovery can report the runtime root, while
// the installed package itself lives under Lib/site-packages.
const backendRoot = JSON.parse(capture(pythonPath, [
  '-c',
  [
    'import importlib.util, json',
    'from pathlib import Path',
    "spec = importlib.util.find_spec('zn_agent')",
    "assert spec is not None and spec.origin is not None, 'installed zn_agent package not found'",
    'print(json.dumps(str(Path(spec.origin).resolve().parent.parent)))'
  ].join('; ')
]))
const residentEntry = path.join(backendRoot, 'zn_agent', 'resident.py')
const residentCore = path.join(backendRoot, 'zn_agent', 'core', 'browser_resident_server.py')
if (!fs.existsSync(residentEntry)) throw new Error(`Installed runtime is missing zn_agent/resident.py under ${backendRoot}`)
if (!fs.existsSync(residentCore)) throw new Error(`Installed runtime is missing zn_agent/core/browser_resident_server.py under ${backendRoot}`)
if (fs.existsSync(path.join(backendRoot, retiredPackageName))) {
  throw new Error(`ZN runtime unexpectedly contains retired package under ${backendRoot}`)
}

console.log('[zn-runtime] running ZN zero-model smoke')
run(pythonPath, [
  '-I',
  '-c',
  [
    'import sys',
    'import tempfile',
    'from pathlib import Path',
    'import zn_agent.resident',
    'from zn_agent.core.browser_resident_server import main as formal_resident_main',
    'from zn_agent.core.provider_bridge import build_resident_runtime',
    'from zn_agent.core.resident_autostart import _resident_argv',
    'd = tempfile.TemporaryDirectory()',
    "argv = _resident_argv(Path(d.name) / 'home', sys.executable)",
    "assert argv[1:3] == ['-m', 'zn_agent.resident']",
    'assert zn_agent.resident.main is formal_resident_main',
    "r = build_resident_runtime(config={'model': {}}, store_path=Path(d.name) / 'kernel.db')",
    'p = r.pulse()',
    's = r.life.snapshot()',
    'assert p.sequence >= 1 and s.body is not None and s.external_brains == ()',
    'r.store.close()',
    'd.cleanup()'
  ].join('; ')
])

const commit = (process.env.ZN_RELEASE_COMMIT || gitHead()).trim()
const version = (process.env.ZN_RELEASE_VERSION || '').trim() || '0.0.0-dev'
const runtimeId = /^[0-9a-f]{7,40}$/i.test(commit) ? commit.toLowerCase() : `version-${version}`
const pythonVersion = capture(pythonPath, ['-c', 'import platform; print(platform.python_version())'])
const manifest = {
  schema: 1,
  product: 'ZN',
  runtime_id: runtimeId,
  version,
  commit,
  platform: process.platform,
  arch: process.arch,
  python_version: pythonVersion,
  python: portableRelative(runtimeRoot, pythonPath),
  backend_root: portableRelative(runtimeRoot, backendRoot),
  browser_root: portableRelative(runtimeRoot, browserInstallDir),
  chrome_devtools_mcp_runtime: portableRelative(runtimeRoot, chromeDevtoolsMcpRuntimeDir),
  chrome_devtools_mcp_version: chromeDevtoolsMcpVersion,
  veteran_runtime: portableRelative(runtimeRoot, veteranRuntimeDir)
}
fs.writeFileSync(path.join(runtimeRoot, 'runtime.json'), `${JSON.stringify(manifest, null, 2)}\n`, 'utf8')
console.log(`[zn-runtime] staged ${runtimeId} at ${runtimeRoot}`)
