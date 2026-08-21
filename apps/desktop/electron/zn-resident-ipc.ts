import { app, ipcMain } from 'electron'

import { ZnResidentProcess, defaultZnResidentLaunch } from './zn-resident-process'

let resident: ZnResidentProcess | null = null
let registered = false

export function getZnResidentProcess(): ZnResidentProcess {
  if (!resident) resident = new ZnResidentProcess(defaultZnResidentLaunch())
  return resident
}

function history(
  method: 'pulses' | 'situations' | 'thoughts' | 'impasses' | 'learning' | 'neural',
  limit: unknown
): Promise<unknown> {
  return getZnResidentProcess().request(method, { limit: Number(limit || 20) })
}

export function registerZnResidentIpc(): void {
  if (registered) return
  registered = true

  ipcMain.handle('zn:resident:start', async () => getZnResidentProcess().start())
  ipcMain.handle('zn:resident:status', async () => getZnResidentProcess().request('status'))
  ipcMain.handle('zn:resident:self', async () => getZnResidentProcess().request('self'))
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
    if (!resident) return { stopped: true }
    await resident.stop()
    resident = null
    return { stopped: true }
  })

  app.on('before-quit', () => {
    // The window is only ZN's face. Closing Electron detaches this client but
    // deliberately leaves the resident service, heartbeat, Will, and senses alive.
    resident?.disconnect()
    resident = null
  })
}

export async function startZnResidentOnDesktopReady(): Promise<void> {
  try {
    await getZnResidentProcess().start()
  } catch (error) {
    // Desktop shell remains usable when the resident cannot boot. Renderer can
    // surface the failure through zn:resident:start/status and offer repair.
    console.error('[zn-resident] failed to connect or start', error)
  }
}
