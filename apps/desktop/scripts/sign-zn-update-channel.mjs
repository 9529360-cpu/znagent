#!/usr/bin/env node
import { createHash, createPrivateKey, createPublicKey, sign } from 'node:crypto'
import fs from 'node:fs/promises'
import path from 'node:path'

function canonicalize(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return `[${value.map(item => canonicalize(item)).join(',')}]`
  const entries = Object.entries(value).sort(([left], [right]) => left.localeCompare(right))
  return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonicalize(item)}`).join(',')}}`
}

function unsignedDocument(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('ZN update channel must be a JSON object')
  }
  const copy = { ...value }
  delete copy.signatures
  return copy
}

function trustedKeys(value) {
  return String(value || '').split(';').map(item => item.trim()).filter(Boolean)
}

const channelPath = path.resolve(process.argv[2] || 'public-channel/stable.json')
const privatePem = String(process.env.ZN_UPDATE_SIGNING_PRIVATE_KEY || '').trim()
if (!privatePem) throw new Error('ZN_UPDATE_SIGNING_PRIVATE_KEY is required')

const privateKey = createPrivateKey(privatePem)
if (privateKey.asymmetricKeyType !== 'ed25519') {
  throw new Error('ZN update signing key must be Ed25519')
}

const publicKey = createPublicKey(privateKey)
const publicDer = publicKey.export({ format: 'der', type: 'spki' })
const encodedPublic = publicDer.toString('base64')
const allowed = trustedKeys(process.env.ZN_UPDATE_SIGNING_PUBLIC_KEYS)
if (!allowed.includes(encodedPublic)) {
  throw new Error('release signing private key does not match any configured ZN_UPDATE_SIGNING_PUBLIC_KEYS entry')
}

const document = JSON.parse(await fs.readFile(channelPath, 'utf8'))
const payload = Buffer.from(canonicalize(unsignedDocument(document)), 'utf8')
const signature = sign(null, payload, privateKey).toString('base64')
const keyId = createHash('sha256').update(publicDer).digest('hex')

const signed = {
  ...unsignedDocument(document),
  signatures: [{ alg: 'ed25519', key_id: keyId, value: signature }]
}
await fs.writeFile(channelPath, `${JSON.stringify(signed, null, 2)}\n`, 'utf8')
console.log(`signed ${channelPath} with key ${keyId}`)
