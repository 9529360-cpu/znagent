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
  assert.match(workbench, /work\.residentProgress/)
  assert.match(workbench, /workProgress\.delegation/)
  assert.match(workbench, /work\.delegated/)
  assert.match(workbench, /delegatedKindLabel\(phase\.kind, t\)/)
  assert.match(workbench, /delegatedStageLabel\(phase\.stage, t\)/)
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

test('completed Work exposes durable execution evidence without inferring model use from provider readiness', () => {
  const workbench = read('src/zn/workbench.tsx')
  const client = read('src/zn/resident-client.ts')

  assert.match(client, /executionPath\?: string/)
  assert.match(client, /modelInvocations\?: number/)
  assert.match(client, /item\.execution_path \|\| item\.executionPath/)
  assert.match(client, /item\.model_invocations \?\? item\.modelInvocations/)
  assert.match(workbench, /executionEvidenceFromDetail/)
  assert.match(workbench, /detail\.execution_path \?\? detail\.executionPath/)
  assert.match(workbench, /detail\.model_invocations \?\? detail\.modelInvocations/)
  assert.match(workbench, /message\.executionEvidence/)
  assert.match(workbench, /message\.modelCalls/)
  assert.match(workbench, /executionPathLabel\(executionEvidence\.executionPath, t\)/)

  const helperStart = workbench.indexOf('function executionEvidenceFromDetail')
  const helperEnd = workbench.indexOf('function credentialLabel', helperStart)
  assert.ok(helperStart >= 0)
  assert.ok(helperEnd > helperStart)
  assert.doesNotMatch(workbench.slice(helperStart, helperEnd), /providerSettings|cognitionAvailable/)
})

test('continuation inspection returns control to the composer without finalizing the durable Work', () => {
  const workbench = read('src/zn/workbench.tsx')

  assert.match(workbench, /while \(!current\.terminal && current\.stage !== 'inspection_complete'\)/)
  assert.match(workbench, /if \(current\.stage === 'inspection_complete'\) \{[\s\S]*?return[\s\S]*?\}/)

  const inspectionBranchStart = workbench.indexOf("if (current.stage === 'inspection_complete')")
  const inspectionBranchEnd = workbench.indexOf("if (!current.finalized)", inspectionBranchStart)
  assert.ok(inspectionBranchStart >= 0)
  assert.ok(inspectionBranchEnd > inspectionBranchStart)
  const inspectionBranch = workbench.slice(inspectionBranchStart, inspectionBranchEnd)
  assert.doesNotMatch(inspectionBranch, /terminal\s*=/)
  assert.doesNotMatch(inspectionBranch, /finalized\s*=/)
})
