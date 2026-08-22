import assert from 'node:assert/strict'

import { afterEach, beforeEach, test, vi } from 'vitest'

const desiredRuntimeId = 'runtime-n-plus-1'

const mocks = vi.hoisted(() => {
  const order: string[] = []
  const resident = {
    runtimeIdentity: {
      runtimeId: 'runtime-n',
      python: '/opt/ZN/runtime-n/python'
    },
    start: vi.fn(),
    request: vi.fn(),
    restart: vi.fn(),
    stop: vi.fn(),
    disconnect: vi.fn()
  }
  return {
    order,
    resident,
    ensureAutostart: vi.fn(),
    appOn: vi.fn(),
    ipcHandle: vi.fn()
  }
})

vi.mock('electron', () => ({
  app: { on: mocks.appOn },
  ipcMain: { handle: mocks.ipcHandle }
}))

vi.mock('./zn-resident-autostart', () => ({
  ensureZnResidentAutostart: mocks.ensureAutostart
}))

vi.mock('./zn-resident-process', () => ({
  defaultZnResidentLaunch: vi.fn(() => ({})),
  ZnResidentProcess: function MockZnResidentProcess() {
    return mocks.resident
  }
}))

import { startZnResidentOnDesktopReady } from './zn-resident-ipc'

function idleStatus() {
  return {
    queue_depth: 0,
    working_state: { current_event_id: null },
    self: { current_situation: { active_event_id: null } }
  }
}

function busyStatus() {
  return {
    queue_depth: 1,
    working_state: { current_event_id: null },
    self: { current_situation: { active_event_id: null } }
  }
}

beforeEach(() => {
  vi.useFakeTimers()
  process.env.ZN_RUNTIME_ID = desiredRuntimeId
  mocks.order.length = 0
  mocks.resident.runtimeIdentity = {
    runtimeId: 'runtime-n',
    python: '/opt/ZN/runtime-n/python'
  }
  mocks.resident.start.mockReset().mockImplementation(async () => {
    mocks.order.push('start')
    return idleStatus()
  })
  mocks.resident.request.mockReset()
  mocks.resident.restart.mockReset().mockImplementation(async () => {
    mocks.order.push('restart')
    mocks.resident.runtimeIdentity = {
      runtimeId: desiredRuntimeId,
      python: '/opt/ZN/runtime-n-plus-1/python'
    }
    return idleStatus()
  })
  mocks.resident.stop.mockReset()
  mocks.resident.disconnect.mockReset()
  mocks.ensureAutostart.mockReset().mockImplementation(async () => {
    mocks.order.push('autostart')
  })
  vi.spyOn(console, 'error').mockImplementation(() => {})
  vi.spyOn(console, 'info').mockImplementation(() => {})
  vi.spyOn(console, 'warn').mockImplementation(() => {})
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
  delete process.env.ZN_RUNTIME_ID
})

test('desktop startup defers an N to N+1 handoff while resident-owned work remains busy', async () => {
  mocks.resident.start.mockImplementationOnce(async () => {
    mocks.order.push('start')
    return busyStatus()
  })

  await startZnResidentOnDesktopReady()

  assert.deepEqual(mocks.order, ['start', 'autostart'])
  assert.equal(mocks.resident.restart.mock.calls.length, 0)
})

test('desktop startup refreshes future autostart before an idle N to N+1 restart', async () => {
  await startZnResidentOnDesktopReady()
  await Promise.resolve()

  assert.deepEqual(mocks.order, ['start', 'autostart', 'restart'])
  assert.equal(mocks.resident.restart.mock.calls.length, 1)
  assert.equal(mocks.resident.runtimeIdentity.runtimeId, desiredRuntimeId)
})

test('desktop startup keeps N active when the future autostart target cannot be refreshed', async () => {
  mocks.ensureAutostart.mockImplementationOnce(async () => {
    mocks.order.push('autostart')
    throw new Error('autostart write failed')
  })

  await startZnResidentOnDesktopReady()
  await Promise.resolve()

  assert.deepEqual(mocks.order, ['start', 'autostart'])
  assert.equal(mocks.resident.restart.mock.calls.length, 0)
  assert.equal(mocks.resident.runtimeIdentity.runtimeId, 'runtime-n')
})
