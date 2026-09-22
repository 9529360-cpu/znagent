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
  const veteranRelative = 'veteran-engineer'
  const python = path.join(runtimeRoot, ...pythonRelative.split('/'))
  const backendRoot = path.join(runtimeRoot, ...backendRelative.split('/'))
  const browserRoot = path.join(runtimeRoot, browserRelative)
  const veteranRuntimeRoot = path.join(runtimeRoot, veteranRelative)
  await fs.mkdir(path.dirname(python), { recursive: true })
  await fs.writeFile(python, 'fake-python')
  if (process.platform !== 'win32') await fs.chmod(python, 0o755)
  await fs.mkdir(path.join(backendRoot, 'zn_agent', 'core'), { recursive: true })
  await fs.writeFile(path.join(backendRoot, 'zn_agent', 'resident.py'), '# resident package entry\n')
  await fs.writeFile(path.join(backendRoot, 'zn_agent', 'core', 'resident_server.py'), '# resident core\n')
  await fs.mkdir(path.join(browserRoot, 'chromium-fixture'), { recursive: true })
  await fs.writeFile(path.join(browserRoot, 'chromium-fixture', 'marker'), 'managed chromium')
  await fs.mkdir(path.join(veteranRuntimeRoot, 'mcp'), { recursive: true })
  await fs.writeFile(path.join(veteranRuntimeRoot, 'mcp', 'server.mjs'), '// veteran fixture\n')
  await fs.writeFile(path.join(veteranRuntimeRoot, 'VENDOR.json'), '{}\n')
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
    veteran_runtime: veteranRelative
  }, null, 2)}\n`)
  return { releaseDir: path.join(root, 'release'), runtimeRoot, python, backendRoot, browserRoot, veteranRuntimeRoot }
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
    assert.equal(verified[0].veteranRuntimeRoot, fixture.veteranRuntimeRoot)
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
    assert.equal(invocation.options.env.ZN_VETERAN_RUNTIME_ROOT, fixture.veteranRuntimeRoot)
    assert.match(invocation.args[2], /PlaywrightManagedBrowser/)
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
