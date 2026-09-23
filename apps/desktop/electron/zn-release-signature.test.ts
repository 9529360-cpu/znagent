import assert from 'node:assert/strict'
import { generateKeyPairSync, sign } from 'node:crypto'

import { test } from 'vitest'

import {
  canonicalZnReleasePayload,
  verifyZnReleaseChannelSignature
} from './zn-release-signature'

function fixture() {
  return {
    schema: 1,
    product: 'ZN',
    channel: 'stable',
    version: '1.2.3',
    targets: [
      {
        platform: 'windows',
        arch: 'x64',
        name: 'ZN.exe',
        url: './ZN.exe',
        size: 42,
        sha256: 'a'.repeat(64)
      }
    ]
  }
}

function signingFixture() {
  const { privateKey, publicKey } = generateKeyPairSync('ed25519')
  const publicDer = publicKey.export({ format: 'der', type: 'spki' }) as Buffer
  const keyId = (await import('node:crypto')).createHash('sha256').update(publicDer).digest('hex')
  return { privateKey, publicDer, keyId }
}

test('signed release channel verifies against its embedded trust root', async () => {
  const { generateKeyPairSync, createHash } = await import('node:crypto')
  const { privateKey, publicKey } = generateKeyPairSync('ed25519')
  const publicDer = publicKey.export({ format: 'der', type: 'spki' }) as Buffer
  const document = fixture()
  const signature = sign(null, canonicalZnReleasePayload(document), privateKey).toString('base64')
  const signed = {
    ...document,
    signatures: [{
      alg: 'ed25519',
      key_id: createHash('sha256').update(publicDer).digest('hex'),
      value: signature
    }]
  }

  assert.doesNotThrow(() =>
    verifyZnReleaseChannelSignature(signed, publicDer.toString('base64'))
  )
})

test('tampered signed release channel fails closed', async () => {
  const { generateKeyPairSync, createHash } = await import('node:crypto')
  const { privateKey, publicKey } = generateKeyPairSync('ed25519')
  const publicDer = publicKey.export({ format: 'der', type: 'spki' }) as Buffer
  const document = fixture()
  const signature = sign(null, canonicalZnReleasePayload(document), privateKey).toString('base64')
  const signed = {
    ...document,
    signatures: [{
      alg: 'ed25519',
      key_id: createHash('sha256').update(publicDer).digest('hex'),
      value: signature
    }]
  }
  const tampered = { ...signed, version: '9.9.9' }

  assert.throws(
    () => verifyZnReleaseChannelSignature(tampered, publicDer.toString('base64')),
    /signature is not trusted/
  )
})

test('packaged verification rejects missing keys or missing signatures', () => {
  assert.throws(
    () => verifyZnReleaseChannelSignature(fixture(), ''),
    /no trusted update signing key/
  )

  const { publicKey } = generateKeyPairSync('ed25519')
  const publicDer = publicKey.export({ format: 'der', type: 'spki' }) as Buffer
  assert.throws(
    () => verifyZnReleaseChannelSignature(fixture(), publicDer.toString('base64')),
    /not signed/
  )
})

test('explicit development mode may permit an unsigned channel without keys', () => {
  assert.doesNotThrow(() =>
    verifyZnReleaseChannelSignature(fixture(), '', { required: false })
  )
})
