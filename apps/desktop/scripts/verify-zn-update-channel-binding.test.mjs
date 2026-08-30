import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import {
  normalizeZnUpdateChannelUrl,
  verifyZnUpdateChannelBinding
} from './verify-zn-update-channel-binding.mjs'

const CHANNEL = 'https://updates.zn.example/stable.json'

async function withBundle(source, fn) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zn-update-binding-'))
  const bundlePath = path.join(root, 'electron-main.mjs')
  await fs.writeFile(bundlePath, source, 'utf8')
  try {
    await fn(bundlePath)
  } finally {
    await fs.rm(root, { recursive: true, force: true })
  }
}

test('accepts a release bundle containing the exact normalized public stable channel', async () => {
  await withBundle(`const channel=${JSON.stringify(CHANNEL)};\n`, async bundlePath => {
    const result = await verifyZnUpdateChannelBinding({ bundlePath, expectedUrl: CHANNEL })
    assert.equal(result.updateChannelUrl, CHANNEL)
    assert.equal(result.bundlePath, path.resolve(bundlePath))
  })
})

test('rejects a bundle that still relies on runtime environment configuration', async () => {
  await withBundle(
    'const channel=process.env.ZN_DESKTOP_UPDATE_CHANNEL_URL;\n',
    async bundlePath => {
      await assert.rejects(
        verifyZnUpdateChannelBinding({ bundlePath, expectedUrl: CHANNEL }),
        /still depends on runtime update-channel environment/
      )
    }
  )
})

test('rejects a release bundle with a different channel binding', async () => {
  await withBundle('const channel="https://other.example/stable.json";\n', async bundlePath => {
    await assert.rejects(
      verifyZnUpdateChannelBinding({ bundlePath, expectedUrl: CHANNEL }),
      /does not contain the expected public ZN update channel/
    )
  })
})

test('rejects missing, insecure, credentialed, or non-stable channel URLs', () => {
  assert.throws(() => normalizeZnUpdateChannelUrl(''), /missing/)
  assert.throws(
    () => normalizeZnUpdateChannelUrl('http://updates.zn.example/stable.json'),
    /HTTPS URL ending in \/stable\.json/
  )
  assert.throws(
    () => normalizeZnUpdateChannelUrl('https://user:secret@updates.zn.example/stable.json'),
    /must not contain URL credentials/
  )
  assert.throws(
    () => normalizeZnUpdateChannelUrl('https://updates.zn.example/latest.json'),
    /HTTPS URL ending in \/stable\.json/
  )
})
