import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { build } from 'esbuild'
import { test, vi } from 'vitest'

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

// Like zn-delegated-progress.test.ts, execute the actual renderer bundle rather
// than importing DOM-dependent source into Electron's deliberately DOM-free
// TypeScript project. Renderer source remains checked by its own strict project.
type ActiveRun = { threadId: string; eventId: string }
type Thread = {
  id: string; title: string; createdAt: number; updatedAt: number
  messages: unknown[]; artifacts: unknown[]; activeRun?: ActiveRun
}
type Progress = ActiveRun & {
  status: string; stage: string; nextAction: string; terminal: boolean
  finalized: boolean; updatedAt: number; bodyActions: unknown[]
  recovery?: { replayBlocked: boolean }
}
type ProgressResult = { progress: Progress; thread?: Thread }
type ReconnectionModules = {
  normalizeZnActiveWorkRun: (value: unknown, threadId: string) => ActiveRun | undefined
  hasZnUnfinishedWork: (thread: Thread | null, progress: Progress | null) => boolean
  shouldDiscardZnWorkProgress: (thread: Thread | null, progress: Progress | null, submissionBusy: boolean) => boolean
  observeZnWorkProgress: (
    run: ActiveRun,
    read: (threadId: string, eventId: string) => Promise<ProgressResult>,
    onUpdate: (value: ProgressResult) => void,
    onError: (error: Error) => void
  ) => () => void
  loadZnThreadCache: () => Thread[]
  saveZnThreadCache: (threads: Thread[]) => void
  loadZnWorkThreads: () => Promise<Thread[]>
  loadZnWorkProgress: (threadId: string, eventId: string) => Promise<ProgressResult>
}
let rendererModules: Promise<ReconnectionModules> | undefined
function loadReconnectionModules(): Promise<ReconnectionModules> {
  rendererModules ??= (async () => {
    const result = await build({
      stdin: {
        contents: [
          "export * from './src/zn/work-reconnection';",
          "export { loadZnWorkThreads, loadZnWorkProgress } from './src/zn/resident-client';",
          "export { loadZnThreadCache, saveZnThreadCache } from './src/zn/state';"
        ].join('\n'),
        resolveDir: desktopRoot,
        sourcefile: 'reconnection-test-entry.ts',
        loader: 'ts'
      },
      bundle: true, write: false, format: 'esm', platform: 'browser', target: 'es2023'
    })
    assert.ok(result.outputFiles[0])
    const url = `data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`
    return await import(url) as ReconnectionModules
  })()
  return rendererModules
}

const activeRun = { threadId: 'thread-a', eventId: 'event-a' }
function progressResult(overrides: Partial<Progress> = {}): ProgressResult {
  return { progress: {
    ...activeRun, status: 'processing', stage: 'working', nextAction: 'observe',
    terminal: false, finalized: false, updatedAt: 1, bodyActions: [], ...overrides
  } }
}
function threadWithRun(): Thread {
  return { id: activeRun.threadId, title: 'Current work', createdAt: 1, updatedAt: 1,
    messages: [], artifacts: [], activeRun }
}

test('reconnection identity is same-thread Resident evidence and is never read from the cache', async () => {
  const { normalizeZnActiveWorkRun, loadZnThreadCache, saveZnThreadCache } = await loadReconnectionModules()
  assert.deepEqual(normalizeZnActiveWorkRun({ thread_id: 'thread-a', event_id: 'event-a', command: 'private' }, 'thread-a'), activeRun)
  for (const invalid of [null, [], {}, { thread_id: 'other', event_id: 'event-a' }, { thread_id: 'thread-a', event_id: 42 }]) {
    assert.equal(normalizeZnActiveWorkRun(invalid, 'thread-a'), undefined)
  }
  const source = threadWithRun()
  let cached = JSON.stringify([source])
  vi.stubGlobal('window', { localStorage: {
    getItem: () => cached, setItem: (_key: string, value: string) => { cached = value }
  } })
  try {
    assert.equal(loadZnThreadCache()[0].activeRun, undefined)
    saveZnThreadCache([source])
    assert.equal(JSON.parse(cached)[0].activeRun, undefined)
    assert.equal(source.activeRun?.eventId, activeRun.eventId)
  } finally { vi.unstubAllGlobals() }
})

test('reconnected Work locks duplicate submission until exact-event inspection or completion', async () => {
  const { hasZnUnfinishedWork } = await loadReconnectionModules()
  const thread = threadWithRun()
  assert.equal(hasZnUnfinishedWork(thread, null), true)
  assert.equal(hasZnUnfinishedWork(thread, progressResult().progress), true)
  assert.equal(hasZnUnfinishedWork(thread, progressResult({ eventId: 'old', terminal: true }).progress), true)
  assert.equal(hasZnUnfinishedWork(thread, progressResult({ stage: 'inspection_complete' }).progress), false)
  assert.equal(hasZnUnfinishedWork(thread, progressResult({ finalized: true }).progress), false)
  assert.equal(hasZnUnfinishedWork({ ...thread, activeRun: undefined }, null), false)
})

test('authoritative completion or replacement retires a stale card without disrupting submission or inspection', async () => {
  const { shouldDiscardZnWorkProgress } = await loadReconnectionModules()
  const progress = progressResult().progress
  const completed = { ...threadWithRun(), activeRun: undefined }
  assert.equal(shouldDiscardZnWorkProgress(completed, progress, false), true)
  assert.equal(shouldDiscardZnWorkProgress(threadWithRun(), progress, false), false)
  assert.equal(shouldDiscardZnWorkProgress({ ...threadWithRun(), activeRun: { ...activeRun, eventId: 'next-event' } }, progress, false), true)
  assert.equal(shouldDiscardZnWorkProgress(completed, progress, true), false)
  assert.equal(shouldDiscardZnWorkProgress(completed, progressResult({ stage: 'inspection_complete' }).progress, false), false)
  assert.equal(shouldDiscardZnWorkProgress({ ...completed, id: 'another-thread' }, progress, false), false)
  assert.equal(progress.terminal, false)
  assert.equal(progress.finalized, false)
  assert.match(read('src/zn/use-work-reconnection.ts'), /if \(shouldDiscardZnWorkProgress\(thread, progress, submissionBusy\)\) onProgress\(null\)/)
})

test('read-only reconnect survives disconnect and delivers completion without resubmitting', async () => {
  const { observeZnWorkProgress } = await loadReconnectionModules()
  vi.useFakeTimers()
  const updates: ProgressResult[] = []
  const errors: Error[] = []
  let reads = 0
  const reader = vi.fn(async () => {
    reads += 1
    if (reads === 1) throw new Error('transport disconnected')
    return progressResult({ terminal: true, finalized: true })
  })
  const stop = observeZnWorkProgress(activeRun, reader, update => updates.push(update), error => errors.push(error))
  try {
    await vi.advanceTimersByTimeAsync(0)
    assert.equal(errors.length, 1)
    await vi.advanceTimersByTimeAsync(1400)
    assert.equal(updates.length, 1)
    assert.equal(updates[0].progress.finalized, true)
    await vi.advanceTimersByTimeAsync(10000)
    assert.equal(reader.mock.calls.length, 2)
    for (const args of reader.mock.calls) assert.deepEqual(args, ['thread-a', 'event-a'])
  } finally { stop(); vi.useRealTimers() }
})

test('cleanup ignores late replies and keeps only one outstanding progress request', async () => {
  const { observeZnWorkProgress } = await loadReconnectionModules()
  vi.useFakeTimers()
  let resolve!: (result: ProgressResult) => void
  const reader = vi.fn(() => new Promise<ProgressResult>(done => { resolve = done }))
  const updates = vi.fn()
  const errors = vi.fn()
  const stop = observeZnWorkProgress(activeRun, reader, updates, errors)
  try {
    await vi.advanceTimersByTimeAsync(10000)
    assert.equal(reader.mock.calls.length, 1)
    stop()
    resolve(progressResult())
    await vi.advanceTimersByTimeAsync(10000)
    assert.equal(updates.mock.calls.length, 0)
    assert.equal(errors.mock.calls.length, 0)
    assert.equal(reader.mock.calls.length, 1)
  } finally { stop(); vi.useRealTimers() }
})

test('mismatched progress identity cannot overwrite the selected Work', async () => {
  const { observeZnWorkProgress } = await loadReconnectionModules()
  vi.useFakeTimers()
  const updates = vi.fn()
  const errors = vi.fn()
  const stop = observeZnWorkProgress(activeRun, async () => progressResult({ eventId: 'other-event' }), updates, errors)
  try {
    await vi.advanceTimersByTimeAsync(0)
    assert.equal(updates.mock.calls.length, 0)
    assert.equal(errors.mock.calls.length, 1)
    assert.match(errors.mock.calls[0][0].message, /different Work event/)
  } finally { stop(); vi.useRealTimers() }
})

test('inspection stops observation without inventing terminal Work truth', async () => {
  const { observeZnWorkProgress } = await loadReconnectionModules()
  vi.useFakeTimers()
  const result = progressResult({ stage: 'inspection_complete' })
  const reader = vi.fn(async () => result)
  const updates = vi.fn()
  const stop = observeZnWorkProgress(activeRun, reader, updates, assert.fail)
  try {
    await vi.advanceTimersByTimeAsync(10000)
    assert.equal(reader.mock.calls.length, 1)
    assert.equal(updates.mock.calls.length, 1)
    assert.equal(result.progress.terminal, false)
    assert.equal(result.progress.finalized, false)
  } finally { stop(); vi.useRealTimers() }
})

test('actual renderer client normalizes active Work and reconnects through existing read RPC only', async () => {
  const { loadZnWorkThreads, loadZnWorkProgress } = await loadReconnectionModules()
  const workStart = vi.fn()
  const workProgress = vi.fn(async () => ({ progress: {
    event_id: 'event-a', thread_id: 'thread-a', status: 'processing',
    stage: 'side_effect_recovery', next_action: 'await decision', terminal: false,
    finalized: false, recovery: { status: 'uncertain', kind: 'command',
      decision: 'user_decision_required', replay_blocked: true }
  } }))
  vi.stubGlobal('window', { znDesktop: { resident: {
    workList: async () => [{ id: 'thread-a', messages: [], artifacts: [],
      active_run: { thread_id: 'thread-a', event_id: 'event-a' } }],
    workProgress, workStart
  } } })
  try {
    const threads = await loadZnWorkThreads()
    assert.deepEqual(threads[0].activeRun, activeRun)
    const result = await loadZnWorkProgress(activeRun.threadId, activeRun.eventId)
    assert.equal(result.progress.recovery?.replayBlocked, true)
    assert.equal(workStart.mock.calls.length, 0)
    assert.equal(workProgress.mock.calls.length, 1)
    assert.match(read('src/zn/workbench.tsx'), /const busy = useZnWorkReconnection\(/)
    assert.match(read('src/zn/use-work-reconnection.ts'), /if \(submissionBusy \|\| !threadId \|\| !eventId\) return/)
    assert.doesNotMatch(read('src/zn/use-work-reconnection.ts'), /startZnWork|submitZnWork|workStart/)
  } finally { vi.unstubAllGlobals() }
})
