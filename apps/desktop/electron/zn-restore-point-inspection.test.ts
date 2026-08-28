import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { test } from 'vitest'

const here = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(here, '..')

function read(relative: string): string {
  return fs.readFileSync(path.join(desktopRoot, relative), 'utf8')
}

test('Work restore points expose only explicit missing-target no-replace application', () => {
  const state = read('src/zn/state.ts')
  const client = read('src/zn/resident-client.ts')
  const controls = read('src/zn/restore-controls.tsx')
  const workbench = read('src/zn/workbench.tsx')
  const preload = read('electron/zn-preload.ts')
  const ipc = read('electron/zn-resident-ipc.ts')

  assert.match(state, /ZnRestorePointCurrentStatus/)
  assert.match(state, /ZnRestoreProposalStatus/)
  assert.match(state, /ZnRestoreApplicationStatus/)
  assert.match(state, /requiresUserApproval: true/)
  assert.match(state, /requiresFreshRevalidation: true/)
  assert.match(state, /applicationScope\?: 'missing_target_no_replace'/)
  assert.match(state, /automaticAuthority: false/)
  assert.match(state, /delete cached\.restorePoints/)

  assert.match(client, /resident\.workGet/)
  assert.match(client, /normalizeRestorePoint/)
  assert.match(client, /normalizeRestoreProposal/)
  assert.match(client, /normalizeRestoreApplication/)
  assert.match(client, /status !== 'missing_target_review_required'/)
  assert.match(client, /applicationScope !== 'missing_target_no_replace'/)
  assert.match(client, /currentStatus === 'missing'/)
  assert.match(client, /prepareZnMissingWorkRestore/)
  assert.match(client, /approveZnMissingWorkRestore/)
  assert.match(client, /workRestorePrepare/)
  assert.match(client, /workRestoreApprove/)

  assert.match(preload, /workRestorePrepare/)
  assert.match(preload, /workRestoreApprove/)
  assert.match(ipc, /zn:resident:work-restore-prepare/)
  assert.match(ipc, /zn:resident:work-restore-approve/)
  assert.match(ipc, /if \(!threadId\) throw new Error\('threadId is required'\)/)
  assert.match(ipc, /work_restore_prepare/)
  assert.match(ipc, /work_restore_approve/)

  assert.match(workbench, /Restore points/)
  assert.match(workbench, /ZnMissingRestoreControls/)
  assert.match(workbench, /Changed, unchanged and unsafe targets remain inspection-only/)
  assert.match(controls, /point\.currentStatus === 'missing'/)
  assert.match(controls, /point\.proposal\.applicationScope === 'missing_target_no_replace'/)
  assert.match(controls, /Prepare restore/)
  assert.match(controls, /Approve exact restore/)
  assert.match(controls, /never overwrites a target that exists again/)
  assert.match(controls, /prepareZnMissingWorkRestore/)
  assert.match(controls, /approveZnMissingWorkRestore/)

  const prepareIndex = controls.indexOf('prepareZnMissingWorkRestore(threadId, point.id)')
  const approveIndex = controls.indexOf('approveZnMissingWorkRestore(threadId, application.id)')
  assert.ok(prepareIndex >= 0)
  assert.ok(approveIndex > prepareIndex)

  assert.doesNotMatch(state, /contentSha256|content_sha256|preIdentity|pre_identity/i)
  assert.doesNotMatch(client, /contentSha256|content_sha256|preIdentity|pre_identity/i)
  assert.doesNotMatch(controls, /workSubmit|resident\.submit|automatic/i)
})
