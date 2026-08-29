#!/usr/bin/env node
import assert from 'node:assert/strict'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import { validateScheduledTaskXml } from './verify-zn-windows-resident-autostart.mjs'

function taskXml({ command, args }) {
  return `<?xml version="1.0" encoding="UTF-16"?>
<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Actions Context="Author">
    <Exec>
      <Command>${command}</Command>
      <Arguments>${args}</Arguments>
    </Exec>
  </Actions>
</Task>`
}

test('scheduled task pins the formal resident to the installed runtime and home', () => {
  const runtimeId = '0123456789abcdef0123456789abcdef01234567'
  const znHome = path.join(os.tmpdir(), 'ZN Home')
  const python = path.join(znHome, 'runtime', runtimeId, 'python', 'python.exe')
  const xml = taskXml({ command: python, args: `-m zn_agent.resident --home "${znHome}"` })
  assert.deepEqual(validateScheduledTaskXml(xml, { znHome, expectedRuntimeId: runtimeId }), { command: python, args: `-m zn_agent.resident --home "${znHome}"` })
})

test('scheduled task rejects a Python command outside the installed runtime', () => {
  const runtimeId = '0123456789abcdef0123456789abcdef01234567'
  const znHome = path.join(os.tmpdir(), 'ZN Home')
  const xml = taskXml({ command: path.join(os.tmpdir(), 'foreign', 'python.exe'), args: `-m zn_agent.resident --home "${znHome}"` })
  assert.throws(() => validateScheduledTaskXml(xml, { znHome, expectedRuntimeId: runtimeId }), /outside installed runtime/)
})

test('scheduled task rejects legacy or non-formal resident entrypoints', () => {
  const runtimeId = '0123456789abcdef0123456789abcdef01234567'
  const znHome = path.join(os.tmpdir(), 'ZN Home')
  const python = path.join(znHome, 'runtime', runtimeId, 'python', 'python.exe')
  const xml = taskXml({ command: python, args: `-m zn_agent.core.resident_server --home "${znHome}"` })
  assert.throws(() => validateScheduledTaskXml(xml, { znHome, expectedRuntimeId: runtimeId }), /does not launch formal resident/)
})

test('scheduled task rejects a different ZN home even with the right runtime command', () => {
  const runtimeId = '0123456789abcdef0123456789abcdef01234567'
  const znHome = path.join(os.tmpdir(), 'ZN Home')
  const python = path.join(znHome, 'runtime', runtimeId, 'python', 'python.exe')
  const xml = taskXml({ command: python, args: `-m zn_agent.resident --home "${path.join(os.tmpdir(), 'Other Home')}"` })
  assert.throws(() => validateScheduledTaskXml(xml, { znHome, expectedRuntimeId: runtimeId }), /does not pin ZN home/)
})

test('scheduled task cannot satisfy home check by mentioning expected home in another argument', () => {
  const runtimeId = '0123456789abcdef0123456789abcdef01234567'
  const znHome = path.join(os.tmpdir(), 'ZN Home')
  const otherHome = path.join(os.tmpdir(), 'Other Home')
  const python = path.join(znHome, 'runtime', runtimeId, 'python', 'python.exe')
  const xml = taskXml({ command: python, args: `-m zn_agent.resident --home "${otherHome}" --note "${znHome}"` })
  assert.throws(() => validateScheduledTaskXml(xml, { znHome, expectedRuntimeId: runtimeId }), /does not pin ZN home/)
})
