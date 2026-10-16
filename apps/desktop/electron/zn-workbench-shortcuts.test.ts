import assert from 'node:assert/strict'
import { test } from 'vitest'

import { znPlainEnterToSend, znWorkbenchShortcut, type ZnShortcutKey } from '../src/zn/workbench-shortcuts'

function key(override: Partial<ZnShortcutKey>): ZnShortcutKey {
  return {
    key: '', ctrlKey: false, metaKey: false, shiftKey: false, altKey: false,
    isComposing: false, repeat: false, ...override
  }
}

test('Cmd/Ctrl+Enter sends without stealing modified or composing keystrokes', () => {
  assert.equal(znWorkbenchShortcut(key({ key: 'Enter', ctrlKey: true })), 'send')
  assert.equal(znWorkbenchShortcut(key({ key: 'Enter', metaKey: true })), 'send')
  assert.equal(znWorkbenchShortcut(key({ key: 'Enter', ctrlKey: true, shiftKey: true })), null)
  assert.equal(znWorkbenchShortcut(key({ key: 'Enter', ctrlKey: true, isComposing: true })), null)
  assert.equal(znWorkbenchShortcut(key({ key: 'Enter', metaKey: true, repeat: true })), null)
})

test('Ctrl/Cmd+K opens search, Escape requests cancel, modifiers do not', () => {
  assert.equal(znWorkbenchShortcut(key({ key: 'k', ctrlKey: true })), 'search')
  assert.equal(znWorkbenchShortcut(key({ key: 'K', metaKey: true })), 'search')
  assert.equal(znWorkbenchShortcut(key({ key: 'Escape' })), 'stop')
  assert.equal(znWorkbenchShortcut(key({ key: 'Escape', metaKey: true })), null)
  assert.equal(znWorkbenchShortcut(key({ key: 'Escape', altKey: true })), null)
  assert.equal(znWorkbenchShortcut(key({ key: 'Escape', repeat: true })), null)
})

test('Existing Enter-to-send and Shift+Enter newline remain compatible', () => {
  assert.equal(znPlainEnterToSend(key({ key: 'Enter' })), true)
  assert.equal(znPlainEnterToSend(key({ key: 'Enter', shiftKey: true })), false)
  assert.equal(znPlainEnterToSend(key({ key: 'Enter', isComposing: true })), false)
  assert.equal(znPlainEnterToSend(key({ key: 'Enter', altKey: true })), false)
})
