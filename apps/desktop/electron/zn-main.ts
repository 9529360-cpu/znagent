import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { app, BrowserWindow, dialog, globalShortcut, ipcMain, Menu, shell, Tray } from 'electron'

import {
  isZnLocalePreference,
  resolveZnLocale,
  translateZnDesktop,
  type ZnDesktopLocaleState,
  type ZnLocalePreference,
  type ZnTranslationKey
} from '../localization/zn-localization'
import { readZnLocalePreference, writeZnLocalePreference } from './zn-locale-preference'
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
const ZN_DESKTOP_PREFERENCES_FILE = 'desktop-preferences.json'
const ZN_WINDOW_BOUNDS = {
  compact: { width: 480, height: 620 },
  expanded: { width: 1120, height: 760 }
} as const

type ZnWindowMode = keyof typeof ZN_WINDOW_BOUNDS

type ZnWindowTransitionAck = {
  transitionId: string
  mode: ZnWindowMode
}

const ZN_WINDOW_TRANSITION_TIMEOUT_MS = 250
let nextWindowTransitionId = 0
const latestWindowTransitionIds = new Map<number, string>()
const pendingWindowTransitionAcks = new Map<
  string,
  {
    windowId: number
    mode: ZnWindowMode
    timer: ReturnType<typeof setTimeout>
    resolve: () => void
  }
>()

let primaryWindow: BrowserWindow | null = null
let windowsResidentSurface: ZnWindowsResidentSurface | null = null
let windowsResidentTray: Tray | null = null
let currentLocaleState: ZnDesktopLocaleState = {
  preference: 'system',
  resolvedLocale: 'en-US',
  preferredSystemLanguages: []
}
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

function preferredSystemLanguages(): string[] {
  try {
    const languages = app.getPreferredSystemLanguages().filter(Boolean)
    if (languages.length > 0) return languages
  } catch {
    void 0
  }
  try {
    const locale = app.getLocale()
    if (locale) return [locale]
  } catch {
    void 0
  }
  return ['en-US']
}

function desktopPreferencesPath(): string {
  return path.join(app.getPath('userData'), ZN_DESKTOP_PREFERENCES_FILE)
}

function buildLocaleState(preference: ZnLocalePreference): ZnDesktopLocaleState {
  const languages = preferredSystemLanguages()
  return {
    preference,
    resolvedLocale: resolveZnLocale(preference, languages),
    preferredSystemLanguages: languages
  }
}

function refreshLocaleStateFromDisk(): ZnDesktopLocaleState {
  currentLocaleState = buildLocaleState(readZnLocalePreference(desktopPreferencesPath()))
  return currentLocaleState
}

function localizedMainText(key: ZnTranslationKey): string {
  return translateZnDesktop(currentLocaleState.resolvedLocale, key)
}

function refreshWindowsTrayMenu(): void {
  const tray = windowsResidentTray
  const surface = windowsResidentSurface
  if (!tray || !surface) return
  tray.setContextMenu(
    Menu.buildFromTemplate([
      {
        label: localizedMainText('tray.open'),
        click: () => showPrimaryWindow(true, 'compact')
      },
      { type: 'separator' },
      {
        label: localizedMainText('tray.quit'),
        click: () => surface.quit()
      }
    ])
  )
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

async function prepareZnWindowTransition(
  window: BrowserWindow,
  mode: ZnWindowMode,
  reason: string
): Promise<string | null> {
  if (window.isDestroyed() || window.webContents.isLoading()) return null
  const transitionId = `${window.id}:${++nextWindowTransitionId}`
  latestWindowTransitionIds.set(window.id, transitionId)

  await new Promise<void>(resolve => {
    const timer = setTimeout(() => {
      pendingWindowTransitionAcks.delete(transitionId)
      resolve()
    }, ZN_WINDOW_TRANSITION_TIMEOUT_MS)

    pendingWindowTransitionAcks.set(transitionId, {
      windowId: window.id,
      mode,
      timer,
      resolve: () => {
        clearTimeout(timer)
        pendingWindowTransitionAcks.delete(transitionId)
        resolve()
      }
    })

    window.webContents.send('zn:shell:window-mode-transition', {
      transitionId,
      phase: 'prepare',
      mode,
      reason
    })
  })

  return transitionId
}

async function transitionZnWindowMode(
  window: BrowserWindow,
  mode: ZnWindowMode,
  reason: string
): Promise<{ mode: ZnWindowMode; width: number; height: number }> {
  const transitionId = await prepareZnWindowTransition(window, mode, reason)
  const result = { mode, ...ZN_WINDOW_BOUNDS[mode] }
  if (transitionId && latestWindowTransitionIds.get(window.id) !== transitionId) return result
  if (window.isDestroyed()) {
    if (transitionId) latestWindowTransitionIds.delete(window.id)
    return result
  }
  setZnWindowMode(window, mode)
  if (transitionId) {
    latestWindowTransitionIds.delete(window.id)
    window.webContents.send('zn:shell:window-mode-transition', {
      transitionId,
      phase: 'complete',
      mode,
      reason,
      width: result.width,
      height: result.height
    })
  }
  return result
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
  if (mode) {
    void transitionZnWindowMode(
      window,
      mode,
      focusComposer ? 'resident-invocation' : 'resident-show'
    )
      .catch(error => {
        console.error('[ZN] failed to transition resident window mode', error)
      })
      .finally(() => {
        if (focusComposer) focusComposerAfterInvocation(window)
      })
    return
  }
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
    tray.setToolTip('ZN')
    tray.on('double-click', () => showPrimaryWindow(true, 'compact'))
    windowsResidentSurface = surface
    windowsResidentTray = tray
    refreshWindowsTrayMenu()
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
  ipcMain.removeHandler('zn:shell:get-locale-state')
  ipcMain.handle('zn:shell:get-locale-state', () => {
    if (currentLocaleState.preference === 'system') {
      currentLocaleState = buildLocaleState('system')
    }
    return {
      ...currentLocaleState,
      preferredSystemLanguages: [...currentLocaleState.preferredSystemLanguages]
    }
  })

  ipcMain.removeHandler('zn:shell:set-locale-preference')
  ipcMain.handle('zn:shell:set-locale-preference', (_event, preference: unknown) => {
    if (!isZnLocalePreference(preference)) {
      throw new Error('invalid ZN locale preference')
    }
    writeZnLocalePreference(desktopPreferencesPath(), preference)
    currentLocaleState = buildLocaleState(preference)
    refreshWindowsTrayMenu()
    return {
      ...currentLocaleState,
      preferredSystemLanguages: [...currentLocaleState.preferredSystemLanguages]
    }
  })

  ipcMain.removeHandler('zn:shell:set-window-mode')
  ipcMain.removeHandler('zn:shell:ack-window-mode-transition')
  ipcMain.handle('zn:shell:ack-window-mode-transition', (event, ack: unknown) => {
    if (
      !ack ||
      typeof ack !== 'object' ||
      typeof (ack as ZnWindowTransitionAck).transitionId !== 'string' ||
      ((ack as ZnWindowTransitionAck).mode !== 'compact' &&
        (ack as ZnWindowTransitionAck).mode !== 'expanded')
    ) {
      return { accepted: false }
    }
    const typedAck = ack as ZnWindowTransitionAck
    const pending = pendingWindowTransitionAcks.get(typedAck.transitionId)
    const sourceWindow = BrowserWindow.fromWebContents(event.sender)
    if (
      !pending ||
      !sourceWindow ||
      sourceWindow.id !== pending.windowId ||
      typedAck.mode !== pending.mode
    ) {
      return { accepted: false }
    }
    pending.resolve()
    return { accepted: true }
  })
  ipcMain.handle('zn:shell:set-window-mode', async (_event, mode: unknown) => {
    if (mode !== 'compact' && mode !== 'expanded') {
      throw new Error('invalid ZN window mode')
    }
    const window = ensurePrimaryWindow()
    return transitionZnWindowMode(window, mode, 'renderer-request')
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
  refreshLocaleStateFromDisk()
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
    dialog.showErrorBox(localizedMainText('dialog.runtimeUnavailable'), message)
  } catch {
    void 0
  }

  app.quit()
})
