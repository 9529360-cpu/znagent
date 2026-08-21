import { useCallback, useEffect, useState } from 'react'

import { openExternalLink } from '@/lib/external-link'

const CHECK_EVERY_MS = 6 * 60 * 60 * 1000

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
    const timer = window.setInterval(() => void check(), CHECK_EVERY_MS)
    return () => window.clearInterval(timer)
  }, [check])

  if (!status?.updateAvailable) return null

  const version = status.availableVersion || 'new version'
  const title = error || status.message || `ZN ${version} is available`

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
    <button
      className="inline-flex h-full items-center gap-1.5 px-1.5 text-[0.6875rem] font-medium text-(--ui-text-secondary) transition-colors hover:bg-(--chrome-action-hover) hover:text-foreground disabled:opacity-60"
      disabled={applying}
      onClick={() => void act()}
      title={title}
      type="button"
    >
      <span aria-hidden="true" className="size-1.5 animate-pulse rounded-full bg-(--ui-accent-foreground)" />
      <span>{applying ? 'Installing ZN…' : status.supported ? `Update ZN ${version}` : `ZN ${version} available`}</span>
    </button>
  )
}
