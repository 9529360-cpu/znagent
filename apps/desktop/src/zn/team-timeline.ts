/**
 * Team group-chat timeline (P2-5): pure types + normalization for the
 * timeline the resident derives from the Work log.
 *
 * The timeline is read-only history: every entry maps 1:1 to a Work log
 * message (same id/text/timestamp). This module never invents entries and
 * never edits them; it only validates the resident's shape.
 */

export type ZnTeamTimelineKind =
  | 'message'
  | 'progress'
  | 'handoff'
  | 'blocker'
  | 'decision'
  | 'assignment'

export type ZnTeamTimelineEvidence = {
  label: string
  ref: string
  artifactId?: string
}

export type ZnTeamTimelineEntry = {
  id: string
  kind: ZnTeamTimelineKind
  author: string
  text: string
  at: number
  teamId: string
  fromAuthor: string
  toAuthor: string
  itemTitle: string
  objective: string
  instruction: string
  evidence: ZnTeamTimelineEvidence[]
}

export type ZnTeamTimeline = {
  teamId: string | null
  members: string[]
  entries: ZnTeamTimelineEntry[]
}

export type ZnTeamAssignResult = {
  teamId: string
  specialist: string
  itemId: string
  itemTitle: string
  instruction: string
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function timestamp(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Date.parse(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return 0
}

function timelineKind(value: unknown): ZnTeamTimelineKind {
  if (
    value === 'message' ||
    value === 'progress' ||
    value === 'handoff' ||
    value === 'blocker' ||
    value === 'decision' ||
    value === 'assignment'
  ) return value
  return 'message'
}

/**
 * Parse a leading `@specialist [instruction]` mention. Both half-width
 * `@` and full-width `＠` are accepted (CJK keyboards emit the latter).
 * Returns null when the text does not start with a mention.
 */
export function parseZnTeamMention(
  value: string
): { specialist: string; instruction: string } | null {
  const match = /^\s*[@＠]\s*([^\s@＠]+)\s*([\s\S]*)$/.exec(value)
  if (!match) return null
  const specialist = (match[1] || '').trim()
  if (!specialist) return null
  return { specialist, instruction: (match[2] || '').trim() }
}

function normalizeEvidence(value: unknown): ZnTeamTimelineEvidence[] {
  if (!Array.isArray(value)) return []
  return value.slice(0, 32).flatMap(item => {
    const entry = record(item)
    if (!entry) return []
    const label = text(entry.label).trim().slice(0, 300)
    const ref = text(entry.ref).trim().slice(0, 2000)
    if (!label || !ref) return []
    const artifactId = text(entry.artifact_id ?? entry.artifactId).trim()
    return [{
      label,
      ref,
      ...(artifactId ? { artifactId } : {})
    }]
  })
}

function normalizeEntry(value: unknown): ZnTeamTimelineEntry | null {
  const item = record(value)
  if (!item) return null
  const id = text(item.id).trim()
  if (!id) return null
  return {
    id,
    kind: timelineKind(item.kind),
    author: text(item.author),
    text: text(item.text),
    at: timestamp(item.at),
    teamId: text(item.team_id ?? item.teamId),
    fromAuthor: text(item.from_author ?? item.fromAuthor),
    toAuthor: text(item.to_author ?? item.toAuthor),
    itemTitle: text(item.item_title ?? item.itemTitle),
    objective: text(item.objective),
    instruction: text(item.instruction),
    evidence: normalizeEvidence(item.evidence)
  }
}

export function normalizeZnTeamTimeline(value: unknown): ZnTeamTimeline | null {
  const item = record(value)
  if (!item) return null
  const teamId = text(item.team_id ?? item.teamId).trim()
  const members = Array.isArray(item.members)
    ? item.members
        .slice(0, 64)
        .filter((member): member is string => typeof member === 'string' && Boolean(member.trim()))
    : []
  if (!Array.isArray(item.entries)) return null
  return {
    teamId: teamId || null,
    members,
    entries: item.entries
      .slice(0, 500)
      .map(normalizeEntry)
      .filter((entry): entry is ZnTeamTimelineEntry => entry !== null)
  }
}

export function normalizeZnTeamAssignResult(value: unknown): ZnTeamAssignResult | null {
  const item = record(value)
  if (!item) return null
  const teamId = text(item.team_id ?? item.teamId).trim()
  const specialist = text(item.specialist).trim()
  const itemId = text(item.item_id ?? item.itemId).trim()
  const itemTitle = text(item.item_title ?? item.itemTitle).trim()
  if (!teamId || !specialist || !itemId || !itemTitle) return null
  return {
    teamId,
    specialist,
    itemId,
    itemTitle,
    instruction: text(item.instruction)
  }
}
