import assert from 'node:assert/strict'

import { test, vi } from 'vitest'

import { ZnWindowsResidentSurface, type ZnResidentSurfaceWindow } from './zn-windows-resident-surface'

function makeWindow(overrides: Partial<ZnResidentSurfaceWindow> = {}): ZnResidentSurfaceWindow {
  return {
    isDestroyed: () => false,
    isMinimized: () => false,
    restore: vi.fn(),
    show: vi.fn(),
    focus: vi.fn(),
    hide: vi.fn(),
    ...overrides
  }
}

test('closing the Windows desktop window hides the surface without quitting the app', () => {
  const window = makeWindow()
  const quitApplication = vi.fn()
  const preventDefault = vi.fn()
  const surface = new ZnWindowsResidentSurface(() => window, quitApplication)

  const hidden = surface.handleWindowClose({ preventDefault }, window)

  assert.equal(hidden, true)
  assert.equal(preventDefault.mock.calls.length, 1)
  assert.equal(vi.mocked(window.hide).mock.calls.length, 1)
  assert.equal(quitApplication.mock.calls.length, 0)
})

test('a genuine before-quit lifecycle lets the desktop window close normally', () => {
  const window = makeWindow()
  const preventDefault = vi.fn()
  const surface = new ZnWindowsResidentSurface(() => window, vi.fn())

  surface.beginQuit()
  const hidden = surface.handleWindowClose({ preventDefault }, window)

  assert.equal(hidden, false)
  assert.equal(preventDefault.mock.calls.length, 0)
  assert.equal(vi.mocked(window.hide).mock.calls.length, 0)
})

test('show restores a minimized resident window before showing and focusing it', () => {
  const order: string[] = []
  const window = makeWindow({
    isMinimized: () => true,
    restore: vi.fn(() => order.push('restore')),
    show: vi.fn(() => order.push('show')),
    focus: vi.fn(() => order.push('focus'))
  })
  const surface = new ZnWindowsResidentSurface(() => window, vi.fn())

  surface.show()

  assert.deepEqual(order, ['restore', 'show', 'focus'])
})

test('explicit tray quit marks the lifecycle before asking Electron to quit', () => {
  const window = makeWindow()
  const quitApplication = vi.fn()
  const preventDefault = vi.fn()
  const surface = new ZnWindowsResidentSurface(() => window, quitApplication)

  surface.quit()
  const hidden = surface.handleWindowClose({ preventDefault }, window)

  assert.equal(quitApplication.mock.calls.length, 1)
  assert.equal(hidden, false)
  assert.equal(preventDefault.mock.calls.length, 0)
})
