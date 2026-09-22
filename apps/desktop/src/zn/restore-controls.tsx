import type { TFunction } from 'i18next'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import {
  approveZnMissingWorkRestore,
  prepareZnMissingWorkRestore
} from './resident-client'
import type { ZnRestoreApplication, ZnRestorePoint } from './state'

type Props = {
  threadId: string
  point: ZnRestorePoint
  disabled?: boolean
  onRealityChanged: () => void | Promise<void>
}

function statusLabel(application: ZnRestoreApplication, t: TFunction): string {
  if (application.status === 'approval_required') return t('restore.application.approvalRequired')
  if (application.status === 'recovery_required') return t('restore.application.recoveryRequired')
  if (application.status === 'completed') return t('restore.application.completed')
  if (application.status === 'blocked') return application.error || t('restore.application.blocked')
  return t('restore.application.state', { status: application.status })
}

export function ZnMissingRestoreControls({ threadId, point, disabled, onRealityChanged }: Props) {
  const { t } = useTranslation()
  const [application, setApplication] = useState<ZnRestoreApplication | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const available = Boolean(
    point.currentStatus === 'missing' &&
    point.restoreApplicationAvailable &&
    point.proposal?.applicationAvailable &&
    point.proposal.applicationScope === 'missing_target_no_replace'
  )
  if (!available) return null

  const prepare = async () => {
    if (busy || disabled) return
    setBusy(true)
    setError(null)
    try {
      setApplication(await prepareZnMissingWorkRestore(threadId, point.id))
    } catch (value) {
      setApplication(null)
      setError(value instanceof Error ? value.message : String(value))
      await onRealityChanged()
    } finally {
      setBusy(false)
    }
  }

  const approve = async () => {
    if (!application || busy || disabled || !application.requiresUserApproval) return
    setBusy(true)
    setError(null)
    try {
      const result = await approveZnMissingWorkRestore(threadId, application.id)
      setApplication(result)
      await onRealityChanged()
    } catch (value) {
      // Approval failure means fresh resident reality invalidated this approval
      // context. Never keep presenting a stale/blocked application id as reusable.
      setApplication(null)
      setError(value instanceof Error ? value.message : String(value))
      await onRealityChanged()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="zn-restore-controls">
      <div className="zn-muted zn-small">
        {t('restore.controls.description')}
      </div>
      {!application ? (
        <button type="button" disabled={busy || disabled} onClick={() => void prepare()}>
          {busy ? t('restore.controls.preparing') : t('restore.controls.prepare')}
        </button>
      ) : application.requiresUserApproval ? (
        <>
          <div className="zn-muted zn-small">{statusLabel(application, t)}</div>
          <button className="zn-primary" type="button" disabled={busy || disabled} onClick={() => void approve()}>
            {busy ? t('restore.controls.restoring') : t('restore.controls.approve')}
          </button>
        </>
      ) : (
        <div className="zn-muted zn-small">{statusLabel(application, t)}</div>
      )}
      {error ? <div className="zn-error-text">{error}</div> : null}
    </div>
  )
}
