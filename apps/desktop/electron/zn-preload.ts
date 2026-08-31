import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron'

type ZnDesktopPayload = Record<string, unknown>

type ZnDesktopDeepLink = {
  url: string
  route: string
  path: string
  params: Record<string, string>
}

contextBridge.exposeInMainWorld('znDesktop', {
  resident: {
    start: () => ipcRenderer.invoke('zn:resident:start'),
    stop: () => ipcRenderer.invoke('zn:resident:stop'),
    status: () => ipcRenderer.invoke('zn:resident:status'),
    self: () => ipcRenderer.invoke('zn:resident:self'),
    providerSettings: () => ipcRenderer.invoke('zn:resident:provider-settings'),
    providerSettingsUpdate: (payload?: ZnDesktopPayload) =>
      ipcRenderer.invoke('zn:resident:provider-settings-update', payload || {}),
    upstreamBugReportDispatch: (payload?: ZnDesktopPayload) =>
      ipcRenderer.invoke('zn:resident:upstream-bug-report-dispatch', payload || {}),
    upstreamBugReportReconcile: (payload?: ZnDesktopPayload) =>
      ipcRenderer.invoke('zn:resident:upstream-bug-report-reconcile', payload || {}),
    workList: (payload?: ZnDesktopPayload) => ipcRenderer.invoke('zn:resident:work-list', payload || {}),
    workCreate: (payload?: ZnDesktopPayload) => ipcRenderer.invoke('zn:resident:work-create', payload || {}),
    workGet: (payload?: ZnDesktopPayload) => ipcRenderer.invoke('zn:resident:work-get', payload || {}),
    workStart: (payload?: ZnDesktopPayload) => ipcRenderer.invoke('zn:resident:work-start', payload || {}),
    workProgress: (payload?: ZnDesktopPayload) =>
      ipcRenderer.invoke('zn:resident:work-progress', payload || {}),
    workCancel: (payload?: ZnDesktopPayload) =>
      ipcRenderer.invoke('zn:resident:work-cancel', payload || {}),
    workSubmit: (payload?: ZnDesktopPayload) => ipcRenderer.invoke('zn:resident:work-submit', payload || {}),
    workRestorePrepare: (payload?: ZnDesktopPayload) =>
      ipcRenderer.invoke('zn:resident:work-restore-prepare', payload || {}),
    workRestoreApprove: (payload?: ZnDesktopPayload) =>
      ipcRenderer.invoke('zn:resident:work-restore-approve', payload || {}),
    workRestoreApplication: (payload?: ZnDesktopPayload) =>
      ipcRenderer.invoke('zn:resident:work-restore-application', payload || {}),
    pulses: (limit?: number) => ipcRenderer.invoke('zn:resident:pulses', limit),
    situations: (limit?: number) => ipcRenderer.invoke('zn:resident:situations', limit),
    thoughts: (limit?: number) => ipcRenderer.invoke('zn:resident:thoughts', limit),
    impasses: (limit?: number) => ipcRenderer.invoke('zn:resident:impasses', limit),
    learning: (limit?: number) => ipcRenderer.invoke('zn:resident:learning', limit),
    neural: (limit?: number) => ipcRenderer.invoke('zn:resident:neural', limit),
    perceive: (payload: ZnDesktopPayload) => ipcRenderer.invoke('zn:resident:perceive', payload),
    worldFollow: (payload: ZnDesktopPayload) => ipcRenderer.invoke('zn:resident:world-follow', payload),
    worldFocuses: (payload?: ZnDesktopPayload) =>
      ipcRenderer.invoke('zn:resident:world-focuses', payload || {}),
    worldObserve: (payload: ZnDesktopPayload) => ipcRenderer.invoke('zn:resident:world-observe', payload),
    submit: (payload: ZnDesktopPayload) => ipcRenderer.invoke('zn:resident:submit', payload),
    remember: (payload: ZnDesktopPayload) => ipcRenderer.invoke('zn:resident:remember', payload),
    forget: (key: string) => ipcRenderer.invoke('zn:resident:forget', key)
  },
  workspaces: {
    attach: (threadId: string) => ipcRenderer.invoke('zn:workspaces:attach', { threadId }),
    detach: (threadId: string) => ipcRenderer.invoke('zn:workspaces:detach', { threadId })
  },
  updates: {
    check: () => ipcRenderer.invoke('zn:updates:check'),
    apply: () => ipcRenderer.invoke('zn:updates:apply')
  },
  shell: {
    onDeepLink: (callback: (payload: ZnDesktopDeepLink) => void) => {
      const listener = (_event: IpcRendererEvent, payload: ZnDesktopDeepLink) => callback(payload)
      ipcRenderer.on('zn:deep-link', listener)
      return () => ipcRenderer.removeListener('zn:deep-link', listener)
    }
  }
})