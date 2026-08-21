import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { test } from 'vitest'

import { configureZnPackagedRuntime, resolveRuntime, resolveZnHome } from './zn-packaged-runtime'

function mkTmpRoot() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'zn-packaged-runtime-test-'))
}

function writeBundledRuntime(resourcesPath: string, runtimeId = 'abcdef1234567890') {
  const runtimeRoot = path.join(resourcesPath, 'zn-runtime')
  const pythonRelative = process.platform === 'win32' ? 'python/python.exe' : 'python/bin/python3'
  const backendRelative = 'python/site-packages'
  const python = path.join(runtimeRoot, ...pythonRelative.split('/'))
  const backendRoot = path.join(runtimeRoot, ...backendRelative.split('/'))

  fs.mkdirSync(path.dirname(python), { recursive: true })
  fs.writeFileSync(python, 'portable-python')
  fs.mkdirSync(path.join(backendRoot, 'hermes_cli'), { recursive: true })
  fs.mkdirSync(path.join(backendRoot, 'agent', 'kernel'), { recursive: true })
  fs.writeFileSync(path.join(backendRoot, 'hermes_cli', 'main.py'), '# backend\n')
  fs.writeFileSync(path.join(backendRoot, 'agent', 'kernel', 'resident_server.py'), '# resident\n')
  fs.writeFileSync(
    path.join(runtimeRoot, 'runtime.json'),
    `${JSON.stringify(
      {
        schema: 1,
        product: 'ZN',
        runtime_id: runtimeId,
        version: '0.1.0',
        commit: runtimeId,
        platform: process.platform,
        arch: process.arch,
        python: pythonRelative,
        backend_root: backendRelative
      },
      null,
      2
    )}\n`
  )

  return { runtimeRoot, runtimeId }
}

test('packaged runtime is materialized under ZN home and owns both backend and resident Python', () => {
  const root = mkTmpRoot()
  const resourcesPath = path.join(root, 'resources')
  const znHome = path.join(root, 'zn-home')
  const env: Record<string, string | undefined> = {}

  try {
    const { runtimeId } = writeBundledRuntime(resourcesPath)
    const runtime = configureZnPackagedRuntime({ resourcesPath, znHome, env })
    const expectedRoot = path.join(znHome, 'runtime', runtimeId)

    assert.equal(runtime.root, expectedRoot)
    assert.equal(env.ZN_AGENT_HOME, znHome)
    assert.equal(env.ZN_PACKAGED_RUNTIME_ROOT, expectedRoot)
    assert.equal(env.ZN_RESIDENT_PYTHON, runtime.python)
    assert.equal(env.HERMES_DESKTOP_PYTHON, runtime.python)
    assert.equal(env.HERMES_DESKTOP_HERMES_ROOT, runtime.backendRoot)
    assert.equal(env.PYTHONNOUSERSITE, '1')
    assert.equal(env.PYTHONUTF8, '1')
    assert.ok(runtime.python.startsWith(expectedRoot + path.sep))
    assert.ok(runtime.backendRoot.startsWith(expectedRoot + path.sep))

    fs.rmSync(path.join(resourcesPath, 'zn-runtime'), { recursive: true, force: true })
    const installed = resolveRuntime(expectedRoot, runtimeId)
    assert.equal(installed.python, runtime.python, 'installed runtime is self-contained after bundle removal')
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('packaged runtime rejects paths that escape the installer payload root', () => {
  const root = mkTmpRoot()
  const resourcesPath = path.join(root, 'resources')

  try {
    const { runtimeRoot } = writeBundledRuntime(resourcesPath)
    const manifestPath = path.join(runtimeRoot, 'runtime.json')
    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
    manifest.python = '../outside-python'
    fs.writeFileSync(manifestPath, `${JSON.stringify(manifest)}\n`)

    assert.throws(() => resolveRuntime(runtimeRoot), /escapes its payload root/)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('packaged runtime requires both desktop backend and resident entrypoints', () => {
  const root = mkTmpRoot()
  const resourcesPath = path.join(root, 'resources')

  try {
    const { runtimeRoot } = writeBundledRuntime(resourcesPath)
    const runtime = resolveRuntime(runtimeRoot)
    fs.rmSync(path.join(runtime.backendRoot, 'agent', 'kernel', 'resident_server.py'))

    assert.throws(() => resolveRuntime(runtimeRoot), /resident entrypoint is missing/)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('ZN home resolution honors explicit home before platform defaults', () => {
  const explicit = path.resolve('/tmp/zn-explicit-home')
  assert.equal(resolveZnHome({ ZN_AGENT_HOME: explicit }, 'linux', '/tmp/user'), explicit)
  assert.equal(resolveZnHome({}, 'linux', '/tmp/user'), path.join('/tmp/user', '.znagent'))
  assert.equal(
    resolveZnHome({ LOCALAPPDATA: 'C:\\Users\\ZN\\AppData\\Local' }, 'win32', 'C:\\Users\\ZN'),
    path.join('C:\\Users\\ZN\\AppData\\Local', 'znagent')
  )
})
