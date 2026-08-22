export type ZnResidentSnapshot = {
  status: unknown
  self: unknown
}

function desktop() {
  const bridge = window.znDesktop
  if (!bridge?.resident) throw new Error('ZN desktop resident bridge is unavailable')
  return bridge
}

export async function loadZnResidentSnapshot(): Promise<ZnResidentSnapshot> {
  const resident = desktop().resident
  let initial: unknown
  try {
    initial = await resident.status()
  } catch {
    initial = await resident.start()
  }

  const [status, self] = await Promise.all([
    resident.status().catch(() => initial),
    resident.self().catch(() => null)
  ])
  return { status, self }
}

export async function submitZnTask(task: string): Promise<unknown> {
  const normalized = task.trim()
  if (!normalized) throw new Error('Task must not be empty')
  return desktop().resident.submit({
    task: normalized,
    kind: 'desktop_user_event',
    priority: 0
  })
}

export async function checkZnUpdate(): Promise<ZnDesktopUpdateStatus> {
  return desktop().updates.check()
}

export async function applyZnUpdate(): Promise<ZnDesktopUpdateApplyResult> {
  return desktop().updates.apply()
}
