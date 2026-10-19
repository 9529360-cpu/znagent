import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { test } from 'vitest'

import {
  ZN_RECENT_ACTION_LIMIT,
  znExecutionActionsFromDetail,
  znExecutionActionsFromUnknown
} from '../src/zn/execution-timeline'

test('historical Resident activities show only bounded, well-formed actions', () => {
  const actions = Array.from({ length: 8 }, (_, i) => ({
    kind: 'inspect_' + i,
    success: i % 2 === 0,
    at: '2026-10-16T03:00:00.000Z',
    summary: 'read ' + i,
    private_command: 'unsafe arguments'
  }))
  const trace = znExecutionActionsFromDetail({ body_actions: actions })
  assert.equal(trace.length, ZN_RECENT_ACTION_LIMIT)
  assert.deepEqual(trace.map(action => action.kind), ['inspect_2', 'inspect_3', 'inspect_4', 'inspect_5', 'inspect_6', 'inspect_7'])
  assert.equal(trace[0].at, Date.parse('2026-10-16T03:00:00.000Z'))
  assert.equal(trace[1].success, false)
  assert.equal(trace[0].summary, 'read 2')
  assert.equal(JSON.stringify(trace).includes('private_command'), false)
  assert.equal(JSON.stringify(trace).includes('unsafe arguments'), false)
})

test('unknown outcomes, invalid timestamps and non-action records are never fabricated', () => {
  const trace = znExecutionActionsFromUnknown([
    { kind: 'read', success: 'true', at: 'yesterday' },
    { kind: '', success: true, at: '2026-10-16T03:00:00.000Z' },
    { kind: 'write', success: false, at: 1e300, summary: 'z'.repeat(500) },
    { kind: 'check', success: true, at: -2, summary: { secret: 'never serialise' } },
    false, null, 'invalid'
  ])
  assert.deepEqual(trace.map(action => ({ kind: action.kind, success: action.success })), [
    { kind: 'write', success: false },
    { kind: 'check', success: true }
  ])
  assert.equal(trace[0].at, undefined)
  assert.equal(trace[1].at, undefined)
  assert.equal(trace[0].summary.length, 320)
  assert.equal(trace[1].summary, '')
  assert.deepEqual(znExecutionActionsFromDetail({}), [])
  assert.deepEqual(znExecutionActionsFromUnknown({ body_actions: [] }), [])
})

test('workbench timeline is read-only and uses native disclosure, not HTML injection', () => {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
  const read = (part: string) => fs.readFileSync(path.join(root, part), 'utf8')
  const screen = read('src/zn/workbench.tsx')
  const view = read('src/zn/execution-timeline-view.tsx')
  const shell = read('src/zn/zn-claude-shell.tsx')
  assert.match(screen, /znExecutionActionsFromDetail\(message\.detail\)/)
  assert.match(screen, /className="zn-history-trace"/)
  assert.match(screen, /actions=\{workProgress\.bodyActions\}/)
  assert.match(screen, /className="zn-live-trace"/)
  assert.match(view, /<details className="zn-trace-summary">/)
  assert.match(view, /<time dateTime=\{time\.dateTime\}>/)
  assert.doesNotMatch(view, /dangerouslySetInnerHTML|eval\(|innerHTML/)
  // The new active shell is chat + pending approvals/todos only: it never
  // renders the execution timeline / ledger, and never fabricates one.
  assert.doesNotMatch(shell, /execution-timeline|zn-history-trace|zn-live-trace/)
  assert.doesNotMatch(shell, /dangerouslySetInnerHTML|eval\(|innerHTML/)
})
