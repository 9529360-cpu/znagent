export type ZnThreadRole = 'user' | 'zn' | 'activity'

export type ZnThreadMessage = {
  id: string
  role: ZnThreadRole
  text: string
  at: number
  detail?: Record<string, unknown>
}

export type ZnWorkspace = {
  path: string
  name: string
  attachedAt?: number
}

export type ZnArtifactKind = 'file' | 'diff' | 'terminal' | 'presentation' | 'other'

export type ZnArtifact = {
  id: string
  eventId: string
  kind: ZnArtifactKind
  name: string
  content: string
  path?: string
  createdAt: number
  metadata?: Record<string, unknown>
}

export type ZnRestorePointCurrentStatus = 'unchanged' | 'changed' | 'missing' | 'unsupported'
export type ZnRestoreProposalStatus = 'candidate' | 'conflict_review_required' | 'missing_target_review_required' | 'blocked'
export type ZnRestoreApplicationStatus =
  | 'approval_required'
  | 'applying'
  | 'stage_ready'
  | 'commit_started'
  | 'completed'
  | 'recovery_required'
  | 'blocked'

export type ZnRestoreProposal = {
  kind: 'restore_exact_file'
  status: ZnRestoreProposalStatus
  reason: string
  destructive: true
  requiresUserApproval: true
  requiresFreshRevalidation: true
  applicationAvailable: boolean
  applicationScope?: 'missing_target_no_replace'
  automaticAuthority: false
}

export type ZnRestorePoint = {
  id: string
  eventId: string
  targetPath: string
  sizeBytes: number
  status: string
  currentStatus: ZnRestorePointCurrentStatus
  currentReason: string
  currentObservedAt: number
  currentExists?: boolean
  currentType: string
  currentSizeBytes?: number
  createdAt: number
  updatedAt: number
  proposal?: ZnRestoreProposal
  automaticRestoreAuthority: false
  restoreApplicationAvailable: boolean
}

export type ZnRestoreApplication = {
  id: string
  status: ZnRestoreApplicationStatus
  requiresUserApproval: boolean
  freshRevalidationRequired: boolean
  automaticAuthority: false
  error?: string
  updatedAt: number
  completedAt?: number
}

export type ZnThread = {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  messages: ZnThreadMessage[]
  artifacts: ZnArtifact[]
  workspace?: ZnWorkspace
  restorePoints?: ZnRestorePoint[]
}

const STORAGE_KEY = 'zn.desktop.thread-cache.v1'
const MAX_THREADS = 24
const MAX_MESSAGES_PER_THREAD = 120
const MAX_ARTIFACTS_PER_THREAD = 48

function id(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`
}

export function newZnThread(now = Date.now()): ZnThread {
  return {
    id: id('work'),
    title: 'New work',
    createdAt: now,
    updatedAt: now,
    messages: [],
    artifacts: []
  }
}

export function titleForZnTask(task: string): string {
  const normalized = task.trim().replace(/\s+/g, ' ')
  if (!normalized) return 'New work'
  return normalized.length <= 48 ? normalized : `${normalized.slice(0, 47).trimEnd()}…`
}

export function addZnThreadMessage(
  thread: ZnThread,
  role: ZnThreadRole,
  text: string,
  detail?: Record<string, unknown>,
  now = Date.now()
): ZnThread {
  const message: ZnThreadMessage = {
    id: id('msg'),
    role,
    text,
    at: now,
    ...(detail ? { detail } : {})
  }
  const messages = [...thread.messages, message].slice(-MAX_MESSAGES_PER_THREAD)
  return {
    ...thread,
    title: thread.messages.length === 0 && role === 'user' ? titleForZnTask(text) : thread.title,
    updatedAt: now,
    messages
  }
}

function isThread(value: unknown): value is ZnThread {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const record = value as Record<string, unknown>
  return (
    typeof record.id === 'string' &&
    typeof record.title === 'string' &&
    typeof record.createdAt === 'number' &&
    typeof record.updatedAt === 'number' &&
    Array.isArray(record.messages)
  )
}

function withoutTransientRestorePoints(thread: ZnThread): ZnThread {
  const cached = { ...thread }
  delete cached.restorePoints
  return cached
}

export function loadZnThreadCache(): ZnThread[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return []
    return parsed.filter(isThread).slice(0, MAX_THREADS).map(thread => {
      const cached = withoutTransientRestorePoints(thread)
      return {
        ...cached,
        messages: cached.messages.slice(-MAX_MESSAGES_PER_THREAD),
        artifacts: Array.isArray(cached.artifacts)
          ? cached.artifacts.slice(0, MAX_ARTIFACTS_PER_THREAD)
          : []
      }
    })
  } catch {
    return []
  }
}

export function saveZnThreadCache(threads: readonly ZnThread[]): void {
  try {
    const bounded = [...threads]
      .sort((left, right) => right.updatedAt - left.updatedAt)
      .slice(0, MAX_THREADS)
      .map(thread => {
        const cached = withoutTransientRestorePoints(thread)
        return {
          ...cached,
          messages: cached.messages.slice(-MAX_MESSAGES_PER_THREAD),
          artifacts: cached.artifacts.slice(0, MAX_ARTIFACTS_PER_THREAD)
        }
      })
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(bounded))
  } catch {
    // The cache is convenience state only. Resident identity/memory must never
    // depend on browser storage; fresh restore-point inspection is transient too.
  }
}
