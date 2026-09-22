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
  const browserRelative = 'playwright-browsers'
  const browserExecutableRelative = 'playwright-browsers/chromium-fixture/chrome.exe'
  const veteranRelative = 'veteran-engineer'
  const chromeMcpRelative = 'browser-runtimes/chrome-devtools-mcp'
  const python = path.join(runtimeRoot, ...pythonRelative.split('/'))
  const backendRoot = path.join(runtimeRoot, ...backendRelative.split('/'))
  const browserRoot = path.join(runtimeRoot, browserRelative)
  const browserExecutable = path.join(runtimeRoot, ...browserExecutableRelative.split('/'))
  const veteranRuntimeRoot = path.join(runtimeRoot, veteranRelative)
  const chromeDevtoolsMcpRuntimeRoot = path.join(runtimeRoot, ...chromeMcpRelative.split('/'))
  const chromeDevtoolsMcpPackageRoot = path.join(
    chromeDevtoolsMcpRuntimeRoot,
    'node_modules',
    'chrome-devtools-mcp'
  )
  fs.mkdirSync(path.dirname(python), { recursive: true })
  fs.writeFileSync(python, 'portable-python')
  fs.mkdirSync(path.join(backendRoot, 'zn_agent', 'core'), { recursive: true })
  fs.writeFileSync(path.join(backendRoot, 'zn_agent', 'resident.py'), '# resident package entry\n')
  fs.writeFileSync(path.join(backendRoot, 'zn_agent', 'core', 'resident_server.py'), '# resident core\n')
  fs.mkdirSync(path.join(browserRoot, 'chromium-fixture'), { recursive: true })
  fs.writeFileSync(path.join(browserRoot, 'chromium-fixture', 'marker'), 'managed chromium')
  fs.writeFileSync(browserExecutable, 'fake chromium executable')
  fs.mkdirSync(path.join(veteranRuntimeRoot, 'mcp'), { recursive: true })
  fs.writeFileSync(path.join(veteranRuntimeRoot, 'mcp', 'server.mjs'), '// veteran fixture\n')
  fs.writeFileSync(path.join(veteranRuntimeRoot, 'VENDOR.json'), '{}\n')
  fs.mkdirSync(path.join(chromeDevtoolsMcpPackageRoot, 'build', 'src', 'bin'), { recursive: true })
  fs.writeFileSync(
    path.join(chromeDevtoolsMcpPackageRoot, 'build', 'src', 'bin', 'chrome-devtools-mcp.js'),
    '// chrome devtools mcp fixture\n'
  )
  fs.writeFileSync(
    path.join(chromeDevtoolsMcpPackageRoot, 'package.json'),
    JSON.stringify({ name: 'chrome-devtools-mcp', version: '1.9.0' })
  )
  fs.writeFileSync(path.join(runtimeRoot, 'runtime.json'), `${JSON.stringify({
    schema: 1,
    product: 'ZN',
    runtime_id: runtimeId,
    version: '0.1.0',
    commit: runtimeId,
    platform: process.platform,
    arch: process.arch,
    python: pythonRelative,
    backend_root: backendRelative,
    browser_root: browserRelative,
    browser_executable: browserExecutableRelative,
    veteran_runtime: veteranRelative,
    chrome_devtools_mcp_runtime: chromeMcpRelative,
    chrome_devtools_mcp_version: '1.9.0'
  }, null, 2)}\n`)
  return {
    runtimeRoot,
    runtimeId,
    backendRoot,
    browserRoot,
    browserExecutable,
    veteranRuntimeRoot,
    chromeDevtoolsMcpRuntimeRoot
  }
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
    assert.equal(runtime.browserRoot, path.join(expectedRoot, 'playwright-browsers'))
    assert.equal(env.PLAYWRIGHT_BROWSERS_PATH, runtime.browserRoot)
    assert.equal(
      runtime.browserExecutable,
      path.join(expectedRoot, 'playwright-browsers', 'chromium-fixture', 'chrome.exe')
    )
    assert.equal(env.ZN_BROWSER_EXECUTABLE, runtime.browserExecutable)
    assert.equal(runtime.veteranRuntimeRoot, path.join(expectedRoot, 'veteran-engineer'))
    assert.equal(env.ZN_VETERAN_RUNTIME_ROOT, runtime.veteranRuntimeRoot)
    assert.equal(
      runtime.chromeDevtoolsMcpRuntimeRoot,
      path.join(expectedRoot, 'browser-runtimes', 'chrome-devtools-mcp')
    )
    assert.equal(
      env.ZN_CHROME_DEVTOOLS_MCP_ROOT,
      runtime.chromeDevtoolsMcpRuntimeRoot
    )
    assert.equal(env.ZN_DESKTOP_EXECUTABLE, path.resolve(process.execPath))
    assert.equal(env[`${retiredProduct.toUpperCase()}_DESKTOP_PYTHON`], undefined)
    assert.equal(env[`${retiredProduct.toUpperCase()}_DESKTOP_${retiredProduct.toUpperCase()}_ROOT`], undefined)
    fs.rmSync(path.join(resourcesPath, 'zn-runtime'), { recursive: true, force: true })
    assert.equal(resolveRuntime(expectedRoot, runtimeId).python, runtime.python)
    assert.equal(resolveRuntime(expectedRoot, runtimeId).browserRoot, runtime.browserRoot)
    assert.equal(resolveRuntime(expectedRoot, runtimeId).browserExecutable, runtime.browserExecutable)
    assert.equal(
      resolveRuntime(expectedRoot, runtimeId).chromeDevtoolsMcpRuntimeRoot,
      runtime.chromeDevtoolsMcpRuntimeRoot
    )
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('packaged N+1 materializes beside N with its own managed browser root', () => {
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
    assert.equal(current.browserRoot, path.join(current.root, 'playwright-browsers'))
    assert.equal(desired.browserRoot, path.join(desired.root, 'playwright-browsers'))
    assert.notEqual(desired.browserRoot, current.browserRoot)
    assert.notEqual(desired.browserExecutable, current.browserExecutable)
    assert.equal(
      current.chromeDevtoolsMcpRuntimeRoot,
      path.join(current.root, 'browser-runtimes', 'chrome-devtools-mcp')
    )
    assert.equal(
      desired.chromeDevtoolsMcpRuntimeRoot,
      path.join(desired.root, 'browser-runtimes', 'chrome-devtools-mcp')
    )
    assert.notEqual(
      desired.chromeDevtoolsMcpRuntimeRoot,
      current.chromeDevtoolsMcpRuntimeRoot
    )
    assert.equal(env.ZN_AGENT_HOME, znHome)
    assert.equal(env.ZN_RUNTIME_ID, 'runtime-n-plus-1')
    assert.equal(env.ZN_RESIDENT_PYTHON, desired.python)
    assert.equal(env.PLAYWRIGHT_BROWSERS_PATH, desired.browserRoot)
    assert.equal(env.ZN_BROWSER_EXECUTABLE, desired.browserExecutable)
    assert.equal(
      env.ZN_CHROME_DEVTOOLS_MCP_ROOT,
      desired.chromeDevtoolsMcpRuntimeRoot
    )
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('packaged runtime without browser manifest clears inherited Playwright cache authority', () => {
  const root = mkTmpRoot()
  const resourcesPath = path.join(root, 'resources')
  const znHome = path.join(root, 'zn-home')
  const env: Record<string, string | undefined> = {
    PLAYWRIGHT_BROWSERS_PATH: 'machine-global-cache',
    ZN_BROWSER_EXECUTABLE: 'machine-global-browser'
  }
  try {
    const { runtimeRoot } = writeBundledRuntime(resourcesPath)
    const manifestPath = path.join(runtimeRoot, 'runtime.json')
    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
    delete manifest.browser_root
    delete manifest.browser_executable
    fs.writeFileSync(manifestPath, `${JSON.stringify(manifest)}\n`)
    const runtime = configureZnPackagedRuntime({ resourcesPath, znHome, env })
    assert.equal(runtime.browserRoot, undefined)
    assert.equal(runtime.browserExecutable, undefined)
    assert.equal(env.PLAYWRIGHT_BROWSERS_PATH, undefined)
    assert.equal(env.ZN_BROWSER_EXECUTABLE, undefined)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('packaged runtime clears inherited Chrome MCP authority when manifest omits the pair', () => {
  const root = mkTmpRoot()
  const resourcesPath = path.join(root, 'resources')
  const znHome = path.join(root, 'zn-home')
  const env: Record<string, string | undefined> = {
    ZN_CHROME_DEVTOOLS_MCP_ROOT: 'machine-global-chrome-mcp'
  }
  try {
    const { runtimeRoot } = writeBundledRuntime(resourcesPath)
    const manifestPath = path.join(runtimeRoot, 'runtime.json')
    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
    delete manifest.chrome_devtools_mcp_runtime
    delete manifest.chrome_devtools_mcp_version
    fs.writeFileSync(manifestPath, `${JSON.stringify(manifest)}\n`)
    const runtime = configureZnPackagedRuntime({ resourcesPath, znHome, env })
    assert.equal(runtime.chromeDevtoolsMcpRuntimeRoot, undefined)
    assert.equal(env.ZN_CHROME_DEVTOOLS_MCP_ROOT, undefined)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('packaged runtime rejects Chrome MCP root escaping payload root', () => {
  const root = mkTmpRoot()
  const resourcesPath = path.join(root, 'resources')
  try {
    const { runtimeRoot } = writeBundledRuntime(resourcesPath)
    const manifestPath = path.join(runtimeRoot, 'runtime.json')
    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
    manifest.chrome_devtools_mcp_runtime = '../machine-chrome-mcp'
    fs.writeFileSync(manifestPath, `${JSON.stringify(manifest)}\n`)
    assert.throws(
      () => resolveRuntime(runtimeRoot),
      /chrome_devtools_mcp_runtime escapes its payload root/
    )
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('packaged runtime rejects missing or wrong-version Chrome MCP runtime', () => {
  const root = mkTmpRoot()
  const resourcesPath = path.join(root, 'resources')
  try {
    const fixture = writeBundledRuntime(resourcesPath)
    const server = path.join(
      fixture.chromeDevtoolsMcpRuntimeRoot,
      'node_modules',
      'chrome-devtools-mcp',
      'build',
      'src',
      'bin',
      'chrome-devtools-mcp.js'
    )
    fs.rmSync(server)
    assert.throws(() => resolveRuntime(fixture.runtimeRoot), /Chrome DevTools MCP server is missing/)

    fs.mkdirSync(path.dirname(server), { recursive: true })
    fs.writeFileSync(server, '// restored\n')
    const packagePath = path.join(
      fixture.chromeDevtoolsMcpRuntimeRoot,
      'node_modules',
      'chrome-devtools-mcp',
      'package.json'
    )
    fs.writeFileSync(
      packagePath,
      JSON.stringify({ name: 'chrome-devtools-mcp', version: '9.9.9' })
    )
    assert.throws(() => resolveRuntime(fixture.runtimeRoot), /version mismatch/)
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

test('packaged runtime rejects browser root escaping payload root', () => {
  const root = mkTmpRoot()
  const resourcesPath = path.join(root, 'resources')
  try {
    const { runtimeRoot } = writeBundledRuntime(resourcesPath)
    const manifestPath = path.join(runtimeRoot, 'runtime.json')
    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
    manifest.browser_root = '../machine-browser-cache'
    fs.writeFileSync(manifestPath, `${JSON.stringify(manifest)}\n`)
    assert.throws(() => resolveRuntime(runtimeRoot), /browser_root escapes its payload root/)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('packaged runtime rejects Veteran runtime escaping payload root', () => {
  const root = mkTmpRoot()
  const resourcesPath = path.join(root, 'resources')
  try {
    const { runtimeRoot } = writeBundledRuntime(resourcesPath)
    const manifestPath = path.join(runtimeRoot, 'runtime.json')
    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
    manifest.veteran_runtime = '../outside-veteran'
    fs.writeFileSync(manifestPath, `${JSON.stringify(manifest)}\n`)
    assert.throws(() => resolveRuntime(runtimeRoot), /veteran_runtime escapes its payload root/)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('packaged runtime requires declared Veteran MCP server', () => {
  const root = mkTmpRoot()
  const resourcesPath = path.join(root, 'resources')
  try {
    const { runtimeRoot, veteranRuntimeRoot } = writeBundledRuntime(resourcesPath)
    fs.rmSync(path.join(veteranRuntimeRoot, 'mcp', 'server.mjs'))
    assert.throws(() => resolveRuntime(runtimeRoot), /Veteran MCP server is missing/)
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
  assert.equal(packageJson.repository, undefined)
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
