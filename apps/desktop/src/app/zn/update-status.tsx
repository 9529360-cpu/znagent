import { useCallback, useEffect, useMemo, useState } from 'react'

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { openExternalLink } from '@/lib/external-link'

const CHECK_EVERY_MS = 6 * 60 * 60 * 1000
const ACTIVE_DOWNLOAD_CHECK_MS = 2_000

function NoteSection({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null

  return (
    <section className="space-y-1">
      <h4 className="text-[0.6875rem] font-semibold text-foreground">{title}</h4>
      <ul className="space-y-0.5 pl-4 text-[0.6875rem] leading-4 text-(--ui-text-secondary)">
        {items.map(item => (
          <li className="list-disc" key={item}>
            {item}
          </li>
        ))}
      </ul>
    </section>
  )
}

function formatDownload(status: ZnDesktopUpdateStatus): string | null {
  if (status.downloadState === 'ready') return 'Downloaded and verified. Ready to install.'
  if (status.downloadState === 'failed') return status.downloadError || 'Background download failed.'
  if (status.downloadState !== 'downloading') return null

  const downloaded = Number(status.downloadedBytes || 0)
  const total = Number(status.downloadTotalBytes || 0)
  if (total <= 0) return 'Downloading update in the background…'
  const percent = Math.max(0, Math.min(100, Math.floor((downloaded / total) * 100)))
  return `Downloading update in the background… ${percent}%`
}

export function ZnUpdateStatus() {
  const [status, setStatus] = useState<ZnDesktopUpdateStatus | null>(null)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const check = useCallback(async () => {
    const updates = window.znDesktop?.updates
    if (!updates) return
    try {
      const next = await updates.check()
      setStatus(next)
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }, [])

  useEffect(() => {
    void check()
    const activeDownload = status?.updateAvailable && status.downloadState === 'downloading'
    const timer = window.setInterval(() => void check(), activeDownload ? ACTIVE_DOWNLOAD_CHECK_MS : CHECK_EVERY_MS)
    return () => window.clearInterval(timer)
  }, [check, status?.downloadState, status?.updateAvailable])

  const noteSections = useMemo(() => {
    const notes = status?.releaseNotes
    if (!notes) return []
    return [
      ['New', notes.new],
      ['Improvements', notes.improvements],
      ['Bug fixes', notes.fixes],
      ['Possible impact', notes.impact]
    ] as const
  }, [status?.releaseNotes])

  if (!status?.updateAvailable) return null

  const version = status.availableVersion || 'new version'
  const downloadText = formatDownload(status)
  const triggerText =
    status.downloadState === 'ready'
      ? `ZN ${version} ready`
      : status.downloadState === 'downloading'
        ? `Downloading ZN ${version}…`
        : `Update ZN ${version}`
  const installDisabled =
    applying ||
    (status.supported && status.downloadState === 'downloading') ||
    (!status.supported && !status.releaseUrl)
  const installText = applying
    ? 'Installing…'
    : status.downloadState === 'failed'
      ? 'Retry download and install'
      : status.downloadState === 'ready'
        ? 'Install now'
        : 'Download and install'

  const act = async () => {
    if (applying) return
    if (!status.supported) {
      if (status.releaseUrl) openExternalLink(status.releaseUrl)
      return
    }

    const updates = window.znDesktop?.updates
    if (!updates) return
    setApplying(true)
    setError(null)
    try {
      const result = await updates.apply()
      if (!result.ok) {
        setError(result.message || result.error || 'update failed')
        setApplying(false)
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
      setApplying(false)
    }
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          className="inline-flex h-full items-center gap-1.5 px-1.5 text-[0.6875rem] font-medium text-(--ui-text-secondary) transition-colors hover:bg-(--chrome-action-hover) hover:text-foreground"
          title={error || status.message || `ZN ${version} update`}
          type="button"
        >
          <span
            aria-hidden="true"
            className={`size-1.5 rounded-full bg-(--ui-accent-foreground) ${status.downloadState === 'downloading' ? 'animate-pulse' : ''}`}
          />
          <span>{triggerText}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 space-y-3 p-3" side="top">
        <div className="space-y-1">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-xs font-semibold text-foreground">ZN {version}</h3>
            <span className="text-[0.625rem] text-(--ui-text-tertiary)">Current {status.currentVersion}</span>
          </div>
          {downloadText ? <p className="text-[0.6875rem] text-(--ui-text-secondary)">{downloadText}</p> : null}
          {status.message ? <p className="text-[0.6875rem] text-(--ui-text-secondary)">{status.message}</p> : null}
          {error ? <p className="text-[0.6875rem] text-destructive">{error}</p> : null}
        </div>

        <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
          {noteSections.some(([, items]) => items.length > 0) ? (
            noteSections.map(([title, items]) => <NoteSection items={[...items]} key={title} title={title} />)
          ) : (
            <p className="text-[0.6875rem] text-(--ui-text-tertiary)">No structured release notes were published.</p>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-(--ui-stroke-secondary) pt-2">
          {status.releaseUrl ? (
            <button
              className="rounded px-2 py-1 text-[0.6875rem] text-(--ui-text-secondary) hover:bg-(--chrome-action-hover) hover:text-foreground"
              onClick={() => openExternalLink(status.releaseUrl!)}
              type="button"
            >
              Release details
            </button>
          ) : null}
          <button
            className="rounded bg-(--ui-accent) px-2.5 py-1 text-[0.6875rem] font-medium text-(--ui-accent-foreground) disabled:cursor-not-allowed disabled:opacity-50"
            disabled={installDisabled}
            onClick={() => void act()}
            type="button"
          >
            {status.supported ? installText : 'Open release'}
          </button>
        </div>
      </PopoverContent>
    </Popover>
  )
}
