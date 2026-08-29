import assert from 'node:assert/strict'

import { test } from 'vitest'

import {
  ZN_RUNTIME_HANDOFF_FAILURE_BUDGET_MS,
  nextZnRuntimeHandoffDeadline,
  znRuntimeHandoffFailureBudgetExpired
} from './zn-runtime-handoff-policy'

test('active resident Work renews the finite handoff failure budget', () => {
  const originalDeadline = 1000
  const now = originalDeadline + 60_000
  const renewed = nextZnRuntimeHandoffDeadline({
    now,
    deadline: originalDeadline,
    busy: true
  })

  assert.equal(renewed, now + ZN_RUNTIME_HANDOFF_FAILURE_BUDGET_MS)
  assert.equal(znRuntimeHandoffFailureBudgetExpired(now, renewed), false)
})

test('idle resident does not silently renew an expired failure budget', () => {
  const deadline = 1000
  const now = 1001

  assert.equal(nextZnRuntimeHandoffDeadline({ now, deadline, busy: false }), deadline)
  assert.equal(znRuntimeHandoffFailureBudgetExpired(now, deadline), true)
})

test('busy renewal never shortens an existing later deadline', () => {
  const now = 1000
  const later = now + ZN_RUNTIME_HANDOFF_FAILURE_BUDGET_MS * 2

  assert.equal(
    nextZnRuntimeHandoffDeadline({ now, deadline: later, busy: true }),
    later
  )
})
