import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { test } from 'vitest'

const here = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(here, '..')

function read(relative: string): string {
  return fs.readFileSync(path.join(desktopRoot, relative), 'utf8')
}

test('existing Resident progress card renders bounded delegated phase/status text', () => {
  const workbench = read('src/zn/workbench.tsx')
  const client = read('src/zn/resident-client.ts')

  assert.match(client, /export type ZnDelegatedProgress/)
  assert.match(client, /export type ZnDelegatedPhaseProgress/)
  assert.match(client, /normalizeDelegatedProgress/)
  assert.match(client, /delegation\?: ZnDelegatedProgress/)
  assert.match(workbench, /Resident progress/)
  assert.match(workbench, /workProgress\.delegation/)
  assert.match(workbench, /Delegated work/)
  assert.match(workbench, /delegatedKindLabel\(phase\.kind\)/)
  assert.match(workbench, /delegatedStageLabel\(phase\.stage\)/)
})

test('delegated renderer path never references internal WorkerRun routing or fingerprint fields', () => {
  const workbench = read('src/zn/workbench.tsx')
  const delegatedStart = workbench.indexOf('{workProgress.delegation ? (')
  const delegatedEnd = workbench.indexOf('{workProgress.recovery?.replayBlocked', delegatedStart)
  assert.ok(delegatedStart >= 0)
  assert.ok(delegatedEnd > delegatedStart)
  const delegatedSection = workbench.slice(delegatedStart, delegatedEnd)

  for (const internalName of [
    'workerRunId',
    'worker_run_id',
    'modelGoalId',
    'model_goal_id',
    'modelRouteId',
    'model_route_id',
    'provider',
    'fingerprint',
    'toolScope',
    'authorityScope',
    'resultSummary',
    'rawError'
  ]) assert.doesNotMatch(delegatedSection, new RegExp(internalName, 'i'))
})
