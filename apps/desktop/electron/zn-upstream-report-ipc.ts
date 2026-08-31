import { ipcMain } from 'electron'

import { getZnResidentProcess } from './zn-resident-ipc'

let registered = false

function reportKey(payload: unknown): string {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error('reportKey is required')
  }
  const values = payload as Record<string, unknown>
  const key = String(values.reportKey || values.report_key || '').trim()
  if (!key) throw new Error('reportKey is required')
  return key
}

export function registerZnUpstreamReportIpc(): void {
  if (registered) return
  registered = true

  ipcMain.handle('zn:resident:upstream-bug-report-dispatch', async (_event, payload) => {
    return getZnResidentProcess().request('upstream_bug_report_dispatch', {
      report_key: reportKey(payload)
    })
  })

  ipcMain.handle('zn:resident:upstream-bug-report-reconcile', async (_event, payload) => {
    return getZnResidentProcess().request('upstream_bug_report_reconcile', {
      report_key: reportKey(payload)
    })
  })
}
