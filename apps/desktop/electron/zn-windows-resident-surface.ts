export interface ZnResidentSurfaceWindow {
  isDestroyed(): boolean
  isMinimized(): boolean
  restore(): void
  show(): void
  focus(): void
  hide(): void
}

export interface ZnResidentSurfaceCloseEvent {
  preventDefault(): void
}

/**
 * Own the Windows notification-area lifetime policy without making the tray a
 * second Resident. The Python Resident remains the durable subject; this
 * surface only keeps the user-facing Desktop reachable after its window is
 * closed.
 *
 * A genuine application quit must always win. The Electron main process marks
 * the lifecycle as quitting from `before-quit`, which covers explicit tray
 * quit as well as release/update handoff through the existing app.quit path.
 */
export class ZnWindowsResidentSurface {
  private quitting = false

  constructor(
    private readonly windowProvider: () => ZnResidentSurfaceWindow,
    private readonly quitApplication: () => void
  ) {}

  beginQuit(): void {
    this.quitting = true
  }

  handleWindowClose(event: ZnResidentSurfaceCloseEvent, window: ZnResidentSurfaceWindow): boolean {
    if (this.quitting || window.isDestroyed()) return false
    event.preventDefault()
    window.hide()
    return true
  }

  show(): void {
    const window = this.windowProvider()
    if (window.isDestroyed()) return
    if (window.isMinimized()) window.restore()
    window.show()
    window.focus()
  }

  quit(): void {
    this.beginQuit()
    this.quitApplication()
  }
}
