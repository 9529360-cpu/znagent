import { describe, expect, it } from 'vitest'

import {
  describeZnResidentRuntime,
  ZN_FORMAL_RESIDENT_SURFACE,
  ZN_FORMAL_RESIDENT_SURFACE_SCHEMA
} from './zn-resident-runtime-state'

const identity = {
  runtimeId: 'runtime-n',
  python: '/opt/ZN/runtime-n/python'
}

const desiredRuntimeId = 'runtime-n-plus-1'
const formalSurface = {
  resident_surface: {
    name: ZN_FORMAL_RESIDENT_SURFACE,
    schema: ZN_FORMAL_RESIDENT_SURFACE_SCHEMA
  }
}

describe('describeZnResidentRuntime', () => {
  it('keeps a runtime handoff pending while durable resident work is queued', () => {
    const relation = describeZnResidentRuntime(identity, desiredRuntimeId, {
      ...formalSurface,
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
      ...formalSurface,
      queue_depth: 0,
      working_state: { current_event_id: null },
      self: { current_situation: { active_event_id: null } }
    })

    expect(relation.state).toBe('pending')
    expect(relation.busy).toBe(false)
  })

  it('keeps a claimed resident event busy after it leaves the pending queue', () => {
    const relation = describeZnResidentRuntime(identity, desiredRuntimeId, {
      ...formalSurface,
      queue_depth: 0,
      working_state: { current_event_id: 'evt-active' },
      self: { current_situation: { active_event_id: null } }
    })

    expect(relation.state).toBe('pending')
    expect(relation.busy).toBe(true)
  })

  it('accepts an exact runtime only when the formal resident surface is present', () => {
    const relation = describeZnResidentRuntime(identity, identity.runtimeId, {
      ...formalSurface,
      queue_depth: 0
    })

    expect(relation.state).toBe('current')
    expect(relation.busy).toBe(false)
  })

  it('treats the same runtime with a legacy RPC surface as needing handoff', () => {
    const relation = describeZnResidentRuntime(identity, identity.runtimeId, {
      queue_depth: 0,
      working_state: { current_event_id: null }
    })

    expect(relation.state).toBe('surface-pending')
    expect(relation.activeRuntimeId).toBe(identity.runtimeId)
    expect(relation.busy).toBe(false)
  })

  it('does not restart a capability-reduced same-runtime resident while Work is active', () => {
    const relation = describeZnResidentRuntime(identity, identity.runtimeId, {
      queue_depth: 1,
      working_state: { current_event_id: null }
    })

    expect(relation.state).toBe('surface-pending')
    expect(relation.busy).toBe(true)
  })
})
