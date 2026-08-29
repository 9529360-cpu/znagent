export const ZN_RUNTIME_HANDOFF_FAILURE_BUDGET_MS = 10 * 60_000

export type ZnRuntimeHandoffTiming = {
  now: number
  deadline: number
  busy: boolean
}

/**
 * Resident-owned Work must never consume the desktop handoff failure budget.
 *
 * A pending old/surface-reduced resident may legitimately stay alive for hours
 * while durable Work is active. Every busy observation therefore renews the
 * finite failure budget. Once Work becomes idle, the existing deadline again
 * bounds actual restart/activation failures instead of creating an unbounded
 * retry loop.
 */
export function nextZnRuntimeHandoffDeadline({
  now,
  deadline,
  busy
}: ZnRuntimeHandoffTiming): number {
  const current = Number.isFinite(deadline) ? deadline : 0
  if (!busy) return current
  return Math.max(current, now + ZN_RUNTIME_HANDOFF_FAILURE_BUDGET_MS)
}

export function znRuntimeHandoffFailureBudgetExpired(now: number, deadline: number): boolean {
  return Number.isFinite(deadline) && deadline > 0 && now >= deadline
}
