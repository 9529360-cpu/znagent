import assert from 'node:assert/strict'

import { afterEach, beforeEach, test, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  resident: {
    runtimeIdentity: {
      runtimeId: 'runtime-n',
      python: '/opt/ZN/runtime-n/python'
    },
    request: vi.fn()
  }
}))

vi.mock('./zn-resident-ipc', () => ({
  getZnResidentProcess: () => mocks.resident
}))

import { checkZnResidentApplicationUpdateReadiness } from './zn-resident-update-readiness'

beforeEach(() => {
  process.env.ZN_RUNTIME_ID = 'runtime-n-plus-1'
  mocks.resident.request.mockReset()
})

afterEach(() => {
  delete process.env.ZN_RUNTIME_ID
})

test('update readiness defers when durable resident work remains queued', async () => {
  mocks.resident.request.mockResolvedValue({
    queue_depth: 1,
    working_state: { current_event_id: null },
    self: { current_situation: { active_event_id: null } }
  })

  const result = await checkZnResidentApplicationUpdateReadiness()

  assert.equal(result.ready, false)
  assert.equal(result.reason, 'busy')
  assert.deepEqual(mocks.resident.request.mock.calls[0], ['status', {}, 5_000])
})

test('update readiness permits application only when resident status is idle', async () => {
  mocks.resident.request.mockResolvedValue({
    queue_depth: 0,
    working_state: { current_event_id: null },
    self: { current_situation: { active_event_id: null } }
  })

  const result = await checkZnResidentApplicationUpdateReadiness()

  assert.equal(result.ready, true)
  assert.equal(result.reason, 'idle')
})

test('update readiness fails closed when resident status cannot be read', async () => {
  mocks.resident.request.mockRejectedValue(new Error('resident unavailable'))

  const result = await checkZnResidentApplicationUpdateReadiness()

  assert.equal(result.ready, false)
  assert.equal(result.reason, 'unavailable')
  assert.match(result.message, /resident unavailable/)
})
