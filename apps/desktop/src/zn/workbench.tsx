import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import {
  ArrowUp,
  ArrowsInSimple,
  ArrowsOutSimple,
  Brain,
  CheckCircle,
  CircleNotch,
  ClockCounterClockwise,
  Desktop,
  FileText,
  FolderSimple,
  GearSix,
  MagnifyingGlass,
  Paperclip,
  Plus,
  Pulse,
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
import {
  describeZnProviderReadiness,
  providerUpdateNotice
} from './provider-readiness'
import { ZnMissingRestoreControls } from './restore-controls'
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

function renderUnknown(value: unknown): string {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function timeLabel(value: number): string {
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

function artifactKindLabel(kind: string): string {
  if (kind === 'diff') return 'Diff'
  if (kind === 'file') return 'File'
  if (kind === 'terminal') return 'Terminal'
  return 'Artifact'
}

function restorePointStatusLabel(status: ZnRestorePointCurrentStatus): string {
  if (status === 'unchanged') return 'Current target unchanged'
  if (status === 'changed') return 'Current target changed'
  if (status === 'missing') return 'Current target missing'
  return 'Current target cannot be compared safely'
}

function restoreProposalStatusLabel(status: ZnRestoreProposalStatus): string {
  if (status === 'candidate') return 'Restore candidate'
  if (status === 'conflict_review_required') return 'Review current changes before any restore'
  if (status === 'missing_target_review_required') return 'Review missing target before any restore'
  return 'Restore proposal blocked'
}

function delegatedKindLabel(kind: string): string {
  if (kind === 'research') return 'Research'
  if (kind === 'coding') return 'Coding'
  if (kind === 'review') return 'Review'
  return 'Work'
}

function delegatedStageLabel(stage: string): string {
  if (stage === 'result_ready') return 'result ready'
  return stage.replaceAll('_', ' ')
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

function executionPathLabel(path: string): string {
  if (path === 'memory') return 'Resident memory'
  if (path === 'capability') return 'Resident capability'
  if (path === 'investigation') return 'Resident investigation'
  if (path === 'body') return 'PC action'
  if (path === 'model') return 'Model cognition'
  if (path === 'control') return 'Resident control'
  if (path === 'budget_blocked') return 'Cognition budget blocked'
  return path.replaceAll('_', ' ')
}

function executionEvidenceFromDetail(detail?: Record<string, unknown>): ExecutionEvidence | null {
  if (!detail) return null
  const executionPath = String(detail.execution_path ?? detail.executionPath ?? '').trim()
  const modelInvocations = Number(detail.model_invocations ?? detail.modelInvocations)
  if (!executionPath || !Number.isSafeInteger(modelInvocations) || modelInvocations < 0) return null
  return { executionPath, modelInvocations }
}

function credentialLabel(settings: ZnProviderSettings | null): string {
  if (!settings) return 'Credential status unavailable'
  const { credential } = settings
  if (credential.source === 'secure_store') return 'Credential stored in the resident secure store'
  if (credential.source === 'environment') {
    return `Credential supplied by ${credential.environmentName || 'provider environment'}`
  }
  if (credential.source === 'config') return 'Legacy plaintext credential exists in config; replace it to migrate securely'
  if (credential.source === 'secure_store_unavailable') return 'Credential reference exists, but this OS secure store is unavailable'
  return 'No credential configured; local providers or provider environment variables can still work'
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
  { label: 'Open an app', prompt: 'Open Chrome.' },
  { label: 'Clean current app', prompt: 'Clean up the text in the current app.' },
  { label: 'Research a topic', prompt: 'Research this topic and give me the useful evidence: ' }
] as const

export function ZnWorkbench() {
  const [threads, setThreads] = useState<ZnThread[]>(() => {
    const cached = loadZnThreadCache()
    return cached.length > 0 ? cached : [newZnThread()]
  })
  const [activeThreadId, setActiveThreadId] = useState(() => threads[0]?.id || '')
  const [selectedArtifactId, setSelectedArtifactId] = useState('')
  const [view, setView] = useState<MainView>('work')
  const [query, setQuery] = useState('')
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
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
  const activeArtifacts = useMemo(() => activeThread?.artifacts || [], [activeThread])
  const activeRestorePoints = activeThread?.restorePoints
  const selectedArtifact = useMemo(
    () => activeArtifacts.find(artifact => artifact.id === selectedArtifactId) || activeArtifacts[0] || null,
    [activeArtifacts, selectedArtifactId]
  )
  const recentThreads = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    return [...threads]
      .sort((left, right) => right.updatedAt - left.updatedAt)
      .filter(thread => !normalized || thread.title.toLowerCase().includes(normalized))
  }, [query, threads])
  const providerReadiness = useMemo(
    () => describeZnProviderReadiness(providerSettings),
    [providerSettings]
  )

  useEffect(() => saveZnThreadCache(threads), [threads])

  useEffect(() => {
    setSelectedArtifactId(current =>
      activeArtifacts.some(artifact => artifact.id === current)
        ? current
        : activeArtifacts[0]?.id || ''
    )
  }, [activeArtifacts])

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
      focusComposerInput()
    })
  }, [])

  const openNewWork = useCallback(() => {
    const thread = newZnThread()
    setThreads(current => [thread, ...current])
    setActiveThreadId(thread.id)
    setSelectedArtifactId('')
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
          await sleep(700)
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
          throw new Error(current.error || 'Resident work ended without a durable work outcome')
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
            ? `${message} ZN may keep working on this task while the desktop reconnects.`
            : message
        )
        setResidentHealth(residentAccepted ? 'connecting' : 'offline')
      } finally {
        setBusy(false)
      }
    },
    [activeThread, busy, draft, replaceThread]
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
      setProviderNotice(providerUpdateNotice(settings))
      setResidentHealth('live')
    } catch (error) {
      setProviderNotice(error instanceof Error ? error.message : String(error))
    } finally {
      setProviderBusy(false)
    }
  }, [applyProviderSettings, providerApiKey, providerBaseUrl, providerModel, providerName])

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
      setProviderNotice('Stored provider credential cleared.')
    } catch (error) {
      setProviderNotice(error instanceof Error ? error.message : String(error))
    } finally {
      setProviderBusy(false)
    }
  }, [applyProviderSettings, providerBaseUrl, providerModel, providerName, providerSettings?.editable])

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
    setWindowMode(mode)
    void window.znDesktop?.shell?.setWindowMode?.(mode)
    if (mode === 'compact') setContextOpen(false)
  }, [])

  const openSettings = useCallback(() => {
    setView('settings')
    requestWindowMode('expanded')
  }, [requestWindowMode])

  const openDetails = useCallback(() => {
    setContextOpen(true)
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
    <div className={'zn-app ' + windowMode + (contextOpen ? ' details-open' : '')}>
      <aside className="zn-sidebar">
        <div className="zn-brand-row">
          <div className="zn-mark" aria-hidden="true">ZN</div>
          <div className="zn-brand-copy">
            <div className="zn-brand">ZN</div>
            <div className="zn-muted zn-small">Always here for you</div>
          </div>
        </div>

        <button className="zn-primary zn-new-work" type="button" onClick={openNewWork}>
          <Plus size={16} weight="bold" />
          <span>New work</span>
        </button>

        <label className="zn-search-shell">
          <MagnifyingGlass size={15} />
          <input
            className="zn-search"
            aria-label="Search recent work"
            placeholder="Search recent work"
            value={query}
            onChange={event => setQuery(event.target.value)}
          />
        </label>

        <nav className="zn-nav" aria-label="Recent work">
          <div className="zn-section-label">Recent</div>
          <div className="zn-thread-list">
            {recentThreads.map(thread => (
              <button
                className={'zn-thread-link' + (thread.id === activeThread?.id && view === 'work' ? ' active' : '')}
                key={thread.id}
                type="button"
                onClick={() => {
                  setActiveThreadId(thread.id)
                  setView('work')
                  setContextOpen(false)
                  void refreshRestorePoints(thread.id)
                }}
              >
                <span>{thread.title}</span>
                <span className="zn-thread-time">{timeLabel(thread.updatedAt)}</span>
              </button>
            ))}
          </div>

          <div className="zn-section-label zn-section-spaced">Workspaces</div>
          <div className="zn-workspace-card">
            <FolderSimple size={17} />
            <div className="zn-workspace-copy">
              <div>{activeWorkspace?.name || 'Local work'}</div>
              <div className="zn-muted zn-small zn-workspace-path" title={activeWorkspace?.path}>
                {activeWorkspace?.path || 'No folder attached'}
              </div>
            </div>
          </div>
          <div className="zn-workspace-actions">
            <button type="button" disabled={workspaceBusy || busy || !activeThread} onClick={() => void attachWorkspace()}>
              {workspaceBusy ? 'Working...' : activeWorkspace ? 'Change folder' : 'Attach folder'}
            </button>
            {activeWorkspace ? (
              <button type="button" disabled={workspaceBusy || busy} onClick={() => void detachWorkspace()}>
                Detach
              </button>
            ) : null}
          </div>
        </nav>

        <div className="zn-sidebar-footer">
          <button className="zn-nav-button" type="button" onClick={openSettings}>
            <GearSix size={16} />
            <span>Settings</span>
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
                {residentHealth === 'live' ? 'Ready' : residentHealth === 'connecting' ? 'Connecting' : 'Offline'}
              </div>
            </div>
          </div>

          <div className="zn-topbar-copy">
            <div className="zn-topbar-title">{view === 'settings' ? 'Settings' : activeThread?.title || 'New work'}</div>
            <div className="zn-muted zn-small">{view === 'settings' ? 'ZN on this computer' : activeWorkspace?.name || 'This computer'}</div>
          </div>

          <div className="zn-topbar-actions">
            <button type="button" aria-label="Open recent work" title="Recent work" onClick={() => requestWindowMode('expanded')}>
              <ClockCounterClockwise size={17} />
            </button>
            <button type="button" aria-label="Open work details" title="Details" disabled={!activeThread} onClick={openDetails}>
              <SidebarSimple size={17} />
            </button>
            <button type="button" aria-label="Open Settings" title="Settings" onClick={openSettings}>
              <GearSix size={17} />
            </button>
            <button
              type="button"
              aria-label={windowMode === 'compact' ? 'Expand ZN' : 'Compact ZN'}
              title={windowMode === 'compact' ? 'Expand' : 'Compact'}
              onClick={toggleWindowMode}
            >
              {windowMode === 'compact' ? <ArrowsOutSimple size={17} /> : <ArrowsInSimple size={17} />}
            </button>
          </div>
        </header>

        {view === 'settings' ? (
          <main className="zn-settings">
            <div className="zn-page-intro">
              <span className="zn-eyebrow">ZN desktop</span>
              <h1>Settings</h1>
              <p>Settings apply to ZN on this device. Provider secrets stay behind ZN's secure credential boundary and are never returned to this renderer.</p>
            </div>
            <div className="zn-settings-grid">
              <section className="zn-card">
                <h2>Background service</h2>
                <p className="zn-muted">ZN stays available when this window closes, so longer work can continue and reconnect here later.</p>
                <button type="button" onClick={() => void refreshResident()}>Refresh status</button>
                {residentError ? <div className="zn-error-text">{residentError}</div> : null}
                <details>
                  <summary className="zn-muted zn-small">Technical details</summary>
                  <pre className="zn-compact-pre">{residentSnapshot ? renderUnknown(residentSnapshot) : 'Waiting for ZN...'}</pre>
                </details>
              </section>

              <section className="zn-card">
                <h2>Models & providers</h2>
                <p className="zn-muted">Choose cognition resources for open-ended reasoning without changing ZN's identity, Work ownership, or execution authority. Local and deterministic Resident paths remain available when cognition is not configured.</p>
                {providerSettings && !providerSettings.editable ? (
                  <>
                    <div className="zn-setting-state">
                      Advanced {providerSettings.mode} configuration is active
                      {providerSettings.routeCount ? ' · ' + providerSettings.routeCount + ' routes' : ''}.
                    </div>
                    <p className="zn-muted zn-small">The simple editor will not overwrite advanced model routing configuration.</p>
                  </>
                ) : (
                  <form onSubmit={saveProvider}>
                    <div className="zn-context-title">Provider</div>
                    <input className="zn-search" aria-label="Model provider" value={providerName} disabled={providerBusy} onChange={event => setProviderName(event.target.value)} placeholder="openai, anthropic, gemini, ollama..." />
                    <div className="zn-context-title zn-context-title-spaced">Model</div>
                    <input className="zn-search" aria-label="Provider model" value={providerModel} disabled={providerBusy} onChange={event => setProviderModel(event.target.value)} placeholder="Model ID" />
                    <div className="zn-context-title zn-context-title-spaced">Base URL</div>
                    <input className="zn-search" aria-label="Provider base URL" value={providerBaseUrl} disabled={providerBusy} onChange={event => setProviderBaseUrl(event.target.value)} placeholder="Optional custom endpoint" />
                    <div className="zn-context-title zn-context-title-spaced">Credential</div>
                    <input className="zn-search" aria-label="Provider API key" type="password" autoComplete="new-password" value={providerApiKey} disabled={providerBusy} onChange={event => setProviderApiKey(event.target.value)} placeholder={providerSettings?.credential.configured ? 'Leave blank to keep current credential' : 'Optional for local/env-configured providers'} />
                    <p className="zn-muted zn-small">{credentialLabel(providerSettings)}</p>
                    {providerSettings ? <p className="zn-muted zn-small">Secure store: {providerSettings.credential.secureStore.available ? 'available' : 'unavailable'} · {providerSettings.credential.secureStore.backend}</p> : null}
                    {providerSettings?.configurationError ? <div className="zn-error-text">{providerSettings.configurationError}</div> : null}
                    {providerNotice ? <div className="zn-setting-state">{providerNotice}</div> : null}
                    <div className="zn-inline-actions zn-settings-actions">
                      <button className="zn-primary" type="submit" disabled={providerBusy || !providerName.trim() || !providerModel.trim()}>{providerBusy ? 'Applying...' : 'Save provider'}</button>
                      {showClearCredential ? <button type="button" disabled={providerBusy} onClick={() => void clearProviderCredential()}>Clear credential</button> : null}
                      <button type="button" disabled={providerBusy} onClick={() => void refreshProviderSettings()}>Refresh</button>
                    </div>
                  </form>
                )}
              </section>

              <section className="zn-card">
                <h2>Updates</h2>
                <p className="zn-muted">Check the ZN stable channel without source-repository credentials.</p>
                <div className="zn-inline-actions">
                  <button type="button" disabled={updateBusy} onClick={() => void checkUpdates()}>{updateBusy ? 'Checking...' : 'Check for updates'}</button>
                  {updateStatus?.updateAvailable ? <button className="zn-primary" type="button" disabled={updateBusy} onClick={() => void applyUpdate()}>Apply {updateStatus.availableVersion || 'update'}</button> : null}
                </div>
                {updateStatus ? <pre className="zn-compact-pre">{renderUnknown(updateStatus)}</pre> : null}
              </section>
            </div>
          </main>
        ) : (
          <>
            <main className="zn-thread-surface">
              {deepLinkNotice ? (
                <div className="zn-notice">
                  <strong>Deep link received.</strong> Nothing was executed automatically.
                  <button type="button" onClick={() => setDeepLinkNotice(null)}>Dismiss</button>
                </div>
              ) : null}

              {activeThread && activeThread.messages.length === 0 && !showActiveWork ? (
                <section className="zn-home">
                  <div className="zn-home-hero">
                    <span className="zn-home-orbit"><Sparkle size={18} weight="fill" /></span>
                    <span className="zn-eyebrow">Resident assistant</span>
                    <h1>What do you want to do?</h1>
                    <p>Tell ZN the outcome. Clear computer actions stay local when a deterministic path exists; harder work can use cognition resources when needed.</p>
                  </div>

                  <div className="zn-home-quick-starts" aria-label="Quick starts">
                    {ZN_HOME_QUICK_STARTS.map((action, index) => (
                      <button key={action.label} type="button" onClick={() => chooseHomePrompt(action.prompt)}>
                        {index === 0 ? <Desktop size={17} /> : index === 1 ? <FileText size={17} /> : <Brain size={17} />}
                        <span>{action.label}</span>
                      </button>
                    ))}
                    {activeWorkspace ? (
                      <button type="button" onClick={() => chooseHomePrompt('Review the files in this workspace and tell me what needs attention.')}>
                        <FolderSimple size={17} />
                        <span>Review workspace</span>
                      </button>
                    ) : (
                      <button type="button" disabled={workspaceBusy || busy || !activeThread} onClick={() => void attachWorkspace()}>
                        <FolderSimple size={17} />
                        <span>{workspaceBusy ? 'Attaching...' : 'Attach a folder'}</span>
                      </button>
                    )}
                  </div>

                  <div className="zn-home-status" aria-label="ZN readiness">
                    <span><i className={'zn-health-dot ' + residentHealth} />{residentHealth === 'live' ? 'Resident ready' : residentHealth === 'connecting' ? 'Resident connecting' : 'Resident offline'}</span>
                    <span>{activeWorkspace ? 'Workspace · ' + activeWorkspace.name : 'This computer'}</span>
                    <span title={providerReadiness.detail}>{providerReadiness.ready ? 'Cognition available' : 'Cognition setup needed'}</span>
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
                        <div className="zn-message-label">{message.role === 'user' ? 'You' : message.role === 'zn' ? 'ZN' : 'Activity'}</div>
                        <div className="zn-message-body">{message.text}</div>
                        {executionEvidence ? (
                          <div className="zn-execution-evidence" aria-label="Execution evidence">
                            <span>{executionPathLabel(executionEvidence.executionPath)}</span>
                            <span>{executionEvidence.modelInvocations} model {executionEvidence.modelInvocations === 1 ? 'call' : 'calls'}</span>
                          </div>
                        ) : null}
                        {message.detail ? (
                          executionEvidence ? (
                            <details className="zn-activity-technical">
                              <summary>Technical details</summary>
                              <pre className="zn-activity-detail">{renderUnknown(message.detail)}</pre>
                            </details>
                          ) : <pre className="zn-activity-detail">{renderUnknown(message.detail)}</pre>
                        ) : null}
                      </article>
                    )
                  })}
                </div>
              ) : null}

              {showActiveWork && workProgress ? (
                <section className="zn-current-work" aria-live="polite">
                  <div className="zn-current-work-head">
                    <span className="zn-current-work-icon"><Pulse size={19} weight="bold" /></span>
                    <div className="zn-current-work-copy">
                      <div className="zn-eyebrow">Resident progress · {workProgress.status}</div>
                      <h2>{activeThread?.title || 'Working on it'}</h2>
                      <p>{workProgress.stage} · {workProgress.nextAction || 'continuing work'}</p>
                    </div>
                    {workProgress.recovery?.replayBlocked ? (
                      <button className="zn-stop-button" type="button" disabled={cancelBusy} onClick={() => void cancelCurrentWork()}>
                        <Stop size={15} weight="fill" />
                        <span>{cancelBusy ? 'Stopping...' : 'Stop work'}</span>
                      </button>
                    ) : null}
                  </div>

                  <div className="zn-work-steps" aria-label="Current work status">
                    <div className="done"><CheckCircle size={17} weight="fill" /><span>Accepted by ZN</span></div>
                    <div className="active"><CircleNotch className="zn-spin" size={17} /><span>{workProgress.stage}</span></div>
                    <div><CheckCircle size={17} /><span>Verify result</span></div>
                  </div>

                  {workProgress.delegation ? (
                    <div className="zn-work-detail" aria-label="Delegated work progress">
                      <div><strong>Delegated work</strong> · {workProgress.delegation.status}</div>
                      {workProgress.delegation.phases.map((phase, index) => (
                        <div key={phase.kind + '-' + phase.status + '-' + (phase.updatedAt || 0) + '-' + index}>
                          {delegatedStatusMarker(phase.status)} {delegatedKindLabel(phase.kind)} · {delegatedStageLabel(phase.stage)}
                        </div>
                      ))}
                    </div>
                  ) : null}

                  {workProgress.recovery?.replayBlocked ? (
                    <div className="zn-recovery-warning">
                      <strong>Outside-world effect is uncertain.</strong>
                      <span>ZN will not replay this action automatically.</span>
                      {workProgress.recovery.reason ? <span>{workProgress.recovery.reason}</span> : null}
                    </div>
                  ) : null}

                  <details className="zn-progress-technical">
                    <summary>What ZN is doing</summary>
                    {workProgress.thought ? (
                      <div className="zn-muted zn-small">
                        {workProgress.thought.action || workProgress.thought.focus}
                        {workProgress.thought.reason ? ' — ' + workProgress.thought.reason : ''}
                      </div>
                    ) : null}
                    {workProgress.investigation ? (
                      <div className="zn-muted zn-small">
                        Investigation round {workProgress.investigation.rounds} · {workProgress.investigation.status}
                        {workProgress.investigation.nextProbe ? ' · next: ' + workProgress.investigation.nextProbe : ''}
                      </div>
                    ) : null}
                    {workProgress.bodyActions.length > 0 ? (
                      <div className="zn-work-detail">
                        {workProgress.bodyActions.map((action, index) => (
                          <div key={action.at + '-' + action.kind + '-' + index}>
                            {action.kind} · {action.success ? 'ok' : 'failed'}{action.summary ? ' · ' + action.summary : ''}
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </details>

                  <div className="zn-current-work-actions">
                    <button type="button" onClick={openDetails}>View details</button>
                    <span>Updated {timeLabel(workProgress.updatedAt)}</span>
                  </div>
                </section>
              ) : null}

              {!showActiveWork && firstResult ? (
                <section className="zn-result-summary">
                  <span className="zn-result-icon"><CheckCircle size={22} weight="fill" /></span>
                  <div className="zn-result-copy">
                    <span className="zn-eyebrow">Work result</span>
                    <strong>{firstResult.name}</strong>
                    <span>{activeArtifacts.length === 1 ? 'Result is ready.' : activeArtifacts.length + ' results are ready.'}</span>
                  </div>
                  <button type="button" onClick={openDetails}>View results</button>
                </section>
              ) : null}
            </main>

            <form className="zn-composer-wrap" onSubmit={submit}>
              <div className="zn-composer">
                <button
                  className="zn-composer-tool"
                  type="button"
                  aria-label={activeWorkspace ? 'Change attached folder' : 'Attach folder'}
                  title={activeWorkspace ? 'Change folder' : 'Attach folder'}
                  disabled={workspaceBusy || busy || !activeThread}
                  onClick={() => void attachWorkspace()}
                >
                  <Paperclip size={18} />
                </button>
                <textarea
                  aria-label="Message ZN"
                  placeholder="Tell ZN what you want to do..."
                  rows={1}
                  value={draft}
                  onChange={event => setDraft(event.target.value)}
                  onKeyDown={event => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault()
                      event.currentTarget.form?.requestSubmit()
                    }
                  }}
                />
                <button className="zn-send" type="submit" aria-label="Send to ZN" disabled={busy || !draft.trim()}>
                  {busy ? <CircleNotch className="zn-spin" size={18} /> : <ArrowUp size={19} weight="bold" />}
                </button>
              </div>
              <div className="zn-composer-caption">
                {activeWorkspace ? activeWorkspace.name + ' · ' : ''}{busy ? 'ZN can keep working in the background · ' : ''}Enter to send · Shift+Enter for newline
              </div>
            </form>
          </>
        )}
      </section>

      {contextOpen ? <button className="zn-details-backdrop" type="button" aria-label="Close work details" onClick={() => setContextOpen(false)} /> : null}

      {contextOpen ? (
        <aside className="zn-context-panel" aria-label="Work details">
          <div className="zn-context-header">
            <div>
              <div className="zn-section-label">Details</div>
              <strong>{selectedArtifact ? artifactKindLabel(selectedArtifact.kind) : 'Current work'}</strong>
            </div>
            <button type="button" aria-label="Close context panel" onClick={() => setContextOpen(false)}>
              <X size={18} />
            </button>
          </div>

          <section className="zn-context-section">
            <div className="zn-context-title">Workspace</div>
            {activeWorkspace ? (
              <>
                <div className="zn-context-value"><FolderSimple size={16} />{activeWorkspace.name}</div>
                <div className="zn-context-path" title={activeWorkspace.path}>{activeWorkspace.path}</div>
                <div className="zn-inline-actions zn-context-actions">
                  <button type="button" disabled={workspaceBusy || busy} onClick={() => void attachWorkspace()}>Change</button>
                  <button type="button" disabled={workspaceBusy || busy} onClick={() => void detachWorkspace()}>Detach</button>
                </div>
              </>
            ) : (
              <>
                <p className="zn-muted zn-small">No local folder is attached to this work.</p>
                <div className="zn-context-actions">
                  <button type="button" disabled={workspaceBusy || busy || !activeThread} onClick={() => void attachWorkspace()}>Attach folder</button>
                </div>
              </>
            )}
          </section>

          {activeArtifacts.length > 0 ? (
            <section className="zn-context-section zn-context-grow zn-artifact-section">
              <div className="zn-context-title">Results</div>
              <div className="zn-artifact-list" aria-label="Work artifacts">
                {activeArtifacts.map(artifact => (
                  <button className={'zn-artifact-link' + (artifact.id === selectedArtifact?.id ? ' active' : '')} key={artifact.id} type="button" onClick={() => setSelectedArtifactId(artifact.id)}>
                    <span className="zn-artifact-icon"><FileText size={15} /></span>
                    <span className="zn-artifact-copy">
                      <span className="zn-artifact-kind">{artifactKindLabel(artifact.kind)}</span>
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
                  <pre>{selectedArtifact.content || 'No textual preview available.'}</pre>
                  {selectedArtifact.metadata?.truncated ? <div className="zn-artifact-note">Preview is bounded; content was truncated.</div> : null}
                </div>
              ) : null}
            </section>
          ) : (
            <section className="zn-context-section">
              <div className="zn-context-title">Results</div>
              <p className="zn-muted zn-small">Relevant files, diffs and terminal output will appear here when this task produces them.</p>
            </section>
          )}

          <section className="zn-context-section">
            <div className="zn-context-title">Resident status</div>
            <div className="zn-context-value">
              <span className={'zn-health-dot ' + residentHealth} />
              {residentHealth === 'live' ? 'Ready' : residentHealth === 'connecting' ? 'Connecting' : 'Offline'}
            </div>
            {residentError ? <div className="zn-error-text">{residentError}</div> : null}
          </section>

          <section className="zn-context-section">
            <div className="zn-context-section-head">
              <div className="zn-context-title">Restore points</div>
              <button type="button" disabled={restoreBusy || !activeThread} onClick={() => activeThread && void refreshRestorePoints(activeThread.id)}>
                {restoreBusy ? 'Checking...' : 'Refresh'}
              </button>
            </div>
            {activeRestorePoints === undefined ? (
              <p className="zn-muted zn-small">Open a Work or refresh to inspect retained restore points against current file reality.</p>
            ) : activeRestorePoints.length === 0 ? (
              <p className="zn-muted zn-small">No retained restore points for this Work.</p>
            ) : (
              <div className="zn-restore-list" aria-label="Work restore points">
                {activeRestorePoints.map(point => (
                  <div className="zn-restore-row" key={point.id}>
                    <div className="zn-restore-row-head">
                      <span>{restorePointStatusLabel(point.currentStatus)}</span>
                      <span>{timeLabel(point.currentObservedAt)}</span>
                    </div>
                    <strong title={point.targetPath}>{point.targetPath}</strong>
                    <span className="zn-muted zn-small">Retained {point.sizeBytes} bytes</span>
                    {point.proposal ? (
                      <span className="zn-muted zn-small">{restoreProposalStatusLabel(point.proposal.status)} · user approval and fresh revalidation would be required</span>
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
            <p className="zn-muted zn-small">Changed, unchanged and unsafe targets remain inspection-only. Missing-target restore requires explicit preparation and approval with fresh resident revalidation.</p>
          </section>
        </aside>
      ) : null}
    </div>
  )
}
