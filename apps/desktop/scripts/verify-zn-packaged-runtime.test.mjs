import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import {
  findPackagedZnRuntimeRoots,
  smokePackagedZnRuntime,
  verifyPackagedZnRelease
} from './verify-zn-packaged-runtime.mjs'

const retiredPackage = Buffer.from('6865726d65735f636c69', 'hex').toString('utf8')

async function writeFakePackagedRuntime(root, { version = '1.2.3', commit = 'a'.repeat(40) } = {}) {
  const runtimeRoot = path.join(root, 'release', 'linux-unpacked', 'resources', 'zn-runtime')
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
  await fs.mkdir(path.dirname(python), { recursive: true })
  await fs.writeFile(python, 'fake-python')
  if (process.platform !== 'win32') await fs.chmod(python, 0o755)
  await fs.mkdir(path.join(backendRoot, 'zn_agent', 'core'), { recursive: true })
  await fs.writeFile(path.join(backendRoot, 'zn_agent', 'resident.py'), '# resident package entry\n')
  await fs.writeFile(path.join(backendRoot, 'zn_agent', 'core', 'resident_server.py'), '# resident core\n')
  await fs.mkdir(path.join(browserRoot, 'chromium-fixture'), { recursive: true })
  await fs.writeFile(path.join(browserRoot, 'chromium-fixture', 'marker'), 'managed chromium')
  await fs.writeFile(browserExecutable, 'fake chromium executable')
  await fs.mkdir(path.join(veteranRuntimeRoot, 'mcp'), { recursive: true })
  await fs.writeFile(path.join(veteranRuntimeRoot, 'mcp', 'server.mjs'), '// veteran fixture\n')
  await fs.writeFile(path.join(veteranRuntimeRoot, 'VENDOR.json'), '{}\n')
  await fs.mkdir(path.join(chromeDevtoolsMcpPackageRoot, 'build', 'src', 'bin'), { recursive: true })
  await fs.writeFile(
    path.join(chromeDevtoolsMcpPackageRoot, 'build', 'src', 'bin', 'chrome-devtools-mcp.js'),
    '// chrome devtools mcp fixture\n'
  )
  await fs.writeFile(
    path.join(chromeDevtoolsMcpPackageRoot, 'package.json'),
    JSON.stringify({ name: 'chrome-devtools-mcp', version: '1.9.0' })
  )
  await fs.writeFile(path.join(runtimeRoot, 'runtime.json'), `${JSON.stringify({
    schema: 1,
    product: 'ZN',
    runtime_id: commit,
    version,
    commit,
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
    releaseDir: path.join(root, 'release'),
    runtimeRoot,
    python,
    backendRoot,
    browserRoot,
    browserExecutable,
    veteranRuntimeRoot,
    chromeDevtoolsMcpRuntimeRoot
  }
}

test('packaged release verifier validates ZN runtime and version-bound managed browser root', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zn-packaged-release-'))
  try {
    const fixture = await writeFakePackagedRuntime(root)
    assert.deepEqual(await findPackagedZnRuntimeRoots(fixture.releaseDir), [fixture.runtimeRoot])
    const verified = await verifyPackagedZnRelease({ releaseDir: fixture.releaseDir, version: '1.2.3', commit: 'a'.repeat(40) })
    assert.equal(verified.length, 1)
    assert.equal(verified[0].python, fixture.python)
    assert.equal(verified[0].browserRoot, fixture.browserRoot)
    assert.equal(verified[0].browserExecutable, fixture.browserExecutable)
    assert.equal(verified[0].veteranRuntimeRoot, fixture.veteranRuntimeRoot)
    assert.equal(
      verified[0].chromeDevtoolsMcpRuntimeRoot,
      fixture.chromeDevtoolsMcpRuntimeRoot
    )
  } finally {
    await fs.rm(root, { recursive: true, force: true })
  }
})

test('packaged runtime smoke binds Chromium lookup to the verified runtime root', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zn-packaged-release-'))
  try {
    const fixture = await writeFakePackagedRuntime(root)
    const [runtime] = await verifyPackagedZnRelease({ releaseDir: fixture.releaseDir, version: '1.2.3', commit: 'a'.repeat(40) })
    let invocation = null
    await smokePackagedZnRuntime(runtime, {
      run: async (python, args, options) => {
        invocation = { python, args, options }
        return { stdout: '', stderr: '' }
      }
    })
    assert.equal(invocation.python, fixture.python)
    assert.deepEqual(invocation.args.slice(0, 2), ['-I', '-c'])
    assert.equal(invocation.options.env.PLAYWRIGHT_BROWSERS_PATH, fixture.browserRoot)
    assert.equal(invocation.options.env.ZN_BROWSER_EXECUTABLE, fixture.browserExecutable)
    assert.equal(invocation.options.env.ZN_VETERAN_RUNTIME_ROOT, fixture.veteranRuntimeRoot)
    assert.equal(
      invocation.options.env.ZN_CHROME_DEVTOOLS_MCP_ROOT,
      fixture.chromeDevtoolsMcpRuntimeRoot
    )
    assert.match(invocation.args[2], /build_managed_browser_adapter/)
    assert.match(invocation.args[2], /chrome-devtools-mcp/)
    assert.match(invocation.args[2], /ZN_CHROME_DEVTOOLS_MCP_ROOT/)
    assert.match(invocation.args[2], /vendored_veteran_root/)
    assert.match(invocation.args[2], /about:blank/)
  } finally {
    await fs.rm(root, { recursive: true, force: true })
  }
})

test('packaged release verifier rejects missing managed browser root', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zn-packaged-release-'))
  try {
    const fixture = await writeFakePackagedRuntime(root)
    await fs.rm(fixture.browserRoot, { recursive: true, force: true })
    await assert.rejects(
      verifyPackagedZnRelease({ releaseDir: fixture.releaseDir, version: '1.2.3', commit: 'a'.repeat(40) }),
      /managed browser root is missing/
    )
  } finally {
    await fs.rm(root, { recursive: true, force: true })
  }
})

test('packaged release verifier rejects missing Veteran MCP server', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zn-packaged-release-'))
  try {
    const fixture = await writeFakePackagedRuntime(root)
    await fs.rm(path.join(fixture.veteranRuntimeRoot, 'mcp', 'server.mjs'))
    await assert.rejects(
      verifyPackagedZnRelease({ releaseDir: fixture.releaseDir, version: '1.2.3', commit: 'a'.repeat(40) }),
      /Veteran MCP server is missing/
    )
  } finally {
    await fs.rm(root, { recursive: true, force: true })
  }
})

test('packaged release verifier rejects missing Chrome DevTools MCP server', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zn-packaged-release-'))
  try {
    const fixture = await writeFakePackagedRuntime(root)
    await fs.rm(
      path.join(
        fixture.chromeDevtoolsMcpRuntimeRoot,
        'node_modules',
        'chrome-devtools-mcp',
        'build',
        'src',
        'bin',
        'chrome-devtools-mcp.js'
      )
    )
    await assert.rejects(
      verifyPackagedZnRelease({
        releaseDir: fixture.releaseDir,
        version: '1.2.3',
        commit: 'a'.repeat(40)
      }),
      /Chrome DevTools MCP server is missing/
    )
  } finally {
    await fs.rm(root, { recursive: true, force: true })
  }
})

test('packaged release verifier rejects Chrome MCP path outside runtime', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zn-packaged-release-'))
  try {
    const fixture = await writeFakePackagedRuntime(root)
    const manifestPath = path.join(fixture.runtimeRoot, 'runtime.json')
    const manifest = JSON.parse(await fs.readFile(manifestPath, 'utf8'))
    manifest.chrome_devtools_mcp_runtime = '../machine-chrome-mcp'
    await fs.writeFile(manifestPath, `${JSON.stringify(manifest)}\n`)
    await assert.rejects(
      verifyPackagedZnRelease({
        releaseDir: fixture.releaseDir,
        version: '1.2.3',
        commit: 'a'.repeat(40)
      }),
      /chrome_devtools_mcp_runtime escapes runtime root/
    )
  } finally {
    await fs.rm(root, { recursive: true, force: true })
  }
})

test('packaged release verifier rejects wrong Chrome MCP version', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zn-packaged-release-'))
  try {
    const fixture = await writeFakePackagedRuntime(root)
    const packagePath = path.join(
      fixture.chromeDevtoolsMcpRuntimeRoot,
      'node_modules',
      'chrome-devtools-mcp',
      'package.json'
    )
    await fs.writeFile(
      packagePath,
      JSON.stringify({ name: 'chrome-devtools-mcp', version: '9.9.9' })
    )
    await assert.rejects(
      verifyPackagedZnRelease({
        releaseDir: fixture.releaseDir,
        version: '1.2.3',
        commit: 'a'.repeat(40)
      }),
      /package version mismatch/
    )
  } finally {
    await fs.rm(root, { recursive: true, force: true })
  }
})

test('packaged release verifier rejects browser root outside runtime', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zn-packaged-release-'))
  try {
    const fixture = await writeFakePackagedRuntime(root)
    const manifestPath = path.join(fixture.runtimeRoot, 'runtime.json')
    const manifest = JSON.parse(await fs.readFile(manifestPath, 'utf8'))
    manifest.browser_root = '../machine-cache'
    await fs.writeFile(manifestPath, `${JSON.stringify(manifest)}\n`)
    await assert.rejects(
      verifyPackagedZnRelease({ releaseDir: fixture.releaseDir, version: '1.2.3', commit: 'a'.repeat(40) }),
      /browser_root escapes runtime root/
    )
  } finally {
    await fs.rm(root, { recursive: true, force: true })
  }
})

test('packaged release verifier rejects wrong source commit', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zn-packaged-release-'))
  try {
    const fixture = await writeFakePackagedRuntime(root)
    await assert.rejects(verifyPackagedZnRelease({ releaseDir: fixture.releaseDir, version: '1.2.3', commit: 'b'.repeat(40) }), /commit mismatch/)
  } finally {
    await fs.rm(root, { recursive: true, force: true })
  }
})

test('packaged release verifier rejects retired package content', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zn-packaged-release-'))
  try {
    const fixture = await writeFakePackagedRuntime(root)
    await fs.mkdir(path.join(fixture.backendRoot, retiredPackage), { recursive: true })
    await assert.rejects(verifyPackagedZnRelease({ releaseDir: fixture.releaseDir, version: '1.2.3', commit: 'a'.repeat(40) }), /forbidden retired package/)
  } finally {
    await fs.rm(root, { recursive: true, force: true })
  }
})

test('packaged release verifier requires resident core entrypoint', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zn-packaged-release-'))
  try {
    const fixture = await writeFakePackagedRuntime(root)
    await fs.rm(path.join(fixture.backendRoot, 'zn_agent', 'core', 'resident_server.py'))
    await assert.rejects(verifyPackagedZnRelease({ releaseDir: fixture.releaseDir, version: '1.2.3', commit: 'a'.repeat(40) }), /resident core entrypoint is missing/)
  } finally {
    await fs.rm(root, { recursive: true, force: true })
  }
})
