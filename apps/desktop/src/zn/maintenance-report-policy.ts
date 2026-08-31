export type ZnMaintenanceReportState = 'pending' | 'outcome_uncertain' | 'delivered' | string

export type ZnMaintenanceReport = {
  reportKey: string
  state: ZnMaintenanceReportState
  dispatchAttempts: number
  failureClass: string
  exceptionType: string
}

export type ZnMaintenanceReportStatus = {
  available: boolean
  transportAvailable: boolean
  reports: ZnMaintenanceReport[]
}

export type ZnMaintenanceReportAction = 'dispatch' | 'reconcile' | null

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

export function normalizeZnMaintenanceReportStatus(value: unknown): ZnMaintenanceReportStatus | null {
  const status = record(value)
  const raw = record(status?.upstream_bug_reports)
  if (!raw) return null

  const reports = (Array.isArray(raw.reports) ? raw.reports : []).flatMap(value => {
    const item = record(value)
    if (!item) return []
    const reportKey = String(item.report_key || '').trim()
    const state = String(item.state || '').trim()
    if (!reportKey || !state) return []
    const attempts = Number(item.dispatch_attempts || 0)
    return [{
      reportKey,
      state,
      dispatchAttempts: Number.isFinite(attempts) && attempts >= 0 ? attempts : 0,
      failureClass: String(item.failure_class || ''),
      exceptionType: String(item.exception_type || '')
    }]
  })

  return {
    available: raw.available === true,
    transportAvailable: raw.transport_available === true,
    reports
  }
}

export function znMaintenanceReportAction(report: ZnMaintenanceReport): ZnMaintenanceReportAction {
  if (report.state === 'pending') return 'dispatch'
  if (report.state === 'outcome_uncertain') return 'reconcile'
  return null
}

export function actionableZnMaintenanceReports(
  status: ZnMaintenanceReportStatus | null
): ZnMaintenanceReport[] {
  if (!status) return []
  return status.reports.filter(report => znMaintenanceReportAction(report) !== null)
}
