import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { app, BrowserWindow, dialog, shell } from 'electron'

import { configureZnPackagedRuntime } from './zn-packaged-runtime'
import { registerZnReleaseUpdaterIpc } from './zn-release-updater'
import { registerZnResidentIpc, startZnResidentOnDesktopReady } from './zn-resident-ipc'

const moduleDir = path.dirname(fileURLToPath(import.meta.url))
const preloadPath = path.join(moduleDir, 'electron-preload.js')
const shellPath = path.join(moduleDir, 'zn-shell.html')

let primaryWindow: BrowserWindow | null = null

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
  window.webContents.setWindowOpenHandler(({ url }) => {
    openExternal(url)
    return { action: 'deny' }
  })
  window.webContents.on('will-navigate', (event, url) => {
    const current = window.webContents.getURL()
    if (url === current) return
    event.preventDefault()
    openExternal(url)
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

async function bootstrapZnDesktop(): Promise<void> {
  if (!app.requestSingleInstanceLock()) {
    app.quit()
    return
  }

  app.on('second-instance', () => {
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
  registerZnReleaseUpdaterIpc()

  await app.whenReady()
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
