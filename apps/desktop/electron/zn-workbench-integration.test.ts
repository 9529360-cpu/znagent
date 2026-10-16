import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { test } from 'vitest'

import { znExportConversation } from '../src/zn/conversation-export'
import { znPlainEnterToSend, znWorkbenchShortcut } from '../src/zn/workbench-shortcuts'
import { znExecutionActionsFromDetail } from '../src/zn/execution-timeline'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const read = (name: string) => fs.readFileSync(path.join(root, name), 'utf8')

test('integration: export, keyboard navigation and actual execution status coexist', () => {
  const sample = {
    id: 'integration-thread',
    title: 'Workspace',
    messages: [
      { role: 'user' as const, text: 'Read a file', at: Date.UTC(2026, 9, 16) },
      { role: 'zn' as const, text: 'Completed', at: Date.UTC(2026, 9, 16, 0, 0, 1) },
      { role: 'activity' as const, text: 'tool payload', at: Date.UTC(2026, 9, 16, 0, 0, 2) }
    ]
  }
  assert.deepEqual(JSON.parse(znExportConversation(sample, 'json')).messages.map((m: { role: string }) => m.role), ['user', 'assistant'])
  assert.equal(znExportConversation(sample, 'markdown').includes('tool payload'), false)
  assert.equal(znWorkbenchShortcut({ key: 'Enter', ctrlKey: true, metaKey: false, shiftKey: false, altKey: false }), 'send')
  assert.equal(znWorkbenchShortcut({ key: 'k', ctrlKey: true, metaKey: false, shiftKey: false, altKey: false }), 'search')
  assert.equal(znPlainEnterToSend({ key: 'Enter', ctrlKey: false, metaKey: false, shiftKey: true, altKey: false }), false)
  const actual = znExecutionActionsFromDetail({ body_actions: [{ kind: 'inspect_path', success: false, summary: 'Denied', at: Date.UTC(2026, 9, 16) }] })
  assert.equal(actual[0].success, false)
  assert.equal(actual[0].summary, 'Denied')
})

test('integration: all four entry points share the ZN Resident and one Workbench', () => {
  const screen = read('src/zn/workbench.tsx')
  const client = read('src/zn/resident-client.ts')
  const ipc = read('electron/zn-resident-ipc.ts')
  const daemon = read('../../runtime/python/zn_agent/core/daemon.py')
  const resident = read('../../runtime/python/zn_agent/core/work.py')
  const workflow = read('../../.github/workflows/zn-ci.yml')
  for(const token of [
    'znExportConversation(activeThread, format)',
    'copyMessage(message.id, message.text)',
    'renameZnWorkThread(threadId, title)',
    'znExecutionActionsFromDetail(message.detail)',
    'actions={workProgress.bodyActions}'
  ]) assert.ok(screen.includes(token), 'missing shared Workbench feature: ' + token)
  assert.match(client, /desktop\(\)\.resident\.workRename\(/)
  assert.match(ipc, /request\('work_rename',/)
  assert.match(daemon, /elif method == "work_rename":/)
  assert.match(resident, /def rename_thread\(/)
  assert.match(resident, /def _recent_public_body_actions\(/)
  for(const name of [
    'electron/zn-conversation-export.test.ts',
    'electron/zn-workbench-shortcuts.test.ts',
    'electron/zn-execution-timeline.test.ts',
    'electron/zn-workbench-integration.test.ts'
  ]) assert.ok(workflow.includes(name), 'missing CI coverage: ' + name)
})
