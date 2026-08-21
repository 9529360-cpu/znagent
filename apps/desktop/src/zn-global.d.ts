export {}

declare global {
  type ZnDesktopUpdateStatus = {
    supported: boolean
    currentVersion: string
    updateAvailable: boolean
    availableVersion?: string
    releaseUrl?: string
    assetName?: string
    message?: string
  }

  type ZnDesktopUpdateApplyResult = {
    ok: boolean
    message?: string
    error?: string
  }

  interface Window {
    znDesktop?: {
      resident: {
        start: () => Promise<unknown>
        stop: () => Promise<unknown>
        status: () => Promise<unknown>
        self: () => Promise<unknown>
        pulses: (limit?: number) => Promise<unknown>
        situations: (limit?: number) => Promise<unknown>
        thoughts: (limit?: number) => Promise<unknown>
        impasses: (limit?: number) => Promise<unknown>
        learning: (limit?: number) => Promise<unknown>
        neural: (limit?: number) => Promise<unknown>
        perceive: (payload: Record<string, unknown>) => Promise<unknown>
        worldFollow: (payload: Record<string, unknown>) => Promise<unknown>
        worldFocuses: (payload?: Record<string, unknown>) => Promise<unknown>
        worldObserve: (payload: Record<string, unknown>) => Promise<unknown>
        submit: (payload: Record<string, unknown>) => Promise<unknown>
        remember: (payload: Record<string, unknown>) => Promise<unknown>
        forget: (key: string) => Promise<unknown>
      }
      updates: {
        check: () => Promise<ZnDesktopUpdateStatus>
        apply: () => Promise<ZnDesktopUpdateApplyResult>
      }
    }
  }
}
