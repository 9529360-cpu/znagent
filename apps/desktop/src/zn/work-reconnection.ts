import type { ZnWorkProgress, ZnWorkProgressResult } from './resident-client'
import type { ZnActiveWorkRun, ZnThread } from './state'

export function normalizeZnActiveWorkRun(value: unknown, threadId: string): ZnActiveWorkRun | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  const raw = value as Record<string, unknown>
  const eventId = typeof raw.event_id === 'string' ? raw.event_id.trim() : ''
  if (!eventId || raw.thread_id !== threadId) return undefined
  return { threadId, eventId }
}

export function hasZnUnfinishedWork(thread: ZnThread | null, progress: ZnWorkProgress | null): boolean {
  const run = thread?.activeRun
  if (!run || run.threadId !== thread?.id) return false
  const current = progress?.threadId === run.threadId && progress.eventId === run.eventId
    ? progress
    : null
  return !current?.terminal && !current?.finalized && current?.stage !== 'inspection_complete'
}

/** Retire a progress card when a newer Resident snapshot retires its event. */
export function shouldDiscardZnWorkProgress(
  thread: ZnThread | null,
  progress: ZnWorkProgress | null,
  submissionBusy: boolean
): boolean {
  if (
    submissionBusy || !thread || !progress || progress.threadId !== thread.id ||
    progress.stage === 'inspection_complete'
  ) return false
  const run = thread.activeRun
  return !run || run.threadId !== thread.id || run.eventId !== progress.eventId
}

/** Follow one Resident-owned event. This observer has no submission/replay path. */
export function observeZnWorkProgress(
  run: ZnActiveWorkRun,
  read: (threadId: string, eventId: string) => Promise<ZnWorkProgressResult>,
  onUpdate: (update: ZnWorkProgressResult) => void,
  onError: (error: Error) => void,
  intervalMs = 700
): () => void {
  let stopped = false
  let timer: ReturnType<typeof setTimeout> | undefined
  let failures = 0

  const schedule = (delay: number) => {
    if (!stopped) timer = setTimeout(() => void poll(), delay)
  }
  const poll = async () => {
    try {
      const update = await read(run.threadId, run.eventId)
      // React cleanup, thread switches and StrictMode must retire pending reads.
      if (stopped) return
      if (
        update.progress.threadId !== run.threadId ||
        update.progress.eventId !== run.eventId ||
        (update.thread && update.thread.id !== run.threadId)
      ) throw new Error('Resident returned progress for a different Work event')
      failures = 0
      onUpdate(update)
      if (
        update.progress.terminal || update.progress.finalized ||
        update.progress.stage === 'inspection_complete'
      ) {
        stopped = true
        return
      }
      schedule(intervalMs)
    } catch (error) {
      if (stopped) return
      onError(error instanceof Error ? error : new Error(String(error)))
      failures += 1
      // Retry only read-only progress, with bounded backoff; never work_start.
      schedule(Math.min(6000, intervalMs * 2 ** Math.min(failures, 4)))
    }
  }
  void poll()
  return () => {
    stopped = true
    if (timer !== undefined) clearTimeout(timer)
  }
}
