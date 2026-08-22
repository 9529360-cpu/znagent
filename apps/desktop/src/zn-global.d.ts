export {}

declare global {
  type ZnDesktopReleaseNotes = {
    new: string[]
    improvements: string[]
    fixes: string[]
    impact: string[]
  }

  type ZnDesktopUpdateStatus = {
    supported: boolean
    currentVersion: string
    updateAvailable: boolean
    availableVersion?: string
    releaseUrl?: string
    assetName?: string
    releaseNotes?: ZnDesktopReleaseNotes
    downloadState?: 'idle' | 'downloading' | 'ready' | 'failed'
    downloadedBytes?: number
    downloadTotalBytes?: number
    downloadError?: string
    message?: string
  }

  type ZnDesktopUpdateApplyResult = {
    ok: boolean
    message?: string
    error?: string
  }

  type ZnDesktopDeepLink = {
    url: string
    route: string
    path: string
    params: Record<string, string>
  }

  interface Window {
    znDesktop?: {
      resident: {
        start: () => Promise<unknown>
        stop: () => Promise<unknown>
        status: () => Promise<unknown>
        self: () => Promise<unknown>
        workList: (payload?: Record<string, unknown>) => Promise<unknown>
        workCreate: (payload?: Record<string, unknown>) => Promise<unknown>
        workGet: (payload: Record<string, unknown>) => Promise<unknown>
        workSubmit: (payload: Record<string, unknown>) => Promise<unknown>
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
      shell: {
        onDeepLink: (callback: (link: ZnDesktopDeepLink) => void) => () => void
      }
    }
  }
}
