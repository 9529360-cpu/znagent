import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { test } from 'vitest'

import {
  normalizeZnRecurringDisablePayload,
  normalizeZnRecurringListPayload,
  normalizeZnRecurringSchedulePayload
} from './zn-recurring-will-ipc-contract'

const here = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(here, '..')

function read(relative: string): string {
  return fs.readFileSync(path.join(desktopRoot, relative), 'utf8')
}

test('recurring schedule bridge forwards only bounded scheduling fields', () => {
  const normalized = normalizeZnRecurringSchedulePayload({
    description: '  keep project status current  ',
    task: '  inspect fresh project status  ',
    intervalSeconds: '300',
    priority: 4,
    source: ' user ',
    firstDueAt: '2026-09-17T08:00:00+08:00',
    payload: {
      command: 'must-not-cross-desktop-bridge',
      execution_authority: true
    },
    bodyAction: 'must-not-cross-desktop-bridge'
  })

  assert.deepEqual(normalized, {
    description: 'keep project status current',
    task: 'inspect fresh project status',
    interval_seconds: 300,
    source: 'user',
    priority: 4,
    first_due_at: '2026-09-17T08:00:00+08:00'
  })
  assert.equal('payload' in normalized, false)
  assert.equal('bodyAction' in normalized, false)
  assert.equal('execution_authority' in normalized, false)
})

test('recurring schedule bridge accepts snake case but rejects malformed integers', () => {
  assert.deepEqual(
    normalizeZnRecurringSchedulePayload({
      description: 'observe current state',
      task: 'inspect current state',
      interval_seconds: 60,
      first_due_at: '2026-09-17T00:00:00Z'
    }),
    {
      description: 'observe current state',
      task: 'inspect current state',
      interval_seconds: 60,
      source: 'user',
      priority: 0,
      first_due_at: '2026-09-17T00:00:00Z'
    }
  )

  assert.throws(
    () => normalizeZnRecurringSchedulePayload({
      description: 'bad interval',
      task: 'inspect current state',
      intervalSeconds: 1.5
    }),
    /intervalSeconds must be an integer/
  )
  assert.throws(
    () => normalizeZnRecurringSchedulePayload({
      description: 'bad priority',
      task: 'inspect current state',
      intervalSeconds: 60,
      priority: 'high'
    }),
    /priority must be an integer/
  )
})

test('recurring list bridge is bounded and disable requires an intention id', () => {
  assert.deepEqual(normalizeZnRecurringListPayload(undefined), {
    limit: 20,
    enabled_only: false
  })
  assert.deepEqual(normalizeZnRecurringListPayload({ limit: 500, enabledOnly: true }), {
    limit: 100,
    enabled_only: true
  })
  assert.deepEqual(normalizeZnRecurringListPayload({ enabled_only: true }), {
    limit: 20,
    enabled_only: true
  })
  assert.throws(() => normalizeZnRecurringListPayload({ limit: 0 }), /limit must be positive/)

  assert.deepEqual(normalizeZnRecurringDisablePayload({ intentionId: ' intent-1 ' }), {
    intention_id: 'intent-1'
  })
  assert.deepEqual(normalizeZnRecurringDisablePayload({ intention_id: 'intent-2' }), {
    intention_id: 'intent-2'
  })
  assert.throws(() => normalizeZnRecurringDisablePayload({}), /intentionId is required/)
})

test('recurring controls stay on the existing scoped Electron bridge', () => {
  const ipc = read('electron/zn-resident-ipc.ts')
  const residentProcess = read('electron/zn-resident-process.ts')
  const preload = read('electron/zn-preload.ts')
  const desktopEnv = read('src/zn/desktop-env.d.ts')

  assert.match(ipc, /zn:resident:recurring-schedule/)
  assert.match(ipc, /request\(\s*['"]recurring_schedule['"]/)
  assert.match(ipc, /normalizeZnRecurringSchedulePayload\(payload\)/)
  assert.match(ipc, /zn:resident:recurring-list/)
  assert.match(ipc, /request\(\s*['"]recurring_list['"]/)
  assert.match(ipc, /normalizeZnRecurringListPayload\(payload\)/)
  assert.match(ipc, /zn:resident:recurring-disable/)
  assert.match(ipc, /request\(\s*['"]recurring_disable['"]/)
  assert.match(ipc, /normalizeZnRecurringDisablePayload\(payload\)/)

  assert.match(residentProcess, /\| ['"]recurring_schedule['"]/)
  assert.match(residentProcess, /\| ['"]recurring_list['"]/)
  assert.match(residentProcess, /\| ['"]recurring_disable['"]/)

  assert.match(preload, /recurringSchedule/)
  assert.match(preload, /zn:resident:recurring-schedule/)
  assert.match(preload, /recurringList/)
  assert.match(preload, /zn:resident:recurring-list/)
  assert.match(preload, /recurringDisable/)
  assert.match(preload, /zn:resident:recurring-disable/)
  assert.doesNotMatch(preload, /exposeInMainWorld\([^)]*ipcRenderer/)

  assert.match(desktopEnv, /recurringSchedule:/)
  assert.match(desktopEnv, /recurringList:/)
  assert.match(desktopEnv, /recurringDisable:/)
})
