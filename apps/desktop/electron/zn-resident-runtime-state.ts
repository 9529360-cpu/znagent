type UnknownRecord = Record<string, unknown>

export type ZnResidentRuntimeIdentity = {
  runtimeId: string | null
  python: string | null
}

export type ZnResidentRuntimeRelation = {
  state: 'unmanaged' | 'current' | 'pending' | 'legacy'
  desiredRuntimeId: string | null
  activeRuntimeId: string | null
  activePython: string | null
  busy: boolean
}

export type ZnResidentRuntimeHandoffDecision = 'none' | 'defer' | 'restart'

function asRecord(value: unknown): UnknownRecord | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as UnknownRecord) : null
}

function normalize(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function residentBusy(status: unknown): boolean {
  const root = asRecord(status)
  if (!root) return false

  const queueDepth = Number(root.queue_depth ?? 0)
  if (Number.isFinite(queueDepth) && queueDepth > 0) return true

  const working = asRecord(root.working_state)
  if (normalize(working?.current_event_id)) return true

  const self = asRecord(root.self)
  const situation = asRecord(self?.current_situation)
  return Boolean(normalize(situation?.active_event_id))
}

export function describeZnResidentRuntime(
  identity: ZnResidentRuntimeIdentity,
  desiredRuntimeId: string | null | undefined,
  status: unknown
): ZnResidentRuntimeRelation {
  const desired = normalize(desiredRuntimeId)
  const activeRuntimeId = normalize(identity.runtimeId)
  const activePython = normalize(identity.python)
  const busy = residentBusy(status)

  if (!desired) {
    return {
      state: 'unmanaged',
      desiredRuntimeId: null,
      activeRuntimeId,
      activePython,
      busy
    }
  }

  if (activeRuntimeId === desired) {
    return {
      state: 'current',
      desiredRuntimeId: desired,
      activeRuntimeId,
      activePython,
      busy
    }
  }

  return {
    state: activeRuntimeId ? 'pending' : 'legacy',
    desiredRuntimeId: desired,
    activeRuntimeId,
    activePython,
    busy
  }
}

export function decideZnResidentRuntimeHandoff(
  relation: ZnResidentRuntimeRelation
): ZnResidentRuntimeHandoffDecision {
  if (relation.state === 'unmanaged' || relation.state === 'current') return 'none'
  if (relation.busy) return 'defer'
  return 'restart'
}
