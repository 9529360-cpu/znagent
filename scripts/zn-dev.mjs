#!/usr/bin/env node
import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const SCRIPT_PATH = fileURLToPath(import.meta.url)
const SCRIPT_DIR = path.dirname(SCRIPT_PATH)
const REPO_ROOT = path.resolve(SCRIPT_DIR, '..')
const DESKTOP_ROOT = path.join(REPO_ROOT, 'apps', 'desktop')
const RUNTIME_PROJECT = path.join(REPO_ROOT, 'runtime', 'python')
const PACKAGE_LOCK = path.join(REPO_ROOT, 'package-lock.json')
const VENV_ROOT = path.join(REPO_ROOT, '.venv')
const DEV_ROOT = path.join(REPO_ROOT, '.dev')
const NPM_STAMP = path.join(DEV_ROOT, 'npm-lock.sha256')
const PYTHON_STAMP = path.join(DEV_ROOT, 'python-runtime.sha256')
const PLAYWRIGHT_ROOT = path.join(DEV_ROOT, 'playwright-browsers')

const MIN_NODE = [22, 22, 0]
const MIN_PYTHON = [3, 11, 0]
const MAX_PYTHON_EXCLUSIVE = [3, 14, 0]

export function parseVersion(value) {
  const match = String(value || '').trim().match(/^(?:v)?(\d+)\.(\d+)\.(\d+)/)
  if (!match) return null
  return match.slice(1, 4).map(part => Number.parseInt(part, 10))
}

export function compareVersions(left, right) {
  for (let index = 0; index < Math.max(left.length, right.length); index += 1) {
    const delta = (left[index] || 0) - (right[index] || 0)
    if (delta !== 0) return Math.sign(delta)
  }
  return 0
}

export function isSupportedNodeVersion(value) {
  const version = parseVersion(value)
  return Boolean(version && compareVersions(version, MIN_NODE) >= 0)
}

export function isSupportedPythonVersion(value) {
  const version = parseVersion(value)
  return Boolean(
    version &&
    compareVersions(version, MIN_PYTHON) >= 0 &&
    compareVersions(version, MAX_PYTHON_EXCLUSIVE) < 0
  )
}

export function venvPythonPathFor(root, platform = process.platform) {
  return platform === 'win32'
    ? path.win32.join(root, 'Scripts', 'python.exe')
    : path.posix.join(root, 'bin', 'python')
}

export function resolveDevHome(repoRoot, env = process.env) {
  const explicit = String(env.ZN_DEV_AGENT_HOME || '').trim()
  return explicit ? path.resolve(explicit) : path.join(repoRoot, '.dev', 'zn-home')
}

export function resolveDevUserData(repoRoot, env = process.env) {
  const explicit = String(env.ZN_DEV_USER_DATA || '').trim()
  return explicit ? path.resolve(explicit) : path.join(repoRoot, '.dev', 'electron-user-data')
}

export function pythonCandidatesFor(platform = process.platform, env = process.env) {
  const explicit = String(env.ZN_DEV_PYTHON || '').trim()
  const candidates = []
  if (explicit) candidates.push({ command: explicit, argsPrefix: [], source: 'ZN_DEV_PYTHON' })
  if (platform === 'win32') {
    candidates.push(
      { command: 'py', argsPrefix: ['-3.12'], source: 'py -3.12' },
      { command: 'py', argsPrefix: ['-3.13'], source: 'py -3.13' },
      { command: 'py', argsPrefix: ['-3.11'], source: 'py -3.11' },
      { command: 'python', argsPrefix: [], source: 'python' },
      { command: 'python3', argsPrefix: [], source: 'python3' }
    )
  } else {
    candidates.push(
      { command: 'python3.12', argsPrefix: [], source: 'python3.12' },
      { command: 'python3.13', argsPrefix: [], source: 'python3.13' },
      { command: 'python3.11', argsPrefix: [], source: 'python3.11' },
      { command: 'python3', argsPrefix: [], source: 'python3' },
      { command: 'python', argsPrefix: [], source: 'python' }
    )
  }
  const seen = new Set()
  return candidates.filter(candidate => {
    const key = `${candidate.command}\u0000${candidate.argsPrefix.join('\u0000')}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export function npmInvocation(args, env = process.env, platform = process.platform) {
  const npmExecPath = String(env.npm_execpath || '').trim()
  if (npmExecPath && fs.existsSync(npmExecPath)) {
    return { command: process.execPath, args: [npmExecPath, ...args], shell: false }
  }
  return {
    command: platform === 'win32' ? 'npm.cmd' : 'npm',
    args,
    shell: platform === 'win32'
  }
}

function sha256File(filePath) {
  return createHash('sha256').update(fs.readFileSync(filePath)).digest('hex')
}

function sha256Files(filePaths) {
  const hash = createHash('sha256')
  for (const filePath of filePaths) {
    hash.update(path.relative(REPO_ROOT, filePath).replaceAll(path.sep, '/'))
    hash.update('\u0000')
    hash.update(fs.readFileSync(filePath))
    hash.update('\u0000')
  }
  return hash.digest('hex')
}

function readTextIfExists(filePath) {
  try {
    return fs.readFileSync(filePath, 'utf8').trim()
  } catch {
    return ''
  }
}

function writeText(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  fs.writeFileSync(filePath, `${value}\n`, 'utf8')
}

function run(command, args, options = {}) {
  const printable = [command, ...args].join(' ')
  console.log(`[zn-dev] ${printable}`)
  const result = spawnSync(command, args, {
    cwd: REPO_ROOT,
    env: process.env,
    stdio: 'inherit',
    ...options
  })
  if (result.error) throw result.error
  if (result.status !== 0) {
    throw new Error(`Command failed with exit code ${result.status ?? 'unknown'}: ${printable}`)
  }
}

function capture(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: REPO_ROOT,
    env: process.env,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    ...options
  })
  if (result.error || result.status !== 0) return null
  return String(result.stdout || '').trim()
}

function assertNodeVersion() {
  if (!isSupportedNodeVersion(process.version)) {
    throw new Error(`Node ${process.version} is unsupported. Install Node >=22.22.0, then rerun npm run dev.`)
  }
}

function probeNodeRuntime() {
  if (!fs.existsSync(path.join(REPO_ROOT, 'node_modules'))) return false
  const probe = spawnSync(process.execPath, ['-e', [
    "const electron = require('electron')",
    "if (!electron) process.exit(2)",
    "require('esbuild').transformSync('const x = 1')"
  ].join(';')], {
    cwd: REPO_ROOT,
    env: process.env,
    stdio: 'ignore'
  })
  return !probe.error && probe.status === 0
}

function ensureNodeDependencies() {
  const lockHash = sha256File(PACKAGE_LOCK)
  const stampedHash = readTextIfExists(NPM_STAMP)
  let installRequired = stampedHash !== lockHash || !fs.existsSync(path.join(REPO_ROOT, 'node_modules'))
  if (!installRequired) {
    const npm = npmInvocation(['ls', '--depth=0', '--workspaces', '--include-workspace-root'])
    const listing = spawnSync(npm.command, npm.args, {
      cwd: REPO_ROOT,
      env: process.env,
      shell: npm.shell,
      stdio: 'ignore'
    })
    installRequired = Boolean(listing.error || listing.status !== 0)
  }

  if (installRequired) {
    console.log('[zn-dev] installing locked Node workspace dependencies')
    const npm = npmInvocation(['ci'])
    run(npm.command, npm.args, { shell: npm.shell })
  }

  if (!probeNodeRuntime()) {
    console.log('[zn-dev] Electron/esbuild lifecycle artifacts are missing; repairing ignored install scripts')
    const npm = npmInvocation(['rebuild', 'electron', 'esbuild'])
    run(npm.command, npm.args, { shell: npm.shell })
  }

  if (!probeNodeRuntime()) {
    throw new Error('Electron/esbuild are still unusable after repair. Remove node_modules and rerun npm run setup.')
  }
  writeText(NPM_STAMP, lockHash)
}

function inspectPython(candidate) {
  const raw = capture(candidate.command, [
    ...candidate.argsPrefix,
    '-c',
    "import platform,sys; print(platform.python_version()); print(sys.executable)"
  ])
  if (!raw) return null
  const [version = '', executable = ''] = raw.split(/\r?\n/)
  if (!isSupportedPythonVersion(version)) return null
  return { ...candidate, version, executable: executable.trim() }
}

function findBasePython() {
  for (const candidate of pythonCandidatesFor()) {
    const inspected = inspectPython(candidate)
    if (inspected) return inspected
  }
  throw new Error(
    'No supported Python found. Install Python 3.12 (supported: >=3.11,<3.14) or set ZN_DEV_PYTHON to a Python executable.'
  )
}

function venvPythonPath() {
  return venvPythonPathFor(VENV_ROOT, process.platform)
}

function ensureVenv() {
  let pythonPath = venvPythonPath()
  if (!fs.existsSync(pythonPath)) {
    const base = findBasePython()
    console.log(`[zn-dev] creating .venv with Python ${base.version} (${base.source})`)
    run(base.command, [...base.argsPrefix, '-m', 'venv', VENV_ROOT])
  }
  pythonPath = venvPythonPath()
  const version = capture(pythonPath, ['-c', 'import platform; print(platform.python_version())'])
  if (!version || !isSupportedPythonVersion(version)) {
    throw new Error(`.venv uses unsupported Python ${version || 'unknown'}. Remove .venv and rerun npm run setup.`)
  }
  return { pythonPath, version }
}

function ensurePythonRuntime() {
  const { pythonPath, version } = ensureVenv()
  const runtimeHash = sha256Files([path.join(RUNTIME_PROJECT, 'pyproject.toml')])
  const stampedHash = readTextIfExists(PYTHON_STAMP)
  const residentReady = capture(pythonPath, [
    '-c',
    "import importlib.util; import sys; sys.exit(0 if importlib.util.find_spec('zn_agent.resident') else 1)"
  ]) !== null
  const playwrightReady = capture(pythonPath, [
    '-c',
    "import importlib.util; import sys; sys.exit(0 if importlib.util.find_spec('playwright') else 1)"
  ]) !== null
  const browserReady = fs.existsSync(PLAYWRIGHT_ROOT) && fs.readdirSync(PLAYWRIGHT_ROOT).length > 0
  const installRequired = stampedHash !== runtimeHash || !residentReady || !playwrightReady || !browserReady

  if (installRequired) {
    console.log('[zn-dev] installing ZN Python runtime with managed-browser support')
    run(pythonPath, ['-m', 'pip', 'install', '--disable-pip-version-check', '-e', `${RUNTIME_PROJECT}[browser]`])
    console.log('[zn-dev] installing the version-bound Playwright Chromium runtime')
    fs.mkdirSync(PLAYWRIGHT_ROOT, { recursive: true })
    run(pythonPath, ['-m', 'playwright', 'install', 'chromium'], {
      env: { ...process.env, PLAYWRIGHT_BROWSERS_PATH: PLAYWRIGHT_ROOT }
    })
    writeText(PYTHON_STAMP, runtimeHash)
  }

  const smoke = spawnSync(pythonPath, ['-I', '-c', [
    'import zn_agent.resident',
    'from zn_agent.core.browser_resident_server import main as formal_resident_main',
    'assert zn_agent.resident.main is formal_resident_main'
  ].join(';')], {
    cwd: REPO_ROOT,
    env: process.env,
    stdio: 'ignore'
  })
  if (smoke.error || smoke.status !== 0) {
    throw new Error('ZN Python runtime import smoke failed after setup.')
  }
  return { pythonPath, version }
}

function checkDoctorItem(label, ok, detail, remediation = '') {
  const mark = ok ? 'OK' : 'FAIL'
  console.log(`[${mark}] ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok && remediation) console.log(`       ${remediation}`)
  return ok
}

function doctor() {
  let ok = true
  ok = checkDoctorItem(
    'Node',
    isSupportedNodeVersion(process.version),
    process.version,
    'Install Node >=22.22.0.'
  ) && ok

  const lockHash = fs.existsSync(PACKAGE_LOCK) ? sha256File(PACKAGE_LOCK) : ''
  const npmReady = Boolean(lockHash) && readTextIfExists(NPM_STAMP) === lockHash
  const nodeRuntimeReady = npmReady && probeNodeRuntime()
  ok = checkDoctorItem(
    'Node dependencies',
    nodeRuntimeReady,
    nodeRuntimeReady ? 'locked install and Electron/esbuild are ready' : 'setup missing or stale',
    'Run npm run setup.'
  ) && ok

  const pythonPath = venvPythonPath()
  const pythonVersion = fs.existsSync(pythonPath)
    ? capture(pythonPath, ['-c', 'import platform; print(platform.python_version())'])
    : null
  const pythonReady = Boolean(pythonVersion && isSupportedPythonVersion(pythonVersion))
  ok = checkDoctorItem(
    'Python virtual environment',
    pythonReady,
    pythonReady ? `${pythonVersion} at ${pythonPath}` : '.venv is missing or unsupported',
    'Run npm run setup. Python 3.12 is recommended.'
  ) && ok

  let residentReady = false
  let playwrightReady = false
  if (pythonReady) {
    residentReady = capture(pythonPath, ['-c', "import zn_agent.resident; print('ready')"]) === 'ready'
    playwrightReady = capture(pythonPath, ['-c', "import playwright; print('ready')"]) === 'ready'
  }
  ok = checkDoctorItem(
    'ZN Resident package',
    residentReady,
    residentReady ? 'importable from .venv' : 'not importable',
    'Run npm run setup.'
  ) && ok
  ok = checkDoctorItem(
    'Managed browser runtime',
    playwrightReady && fs.existsSync(PLAYWRIGHT_ROOT) && fs.readdirSync(PLAYWRIGHT_ROOT).length > 0,
    playwrightReady ? PLAYWRIGHT_ROOT : 'Playwright/browser payload missing',
    'Run npm run setup.'
  ) && ok

  console.log(`[INFO] Source-development ZN home — ${resolveDevHome(REPO_ROOT)}`)
  console.log(`[INFO] Source-development Electron profile — ${resolveDevUserData(REPO_ROOT)}`)
  console.log('[INFO] Product acceptance target — Windows x64')
  return ok ? 0 : 1
}

function setup() {
  assertNodeVersion()
  fs.mkdirSync(DEV_ROOT, { recursive: true })
  ensureNodeDependencies()
  const python = ensurePythonRuntime()
  const devHome = resolveDevHome(REPO_ROOT)
  const userData = resolveDevUserData(REPO_ROOT)
  fs.mkdirSync(devHome, { recursive: true })
  fs.mkdirSync(userData, { recursive: true })
  console.log(`[zn-dev] ready: Python ${python.version}`)
  console.log(`[zn-dev] isolated Resident home: ${devHome}`)
  console.log(`[zn-dev] isolated Electron profile: ${userData}`)
  return { ...python, devHome, userData }
}

async function runDev() {
  const runtime = setup()
  const npm = npmInvocation(['run', 'bundle:dev', '--workspace', 'apps/desktop'])
  run(npm.command, npm.args, { shell: npm.shell })
  const electronCli = path.join(REPO_ROOT, 'node_modules', 'electron', 'cli.js')
  if (!fs.existsSync(electronCli)) throw new Error(`Electron CLI is missing: ${electronCli}`)
  const env = {
    ...process.env,
    ZN_DESKTOP_DEV: '1',
    ZN_DESKTOP_USER_DATA: runtime.userData,
    ZN_DESKTOP_UPDATE_CHANNEL_URL: '',
    ZN_RESIDENT_PYTHON: runtime.pythonPath,
    ZN_AGENT_HOME: runtime.devHome,
    PLAYWRIGHT_BROWSERS_PATH: PLAYWRIGHT_ROOT
  }
  console.log('[zn-dev] launching isolated ZN Desktop source instance')
  await new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [electronCli, DESKTOP_ROOT], {
      cwd: REPO_ROOT,
      env,
      stdio: 'inherit'
    })
    child.once('error', reject)
    child.once('exit', (code, signal) => {
      if (signal) reject(new Error(`ZN Desktop exited from signal ${signal}`))
      else if (code === 0) resolve()
      else reject(new Error(`ZN Desktop exited with code ${code ?? 'unknown'}`))
    })
  })
}

async function main(argv = process.argv.slice(2)) {
  const command = argv[0] || 'dev'
  if (command === 'doctor') {
    process.exitCode = doctor()
    return
  }
  if (command === 'setup') {
    setup()
    return
  }
  if (command === 'dev') {
    await runDev()
    return
  }
  throw new Error(`Unknown zn-dev command: ${command}. Use setup, doctor, or dev.`)
}

const invokedDirectly = process.argv[1] && path.resolve(process.argv[1]) === path.resolve(SCRIPT_PATH)
if (invokedDirectly) {
  main().catch(error => {
    const message = error instanceof Error ? error.message : String(error)
    console.error(`[zn-dev] ${message}`)
    process.exitCode = 1
  })
}
