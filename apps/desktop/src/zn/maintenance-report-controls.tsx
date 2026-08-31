import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  actionableZnMaintenanceReports,
  normalizeZnMaintenanceReportStatus,
  znMaintenanceReportAction,
  type ZnMaintenanceReport,
  type ZnMaintenanceReportStatus
} from './maintenance-report-policy'

function shortKey(value: string): string {
  return value.length > 12 ? `${value.slice(0, 12)}…` : value
}

export function ZnMaintenanceReportControls() {
  const [status, setStatus] = useState<ZnMaintenanceReportStatus | null>(null)
  const [busyKey, setBusyKey] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const next = normalizeZnMaintenanceReportStatus(await window.znDesktop.resident.status())
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

  const actionable = useMemo(() => actionableZnMaintenanceReports(status), [status])

  const act = useCallback(async (report: ZnMaintenanceReport) => {
    if (!status?.transportAvailable || busyKey) return
    const action = znMaintenanceReportAction(report)
    if (!action) return

    setBusyKey(report.reportKey)
    setNotice(null)
    try {
      if (action === 'dispatch') {
        await window.znDesktop.resident.upstreamBugReportDispatch({ reportKey: report.reportKey })
        setNotice('Report delivery acknowledged.')
      } else {
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
      {actionable.map(report => {
        const action = znMaintenanceReportAction(report)
        return (
          <div className="zn-setting-state" key={report.reportKey} style={{ marginTop: 10 }}>
            <div>
              <strong>{shortKey(report.reportKey)}</strong> · {report.state}
            </div>
            <div className="zn-muted zn-small">
              {report.failureClass || 'maintenance defect'}
              {report.exceptionType ? ` · ${report.exceptionType}` : ''}
              {` · attempts ${report.dispatchAttempts}`}
            </div>
            {action === 'dispatch' ? (
              <button
                type="button"
                disabled={!status.transportAvailable || Boolean(busyKey)}
                onClick={() => void act(report)}
                style={{ marginTop: 8 }}
              >
                {busyKey === report.reportKey ? 'Sending…' : 'Send report'}
              </button>
            ) : action === 'reconcile' ? (
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
        )
      })}
      {notice ? <div className="zn-setting-state" style={{ marginTop: 10 }}>{notice}</div> : null}
    </aside>
  )
}
