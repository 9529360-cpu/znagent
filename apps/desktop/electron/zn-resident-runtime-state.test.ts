import { describe, expect, it } from 'vitest'

import { describeZnResidentRuntime } from './zn-resident-runtime-state'

const identity = {
  runtimeId: 'runtime-n',
  python: '/opt/ZN/runtime-n/python'
}

const desiredRuntimeId = 'runtime-n-plus-1'

describe('describeZnResidentRuntime', () => {
  it('keeps a runtime handoff pending while durable resident work is queued', () => {
    const relation = describeZnResidentRuntime(identity, desiredRuntimeId, {
      queue_depth: 1,
      working_state: { current_event_id: null },
      self: { current_situation: { active_event_id: null } }
    })

    expect(relation).toMatchObject({
      state: 'pending',
      desiredRuntimeId,
      activeRuntimeId: 'runtime-n',
      busy: true
    })
  })

  it('allows an idle runtime mismatch to proceed once the durable queue is empty', () => {
    const relation = describeZnResidentRuntime(identity, desiredRuntimeId, {
      queue_depth: 0,
      working_state: { current_event_id: null },
      self: { current_situation: { active_event_id: null } }
    })

    expect(relation.state).toBe('pending')
    expect(relation.busy).toBe(false)
  })

  it('keeps a claimed resident event busy after it leaves the pending queue', () => {
    const relation = describeZnResidentRuntime(identity, desiredRuntimeId, {
      queue_depth: 0,
      working_state: { current_event_id: 'evt-active' },
      self: { current_situation: { active_event_id: null } }
    })

    expect(relation.state).toBe('pending')
    expect(relation.busy).toBe(true)
  })
})
