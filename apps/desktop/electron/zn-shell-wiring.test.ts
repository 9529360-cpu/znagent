import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { test } from 'vitest'

function read(relative: string): string {
  return readFileSync(join(__dirname, '..', relative), 'utf8')
}

test('shell wiring: data hook talks to the real backend through resident-client only', () => {
  const hooks = read('src/zn/zn-data-hooks.ts')
  // Real backend calls, via the resident-client wrappers.
  for (const name of [
    'loadZnResidentSnapshot',
    'loadZnWorkThreads',
    'loadZnWorkThread',
    'createZnWorkThread',
    'startZnWork',
    'loadZnWorkProgress',
    'loadZnApprovals',
    'decideZnApproval',
    'loadZnSuggestions'
  ]) {
    assert.match(hooks, new RegExp(name))
  }
  // One seam: the shell never touches the bridge, IPC, fetch or the
  // Resident socket itself; everything goes through resident-client.
  assert.doesNotMatch(hooks, /window\.znDesktop/)
  assert.doesNotMatch(hooks, /ipcRenderer/)
  assert.doesNotMatch(hooks, /fetch\(/)
  assert.doesNotMatch(hooks, /resident-endpoint/)
  // Chat sends through work_start (steering), never the blocking
  // work_submit used by the `zn` CLI.
  assert.doesNotMatch(hooks, /submitZnWork|workSubmit/)
})

test('shell wiring: polling rhythm matches the spec (snapshot 12s, approvals 30s, progress 700ms read-only)', () => {
  const hooks = read('src/zn/zn-data-hooks.ts')
  const reconnection = read('src/zn/work-reconnection.ts')
  assert.match(hooks, /setInterval\(\(\) => void refreshSnapshot\(\), 12_000\)/)
  assert.match(hooks, /setInterval\(\(\) => void refreshApprovals\(\), 30_000\)/)
  // Progress follows the shared 700ms read-only observer; the hook never
  // re-sends a user task to poll.
  assert.match(hooks, /observeZnWorkProgress/)
  assert.match(reconnection, /intervalMs = 700/)
  assert.match(hooks, /activeRun/)
})

test('shell wiring: approval decisions are sent once with real always_allow semantics', () => {
  const hooks = read('src/zn/zn-data-hooks.ts')
  assert.match(hooks, /decideZnApproval\(approvalId, verdict/)
  // always_allow is passed through with the backend's real semantics,
  // never downgraded to allow_once.
  assert.match(hooks, /always_allow.*后端真实语义/)
  assert.doesNotMatch(hooks, /always_allow' \? 'allow_once/)
  // A decided card is hidden until the backend confirms, so the vendor
  // card's simulated 1200ms success state is never shown.
  assert.match(hooks, /decidedApprovals/)
  assert.match(hooks, /DECIDED_APPROVAL_TTL_MS/)
})

test('shell wiring: cross-zone drag dedupes reorder and keeps pin state in the hook', () => {
  const hooks = read('src/zn/zn-data-hooks.ts')
  assert.match(hooks, /onReorderSessions/)
  assert.match(hooks, /onTogglePin/)
  // Reorder dedupes ids (first occurrence wins); pin lives in the hook.
  assert.match(hooks, /seen\.has\(id\)/)
  assert.match(hooks, /setPinned/)
  assert.match(hooks, /setSessionOrder/)
})

test('shell wiring: identity is ZN, and no fake data is invented', () => {
  const bubbles = read('../../vendor/open-claude-ui/code-examples/ChatMessageBubbles.tsx')
  // The vendor bubble's only identity word reads ZN now.
  assert.match(bubbles, />ZN</)
  assert.doesNotMatch(bubbles, />Claude</)
  const hooks = read('src/zn/zn-data-hooks.ts')
  // The hook still starts from loading; nothing is fabricated.
  assert.match(hooks, /useState<ZnShellConnection>\('loading'\)/)
})
