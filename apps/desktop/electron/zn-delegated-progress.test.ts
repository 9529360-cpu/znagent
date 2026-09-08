import assert from 'node:assert/strict'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { build } from 'esbuild'
import { test } from 'vitest'

const here = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(here, '..')

type DelegatedProgressResult = {
  planVersion: number
  status: string
  currentPhase?: string
  counts: Record<string, number>
  phases: Array<{ kind: string; status: string; stage: string; updatedAt?: number }>
}

async function loadNormalizer(): Promise<(value: unknown) => DelegatedProgressResult | undefined> {
  const result = await build({
    entryPoints: [path.join(desktopRoot, 'src/zn/resident-client.ts')],
    bundle: true,
    write: false,
    format: 'esm',
    platform: 'browser',
    target: 'es2023'
  })
  const output = result.outputFiles[0]
  assert.ok(output)
  const moduleUrl = `data:text/javascript;base64,${Buffer.from(output.text).toString('base64')}`
  const module = await import(moduleUrl) as {
    normalizeDelegatedProgress?: (value: unknown) => DelegatedProgressResult | undefined
  }
  assert.equal(typeof module.normalizeDelegatedProgress, 'function')
  return module.normalizeDelegatedProgress!
}

test('delegated progress normalization keeps only bounded user-readable fields', async () => {
  const normalizeDelegatedProgress = await loadNormalizer()
  const result = normalizeDelegatedProgress({
    plan_version: 2,
    status: 'running',
    current_phase: 'coding',
    counts: { pending: 1, running: 1, completed: 1, failed: 0, superseded: 1 },
    phases: [
      { kind: 'research', status: 'completed', stage: 'completed', updated_at: '2026-09-08T00:00:00Z' },
      {
        kind: 'coding',
        status: 'running',
        stage: 'acting',
        updated_at: '2026-09-08T00:01:00Z',
        worker_run_id: 'SECRET-WORKER',
        model_goal_id: 'SECRET-GOAL',
        provider: 'SECRET-PROVIDER',
        fingerprint: 'SECRET-FINGERPRINT'
      },
      { kind: 'review', status: 'pending', stage: 'waiting' }
    ],
    worker_run_id: 'SECRET-TOP-WORKER',
    raw_error: 'SECRET-RAW-ERROR'
  })

  assert.ok(result)
  assert.equal(result.planVersion, 2)
  assert.equal(result.status, 'running')
  assert.equal(result.currentPhase, 'coding')
  assert.deepEqual(result.counts, {
    pending: 1,
    running: 1,
    completed: 1,
    failed: 0,
    superseded: 1
  })
  assert.equal(result.phases[1]?.stage, 'acting')

  const encoded = JSON.stringify(result)
  for (const secret of [
    'SECRET-WORKER',
    'SECRET-TOP-WORKER',
    'SECRET-GOAL',
    'SECRET-PROVIDER',
    'SECRET-FINGERPRINT',
    'SECRET-RAW-ERROR',
    'worker_run_id',
    'model_goal_id',
    'provider',
    'fingerprint'
  ]) assert.doesNotMatch(encoded, new RegExp(secret))
})

test('delegated progress normalizer ignores malformed phases and fails safe on unknown enums', async () => {
  const normalizeDelegatedProgress = await loadNormalizer()
  const result = normalizeDelegatedProgress({
    plan_version: 7,
    status: 'INTERNAL-STATUS',
    current_phase: 'INTERNAL-KIND',
    counts: { pending: -4, running: '2', completed: 99999, failed: null, superseded: 1.9 },
    phases: [
      null,
      'bad',
      {},
      { kind: 'coding', status: 'INTERNAL-STATUS', stage: 'SECRET-INTERNAL-STAGE', updated_at: 'not-a-date' },
      { kind: 'INTERNAL-KIND', status: 'running', stage: 'acting' }
    ]
  })

  assert.ok(result)
  assert.equal(result.status, 'pending')
  assert.equal(result.currentPhase, 'work')
  assert.deepEqual(result.counts, {
    pending: 0,
    running: 2,
    completed: 256,
    failed: 0,
    superseded: 1
  })
  assert.equal(result.phases.length, 2)
  assert.deepEqual(result.phases[0], { kind: 'coding', status: 'pending', stage: 'working' })
  assert.deepEqual(result.phases[1], { kind: 'work', status: 'running', stage: 'acting' })
  assert.doesNotMatch(JSON.stringify(result), /SECRET-INTERNAL-STAGE/)
})

test('delegated progress is optional for old or malformed resident payloads', async () => {
  const normalizeDelegatedProgress = await loadNormalizer()
  assert.equal(normalizeDelegatedProgress(undefined), undefined)
  assert.equal(normalizeDelegatedProgress({}), undefined)
  assert.equal(normalizeDelegatedProgress({ plan_version: 0, counts: {} }), undefined)
  assert.equal(normalizeDelegatedProgress({ plan_version: 1 }), undefined)
})
