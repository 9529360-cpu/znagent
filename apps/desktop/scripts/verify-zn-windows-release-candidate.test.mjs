import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import { verifyZnWindowsReleaseCandidate } from './verify-zn-windows-release-candidate.mjs'

const VERSION = '0.17.0'
const ARCH = 'x64'

function digest(bytes) {
  return createHash('sha256').update(bytes).digest('hex')
}

async function fixture() {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zn-windows-candidate-'))
  const exe = Buffer.from('zn-nsis-candidate')
  const msi = Buffer.from('zn-msi-candidate')
  const assets = [
    { name: `ZN-${VERSION}-win-${ARCH}.exe`, size: exe.length, sha256: digest(exe) },
    { name: `ZN-${VERSION}-win-${ARCH}.msi`, size: msi.length, sha256: digest(msi) }
  ]
  await fs.writeFile(path.join(root, assets[0].name), exe)
  await fs.writeFile(path.join(root, assets[1].name), msi)

  const writeManifest = async overrides => {
    const manifest = {
      schema: 1,
      product: 'ZN',
      repository: '9529360-cpu/znagent',
      version: VERSION,
      tag: null,
      platform: 'windows',
      arch: ARCH,
      generated_at: '2026-08-28T00:00:00.000Z',
      assets,
      ...overrides
    }
    await fs.writeFile(
      path.join(root, `zn-release-windows-${ARCH}.json`),
      `${JSON.stringify(manifest, null, 2)}\n`,
      'utf8'
    )
  }

  await writeManifest()
  return { root, assets, writeManifest, cleanup: () => fs.rm(root, { recursive: true, force: true }) }
}

test('verifies one NSIS exe and one MSI against exact manifest size and SHA-256', async () => {
  const item = await fixture()
  try {
    const result = await verifyZnWindowsReleaseCandidate({ releaseDir: item.root, version: VERSION })
    assert.equal(result.version, VERSION)
    assert.equal(result.arch, ARCH)
    assert.deepEqual(result.assets.map(asset => path.extname(asset.name)).sort(), ['.exe', '.msi'])
  } finally {
    await item.cleanup()
  }
})

test('rejects a candidate that does not contain exactly one exe and one msi', async () => {
  const item = await fixture()
  try {
    const secondExe = Buffer.from('second')
    const secondAsset = {
      name: 'second.exe',
      size: secondExe.length,
      sha256: digest(secondExe)
    }
    await fs.writeFile(path.join(item.root, secondAsset.name), secondExe)
    await item.writeManifest({ assets: [item.assets[0], secondAsset] })
    await assert.rejects(
      verifyZnWindowsReleaseCandidate({ releaseDir: item.root, version: VERSION }),
      /exactly one \.exe installer|exactly one \.msi installer/
    )
  } finally {
    await item.cleanup()
  }
})

test('rejects manifest/file hash drift', async () => {
  const item = await fixture()
  try {
    const changed = item.assets.map(asset => ({ ...asset }))
    changed[0].sha256 = '0'.repeat(64)
    await item.writeManifest({ assets: changed })
    await assert.rejects(
      verifyZnWindowsReleaseCandidate({ releaseDir: item.root, version: VERSION }),
      /SHA-256 mismatch/
    )
  } finally {
    await item.cleanup()
  }
})

test('rejects wrong release identity', async () => {
  const item = await fixture()
  try {
    await item.writeManifest({ platform: 'linux' })
    await assert.rejects(
      verifyZnWindowsReleaseCandidate({ releaseDir: item.root, version: VERSION }),
      /platform mismatch/
    )
    await item.writeManifest({ arch: 'arm64' })
    await assert.rejects(
      verifyZnWindowsReleaseCandidate({ releaseDir: item.root, version: VERSION }),
      /arch mismatch/
    )
    await item.writeManifest({ version: '0.17.1' })
    await assert.rejects(
      verifyZnWindowsReleaseCandidate({ releaseDir: item.root, version: VERSION }),
      /version mismatch/
    )
  } finally {
    await item.cleanup()
  }
})

test('rejects unsafe asset names before filesystem lookup', async () => {
  const item = await fixture()
  try {
    const unsafe = item.assets.map(asset => ({ ...asset }))
    unsafe[0].name = '../escape.exe'
    await item.writeManifest({ assets: unsafe })
    await assert.rejects(
      verifyZnWindowsReleaseCandidate({ releaseDir: item.root, version: VERSION }),
      /asset name is unsafe/
    )
  } finally {
    await item.cleanup()
  }
})
