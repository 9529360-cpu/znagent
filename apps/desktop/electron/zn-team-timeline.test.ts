import assert from 'node:assert/strict'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { build } from 'esbuild'
import { test } from 'vitest'

const here = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(here, '..')

type TeamTimelineModule = {
  parseZnTeamMention?: (value: string) => { specialist: string; instruction: string } | null
  normalizeZnTeamTimeline?: (value: unknown) => {
    teamId: string | null
    members: string[]
    entries: Array<{
      id: string
      kind: string
      author: string
      text: string
      at: number
      fromAuthor: string
      toAuthor: string
      itemTitle: string
      evidence: Array<{ label: string; ref: string; artifactId?: string }>
    }>
  } | null
}

async function loadModule(): Promise<TeamTimelineModule> {
  const result = await build({
    entryPoints: [path.join(desktopRoot, 'src/zn/team-timeline.ts')],
    bundle: true,
    write: false,
    format: 'esm',
    platform: 'browser',
    target: 'es2023'
  })
  const output = result.outputFiles[0]
  assert.ok(output)
  const moduleUrl = `data:text/javascript;base64,${Buffer.from(output.text).toString('base64')}`
  const module = (await import(moduleUrl)) as TeamTimelineModule
  assert.equal(typeof module.parseZnTeamMention, 'function')
  assert.equal(typeof module.normalizeZnTeamTimeline, 'function')
  return module
}

test('team mention parsing accepts @ and full-width ＠', async () => {
  const { parseZnTeamMention } = await loadModule()
  assert.deepEqual(parseZnTeamMention!('@调研-01 先把登录做了'), {
    specialist: '调研-01',
    instruction: '先把登录做了'
  })
  assert.deepEqual(parseZnTeamMention!('＠开发-02'), {
    specialist: '开发-02',
    instruction: ''
  })
  assert.equal(parseZnTeamMention!('调研-01 做调研'), null)
  assert.equal(parseZnTeamMention!('@'), null)
})

test('team timeline normalization keeps only bounded user-readable fields', async () => {
  const { normalizeZnTeamTimeline } = await loadModule()
  const result = normalizeZnTeamTimeline!({
    team_id: 't1',
    members: ['调研-01', '开发-02'],
    entries: [
      {
        id: 'm1',
        kind: 'handoff',
        author: 'coordinator',
        text: '派活：XX 项目·调研 → 调研-01',
        at: '2026-10-14T00:00:00Z',
        team_id: 't1',
        from_author: 'coordinator',
        to_author: '调研-01',
        item_title: 'XX 项目·调研',
        evidence: [{ label: 'notes.md', ref: 'notes.md', artifact_id: 'a1' }],
        secret_field: 'SECRET'
      },
      {
        id: 'm2',
        kind: 'bogus-kind',
        author: '调研-01',
        text: '调研结论',
        at: '2026-10-14T00:01:00Z'
      },
      { id: '', kind: 'message', author: 'x', text: 'dropped: no id' },
      'not-an-entry'
    ]
  })

  assert.ok(result)
  assert.equal(result.teamId, 't1')
  assert.deepEqual(result.members, ['调研-01', '开发-02'])
  assert.equal(result.entries.length, 2)
  assert.equal(result.entries[0]?.kind, 'handoff')
  assert.equal(result.entries[0]?.toAuthor, '调研-01')
  assert.equal(result.entries[0]?.itemTitle, 'XX 项目·调研')
  assert.deepEqual(result.entries[0]?.evidence, [
    { label: 'notes.md', ref: 'notes.md', artifactId: 'a1' }
  ])
  assert.equal(result.entries[0]?.at, Date.parse('2026-10-14T00:00:00Z'))
  // Unknown kinds fall back to a plain message, never a new kind.
  assert.equal(result.entries[1]?.kind, 'message')
  assert.ok(!JSON.stringify(result).includes('SECRET'))
  assert.equal(normalizeZnTeamTimeline!(null), null)
  assert.equal(normalizeZnTeamTimeline!({ entries: 'nope' }), null)
})
