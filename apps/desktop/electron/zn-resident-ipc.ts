import { app, ipcMain } from 'electron'

import { ensureZnResidentAutostart } from './zn-resident-autostart'
import { ZnResidentProcess, defaultZnResidentLaunch } from './zn-resident-process'
import { describeZnResidentRuntime, type ZnResidentRuntimeRelation } from './zn-resident-runtime-state'

const RUNTIME_HANDOFF_RETRY_MS = 5_000
const RUNTIME_HANDOFF_MAX_WAIT_MS = 10 * 60_000

let resident: ZnResidentProcess | null = null
let registered = false
let runtimeHandoffTimer: NodeJS.Timeout | null = null
let runtimeHandoffDeadline = 0
let runtimeHandoffRunning = false

export function getZnResidentProcess(): ZnResidentProcess {
  if (!resident) resident = new ZnResidentProcess(defaultZnResidentLaunch())
  return resident
}

function runtimeRelation(residentProcess: ZnResidentProcess, status: unknown): ZnResidentRuntimeRelation {
  return describeZnResidentRuntime(residentProcess.runtimeIdentity, process.env.ZN_RUNTIME_ID, status)
}

function withDesktopRuntime(status: unknown, residentProcess: ZnResidentProcess): unknown {
  const relation = runtimeRelation(residentProcess, status)
  if (status && typeof status === 'object' && !Array.isArray(status)) {
    return { ...(status as Record<string, unknown>), desktop_runtime: relation }
  }
  return { status, desktop_runtime: relation }
}

function clearRuntimeHandoffTimer() {
  if (runtimeHandoffTimer) clearTimeout(runtimeHandoffTimer)
  runtimeHandoffTimer = null
}

function scheduleRuntimeHandoff(residentProcess: ZnResidentProcess) {
  if (runtimeHandoffTimer || Date.now() >= runtimeHandoffDeadline) return
  runtimeHandoffTimer = setTimeout(() => {
    runtimeHandoffTimer = null
    void attemptRuntimeHandoff(residentProcess)
  }, RUNTIME_HANDOFF_RETRY_MS)
}

async function attemptRuntimeHandoff(residentProcess: ZnResidentProcess, knownStatus?: unknown): Promise<void> {
  if (runtimeHandoffRunning || Date.now() >= runtimeHandoffDeadline) return
  runtimeHandoffRunning = true
  let retry = false

  try {
    const status = knownStatus ?? (await residentProcess.request('status', {}, 5_000))
    const relation = runtimeRelation(residentProcess, status)

    if (relation.state === 'unmanaged' || relation.state === 'current') {
      clearRuntimeHandoffTimer()
      return
    }

    if (relation.busy) {
      retry = true
      return
    }

    console.info(
      `[zn-resident] activating runtime ${relation.desiredRuntimeId}; ` +
        `resident currently uses ${relation.activeRuntimeId || relation.activePython || 'legacy runtime'}`
    )

    const restartedStatus = await residentProcess.restart()
    const after = runtimeRelation(residentProcess, restartedStatus)
    if (after.state === 'current') {
      clearRuntimeHandoffTimer()
      console.info(`[zn-resident] runtime ${after.desiredRuntimeId} is active`)
      return
    }

    retry = true
    console.warn(
      `[zn-resident] runtime handoff did not activate ${after.desiredRuntimeId}; ` +
        `active=${after.activeRuntimeId || after.activePython || 'unknown'}`
    )
  } catch (error) {
    retry = true
    console.error('[zn-resident] runtime handoff failed', error)
  } finally {
    runtimeHandoffRunning = false
    if (retry) scheduleRuntimeHandoff(residentProcess)
  }
}

function beginRuntimeHandoff(residentProcess: ZnResidentProcess, status: unknown) {
  const relation = runtimeRelation(residentProcess, status)
  if (relation.state === 'unmanaged' || relation.state === 'current') return

  runtimeHandoffDeadline = Date.now() + RUNTIME_HANDOFF_MAX_WAIT_MS
  clearRuntimeHandoffTimer()
  void attemptRuntimeHandoff(residentProcess, status)
}

function history(
  method: 'pulses' | 'situations' | 'thoughts' | 'impasses' | 'learning' | 'neural',
  limit: unknown
): Promise<unknown> {
  return getZnResidentProcess().request(method, { limit: Number(limit || 20) })
}

function normalizedWorkPayload(payload: any): Record<string, unknown> {
  const threadId = String(payload?.threadId || payload?.thread_id || '').trim()
  const task = String(payload?.task || '').trim()
  if (!threadId) throw new Error('threadId is required')
  if (!task) throw new Error('task is required')
  return {
    thread_id: threadId,
    task,
    kind: payload?.kind || 'desktop_user_event',
    priority: Number(payload?.priority || 0),
    payload: payload?.payload && typeof payload.payload === 'object' ? payload.payload : {}
  }
}

export function registerZnResidentIpc(): void {
  if (registered) return
  registered = true

  ipcMain.handle('zn:resident:start', async () => {
    const residentProcess = getZnResidentProcess()
    return withDesktopRuntime(await residentProcess.start(), residentProcess)
  })
  ipcMain.handle('zn:resident:status', async () => {
    const residentProcess = getZnResidentProcess()
    return withDesktopRuntime(await residentProcess.request('status'), residentProcess)
  })
  ipcMain.handle('zn:resident:self', async () => getZnResidentProcess().request('self'))
  ipcMain.handle('zn:resident:provider-settings', async () => {
    return getZnResidentProcess().request('provider_settings')
  })
  ipcMain.handle('zn:resident:provider-settings-update', async (_event, payload) => {
    const provider = String(payload?.provider || '').trim()
    const model = String(payload?.model || '').trim()
    if (!provider) throw new Error('provider is required')
    if (!model) throw new Error('model is required')
    return getZnResidentProcess().request('provider_settings_update', {
      provider,
      model,
      base_url: String(payload?.baseUrl || payload?.base_url || '').trim(),
      ...(payload?.apiKey ? { api_key: String(payload.apiKey) } : {}),
      clear_credential: payload?.clearCredential === true
    })
  })
  ipcMain.handle('zn:resident:work-list', async (_event, payload) => {
    return getZnResidentProcess().request('work_list', {
      limit: Number(payload?.limit || 24),
      message_limit: Number(payload?.messageLimit || payload?.message_limit || 120)
    })
  })
  ipcMain.handle('zn:resident:work-create', async (_event, payload) => {
    return getZnResidentProcess().request('work_create', {
      thread_id: String(payload?.threadId || payload?.thread_id || ''),
      title: String(payload?.title || 'New work'),
      metadata: payload?.metadata && typeof payload.metadata === 'object' ? payload.metadata : {}
    })
  })
  ipcMain.handle('zn:resident:work-get', async (_event, payload) => {
    const threadId = String(payload?.threadId || payload?.thread_id || '').trim()
    if (!threadId) throw new Error('threadId is required')
    return getZnResidentProcess().request('work_get', {
      thread_id: threadId,
      message_limit: Number(payload?.messageLimit || payload?.message_limit || 120)
    })
  })
  ipcMain.handle('zn:resident:work-start', async (_event, payload) => {
    return getZnResidentProcess().request('work_start', normalizedWorkPayload(payload))
  })
  ipcMain.handle('zn:resident:work-progress', async (_event, payload) => {
    const threadId = String(payload?.threadId || payload?.thread_id || '').trim()
    const eventId = String(payload?.eventId || payload?.event_id || '').trim()
    if (!threadId) throw new Error('threadId is required')
    if (!eventId) throw new Error('eventId is required')
    return getZnResidentProcess().request('work_progress', {
      thread_id: threadId,
      event_id: eventId,
      message_limit: Number(payload?.messageLimit || payload?.message_limit || 120)
    })
  })
  ipcMain.handle('zn:resident:work-cancel', async (_event, payload) => {
    const threadId = String(payload?.threadId || payload?.thread_id || '').trim()
    const eventId = String(payload?.eventId || payload?.event_id || '').trim()
    if (!threadId) throw new Error('threadId is required')
    if (!eventId) throw new Error('eventId is required')
    return getZnResidentProcess().request('work_cancel', {
      thread_id: threadId,
      event_id: eventId,
      message_limit: Number(payload?.messageLimit || payload?.message_limit || 120)
    })
  })
  ipcMain.handle('zn:resident:work-submit', async (_event, payload) => {
    return getZnResidentProcess().request('work_submit', normalizedWorkPayload(payload))
  })
  ipcMain.handle('zn:resident:work-restore-prepare', async (_event, payload) => {
    const threadId = String(payload?.threadId || payload?.thread_id || '').trim()
    const restorePointId = String(payload?.restorePointId || payload?.restore_point_id || '').trim()
    if (!threadId) throw new Error('threadId is required')
    if (!restorePointId) throw new Error('restorePointId is required')
    return getZnResidentProcess().request('work_restore_prepare', {
      thread_id: threadId,
      restore_point_id: restorePointId
    })
  })
  ipcMain.handle('zn:resident:work-restore-approve', async (_event, payload) => {
    const threadId = String(payload?.threadId || payload?.thread_id || '').trim()
    const applicationId = String(payload?.applicationId || payload?.application_id || '').trim()
    if (!threadId) throw new Error('threadId is required')
    if (!applicationId) throw new Error('applicationId is required')
    return getZnResidentProcess().request('work_restore_approve', {
      thread_id: threadId,
      application_id: applicationId
    })
  })
  ipcMain.handle('zn:resident:work-restore-application', async (_event, payload) => {
    const applicationId = String(payload?.applicationId || payload?.application_id || '').trim()
    if (!applicationId) throw new Error('applicationId is required')
    return getZnResidentProcess().request('work_restore_application', {
      application_id: applicationId
    })
  })
  ipcMain.handle('zn:resident:pulses', async (_event, limit) => history('pulses', limit))
  ipcMain.handle('zn:resident:situations', async (_event, limit) => history('situations', limit))
  ipcMain.handle('zn:resident:thoughts', async (_event, limit) => history('thoughts', limit))
  ipcMain.handle('zn:resident:impasses', async (_event, limit) => history('impasses', limit))
  ipcMain.handle('zn:resident:learning', async (_event, limit) => history('learning', limit))
  ipcMain.handle('zn:resident:neural', async (_event, limit) => history('neural', limit))
  ipcMain.handle('zn:resident:perceive', async (_event, payload) => {
    const summary = String(payload?.summary || '').trim()
    if (!summary) throw new Error('summary is required')
    return getZnResidentProcess().request('perceive', {
      channel: String(payload?.channel || 'sense'),
      summary,
      source: String(payload?.source || payload?.channel || 'sense'),
      features: Array.isArray(payload?.features) ? payload.features : [],
      salience: Number(payload?.salience ?? 0.5),
      valence: Number(payload?.valence ?? 0),
      arousal: Number(payload?.arousal ?? 0.3),
      metadata: payload?.metadata && typeof payload.metadata === 'object' ? payload.metadata : {}
    })
  })
  ipcMain.handle('zn:resident:world-follow', async (_event, payload) => {
    const topic = String(payload?.topic || '').trim()
    if (!topic) throw new Error('topic is required')
    return getZnResidentProcess().request('world_follow', {
      topic,
      priority: Number(payload?.priority || 0),
      interval_seconds: Number(payload?.intervalSeconds || payload?.interval_seconds || 1800),
      source: String(payload?.source || 'self')
    })
  })
  ipcMain.handle('zn:resident:world-focuses', async (_event, payload) => {
    return getZnResidentProcess().request('world_focuses', {
      limit: Number(payload?.limit || 20),
      enabled_only: payload?.enabledOnly !== false
    })
  })
  ipcMain.handle('zn:resident:world-observe', async (_event, payload) => {
    const focusId = String(payload?.focusId || payload?.focus_id || '').trim()
    if (!focusId) throw new Error('focusId is required')
    return getZnResidentProcess().request('world_observe', {
      focus_id: focusId,
      limit: Number(payload?.limit || 5)
    })
  })
  ipcMain.handle('zn:resident:submit', async (_event, payload) => {
    const task = String(payload?.task || '').trim()
    if (!task) throw new Error('task is required')
    return getZnResidentProcess().request('submit', {
      task,
      kind: payload?.kind || 'user_task',
      priority: Number(payload?.priority || 0),
      payload: payload?.payload && typeof payload.payload === 'object' ? payload.payload : {}
    })
  })
  ipcMain.handle('zn:resident:remember', async (_event, payload) => {
    const key = String(payload?.key || '').trim()
    if (!key) throw new Error('key is required')
    return getZnResidentProcess().request('remember', {
      key,
      value: payload?.value,
      aliases: Array.isArray(payload?.aliases) ? payload.aliases : []
    })
  })
  ipcMain.handle('zn:resident:forget', async (_event, key) => {
    const normalized = String(key || '').trim()
    if (!normalized) throw new Error('key is required')
    return getZnResidentProcess().request('forget', { key: normalized })
  })
  ipcMain.handle('zn:resident:stop', async () => {
    clearRuntimeHandoffTimer()
    if (!resident) return { stopped: true }
    await resident.stop()
    resident = null
    return { stopped: true }
  })

  app.on('before-quit', () => {
    clearRuntimeHandoffTimer()
    resident?.disconnect()
    resident = null
  })
}

export async function startZnResidentOnDesktopReady(): Promise<void> {
  try {
    const residentProcess = getZnResidentProcess()
    const status = await residentProcess.start()
    try {
      await ensureZnResidentAutostart()
    } catch (error) {
      console.error('[zn-resident] failed to install login autostart; runtime handoff deferred', error)
      return
    }
    beginRuntimeHandoff(residentProcess, status)
  } catch (error) {
    console.error('[zn-resident] failed to connect or start', error)
  }
}
