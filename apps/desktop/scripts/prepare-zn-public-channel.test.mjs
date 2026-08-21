import assert from 'node:assert/strict'
import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import { deriveZnReleaseNotes, prepareZnPublicChannel } from './prepare-zn-public-channel.mjs'

async function writeTarget(artifactDir, { platform, arch, name, bytes }) {
  const filePath = path.join(artifactDir, name)
  await fs.writeFile(filePath, bytes)
  const manifest = {
    schema: 1,
    product: 'ZN',
    repository: '9529360-cpu/znagent',
    version: '1.2.3',
    platform,
    arch,
    assets: [
      {
        name,
        size: bytes.length,
        sha256: crypto.createHash('sha256').update(bytes).digest('hex')
      }
    ]
  }
  await fs.writeFile(
    path.join(artifactDir, `zn-release-${platform}-${arch}.json`),
    `${JSON.stringify(manifest)}\n`
  )
}

test('public channel bundle copies immutable assets and writes stable.json last', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zn-public-channel-'))
  const artifactDir = path.join(root, 'dist')
  const outputDir = path.join(root, 'public')
  await fs.mkdir(artifactDir)

  try {
    await writeTarget(artifactDir, {
      platform: 'windows',
      arch: 'x64',
      name: 'ZN-1.2.3-win-x64.exe',
      bytes: Buffer.from('windows-installer')
    })
    await writeTarget(artifactDir, {
      platform: 'macos',
      arch: 'arm64',
      name: 'ZN-1.2.3-mac-arm64.zip',
      bytes: Buffer.from('mac-installer')
    })

    const { channel } = await prepareZnPublicChannel({
      artifactDir,
      version: '1.2.3',
      outputDir,
      releaseUrl: 'https://updates.zn.example/releases/1.2.3',
      subjects: [
        'feat: add resident runtime',
        'fix: repair update handoff',
        'refactor: simplify desktop bridge',
        'feat!: change runtime layout',
        'docs: internal notes'
      ]
    })

    assert.equal(channel.version, '1.2.3')
    assert.equal(channel.targets.length, 2)
    assert.deepEqual(channel.notes.new, ['add resident runtime', 'change runtime layout'])
    assert.deepEqual(channel.notes.fixes, ['repair update handoff'])
    assert.deepEqual(channel.notes.improvements, ['simplify desktop bridge'])
    assert.deepEqual(channel.notes.impact, ['change runtime layout'])
    assert.equal(
      channel.targets.find(target => target.platform === 'windows')?.url,
      './releases/1.2.3/ZN-1.2.3-win-x64.exe'
    )
    await fs.access(path.join(outputDir, 'releases', '1.2.3', 'ZN-1.2.3-win-x64.exe'))
    await fs.access(path.join(outputDir, 'stable.json'))
  } finally {
    await fs.rm(root, { recursive: true, force: true })
  }
})

test('release-note derivation ignores non-user-facing commit prefixes', () => {
  assert.deepEqual(deriveZnReleaseNotes(['ci: tune cache', 'test: add coverage', 'fix: visible bug']), {
    new: [],
    improvements: [],
    fixes: ['visible bug'],
    impact: []
  })
})
