import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { test } from 'vitest'

import { configureZnPackagedRuntime, resolveRuntime, resolveZnHome } from './zn-packaged-runtime'

const desktopRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const retiredProduct = Buffer.from('6865726d6573', 'hex').toString('utf8')
const retiredPackage = Buffer.from('6865726d65735f636c69', 'hex').toString('utf8')
const retiredOrg = Buffer.from('6e6f75737265736561726368', 'hex').toString('utf8')
const retiredBrand = Buffer.from('4e6f7573205265736561726368', 'hex').toString('utf8')

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
  fs.mkdirSync(path.join(backendRoot, 'zn_agent', 'core'), { recursive: true })
  fs.writeFileSync(path.join(backendRoot, 'zn_agent', 'resident.py'), '# resident package entry\n')
  fs.writeFileSync(path.join(backendRoot, 'zn_agent', 'core', 'resident_server.py'), '# resident core\n')
  fs.writeFileSync(path.join(runtimeRoot, 'runtime.json'), `${JSON.stringify({
    schema: 1,
    product: 'ZN',
    runtime_id: runtimeId,
    version: '0.1.0',
    commit: runtimeId,
    platform: process.platform,
    arch: process.arch,
    python: pythonRelative,
    backend_root: backendRelative
  }, null, 2)}\n`)
  return { runtimeRoot, runtimeId, backendRoot }
}

test('packaged runtime materializes under ZN home and uses only ZN runtime entrypoints', () => {
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
    assert.equal(env.ZN_RESIDENT_PYTHON, runtime.python)
    assert.equal(env[`${retiredProduct.toUpperCase()}_DESKTOP_PYTHON`], undefined)
    assert.equal(env[`${retiredProduct.toUpperCase()}_DESKTOP_${retiredProduct.toUpperCase()}_ROOT`], undefined)
    fs.rmSync(path.join(resourcesPath, 'zn-runtime'), { recursive: true, force: true })
    assert.equal(resolveRuntime(expectedRoot, runtimeId).python, runtime.python)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('packaged N+1 materializes beside N without replacing the active runtime', () => {
  const root = mkTmpRoot()
  const resourcesPath = path.join(root, 'resources')
  const znHome = path.join(root, 'zn-home')
  const env: Record<string, string | undefined> = {}
  try {
    writeBundledRuntime(resourcesPath, 'runtime-n')
    const current = configureZnPackagedRuntime({ resourcesPath, znHome, env })
    const currentMarker = path.join(current.root, 'active-runtime-marker')
    fs.writeFileSync(currentMarker, 'resident-n-is-still-using-this-runtime')

    fs.rmSync(path.join(resourcesPath, 'zn-runtime'), { recursive: true, force: true })
    writeBundledRuntime(resourcesPath, 'runtime-n-plus-1')
    const desired = configureZnPackagedRuntime({ resourcesPath, znHome, env })

    assert.equal(current.root, path.join(znHome, 'runtime', 'runtime-n'))
    assert.equal(desired.root, path.join(znHome, 'runtime', 'runtime-n-plus-1'))
    assert.notEqual(desired.root, current.root)
    assert.equal(fs.readFileSync(currentMarker, 'utf8'), 'resident-n-is-still-using-this-runtime')
    assert.equal(resolveRuntime(current.root, 'runtime-n').manifest.runtime_id, 'runtime-n')
    assert.equal(resolveRuntime(desired.root, 'runtime-n-plus-1').manifest.runtime_id, 'runtime-n-plus-1')
    assert.equal(env.ZN_AGENT_HOME, znHome)
    assert.equal(env.ZN_RUNTIME_ID, 'runtime-n-plus-1')
    assert.equal(env.ZN_RESIDENT_PYTHON, desired.python)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('packaged runtime rejects retired package content', () => {
  const root = mkTmpRoot()
  const resourcesPath = path.join(root, 'resources')
  try {
    const { runtimeRoot, backendRoot } = writeBundledRuntime(resourcesPath)
    fs.mkdirSync(path.join(backendRoot, retiredPackage), { recursive: true })
    fs.writeFileSync(path.join(backendRoot, retiredPackage, 'main.py'), '# forbidden\n')
    assert.throws(() => resolveRuntime(runtimeRoot), /forbidden retired package/)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('packaged runtime rejects paths escaping payload root', () => {
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

test('packaged runtime requires the ZN resident core entrypoint', () => {
  const root = mkTmpRoot()
  const resourcesPath = path.join(root, 'resources')
  try {
    const { runtimeRoot, backendRoot } = writeBundledRuntime(resourcesPath)
    fs.rmSync(path.join(backendRoot, 'zn_agent', 'core', 'resident_server.py'))
    assert.throws(() => resolveRuntime(runtimeRoot), /resident core entrypoint is missing/)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('ZN home resolution honors explicit home before platform defaults', () => {
  const explicit = path.resolve('/tmp/zn-explicit-home')
  assert.equal(resolveZnHome({ ZN_AGENT_HOME: explicit }, 'linux', '/tmp/user'), explicit)
  assert.equal(resolveZnHome({}, 'linux', '/tmp/user'), path.join('/tmp/user', '.znagent'))
})

test('formal desktop package and builder expose only ZN product identity', () => {
  const packageJson = JSON.parse(fs.readFileSync(path.join(desktopRoot, 'package.json'), 'utf8'))
  const builder = fs.readFileSync(path.join(desktopRoot, 'electron-builder.zn.yml'), 'utf8')

  assert.equal(packageJson.name, 'zn-desktop')
  assert.equal(packageJson.productName, 'ZN')
  assert.equal(packageJson.repository?.url, 'git+https://github.com/9529360-cpu/znagent.git')
  assert.equal(packageJson.build, undefined)
  assert.doesNotMatch(packageJson.scripts?.build || '', /write-build-stamp/)
  assert.match(packageJson.scripts?.builder || '', /--config electron-builder\.zn\.yml/)

  assert.match(builder, /^appId: ai\.zn\.desktop$/m)
  assert.match(builder, /^productName: ZN$/m)
  assert.match(builder, /^executableName: ZN$/m)
  assert.match(builder, /^artifactName: ZN-/m)
  assert.match(builder, /^\s+- zn$/m)
  assert.match(builder, /from: build\/zn-runtime/)
  assert.match(builder, /^\s+legalTrademarks: ZN$/m)
  assert.doesNotMatch(builder, new RegExp(`${retiredProduct}|install-stamp|beforePack|afterPack`, 'i'))

  const publicIdentity = `${JSON.stringify({
    name: packageJson.name,
    productName: packageJson.productName,
    description: packageJson.description,
    author: packageJson.author,
    repository: packageJson.repository
  })}\n${builder}`
  assert.doesNotMatch(publicIdentity, new RegExp(`${retiredProduct}|${retiredOrg}`, 'i'))

  for (const retiredHook of [
    'scripts/before-pack.mjs',
    'scripts/after-pack.mjs',
    'scripts/set-exe-identity.mjs',
    'scripts/stage-native-deps.mjs'
  ]) {
    assert.equal(fs.existsSync(path.join(desktopRoot, retiredHook)), false)
  }

  const activeHooks = [
    'scripts/before-build.mjs',
    'scripts/notarize.mjs'
  ].map(relative => fs.readFileSync(path.join(desktopRoot, relative), 'utf8')).join('\n')
  assert.doesNotMatch(activeHooks, new RegExp(`${retiredProduct}|${retiredBrand}|install\\.ps1|${retiredPackage}`, 'i'))
})
