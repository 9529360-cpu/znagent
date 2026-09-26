import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdtemp, readFile, rm, stat } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { Readable } from 'node:stream'

import { afterEach, test } from 'vitest'

import {
  readZnBoundedUpdateBody,
  writeZnVerifiedUpdateBody,
  type ZnUpdateResponseBody
} from './zn-release-download-safety'

const temporaryRoots: string[] = []

function response(
  chunks: Array<Buffer | string>,
  headers: Record<string, string> = {}
): ZnUpdateResponseBody {
  const body = Readable.from(chunks) as ZnUpdateResponseBody
  body.headers = headers
  return body
}

async function temporaryPath(name: string): Promise<string> {
  const root = await mkdtemp(path.join(os.tmpdir(), 'zn-updater-bounds-'))
  temporaryRoots.push(root)
  return path.join(root, name)
}

afterEach(async () => {
  await Promise.all(
    temporaryRoots.splice(0).map(root => rm(root, { recursive: true, force: true }))
  )
})

test('bounded update body rejects an oversized declared response before buffering it', async () => {
  const body = response([Buffer.alloc(8)], { 'content-length': '2048' })

  await assert.rejects(
    readZnBoundedUpdateBody(body, 1024, 'update channel'),
    /update channel exceeds 1024 byte limit/
  )
  assert.equal(body.destroyed, true)
})

test('bounded update body rejects streamed overflow when content length is absent', async () => {
  const body = response([Buffer.alloc(700), Buffer.alloc(700)])

  await assert.rejects(
    readZnBoundedUpdateBody(body, 1024, 'update channel'),
    /update channel exceeds 1024 byte limit/
  )
  assert.equal(body.destroyed, true)
})

test('verified update stream writes exactly the signed size and digest', async () => {
  const bytes = Buffer.from('verified update bytes')
  const destination = await temporaryPath('update.bin')
  const progress: number[] = []

  const size = await writeZnVerifiedUpdateBody({
    response: response([bytes.subarray(0, 7), bytes.subarray(7)]),
    destination,
    expectedSize: bytes.length,
    expectedSha256: createHash('sha256').update(bytes).digest('hex'),
    onProgress: value => progress.push(value)
  })

  assert.equal(size, bytes.length)
  assert.deepEqual(await readFile(destination), bytes)
  assert.equal(progress.at(-1), bytes.length)
})

test('verified update stream rejects declared bytes beyond the signed size before opening a file', async () => {
  const destination = await temporaryPath('update.bin')
  const body = response([Buffer.alloc(4)], { 'content-length': '11' })

  await assert.rejects(
    writeZnVerifiedUpdateBody({
      response: body,
      destination,
      expectedSize: 10,
      expectedSha256: '0'.repeat(64)
    }),
    /exceeds signed size/
  )
  await assert.rejects(stat(destination), { code: 'ENOENT' })
  assert.equal(body.destroyed, true)
})

test('verified update stream stops a chunk that would exceed the signed size', async () => {
  const destination = await temporaryPath('update.bin')

  await assert.rejects(
    writeZnVerifiedUpdateBody({
      response: response([Buffer.alloc(8), Buffer.alloc(8)]),
      destination,
      expectedSize: 10,
      expectedSha256: '0'.repeat(64)
    }),
    /exceeds signed size/
  )

  const info = await stat(destination)
  assert.ok(info.size <= 10)
})
