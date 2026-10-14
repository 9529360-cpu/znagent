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

test('routines panel wires all six confirmations into the create flow', () => {
  const panel = read('src/zn/routines-panel.tsx')
  const localization = read('localization/zn-localization.ts')

  // The confirmation dialog shows every one of the six confirmations.
  for (const key of [
    'routines.task',
    'routines.owner',
    'routines.schedule',
    'routines.timezone',
    'routines.inputSource',
    'routines.expectedResult',
    'routines.approvalBoundary',
    'routines.missingDataPolicy',
    'routines.autoPause'
  ]) {
    assert.match(panel, new RegExp(key.replace('.', '\\.')))
    assert.ok(localization.includes(`'${key}'`), `missing i18n key ${key}`)
  }
  // The draft is only confirmed after the user reviews it; nothing
  // auto-creates a routine from the sentence alone.
  assert.match(panel, /confirmZnRoutine/)
  assert.doesNotMatch(panel, /confirmZnRoutine\(\{\s*text/)
})

test('routines panel labels a test run as real execution', () => {
  const panel = read('src/zn/routines-panel.tsx')
  const localization = read('localization/zn-localization.ts')
  assert.match(panel, /routines\.testRunWarning/)
  assert.match(localization, /Test run executes for real/)
  assert.match(localization, /试运行是真实执行/)
  assert.match(panel, /routines\.testRunConfirm/)
  // The test run goes through the same resident path as a scheduled run.
  assert.match(panel, /testRunZnRoutine/)
})

test('routines panel shows run history with failure reasons', () => {
  const panel = read('src/zn/routines-panel.tsx')
  assert.match(panel, /loadZnRoutineRuns/)
  assert.match(panel, /routines\.runs/)
  assert.match(panel, /failureReason/)
  assert.match(panel, /runStatusLabel/)
  assert.match(panel, /routines\.runScheduled/)
  assert.match(panel, /routines\.runTestRun/)
  assert.match(panel, /routines\.noRuns/)
})

test('routines panel exposes pause, resume, edit and delete', () => {
  const panel = read('src/zn/routines-panel.tsx')
  for (const action of [
    'pauseZnRoutine',
    'resumeZnRoutine',
    'editZnRoutine',
    'deleteZnRoutine',
    'acknowledgeZnRoutine'
  ]) assert.match(panel, new RegExp(action))
  assert.match(panel, /routines\.deleteConfirm/)
  assert.match(panel, /routines\.acknowledge/)
})

test('routine RPC chain is wired from preload through IPC to the client', () => {
  const preload = read('electron/zn-preload.ts')
  const ipc = read('electron/zn-resident-ipc.ts')
  const client = read('src/zn/resident-client.ts')
  for (const method of [
    'routinePropose',
    'routineConfirm',
    'routineList',
    'routineGet',
    'routineRuns',
    'routinePause',
    'routineResume',
    'routineEdit',
    'routineDelete',
    'routineTestRun',
    'routineAcknowledge'
  ]) {
    assert.match(preload, new RegExp(method))
    assert.match(client, new RegExp(method))
  }
  for (const channel of [
    'zn:resident:routine-propose',
    'zn:resident:routine-confirm',
    'zn:resident:routine-list',
    'zn:resident:routine-get',
    'zn:resident:routine-runs',
    'zn:resident:routine-pause',
    'zn:resident:routine-resume',
    'zn:resident:routine-edit',
    'zn:resident:routine-delete',
    'zn:resident:routine-test-run',
    'zn:resident:routine-acknowledge'
  ]) {
    assert.match(preload, new RegExp(channel.replace(/:/g, ':')))
    assert.match(ipc, new RegExp(channel.replace(/:/g, ':')))
  }
})

test('workbench mounts the routines panel in the sidebar', () => {
  const workbench = read('src/zn/workbench.tsx')
  assert.match(workbench, /RoutinesPanel/)
  assert.match(workbench, /sidebar\.scheduled/)
  assert.match(workbench, /routinesExpanded/)
})
