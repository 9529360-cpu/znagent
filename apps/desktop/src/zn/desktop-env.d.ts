declare module '*.css' {
  const stylesheet: string
  export default stylesheet
}

type ZnDesktopPayload = Record<string, unknown>

type ZnDesktopDeepLink = {
  url: string
  route: string
  path: string
  params: Record<string, string>
}

type ZnDesktopUpdateStatus = {
  supported: boolean
  currentVersion: string
  updateAvailable: boolean
  availableVersion?: string
  releaseUrl?: string
  assetName?: string
  releaseNotes?: unknown
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

type ZnDesktopResidentBridge = {
  start: () => Promise<unknown>
  stop: () => Promise<unknown>
  status: () => Promise<unknown>
  self: () => Promise<unknown>
  providerSettings: () => Promise<unknown>
  providerSettingsUpdate: (payload: ZnDesktopPayload) => Promise<unknown>
  workList: (payload: ZnDesktopPayload) => Promise<unknown>
  workCreate: (payload: ZnDesktopPayload) => Promise<unknown>
  workGet: (payload: ZnDesktopPayload) => Promise<unknown>
  workStart: (payload: ZnDesktopPayload) => Promise<unknown>
  workProgress: (payload: ZnDesktopPayload) => Promise<unknown>
  workCancel: (payload: ZnDesktopPayload) => Promise<unknown>
  workSubmit: (payload: ZnDesktopPayload) => Promise<unknown>
  workRestorePrepare: (payload: ZnDesktopPayload) => Promise<unknown>
  workRestoreApprove: (payload: ZnDesktopPayload) => Promise<unknown>
  workRestoreApplication: (payload: ZnDesktopPayload) => Promise<unknown>
  pulses: (limit?: number) => Promise<unknown>
  situations: (limit?: number) => Promise<unknown>
  thoughts: (limit?: number) => Promise<unknown>
  impasses: (limit?: number) => Promise<unknown>
  learning: (limit?: number) => Promise<unknown>
  neural: (limit?: number) => Promise<unknown>
  perceive: (payload: ZnDesktopPayload) => Promise<unknown>
  worldFollow: (payload: ZnDesktopPayload) => Promise<unknown>
  worldFocuses: (payload?: ZnDesktopPayload) => Promise<unknown>
  worldObserve: (payload: ZnDesktopPayload) => Promise<unknown>
  submit: (payload: ZnDesktopPayload) => Promise<unknown>
  remember: (payload: ZnDesktopPayload) => Promise<unknown>
  forget: (key: string) => Promise<unknown>
}

declare interface Window {
  znDesktop: {
    resident: ZnDesktopResidentBridge
    workspaces: {
      attach: (threadId: string) => Promise<unknown>
      detach: (threadId: string) => Promise<unknown>
    }
    updates: {
      check: () => Promise<ZnDesktopUpdateStatus>
      apply: () => Promise<ZnDesktopUpdateApplyResult>
    }
    shell: {
      setWindowMode: (mode: 'compact' | 'expanded') => Promise<{ mode: 'compact' | 'expanded'; width: number; height: number }>
      onDeepLink: (callback: (payload: ZnDesktopDeepLink) => void) => () => void
      onGlobalInvocation: (callback: () => void) => () => void
    }
  }
}