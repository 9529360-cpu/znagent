import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { app, BrowserWindow, dialog, Menu, shell, Tray } from 'electron'

import { configureZnPackagedRuntime } from './zn-packaged-runtime'
import { parseZnDeepLink, type ZnDeepLink, znDeepLinksFromArgv } from './zn-protocol'
import { registerZnReleaseUpdaterIpc } from './zn-release-updater'
import { registerZnResidentIpc, startZnResidentOnDesktopReady } from './zn-resident-ipc'
import { ZnWindowsResidentSurface } from './zn-windows-resident-surface'
import { registerZnWorkspaceIpc } from './zn-workspace-ipc'

const moduleDir = path.dirname(fileURLToPath(import.meta.url))
const preloadPath = path.join(moduleDir, 'electron-preload.js')
const shellPath = path.join(moduleDir, 'zn-shell.html')

let primaryWindow: BrowserWindow | null = null
let windowsResidentSurface: ZnWindowsResidentSurface | null = null
let windowsResidentTray: Tray | null = null
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
    width: 1180,
    height: 760,
    minWidth: 760,
    minHeight: 520,
    show: false,
    backgroundColor: '#0f1115',
    webPreferences: {
      preload: preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  })

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

function initializeWindowsResidentSurface(): void {
  if (process.platform !== 'win32' || windowsResidentSurface) return

  windowsResidentSurface = new ZnWindowsResidentSurface(
    () => ensurePrimaryWindow(),
    () => app.quit()
  )

  windowsResidentTray = new Tray(path.join(app.getAppPath(), 'assets', 'icon.ico'))
  windowsResidentTray.setToolTip('ZN')
  windowsResidentTray.setContextMenu(
    Menu.buildFromTemplate([
      {
        label: 'Open ZN',
        click: () => windowsResidentSurface?.show()
      },
      { type: 'separator' },
      {
        label: 'Quit ZN',
        click: () => windowsResidentSurface?.quit()
      }
    ])
  )
  windowsResidentTray.on('double-click', () => windowsResidentSurface?.show())
}

async function bootstrapZnDesktop(): Promise<void> {
  if (!app.requestSingleInstanceLock()) {
    app.quit()
    return
  }

  for (const link of znDeepLinksFromArgv(process.argv)) pendingDeepLinks.push(link)

  app.on('before-quit', () => windowsResidentSurface?.beginQuit())
  app.on('open-url', (event, url) => {
    event.preventDefault()
    receiveDeepLink(url)
  })
  app.on('second-instance', (_event, argv) => {
    for (const link of znDeepLinksFromArgv(argv)) deliverDeepLink(link)
    const window = ensurePrimaryWindow()
    if (window.isMinimized()) window.restore()
    window.show()
    window.focus()
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

  await app.whenReady()
  if (!app.setAsDefaultProtocolClient('zn')) {
    console.warn('[ZN] OS protocol registration for zn:// is unavailable in this build')
  }
  initializeWindowsResidentSurface()
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
