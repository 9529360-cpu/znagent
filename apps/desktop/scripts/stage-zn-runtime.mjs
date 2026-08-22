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
    .filter(entry => entry.isDirectory())
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

console.log('[zn-runtime] installing portable CPython 3.11')
run('uv', ['python', 'install', '3.11', '--install-dir', pythonInstallDir, '--no-bin'])
const pythonPath = findPortablePython(pythonInstallDir)
const stagedPythonInstallArgs = ['--python', pythonPath, '--break-system-packages']

console.log('[zn-runtime] installing ZN-owned Python distribution')
run('uv', ['pip', 'install', ...stagedPythonInstallArgs, runtimeProject])

const backendRoot = capture(pythonPath, [
  '-c',
  'import site; paths = site.getsitepackages(); print(paths[0])'
])
const residentEntry = path.join(backendRoot, 'zn_agent', 'resident.py')
const residentCore = path.join(backendRoot, 'zn_agent', 'core', 'resident_server.py')
if (!fs.existsSync(residentEntry)) throw new Error(`Installed runtime is missing zn_agent/resident.py under ${backendRoot}`)
if (!fs.existsSync(residentCore)) throw new Error(`Installed runtime is missing zn_agent/core/resident_server.py under ${backendRoot}`)
if (fs.existsSync(path.join(backendRoot, 'hermes_cli'))) {
  throw new Error(`ZN runtime unexpectedly contains hermes_cli under ${backendRoot}`)
}

console.log('[zn-runtime] running ZN zero-model smoke')
run(pythonPath, [
  '-I',
  '-c',
  [
    'import tempfile',
    'from pathlib import Path',
    'import zn_agent.resident',
    'from zn_agent.core.provider_bridge import build_resident_runtime',
    'd = tempfile.TemporaryDirectory()',
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
  backend_root: portableRelative(runtimeRoot, backendRoot)
}
fs.writeFileSync(path.join(runtimeRoot, 'runtime.json'), `${JSON.stringify(manifest, null, 2)}\n`, 'utf8')
console.log(`[zn-runtime] staged ${runtimeId} at ${runtimeRoot}`)
