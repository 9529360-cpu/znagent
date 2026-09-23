import type { TFunction } from 'i18next'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ArrowLeft,
  ArrowUp,
  ArrowsInSimple,
  ArrowsOutSimple,
  Brain,
  CaretDown,
  CheckCircle,
  Clock,
  Compass,
  ImageSquare,
  CircleNotch,
  ClockCounterClockwise,
  Desktop,
  FileText,
  FolderSimple,
  GearSix,
  MagnifyingGlass,
  Plus,
  Pulse,
  PushPin,
  PuzzlePiece,
  SidebarSimple,
  Sparkle,
  Stop,
  X
} from '@phosphor-icons/react'

import {
  applyZnUpdate,
  attachZnWorkspace,
  cancelZnWork,
  checkZnUpdate,
  createZnWorkThread,
  detachZnWorkspace,
  loadZnProviderSettings,
  loadZnResidentSnapshot,
  loadZnWorkProgress,
  loadZnWorkThread,
  loadZnWorkThreads,
  startZnWork,
  updateZnProviderSettings,
  type ZnProviderSettings,
  type ZnResidentSnapshot,
  type ZnWorkProgress
} from './resident-client'
import { describeZnProviderReadiness } from './provider-readiness'
import { useZnWorkReconnection } from './use-work-reconnection'
import {
  getZnDesktopLocaleState,
  setZnDesktopLocalePreference
} from './i18n'
import type { ZnLocalePreference } from '../../localization/zn-localization'
import { ZnMissingRestoreControls } from './restore-controls'
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

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => window.setTimeout(resolve, ms))
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

  const busy = useZnWorkReconnection({
    thread: activeThread,
    submissionBusy,
    progress: workProgress,
    onProgress: setWorkProgress,
    onThread: replaceThread,
    onError: setResidentError,
    onHealth: setResidentHealth,
    t
  })

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
    if (!activeThread || workspaceBusy || busy) return
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
  }, [activeThread, busy, replaceThread, workspaceBusy])

  const detachWorkspace = useCallback(async () => {
    if (!activeThread?.workspace || workspaceBusy || busy) return
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
  }, [activeThread, busy, replaceThread, workspaceBusy])

  const cancelCurrentWork = useCallback(async () => {
    if (!activeThread || !workProgress || cancelBusy || workProgress.finalized) return
    if (workProgress.threadId !== activeThread.id || !workProgress.recovery?.replayBlocked) return

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
      if (!task || busy || !activeThread) return

      const threadId = activeThread.id
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
        setWorkProgress(started.progress)
        setResidentError(null)
        setResidentHealth('live')

        const progressThreadId = started.progress.threadId
        let current = started.progress
        let finalThread = started.progress.finalized ? started.thread : undefined
        while (!current.terminal && current.stage !== 'inspection_complete') {
          await sleep(current.assistantResponse ? 260 : 650)
          const update = await loadZnWorkProgress(progressThreadId, current.eventId)
          current = update.progress
          setWorkProgress(current)
          if (update.thread) finalThread = update.thread
        }

        if (current.stage === 'inspection_complete') {
          void loadZnResidentSnapshot().then(setResidentSnapshot).catch(() => undefined)
          return
        }
        if (!current.finalized) {
          throw new Error(current.error || t('error.missingDurableOutcome'))
        }
        if (!finalThread) {
          const update = await loadZnWorkProgress(progressThreadId, current.eventId)
          finalThread = update.thread
        }
        if (finalThread) {
          replaceThread(finalThread)
          if (finalThread.artifacts.length > 0) {
            setSelectedArtifactId(finalThread.artifacts[0].id)
            setContextOpen(false)
            setArtifactOpen(false)
          }
        }
        setWorkProgress(null)
        void loadZnResidentSnapshot().then(setResidentSnapshot).catch(() => undefined)
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
    [activeThread, busy, draft, replaceThread, t]
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
      <aside className="zn-sidebar">
        <div className="zn-brand-row">
          <div className="zn-mark" aria-hidden="true">ZN</div>
          <div className="zn-brand-copy">
            <div className="zn-brand">ZN</div>
            <div className="zn-muted zn-small">{t('sidebar.alwaysHere')}</div>
          </div>
        </div>

        <button className="zn-primary zn-new-work" type="button" onClick={openNewWork}>
          <Plus size={16} weight="bold" />
          <span>{t('sidebar.newWork')}</span>
        </button>

        <nav className="zn-primary-nav" aria-label={t('sidebar.navigation')}>
          <button className="zn-nav-link" type="button" onClick={() => {
            openNewWork()
            setDraft(t('sidebar.imagePrompt'))
            window.requestAnimationFrame(focusComposerInput)
          }}>
            <ImageSquare size={17} /><span>{t('sidebar.images')}</span>
          </button>
          <button className="zn-nav-link" type="button" disabled title={t('sidebar.comingSoon')}>
            <Clock size={17} /><span>{t('sidebar.scheduled')}</span><small>{t('sidebar.soon')}</small>
          </button>
          <button className="zn-nav-link" type="button" disabled title={t('sidebar.comingSoon')}>
            <PuzzlePiece size={17} /><span>{t('sidebar.plugins')}</span><small>{t('sidebar.soon')}</small>
          </button>
          <button className="zn-nav-link" type="button" disabled title={t('sidebar.comingSoon')}>
            <Compass size={17} /><span>{t('sidebar.explore')}</span><small>{t('sidebar.soon')}</small>
          </button>
        </nav>

        <label className="zn-search-shell">
          <MagnifyingGlass size={15} />
          <input
            className="zn-search"
            aria-label={t('sidebar.searchRecent')}
            placeholder={t('sidebar.searchRecent')}
            value={query}
            onChange={event => setQuery(event.target.value)}
          />
        </label>

        <nav className="zn-nav" aria-label={t('topbar.recentWork')}>
          <button className="zn-section-toggle" type="button" aria-expanded={pinnedExpanded} onClick={() => setPinnedExpanded(value => !value)}>
            <CaretDown className={pinnedExpanded ? '' : 'collapsed'} size={14} /><span>{t('sidebar.pinned')}</span>
          </button>
          {pinnedExpanded && pinnedThreads.length > 0 ? (
            <div className="zn-thread-list zn-pinned-thread-list">
              {pinnedThreads.map(thread => (
                <div className="zn-thread-row" key={thread.id}>
                  <button className={'zn-thread-link' + (thread.id === activeThread?.id && view === 'work' ? ' active' : '')} type="button" onClick={() => {
                    setActiveThreadId(thread.id)
                    setView('work')
                    setContextOpen(false)
                    setArtifactOpen(false)
                    void refreshRestorePoints(thread.id)
                  }}>
                    <span>{threadDisplayTitle(thread.title, t)}</span>
                    <span className="zn-thread-time">{timeLabel(thread.updatedAt, localeState.resolvedLocale)}</span>
                  </button>
                  <button className="zn-thread-pin active" type="button" aria-label={t('sidebar.unpin')} title={t('sidebar.unpin')} onClick={() => togglePinnedThread(thread.id)}><PushPin size={14} weight="fill" /></button>
                </div>
              ))}
            </div>
          ) : null}
          {pinnedExpanded && pinnedThreads.length === 0 ? <div className="zn-sidebar-empty">{t('sidebar.noPinned')}</div> : null}
          <button className="zn-section-toggle zn-section-spaced" type="button" aria-expanded={projectsExpanded} onClick={() => setProjectsExpanded(value => !value)}>
            <CaretDown className={projectsExpanded ? '' : 'collapsed'} size={14} /><span>{t('sidebar.workspaces')}</span>
          </button>
          {projectsExpanded ? (
          <>
          <div className="zn-workspace-card">
            <FolderSimple size={17} />
            <div className="zn-workspace-copy">
              <div>{activeWorkspace?.name || t('sidebar.localWork')}</div>
              <div className="zn-muted zn-small zn-workspace-path" title={activeWorkspace?.path}>
                {activeWorkspace?.path || t('sidebar.noFolder')}
              </div>
            </div>
          </div>
          <div className="zn-workspace-actions">
            <button type="button" disabled={workspaceBusy || busy || !activeThread} onClick={() => void attachWorkspace()}>
              {workspaceBusy ? t('common.working') : activeWorkspace ? t('sidebar.changeFolder') : t('sidebar.attachFolder')}
            </button>
            {activeWorkspace ? (
              <button type="button" disabled={workspaceBusy || busy} onClick={() => void detachWorkspace()}>
                {t('sidebar.detach')}
              </button>
            ) : null}
          </div>
          </>
          ) : null}
          <button className="zn-section-toggle zn-section-spaced" type="button" aria-expanded={recentExpanded} onClick={() => setRecentExpanded(value => !value)}>
            <CaretDown className={recentExpanded ? '' : 'collapsed'} size={14} /><span>{t('sidebar.recent')}</span>
          </button>
          {recentExpanded ? <div className="zn-thread-list">
            {recentThreads.map(thread => (
              <div className="zn-thread-row" key={thread.id}>
                <button
                  className={'zn-thread-link' + (thread.id === activeThread?.id && view === 'work' ? ' active' : '')}
                  type="button"
                  onClick={() => {
                    setActiveThreadId(thread.id)
                    setView('work')
                    setContextOpen(false)
                    setArtifactOpen(false)
                    void refreshRestorePoints(thread.id)
                  }}
                >
                  <span>{threadDisplayTitle(thread.title, t)}</span>
                  <span className="zn-thread-time">{timeLabel(thread.updatedAt, localeState.resolvedLocale)}</span>
                </button>
                <button className="zn-thread-pin" type="button" aria-label={t('sidebar.pin')} title={t('sidebar.pin')} onClick={() => togglePinnedThread(thread.id)}><PushPin size={14} /></button>
              </div>
            ))}
          </div> : null}


        </nav>

        <div className="zn-sidebar-footer">
          <button className="zn-nav-button" type="button" onClick={openSettings}>
            <GearSix size={16} />
            <span>{t('settings.title')}</span>
          </button>
        </div>
      </aside>

      <section className="zn-main-column">
        <header className="zn-topbar">
          <div className="zn-topbar-brand">
            <div className="zn-mark zn-mark-small" aria-hidden="true">ZN</div>
            <div>
              <div className="zn-brand">ZN</div>
              <div className="zn-topbar-presence">
                <span className={'zn-health-dot ' + residentHealth} />
                {residentHealth === 'live' ? t('common.ready') : residentHealth === 'connecting' ? t('common.connecting') : t('common.offline')}
              </div>
            </div>
          </div>

          <div className="zn-topbar-copy">
            <div className="zn-topbar-title">{view === 'settings' ? t('settings.title') : activeThread ? threadDisplayTitle(activeThread.title, t) : t('sidebar.newWork')}</div>
            <div className="zn-muted zn-small">{view === 'settings' ? `ZN · ${t('topbar.thisComputer')}` : activeWorkspace?.name || t('topbar.thisComputer')}</div>
          </div>

          {view === 'work' ? (
            <div className="zn-mode-switch" role="tablist" aria-label={t('topbar.workDetails')}>
              <button className={!contextOpen ? 'active' : ''} role="tab" aria-selected={!contextOpen} type="button" onClick={() => setContextOpen(false)}>
                {t('topbar.chat')}
              </button>
              <button className={contextOpen ? 'active' : ''} role="tab" aria-selected={contextOpen} type="button" onClick={openDetails}>
                {t('topbar.work')}
              </button>
            </div>
          ) : null}

          <div className="zn-topbar-actions">
            <button type="button" aria-label={t('topbar.recentWork')} title={t('topbar.recentWork')} onClick={() => requestWindowMode('expanded')}>
              <ClockCounterClockwise size={17} />
            </button>
            <button type="button" aria-label={t('topbar.toggleSidebar')} title={t('topbar.toggleSidebar')} aria-pressed={sidebarCollapsed} onClick={() => setSidebarCollapsed(value => !value)}>
              <SidebarSimple size={17} />
            </button>
            <button type="button" aria-label={t('topbar.openSettings')} title={t('settings.title')} onClick={openSettings}>
              <GearSix size={17} />
            </button>
            <button
              type="button"
              aria-label={windowMode === 'compact' ? t('topbar.expandZn') : t('topbar.compactZn')}
              title={windowMode === 'compact' ? t('topbar.expand') : t('topbar.compact')}
              onClick={toggleWindowMode}
            >
              {windowMode === 'compact' ? <ArrowsOutSimple size={17} /> : <ArrowsInSimple size={17} />}
            </button>
          </div>
        </header>

        {view === 'settings' ? (
          <main className="zn-settings">
            <div className="zn-settings-layout">
              <nav className="zn-settings-nav" aria-label={t('settings.title')}>
                <button className="zn-settings-back" type="button" onClick={() => setView('work')}>
                  <ArrowLeft size={17} />
                  <span>{t('workstation.returnToConversation')}</span>
                </button>
                <div className="zn-settings-nav-group">
                  <div className="zn-settings-nav-label">{t('settings.nav.personal')}</div>
                  <button className={settingsSection === 'language' ? 'active' : ''} type="button" aria-current={settingsSection === 'language' ? 'page' : undefined} onClick={() => focusSettingsSection('language')}><Desktop size={17} /><span>{t('settings.language.title')}</span></button>
                  <button className={settingsSection === 'models' ? 'active' : ''} type="button" aria-current={settingsSection === 'models' ? 'page' : undefined} onClick={() => focusSettingsSection('models')}><Brain size={17} /><span>{t('settings.models.title')}</span></button>
                </div>
                <div className="zn-settings-nav-group zn-settings-nav-group-spaced">
                  <div className="zn-settings-nav-label">{t('settings.nav.app')}</div>
                  <button className={settingsSection === 'background' ? 'active' : ''} type="button" aria-current={settingsSection === 'background' ? 'page' : undefined} onClick={() => focusSettingsSection('background')}><Pulse size={17} /><span>{t('settings.background.title')}</span></button>
                  <button className={settingsSection === 'updates' ? 'active' : ''} type="button" aria-current={settingsSection === 'updates' ? 'page' : undefined} onClick={() => focusSettingsSection('updates')}><CheckCircle size={17} /><span>{t('settings.updates.title')}</span></button>
                </div>
              </nav>
              <div className="zn-settings-content">
            <div className="zn-page-intro">
              <span className="zn-eyebrow">{t('settings.eyebrow')}</span>
              <h1>{t(settingsSection === 'language' ? 'settings.language.title' : settingsSection === 'models' ? 'settings.models.title' : settingsSection === 'background' ? 'settings.background.title' : 'settings.updates.title')}</h1>
              <p>{t(settingsSection === 'language' ? 'settings.language.description' : settingsSection === 'models' ? 'settings.models.description' : settingsSection === 'background' ? 'settings.background.description' : 'settings.updates.description')}</p>
            </div>
            <div className="zn-settings-grid" data-active-section={settingsSection}>
              <section className="zn-card" id="zn-settings-language">
                <label className="zn-setting-field">
                  <span className="zn-context-title">{t('settings.language.label')}</span>
                  <select
                    className="zn-search"
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
                <p className="zn-muted zn-small">
                  {t('settings.language.systemDetected', {
                    languages: localeState.preferredSystemLanguages.join(', ') || localeState.resolvedLocale
                  })}
                </p>
              </section>

              <section className="zn-card" id="zn-settings-background">
                <button type="button" onClick={() => void refreshResident()}>{t('settings.background.refresh')}</button>
                {residentError ? <div className="zn-error-text">{residentError}</div> : null}
                <details>
                  <summary className="zn-muted zn-small">{t('settings.background.technical')}</summary>
                  <pre className="zn-compact-pre">{residentSnapshot ? renderUnknown(residentSnapshot) : t('settings.background.waiting')}</pre>
                </details>
              </section>

              <section className="zn-card" id="zn-settings-models">
                {providerSettings && !providerSettings.editable ? (
                  <>
                    <div className="zn-setting-state">
                      {t('settings.models.advancedActive', {
                        mode: providerSettings.mode,
                        routes: providerSettings.routeCount
                          ? t('settings.models.routes', { count: providerSettings.routeCount })
                          : ''
                      })}
                    </div>
                    <p className="zn-muted zn-small">{t('settings.models.advancedWarning')}</p>
                  </>
                ) : (
                  <form onSubmit={saveProvider}>
                    <div className={'zn-api-connection-state ' + (providerReadiness.ready ? 'ready' : 'needs-setup')} role="status" aria-live="polite">
                      <span className="zn-api-status-dot" />
                      <span>{t(providerReadiness.ready ? 'settings.models.connectionReady' : 'settings.models.connectionNeedsSetup')}</span>
                      <span className="zn-api-status-detail">{localizedProviderReadinessDetail}</span>
                    </div>
                    <div className="zn-api-fields">
                      <label className="zn-api-field">
                        <span>{t('settings.models.provider')}</span>
                        <input className="zn-search" aria-label={t('settings.models.providerAria')} value={providerName} disabled={providerBusy} onChange={event => setProviderName(event.target.value)} placeholder="openai, anthropic, gemini, ollama..." />
                        <small>{t('settings.models.providerHelp')}</small>
                      </label>
                      <label className="zn-api-field">
                        <span>{t('settings.models.model')}</span>
                        <input className="zn-search" aria-label={t('settings.models.modelAria')} value={providerModel} disabled={providerBusy} onChange={event => setProviderModel(event.target.value)} placeholder={t('settings.models.modelPlaceholder')} />
                        <small>{t('settings.models.modelHelp')}</small>
                      </label>
                      <label className="zn-api-field zn-api-field-wide">
                        <span>{t('settings.models.baseUrl')}</span>
                        <input className="zn-search" aria-label={t('settings.models.baseUrlAria')} type="url" autoComplete="url" value={providerBaseUrl} disabled={providerBusy} onChange={event => setProviderBaseUrl(event.target.value)} placeholder={t('settings.models.baseUrlPlaceholder')} />
                        <small>{t('settings.models.baseUrlHelp')}</small>
                      </label>
                      <label className="zn-api-field zn-api-field-wide">
                        <span>{t('settings.models.credential')}</span>
                        <input className="zn-search" aria-label={t('settings.models.credentialAria')} type="password" autoComplete="new-password" value={providerApiKey} disabled={providerBusy} onChange={event => setProviderApiKey(event.target.value)} placeholder={providerSettings?.credential.configured ? t('settings.models.keepCredential') : t('settings.models.optionalCredential')} />
                        <small>{t(providerSettings?.credential.configured ? 'settings.models.credentialSaved' : 'settings.models.credentialHelp')}</small>
                      </label>
                    </div>
                    <details className="zn-api-security-details">
                      <summary>{t('settings.models.securityDetails')}</summary>
                      <p>{credentialLabel(providerSettings, t)}</p>
                      {providerSettings ? <p>{t('settings.models.secureStore', {
                        status: providerSettings.credential.secureStore.available ? t('common.available') : t('common.unavailable'),
                        backend: providerSettings.credential.secureStore.backend
                      })}</p> : null}
                    </details>
                    {providerSettings?.configurationError ? <div className="zn-error-text" role="alert">{providerSettings.configurationError}</div> : null}
                    {providerNotice ? <div className="zn-setting-state" role="status" aria-live="polite">{providerNotice}</div> : null}
                    <div className="zn-inline-actions zn-settings-actions">
                      <button className="zn-primary" type="submit" disabled={providerBusy || !providerName.trim() || !providerModel.trim()}>{providerBusy ? t('common.applying') : t('settings.models.save')}</button>
                      {showClearCredential ? <button type="button" disabled={providerBusy} onClick={() => void clearProviderCredential()}>{t('settings.models.clearCredential')}</button> : null}
                      <button type="button" disabled={providerBusy} onClick={() => void refreshProviderSettings()}>{t('common.refresh')}</button>
                    </div>
                  </form>
                )}
              </section>

              <section className="zn-card" id="zn-settings-updates">
                <div className="zn-inline-actions">
                  <button type="button" disabled={updateBusy} onClick={() => void checkUpdates()}>{updateBusy ? t('common.checking') : t('settings.updates.check')}</button>
                  {updateStatus?.updateAvailable ? <button className="zn-primary" type="button" disabled={updateBusy} onClick={() => void applyUpdate()}>{t('settings.updates.apply', { version: updateStatus.availableVersion || t('settings.updates.updateFallback') })}</button> : null}
                </div>
                {updateStatus ? <pre className="zn-compact-pre">{renderUnknown(updateStatus)}</pre> : null}
              </section>
            </div>
            </div>
            </div>
          </main>
        ) : (
          <>
            <main className="zn-thread-surface">
              {residentHealth === 'offline' ? (
                <div className="zn-connection-recovery" role="alert" aria-live="polite">
                  <div className="zn-connection-recovery-copy">
                    <strong>{t('error.residentUnavailableTitle')}</strong>
                    <span>{t('error.residentUnavailableHint')}</span>
                  </div>
                  <button type="button" onClick={() => void refreshResident()}>{t('error.reconnect')}</button>
                </div>
              ) : null}
              {deepLinkNotice ? (
                <div className="zn-notice">
                  <strong>{t('deepLink.received')}</strong> {t('deepLink.safe')}
                  <button type="button" onClick={() => setDeepLinkNotice(null)}>{t('deepLink.dismiss')}</button>
                </div>
              ) : null}

              {activeThread && activeThread.messages.length === 0 && !showActiveWork ? (
                <section className="zn-home">
                  <div className="zn-home-hero">
                    <span className="zn-home-orbit"><Sparkle size={18} weight="fill" /></span>
                    <span className="zn-eyebrow">{t('home.eyebrow')}</span>
                    <h1>{t('home.title')}</h1>
                    <p>{t('home.description')}</p>
                  </div>

                  <div className="zn-home-quick-starts" aria-label={t('home.quickStartsAria')}>
                    {ZN_HOME_QUICK_STARTS.map((action, index) => (
                      <button key={action.labelKey} type="button" onClick={() => chooseHomePrompt(t(action.promptKey))}>
                        {index === 0 ? <Desktop size={17} /> : index === 1 ? <FileText size={17} /> : <Brain size={17} />}
                        <span>{t(action.labelKey)}</span>
                      </button>
                    ))}
                    {activeWorkspace ? (
                      <button type="button" onClick={() => chooseHomePrompt(t('home.prompt.reviewWorkspace'))}>
                        <FolderSimple size={17} />
                        <span>{t('home.reviewWorkspace')}</span>
                      </button>
                    ) : (
                      <button type="button" disabled={workspaceBusy || busy || !activeThread} onClick={() => void attachWorkspace()}>
                        <FolderSimple size={17} />
                        <span>{workspaceBusy ? t('home.attaching') : t('sidebar.attachFolder')}</span>
                      </button>
                    )}
                  </div>

                  <div className="zn-home-status" aria-label={t('home.readinessAria')}>
                    <span><i className={'zn-health-dot ' + residentHealth} />{residentHealth === 'live' ? t('home.residentReady') : residentHealth === 'connecting' ? t('home.residentConnecting') : t('home.residentOffline')}</span>
                    <span>{activeWorkspace ? t('home.workspace', { name: activeWorkspace.name }) : t('topbar.thisComputer')}</span>
                    <span title={localizedProviderReadinessDetail}>{providerReadiness.ready ? t('home.cognitionAvailable') : t('home.cognitionSetupNeeded')}</span>
                  </div>
                </section>
              ) : null}

              {activeThread && activeThread.messages.length > 0 ? (
                <div className="zn-messages">
                  {activeThread.messages.map(message => {
                    const executionEvidence = message.role === 'activity'
                      ? executionEvidenceFromDetail(message.detail)
                      : null
                    return (
                      <article className={'zn-message ' + message.role} key={message.id}>
                        <div className="zn-message-label">{message.role === 'user' ? t('message.you') : message.role === 'zn' ? 'ZN' : t('message.activity')}</div>
                        <div className="zn-message-body">{message.text}</div>
                        {executionEvidence ? (
                          <div className="zn-execution-evidence" aria-label={t('message.executionEvidence')}>
                            <span>{executionPathLabel(executionEvidence.executionPath, t)}</span>
                            <span>{t('message.modelCalls', { count: executionEvidence.modelInvocations })}</span>
                          </div>
                        ) : null}
                        {message.detail && Object.keys(message.detail).length > 0 ? (
                          executionEvidence ? (
                            <details className="zn-activity-technical">
                              <summary>{t('message.technical')}</summary>
                              <pre className="zn-activity-detail">{renderUnknown(message.detail)}</pre>
                            </details>
                          ) : <pre className="zn-activity-detail">{renderUnknown(message.detail)}</pre>
                        ) : null}
                      </article>
                    )
                  })}
                  {showActiveWork && workProgress?.assistantResponse ? (
                    <article className="zn-message zn zn-message-streaming" aria-live="polite">
                      <div className="zn-message-label">ZN</div>
                      <div className="zn-message-body">{workProgress.assistantResponse}<span className="zn-stream-caret" aria-hidden="true" /></div>
                    </article>
                  ) : null}
                </div>
              ) : null}

              {showActiveWork && workProgress ? (
                <section className="zn-current-work" aria-live="polite">
                  <div className="zn-current-work-head">
                    <span className="zn-current-work-icon"><Pulse size={19} weight="bold" /></span>
                    <div className="zn-current-work-copy">
                      <div className="zn-eyebrow">{t('work.residentProgress', { status: statusLabel(workProgress.status, t) })}</div>
                      <h2>{activeThread ? threadDisplayTitle(activeThread.title, t) : t('work.workingOnIt')}</h2>
                      <p>{stageLabel(workProgress.stage, t)} · {workProgress.nextAction || t('work.continuing')}</p>
                    </div>
                    {workProgress.recovery?.replayBlocked ? (
                      <button className="zn-stop-button" type="button" disabled={cancelBusy} onClick={() => void cancelCurrentWork()}>
                        <Stop size={15} weight="fill" />
                        <span>{cancelBusy ? t('work.stopping') : t('work.stop')}</span>
                      </button>
                    ) : null}
                  </div>

                  <div className="zn-work-steps" aria-label={t('work.statusAria')}>
                    <div className="done"><CheckCircle size={17} weight="fill" /><span>{t('work.accepted')}</span></div>
                    <div className="active"><CircleNotch className="zn-spin" size={17} /><span>{stageLabel(workProgress.stage, t)}</span></div>
                    <div><CheckCircle size={17} /><span>{t('work.verify')}</span></div>
                  </div>

                  {workProgress.delegation ? (
                    <div className="zn-work-detail" aria-label={t('work.delegatedProgressAria')}>
                      <div><strong>{t('work.delegated')}</strong> · {statusLabel(workProgress.delegation.status, t)}</div>
                      {workProgress.delegation.phases.map((phase, index) => (
                        <div key={phase.kind + '-' + phase.status + '-' + (phase.updatedAt || 0) + '-' + index}>
                          {delegatedStatusMarker(phase.status)} {delegatedKindLabel(phase.kind, t)} · {delegatedStageLabel(phase.stage, t)}
                        </div>
                      ))}
                    </div>
                  ) : null}

                  {workProgress.recovery?.replayBlocked ? (
                    <div className="zn-recovery-warning">
                      <strong>{t('work.outsideUncertain')}</strong>
                      <span>{t('work.noReplay')}</span>
                      {workProgress.recovery.reason ? <span>{workProgress.recovery.reason}</span> : null}
                    </div>
                  ) : null}

                  <details className="zn-progress-technical">
                    <summary>{t('work.whatDoing')}</summary>
                    {workProgress.thought ? (
                      <div className="zn-muted zn-small">
                        {workProgress.thought.action || workProgress.thought.focus}
                        {workProgress.thought.reason ? ' — ' + workProgress.thought.reason : ''}
                      </div>
                    ) : null}
                    {workProgress.investigation ? (
                      <div className="zn-muted zn-small">
                        {t('work.investigationRound', { round: workProgress.investigation.rounds, status: statusLabel(workProgress.investigation.status, t) })}
                        {workProgress.investigation.nextProbe ? t('work.next', { next: workProgress.investigation.nextProbe }) : ''}
                      </div>
                    ) : null}
                    {workProgress.bodyActions.length > 0 ? (
                      <div className="zn-work-detail">
                        {workProgress.bodyActions.map((action, index) => (
                          <div key={action.at + '-' + action.kind + '-' + index}>
                            {action.kind} · {action.success ? t('work.ok') : t('work.failed')}{action.summary ? ' · ' + action.summary : ''}
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </details>

                  <div className="zn-current-work-actions">
                    <button type="button" onClick={openDetails}>{t('work.viewDetails')}</button>
                    <span>{t('work.updated', { time: timeLabel(workProgress.updatedAt, localeState.resolvedLocale) })}</span>
                  </div>
                </section>
              ) : null}

              {!showActiveWork && firstResult ? (
                <section className="zn-result-summary">
                  <span className="zn-result-icon"><CheckCircle size={22} weight="fill" /></span>
                  <div className="zn-result-copy">
                    <span className="zn-eyebrow">{t('result.title')}</span>
                    <strong>{firstResult.name}</strong>
                    <span>{t('result.ready', { count: activeArtifacts.length })}</span>
                  </div>
                  <button type="button" onClick={() => activeWorkstationArtifact ? openArtifact(activeWorkstationArtifact.id) : openDetails()}>{t('result.view')}</button>
                </section>
              ) : null}
            </main>

            <form className="zn-composer-wrap" onSubmit={submit}>
              <div className="zn-composer">
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
                <div className="zn-composer-toolbar">
                  <div className="zn-composer-tools">
                    <button
                      className="zn-composer-tool"
                      type="button"
                      aria-label={activeWorkspace ? t('composer.changeAttachedFolder') : t('composer.attachFolder')}
                      title={activeWorkspace ? t('composer.changeFolder') : t('composer.attachFolder')}
                      disabled={workspaceBusy || busy || !activeThread}
                      onClick={() => void attachWorkspace()}
                    >
                      <Plus size={18} />
                    </button>
                    <span className="zn-context-chip" title={activeWorkspace?.path}>
                      <FolderSimple size={14} />
                      {activeWorkspace?.name || t('topbar.thisComputer')}
                    </span>
                  </div>
                  <div className="zn-composer-tools">
                    <span className="zn-model-chip" title={localizedProviderReadinessDetail}>
                      {providerSettings?.model || 'ZN'}
                    </span>
                    <button className="zn-send" type="submit" aria-label={t('composer.sendAria')} disabled={busy || !draft.trim()}>
                      {busy ? <CircleNotch className="zn-spin" size={18} /> : <ArrowUp size={18} weight="bold" />}
                    </button>
                  </div>
                </div>
              </div>
              <div className="zn-composer-caption">
                {busy ? t('composer.background') : ''}{t('composer.shortcut')}
              </div>
            </form>
          </>
        )}
      </section>

      {artifactOpen && selectedWorkstationArtifact && view === 'work' ? (
        <aside className="zn-artifact-pane" aria-label={t('artifact.preview')}>
          <div className="zn-artifact-pane-header">
            <div>
              <span>{artifactKindLabel(selectedWorkstationArtifact.kind, t)}</span>
              <strong>{selectedWorkstationArtifact.name}</strong>
            </div>
            <button type="button" aria-label={t('artifact.closePreview')} onClick={() => setArtifactOpen(false)}>
              <X size={18} />
            </button>
          </div>
          <div className="zn-artifact-pane-body">
            {selectedWorkstationArtifact.kind === 'document' ? (
              <ZnDocumentWorkstation artifact={selectedWorkstationArtifact} />
            ) : (
              <ZnSlidesWorkstation artifact={selectedWorkstationArtifact} artifacts={activeArtifacts} />
            )}
          </div>
        </aside>
      ) : null}

      {contextOpen ? <button className="zn-details-backdrop" type="button" aria-label={t('details.closeWorkAria')} onClick={() => setContextOpen(false)} /> : null}

      {contextOpen ? (
        <aside className="zn-context-panel" aria-label={t('details.panelAria')}>
          <div className="zn-context-header">
            <div>
              <div className="zn-section-label">{t('details.title')}</div>
              <strong>{selectedArtifact ? artifactKindLabel(selectedArtifact.kind, t) : t('details.currentWork')}</strong>
            </div>
            <button type="button" aria-label={t('details.closePanelAria')} onClick={() => setContextOpen(false)}>
              <X size={18} />
            </button>
          </div>

          <section className="zn-context-section">
            <div className="zn-context-title">{t('details.workspace')}</div>
            {activeWorkspace ? (
              <>
                <div className="zn-context-value"><FolderSimple size={16} />{activeWorkspace.name}</div>
                <div className="zn-context-path" title={activeWorkspace.path}>{activeWorkspace.path}</div>
                <div className="zn-inline-actions zn-context-actions">
                  <button type="button" disabled={workspaceBusy || busy} onClick={() => void attachWorkspace()}>{t('details.change')}</button>
                  <button type="button" disabled={workspaceBusy || busy} onClick={() => void detachWorkspace()}>{t('details.detach')}</button>
                </div>
              </>
            ) : (
              <>
                <p className="zn-muted zn-small">{t('details.noFolder')}</p>
                <div className="zn-context-actions">
                  <button type="button" disabled={workspaceBusy || busy || !activeThread} onClick={() => void attachWorkspace()}>{t('details.attachFolder')}</button>
                </div>
              </>
            )}
          </section>

          {activeArtifacts.length > 0 ? (
            <section className="zn-context-section zn-context-grow zn-artifact-section">
              <div className="zn-context-title">{t('details.results')}</div>
              <div className="zn-artifact-list" aria-label={t('details.artifactsAria')}>
                {activeArtifacts.map(artifact => (
                  <button
                    className={'zn-artifact-link' + (artifact.id === selectedArtifact?.id ? ' active' : '')}
                    key={artifact.id}
                    type="button"
                    onClick={() => {
                      setSelectedArtifactId(artifact.id)
                      if (artifact.kind === 'presentation' || artifact.kind === 'document') openArtifact(artifact.id)
                    }}
                  >
                    <span className="zn-artifact-icon"><FileText size={15} /></span>
                    <span className="zn-artifact-copy">
                      <span className="zn-artifact-kind">{artifactKindLabel(artifact.kind, t)}</span>
                      <span className="zn-artifact-name">{artifact.name}</span>
                    </span>
                  </button>
                ))}
              </div>
              {selectedArtifact ? (
                <div className="zn-artifact-preview">
                  <div className="zn-artifact-preview-head">
                    <strong>{selectedArtifact.name}</strong>
                    {selectedArtifact.path ? <span title={selectedArtifact.path}>{selectedArtifact.path}</span> : null}
                  </div>
                  {selectedArtifact.kind === 'presentation' ? (
                    <div className="zn-artifact-note">{selectedArtifact.name}</div>
                  ) : (
                    <pre>{selectedArtifact.content || t('details.noPreview')}</pre>
                  )}
                  {selectedArtifact.metadata?.truncated ? <div className="zn-artifact-note">{t('details.previewTruncated')}</div> : null}
                </div>
              ) : null}
            </section>
          ) : (
            <section className="zn-context-section">
              <div className="zn-context-title">{t('details.results')}</div>
              <p className="zn-muted zn-small">{t('details.noResults')}</p>
            </section>
          )}

          <section className="zn-context-section">
            <div className="zn-context-title">{t('details.residentStatus')}</div>
            <div className="zn-context-value">
              <span className={'zn-health-dot ' + residentHealth} />
              {residentHealth === 'live' ? t('common.ready') : residentHealth === 'connecting' ? t('common.connecting') : t('common.offline')}
            </div>
            {residentError ? <div className="zn-error-text">{residentError}</div> : null}
          </section>

          <section className="zn-context-section">
            <div className="zn-context-section-head">
              <div className="zn-context-title">{t('details.restorePoints')}</div>
              <button type="button" disabled={restoreBusy || !activeThread} onClick={() => activeThread && void refreshRestorePoints(activeThread.id)}>
                {restoreBusy ? t('common.checking') : t('common.refresh')}
              </button>
            </div>
            {activeRestorePoints === undefined ? (
              <p className="zn-muted zn-small">{t('details.restorePrompt')}</p>
            ) : activeRestorePoints.length === 0 ? (
              <p className="zn-muted zn-small">{t('details.noRestorePoints')}</p>
            ) : (
              <div className="zn-restore-list" aria-label={t('details.restoreListAria')}>
                {activeRestorePoints.map(point => (
                  <div className="zn-restore-row" key={point.id}>
                    <div className="zn-restore-row-head">
                      <span>{restorePointStatusLabel(point.currentStatus, t)}</span>
                      <span>{timeLabel(point.currentObservedAt, localeState.resolvedLocale)}</span>
                    </div>
                    <strong title={point.targetPath}>{point.targetPath}</strong>
                    <span className="zn-muted zn-small">{t('details.retainedBytes', { count: point.sizeBytes })}</span>
                    {point.proposal ? (
                      <span className="zn-muted zn-small">{t('details.restoreApproval', { proposal: restoreProposalStatusLabel(point.proposal.status, t) })}</span>
                    ) : null}
                    {activeThread ? (
                      <ZnMissingRestoreControls
                        threadId={activeThread.id}
                        point={point}
                        disabled={restoreBusy || busy}
                        onRealityChanged={() => refreshRestorePoints(activeThread.id)}
                      />
                    ) : null}
                  </div>
                ))}
              </div>
            )}
            <p className="zn-muted zn-small">{t('details.restoreSafety')}</p>
          </section>
        </aside>
      ) : null}
    </div>
  )
}