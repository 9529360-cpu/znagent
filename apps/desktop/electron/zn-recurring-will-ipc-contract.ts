type ZnRecurringBridgePayload = Record<string, unknown>

function asPayload(raw: unknown): ZnRecurringBridgePayload {
  return raw && typeof raw === 'object' && !Array.isArray(raw)
    ? (raw as ZnRecurringBridgePayload)
    : {}
}

function firstValue(
  payload: ZnRecurringBridgePayload,
  camelName: string,
  snakeName: string
): unknown {
  return payload[camelName] ?? payload[snakeName]
}

function requiredText(value: unknown, field: string): string {
  const text = String(value ?? '').trim()
  if (!text) throw new Error(`${field} is required`)
  return text
}

function integerValue(value: unknown, field: string): number {
  const number = typeof value === 'number'
    ? value
    : typeof value === 'string' && value.trim()
      ? Number(value)
      : Number.NaN
  if (!Number.isSafeInteger(number)) throw new Error(`${field} must be an integer`)
  return number
}

export function normalizeZnRecurringSchedulePayload(raw: unknown): Record<string, unknown> {
  const payload = asPayload(raw)
  const description = requiredText(payload.description, 'description')
  const task = requiredText(payload.task, 'task')
  const intervalSeconds = integerValue(
    firstValue(payload, 'intervalSeconds', 'interval_seconds'),
    'intervalSeconds'
  )
  const priority = integerValue(payload.priority ?? 0, 'priority')
  const source = String(payload.source ?? 'user').trim() || 'user'
  const firstDueAt = String(
    firstValue(payload, 'firstDueAt', 'first_due_at') ?? ''
  ).trim()

  return {
    description,
    task,
    interval_seconds: intervalSeconds,
    source,
    priority,
    ...(firstDueAt ? { first_due_at: firstDueAt } : {})
  }
}

export function normalizeZnRecurringListPayload(raw: unknown): Record<string, unknown> {
  const payload = asPayload(raw)
  const rawLimit = payload.limit ?? 20
  const limit = integerValue(rawLimit, 'limit')
  if (limit < 1) throw new Error('limit must be positive')
  return {
    limit: Math.min(100, limit),
    enabled_only: firstValue(payload, 'enabledOnly', 'enabled_only') === true
  }
}

export function normalizeZnRecurringDisablePayload(raw: unknown): Record<string, unknown> {
  const payload = asPayload(raw)
  return {
    intention_id: requiredText(
      firstValue(payload, 'intentionId', 'intention_id'),
      'intentionId'
    )
  }
}
