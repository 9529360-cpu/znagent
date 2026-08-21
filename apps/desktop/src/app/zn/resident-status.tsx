import { useCallback, useEffect, useState } from 'react'

type ResidentHealth = 'checking' | 'live' | 'offline'

const REFRESH_MS = 12_000

export function ZnResidentStatus() {
  const [health, setHealth] = useState<ResidentHealth>('checking')

  const refresh = useCallback(async () => {
    const resident = window.znDesktop?.resident

    if (!resident) {
      setHealth('offline')
      return
    }

    setHealth(previous => (previous === 'live' ? previous : 'checking'))
    try {
      await resident.status()
      setHealth('live')
    } catch {
      try {
        await resident.start()
        await resident.status()
        setHealth('live')
      } catch {
        setHealth('offline')
      }
    }
  }, [])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [refresh])

  const label = health === 'live' ? 'resident live' : health === 'checking' ? 'connecting' : 'resident offline'

  return (
    <button
      className="inline-flex h-full items-center gap-1.5 px-1.5 text-[0.6875rem] text-(--ui-text-tertiary) transition-colors hover:bg-(--chrome-action-hover) hover:text-foreground"
      onClick={() => void refresh()}
      title={health === 'offline' ? 'ZN resident is unreachable. Click to reconnect.' : 'Persistent ZN resident'}
      type="button"
    >
      <span
        aria-hidden="true"
        className={
          health === 'live'
            ? 'size-1.5 rounded-full bg-(--ui-success-foreground)'
            : health === 'checking'
              ? 'size-1.5 animate-pulse rounded-full bg-(--ui-text-quaternary)'
              : 'size-1.5 rounded-full bg-(--ui-danger-foreground)'
        }
      />
      <span className="font-medium text-(--ui-text-secondary)">ZN</span>
      <span>{label}</span>
    </button>
  )
}
