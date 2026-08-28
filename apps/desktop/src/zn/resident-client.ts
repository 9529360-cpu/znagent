import type {
  ZnArtifact,
  ZnArtifactKind,
  ZnRestorePoint,
  ZnRestorePointCurrentStatus,
  ZnRestoreProposal,
  ZnRestoreProposalStatus,
  ZnThread,
  ZnThreadMessage,
  ZnThreadRole,
  ZnWorkspace
} from './state'

export type ZnResidentSnapshot = {
  status: unknown
  self: unknown
}

export type ZnWorkSubmitResult = {
  thread: ZnThread
  run: unknown
}

export type ZnWorkRecovery = {
  status: string
  kind: string
  replayBlocked: boolean
  decision: string
  verificationKind?: string
  reason?: string
}

export type ZnWorkProgress = {
  eventId: string
  threadId: string
  status: string
  stage: string
  nextAction: string
  terminal: boolean
  finalized: boolean
  updatedAt: number
  error?: string
  recovery?: ZnWorkRecovery
  thought?: {
    at: number
    focus: string
    action: string
    actionKind: string
    reason: string
    confidence: number
  }
  investigation?: {
    rounds: number
    status: string
    unresolved: string
    nextProbe: string
    evidenceCount: number
  }
  bodyActions: Array<{
    kind: string
    success: boolean
    at: number
    summary: string
  }>
}

export type ZnWorkStartResult = {
  thread: ZnThread
  progress: ZnWorkProgress
}

export type ZnWorkProgressResult = {
  progress: ZnWorkProgress
  thread?: ZnThread
}

export type ZnProviderCredentialStatus = {
  configured: boolean
  source: 'none' | 'secure_store' | 'secure_store_unavailable' | 'environment' | 'config' | string
  environmentName?: string
  secureStore: {
    available: boolean
    backend: string
    error?: string
  }
}

export type ZnProviderSettings = {
  mode: string
  editable: boolean
  provider: string
  model: string
  baseUrl: string
  credential: ZnProviderCredentialStatus
  cognitionAvailable: boolean
  configurationError?: string
  activeRoutes: Array<{ id: string; provider: string; model: string }>
  routeCount?: number
}

export type ZnProviderSettingsUpdate = {
  provider: string
  model: string
  baseUrl?: string
  apiKey?: string
  clearCredential?: boolean
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

function artifactKind(value: unknown): ZnArtifactKind {
  return value === 'file' || value === 'diff' || value === 'terminal' ? value : 'other'
}

function restorePointCurrentStatus(value: unknown): ZnRestorePointCurrentStatus {
  return value === 'unchanged' || value === 'changed' || value === 'missing'
    ? value
    : 'unsupported'
}

function restoreProposalStatus(value: unknown): ZnRestoreProposalStatus {
  if (
    value === 'candidate' ||
    value === 'conflict_review_required' ||
    value === 'missing_target_review_required'
  ) return value
  return 'blocked'
}

function normalizeRestoreProposal(value: unknown): ZnRestoreProposal | undefined {
  const item = record(value)
  if (!item || item.kind !== 'restore_exact_file') return undefined
  if (
    item.destructive !== true ||
    item.requires_user_approval !== true ||
    item.requires_fresh_revalidation !== true ||
    item.application_available !== false ||
    item.automatic_authority !== false
  ) return undefined
  return {
    kind: 'restore_exact_file',
    status: restoreProposalStatus(item.status),
    reason: String(item.reason || ''),
    destructive: true,
    requiresUserApproval: true,
    requiresFreshRevalidation: true,
    applicationAvailable: false,
    automaticAuthority: false
  }
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

function normalizeArtifact(value: unknown): ZnArtifact | null {
  const item = record(value)
  if (!item) return null
  const id = String(item.id || '').trim()
  if (!id) return null
  const path = String(item.path || '').trim()
  const metadata = record(item.metadata)
  return {
    id,
    eventId: String(item.event_id || item.eventId || '').trim(),
    kind: artifactKind(item.kind),
    name: String(item.name || path || 'Artifact'),
    content: String(item.content || ''),
    ...(path ? { path } : {}),
    createdAt: timestamp(item.created_at || item.createdAt),
    ...(metadata ? { metadata } : {})
  }
}

function normalizeRestorePoint(value: unknown): ZnRestorePoint | null {
  const item = record(value)
  if (!item) return null
  const id = String(item.restore_point_id || item.restorePointId || item.id || '').trim()
  const eventId = String(item.event_id || item.eventId || '').trim()
  const targetPath = String(item.target_path || item.targetPath || '').trim()
  if (!id || !eventId || !targetPath) return null
  const currentExistsRaw = item.current_exists ?? item.currentExists
  const currentSizeRaw = item.current_size_bytes ?? item.currentSizeBytes
  const sizeBytes = Number(item.size_bytes ?? item.sizeBytes ?? 0)
  const proposal = normalizeRestoreProposal(item.restore_proposal || item.restoreProposal)
  return {
    id,
    eventId,
    targetPath,
    sizeBytes: Number.isFinite(sizeBytes) && sizeBytes >= 0 ? sizeBytes : 0,
    status: String(item.status || 'retained'),
    currentStatus: restorePointCurrentStatus(item.current_status || item.currentStatus),
    currentReason: String(item.current_reason || item.currentReason || ''),
    currentObservedAt: timestamp(item.current_observed_at || item.currentObservedAt),
    ...(typeof currentExistsRaw === 'boolean' ? { currentExists: currentExistsRaw } : {}),
    currentType: String(item.current_type || item.currentType || 'unknown'),
    ...(typeof currentSizeRaw === 'number' && Number.isFinite(currentSizeRaw) && currentSizeRaw >= 0
      ? { currentSizeBytes: currentSizeRaw }
      : {}),
    createdAt: timestamp(item.created_at || item.createdAt),
    updatedAt: timestamp(item.updated_at || item.updatedAt),
    ...(proposal ? { proposal } : {}),
    automaticRestoreAuthority: false,
    restoreApplicationAvailable: false
  }
}

function normalizeWorkspace(value: unknown): ZnWorkspace | undefined {
  const metadata = record(value)
  const raw = record(metadata?.workspace)
  if (!raw) return undefined
  const path = String(raw.path || '').trim()
  if (!path) return undefined
  const name = String(raw.name || '').trim() || path
  const attachedAt = raw.attached_at || raw.attachedAt
  return {
    path,
    name,
    ...(attachedAt ? { attachedAt: timestamp(attachedAt) } : {})
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
  const rawArtifacts = Array.isArray(item.artifacts) ? item.artifacts : []
  const artifacts = rawArtifacts
    .map(normalizeArtifact)
    .filter((artifact): artifact is ZnArtifact => Boolean(artifact))
  const metadata = record(item.metadata)
  const workspace = normalizeWorkspace(metadata)
  const rawRestorePoints = Array.isArray(metadata?.restore_points)
    ? metadata.restore_points
    : Array.isArray(metadata?.restorePoints)
      ? metadata.restorePoints
      : null
  const restorePoints = rawRestorePoints
    ? rawRestorePoints
      .map(normalizeRestorePoint)
      .filter((point): point is ZnRestorePoint => Boolean(point))
    : undefined
  return {
    id,
    title: String(item.title || 'New work'),
    createdAt: timestamp(item.created_at || item.createdAt),
    updatedAt: timestamp(item.updated_at || item.updatedAt),
    messages,
    artifacts,
    ...(workspace ? { workspace } : {}),
    ...(restorePoints ? { restorePoints } : {})
  }
}

function normalizeWorkRecovery(value: unknown): ZnWorkRecovery | undefined {
  const item = record(value)
  if (!item) return undefined
  const status = String(item.status || '').trim()
  const kind = String(item.kind || '').trim()
  const decision = String(item.decision || '').trim()
  if (!status || !kind || !decision) return undefined
  const verificationKind = String(item.verification_kind || item.verificationKind || '').trim()
  const reason = String(item.reason || '').trim()
  return {
    status,
    kind,
    replayBlocked: item.replay_blocked === true || item.replayBlocked === true,
    decision,
    ...(verificationKind ? { verificationKind } : {}),
    ...(reason ? { reason } : {})
  }
}

function normalizeWorkProgress(value: unknown): ZnWorkProgress {
  const item = record(value)
  if (!item) throw new Error('Resident returned invalid work progress')
  const eventId = String(item.event_id || item.eventId || '').trim()
  const threadId = String(item.thread_id || item.threadId || '').trim()
  if (!eventId || !threadId) throw new Error('Resident work progress is missing identity')

  const recovery = normalizeWorkRecovery(item.recovery)
  const rawThought = record(item.thought)
  const thought = rawThought
    ? {
        at: timestamp(rawThought.at),
        focus: String(rawThought.focus || ''),
        action: String(rawThought.action || ''),
        actionKind: String(rawThought.action_kind || rawThought.actionKind || ''),
        reason: String(rawThought.reason || ''),
        confidence: Number(rawThought.confidence || 0)
      }
    : undefined
  const rawInvestigation = record(item.investigation)
  const investigation = rawInvestigation
    ? {
        rounds: Number(rawInvestigation.rounds || 0),
        status: String(rawInvestigation.status || ''),
        unresolved: String(rawInvestigation.unresolved || ''),
        nextProbe: String(rawInvestigation.next_probe || rawInvestigation.nextProbe || ''),
        evidenceCount: Number(rawInvestigation.evidence_count || rawInvestigation.evidenceCount || 0)
      }
    : undefined
  const bodyActions = (Array.isArray(item.body_actions || item.bodyActions)
    ? (item.body_actions || item.bodyActions) as unknown[]
    : []).flatMap(value => {
      const action = record(value)
      if (!action) return []
      return [{
        kind: String(action.kind || ''),
        success: action.success === true,
        at: timestamp(action.at),
        summary: String(action.summary || '')
      }]
    })
  const error = String(item.error || '').trim()
  return {
    eventId,
    threadId,
    status: String(item.status || 'pending'),
    stage: String(item.stage || 'queued'),
    nextAction: String(item.next_action || item.nextAction || ''),
    terminal: item.terminal === true,
    finalized: item.finalized === true,
    updatedAt: timestamp(item.updated_at || item.updatedAt),
    ...(error ? { error } : {}),
    ...(recovery ? { recovery } : {}),
    ...(thought ? { thought } : {}),
    ...(investigation ? { investigation } : {}),
    bodyActions
  }
}

function normalizeProviderSettings(value: unknown): ZnProviderSettings {
  const item = record(value)
  if (!item) throw new Error('Resident returned invalid provider settings')
  const credential = record(item.credential) || {}
  const secureStore = record(credential.secure_store || credential.secureStore) || {}
  const rawRoutes = Array.isArray(item.active_routes || item.activeRoutes)
    ? (item.active_routes || item.activeRoutes) as unknown[]
    : []
  const activeRoutes = rawRoutes.flatMap(value => {
    const route = record(value)
    if (!route) return []
    return [{
      id: String(route.id || ''),
      provider: String(route.provider || ''),
      model: String(route.model || '')
    }]
  })
  const environmentName = String(credential.environment_name || credential.environmentName || '').trim()
  const secureError = String(secureStore.error || '').trim()
  const configurationError = String(item.configuration_error || item.configurationError || '').trim()
  return {
    mode: String(item.mode || 'default'),
    editable: item.editable !== false,
    provider: String(item.provider || 'auto'),
    model: String(item.model || ''),
    baseUrl: String(item.base_url || item.baseUrl || ''),
    credential: {
      configured: credential.configured === true,
      source: String(credential.source || 'none'),
      ...(environmentName ? { environmentName } : {}),
      secureStore: {
        available: secureStore.available === true,
        backend: String(secureStore.backend || 'unavailable'),
        ...(secureError ? { error: secureError } : {})
      }
    },
    cognitionAvailable: item.cognition_available === true || item.cognitionAvailable === true,
    ...(configurationError ? { configurationError } : {}),
    activeRoutes,
    ...(typeof item.route_count === 'number' ? { routeCount: item.route_count } : {})
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

export async function loadZnProviderSettings(): Promise<ZnProviderSettings> {
  return normalizeProviderSettings(await desktop().resident.providerSettings())
}

export async function updateZnProviderSettings(
  update: ZnProviderSettingsUpdate
): Promise<ZnProviderSettings> {
  const provider = update.provider.trim()
  const model = update.model.trim()
  if (!provider) throw new Error('Provider is required')
  if (!model) throw new Error('Model is required')
  return normalizeProviderSettings(await desktop().resident.providerSettingsUpdate({
    provider,
    model,
    baseUrl: update.baseUrl?.trim() || '',
    ...(update.apiKey?.trim() ? { apiKey: update.apiKey.trim() } : {}),
    clearCredential: update.clearCredential === true
  }))
}

export async function loadZnWorkThreads(): Promise<ZnThread[]> {
  const result = await desktop().resident.workList({ limit: 24, messageLimit: 120 })
  if (!Array.isArray(result)) throw new Error('Resident returned an invalid work list')
  return result.map(normalizeThread)
}

export async function loadZnWorkThread(threadId: string): Promise<ZnThread> {
  const normalized = threadId.trim()
  if (!normalized) throw new Error('Work thread id is required')
  return normalizeThread(await desktop().resident.workGet({
    threadId: normalized,
    messageLimit: 120
  }))
}

export async function createZnWorkThread(thread: ZnThread): Promise<ZnThread> {
  const result = await desktop().resident.workCreate({
    threadId: thread.id,
    title: thread.title,
    metadata: {}
  })
  return normalizeThread(result)
}

export async function startZnWork(threadId: string, task: string): Promise<ZnWorkStartResult> {
  const normalized = task.trim()
  if (!normalized) throw new Error('Task must not be empty')
  const result = record(await desktop().resident.workStart({
    threadId,
    task: normalized,
    kind: 'desktop_user_event',
    priority: 0
  }))
  if (!result) throw new Error('Resident returned an invalid work start result')
  return {
    thread: normalizeThread(result.thread),
    progress: normalizeWorkProgress(result.progress)
  }
}

export async function loadZnWorkProgress(
  threadId: string,
  eventId: string
): Promise<ZnWorkProgressResult> {
  const result = record(await desktop().resident.workProgress({
    threadId,
    eventId,
    messageLimit: 120
  }))
  if (!result) throw new Error('Resident returned an invalid work progress result')
  return {
    progress: normalizeWorkProgress(result.progress),
    ...(result.thread ? { thread: normalizeThread(result.thread) } : {})
  }
}

export async function cancelZnWork(
  threadId: string,
  eventId: string
): Promise<ZnWorkProgressResult> {
  const result = record(await desktop().resident.workCancel({
    threadId,
    eventId,
    messageLimit: 120
  }))
  if (!result) throw new Error('Resident returned an invalid Work cancellation result')
  return {
    progress: normalizeWorkProgress(result.progress),
    ...(result.thread ? { thread: normalizeThread(result.thread) } : {})
  }
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

export async function attachZnWorkspace(threadId: string): Promise<ZnThread | null> {
  const bridge = desktop()
  if (!bridge.workspaces) throw new Error('ZN desktop workspace bridge is unavailable')
  const result = record(await bridge.workspaces.attach(threadId))
  if (!result) throw new Error('Desktop returned an invalid workspace result')
  if (result.cancelled === true) return null
  return normalizeThread(result.thread)
}

export async function detachZnWorkspace(threadId: string): Promise<ZnThread> {
  const bridge = desktop()
  if (!bridge.workspaces) throw new Error('ZN desktop workspace bridge is unavailable')
  return normalizeThread(await bridge.workspaces.detach(threadId))
}

export async function checkZnUpdate(): Promise<ZnDesktopUpdateStatus> {
  return desktop().updates.check()
}

export async function applyZnUpdate(): Promise<ZnDesktopUpdateApplyResult> {
  return desktop().updates.apply()
}
