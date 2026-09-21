import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'

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
  const [contextOpen, setContextOpen] = useState(true)
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
            setContextOpen(true)
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
  const showProviderGuidance = providerSettings !== null && !providerSettings.cognitionAvailable
  const chooseHomePrompt = (prompt: string) => {
    setDraft(prompt)
    window.requestAnimationFrame(() => {
      const composer = document.querySelector<HTMLTextAreaElement>('.zn-composer textarea')
      composer?.focus()
      composer?.setSelectionRange(composer.value.length, composer.value.length)
    })
  }

  return (
    <div className={`zn-app${contextOpen ? '' : ' context-closed'}`}>
      <aside className="zn-sidebar">
        <div className="zn-brand-row">
          <div className="zn-mark">ZN</div>
          <div>
            <div className="zn-brand">ZN</div>
            <div className="zn-muted zn-small">your ideas, further.</div>
          </div>
        </div>

        <button className="zn-primary zn-new-work" type="button" onClick={openNewWork}>
          + New task
        </button>
        <input
          className="zn-search"
          aria-label="Search recent work"
          placeholder="Search"
          value={query}
          onChange={event => setQuery(event.target.value)}
        />

        <nav className="zn-nav" aria-label="Recent work">
          <div className="zn-section-label">Recent</div>
          <div className="zn-thread-list">
            {recentThreads.map(thread => (
              <button
                className={`zn-thread-link${thread.id === activeThread?.id && view === 'work' ? ' active' : ''}`}
                key={thread.id}
                type="button"
                onClick={() => {
                  setActiveThreadId(thread.id)
                  setView('work')
                  setContextOpen(true)
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
            <span className="zn-workspace-dot" />
            <div className="zn-workspace-copy">
              <div>{activeWorkspace?.name || 'Local work'}</div>
              <div
                className="zn-muted zn-small zn-workspace-path"
                title={activeWorkspace?.path}
              >
                {activeWorkspace?.path || 'No folder attached'}
              </div>
            </div>
          </div>
          <div className="zn-workspace-actions">
            <button type="button" disabled={workspaceBusy || busy || !activeThread} onClick={() => void attachWorkspace()}>
              {workspaceBusy ? 'Working…' : activeWorkspace ? 'Change folder' : 'Attach folder'}
            </button>
            {activeWorkspace ? (
              <button type="button" disabled={workspaceBusy || busy} onClick={() => void detachWorkspace()}>
                Detach
              </button>
            ) : null}
          </div>
        </nav>

        <div className="zn-sidebar-footer">
          <button
            className={`zn-nav-button${view === 'settings' ? ' active' : ''}`}
            type="button"
            onClick={() => setView('settings')}
          >
            Settings
          </button>
          <button className="zn-nav-button" type="button" onClick={() => setContextOpen(value => !value)}>
            {contextOpen ? 'Hide context' : 'Show context'}
          </button>
        </div>
      </aside>

      <section className="zn-main-column">
        <header className="zn-topbar">
          <div>
            <div className="zn-topbar-title">
              {view === 'settings' ? 'Settings' : activeThread?.title || 'New work'}
            </div>
            <div className="zn-muted zn-small">
              {view === 'settings' ? 'ZN desktop' : activeWorkspace?.name || 'Local work'}
            </div>
          </div>
          <button className="zn-resident-pill" type="button" onClick={() => void refreshResident()}>
            <span className={`zn-health-dot ${residentHealth}`} />
            {residentHealth === 'live' ? 'ZN ready' : residentHealth === 'connecting' ? 'Connecting' : 'Offline'}
          </button>
        </header>

        {view === 'settings' ? (
          <main className="zn-settings">
            <div className="zn-page-intro">
              <span className="zn-eyebrow">ZN desktop</span>
              <h1>Settings</h1>
              <p>
                Settings apply to ZN on this device. Provider secrets stay behind ZN's secure credential boundary and are never returned to this renderer.
              </p>
            </div>
            <div className="zn-settings-grid">
              <section className="zn-card">
                <h2>Background service</h2>
                <p className="zn-muted">
                  ZN can stay available when this window closes, so longer tasks can continue and reconnect here later.
                </p>
                <button type="button" onClick={() => void refreshResident()}>Refresh status</button>
                {residentError ? <div className="zn-error-text">{residentError}</div> : null}
                <details>
                  <summary className="zn-muted zn-small">Technical details</summary>
                  <pre className="zn-compact-pre">{residentSnapshot ? renderUnknown(residentSnapshot) : 'Waiting for ZN…'}</pre>
                </details>
              </section>
              <section className="zn-card">
                <h2>Models & providers</h2>
                <p className="zn-muted">
                  Choose the model connection ZN can use for open-ended reasoning. Saving here applies the connection without replacing ZN's identity or history.
                </p>
                {providerSettings && !providerSettings.editable ? (
                  <>
                    <div className="zn-setting-state">
                      Advanced {providerSettings.mode} configuration is active
                      {providerSettings.routeCount ? ` · ${providerSettings.routeCount} routes` : ''}.
                    </div>
                    <p className="zn-muted zn-small">
                      The simple editor will not overwrite advanced model routing configuration.
                    </p>
                  </>
                ) : (
                  <form onSubmit={saveProvider}>
                    <div className="zn-context-title">Provider</div>
                    <input className="zn-search" aria-label="Model provider" value={providerName} disabled={providerBusy} onChange={event => setProviderName(event.target.value)} placeholder="openai, anthropic, gemini, ollama…" />
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
                    <div className="zn-inline-actions" style={{ marginTop: 12 }}>
                      <button className="zn-primary" type="submit" disabled={providerBusy || !providerName.trim() || !providerModel.trim()}>{providerBusy ? 'Applying…' : 'Save provider'}</button>
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
                  <button type="button" disabled={updateBusy} onClick={() => void checkUpdates()}>{updateBusy ? 'Checking…' : 'Check for updates'}</button>
                  {updateStatus?.updateAvailable ? <button className="zn-primary" type="button" disabled={updateBusy} onClick={() => void applyUpdate()}>Apply {updateStatus.availableVersion || 'update'}</button> : null}
                </div>
                {updateStatus ? <pre className="zn-compact-pre">{renderUnknown(updateStatus)}</pre> : null}
              </section>
            </div>
          </main>
        ) : (
          <>
            <main className="zn-thread-surface">
              {showProviderGuidance ? (
                <div className="zn-notice" role="status">
                  <strong>{providerReadiness.headline}.</strong> {providerReadiness.detail}
                  <div className="zn-muted zn-small">
                    Open-ended model-backed reasoning needs a working provider and model. Local and deterministic Resident paths remain available.
                  </div>
                  <button type="button" onClick={() => setView('settings')}>Open Settings</button>
                </div>
              ) : null}
              {deepLinkNotice ? <div className="zn-notice"><strong>Deep link received.</strong> Nothing was executed automatically.<button type="button" onClick={() => setDeepLinkNotice(null)}>Dismiss</button></div> : null}

              {activeThread && activeThread.messages.length > 0 ? (
                <div className="zn-messages">
                  {activeThread.messages.map(message => (
                    <article className={`zn-message ${message.role}`} key={message.id}>
                      <div className="zn-message-label">{message.role === 'user' ? 'You' : message.role === 'zn' ? 'ZN' : 'Activity'}</div>
                      <div className="zn-message-body">{message.text}</div>
                      {message.detail ? <pre className="zn-activity-detail">{renderUnknown(message.detail)}</pre> : null}
                    </article>
                  ))}
                  {workProgress && workProgress.threadId === activeThread.id && !workProgress.finalized ? (
                    <article className="zn-message activity" aria-live="polite">
                      <div className="zn-message-label">Resident progress · {workProgress.status}</div>
                      <div className="zn-message-body">{workProgress.stage} · {workProgress.nextAction || 'continuing work'}</div>
                      {workProgress.delegation ? (
                        <div className="zn-activity-detail" aria-label="Delegated work progress">
                          <div><strong>Delegated work</strong> · {workProgress.delegation.status}</div>
                          {workProgress.delegation.phases.map((phase, index) => (
                            <div key={`${phase.kind}-${phase.status}-${phase.updatedAt || 0}-${index}`}>
                              {delegatedStatusMarker(phase.status)} {delegatedKindLabel(phase.kind)} · {delegatedStageLabel(phase.stage)}
                            </div>
                          ))}
                        </div>
                      ) : null}
                      {workProgress.recovery?.replayBlocked ? (
                        <div className="zn-notice">
                          <strong>Outside-world effect is uncertain.</strong> ZN will not replay this action automatically. Stopping this Work prevents further ZN action, but it cannot undo or prove what already happened outside ZN.
                          {workProgress.recovery.reason ? <div className="zn-muted zn-small">{workProgress.recovery.reason}</div> : null}
                          <button type="button" disabled={cancelBusy} onClick={() => void cancelCurrentWork()}>
                            {cancelBusy ? 'Stopping…' : 'Stop work'}
                          </button>
                        </div>
                      ) : null}
                      {workProgress.thought ? (
                        <div className="zn-muted zn-small">
                          {workProgress.thought.action || workProgress.thought.focus}
                          {workProgress.thought.reason ? ` — ${workProgress.thought.reason}` : ''}
                        </div>
                      ) : null}
                      {workProgress.investigation ? (
                        <div className="zn-muted zn-small">
                          Investigation round {workProgress.investigation.rounds} · {workProgress.investigation.status}
                          {workProgress.investigation.nextProbe ? ` · next: ${workProgress.investigation.nextProbe}` : ''}
                        </div>
                      ) : null}
                      {workProgress.bodyActions.length > 0 ? (
                        <div className="zn-activity-detail">
                          {workProgress.bodyActions.map((action, index) => (
                            <div key={`${action.at}-${action.kind}-${index}`}>
                              {action.kind} · {action.success ? 'ok' : 'failed'}{action.summary ? ` · ${action.summary}` : ''}
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </article>
                  ) : null}
                </div>
              ) : (
                <div className="zn-empty-thread">
                  <span className="zn-eyebrow">ZN resident</span>
                  <h1>What should we work on?</h1>
                  <p>Start with a direct PC action or hand ZN a longer task. Clear system commands stay local when ZN has a deterministic path; open-ended work can use cognition resources when needed.</p>

                  <div className="zn-home-status" aria-label="ZN readiness">
                    <span><i className={`zn-health-dot ${residentHealth}`} />{residentHealth === 'live' ? 'Resident ready' : residentHealth === 'connecting' ? 'Resident connecting' : 'Resident offline'}</span>
                    <span>{activeWorkspace ? `Workspace · ${activeWorkspace.name}` : 'No workspace attached'}</span>
                    <span>{providerSettings?.cognitionAvailable ? 'Cognition available' : 'Local paths remain available'}</span>
                  </div>

                  <div className="zn-home-quick-starts" aria-label="Quick starts">
                    {ZN_HOME_QUICK_STARTS.map(action => (
                      <button key={action.label} type="button" onClick={() => chooseHomePrompt(action.prompt)}>
                        {action.label}
                      </button>
                    ))}
                    {activeWorkspace ? (
                      <button type="button" onClick={() => chooseHomePrompt('Review the files in this workspace and tell me what needs attention.')}>Review workspace</button>
                    ) : (
                      <button type="button" disabled={workspaceBusy || busy || !activeThread} onClick={() => void attachWorkspace()}>
                        {workspaceBusy ? 'Attaching…' : 'Attach a folder'}
                      </button>
                    )}
                  </div>

                  <div className="zn-home-capabilities" aria-label="Ways to work with ZN">
                    <article className="zn-home-card">
                      <span className="zn-home-card-kicker">PC</span>
                      <strong>Use this computer</strong>
                      <span>Open apps and act through ZN-owned Windows capabilities with verification.</span>
                    </article>
                    <article className="zn-home-card">
                      <span className="zn-home-card-kicker">WORK</span>
                      <strong>Keep work durable</strong>
                      <span>Attach local work, keep results visible, and reconnect to longer-running tasks later.</span>
                    </article>
                    <article className="zn-home-card">
                      <span className="zn-home-card-kicker">THINK</span>
                      <strong>Use models as resources</strong>
                      <span>Bring in model reasoning for ambiguous work without handing over ZN's execution authority.</span>
                    </article>
                  </div>
                </div>
              )}
            </main>

            <form className="zn-composer-wrap" onSubmit={submit}>
              <div className="zn-composer">
                <textarea aria-label="Message ZN" placeholder="Ask ZN to help with anything…" rows={1} value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit() } }} />
                <button className="zn-send" type="submit" disabled={busy || !draft.trim()}>{busy ? '…' : '↑'}</button>
              </div>
              <div className="zn-composer-caption">{activeWorkspace ? `${activeWorkspace.name} · ` : ''}{busy ? 'ZN can keep working in the background · ' : ''}Enter to send · Shift+Enter for newline</div>
            </form>
          </>
        )}
      </section>

      {contextOpen ? (
        <aside className="zn-context-panel">
          <div className="zn-context-header"><div><div className="zn-section-label">Context</div><strong>{selectedArtifact ? artifactKindLabel(selectedArtifact.kind) : 'Overview'}</strong></div><button type="button" aria-label="Close context panel" onClick={() => setContextOpen(false)}>×</button></div>
          <section className="zn-context-section">
            <div className="zn-context-title">Workspace</div>
            {activeWorkspace ? (
              <><div className="zn-context-value">{activeWorkspace.name}</div><div className="zn-context-path" title={activeWorkspace.path}>{activeWorkspace.path}</div><div className="zn-inline-actions zn-context-actions"><button type="button" disabled={workspaceBusy || busy} onClick={() => void attachWorkspace()}>Change</button><button type="button" disabled={workspaceBusy || busy} onClick={() => void detachWorkspace()}>Detach</button></div></>
            ) : (
              <><p className="zn-muted zn-small">No local folder is attached to this work.</p><div className="zn-context-actions"><button type="button" disabled={workspaceBusy || busy || !activeThread} onClick={() => void attachWorkspace()}>Attach folder</button></div></>
            )}
          </section>
          {activeArtifacts.length > 0 ? (
            <section className="zn-context-section zn-context-grow zn-artifact-section">
              <div className="zn-context-title">Results</div>
              <div className="zn-artifact-list" aria-label="Work artifacts">
                {activeArtifacts.map(artifact => <button className={`zn-artifact-link${artifact.id === selectedArtifact?.id ? ' active' : ''}`} key={artifact.id} type="button" onClick={() => setSelectedArtifactId(artifact.id)}><span className="zn-artifact-kind">{artifactKindLabel(artifact.kind)}</span><span className="zn-artifact-name">{artifact.name}</span></button>)}
              </div>
              {selectedArtifact ? <div className="zn-artifact-preview"><div className="zn-artifact-preview-head"><strong>{selectedArtifact.name}</strong>{selectedArtifact.path ? <span title={selectedArtifact.path}>{selectedArtifact.path}</span> : null}</div><pre>{selectedArtifact.content || 'No textual preview available.'}</pre>{selectedArtifact.metadata?.truncated ? <div className="zn-artifact-note">Preview is bounded; content was truncated.</div> : null}</div> : null}
            </section>
          ) : (
            <section className="zn-context-section">
              <div className="zn-context-title">Results</div>
              <p className="zn-muted zn-small">Relevant files, diffs and terminal output will appear here when this task produces them.</p>
            </section>
          )}
          <section className="zn-context-section"><div className="zn-context-title">Status</div><div className="zn-context-value"><span className={`zn-health-dot ${residentHealth}`} />{residentHealth === 'live' ? 'Ready' : residentHealth === 'connecting' ? 'Connecting' : 'Offline'}</div>{residentError ? <div className="zn-error-text">{residentError}</div> : null}</section>
          <section className="zn-context-section">
            <div className="zn-context-header">
              <div className="zn-context-title">Restore points</div>
              <button type="button" disabled={restoreBusy || !activeThread} onClick={() => activeThread && void refreshRestorePoints(activeThread.id)}>
                {restoreBusy ? 'Checking…' : 'Refresh'}
              </button>
            </div>
            {activeRestorePoints === undefined ? (
              <p className="zn-muted zn-small">Open a Work or refresh to inspect retained restore points against current file reality.</p>
            ) : activeRestorePoints.length === 0 ? (
              <p className="zn-muted zn-small">No retained restore points for this Work.</p>
            ) : (
              <div className="zn-artifact-list" aria-label="Work restore points">
                {activeRestorePoints.map(point => (
                  <div className="zn-artifact-link" key={point.id}>
                    <span className="zn-artifact-kind">{restorePointStatusLabel(point.currentStatus)}</span>
                    <span className="zn-artifact-name" title={point.targetPath}>{point.targetPath}</span>
                    <span className="zn-muted zn-small">Observed {timeLabel(point.currentObservedAt)} · retained {point.sizeBytes} bytes</span>
                    {point.proposal ? (
                      <span className="zn-muted zn-small">
                        {restoreProposalStatusLabel(point.proposal.status)} · user approval and fresh revalidation would be required
                      </span>
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
