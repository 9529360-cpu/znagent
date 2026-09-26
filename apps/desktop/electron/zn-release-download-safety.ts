import { createHash } from 'node:crypto'
import { createWriteStream } from 'node:fs'
import type { IncomingHttpHeaders } from 'node:http'
import { Readable, Transform } from 'node:stream'
import { pipeline } from 'node:stream/promises'

export type ZnUpdateResponseBody = Readable & {
  headers: IncomingHttpHeaders
}

function contentLength(response: ZnUpdateResponseBody): number | null {
  const raw = response.headers['content-length']
  const value = Array.isArray(raw) ? raw[0] : raw
  if (value === undefined) return null
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : null
}

function sizeLimitError(label: string, limit: number): Error {
  return new Error(`${label} exceeds ${limit} byte limit`)
}

export async function readZnBoundedUpdateBody(
  response: ZnUpdateResponseBody,
  maxBytes: number,
  label: string
): Promise<Buffer> {
  const limit = Math.max(0, Math.trunc(maxBytes))
  const declared = contentLength(response)
  if (declared !== null && declared > limit) {
    response.destroy()
    throw sizeLimitError(label, limit)
  }

  const chunks: Buffer[] = []
  let size = 0
  try {
    for await (const chunk of response) {
      const bytes = Buffer.from(chunk)
      if (size + bytes.length > limit) {
        response.destroy()
        throw sizeLimitError(label, limit)
      }
      size += bytes.length
      chunks.push(bytes)
    }
  } catch (error) {
    response.destroy()
    throw error
  }
  return Buffer.concat(chunks, size)
}

export async function writeZnVerifiedUpdateBody(options: {
  response: ZnUpdateResponseBody
  destination: string
  expectedSize: number
  expectedSha256: string
  onProgress?: (downloadedBytes: number) => void
}): Promise<number> {
  const expectedSize = Math.max(0, Math.trunc(options.expectedSize))
  const declared = contentLength(options.response)
  if (declared !== null && declared > expectedSize) {
    options.response.destroy()
    throw new Error('downloaded ZN update exceeds signed size')
  }

  const hash = createHash('sha256')
  let size = 0
  const guard = new Transform({
    transform(chunk, _encoding, callback) {
      const bytes = Buffer.from(chunk)
      if (size + bytes.length > expectedSize) {
        callback(new Error('downloaded ZN update exceeds signed size'))
        return
      }
      size += bytes.length
      hash.update(bytes)
      options.onProgress?.(size)
      callback(null, bytes)
    }
  })

  await pipeline(
    options.response,
    guard,
    createWriteStream(options.destination, { flags: 'w' })
  )

  const digest = hash.digest('hex')
  if (size !== expectedSize || digest !== options.expectedSha256) {
    throw new Error('downloaded ZN update failed channel verification')
  }
  return size
}
