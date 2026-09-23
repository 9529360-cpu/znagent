import assert from 'node:assert/strict'
import { test } from 'vitest'

import { fitZnWindowToWorkArea } from './zn-window-bounds.js'

test('keeps a window fully visible when its current position extends below the work area', () => {
  assert.deepEqual(
    fitZnWindowToWorkArea(
      { x: 612, y: 200, width: 480, height: 620 },
      { x: 0, y: 0, width: 1116, height: 720 }
    ),
    { x: 612, y: 100, width: 480, height: 620 }
  )
})

test('preserves position on a secondary display with a negative origin', () => {
  assert.deepEqual(
    fitZnWindowToWorkArea(
      { x: -1500, y: 80, width: 480, height: 620 },
      { x: -1920, y: 0, width: 1920, height: 1040 }
    ),
    { x: -1500, y: 80, width: 480, height: 620 }
  )
})

test('shrinks requested bounds when a display work area is smaller than the window', () => {
  assert.deepEqual(
    fitZnWindowToWorkArea(
      { x: 400, y: 300, width: 1120, height: 760 },
      { x: 0, y: 0, width: 960, height: 640 }
    ),
    { x: 0, y: 0, width: 960, height: 640 }
  )
})
