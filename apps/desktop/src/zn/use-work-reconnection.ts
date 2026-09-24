import type { TFunction } from 'i18next'
import { useEffect } from 'react'
import { loadZnWorkProgress, type ZnWorkProgress } from './resident-client'
import type { ZnThread } from './state'
import { hasZnUnfinishedWork, observeZnWorkProgress, shouldDiscardZnWorkProgress } from './work-reconnection'

type WorkReconnection = {
  thread: ZnThread | null
  submissionBusy: boolean
  progress: ZnWorkProgress | null
  onProgress: (progress: ZnWorkProgress | null) => void
  onThread: (thread: ZnThread) => void
  onError: (message: string | null) => void
  onHealth: (health: 'live' | 'connecting') => void
  t: TFunction
}

/** Reattach the existing progress card; Resident alone continues execution. */
export function useZnWorkReconnection({
  thread, submissionBusy, progress, onProgress, onThread, onError, onHealth, t
}: WorkReconnection): boolean {
  const threadId = thread?.id
  const eventId = thread?.activeRun?.eventId
  useEffect(() => {
    // work_list can observe completion before an outstanding progress read.
    // Its authoritative snapshot retires the old card; it does not complete Work.
    if (shouldDiscardZnWorkProgress(thread, progress, submissionBusy)) onProgress(null)
  }, [onProgress, progress, submissionBusy, thread])

  useEffect(() => {
    // While work_start is crossing the RPC acceptance boundary, do not attach
    // an observer to the previous activeRun. As soon as submission releases,
    // this read-only observer becomes the sole progress follower; it never
    // resubmits Work, including after steering or renderer reconnect.
    if (submissionBusy || !threadId || !eventId) return
    return observeZnWorkProgress(
      { threadId, eventId },
      loadZnWorkProgress,
      update => {
        onHealth('live')
        onError(null)
        onProgress(update.progress.finalized ? null : update.progress)
        if (update.thread) onThread(update.thread)
        if (update.progress.terminal && !update.progress.finalized) {
          onError(update.progress.error || t('error.missingDurableOutcome'))
        }
      },
      error => {
        onHealth('connecting')
        onError(t('error.desktopReconnect', { message: error.message }))
      }
    )
  }, [eventId, onError, onHealth, onProgress, onThread, submissionBusy, t, threadId])

  return submissionBusy || hasZnUnfinishedWork(thread, progress)
}
