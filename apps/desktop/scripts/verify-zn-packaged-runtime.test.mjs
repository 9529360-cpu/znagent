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
  await fs.mkdir(path.join(backendRoot, 'hermes_cli'), { recursive: true })
  await fs.mkdir(path.join(backendRoot, 'agent', 'kernel'), { recursive: true })
  await fs.writeFile(path.join(backendRoot, 'hermes_cli', 'main.py'), '# backend\n')
  await fs.writeFile(path.join(backendRoot, 'agent', 'kernel', 'resident_server.py'), '# resident\n')
  await fs.writeFile(
    path.join(runtimeRoot, 'runtime.json'),
    `${JSON.stringify(
      {
        schema: 1,
        product: 'ZN',
        runtime_id: commit,
        version,
        commit,
        platform: process.platform,
        arch: process.arch,
        python: pythonRelative,
        backend_root: backendRelative
      },
      null,
      2
    )}\n`
  )

  return { releaseDir: path.join(root, 'release'), runtimeRoot, python, backendRoot }
}

test('packaged release verifier finds and validates runtime inside unpacked app resources', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zn-packaged-release-'))
  try {
    const fixture = await writeFakePackagedRuntime(root)
    const roots = await findPackagedZnRuntimeRoots(fixture.releaseDir)
    assert.deepEqual(roots, [fixture.runtimeRoot])

    const verified = await verifyPackagedZnRelease({
      releaseDir: fixture.releaseDir,
      version: '1.2.3',
      commit: 'a'.repeat(40)
    })
    assert.equal(verified.length, 1)
    assert.equal(verified[0].python, fixture.python)
    assert.equal(verified[0].backendRoot, fixture.backendRoot)
  } finally {
    await fs.rm(root, { recursive: true, force: true })
  }
})

test('packaged release verifier rejects a runtime from the wrong source commit', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zn-packaged-release-'))
  try {
    const fixture = await writeFakePackagedRuntime(root)
    await assert.rejects(
      verifyPackagedZnRelease({
        releaseDir: fixture.releaseDir,
        version: '1.2.3',
        commit: 'b'.repeat(40)
      }),
      /commit mismatch/
    )
  } finally {
    await fs.rm(root, { recursive: true, force: true })
  }
})

test('packaged release verifier rejects a missing resident entrypoint', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zn-packaged-release-'))
  try {
    const fixture = await writeFakePackagedRuntime(root)
    await fs.rm(path.join(fixture.backendRoot, 'agent', 'kernel', 'resident_server.py'))
    await assert.rejects(
      verifyPackagedZnRelease({
        releaseDir: fixture.releaseDir,
        version: '1.2.3',
        commit: 'a'.repeat(40)
      }),
      /resident entrypoint is missing/
    )
  } finally {
    await fs.rm(root, { recursive: true, force: true })
  }
})
