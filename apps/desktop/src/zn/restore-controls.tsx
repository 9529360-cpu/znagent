import type { TFunction } from 'i18next'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import {
  approveZnMissingWorkRestore,
  prepareZnMissingWorkRestore
} from './resident-client'
import { CdsButton, ConfirmationDialog } from './cds'
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
  const [confirmOpen, setConfirmOpen] = useState(false)
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
    setConfirmOpen(false)
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
    <div className="flex flex-col gap-2">
      <div className="text-xs text-[var(--cds-text-secondary)]">
        {t('restore.controls.description')}
      </div>
      {!application ? (
        <CdsButton type="button" disabled={busy || disabled} onClick={() => void prepare()}>
          {busy ? t('restore.controls.preparing') : t('restore.controls.prepare')}
        </CdsButton>
      ) : application.requiresUserApproval ? (
        <>
          <div className="text-xs text-[var(--cds-text-secondary)]">{statusLabel(application, t)}</div>
          <CdsButton variant="brand" type="button" disabled={busy || disabled} onClick={() => setConfirmOpen(true)}>
            {busy ? t('restore.controls.restoring') : t('restore.controls.approve')}
          </CdsButton>
          <ConfirmationDialog
            isOpen={confirmOpen}
            onClose={() => setConfirmOpen(false)}
            onConfirm={() => void approve()}
            title={t('restore.controls.approve')}
            description={t('restore.controls.description')}
            confirmLabel={t('restore.controls.approve')}
            cancelLabel={t('routines.cancel')}
            variant="danger"
            size="md"
          />
        </>
      ) : (
        <div className="text-xs text-[var(--cds-text-secondary)]">{statusLabel(application, t)}</div>
      )}
      {error ? <div className="text-sm text-[var(--cds-fill-danger)]">{error}</div> : null}
    </div>
  )
}
