import { getZnResidentProcess } from './zn-resident-ipc'
import { describeZnResidentRuntime } from './zn-resident-runtime-state'

export type ZnResidentApplicationUpdateReadiness = {
  ready: boolean
  reason: 'idle' | 'busy' | 'unavailable'
  message: string
}

export async function checkZnResidentApplicationUpdateReadiness(): Promise<ZnResidentApplicationUpdateReadiness> {
  const resident = getZnResidentProcess()

  try {
    const status = await resident.request('status', {}, 5_000)
    const relation = describeZnResidentRuntime(resident.runtimeIdentity, process.env.ZN_RUNTIME_ID, status)

    if (relation.busy) {
      return {
        ready: true,
        reason: 'busy',
        message:
          'ZN is still working; the desktop application can update while resident runtime handoff remains deferred until resident-owned work is idle.'
      }
    }

    return {
      ready: true,
      reason: 'idle',
      message: 'ZN resident is idle and can remain continuous across the desktop update.'
    }
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error)
    return {
      ready: false,
      reason: 'unavailable',
      message: `ZN cannot verify resident readiness for update application: ${detail}`
    }
  }
}
