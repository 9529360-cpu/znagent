import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { test } from 'vitest'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const read = (relative: string) => fs.readFileSync(path.join(root, relative), 'utf8')

test('real desktop Work starts the one durable model-led Resident loop', () => {
  const client = read('src/zn/resident-client.ts')
  const start = client.slice(
    client.indexOf('export async function startZnWork('),
    client.indexOf('export async function loadZnWorkProgress(')
  )
  assert.match(start, /desktop\(\)\.resident\.workStart\(/)
  assert.match(start, /payload:\s*\{\s*agent_loop:\s*true\s*\}/)
  assert.doesNotMatch(start, /agentRun|createAgent|new AgenticToolLoop/)

  const ipc = read('electron/zn-resident-ipc.ts')
  const normalize = ipc.slice(
    ipc.indexOf('function normalizedWorkPayload('),
    ipc.indexOf('export function registerZnResidentIpc(')
  )
  assert.match(normalize, /payload:\s*payload\?\.payload/)
  assert.match(ipc, /request\('work_start', normalizedWorkPayload\(payload\)\)/)

  const workbench = read('src/zn/workbench.tsx')
  assert.match(workbench, /await startZnWork\(threadId, task\)/)
  assert.doesNotMatch(start, /workSubmit\(/)
})
