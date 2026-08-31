import { useCallback, useEffect, useMemo, useState } from 'react'

type ReportState = 'pending' | 'outcome_uncertain' | 'delivered' | string

type MaintenanceReport = {
  reportKey: string
  state: ReportState
  dispatchAttempts: number
  failureClass: string
  exceptionType: string
}

type MaintenanceReportStatus = {
  available: boolean
  transportAvailable: boolean
  reports: MaintenanceReport[]
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function normalizeStatus(value: unknown): MaintenanceReportStatus | null {
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

function shortKey(value: string): string {
  return value.length > 12 ? `${value.slice(0, 12)}…` : value
}

export function ZnMaintenanceReportControls() {
  const [status, setStatus] = useState<MaintenanceReportStatus | null>(null)
  const [busyKey, setBusyKey] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const next = normalizeStatus(await window.znDesktop.resident.status())
      setStatus(next)
    } catch (error) {
      setStatus(null)
      setNotice(error instanceof Error ? error.message : String(error))
    }
  }, [])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), 12_000)
    return () => window.clearInterval(timer)
  }, [refresh])

  const actionable = useMemo(
    () => status?.reports.filter(report =>
      report.state === 'pending' || report.state === 'outcome_uncertain'
    ) || [],
    [status]
  )

  const act = useCallback(async (report: MaintenanceReport) => {
    if (!status?.transportAvailable || busyKey) return
    setBusyKey(report.reportKey)
    setNotice(null)
    try {
      if (report.state === 'pending') {
        await window.znDesktop.resident.upstreamBugReportDispatch({ reportKey: report.reportKey })
        setNotice('Report delivery acknowledged.')
      } else if (report.state === 'outcome_uncertain') {
        await window.znDesktop.resident.upstreamBugReportReconcile({ reportKey: report.reportKey })
        setNotice('Report outcome reconciled from receiver evidence.')
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error))
    } finally {
      await refresh()
      setBusyKey('')
    }
  }, [busyKey, refresh, status?.transportAvailable])

  if (!status || actionable.length === 0) return null

  return (
    <aside
      aria-label="Maintenance reports"
      style={{
        position: 'fixed',
        right: 20,
        bottom: 20,
        zIndex: 1000,
        width: 340,
        maxHeight: '60vh',
        overflow: 'auto',
        padding: 16,
        border: '1px solid rgba(255,255,255,0.14)',
        borderRadius: 12,
        background: 'rgba(15,17,21,0.97)',
        boxShadow: '0 16px 44px rgba(0,0,0,0.36)'
      }}
    >
      <strong>Maintenance reports</strong>
      <p className="zn-muted zn-small">
        Reports remain local until you explicitly send them. An uncertain external outcome is never resent blindly.
      </p>
      {!status.available ? (
        <div className="zn-error-text">The durable report outbox is unavailable.</div>
      ) : !status.transportAvailable ? (
        <div className="zn-setting-state">Report transport is not configured. Reports remain local.</div>
      ) : null}
      {actionable.map(report => (
        <div className="zn-setting-state" key={report.reportKey} style={{ marginTop: 10 }}>
          <div>
            <strong>{shortKey(report.reportKey)}</strong> · {report.state}
          </div>
          <div className="zn-muted zn-small">
            {report.failureClass || 'maintenance defect'}
            {report.exceptionType ? ` · ${report.exceptionType}` : ''}
            {` · attempts ${report.dispatchAttempts}`}
          </div>
          {report.state === 'pending' ? (
            <button
              type="button"
              disabled={!status.transportAvailable || Boolean(busyKey)}
              onClick={() => void act(report)}
              style={{ marginTop: 8 }}
            >
              {busyKey === report.reportKey ? 'Sending…' : 'Send report'}
            </button>
          ) : report.state === 'outcome_uncertain' ? (
            <button
              type="button"
              disabled={!status.transportAvailable || Boolean(busyKey)}
              onClick={() => void act(report)}
              style={{ marginTop: 8 }}
            >
              {busyKey === report.reportKey ? 'Reconciling…' : 'Reconcile outcome'}
            </button>
          ) : null}
        </div>
      ))}
      {notice ? <div className="zn-setting-state" style={{ marginTop: 10 }}>{notice}</div> : null}
    </aside>
  )
}
