import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron'

import type { ZnLocalePreference } from '../localization/zn-localization'

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
    mcpCapabilities: () => ipcRenderer.invoke('zn:resident:mcp-capabilities'),
    mcpConnect: (providerId: string) =>
      ipcRenderer.invoke('zn:resident:mcp-connect', { providerId }),
    mcpDisconnect: (providerId: string) =>
      ipcRenderer.invoke('zn:resident:mcp-disconnect', { providerId }),
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
    routinePropose: (payload: ZnDesktopPayload) =>
      ipcRenderer.invoke('zn:resident:routine-propose', payload),
    routineConfirm: (payload: ZnDesktopPayload) =>
      ipcRenderer.invoke('zn:resident:routine-confirm', payload),
    routineList: (payload?: ZnDesktopPayload) => ipcRenderer.invoke('zn:resident:routine-list', payload || {}),
    routineGet: (payload: ZnDesktopPayload) => ipcRenderer.invoke('zn:resident:routine-get', payload),
    routineRuns: (payload: ZnDesktopPayload) => ipcRenderer.invoke('zn:resident:routine-runs', payload),
    routinePause: (payload: ZnDesktopPayload) => ipcRenderer.invoke('zn:resident:routine-pause', payload),
    routineResume: (payload: ZnDesktopPayload) => ipcRenderer.invoke('zn:resident:routine-resume', payload),
    routineEdit: (payload: ZnDesktopPayload) => ipcRenderer.invoke('zn:resident:routine-edit', payload),
    routineDelete: (payload: ZnDesktopPayload) => ipcRenderer.invoke('zn:resident:routine-delete', payload),
    routineTestRun: (payload: ZnDesktopPayload) => ipcRenderer.invoke('zn:resident:routine-test-run', payload),
    routineAcknowledge: (payload: ZnDesktopPayload) =>
      ipcRenderer.invoke('zn:resident:routine-acknowledge', payload),
    teamTimeline: (payload?: ZnDesktopPayload) =>
      ipcRenderer.invoke('zn:resident:team-timeline', payload || {}),
    teamAssign: (payload?: ZnDesktopPayload) =>
      ipcRenderer.invoke('zn:resident:team-assign', payload || {}),
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
    getLocaleState: () => ipcRenderer.invoke('zn:shell:get-locale-state'),
    setLocalePreference: (preference: ZnLocalePreference) =>
      ipcRenderer.invoke('zn:shell:set-locale-preference', preference),
    setWindowMode: (mode: 'compact' | 'expanded') => ipcRenderer.invoke('zn:shell:set-window-mode', mode),
    ackWindowModeTransition: (payload: { transitionId: string; mode: 'compact' | 'expanded' }) =>
      ipcRenderer.invoke('zn:shell:ack-window-mode-transition', payload),
    onWindowModeTransition: (
      callback: (payload: {
        transitionId: string
        phase: 'prepare' | 'complete'
        mode: 'compact' | 'expanded'
        reason: string
        width?: number
        height?: number
      }) => void
    ) => {
      const listener = (_event: IpcRendererEvent, payload: {
        transitionId: string
        phase: 'prepare' | 'complete'
        mode: 'compact' | 'expanded'
        reason: string
        width?: number
        height?: number
      }) => callback(payload)
      ipcRenderer.on('zn:shell:window-mode-transition', listener)
      return () => ipcRenderer.removeListener('zn:shell:window-mode-transition', listener)
    },
    onDeepLink: (callback: (payload: ZnDesktopDeepLink) => void) => {
      const listener = (_event: IpcRendererEvent, payload: ZnDesktopDeepLink) => callback(payload)
      ipcRenderer.on('zn:deep-link', listener)
      return () => ipcRenderer.removeListener('zn:deep-link', listener)
    },
    onGlobalInvocation: (callback: () => void) => {
      const listener = () => callback()
      ipcRenderer.on('zn:global-invocation', listener)
      return () => ipcRenderer.removeListener('zn:global-invocation', listener)
    }
  }
})