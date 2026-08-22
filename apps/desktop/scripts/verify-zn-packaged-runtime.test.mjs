import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import { findPackagedZnRuntimeRoots, verifyPackagedZnRelease } from './verify-zn-packaged-runtime.mjs'

async function writeFakePackagedRuntime(root, { version = '1.2.3', commit = 'a'.repeat(40) } = {}) {
  const runtimeRoot = path.join(root, 'release', 'linux-unpacked', 'resources', 'zn-runtime')
  const pythonRelative = process.platform === 'win32' ? 'python/python.exe' : 'python/bin/python3'
  const backendRelative = 'python/site-packages'
  const python = path.join(runtimeRoot, ...pythonRelative.split('/'))
  const backendRoot = path.join(runtimeRoot, ...backendRelative.split('/'))
  await fs.mkdir(path.dirname(python), { recursive: true })
  await fs.writeFile(python, 'fake-python')
  if (process.platform !== 'win32') await fs.chmod(python, 0o755)
  await fs.mkdir(path.join(backendRoot, 'zn_agent', 'core'), { recursive: true })
  await fs.writeFile(path.join(backendRoot, 'zn_agent', 'resident.py'), '# resident package entry\n')
  await fs.writeFile(path.join(backendRoot, 'zn_agent', 'core', 'resident_server.py'), '# resident core\n')
  await fs.writeFile(path.join(runtimeRoot, 'runtime.json'), `${JSON.stringify({
    schema: 1,
    product: 'ZN',
    runtime_id: commit,
    version,
    commit,
    platform: process.platform,
    arch: process.arch,
    python: pythonRelative,
    backend_root: backendRelative
  }, null, 2)}\n`)
  return { releaseDir: path.join(root, 'release'), runtimeRoot, python, backendRoot }
}

test('packaged release verifier validates ZN-only runtime', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zn-packaged-release-'))
  try {
    const fixture = await writeFakePackagedRuntime(root)
    assert.deepEqual(await findPackagedZnRuntimeRoots(fixture.releaseDir), [fixture.runtimeRoot])
    const verified = await verifyPackagedZnRelease({ releaseDir: fixture.releaseDir, version: '1.2.3', commit: 'a'.repeat(40) })
    assert.equal(verified.length, 1)
    assert.equal(verified[0].python, fixture.python)
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

test('packaged release verifier rejects inherited Hermes content', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zn-packaged-release-'))
  try {
    const fixture = await writeFakePackagedRuntime(root)
    await fs.mkdir(path.join(fixture.backendRoot, 'hermes_cli'), { recursive: true })
    await assert.rejects(verifyPackagedZnRelease({ releaseDir: fixture.releaseDir, version: '1.2.3', commit: 'a'.repeat(40) }), /forbidden inherited package/)
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
