import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { test } from 'vitest'

function read(relative: string): string {
  return readFileSync(join(__dirname, '..', relative), 'utf8')
}

test('approval cards: Electron IPC forwards the approval RPC methods', () => {
  const ipc = read('electron/zn-resident-ipc.ts')
  for (const [channel, method] of [
    ['zn:resident:approval-list', 'approval_list'],
    ['zn:resident:approval-request', 'approval_request'],
    ['zn:resident:approval-decide', 'approval_decide'],
    ['zn:resident:approval-rule-create', 'approval_rule_create'],
    ['zn:resident:approval-rule-delete', 'approval_rule_delete'],
    ['zn:resident:approval-undo', 'approval_undo']
  ] as const) {
    assert.match(ipc, new RegExp(`handleZnDesktopIpc\\('${channel}'`))
    assert.match(ipc, new RegExp(`request\\('${method}'`))
  }
  // Decisions and rules require their ids; requests require kind/target/scope.
  assert.match(ipc, /requestId is required/)
  assert.match(ipc, /actionKind is required/)
  assert.match(ipc, /scope is required/)
})

test('approval cards: preload exposes the approval bridge and the resident accepts the RPC methods', () => {
  const preload = read('electron/zn-preload.ts')
  for (const name of ['approvalList', 'approvalRequest', 'approvalDecide', 'approvalRuleCreate', 'approvalRuleDelete', 'approvalUndo']) {
    assert.match(preload, new RegExp(`${name}:`))
  }
  const process = read('electron/zn-resident-process.ts')
  for (const method of ['approval_list', 'approval_request', 'approval_decide', 'approval_rule_create', 'approval_rule_delete', 'approval_undo']) {
    assert.match(process, new RegExp(`\\| '${method}'`))
  }
})

test('approval cards: resident client normalizes and exposes approval helpers', () => {
  const client = read('src/zn/resident-client.ts')
  for (const name of ['normalizeApprovalList', 'loadZnApprovals', 'decideZnApproval', 'createZnApprovalRule', 'deleteZnApprovalRule', 'undoZnApproval']) {
    assert.match(client, new RegExp(name))
  }
  // The normalizer must fail closed on an unknown action kind.
  assert.match(client, /invalid approval action kind/)
  // CUR-4: the normalizer maps the diff-first review fields and the
  // applied list through to the workbench.
  assert.match(client, /diffText/)
  assert.match(client, /previousCaptured/)
  assert.match(client, /reviewNote/)
  assert.match(client, /applied/)
})

test('approval cards: normalizer keeps denied and request forwards diff_text', () => {
  const client = read('src/zn/resident-client.ts')
  const ipc = read('electron/zn-resident-ipc.ts')
  const state = read('src/zn/state.ts')
  // Wiring gap 1: the normalizer used to drop `denied`, so the desktop
  // could never see refused cards. The type carries it now too.
  assert.match(client, /denied: denied\.map\(normalizeApprovalRequest\)/)
  assert.match(state, /denied: ZnApprovalRequest\[\]/)
  // Wiring gap 2: approval-request IPC must forward diff_text to the
  // Resident (CUR-4 diff-first review), and the render layer exposes a
  // typed wrapper for it. No UI entry point creates cards by hand.
  assert.match(ipc, /diff_text: String\(payload\?\.diffText \|\| payload\?\.diff_text/)
  assert.match(client, /export async function requestZnApproval/)
  assert.match(client, /diffText: input\.diffText/)
})

test('approval cards: workbench shows a pending banner and a settings section', () => {
  const workbench = read('src/zn/workbench.tsx')
  assert.match(workbench, /ZnApprovalPanel/)
  assert.match(workbench, /approvalPendingCount > 0/)
  assert.match(workbench, /zn-settings-approvals/)
  assert.match(workbench, /settings\.approvals\.title/)
  assert.match(workbench, /openApprovals/)
})

test('approval cards: panel offers allow once / always allow / deny plus rules and audit', () => {
  const panel = read('src/zn/approval-panel.tsx')
  assert.match(panel, /approval\.allowOnce/)
  assert.match(panel, /approval\.alwaysAllow/)
  assert.match(panel, /approval\.deny/)
  assert.match(panel, /approval\.alwaysAllowKind/)
  assert.match(panel, /approval\.rules/)
  assert.match(panel, /approval\.audit/)
  assert.match(panel, /approval\.expired/)
  // Cards show action, target, scope and value.
  assert.match(panel, /approval\.target/)
  assert.match(panel, /approval\.scope/)
  assert.match(panel, /approval\.value/)
  // CUR-4: pending cards show the pending diff; applied cards offer
  // one-click undo and state that external copies are not recalled.
  assert.match(panel, /approval\.diff/)
  assert.match(panel, /approval\.applied/)
  assert.match(panel, /approval\.undo/)
  assert.match(panel, /approval\.undone/)
  assert.match(panel, /approval\.noUndoSnapshot/)
  assert.match(panel, /approval\.undoSideEffect/)
  assert.match(panel, /zn-approval-diff-text/)
})

test('approval cards: every approval string exists in both locales', () => {
  const localization = read('localization/zn-localization.ts')
  const keys = [
    'approval.title',
    'approval.description',
    'approval.pending',
    'approval.noPending',
    'approval.action',
    'approval.target',
    'approval.scope',
    'approval.value',
    'approval.source',
    'approval.expires',
    'approval.allowOnce',
    'approval.alwaysAllow',
    'approval.deny',
    'approval.expired',
    'approval.expiredDescription',
    'approval.alwaysAllowKind',
    'approval.rules',
    'approval.noRules',
    'approval.ruleEffect.askFirst',
    'approval.ruleEffect.autoAllow',
    'approval.addRule',
    'approval.deleteRule',
    'approval.audit',
    'approval.noAudit',
    'approval.kind.send',
    'approval.kind.publish',
    'approval.kind.purchase',
    'approval.kind.delete',
    'approval.kind.productionChange',
    'approval.loadFailed',
    'approval.decideFailed',
    'approval.ruleFailed',
    'approval.ruleTooBroad',
    'approval.banner',
    'approval.review',
    'approval.diff',
    'approval.reviewNote',
    'approval.applied',
    'approval.noApplied',
    'approval.undo',
    'approval.undone',
    'approval.noUndoSnapshot',
    'approval.undoFailed',
    'approval.undoSideEffect',
    'settings.approvals.title',
    'settings.approvals.description'
  ]
  for (const key of keys) {
    const matches = localization.match(new RegExp(`'${key.replaceAll('.', '\\.')}'`, 'g')) ?? []
    assert.ok(matches.length >= 2, `approval key ${key} must exist in both locales`)
  }
})
