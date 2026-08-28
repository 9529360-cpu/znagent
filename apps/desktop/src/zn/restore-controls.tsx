import { useState } from 'react'

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

function statusLabel(application: ZnRestoreApplication): string {
  if (application.status === 'approval_required') return 'Prepared. Explicit approval is still required.'
  if (application.status === 'recovery_required') return 'Interrupted restore needs fresh explicit approval.'
  if (application.status === 'completed') return 'Restore completed and exact retained bytes were verified.'
  if (application.status === 'blocked') return application.error || 'Restore is blocked by fresh reality.'
  return `Restore state: ${application.status}`
}

export function ZnMissingRestoreControls({ threadId, point, disabled, onRealityChanged }: Props) {
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
        This restores the retained exact bytes only if the target is still missing. It never overwrites a target that exists again.
      </div>
      {!application ? (
        <button type="button" disabled={busy || disabled} onClick={() => void prepare()}>
          {busy ? 'Preparing…' : 'Prepare restore'}
        </button>
      ) : application.requiresUserApproval ? (
        <>
          <div className="zn-muted zn-small">{statusLabel(application)}</div>
          <button className="zn-primary" type="button" disabled={busy || disabled} onClick={() => void approve()}>
            {busy ? 'Restoring…' : 'Approve exact restore'}
          </button>
        </>
      ) : (
        <div className="zn-muted zn-small">{statusLabel(application)}</div>
      )}
      {error ? <div className="zn-error-text">{error}</div> : null}
    </div>
  )
}
