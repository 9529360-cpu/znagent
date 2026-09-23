import { createHash, createPublicKey, verify } from 'node:crypto'

export type ZnReleaseSignature = {
  alg: 'ed25519'
  key_id: string
  value: string
}

type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue }

function canonicalize(value: JsonValue): string {
  if (value === null || typeof value !== 'object') {
    const encoded = JSON.stringify(value)
    if (encoded === undefined) throw new Error('ZN update channel contains a non-JSON value')
    return encoded
  }
  if (Array.isArray(value)) return `[${value.map(item => canonicalize(item)).join(',')}]`
  const entries = Object.entries(value).sort(([left], [right]) => left.localeCompare(right))
  return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonicalize(item)}`).join(',')}}`
}

function unsignedDocument(value: unknown): JsonValue {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('ZN update channel must be a JSON object')
  }
  const copy = { ...(value as Record<string, unknown>) }
  delete copy.signatures
  return copy as JsonValue
}

function parsePublicKeyList(value: unknown): string[] {
  if (typeof value !== 'string') return []
  const seen = new Set<string>()
  const result: string[] = []
  for (const item of value.split(';')) {
    const normalized = item.trim()
    if (!normalized || seen.has(normalized)) continue
    seen.add(normalized)
    result.push(normalized)
  }
  return result
}

function keyId(publicKeyDer: Buffer): string {
  return createHash('sha256').update(publicKeyDer).digest('hex')
}

export function canonicalZnReleasePayload(value: unknown): Buffer {
  return Buffer.from(canonicalize(unsignedDocument(value)), 'utf8')
}

export function verifyZnReleaseChannelSignature(
  value: unknown,
  configuredPublicKeys: unknown,
  options: { required?: boolean } = {}
): void {
  const encodedKeys = parsePublicKeyList(configuredPublicKeys)
  const required = options.required !== false

  if (encodedKeys.length === 0) {
    if (required) throw new Error('this packaged ZN build has no trusted update signing key')
    return
  }

  const record = value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
  const signatures = Array.isArray(record?.signatures) ? record.signatures : []
  if (signatures.length === 0) {
    throw new Error('ZN update channel is not signed')
  }

  const payload = canonicalZnReleasePayload(value)
  for (const encodedKey of encodedKeys) {
    let publicKeyDer: Buffer
    try {
      publicKeyDer = Buffer.from(encodedKey, 'base64')
      const publicKey = createPublicKey({ key: publicKeyDer, format: 'der', type: 'spki' })
      if (publicKey.asymmetricKeyType !== 'ed25519') continue
      const expectedKeyId = keyId(publicKeyDer)

      for (const raw of signatures) {
        if (!raw || typeof raw !== 'object' || Array.isArray(raw)) continue
        const signature = raw as Partial<ZnReleaseSignature>
        if (signature.alg !== 'ed25519' || signature.key_id !== expectedKeyId || typeof signature.value !== 'string') {
          continue
        }
        const bytes = Buffer.from(signature.value, 'base64')
        if (bytes.length === 0) continue
        if (verify(null, payload, publicKey, bytes)) return
      }
    } catch {
      continue
    }
  }

  throw new Error('ZN update channel signature is not trusted')
}
