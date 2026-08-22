import type { ZnThread, ZnThreadMessage, ZnThreadRole } from './state'

export type ZnResidentSnapshot = {
  status: unknown
  self: unknown
}

export type ZnWorkSubmitResult = {
  thread: ZnThread
  run: unknown
}

function desktop() {
  const bridge = window.znDesktop
  if (!bridge?.resident) throw new Error('ZN desktop resident bridge is unavailable')
  return bridge
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function timestamp(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Date.parse(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return Date.now()
}

function role(value: unknown): ZnThreadRole {
  return value === 'user' || value === 'activity' ? value : 'zn'
}

function normalizeMessage(value: unknown): ZnThreadMessage | null {
  const item = record(value)
  if (!item) return null
  const id = String(item.id || '').trim()
  const text = String(item.text || '')
  if (!id) return null
  const detail = record(item.detail)
  return {
    id,
    role: role(item.role),
    text,
    at: timestamp(item.created_at || item.at),
    ...(detail ? { detail } : {})
  }
}

function normalizeThread(value: unknown): ZnThread {
  const item = record(value)
  if (!item) throw new Error('Resident returned an invalid work thread')
  const id = String(item.id || '').trim()
  if (!id) throw new Error('Resident work thread has no id')
  const rawMessages = Array.isArray(item.messages) ? item.messages : []
  const messages = rawMessages
    .map(normalizeMessage)
    .filter((message): message is ZnThreadMessage => Boolean(message))
  return {
    id,
    title: String(item.title || 'New work'),
    createdAt: timestamp(item.created_at || item.createdAt),
    updatedAt: timestamp(item.updated_at || item.updatedAt),
    messages
  }
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

export async function loadZnWorkThreads(): Promise<ZnThread[]> {
  const result = await desktop().resident.workList({ limit: 24, messageLimit: 120 })
  if (!Array.isArray(result)) throw new Error('Resident returned an invalid work list')
  return result.map(normalizeThread)
}

export async function createZnWorkThread(thread: ZnThread): Promise<ZnThread> {
  const result = await desktop().resident.workCreate({
    threadId: thread.id,
    title: thread.title,
    metadata: {}
  })
  return normalizeThread(result)
}

export async function submitZnWork(threadId: string, task: string): Promise<ZnWorkSubmitResult> {
  const normalized = task.trim()
  if (!normalized) throw new Error('Task must not be empty')
  const result = record(await desktop().resident.workSubmit({
    threadId,
    task: normalized,
    kind: 'desktop_user_event',
    priority: 0
  }))
  if (!result) throw new Error('Resident returned an invalid work result')
  return {
    thread: normalizeThread(result.thread),
    run: result.run
  }
}

export async function checkZnUpdate(): Promise<ZnDesktopUpdateStatus> {
  return desktop().updates.check()
}

export async function applyZnUpdate(): Promise<ZnDesktopUpdateApplyResult> {
  return desktop().updates.apply()
}
