/**
 * Read-only Work activity projection. No tool arguments, commands, raw output,
 * authority IDs, or model reasoning belong on this renderer data surface.
 */
export type ZnExecutionAction = {
  kind: string
  success: boolean
  at?: number
  summary: string
}

export const ZN_RECENT_ACTION_LIMIT = 6
const MAX_KIND_LENGTH = 80
const MAX_SUMMARY_LENGTH = 320

function normalizedTimestamp(value: unknown): number | undefined {
  if (typeof value === 'number') {
    return Number.isFinite(value) && value > 0 && !Number.isNaN(new Date(value).getTime())
      ? value : undefined
  }
  if (typeof value !== 'string' || !value.trim()) return undefined
  const at = Date.parse(value)
  return Number.isFinite(at) && at > 0 ? at : undefined
}

function normalizeAction(value: unknown): ZnExecutionAction | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const item = value as Record<string, unknown>
  // Unknown results must not be presented as failures or successes.
  if (typeof item.success !== 'boolean' || typeof item.kind !== 'string') return null
  const kind = item.kind.trim().slice(0, MAX_KIND_LENGTH)
  if (!kind) return null
  const summary = typeof item.summary === 'string'
    ? item.summary.trim().slice(0, MAX_SUMMARY_LENGTH)
    : ''
  const at = normalizedTimestamp(item.at)
  return { kind, success: item.success, ...(at ? { at } : {}), summary }
}

/** Preserve order and cap the observed actions; never infer omitted steps. */
export function znExecutionActionsFromUnknown(value: unknown): ZnExecutionAction[] {
  if (!Array.isArray(value)) return []
  return value.slice(-ZN_RECENT_ACTION_LIMIT).flatMap(item => {
    const action = normalizeAction(item)
    return action ? [action] : []
  })
}

export function znExecutionActionsFromDetail(
  detail: Record<string, unknown> | undefined
): ZnExecutionAction[] {
  if (!detail) return []
  return znExecutionActionsFromUnknown(detail.body_actions ?? detail.bodyActions)
}
