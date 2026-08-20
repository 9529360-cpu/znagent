import { app, ipcMain } from 'electron'

import { ZnResidentProcess, defaultZnResidentLaunch } from './zn-resident-process'

let resident: ZnResidentProcess | null = null
let registered = false

function getResident(): ZnResidentProcess {
  if (!resident) resident = new ZnResidentProcess(defaultZnResidentLaunch())
  return resident
}

export function registerZnResidentIpc(): void {
  if (registered) return
  registered = true

  ipcMain.handle('zn:resident:start', async () => getResident().start())
  ipcMain.handle('zn:resident:status', async () => getResident().request('status'))
  ipcMain.handle('zn:resident:self', async () => getResident().request('self'))
  ipcMain.handle('zn:resident:pulses', async (_event, limit) =>
    getResident().request('pulses', { limit: Number(limit || 20) })
  )
  ipcMain.handle('zn:resident:submit', async (_event, payload) => {
    const task = String(payload?.task || '').trim()
    if (!task) throw new Error('task is required')
    return getResident().request('submit', {
      task,
      kind: payload?.kind || 'user_task',
      priority: Number(payload?.priority || 0),
      payload: payload?.payload && typeof payload.payload === 'object' ? payload.payload : {}
    })
  })
  ipcMain.handle('zn:resident:remember', async (_event, payload) => {
    const key = String(payload?.key || '').trim()
    if (!key) throw new Error('key is required')
    return getResident().request('remember', {
      key,
      value: payload?.value,
      aliases: Array.isArray(payload?.aliases) ? payload.aliases : []
    })
  })
  ipcMain.handle('zn:resident:forget', async (_event, key) => {
    const normalized = String(key || '').trim()
    if (!normalized) throw new Error('key is required')
    return getResident().request('forget', { key: normalized })
  })
  ipcMain.handle('zn:resident:stop', async () => {
    if (!resident) return { stopped: true }
    await resident.stop()
    resident = null
    return { stopped: true }
  })

  app.on('before-quit', () => {
    void resident?.stop()
  })
}

export async function startZnResidentOnDesktopReady(): Promise<void> {
  try {
    await getResident().start()
  } catch (error) {
    // Desktop shell remains usable when the resident cannot boot. Renderer can
    // surface the failure through zn:resident:start/status and offer repair.
    console.error('[zn-resident] failed to start', error)
  }
}