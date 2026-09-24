import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash, generateKeyPairSync, verify } from 'node:crypto'
import fs from 'node:fs'
import fsp from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const script = path.join(here, 'sign-zn-update-channel.mjs')

function canonicalize(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return `[${value.map(item => canonicalize(item)).join(',')}]`
  const entries = Object.entries(value).sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
  return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonicalize(item)}`).join(',')}}`
}

test('sign script produces a trusted Ed25519 signature and rejects a mismatched trust root', async () => {
  const temp = await fsp.mkdtemp(path.join(os.tmpdir(), 'zn-update-sign-'))
  try {
    const channelPath = path.join(temp, 'stable.json')
    const document = {
      schema: 1,
      product: 'ZN',
      channel: 'stable',
      version: '1.2.3',
      published_at: '2026-09-23T00:00:00.000Z',
      notes: { new: [], improvements: [], fixes: [], impact: [] },
      targets: [{
        platform: 'windows',
        arch: 'x64',
        name: 'ZN.exe',
        url: './releases/1.2.3/ZN.exe',
        size: 10,
        sha256: 'a'.repeat(64)
      }]
    }
    await fsp.writeFile(channelPath, `${JSON.stringify(document, null, 2)}\n`, 'utf8')

    const { privateKey, publicKey } = generateKeyPairSync('ed25519')
    const privatePem = privateKey.export({ format: 'pem', type: 'pkcs8' })
    const publicDer = publicKey.export({ format: 'der', type: 'spki' })
    const publicBase64 = publicDer.toString('base64')

    execFileSync(process.execPath, [script, channelPath], {
      env: {
        ...process.env,
        ZN_UPDATE_SIGNING_PRIVATE_KEY: privatePem,
        ZN_UPDATE_SIGNING_PUBLIC_KEYS: publicBase64
      },
      stdio: 'pipe'
    })

    const signed = JSON.parse(await fsp.readFile(channelPath, 'utf8'))
    assert.equal(signed.signatures.length, 1)
    assert.equal(signed.signatures[0].alg, 'ed25519')
    assert.equal(
      signed.signatures[0].key_id,
      createHash('sha256').update(publicDer).digest('hex')
    )

    const unsigned = { ...signed }
    delete unsigned.signatures
    const payload = Buffer.from(canonicalize(unsigned), 'utf8')
    const signature = Buffer.from(signed.signatures[0].value, 'base64')
    assert.equal(verify(null, payload, publicKey, signature), true)

    const other = generateKeyPairSync('ed25519').publicKey.export({ format: 'der', type: 'spki' }).toString('base64')
    assert.throws(() => {
      execFileSync(process.execPath, [script, channelPath], {
        env: {
          ...process.env,
          ZN_UPDATE_SIGNING_PRIVATE_KEY: privatePem,
          ZN_UPDATE_SIGNING_PUBLIC_KEYS: other
        },
        stdio: 'pipe'
      })
    }, /Command failed/)
  } finally {
    fs.rmSync(temp, { recursive: true, force: true })
  }
})
