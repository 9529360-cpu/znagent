import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { app, BrowserWindow, dialog, globalShortcut, ipcMain, Menu, shell, Tray } from 'electron'

import { configureZnPackagedRuntime } from './zn-packaged-runtime'
import { parseZnDeepLink, type ZnDeepLink, znDeepLinksFromArgv } from './zn-protocol'
import { registerZnReleaseUpdaterIpc } from './zn-release-updater'
import { registerZnResidentIpc, startZnResidentOnDesktopReady } from './zn-resident-ipc'
import { ZnWindowsResidentSurface, znWindowsTrayIconPath } from './zn-windows-resident-surface'
import { registerZnWorkspaceIpc } from './zn-workspace-ipc'

const moduleDir = path.dirname(fileURLToPath(import.meta.url))
const preloadPath = path.join(moduleDir, 'electron-preload.js')
const shellPath = path.join(moduleDir, 'zn-shell.html')
const ZN_GLOBAL_INVOCATION_SHORTCUT = 'CommandOrControl+Alt+Space'
const ZN_WINDOW_BOUNDS = {
  compact: { width: 480, height: 620 },
  expanded: { width: 1120, height: 760 }
} as const

type ZnWindowMode = keyof typeof ZN_WINDOW_BOUNDS
type ZnWorkAttentionState = 'idle' | 'running' | 'complete' | 'failed' | 'needs_attention'
type ZnWorkAttentionPayload = {
  eventId?: string
  state: ZnWorkAttentionState
}
type ZnUnreadWorkAttention = Exclude<ZnWorkAttentionState, 'idle' | 'running'>

let primaryWindow: BrowserWindow | null = null
let windowsResidentSurface: ZnWindowsResidentSurface | null = null
let windowsResidentTray: Tray | null = null
let activeWorkAttentionState: ZnWorkAttentionState = 'idle'
let unreadWorkAttention: ZnUnreadWorkAttention | null = null
let lastAnnouncedWorkAttention = ''
const pendingDeepLinks: ZnDeepLink[] = []

function isSafeExternalUrl(value: string): boolean {
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:'
  } catch {
    return false
  }
}

function openExternal(value: string): void {
  if (!isSafeExternalUrl(value)) return
  void shell.openExternal(value).catch(error => {
    console.error('[ZN] failed to open external URL', error)
  })
}

function deliverDeepLink(link: ZnDeepLink): void {
  const window = primaryWindow
  if (!window || window.isDestroyed() || window.webContents.isLoading()) {
    pendingDeepLinks.push(link)
    return
  }
  window.webContents.send('zn:deep-link', link)
}

function flushDeepLinks(window: BrowserWindow): void {
  if (window !== primaryWindow || window.isDestroyed()) return
  while (pendingDeepLinks.length > 0) {
    const link = pendingDeepLinks.shift()
    if (link) window.webContents.send('zn:deep-link', link)
  }
}

function receiveDeepLink(value: string): boolean {
  const link = parseZnDeepLink(value)
  if (!link) return false
  deliverDeepLink(link)
  return true
}

function routeNavigation(value: string): void {
  if (receiveDeepLink(value)) return
  openExternal(value)
}

export function createZnDesktopWindow(): BrowserWindow {
  const window = new BrowserWindow({
    title: 'ZN',
    width: ZN_WINDOW_BOUNDS.compact.width,
    height: ZN_WINDOW_BOUNDS.compact.height,
    minWidth: 420,
    minHeight: 480,
    show: false,
    backgroundColor: '#0f1115',
    backgroundMaterial: 'mica',
    titleBarStyle: 'hidden',
    titleBarOverlay: {
      color: '#0a1323',
      symbolColor: '#b7c4d9',
      height: 62
    },
    roundedCorners: true,
    webPreferences: {
      preload: preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  })
  window.setMenu(null)

  window.once('ready-to-show', () => window.show())
  window.webContents.on('did-finish-load', () => flushDeepLinks(window))
  window.webContents.setWindowOpenHandler(({ url }) => {
    routeNavigation(url)
    return { action: 'deny' }
  })
  window.webContents.on('will-navigate', (event, url) => {
    const current = window.webContents.getURL()
    if (url === current) return
    event.preventDefault()
    routeNavigation(url)
  })
  window.on('query-session-end', () => windowsResidentSurface?.beginQuit())
  window.on('focus', () => clearUnreadWorkAttention())
  window.on('close', event => {
    windowsResidentSurface?.handleWindowClose(event, window)
  })
  window.on('closed', () => {
    if (primaryWindow === window) primaryWindow = null
  })

  void window.loadFile(shellPath).catch(error => {
    console.error('[ZN] failed to load desktop shell', error)
  })
  return window
}

function ensurePrimaryWindow(): BrowserWindow {
  if (primaryWindow && !primaryWindow.isDestroyed()) return primaryWindow
  primaryWindow = createZnDesktopWindow()
  return primaryWindow
}

function setZnWindowMode(window: BrowserWindow, mode: ZnWindowMode): void {
  const bounds = ZN_WINDOW_BOUNDS[mode]
  if (window.isMaximized()) window.unmaximize()
  window.setSize(bounds.width, bounds.height, true)
}

function workAttentionLabel(state: ZnWorkAttentionState | null): string {
  if (state === 'running') return 'ZN 路 Working'
  if (state === 'complete') return 'ZN 路 Work complete'
  if (state === 'failed') return 'ZN 路 Work failed'
  if (state === 'needs_attention') return 'ZN 路 Needs attention'
  return 'ZN'
}

function refreshTrayAttention(): void {
  if (!windowsResidentTray) return
  windowsResidentTray.setToolTip(
    workAttentionLabel(unreadWorkAttention || activeWorkAttentionState)
  )
}

function clearUnreadWorkAttention(): void {
  unreadWorkAttention = null
  refreshTrayAttention()
}

function parseWorkAttentionPayload(value: unknown): ZnWorkAttentionPayload | null {
  if (!value || typeof value !== 'object') return null
  const item = value as Record<string, unknown>
  const state = item.state
  if (
    state !== 'idle' &&
    state !== 'running' &&
    state !== 'complete' &&
    state !== 'failed' &&
    state !== 'needs_attention'
  ) {
    return null
  }
  const eventId = typeof item.eventId === 'string' ? item.eventId.trim() : ''
  if (eventId.length > 256) return null
  if (state !== 'idle' && !eventId) return null
  return eventId ? { state, eventId } : { state }
}

function workAttentionMessage(state: ZnUnreadWorkAttention): string {
  if (state === 'complete') return 'Work completed. Open ZN to review the result.'
  if (state === 'failed') return 'Work ended with an error. Open ZN to review.'
  return 'Work needs your attention before it can continue.'
}

function reportWorkAttention(payload: ZnWorkAttentionPayload): void {
  activeWorkAttentionState = payload.state
  if (payload.state === 'idle' || payload.state === 'running') {
    refreshTrayAttention()
    return
  }

  const window = primaryWindow
  const userIsLooking =
    Boolean(window) &&
    !window!.isDestroyed() &&
    window!.isVisible() &&
    window!.isFocused()

  if (userIsLooking) {
    unreadWorkAttention = null
    refreshTrayAttention()
    return
  }

  unreadWorkAttention = payload.state
  refreshTrayAttention()

  const identity = `${payload.eventId || ''}:${payload.state}`
  if (!windowsResidentTray || !payload.eventId || identity === lastAnnouncedWorkAttention) return
  lastAnnouncedWorkAttention = identity
  windowsResidentTray.displayBalloon({
    title: 'ZN',
    content: workAttentionMessage(payload.state),
    noSound: true,
    respectQuietTime: true
  })
}

function focusComposerAfterInvocation(window: BrowserWindow): void {
  const notify = () => {
    if (!window.isDestroyed()) window.webContents.send('zn:global-invocation')
  }
  if (window.webContents.isLoading()) {
    window.webContents.once('did-finish-load', notify)
    return
  }
  notify()
}

function showPrimaryWindow(focusComposer = false, mode?: ZnWindowMode): void {
  const window = ensurePrimaryWindow()
  if (windowsResidentSurface) {
    windowsResidentSurface.show()
  } else {
    if (window.isMinimized()) window.restore()
    window.show()
    window.focus()
  }
  // Windows can ignore size changes while a native window is minimized. Apply
  // compact/expanded bounds only after the resident surface has restored it.
  if (mode) setZnWindowMode(window, mode)
  clearUnreadWorkAttention()
  if (focusComposer) focusComposerAfterInvocation(window)
}

function initializeWindowsResidentSurface(): void {
  if (process.platform !== 'win32' || windowsResidentSurface) return

  const surface = new ZnWindowsResidentSurface(
    () => ensurePrimaryWindow(),
    () => app.quit()
  )

  try {
    const tray = new Tray(
      znWindowsTrayIconPath({
        isPackaged: app.isPackaged,
        resourcesPath: process.resourcesPath,
        appPath: app.getAppPath()
      })
    )
    windowsResidentTray = tray
    refreshTrayAttention()
    tray.setContextMenu(
      Menu.buildFromTemplate([
        {
          label: 'Open ZN',
          click: () => showPrimaryWindow(true, 'compact')
        },
        { type: 'separator' },
        {
          label: 'Quit ZN',
          click: () => surface.quit()
        }
      ])
    )
    tray.on('double-click', () => showPrimaryWindow(true, 'compact'))
    tray.on('balloon-click', () => showPrimaryWindow(true, 'compact'))
    windowsResidentSurface = surface
  } catch (error) {
    console.error('[ZN] failed to initialize Windows resident surface', error)
    windowsResidentSurface = null
    windowsResidentTray = null
  }
}

function initializeGlobalInvocation(): void {
  if (process.platform !== 'win32') return
  const registered = globalShortcut.register(ZN_GLOBAL_INVOCATION_SHORTCUT, () => {
    showPrimaryWindow(true, 'compact')
  })
  if (!registered) {
    console.warn(`[ZN] global invocation shortcut unavailable: ${ZN_GLOBAL_INVOCATION_SHORTCUT}`)
  }
}

function registerZnShellIpc(): void {
  ipcMain.removeHandler('zn:shell:set-window-mode')
  ipcMain.handle('zn:shell:set-window-mode', (_event, mode: unknown) => {
    if (mode !== 'compact' && mode !== 'expanded') {
      throw new Error('invalid ZN window mode')
    }
    const window = ensurePrimaryWindow()
    setZnWindowMode(window, mode)
    return { mode, ...ZN_WINDOW_BOUNDS[mode] }
  })

  ipcMain.removeAllListeners('zn:shell:work-attention')
  ipcMain.on('zn:shell:work-attention', (event, value: unknown) => {
    const window = primaryWindow
    if (!window || window.isDestroyed() || event.sender !== window.webContents) return
    const payload = parseWorkAttentionPayload(value)
    if (!payload) return
    reportWorkAttention(payload)
  })
}

async function bootstrapZnDesktop(): Promise<void> {
  if (!app.requestSingleInstanceLock()) {
    app.quit()
    return
  }

  for (const link of znDeepLinksFromArgv(process.argv)) pendingDeepLinks.push(link)

  app.on('before-quit', () => windowsResidentSurface?.beginQuit())
  app.on('will-quit', () => {
    if (process.platform === 'win32') globalShortcut.unregister(ZN_GLOBAL_INVOCATION_SHORTCUT)
  })
  app.on('open-url', (event, url) => {
    event.preventDefault()
    receiveDeepLink(url)
  })
  app.on('second-instance', (_event, argv) => {
    for (const link of znDeepLinksFromArgv(argv)) deliverDeepLink(link)
    showPrimaryWindow(true, 'compact')
  })

  if (app.isPackaged) {
    const runtime = configureZnPackagedRuntime({ resourcesPath: process.resourcesPath })
    console.info(
      `[ZN] packaged runtime ${runtime.manifest.runtime_id.slice(0, 12)} ready at ${runtime.root}`
    )
  }

  registerZnResidentIpc()
  registerZnWorkspaceIpc()
  registerZnReleaseUpdaterIpc()
  registerZnShellIpc()

  await app.whenReady()
  if (!app.setAsDefaultProtocolClient('zn')) {
    console.warn('[ZN] OS protocol registration for zn:// is unavailable in this build')
  }
  initializeWindowsResidentSurface()
  initializeGlobalInvocation()
  ensurePrimaryWindow()
  await startZnResidentOnDesktopReady()

  app.on('activate', () => {
    ensurePrimaryWindow()
  })
  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit()
  })
}

void bootstrapZnDesktop().catch(error => {
  const message = error instanceof Error ? error.message : String(error)
  console.error('[ZN] desktop bootstrap failed:', error)

  try {
    dialog.showErrorBox('ZN runtime unavailable', message)
  } catch {
    void 0
  }

  app.quit()
})
