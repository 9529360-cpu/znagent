import { describe, expect, it } from 'vitest'

import {
  actionableZnMaintenanceReports,
  normalizeZnMaintenanceReportStatus,
  znMaintenanceReportAction,
  type ZnMaintenanceReport
} from './maintenance-report-policy'

function report(state: string): ZnMaintenanceReport {
  return {
    reportKey: 'report-1',
    state,
    dispatchAttempts: 1,
    failureClass: 'body:command',
    exceptionType: 'AssertionError'
  }
}

describe('maintenance report operator policy', () => {
  it('allows dispatch only for pending reports', () => {
    expect(znMaintenanceReportAction(report('pending'))).toBe('dispatch')
    expect(znMaintenanceReportAction(report('delivered'))).toBeNull()
  })

  it('allows reconciliation rather than replay for outcome-uncertain reports', () => {
    expect(znMaintenanceReportAction(report('outcome_uncertain'))).toBe('reconcile')
    expect(znMaintenanceReportAction(report('outcome_uncertain'))).not.toBe('dispatch')
  })

  it('fails closed for unknown report states', () => {
    expect(znMaintenanceReportAction(report('dispatching'))).toBeNull()
    expect(znMaintenanceReportAction(report('future_state'))).toBeNull()
  })

  it('normalizes only reports with an identity and state', () => {
    const status = normalizeZnMaintenanceReportStatus({
      upstream_bug_reports: {
        available: true,
        transport_available: true,
        reports: [
          {
            report_key: 'report-1',
            state: 'outcome_uncertain',
            dispatch_attempts: 2,
            failure_class: 'body:command',
            exception_type: 'TimeoutError'
          },
          { report_key: '', state: 'pending' },
          { report_key: 'report-2', state: '' }
        ]
      }
    })

    expect(status).toEqual({
      available: true,
      transportAvailable: true,
      reports: [{
        reportKey: 'report-1',
        state: 'outcome_uncertain',
        dispatchAttempts: 2,
        failureClass: 'body:command',
        exceptionType: 'TimeoutError'
      }]
    })
    expect(actionableZnMaintenanceReports(status)).toHaveLength(1)
  })

  it('fails closed when the resident does not expose report status', () => {
    expect(normalizeZnMaintenanceReportStatus({ queue_depth: 0 })).toBeNull()
    expect(actionableZnMaintenanceReports(null)).toEqual([])
  })
})
