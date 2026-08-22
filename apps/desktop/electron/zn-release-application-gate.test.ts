import assert from 'node:assert/strict'

import { afterEach, beforeEach, test, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  quit: vi.fn(),
  checkReadiness: vi.fn()
}))

vi.mock('electron', () => ({
  app: { quit: mocks.quit }
}))

vi.mock('./zn-resident-update-readiness', () => ({
  checkZnResidentApplicationUpdateReadiness: mocks.checkReadiness
}))

import { applyZnReleaseInstallerWithResidentGate } from './zn-release-application-gate'

beforeEach(() => {
  vi.useFakeTimers()
  mocks.quit.mockReset()
  mocks.checkReadiness.mockReset()
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
})

test('release application can replace the desktop while resident-owned work remains busy', async () => {
  const order: string[] = []
  const handoff = vi.fn(async () => {
    order.push('handoff')
  })
  mocks.checkReadiness.mockImplementation(async () => {
    order.push('readiness')
    return {
      ready: true,
      reason: 'busy',
      message: 'desktop can update while resident runtime handoff remains deferred'
    }
  })
  mocks.quit.mockImplementation(() => {
    order.push('quit')
  })

  const result = await applyZnReleaseInstallerWithResidentGate({ version: '0.18.0', handoff })

  assert.deepEqual(result, { ok: true, message: 'installing ZN 0.18.0' })
  assert.deepEqual(order, ['readiness', 'handoff'])
  assert.equal(mocks.quit.mock.calls.length, 0)

  await vi.advanceTimersByTimeAsync(100)
  assert.deepEqual(order, ['readiness', 'handoff', 'quit'])
})

test('release application hands off installer and quits after an idle readiness check', async () => {
  const order: string[] = []
  const handoff = vi.fn(async () => {
    order.push('handoff')
  })
  mocks.checkReadiness.mockImplementation(async () => {
    order.push('readiness')
    return {
      ready: true,
      reason: 'idle',
      message: 'resident idle'
    }
  })
  mocks.quit.mockImplementation(() => {
    order.push('quit')
  })

  const result = await applyZnReleaseInstallerWithResidentGate({ version: '0.18.0', handoff })

  assert.deepEqual(result, { ok: true, message: 'installing ZN 0.18.0' })
  assert.deepEqual(order, ['readiness', 'handoff'])
  assert.equal(mocks.quit.mock.calls.length, 0)

  await vi.advanceTimersByTimeAsync(100)
  assert.deepEqual(order, ['readiness', 'handoff', 'quit'])
})

test('release application fails closed when resident readiness cannot be verified', async () => {
  const handoff = vi.fn()
  mocks.checkReadiness.mockResolvedValue({
    ready: false,
    reason: 'unavailable',
    message: 'resident status unavailable'
  })

  const result = await applyZnReleaseInstallerWithResidentGate({ version: '0.18.0', handoff })

  assert.deepEqual(result, {
    ok: false,
    error: 'resident-unavailable',
    message: 'resident status unavailable'
  })
  assert.equal(handoff.mock.calls.length, 0)
  assert.equal(mocks.quit.mock.calls.length, 0)
})
