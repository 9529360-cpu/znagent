import type { TFunction } from 'i18next'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  CdsButton,
  ClaudeDesktopHeader,
  CodeBlock,
  PulseRunningDot,
  QuietDotsWave,
  SegmentedControl,
  StatusDot,
  ThinkingAccordion,
  UserMessageBubble
} from './cds'

import {
  applyZnUpdate,
  assignZnTeamSpecialist,
  attachZnWorkspace,
  cancelZnWork,
  checkZnUpdate,
  createZnWorkThread,
  detachZnWorkspace,
  loadZnProviderSettings,
  loadZnResidentSnapshot,
  loadZnTeamTimeline,
  loadZnWorkThread,
  loadZnWorkThreads,
  startZnWork,
  updateZnProviderSettings,
  type ZnProviderSettings,
  type ZnResidentSnapshot,
  type ZnWorkProgress
} from './resident-client'
import {
  parseZnTeamMention,
  type ZnTeamTimeline
} from './team-timeline'
import { describeZnProviderReadiness } from './provider-readiness'
import { useZnWorkReconnection } from './use-work-reconnection'
import {
  getZnDesktopLocaleState,
  setZnDesktopLocalePreference
} from './i18n'
import type { ZnLocalePreference } from '../../localization/zn-localization'
import { ZnMissingRestoreControls } from './restore-controls'
import { ZnAssistantMessage } from './zn-assistant-message'
import { RoutinesPanel } from './routines-panel'
import { ZnSlidesWorkstation } from './slides-workstation'
import { ZnDocumentWorkstation } from './document-workstation'
import {
  addZnThreadMessage,
  loadZnThreadCache,
  newZnThread,
  saveZnThreadCache,
  type ZnRestorePointCurrentStatus,
  type ZnRestoreProposalStatus,
  type ZnThread
} from './state'

type ResidentHealth = 'connecting' | 'live' | 'offline'
type MainView = 'work' | 'settings'
type WindowMode = 'compact' | 'expanded'
type SettingsSection = 'language' | 'models' | 'background' | 'updates'

const PINNED_THREADS_STORAGE_KEY = 'zn.desktop.pinned-threads.v1'

function loadPinnedThreadIds(): string[] {
  try {
    const stored: unknown = JSON.parse(window.localStorage.getItem(PINNED_THREADS_STORAGE_KEY) || '[]')
    return Array.isArray(stored) ? stored.filter((value): value is string => typeof value === 'string') : []
  } catch {
    return []
  }
}

function renderUnknown(value: unknown): string {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function timeLabel(value: number, locale: string): string {
  return new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

function artifactKindLabel(kind: string, t: TFunction): string {
  if (kind === 'diff') return t('artifact.diff')
  if (kind === 'file') return t('artifact.file')
  if (kind === 'terminal') return t('artifact.terminal')
  if (kind === 'presentation') return 'Slides'
  return t('artifact.other')
}

function restorePointStatusLabel(status: ZnRestorePointCurrentStatus, t: TFunction): string {
  if (status === 'unchanged') return t('restore.status.unchanged')
  if (status === 'changed') return t('restore.status.changed')
  if (status === 'missing') return t('restore.status.missing')
  return t('restore.status.unsupported')
}

function restoreProposalStatusLabel(status: ZnRestoreProposalStatus, t: TFunction): string {
  if (status === 'candidate') return t('restore.proposal.candidate')
  if (status === 'conflict_review_required') return t('restore.proposal.conflict')
  if (status === 'missing_target_review_required') return t('restore.proposal.missing')
  return t('restore.proposal.blocked')
}

function delegatedKindLabel(kind: string, t: TFunction): string {
  if (kind === 'research') return t('delegated.kind.research')
  if (kind === 'coding') return t('delegated.kind.coding')
  if (kind === 'review') return t('delegated.kind.review')
  return t('delegated.kind.work')
}

function statusLabel(status: string, t: TFunction): string {
  if (status === 'pending') return t('status.pending')
  if (status === 'running') return t('status.running')
  if (status === 'completed') return t('status.completed')
  if (status === 'failed') return t('status.failed')
  if (status === 'blocked') return t('status.blocked')
  if (status === 'cancelled' || status === 'canceled') return t('status.cancelled')
  if (status === 'superseded') return t('status.superseded')
  if (status === 'waiting_for_user') return t('status.waitingForUser')
  return status.replaceAll('_', ' ')
}

function stageLabel(stage: string, t: TFunction): string {
  if (stage === 'result_ready') return t('delegated.stage.resultReady')
  if (stage === 'queued') return t('stage.queued')
  if (stage === 'waiting') return t('stage.waiting')
  if (stage === 'starting') return t('stage.starting')
  if (stage === 'preparing') return t('stage.preparing')
  if (stage === 'acting') return t('stage.acting')
  if (stage === 'verifying') return t('stage.verifying')
  if (stage === 'verified') return t('stage.verified')
  if (stage === 'working') return t('stage.working')
  if (stage === 'completed') return t('stage.completed')
  if (stage === 'failed') return t('stage.failed')
  if (stage === 'cancelling') return t('work.stopping')
  if (stage === 'superseded') return t('stage.superseded')
  if (stage === 'inspection_complete') return t('stage.inspectionComplete')
  return stage.replaceAll('_', ' ')
}

function delegatedStageLabel(stage: string, t: TFunction): string {
  return stageLabel(stage, t)
}

function delegatedStatusMarker(status: string): string {
  if (status === 'completed') return '✓'
  if (status === 'running') return '●'
  if (status === 'failed') return '×'
  if (status === 'superseded') return '↺'
  return '○'
}

type ExecutionEvidence = {
  executionPath: string
  modelInvocations: number
}

function executionPathLabel(path: string, t: TFunction): string {
  if (path === 'memory') return t('execution.memory')
  if (path === 'capability') return t('execution.capability')
  if (path === 'investigation') return t('execution.investigation')
  if (path === 'body') return t('execution.body')
  if (path === 'model') return t('execution.model')
  if (path === 'control') return t('execution.control')
  if (path === 'budget_blocked') return t('execution.budgetBlocked')
  return path.replaceAll('_', ' ')
}

function executionEvidenceFromDetail(detail?: Record<string, unknown>): ExecutionEvidence | null {
  if (!detail) return null
  const executionPath = String(detail.execution_path ?? detail.executionPath ?? '').trim()
  const modelInvocations = Number(detail.model_invocations ?? detail.modelInvocations)
  if (!executionPath || !Number.isSafeInteger(modelInvocations) || modelInvocations < 0) return null
  return { executionPath, modelInvocations }
}

function credentialLabel(settings: ZnProviderSettings | null, t: TFunction): string {
  if (!settings) return t('credential.unavailable')
  const { credential } = settings
  if (credential.source === 'secure_store') return t('credential.secureStore')
  if (credential.source === 'environment') {
    return t('credential.environment', {
      environment: credential.environmentName || t('credential.environmentFallback')
    })
  }
  if (credential.source === 'config') return t('credential.config')
  if (credential.source === 'secure_store_unavailable') return t('credential.secureStoreUnavailable')
  return t('credential.none')
}

function providerReadinessDetail(
  settings: ZnProviderSettings | null,
  t: TFunction
): string {
  if (!settings) return t('provider.checking.detail')
  if (settings.cognitionAvailable) {
    const active = settings.activeRoutes[0]
    const route = active
      ? [active.provider, active.model].filter(Boolean).join(' · ')
      : [settings.provider, settings.model].filter(Boolean).join(' · ')
    return route || t('provider.ready.detail')
  }
  const error = settings.configurationError?.trim()
  if (error) return error
  if (!settings.model.trim()) return t('provider.notConfigured.detail')
  return t('provider.unavailable.detail')
}

function threadDisplayTitle(title: string, t: TFunction): string {
  return title === 'New work' ? t('sidebar.newWork') : title
}

function focusComposerInput(): void {
  window.requestAnimationFrame(() => {
    const composer = document.querySelector<HTMLTextAreaElement>('.zn-composer textarea')
    composer?.focus()
    composer?.setSelectionRange(composer.value.length, composer.value.length)
  })
}

const ZN_HOME_QUICK_STARTS = [
  { labelKey: 'home.openApp', promptKey: 'home.prompt.openApp' },
  { labelKey: 'home.cleanApp', promptKey: 'home.prompt.cleanApp' },
  { labelKey: 'home.researchTopic', promptKey: 'home.prompt.researchTopic' }
] as const

export function ZnWorkbench() {
  const { t } = useTranslation()
  const [localeState, setLocaleState] = useState(getZnDesktopLocaleState)
  const [localeBusy, setLocaleBusy] = useState(false)
  const [threads, setThreads] = useState<ZnThread[]>(() => {
    const cached = loadZnThreadCache()
    return cached.length > 0 ? cached : [newZnThread()]
  })
  const [activeThreadId, setActiveThreadId] = useState(() => threads[0]?.id || '')
  const [selectedArtifactId, setSelectedArtifactId] = useState('')
  const [artifactOpen, setArtifactOpen] = useState(false)
  const [view, setView] = useState<MainView>('work')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [pinnedThreadIds, setPinnedThreadIds] = useState<string[]>(loadPinnedThreadIds)
  const [pinnedExpanded, setPinnedExpanded] = useState(false)
  const [recentExpanded, setRecentExpanded] = useState(true)
  const [projectsExpanded, setProjectsExpanded] = useState(true)
  const [routinesExpanded, setRoutinesExpanded] = useState(false)
  const [settingsSection, setSettingsSection] = useState<SettingsSection>('language')
  const [query, setQuery] = useState('')
  const [draft, setDraft] = useState('')
  const [submissionBusy, setBusy] = useState(false)
  const [workProgress, setWorkProgress] = useState<ZnWorkProgress | null>(null)
  const [cancelBusy, setCancelBusy] = useState(false)
  const [workspaceBusy, setWorkspaceBusy] = useState(false)
  const [restoreBusy, setRestoreBusy] = useState(false)
  const [contextOpen, setContextOpen] = useState(false)
  const [windowMode, setWindowMode] = useState<WindowMode>(() => window.innerWidth <= 720 ? 'compact' : 'expanded')
  const [residentHealth, setResidentHealth] = useState<ResidentHealth>('connecting')
  const [residentSnapshot, setResidentSnapshot] = useState<ZnResidentSnapshot | null>(null)
  const [residentError, setResidentError] = useState<string | null>(null)
  const [deepLinkNotice, setDeepLinkNotice] = useState<ZnDesktopDeepLink | null>(null)
  const [providerSettings, setProviderSettings] = useState<ZnProviderSettings | null>(null)
  const [providerName, setProviderName] = useState('auto')
  const [providerModel, setProviderModel] = useState('')
  const [providerBaseUrl, setProviderBaseUrl] = useState('')
  const [providerApiKey, setProviderApiKey] = useState('')
  const [providerBusy, setProviderBusy] = useState(false)
  const [providerNotice, setProviderNotice] = useState<string | null>(null)
  const [updateStatus, setUpdateStatus] = useState<ZnDesktopUpdateStatus | null>(null)
  const [updateBusy, setUpdateBusy] = useState(false)
  const [teamTimeline, setTeamTimeline] = useState<ZnTeamTimeline | null>(null)
  const [teamNotice, setTeamNotice] = useState<string | null>(null)

  const activeThread = useMemo(
    () => threads.find(thread => thread.id === activeThreadId) || threads[0] || null,
    [activeThreadId, threads]
  )
  const activeWorkspace = activeThread?.workspace || null
  const pinnedThreads = useMemo(() => threads.filter(thread => pinnedThreadIds.includes(thread.id)), [pinnedThreadIds, threads])
  const activeArtifacts = useMemo(() => activeThread?.artifacts || [], [activeThread])
  const activeWorkstationArtifact = useMemo(
    () => activeArtifacts.find(
      artifact => artifact.kind === 'presentation' || artifact.kind === 'document'
    ) || null,
    [activeArtifacts]
  )
  const selectedArtifact = useMemo(
    () => activeArtifacts.find(artifact => artifact.id === selectedArtifactId) || activeArtifacts[0] || null,
    [activeArtifacts, selectedArtifactId]
  )
  const selectedWorkstationArtifact = useMemo(
    () => selectedArtifact && (selectedArtifact.kind === 'presentation' || selectedArtifact.kind === 'document')
      ? selectedArtifact
      : activeWorkstationArtifact,
    [activeWorkstationArtifact, selectedArtifact]
  )
  const activeRestorePoints = activeThread?.restorePoints
  const recentThreads = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    return [...threads]
      .sort((left, right) => right.updatedAt - left.updatedAt)
      .filter(thread => !pinnedThreadIds.includes(thread.id))
      .filter(thread => !normalized || thread.title.toLowerCase().includes(normalized))
  }, [pinnedThreadIds, query, threads])

  useEffect(() => {
    try {
      window.localStorage.setItem(PINNED_THREADS_STORAGE_KEY, JSON.stringify(pinnedThreadIds))
    } catch {
      // Pinning remains available for this session when local storage is unavailable.
    }
  }, [pinnedThreadIds])

  const togglePinnedThread = useCallback((threadId: string) => {
    setPinnedThreadIds(current => current.includes(threadId)
      ? current.filter(id => id !== threadId)
      : [threadId, ...current])
  }, [])

  const providerReadiness = useMemo(
    () => describeZnProviderReadiness(providerSettings),
    [providerSettings]
  )
  const localizedProviderReadinessDetail = useMemo(
    () => providerReadinessDetail(providerSettings, t),
    [providerSettings, t]
  )

  const changeLocale = useCallback(async (preference: ZnLocalePreference) => {
    if (localeBusy || preference === localeState.preference) return
    setLocaleBusy(true)
    try {
      setLocaleState(await setZnDesktopLocalePreference(preference))
    } finally {
      setLocaleBusy(false)
    }
  }, [localeBusy, localeState.preference])

  useEffect(() => saveZnThreadCache(threads), [threads])

  useEffect(() => {
    setSelectedArtifactId(current =>
      activeArtifacts.some(artifact => artifact.id === current)
        ? current
        : activeArtifacts[0]?.id || ''
    )
  }, [activeArtifacts])

  useEffect(() => {
    if (!selectedWorkstationArtifact) setArtifactOpen(false)
  }, [selectedWorkstationArtifact])

  const replaceThread = useCallback((updated: ZnThread) => {
    setThreads(current =>
      current
        .map(thread => {
          if (thread.id !== updated.id) return thread
          if (updated.restorePoints === undefined && thread.restorePoints !== undefined) {
            return { ...updated, restorePoints: thread.restorePoints }
          }
          return updated
        })
        .sort((left, right) => right.updatedAt - left.updatedAt)
    )
  }, [])

  const workActive = useZnWorkReconnection({
    thread: activeThread,
    submissionBusy,
    progress: workProgress,
    onProgress: setWorkProgress,
    onThread: replaceThread,
    onError: setResidentError,
    onHealth: setResidentHealth,
    t
  })
  const stoppingWork = Boolean(cancelBusy || workProgress?.stage === 'cancelling')

  const refreshResident = useCallback(async () => {
    setResidentHealth(previous => (previous === 'live' ? previous : 'connecting'))
    try {
      const [snapshot, residentThreads] = await Promise.all([
        loadZnResidentSnapshot(),
        loadZnWorkThreads()
      ])
      const authoritative = residentThreads.length > 0 ? residentThreads : [newZnThread()]
      setResidentSnapshot(snapshot)
      setThreads(current => authoritative.map(thread => {
        const previous = current.find(item => item.id === thread.id)
        return previous?.restorePoints !== undefined
          ? { ...thread, restorePoints: previous.restorePoints }
          : thread
      }))
      setActiveThreadId(current =>
        authoritative.some(thread => thread.id === current) ? current : authoritative[0]?.id || ''
      )
      setResidentError(null)
      setResidentHealth('live')
    } catch (error) {
      setResidentError(error instanceof Error ? error.message : String(error))
      setResidentHealth('offline')
    }
  }, [])

  const refreshRestorePoints = useCallback(async (threadId: string) => {
    const normalized = threadId.trim()
    if (!normalized) return
    setRestoreBusy(true)
    try {
      replaceThread(await loadZnWorkThread(normalized))
      setResidentError(null)
      setResidentHealth('live')
    } catch (error) {
      setResidentError(error instanceof Error ? error.message : String(error))
    } finally {
      setRestoreBusy(false)
    }
  }, [replaceThread])

  const refreshTeamTimeline = useCallback(async (threadId: string) => {
    const normalized = threadId.trim()
    if (!normalized) return
    try {
      setTeamTimeline(await loadZnTeamTimeline(normalized))
    } catch {
      // The timeline is a derived view; a failed refresh keeps the last
      // known entries instead of blanking live team history.
    }
  }, [])

  // Team timeline follows the active thread. Switching threads clears the
  // previous thread's timeline so entries never leak across Work.
  useEffect(() => {
    setTeamTimeline(null)
    setTeamNotice(null)
    if (activeThreadId) void refreshTeamTimeline(activeThreadId)
  }, [activeThreadId, refreshTeamTimeline])

  // The resident poll already refreshes Work every 12s; the timeline rides
  // the same rhythm so handoffs appear while the team is running.
  useEffect(() => {
    if (!activeThreadId) return
    const timer = window.setInterval(() => void refreshTeamTimeline(activeThreadId), 12_000)
    return () => window.clearInterval(timer)
  }, [activeThreadId, refreshTeamTimeline])

  const applyProviderSettings = useCallback((settings: ZnProviderSettings) => {
    setProviderSettings(settings)
    setProviderName(settings.provider || 'auto')
    setProviderModel(settings.model)
    setProviderBaseUrl(settings.baseUrl)
    setProviderApiKey('')
  }, [])

  const refreshProviderSettings = useCallback(async () => {
    setProviderBusy(true)
    try {
      applyProviderSettings(await loadZnProviderSettings())
      setProviderNotice(null)
    } catch (error) {
      setProviderNotice(error instanceof Error ? error.message : String(error))
    } finally {
      setProviderBusy(false)
    }
  }, [applyProviderSettings])

  useEffect(() => {
    void refreshResident()
    void refreshProviderSettings()
    const timer = window.setInterval(() => void refreshResident(), 12_000)
    return () => window.clearInterval(timer)
  }, [refreshProviderSettings, refreshResident])

  useEffect(() => {
    if (view === 'settings') void refreshProviderSettings()
  }, [refreshProviderSettings, view])

  useEffect(() => {
    return window.znDesktop?.shell?.onDeepLink(link => {
      setDeepLinkNotice(link)
      setView('work')
      setArtifactOpen(false)
    })
  }, [])

  useEffect(() => {
    const syncWindowMode = () => setWindowMode(window.innerWidth <= 720 ? 'compact' : 'expanded')
    syncWindowMode()
    window.addEventListener('resize', syncWindowMode)
    return () => window.removeEventListener('resize', syncWindowMode)
  }, [])

  useEffect(() => {
    return window.znDesktop?.shell?.onGlobalInvocation(() => {
      setWindowMode('compact')
      setView('work')
      setContextOpen(false)
      setArtifactOpen(false)
      focusComposerInput()
    })
  }, [])

  useEffect(() => {
    return window.znDesktop?.shell?.onWindowModeTransition(transition => {
      if (transition.phase === 'prepare') {
        if (transition.mode === 'compact') {
          setContextOpen(false)
          setArtifactOpen(false)
        }
        window.requestAnimationFrame(() => {
          void window.znDesktop?.shell?.ackWindowModeTransition({
            transitionId: transition.transitionId,
            mode: transition.mode
          })
        })
        return
      }
      setWindowMode(transition.mode)
      if (transition.mode === 'compact') {
        setContextOpen(false)
        setArtifactOpen(false)
      }
    })
  }, [])

  const openNewWork = useCallback(() => {
    const thread = newZnThread()
    setThreads(current => [thread, ...current])
    setActiveThreadId(thread.id)
    setSelectedArtifactId('')
    setArtifactOpen(false)
    setView('work')
    setDraft('')
    void createZnWorkThread(thread)
      .then(saved => replaceThread(saved))
      .catch(error => {
        setResidentError(error instanceof Error ? error.message : String(error))
        setResidentHealth('offline')
      })
  }, [replaceThread])

  const attachWorkspace = useCallback(async () => {
    if (!activeThread || workspaceBusy || workActive) return
    const threadId = activeThread.id
    setWorkspaceBusy(true)
    try {
      const updated = await attachZnWorkspace(threadId)
      if (updated) replaceThread(updated)
      setResidentError(null)
      setResidentHealth('live')
    } catch (error) {
      setResidentError(error instanceof Error ? error.message : String(error))
    } finally {
      setWorkspaceBusy(false)
    }
  }, [activeThread, replaceThread, workActive, workspaceBusy])

  const detachWorkspace = useCallback(async () => {
    if (!activeThread?.workspace || workspaceBusy || workActive) return
    const threadId = activeThread.id
    setWorkspaceBusy(true)
    try {
      replaceThread(await detachZnWorkspace(threadId))
      setResidentError(null)
      setResidentHealth('live')
    } catch (error) {
      setResidentError(error instanceof Error ? error.message : String(error))
    } finally {
      setWorkspaceBusy(false)
    }
  }, [activeThread, replaceThread, workActive, workspaceBusy])

  const cancelCurrentWork = useCallback(async () => {
    if (!activeThread || !workProgress || cancelBusy || workProgress.finalized) return
    if (workProgress.threadId !== activeThread.id || workProgress.stage === 'cancelling') return

    const threadId = activeThread.id
    const eventId = workProgress.eventId
    setCancelBusy(true)
    try {
      const result = await cancelZnWork(threadId, eventId)
      setWorkProgress(result.progress)
      if (result.thread) replaceThread(result.thread)
      setResidentError(null)
      setResidentHealth('live')
    } catch (error) {
      setResidentError(error instanceof Error ? error.message : String(error))
    } finally {
      setCancelBusy(false)
    }
  }, [activeThread, cancelBusy, replaceThread, workProgress])

  const submit = useCallback(
    async (event: FormEvent) => {
      event.preventDefault()
      const task = draft.trim()
      if (!task || submissionBusy || stoppingWork || !activeThread) return

      const threadId = activeThread.id

      // `@specialist instruction` assigns the next team step. It goes
      // through the team_assign RPC, not workStart: workStart refuses a
      // second event while the team event is still running, and an
      // assignment is steering, not a new Work event.
      const mention = parseZnTeamMention(task)
      if (mention && teamTimeline && teamTimeline.members.includes(mention.specialist)) {
        setDraft('')
        setBusy(true)
        setTeamNotice(null)
        try {
          const assigned = await assignZnTeamSpecialist(threadId, mention.specialist, mention.instruction)
          setTeamNotice(t('team.assignDone', { specialist: assigned.specialist }))
          void refreshTeamTimeline(threadId)
        } catch (error) {
          setTeamNotice(t('team.assignFailed', {
            message: error instanceof Error ? error.message : String(error)
          }))
        } finally {
          setBusy(false)
        }
        return
      }

      let residentAccepted = false
      setDraft('')
      setBusy(true)
      setThreads(current =>
        current.map(thread =>
          thread.id === threadId ? addZnThreadMessage(thread, 'user', task) : thread
        )
      )

      try {
        const started = await startZnWork(threadId, task)
        residentAccepted = true
        replaceThread(started.thread)
        setActiveThreadId(started.thread.id)
        setWorkProgress(started.progress.finalized ? null : started.progress)
        setResidentError(null)
        setResidentHealth('live')

        // Submission owns only the RPC acceptance boundary. Once the Resident
        // durably accepts the event (including a same-thread steering event),
        // release the composer immediately. The read-only reconnection observer
        // follows progress from here; it never resubmits Work.
        if (started.progress.finalized) {
          if (started.thread.artifacts.length > 0) {
            setSelectedArtifactId(started.thread.artifacts[0].id)
            setContextOpen(false)
            setArtifactOpen(false)
          }
          void loadZnResidentSnapshot().then(setResidentSnapshot).catch(() => undefined)
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        if (!residentAccepted) {
          setThreads(current =>
            current.map(thread =>
              thread.id === threadId
                ? addZnThreadMessage(thread, 'zn', message, { failed: true })
                : thread
            )
          )
        } else {
          setWorkProgress(null)
        }
        setResidentError(
          residentAccepted
            ? t('error.desktopReconnect', { message })
            : message
        )
        setResidentHealth(residentAccepted ? 'connecting' : 'offline')
      } finally {
        setBusy(false)
      }
    },
    [activeThread, draft, refreshTeamTimeline, replaceThread, stoppingWork, submissionBusy, t, teamTimeline]
  )

  const saveProvider = useCallback(async (event: FormEvent) => {
    event.preventDefault()
    setProviderBusy(true)
    try {
      const settings = await updateZnProviderSettings({
        provider: providerName,
        model: providerModel,
        baseUrl: providerBaseUrl,
        ...(providerApiKey.trim() ? { apiKey: providerApiKey } : {})
      })
      applyProviderSettings(settings)
      const readiness = describeZnProviderReadiness(settings)
      const detail = providerReadinessDetail(settings, t)
      setProviderNotice(t(readiness.ready ? 'provider.notice.ready' : 'provider.notice.notReady', { detail }))
    } catch (error) {
      setProviderNotice(error instanceof Error ? error.message : String(error))
    } finally {
      setProviderBusy(false)
    }
  }, [applyProviderSettings, providerApiKey, providerBaseUrl, providerModel, providerName, t])

  const clearProviderCredential = useCallback(async () => {
    if (!providerSettings?.editable) return
    setProviderBusy(true)
    try {
      const settings = await updateZnProviderSettings({
        provider: providerName,
        model: providerModel,
        baseUrl: providerBaseUrl,
        clearCredential: true
      })
      applyProviderSettings(settings)
      setProviderNotice(t('settings.models.storedCredentialCleared'))
    } catch (error) {
      setProviderNotice(error instanceof Error ? error.message : String(error))
    } finally {
      setProviderBusy(false)
    }
  }, [applyProviderSettings, providerBaseUrl, providerModel, providerName, providerSettings?.editable, t])

  const checkUpdates = useCallback(async () => {
    setUpdateBusy(true)
    try {
      setUpdateStatus(await checkZnUpdate())
    } finally {
      setUpdateBusy(false)
    }
  }, [])

  const applyUpdate = useCallback(async () => {
    setUpdateBusy(true)
    try {
      const result = await applyZnUpdate()
      setUpdateStatus(current =>
        current
          ? {
              ...current,
              message:
                result.message || result.error || (result.ok ? 'Update handoff started.' : 'Update failed.')
            }
          : current
      )
    } finally {
      setUpdateBusy(false)
    }
  }, [])

  const showClearCredential = providerSettings?.credential.source === 'secure_store' || providerSettings?.credential.source === 'config'
  const chooseHomePrompt = (prompt: string) => {
    setDraft(prompt)
    focusComposerInput()
  }

  const requestWindowMode = useCallback((mode: WindowMode) => {
    if (mode === 'compact') {
      setContextOpen(false)
      setArtifactOpen(false)
    }
    void window.znDesktop?.shell?.setWindowMode?.(mode).catch(error => {
      console.error('[ZN] failed to request resident window mode', error)
    })
  }, [])

  useEffect(() => {
    if (artifactOpen && selectedWorkstationArtifact && view === 'work') requestWindowMode('expanded')
  }, [artifactOpen, selectedWorkstationArtifact?.id, activeThreadId, requestWindowMode, view])

  const openSettings = useCallback(() => {
    setSettingsSection('language')
    setArtifactOpen(false)
    setContextOpen(false)
    setView('settings')
    requestWindowMode('expanded')
  }, [requestWindowMode])

  const focusSettingsSection = useCallback((section: SettingsSection) => {
    setSettingsSection(section)
    window.requestAnimationFrame(() => {
      document.querySelector('.zn-settings-content')?.scrollTo({ top: 0, behavior: 'smooth' })
    })
  }, [])

  const openDetails = useCallback(() => {
    setArtifactOpen(false)
    setContextOpen(true)
    requestWindowMode('expanded')
  }, [requestWindowMode])

  const openArtifact = useCallback((artifactId?: string) => {
    if (artifactId) setSelectedArtifactId(artifactId)
    setContextOpen(false)
    setArtifactOpen(true)
    requestWindowMode('expanded')
  }, [requestWindowMode])

  const openTeamEvidence = useCallback((artifactId: string) => {
    const artifact = activeArtifacts.find(item => item.id === artifactId)
    if (!artifact) return
    setSelectedArtifactId(artifactId)
    if (artifact.kind === 'presentation' || artifact.kind === 'document') {
      openArtifact(artifactId)
    } else {
      openDetails()
    }
  }, [activeArtifacts, openArtifact, openDetails])

  const toggleWindowMode = useCallback(() => {
    if (windowMode === 'expanded') {
      if (view === 'settings') setView('work')
      requestWindowMode('compact')
      focusComposerInput()
      return
    }
    requestWindowMode('expanded')
  }, [requestWindowMode, view, windowMode])

  const showActiveWork = workProgress && activeThread && workProgress.threadId === activeThread.id && !workProgress.finalized
  const firstResult = activeArtifacts[0] || null
  return (
    <div className={'zn-app ' + windowMode + (sidebarCollapsed ? ' sidebar-collapsed' : '') + (contextOpen ? ' details-open' : ' context-closed') + (artifactOpen && selectedWorkstationArtifact && view === 'work' ? ' artifact-open' : '') + (view === 'settings' ? ' settings-open' : '')}>
      {!sidebarCollapsed ? (
      <aside className="zn-sidebar" aria-label={t('sidebar.navigation')}>
        <div className="flex items-center gap-2 px-3 pb-2 pt-3">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[var(--cds-clay)] text-sm font-semibold text-white" aria-hidden="true">ZN</span>
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-[var(--cds-text-primary)]">ZN</div>
            <div className="truncate text-xs text-[var(--cds-text-secondary)]">{t('sidebar.alwaysHere')}</div>
          </div>
        </div>

        <div className="px-3 pb-2">
          <CdsButton variant="brand" className="w-full" type="button" onClick={openNewWork}>
            + {t('sidebar.newWork')}
          </CdsButton>
        </div>

        <div className="px-3 pb-2">
          <CdsButton variant="ghost" className="w-full justify-start" type="button" onClick={() => {
            openNewWork()
            setDraft(t('sidebar.imagePrompt'))
            window.requestAnimationFrame(focusComposerInput)
          }}>
            {t('sidebar.images')}
          </CdsButton>
        </div>

        <label className="mx-3 mb-2 flex items-center gap-2 rounded-lg bg-[var(--cds-surface-2)] px-2.5 py-1.5">
          <span aria-hidden="true" className="text-xs text-[var(--cds-text-secondary)]">⌕</span>
          <input
            className="w-full bg-transparent text-sm text-[var(--cds-text-primary)] outline-none placeholder:text-[var(--cds-text-muted)]"
            aria-label={t('sidebar.searchRecent')}
            placeholder={t('sidebar.searchRecent')}
            value={query}
            onChange={event => setQuery(event.target.value)}
          />
        </label>

        <nav className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto px-2 pb-2" aria-label={t('topbar.recentWork')}>
          <button className="flex items-center gap-1 px-2 py-1 text-left text-xs font-medium text-[var(--cds-text-secondary)]" type="button" aria-expanded={pinnedExpanded} onClick={() => setPinnedExpanded(value => !value)}>
            <span aria-hidden="true">{pinnedExpanded ? '▾' : '▸'}</span><span>{t('sidebar.pinned')}</span>
          </button>
          {pinnedExpanded && pinnedThreads.length > 0 ? (
            <div>
              {pinnedThreads.map(thread => (
                <div className="group flex items-center gap-1" key={thread.id}>
                  <button className={'min-w-0 flex-1 truncate rounded-lg px-2 py-1.5 text-left text-sm ' + (thread.id === activeThread?.id && view === 'work' ? 'bg-[var(--cds-fill-ghost-selected)] text-[var(--cds-text-primary)]' : 'text-[var(--cds-text-secondary)] hover:bg-[var(--cds-fill-ghost-hover)]')} type="button" onClick={() => {
                    setActiveThreadId(thread.id)
                    setView('work')
                    setContextOpen(false)
                    setArtifactOpen(false)
                    void refreshRestorePoints(thread.id)
                  }}>
                    <span className="block truncate">{threadDisplayTitle(thread.title, t)}</span>
                    <span className="block text-xs text-[var(--cds-text-muted)]">{timeLabel(thread.updatedAt, localeState.resolvedLocale)}</span>
                  </button>
                  <button className="shrink-0 px-1 text-xs" type="button" aria-label={t('sidebar.unpin')} title={t('sidebar.unpin')} onClick={() => togglePinnedThread(thread.id)}>📌</button>
                </div>
              ))}
            </div>
          ) : null}
          {pinnedExpanded && pinnedThreads.length === 0 ? <div className="px-2 py-1 text-xs text-[var(--cds-text-muted)]">{t('sidebar.noPinned')}</div> : null}
          <button className="mt-1 flex items-center gap-1 px-2 py-1 text-left text-xs font-medium text-[var(--cds-text-secondary)]" type="button" aria-expanded={projectsExpanded} onClick={() => setProjectsExpanded(value => !value)}>
            <span aria-hidden="true">{projectsExpanded ? '▾' : '▸'}</span><span>{t('sidebar.workspaces')}</span>
          </button>
          {projectsExpanded ? (
          <>
          <div className="mx-1 flex items-center gap-2 rounded-lg bg-[var(--cds-surface-2)] px-2 py-2">
            <span aria-hidden="true" className="text-sm">📁</span>
            <div className="min-w-0">
              <div className="truncate text-sm text-[var(--cds-text-primary)]">{activeWorkspace?.name || t('sidebar.localWork')}</div>
              <div className="truncate text-xs text-[var(--cds-text-muted)]" title={activeWorkspace?.path}>
                {activeWorkspace?.path || t('sidebar.noFolder')}
              </div>
            </div>
          </div>
          <div className="flex gap-1 px-1 pt-1">
            <CdsButton size="sm" type="button" disabled={workspaceBusy || workActive || !activeThread} onClick={() => void attachWorkspace()}>
              {workspaceBusy ? t('common.working') : activeWorkspace ? t('sidebar.changeFolder') : t('sidebar.attachFolder')}
            </CdsButton>
            {activeWorkspace ? (
              <CdsButton size="sm" type="button" disabled={workspaceBusy || workActive} onClick={() => void detachWorkspace()}>
                {t('sidebar.detach')}
              </CdsButton>
            ) : null}
          </div>
          </>
          ) : null}
          <button className="mt-1 flex items-center gap-1 px-2 py-1 text-left text-xs font-medium text-[var(--cds-text-secondary)]" type="button" aria-expanded={recentExpanded} onClick={() => setRecentExpanded(value => !value)}>
            <span aria-hidden="true">{recentExpanded ? '▾' : '▸'}</span><span>{t('sidebar.recent')}</span>
          </button>
          {recentExpanded ? <div>
            {recentThreads.map(thread => (
              <div className="group flex items-center gap-1" key={thread.id}>
                <button
                  className={'min-w-0 flex-1 truncate rounded-lg px-2 py-1.5 text-left text-sm ' + (thread.id === activeThread?.id && view === 'work' ? 'bg-[var(--cds-fill-ghost-selected)] text-[var(--cds-text-primary)]' : 'text-[var(--cds-text-secondary)] hover:bg-[var(--cds-fill-ghost-hover)]')}
                  type="button"
                  onClick={() => {
                    setActiveThreadId(thread.id)
                    setView('work')
                    setContextOpen(false)
                    setArtifactOpen(false)
                    void refreshRestorePoints(thread.id)
                  }}
                >
                  <span className="block truncate">{threadDisplayTitle(thread.title, t)}</span>
                  <span className="block text-xs text-[var(--cds-text-muted)]">{timeLabel(thread.updatedAt, localeState.resolvedLocale)}</span>
                </button>
                <button className="shrink-0 px-1 text-xs opacity-0 group-hover:opacity-100" type="button" aria-label={t('sidebar.pin')} title={t('sidebar.pin')} onClick={() => togglePinnedThread(thread.id)}>📌</button>
              </div>
            ))}
          </div> : null}
          <button className="mt-1 flex items-center gap-1 px-2 py-1 text-left text-xs font-medium text-[var(--cds-text-secondary)]" type="button" aria-expanded={routinesExpanded} onClick={() => setRoutinesExpanded(value => !value)}>
            <span aria-hidden="true">{routinesExpanded ? '▾' : '▸'}</span><span>{t('sidebar.scheduled')}</span>
          </button>
          {routinesExpanded ? <RoutinesPanel /> : null}
        </nav>

        <div className="border-t border-[var(--cds-border)] p-2">
          <CdsButton variant="ghost" className="w-full justify-start" type="button" onClick={openSettings}>
            ⚙ {t('settings.title')}
          </CdsButton>
        </div>
      </aside>
      ) : null}

      <section className="zn-main-column">
        <ClaudeDesktopHeader title={view === 'settings' ? t('settings.title') : activeThread ? threadDisplayTitle(activeThread.title, t) : t('sidebar.newWork')}>
          <StatusDot kind={residentHealth === 'live' ? 'ready' : residentHealth === 'connecting' ? 'running' : 'error'} label={residentHealth === 'live' ? t('common.ready') : residentHealth === 'connecting' ? t('common.connecting') : t('common.offline')} />
          <CdsButton size="icon" type="button" aria-label={t('topbar.toggleSidebar')} title={t('topbar.toggleSidebar')} aria-pressed={sidebarCollapsed} onClick={() => setSidebarCollapsed(value => !value)}>
            ☰
          </CdsButton>
          <CdsButton size="icon" type="button" aria-label={t('topbar.openSettings')} title={t('settings.title')} onClick={openSettings}>
            ⚙
          </CdsButton>
          <CdsButton size="icon" type="button" aria-label={windowMode === 'compact' ? t('topbar.expandZn') : t('topbar.compactZn')} title={windowMode === 'compact' ? t('topbar.expand') : t('topbar.compact')} onClick={toggleWindowMode}>
            {windowMode === 'compact' ? '⤢' : '⤡'}
          </CdsButton>
        </ClaudeDesktopHeader>

        {view === 'settings' ? (
          <main className="zn-settings">
            <div className="mx-auto flex max-w-3xl flex-col gap-4">
              <div>
                <div className="text-xs font-medium uppercase tracking-wide text-[var(--cds-text-accent)]">{t('settings.eyebrow')}</div>
                <h1 className="mt-1 text-xl font-semibold text-[var(--cds-text-primary)]">{t(settingsSection === 'language' ? 'settings.language.title' : settingsSection === 'models' ? 'settings.models.title' : settingsSection === 'background' ? 'settings.background.title' : 'settings.updates.title')}</h1>
                <p className="mt-1 text-sm text-[var(--cds-text-secondary)]">{t(settingsSection === 'language' ? 'settings.language.description' : settingsSection === 'models' ? 'settings.models.description' : settingsSection === 'background' ? 'settings.background.description' : 'settings.updates.description')}</p>
              </div>
              <SegmentedControl
                tabs={[
                  { id: 'language', label: t('settings.language.title') },
                  { id: 'models', label: t('settings.models.title') },
                  { id: 'background', label: t('settings.background.title') },
                  { id: 'updates', label: t('settings.updates.title') }
                ]}
                value={settingsSection}
                onChange={value => focusSettingsSection(String(value) as SettingsSection)}
              />
              {settingsSection === 'language' ? (
              <section className="zn-card" id="zn-settings-language">
                <label className="block text-sm font-medium text-[var(--cds-text-primary)]">
                  <span>{t('settings.language.label')}</span>
                  <select
                    className="mt-2 w-full rounded-lg bg-[var(--cds-surface-1)] px-2 py-2 text-sm text-[var(--cds-text-primary)]"
                    aria-label={t('settings.language.label')}
                    value={localeState.preference}
                    disabled={localeBusy}
                    onChange={event => void changeLocale(event.target.value as ZnLocalePreference)}
                  >
                    <option value="system">{t('settings.language.system')}</option>
                    <option value="zh-CN">{t('settings.language.zhCN')}</option>
                    <option value="en-US">{t('settings.language.enUS')}</option>
                  </select>
                </label>
                <p className="mt-2 text-xs text-[var(--cds-text-secondary)]">
                  {t('settings.language.systemDetected', {
                    languages: localeState.preferredSystemLanguages.join(', ') || localeState.resolvedLocale
                  })}
                </p>
              </section>
              ) : null}

              {settingsSection === 'background' ? (
              <section className="zn-card" id="zn-settings-background">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusDot kind={residentHealth === 'live' ? 'ready' : residentHealth === 'connecting' ? 'running' : 'error'} label={residentHealth === 'live' ? t('common.ready') : residentHealth === 'connecting' ? t('common.connecting') : t('common.offline')} />
                  <CdsButton type="button" onClick={() => void refreshResident()}>{t('settings.background.refresh')}</CdsButton>
                </div>
                {residentError ? <div className="mt-2 text-sm text-[var(--cds-fill-danger)]">{residentError}</div> : null}
              </section>
              ) : null}

              {settingsSection === 'models' ? (
              <section className="zn-card" id="zn-settings-models">
                {providerSettings && !providerSettings.editable ? (
                  <>
                    <div className="text-sm text-[var(--cds-text-primary)]">
                      {t('settings.models.advancedActive', {
                        mode: providerSettings.mode,
                        routes: providerSettings.routeCount
                          ? t('settings.models.routes', { count: providerSettings.routeCount })
                          : ''
                      })}
                    </div>
                    <p className="mt-1 text-xs text-[var(--cds-text-secondary)]">{t('settings.models.advancedWarning')}</p>
                  </>
                ) : (
                  <form onSubmit={saveProvider}>
                    <div className="flex flex-wrap items-center gap-2" role="status" aria-live="polite">
                      <StatusDot kind={providerReadiness.ready ? 'ready' : 'error'} label={t(providerReadiness.ready ? 'settings.models.connectionReady' : 'settings.models.connectionNeedsSetup')} />
                      <span className="text-xs text-[var(--cds-text-secondary)]">{localizedProviderReadinessDetail}</span>
                    </div>
                    <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                      <label className="block text-sm">
                        <span className="text-[var(--cds-text-primary)]">{t('settings.models.provider')}</span>
                        <input className="mt-1 w-full rounded-lg bg-[var(--cds-surface-1)] px-2 py-2 text-sm text-[var(--cds-text-primary)]" aria-label={t('settings.models.providerAria')} value={providerName} disabled={providerBusy} onChange={event => setProviderName(event.target.value)} placeholder="openai, anthropic, gemini, ollama..." />
                        <small className="text-xs text-[var(--cds-text-secondary)]">{t('settings.models.providerHelp')}</small>
                      </label>
                      <label className="block text-sm">
                        <span className="text-[var(--cds-text-primary)]">{t('settings.models.model')}</span>
                        <input className="mt-1 w-full rounded-lg bg-[var(--cds-surface-1)] px-2 py-2 text-sm text-[var(--cds-text-primary)]" aria-label={t('settings.models.modelAria')} value={providerModel} disabled={providerBusy} onChange={event => setProviderModel(event.target.value)} placeholder={t('settings.models.modelPlaceholder')} />
                        <small className="text-xs text-[var(--cds-text-secondary)]">{t('settings.models.modelHelp')}</small>
                      </label>
                      <label className="block text-sm sm:col-span-2">
                        <span className="text-[var(--cds-text-primary)]">{t('settings.models.baseUrl')}</span>
                        <input className="mt-1 w-full rounded-lg bg-[var(--cds-surface-1)] px-2 py-2 text-sm text-[var(--cds-text-primary)]" aria-label={t('settings.models.baseUrlAria')} type="url" autoComplete="url" value={providerBaseUrl} disabled={providerBusy} onChange={event => setProviderBaseUrl(event.target.value)} placeholder={t('settings.models.baseUrlPlaceholder')} />
                        <small className="text-xs text-[var(--cds-text-secondary)]">{t('settings.models.baseUrlHelp')}</small>
                      </label>
                      <label className="block text-sm sm:col-span-2">
                        <span className="text-[var(--cds-text-primary)]">{t('settings.models.credential')}</span>
                        <input className="mt-1 w-full rounded-lg bg-[var(--cds-surface-1)] px-2 py-2 text-sm text-[var(--cds-text-primary)]" aria-label={t('settings.models.credentialAria')} type="password" autoComplete="new-password" value={providerApiKey} disabled={providerBusy} onChange={event => setProviderApiKey(event.target.value)} placeholder={providerSettings?.credential.configured ? t('settings.models.keepCredential') : t('settings.models.optionalCredential')} />
                        <small className="text-xs text-[var(--cds-text-secondary)]">{t(providerSettings?.credential.configured ? 'settings.models.credentialSaved' : 'settings.models.credentialHelp')}</small>
                      </label>
                    </div>
                    <details className="mt-3 text-sm">
                      <summary className="cursor-pointer text-[var(--cds-text-secondary)]">{t('settings.models.securityDetails')}</summary>
                      <p className="mt-1 text-xs text-[var(--cds-text-secondary)]">{credentialLabel(providerSettings, t)}</p>
                      {providerSettings ? <p className="text-xs text-[var(--cds-text-secondary)]">{t('settings.models.secureStore', {
                        status: providerSettings.credential.secureStore.available ? t('common.available') : t('common.unavailable'),
                        backend: providerSettings.credential.secureStore.backend
                      })}</p> : null}
                    </details>
                    {providerSettings?.configurationError ? <div className="mt-2 text-sm text-[var(--cds-fill-danger)]" role="alert">{providerSettings.configurationError}</div> : null}
                    {providerNotice ? <div className="mt-2 text-sm text-[var(--cds-text-primary)]" role="status" aria-live="polite">{providerNotice}</div> : null}
                    <div className="mt-3 flex flex-wrap gap-2">
                      <CdsButton variant="brand" type="submit" disabled={providerBusy || !providerName.trim() || !providerModel.trim()}>{providerBusy ? t('common.applying') : t('settings.models.save')}</CdsButton>
                      {showClearCredential ? <CdsButton type="button" disabled={providerBusy} onClick={() => void clearProviderCredential()}>{t('settings.models.clearCredential')}</CdsButton> : null}
                      <CdsButton type="button" disabled={providerBusy} onClick={() => void refreshProviderSettings()}>{t('common.refresh')}</CdsButton>
                    </div>
                  </form>
                )}
              </section>
              ) : null}

              {settingsSection === 'updates' ? (
              <section className="zn-card" id="zn-settings-updates">
                <div className="flex flex-wrap gap-2">
                  <CdsButton type="button" disabled={updateBusy} onClick={() => void checkUpdates()}>{updateBusy ? t('common.checking') : t('settings.updates.check')}</CdsButton>
                  {updateStatus?.updateAvailable ? <CdsButton variant="brand" type="button" disabled={updateBusy} onClick={() => void applyUpdate()}>{t('settings.updates.apply', { version: updateStatus.availableVersion || t('settings.updates.updateFallback') })}</CdsButton> : null}
                </div>
                {updateStatus ? (
                  <div className="mt-2 text-sm text-[var(--cds-text-secondary)]">
                    {updateStatus.updateAvailable
                      ? t('settings.updates.apply', { version: updateStatus.availableVersion || t('settings.updates.updateFallback') })
                      : updateStatus.message || t('common.ready')}
                    {updateStatus.message ? <div className="text-xs">{updateStatus.message}</div> : null}
                  </div>
                ) : null}
              </section>
              ) : null}
              <div>
                <CdsButton variant="ghost" type="button" onClick={() => setView('work')}>
                  ← {t('workstation.returnToConversation')}
                </CdsButton>
              </div>
            </div>
          </main>
        ) : (
          <>
            <main className="zn-thread-surface">
              {residentHealth === 'offline' ? (
                <div className="mx-auto mb-3 flex max-w-3xl flex-wrap items-center gap-2 rounded-xl border border-[var(--cds-border)] bg-[var(--cds-surface-2)] px-4 py-3" role="alert" aria-live="polite">
                  <StatusDot kind="error" label={t('error.residentUnavailableTitle')} />
                  <span className="flex-1 text-sm text-[var(--cds-text-secondary)]">{t('error.residentUnavailableHint')}</span>
                  <CdsButton size="sm" type="button" onClick={() => void refreshResident()}>{t('error.reconnect')}</CdsButton>
                </div>
              ) : null}
              {deepLinkNotice ? (
                <div className="mx-auto mb-3 flex max-w-3xl flex-wrap items-center gap-2 rounded-xl border border-[var(--cds-border)] bg-[var(--cds-surface-2)] px-4 py-3">
                  <strong className="text-sm text-[var(--cds-text-primary)]">{t('deepLink.received')}</strong>
                  <span className="flex-1 text-sm text-[var(--cds-text-secondary)]">{t('deepLink.safe')}</span>
                  <CdsButton size="sm" type="button" onClick={() => setDeepLinkNotice(null)}>{t('deepLink.dismiss')}</CdsButton>
                </div>
              ) : null}

              {activeThread && activeThread.messages.length === 0 && !showActiveWork ? (
                <section className="mx-auto flex max-w-3xl flex-col gap-5 px-4">
                  <div className="flex flex-col gap-2">
                    <span className="text-xs font-medium uppercase tracking-wide text-[var(--cds-text-accent)]">{t('home.eyebrow')}</span>
                    <h1 className="text-2xl font-semibold text-[var(--cds-text-primary)]">{t('home.title')}</h1>
                    <p className="text-sm text-[var(--cds-text-secondary)]">{t('home.description')}</p>
                  </div>

                  <div className="flex flex-wrap gap-2" aria-label={t('home.quickStartsAria')}>
                    {ZN_HOME_QUICK_STARTS.map(action => (
                      <CdsButton key={action.labelKey} type="button" onClick={() => chooseHomePrompt(t(action.promptKey))}>
                        {t(action.labelKey)}
                      </CdsButton>
                    ))}
                    {activeWorkspace ? (
                      <CdsButton type="button" onClick={() => chooseHomePrompt(t('home.prompt.reviewWorkspace'))}>
                        {t('home.reviewWorkspace')}
                      </CdsButton>
                    ) : (
                      <CdsButton type="button" disabled={workspaceBusy || workActive || !activeThread} onClick={() => void attachWorkspace()}>
                        {workspaceBusy ? t('home.attaching') : t('sidebar.attachFolder')}
                      </CdsButton>
                    )}
                  </div>

                  <div className="flex flex-wrap gap-4 text-xs text-[var(--cds-text-secondary)]" aria-label={t('home.readinessAria')}>
                    <StatusDot kind={residentHealth === 'live' ? 'ready' : residentHealth === 'connecting' ? 'running' : 'error'} label={residentHealth === 'live' ? t('home.residentReady') : residentHealth === 'connecting' ? t('home.residentConnecting') : t('home.residentOffline')} />
                    <span>{activeWorkspace ? t('home.workspace', { name: activeWorkspace.name }) : t('topbar.thisComputer')}</span>
                    <span title={localizedProviderReadinessDetail}>{providerReadiness.ready ? t('home.cognitionAvailable') : t('home.cognitionSetupNeeded')}</span>
                  </div>
                </section>
              ) : null}

              {activeThread && activeThread.messages.length > 0 ? (
                <div className="mx-auto flex max-w-3xl flex-col gap-4 px-4">
                  {activeThread.messages.map(message => {
                    const executionEvidence = message.role === 'activity'
                      ? executionEvidenceFromDetail(message.detail)
                      : null
                    if (message.role === 'user') {
                      return (
                        <UserMessageBubble
                          key={message.id}
                          text={message.text}
                          time={timeLabel(message.at, localeState.resolvedLocale)}
                          state={message.detail?.failed ? 'failed' : 'done'}
                        />
                      )
                    }
                    if (message.role === 'zn') {
                      const firstArtifact = activeArtifacts[0]
                      return (
                        <ZnAssistantMessage
                          key={message.id}
                          text={message.text}
                          time={timeLabel(message.at, localeState.resolvedLocale)}
                          artifact={firstArtifact ? { title: firstArtifact.name, kind: firstArtifact.kind } : null}
                          onOpenArtifact={() => {
                            if (firstArtifact && (firstArtifact.kind === 'presentation' || firstArtifact.kind === 'document')) openArtifact(firstArtifact.id)
                            else openDetails()
                          }}
                        />
                      )
                    }
                    return (
                      <article className="rounded-xl border border-[var(--cds-border)] bg-[var(--cds-surface-2)] px-4 py-3" key={message.id}>
                        <div className="text-xs font-medium text-[var(--cds-text-secondary)]">{t('message.activity')}</div>
                        <div className="mt-1 whitespace-pre-wrap text-sm text-[var(--cds-text-primary)]">{message.text}</div>
                        {executionEvidence ? (
                          <div className="mt-2 flex flex-wrap gap-3 text-xs text-[var(--cds-text-secondary)]" aria-label={t('message.executionEvidence')}>
                            <span>{executionPathLabel(executionEvidence.executionPath, t)}</span>
                            <span>{t('message.modelCalls', { count: executionEvidence.modelInvocations })}</span>
                          </div>
                        ) : null}
                        {message.detail && Object.keys(message.detail).length > 0 ? (
                          executionEvidence ? (
                            <details className="mt-2">
                              <summary className="cursor-pointer text-xs text-[var(--cds-text-secondary)]">{t('message.technical')}</summary>
                              <pre className="mt-1 overflow-x-auto whitespace-pre-wrap text-xs text-[var(--cds-text-secondary)]">{renderUnknown(message.detail)}</pre>
                            </details>
                          ) : <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-[var(--cds-text-secondary)]">{renderUnknown(message.detail)}</pre>
                        ) : null}
                      </article>
                    )
                  })}
                  {showActiveWork && workProgress?.assistantResponse ? (
                    <div aria-live="polite">
                      <ZnAssistantMessage
                        text={workProgress.assistantResponse}
                      />
                      <div className="mt-1 pl-1"><QuietDotsWave /></div>
                    </div>
                  ) : null}
                </div>
              ) : null}

              {teamTimeline && teamTimeline.entries.length > 0 ? (
                <section className="mx-auto mt-4 flex max-w-3xl flex-col gap-3 px-4" aria-label={t('team.timelineAria')}>
                  <div className="flex flex-wrap items-baseline gap-2">
                    <strong className="text-sm text-[var(--cds-text-primary)]">{t('team.timelineTitle')}</strong>
                    <span className="text-xs text-[var(--cds-text-secondary)]">
                      {t('team.timelineReadOnly')} · {t('team.timelineCount', { count: teamTimeline.entries.length })}
                    </span>
                  </div>
                  {teamTimeline.entries.map(entry => (
                    <article className="rounded-xl border border-[var(--cds-border)] bg-[var(--cds-surface-2)] px-4 py-3" key={entry.id}>
                      <div className="text-xs font-medium text-[var(--cds-text-secondary)]">
                        {entry.author === 'user'
                          ? t('message.you')
                          : entry.author === 'coordinator'
                            ? t('team.coordinator')
                            : entry.author}
                      </div>
                      {entry.kind === 'handoff' ? (
                        <div className="mt-1 flex flex-wrap items-baseline gap-2 text-sm">
                          <span className="text-[var(--cds-text-primary)]">{entry.fromAuthor} → {entry.toAuthor}</span>
                          {entry.itemTitle ? <strong className="text-[var(--cds-text-primary)]">{entry.itemTitle}</strong> : null}
                          {entry.objective ? <span className="text-[var(--cds-text-secondary)]">{entry.objective}</span> : null}
                        </div>
                      ) : null}
                      {entry.kind === 'assignment' ? (
                        <div className="mt-1 flex flex-col gap-1 text-sm">
                          <span className="text-[var(--cds-text-primary)]">{t('team.assignTo', { specialist: entry.toAuthor })}</span>
                          {entry.instruction ? <span className="text-[var(--cds-text-primary)]">{entry.instruction}</span> : null}
                          {entry.itemTitle ? <span className="text-[var(--cds-text-secondary)]">{t('team.nextItem', { item: entry.itemTitle })}</span> : null}
                        </div>
                      ) : null}
                      <div className="mt-1 whitespace-pre-wrap text-sm text-[var(--cds-text-primary)]">{entry.text}</div>
                      {entry.evidence.length > 0 ? (
                        <div className="mt-2 flex flex-wrap gap-2" aria-label={t('team.evidence')}>
                          {entry.evidence.map((item, index) => item.artifactId ? (
                            <CdsButton
                              key={entry.id + '-evidence-' + index}
                              size="sm"
                              type="button"
                              onClick={() => openTeamEvidence(item.artifactId as string)}
                            >
                              {t('team.evidenceLink', { label: item.label })}
                            </CdsButton>
                          ) : (
                            <span key={entry.id + '-evidence-' + index} className="text-xs text-[var(--cds-text-secondary)]">{item.label} · {item.ref}</span>
                          ))}
                        </div>
                      ) : null}
                      {entry.at ? (
                        <div className="mt-1 text-xs text-[var(--cds-text-muted)]">{timeLabel(entry.at, localeState.resolvedLocale)}</div>
                      ) : null}
                    </article>
                  ))}
                </section>
              ) : null}

              {showActiveWork && workProgress ? (
                <section className="mx-auto mt-4 flex max-w-3xl flex-col gap-3 rounded-2xl border border-[var(--cds-border)] bg-[var(--cds-surface-2)] px-4 py-3" aria-live="polite">
                  <div className="flex flex-wrap items-start gap-3">
                    <PulseRunningDot />
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-medium uppercase tracking-wide text-[var(--cds-text-accent)]">{t('work.residentProgress', { status: statusLabel(workProgress.status, t) })}</div>
                      <h2 className="mt-0.5 truncate text-base font-semibold text-[var(--cds-text-primary)]">{activeThread ? threadDisplayTitle(activeThread.title, t) : t('work.workingOnIt')}</h2>
                      <p className="mt-0.5 text-sm text-[var(--cds-text-secondary)]">{stageLabel(workProgress.stage, t)} · {workProgress.nextAction || t('work.continuing')}</p>
                    </div>
                    <CdsButton
                      className="zn-stop-button"
                      variant="danger"
                      type="button"
                      disabled={stoppingWork}
                      onClick={() => void cancelCurrentWork()}
                    >
                      {stoppingWork ? t('work.stopping') : t('work.stop')}
                    </CdsButton>
                  </div>

                  <div className="flex flex-wrap items-center gap-4 text-xs text-[var(--cds-text-secondary)]" aria-label={t('work.statusAria')}>
                    <span>✓ {t('work.accepted')}</span>
                    <span className="flex items-center gap-1"><QuietDotsWave />{stageLabel(workProgress.stage, t)}</span>
                    <span>○ {t('work.verify')}</span>
                  </div>

                  {workProgress.delegation ? (
                    <div className="flex flex-col gap-1 border-t border-[var(--cds-border)] pt-2" aria-label={t('work.delegatedProgressAria')}>
                      <div className="text-sm text-[var(--cds-text-primary)]"><strong>{t('work.delegated')}</strong> · {statusLabel(workProgress.delegation.status, t)}</div>
                      {workProgress.delegation.phases.map((phase, index) => (
                        <div key={phase.kind + '-' + phase.status + '-' + (phase.updatedAt || 0) + '-' + index} className="text-sm text-[var(--cds-text-secondary)]">
                          {delegatedStatusMarker(phase.status)} {delegatedKindLabel(phase.kind, t)} · {delegatedStageLabel(phase.stage, t)}
                        </div>
                      ))}
                    </div>
                  ) : null}

                  {workProgress.recovery?.replayBlocked ? (
                    <div className="rounded-lg bg-[var(--cds-fill-brand-subtle)] px-3 py-2">
                      <strong className="block text-sm text-[var(--cds-text-primary)]">{t('work.outsideUncertain')}</strong>
                      <span className="block text-xs text-[var(--cds-text-secondary)]">{t('work.noReplay')}</span>
                      {workProgress.recovery.reason ? <span className="block text-xs text-[var(--cds-text-secondary)]">{workProgress.recovery.reason}</span> : null}
                    </div>
                  ) : null}

                  <details className="border-t border-[var(--cds-border)] pt-2">
                    <summary className="cursor-pointer text-sm text-[var(--cds-text-secondary)]">{t('work.whatDoing')}</summary>
                    {workProgress.thought ? (
                      <div className="mt-2">
                        <ThinkingAccordion
                          thoughtText={[workProgress.thought.action, workProgress.thought.focus, workProgress.thought.reason].filter(Boolean).join(' — ')}
                          isThinkingLive={true}
                        />
                      </div>
                    ) : null}
                    {workProgress.investigation ? (
                      <div className="mt-2 text-xs text-[var(--cds-text-secondary)]">
                        {t('work.investigationRound', { round: workProgress.investigation.rounds, status: statusLabel(workProgress.investigation.status, t) })}
                        {workProgress.investigation.nextProbe ? t('work.next', { next: workProgress.investigation.nextProbe }) : ''}
                      </div>
                    ) : null}
                    {workProgress.bodyActions.length > 0 ? (
                      <div className="mt-2 flex flex-col gap-1">
                        {workProgress.bodyActions.map((action, index) => (
                          <div key={action.at + '-' + action.kind + '-' + index} className="text-xs text-[var(--cds-text-secondary)]">
                            {action.kind} · {action.success ? t('work.ok') : t('work.failed')}{action.summary ? ' · ' + action.summary : ''}
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </details>

                  <div className="flex flex-wrap items-center gap-3">
                    <CdsButton size="sm" type="button" onClick={openDetails}>{t('work.viewDetails')}</CdsButton>
                    <span className="text-xs text-[var(--cds-text-muted)]">{t('work.updated', { time: timeLabel(workProgress.updatedAt, localeState.resolvedLocale) })}</span>
                  </div>
                </section>
              ) : null}

              {!showActiveWork && firstResult ? (
                <section className="mx-auto mt-4 flex max-w-3xl flex-wrap items-center gap-3 rounded-2xl border border-[var(--cds-border)] bg-[var(--cds-surface-2)] px-4 py-3">
                  <StatusDot kind="ready" />
                  <div className="min-w-0 flex-1">
                    <span className="block text-xs font-medium uppercase tracking-wide text-[var(--cds-text-accent)]">{t('result.title')}</span>
                    <strong className="block truncate text-sm text-[var(--cds-text-primary)]">{firstResult.name}</strong>
                    <span className="block text-xs text-[var(--cds-text-secondary)]">{t('result.ready', { count: activeArtifacts.length })}</span>
                  </div>
                  <CdsButton type="button" onClick={() => activeWorkstationArtifact ? openArtifact(activeWorkstationArtifact.id) : openDetails()}>{t('result.view')}</CdsButton>
                </section>
              ) : null}
            </main>

            {teamNotice ? (
              <div className="mx-auto flex w-full max-w-3xl items-center gap-2 px-4 pb-2" role="status" aria-live="polite">
                <span className="flex-1 text-sm text-[var(--cds-text-secondary)]">{teamNotice}</span>
                <CdsButton size="sm" type="button" aria-label={t('deepLink.dismiss')} onClick={() => setTeamNotice(null)}>×</CdsButton>
              </div>
            ) : null}

            <form className="zn-composer-wrap px-4 pb-3 pt-1" onSubmit={submit}>
              <div className="zn-composer mx-auto max-w-3xl px-3 pb-2 pt-3">
                <textarea
                  aria-label={t('composer.messageAria')}
                  placeholder={t('composer.placeholder')}
                  rows={2}
                  value={draft}
                  onChange={event => setDraft(event.target.value)}
                  onKeyDown={event => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault()
                      event.currentTarget.form?.requestSubmit()
                    }
                  }}
                />
                <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <CdsButton
                      size="icon"
                      type="button"
                      aria-label={activeWorkspace ? t('composer.changeAttachedFolder') : t('composer.attachFolder')}
                      title={activeWorkspace ? t('composer.changeFolder') : t('composer.attachFolder')}
                      disabled={workspaceBusy || workActive || !activeThread}
                      onClick={() => void attachWorkspace()}
                    >
                      +
                    </CdsButton>
                    <span className="flex items-center gap-1 text-xs text-[var(--cds-text-secondary)]" title={activeWorkspace?.path}>
                      📁 {activeWorkspace?.name || t('topbar.thisComputer')}
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full bg-[var(--cds-surface-1)] px-2 py-1 text-xs text-[var(--cds-text-secondary)]" title={localizedProviderReadinessDetail}>
                      {providerSettings?.model || 'ZN'}
                    </span>
                    <CdsButton
                      className="zn-send"
                      variant="brand"
                      type="submit"
                      aria-label={t('composer.sendAria')}
                      disabled={submissionBusy || stoppingWork || !draft.trim()}
                    >
                      {submissionBusy ? '…' : '↑'}
                    </CdsButton>
                  </div>
                </div>
              </div>
              <div className="mx-auto mt-1 max-w-3xl text-center text-xs text-[var(--cds-text-muted)]">
                {teamTimeline && teamTimeline.members.length > 0 ? t('team.assignHint') : ''}
                {workActive ? t('composer.background') : ''}{t('composer.shortcut')}
              </div>
            </form>
          </>
        )}
      </section>

      {artifactOpen && selectedWorkstationArtifact && view === 'work' ? (
        <aside className="zn-artifact-pane" aria-label={t('artifact.preview')}>
          <div className="flex items-start justify-between gap-2 border-b border-[var(--cds-border)] px-4 py-3">
            <div className="min-w-0">
              <span className="block text-xs text-[var(--cds-text-secondary)]">{artifactKindLabel(selectedWorkstationArtifact.kind, t)}</span>
              <strong className="block truncate text-sm text-[var(--cds-text-primary)]">{selectedWorkstationArtifact.name}</strong>
            </div>
            <CdsButton size="icon" type="button" aria-label={t('artifact.closePreview')} onClick={() => setArtifactOpen(false)}>
              ×
            </CdsButton>
          </div>
          <div className="p-3">
            {selectedWorkstationArtifact.kind === 'document' ? (
              <ZnDocumentWorkstation artifact={selectedWorkstationArtifact} />
            ) : (
              <ZnSlidesWorkstation artifact={selectedWorkstationArtifact} artifacts={activeArtifacts} />
            )}
          </div>
        </aside>
      ) : null}

      {contextOpen ? <button className="fixed inset-0 bg-black/30" type="button" aria-label={t('details.closeWorkAria')} onClick={() => setContextOpen(false)} /> : null}

      {contextOpen ? (
        <aside className="zn-context-panel" aria-label={t('details.panelAria')}>
          <div className="flex items-start justify-between gap-2 border-b border-[var(--cds-border)] px-4 py-3">
            <div className="min-w-0">
              <div className="text-xs text-[var(--cds-text-secondary)]">{t('details.title')}</div>
              <strong className="block truncate text-sm text-[var(--cds-text-primary)]">{selectedArtifact ? artifactKindLabel(selectedArtifact.kind, t) : t('details.currentWork')}</strong>
            </div>
            <CdsButton size="icon" type="button" aria-label={t('details.closePanelAria')} onClick={() => setContextOpen(false)}>
              ×
            </CdsButton>
          </div>

          <section className="border-b border-[var(--cds-border)] px-4 py-3">
            <div className="text-xs font-medium text-[var(--cds-text-secondary)]">{t('details.workspace')}</div>
            {activeWorkspace ? (
              <>
                <div className="mt-1 flex items-center gap-1 text-sm text-[var(--cds-text-primary)]">📁 {activeWorkspace.name}</div>
                <div className="mt-0.5 break-all text-xs text-[var(--cds-text-muted)]" title={activeWorkspace.path}>{activeWorkspace.path}</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  <CdsButton size="sm" type="button" disabled={workspaceBusy || workActive} onClick={() => void attachWorkspace()}>{t('details.change')}</CdsButton>
                  <CdsButton size="sm" type="button" disabled={workspaceBusy || workActive} onClick={() => void detachWorkspace()}>{t('details.detach')}</CdsButton>
                </div>
              </>
            ) : (
              <>
                <p className="mt-1 text-xs text-[var(--cds-text-secondary)]">{t('details.noFolder')}</p>
                <div className="mt-2">
                  <CdsButton size="sm" type="button" disabled={workspaceBusy || workActive || !activeThread} onClick={() => void attachWorkspace()}>{t('details.attachFolder')}</CdsButton>
                </div>
              </>
            )}
          </section>

          {activeArtifacts.length > 0 ? (
            <section className="border-b border-[var(--cds-border)] px-4 py-3">
              <div className="text-xs font-medium text-[var(--cds-text-secondary)]">{t('details.results')}</div>
              <div className="mt-2 flex flex-col gap-1" aria-label={t('details.artifactsAria')}>
                {activeArtifacts.map(artifact => (
                  <button
                    className={'flex items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm ' + (artifact.id === selectedArtifact?.id ? 'bg-[var(--cds-fill-ghost-selected)] text-[var(--cds-text-primary)]' : 'text-[var(--cds-text-secondary)] hover:bg-[var(--cds-fill-ghost-hover)]')}
                    key={artifact.id}
                    type="button"
                    onClick={() => {
                      setSelectedArtifactId(artifact.id)
                      if (artifact.kind === 'presentation' || artifact.kind === 'document') openArtifact(artifact.id)
                    }}
                  >
                    <span aria-hidden="true" className="text-xs">📄</span>
                    <span className="min-w-0">
                      <span className="block text-xs text-[var(--cds-text-muted)]">{artifactKindLabel(artifact.kind, t)}</span>
                      <span className="block truncate">{artifact.name}</span>
                    </span>
                  </button>
                ))}
              </div>
              {selectedArtifact ? (
                <div className="zn-artifact-preview mt-3">
                  <div className="flex flex-col gap-0.5">
                    <strong className="truncate text-sm text-[var(--cds-text-primary)]">{selectedArtifact.name}</strong>
                    {selectedArtifact.path ? <span className="truncate text-xs text-[var(--cds-text-muted)]" title={selectedArtifact.path}>{selectedArtifact.path}</span> : null}
                  </div>
                  {selectedArtifact.kind === 'presentation' ? (
                    <div className="mt-2 text-sm text-[var(--cds-text-secondary)]">{selectedArtifact.name}</div>
                  ) : (
                    <div className="mt-2">
                      <CodeBlock code={selectedArtifact.content || t('details.noPreview')} language={selectedArtifact.kind} filename={selectedArtifact.name} />
                    </div>
                  )}
                  {selectedArtifact.metadata?.truncated ? <div className="mt-1 text-xs text-[var(--cds-text-secondary)]">{t('details.previewTruncated')}</div> : null}
                </div>
              ) : null}
            </section>
          ) : (
            <section className="border-b border-[var(--cds-border)] px-4 py-3">
              <div className="text-xs font-medium text-[var(--cds-text-secondary)]">{t('details.results')}</div>
              <p className="mt-1 text-xs text-[var(--cds-text-secondary)]">{t('details.noResults')}</p>
            </section>
          )}

          <section className="border-b border-[var(--cds-border)] px-4 py-3">
            <div className="text-xs font-medium text-[var(--cds-text-secondary)]">{t('details.residentStatus')}</div>
            <div className="mt-1">
              <StatusDot kind={residentHealth === 'live' ? 'ready' : residentHealth === 'connecting' ? 'running' : 'error'} label={residentHealth === 'live' ? t('common.ready') : residentHealth === 'connecting' ? t('common.connecting') : t('common.offline')} />
            </div>
            {residentError ? <div className="mt-1 text-sm text-[var(--cds-fill-danger)]">{residentError}</div> : null}
          </section>

          <section className="px-4 py-3">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-medium text-[var(--cds-text-secondary)]">{t('details.restorePoints')}</div>
              <CdsButton size="sm" type="button" disabled={restoreBusy || !activeThread} onClick={() => activeThread && void refreshRestorePoints(activeThread.id)}>
                {restoreBusy ? t('common.checking') : t('common.refresh')}
              </CdsButton>
            </div>
            {activeRestorePoints === undefined ? (
              <p className="mt-1 text-xs text-[var(--cds-text-secondary)]">{t('details.restorePrompt')}</p>
            ) : activeRestorePoints.length === 0 ? (
              <p className="mt-1 text-xs text-[var(--cds-text-secondary)]">{t('details.noRestorePoints')}</p>
            ) : (
              <div className="mt-2 flex flex-col gap-2" aria-label={t('details.restoreListAria')}>
                {activeRestorePoints.map(point => (
                  <div className="rounded-xl border border-[var(--cds-border)] bg-[var(--cds-surface-2)] px-3 py-2" key={point.id}>
                    <div className="flex flex-wrap justify-between gap-2 text-xs text-[var(--cds-text-secondary)]">
                      <span>{restorePointStatusLabel(point.currentStatus, t)}</span>
                      <span>{timeLabel(point.currentObservedAt, localeState.resolvedLocale)}</span>
                    </div>
                    <strong className="mt-1 block break-all text-sm text-[var(--cds-text-primary)]" title={point.targetPath}>{point.targetPath}</strong>
                    <span className="block text-xs text-[var(--cds-text-secondary)]">{t('details.retainedBytes', { count: point.sizeBytes })}</span>
                    {point.proposal ? (
                      <span className="block text-xs text-[var(--cds-text-secondary)]">{t('details.restoreApproval', { proposal: restoreProposalStatusLabel(point.proposal.status, t) })}</span>
                    ) : null}
                    {activeThread ? (
                      <ZnMissingRestoreControls
                        threadId={activeThread.id}
                        point={point}
                        disabled={restoreBusy || workActive}
                        onRealityChanged={() => refreshRestorePoints(activeThread.id)}
                      />
                    ) : null}
                  </div>
                ))}
              </div>
            )}
            <p className="mt-2 text-xs text-[var(--cds-text-secondary)]">{t('details.restoreSafety')}</p>
          </section>
        </aside>
      ) : null}
    </div>
  )
}
