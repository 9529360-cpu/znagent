import { useCallback, useEffect, useState } from 'react'

type ResidentHealth = 'checking' | 'live' | 'offline'
type RuntimeState = 'unmanaged' | 'current' | 'pending' | 'legacy' | null

const REFRESH_MS = 12_000

function readRuntimeState(value: unknown): RuntimeState {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const desktopRuntime = (value as Record<string, unknown>).desktop_runtime
  if (!desktopRuntime || typeof desktopRuntime !== 'object' || Array.isArray(desktopRuntime)) return null
  const state = (desktopRuntime as Record<string, unknown>).state
  return state === 'unmanaged' || state === 'current' || state === 'pending' || state === 'legacy' ? state : null
}

export function ZnResidentStatus() {
  const [health, setHealth] = useState<ResidentHealth>('checking')
  const [runtimeState, setRuntimeState] = useState<RuntimeState>(null)

  const refresh = useCallback(async () => {
    const resident = window.znDesktop?.resident

    if (!resident) {
      setHealth('offline')
      setRuntimeState(null)
      return
    }

    setHealth(previous => (previous === 'live' ? previous : 'checking'))
    try {
      const status = await resident.status()
      setRuntimeState(readRuntimeState(status))
      setHealth('live')
    } catch {
      try {
        const started = await resident.start()
        const status = await resident.status()
        setRuntimeState(readRuntimeState(status) || readRuntimeState(started))
        setHealth('live')
      } catch {
        setRuntimeState(null)
        setHealth('offline')
      }
    }
  }, [])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [refresh])

  const runtimePending = health === 'live' && (runtimeState === 'pending' || runtimeState === 'legacy')
  const label =
    health === 'live'
      ? runtimePending
        ? 'resident live · runtime handoff pending'
        : 'resident live'
      : health === 'checking'
        ? 'connecting'
        : 'resident offline'
  const title =
    health === 'offline'
      ? 'ZN resident is unreachable. Click to reconnect.'
      : runtimePending
        ? 'ZN remains alive on the previous runtime until its current work is idle, then the desktop will activate the new runtime.'
        : 'Persistent ZN resident'

  return (
    <button
      className="inline-flex h-full items-center gap-1.5 px-1.5 text-[0.6875rem] text-(--ui-text-tertiary) transition-colors hover:bg-(--chrome-action-hover) hover:text-foreground"
      onClick={() => void refresh()}
      title={title}
      type="button"
    >
      <span
        aria-hidden="true"
        className={
          health === 'live'
            ? runtimePending
              ? 'size-1.5 animate-pulse rounded-full bg-(--ui-accent-foreground)'
              : 'size-1.5 rounded-full bg-(--ui-success-foreground)'
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
