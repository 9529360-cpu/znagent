import assert from 'node:assert/strict'

import { test } from 'vitest'

import { normalizeZnReleaseNotes, parseZnReleaseChannel } from './zn-release-channel'

const SHA = 'a'.repeat(64)

function baseDocument() {
  return {
    schema: 1,
    product: 'ZN',
    channel: 'stable',
    version: '1.2.3',
    release_url: './releases/1.2.3',
    notes: {
      new: ['Resident runtime is bundled', 'Resident runtime is bundled'],
      improvements: ['Faster startup'],
      fixes: ['Fixed update handoff'],
      impact: ['Existing resident state is preserved']
    },
    targets: [
      {
        platform: 'windows',
        arch: 'x64',
        name: 'ZN-1.2.3-win-x64.exe',
        url: './assets/ZN-1.2.3-win-x64.exe',
        size: 1234,
        sha256: SHA
      }
    ]
  }
}

test('stable channel resolves a matching target and structured notes', () => {
  const resolved = parseZnReleaseChannel(baseDocument(), {
    baseUrl: 'https://updates.zn.example/stable.json',
    platform: 'windows',
    arch: 'x64'
  })

  assert.equal(resolved.version, '1.2.3')
  assert.equal(resolved.releaseUrl, 'https://updates.zn.example/releases/1.2.3')
  assert.equal(resolved.target?.url, 'https://updates.zn.example/assets/ZN-1.2.3-win-x64.exe')
  assert.equal(resolved.target?.sha256, SHA)
  assert.deepEqual(resolved.notes.new, ['Resident runtime is bundled'])
  assert.deepEqual(resolved.notes.improvements, ['Faster startup'])
  assert.deepEqual(resolved.notes.fixes, ['Fixed update handoff'])
  assert.deepEqual(resolved.notes.impact, ['Existing resident state is preserved'])
})

test('stable channel leaves unsupported architecture without an install target', () => {
  const resolved = parseZnReleaseChannel(baseDocument(), {
    baseUrl: 'https://updates.zn.example/stable.json',
    platform: 'windows',
    arch: 'arm64'
  })

  assert.equal(resolved.version, '1.2.3')
  assert.equal(resolved.target, undefined)
})

test('stable channel rejects insecure asset URLs by default', () => {
  const document = baseDocument()
  document.targets[0].url = 'http://updates.zn.example/ZN.exe'

  assert.throws(
    () =>
      parseZnReleaseChannel(document, {
        baseUrl: 'https://updates.zn.example/stable.json',
        platform: 'windows',
        arch: 'x64'
      }),
    /must use HTTPS/
  )
})

test('development channel may explicitly allow HTTP assets', () => {
  const document = baseDocument()
  document.targets[0].url = 'http://127.0.0.1:8787/ZN-1.2.3-win-x64.exe'

  const resolved = parseZnReleaseChannel(document, {
    baseUrl: 'http://127.0.0.1:8787/stable.json',
    platform: 'windows',
    arch: 'x64',
    allowInsecureUrls: true
  })

  assert.equal(resolved.target?.url, 'http://127.0.0.1:8787/ZN-1.2.3-win-x64.exe')
})

test('release note normalization ignores blanks and non-string values', () => {
  assert.deepEqual(
    normalizeZnReleaseNotes({
      new: ['  one  ', '', 5, 'one', 'two'],
      improvements: null,
      fixes: ['fix'],
      impact: []
    }),
    {
      new: ['one', 'two'],
      improvements: [],
      fixes: ['fix'],
      impact: []
    }
  )
})
