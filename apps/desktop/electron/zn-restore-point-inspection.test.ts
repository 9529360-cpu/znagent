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

test('Work restore-point inspection and proposals stay read-only, fresh and resident-backed', () => {
  const state = read('src/zn/state.ts')
  const client = read('src/zn/resident-client.ts')
  const workbench = read('src/zn/workbench.tsx')
  const preload = read('electron/zn-preload.ts')

  assert.match(state, /ZnRestorePointCurrentStatus/)
  assert.match(state, /ZnRestoreProposalStatus/)
  assert.match(state, /requiresUserApproval: true/)
  assert.match(state, /requiresFreshRevalidation: true/)
  assert.match(state, /applicationAvailable: false/)
  assert.match(state, /automaticAuthority: false/)
  assert.match(state, /delete cached\.restorePoints/)
  assert.match(client, /resident\.workGet/)
  assert.match(client, /normalizeRestorePoint/)
  assert.match(client, /normalizeRestoreProposal/)
  assert.match(client, /restore_proposal/)
  assert.match(client, /loadZnWorkThread/)
  assert.match(workbench, /Restore points/)
  assert.match(workbench, /refreshRestorePoints/)
  assert.match(workbench, /Current target unchanged/)
  assert.match(workbench, /Current target changed/)
  assert.match(workbench, /Current target missing/)
  assert.match(workbench, /cannot be compared safely/)
  assert.match(workbench, /Restore candidate/)
  assert.match(workbench, /Review current changes before any restore/)
  assert.match(workbench, /Review missing target before any restore/)
  assert.match(workbench, /Restore proposal blocked/)
  assert.match(workbench, /user approval and fresh revalidation would be required/)
  assert.match(workbench, /Proposal and inspection only/)
  assert.match(preload, /workGet/)

  assert.doesNotMatch(client, /resident\.(restore|applyRestore)|applyZnRestore|restorePointApply/i)
  assert.doesNotMatch(workbench, />\s*(Restore|Apply restore)\s*</i)
  assert.doesNotMatch(state, /contentSha256|content_sha256|preIdentity|pre_identity/i)
})
