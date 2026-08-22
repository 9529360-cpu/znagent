import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'

import {
  applyZnUpdate,
  checkZnUpdate,
  loadZnResidentSnapshot,
  submitZnTask,
  type ZnResidentSnapshot
} from './resident-client'
import {
  addZnThreadMessage,
  loadZnThreadCache,
  newZnThread,
  saveZnThreadCache,
  type ZnThread
} from './state'

type ResidentHealth = 'connecting' | 'live' | 'offline'
type MainView = 'work' | 'settings'

type NormalizedRun = {
  text: string
  activity: Record<string, unknown>
  failed: boolean
}

function renderUnknown(value: unknown): string {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function normalizeRun(value: unknown): NormalizedRun {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return { text: renderUnknown(value), activity: {}, failed: false }
  }

  const record = value as Record<string, unknown>
  const text = String(
    record.response ||
      record.content ||
      record.error ||
      record.reason ||
      (record.success === false ? 'The resident could not complete this event.' : 'Completed.')
  )
  const activity: Record<string, unknown> = {}
  for (const key of ['execution_path', 'model_invocations', 'capability_name', 'reason', 'event_id']) {
    if (record[key] !== undefined && record[key] !== null && record[key] !== '') activity[key] = record[key]
  }
  return { text, activity, failed: record.success === false }
}

function timeLabel(value: number): string {
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

export function ZnWorkbench() {
  const [threads, setThreads] = useState<ZnThread[]>(() => {
    const cached = loadZnThreadCache()
    return cached.length > 0 ? cached : [newZnThread()]
  })
  const [activeThreadId, setActiveThreadId] = useState(() => threads[0]?.id || '')
  const [view, setView] = useState<MainView>('work')
  const [query, setQuery] = useState('')
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [contextOpen, setContextOpen] = useState(true)
  const [residentHealth, setResidentHealth] = useState<ResidentHealth>('connecting')
  const [residentSnapshot, setResidentSnapshot] = useState<ZnResidentSnapshot | null>(null)
  const [residentError, setResidentError] = useState<string | null>(null)
  const [deepLinkNotice, setDeepLinkNotice] = useState<ZnDesktopDeepLink | null>(null)
  const [updateStatus, setUpdateStatus] = useState<ZnDesktopUpdateStatus | null>(null)
  const [updateBusy, setUpdateBusy] = useState(false)

  const activeThread = useMemo(
    () => threads.find(thread => thread.id === activeThreadId) || threads[0] || null,
    [activeThreadId, threads]
  )
  const recentThreads = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    return [...threads]
      .sort((left, right) => right.updatedAt - left.updatedAt)
      .filter(thread => !normalized || thread.title.toLowerCase().includes(normalized))
  }, [query, threads])

  useEffect(() => saveZnThreadCache(threads), [threads])

  const refreshResident = useCallback(async () => {
    setResidentHealth(previous => (previous === 'live' ? previous : 'connecting'))
    try {
      const snapshot = await loadZnResidentSnapshot()
      setResidentSnapshot(snapshot)
      setResidentError(null)
      setResidentHealth('live')
    } catch (error) {
      setResidentError(error instanceof Error ? error.message : String(error))
      setResidentHealth('offline')
    }
  }, [])

  useEffect(() => {
    void refreshResident()
    const timer = window.setInterval(() => void refreshResident(), 12_000)
    return () => window.clearInterval(timer)
  }, [refreshResident])

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
    setView('work')
    setDraft('')
  }, [])

  const submit = useCallback(
    async (event: FormEvent) => {
      event.preventDefault()
      const task = draft.trim()
      if (!task || busy || !activeThread) return

      const threadId = activeThread.id
      setDraft('')
      setBusy(true)
      setThreads(current =>
        current.map(thread =>
          thread.id === threadId ? addZnThreadMessage(thread, 'user', task) : thread
        )
      )

      try {
        const raw = await submitZnTask(task)
        const run = normalizeRun(raw)
        setThreads(current =>
          current.map(thread => {
            if (thread.id !== threadId) return thread
            let next = addZnThreadMessage(
              thread,
              'zn',
              run.text,
              run.failed ? { failed: true } : undefined
            )
            if (Object.keys(run.activity).length > 0) {
              next = addZnThreadMessage(next, 'activity', 'Resident activity', run.activity)
            }
            return next
          })
        )
        void refreshResident()
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        setThreads(current =>
          current.map(thread =>
            thread.id === threadId
              ? addZnThreadMessage(thread, 'zn', message, { failed: true })
              : thread
          )
        )
      } finally {
        setBusy(false)
      }
    },
    [activeThread, busy, draft, refreshResident]
  )

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

  return (
    <div className={`zn-app${contextOpen ? '' : ' context-closed'}`}>
      <aside className="zn-sidebar">
        <div className="zn-brand-row">
          <div className="zn-mark">ZN</div>
          <div>
            <div className="zn-brand">ZN</div>
            <div className="zn-muted zn-small">resident workbench</div>
          </div>
        </div>

        <button className="zn-primary zn-new-work" type="button" onClick={openNewWork}>
          + New work
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
            <div>
              <div>Local work</div>
              <div className="zn-muted zn-small">No folder attached</div>
            </div>
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
            <div className="zn-muted zn-small">Local work</div>
          </div>
          <button className="zn-resident-pill" type="button" onClick={() => void refreshResident()}>
            <span className={`zn-health-dot ${residentHealth}`} />
            {residentHealth === 'live' ? 'resident live' : residentHealth}
          </button>
        </header>

        {view === 'settings' ? (
          <main className="zn-settings">
            <div className="zn-page-intro">
              <span className="zn-eyebrow">ZN desktop</span>
              <h1>Settings</h1>
              <p>
                Product settings belong to ZN. Provider credential editing will connect to the ZN config boundary rather than an inherited desktop backend.
              </p>
            </div>
            <div className="zn-settings-grid">
              <section className="zn-card">
                <h2>Resident</h2>
                <p className="zn-muted">
                  The resident outlives this window. Reconnect or inspect the current runtime without creating another identity.
                </p>
                <button type="button" onClick={() => void refreshResident()}>Refresh resident</button>
                {residentError ? <div className="zn-error-text">{residentError}</div> : null}
              </section>
              <section className="zn-card">
                <h2>Models & providers</h2>
                <p className="zn-muted">
                  External models remain bounded cognitive resources. Editable provider and credential controls will use the ZN-owned configuration store.
                </p>
                <div className="zn-setting-state">Provider editor not connected yet</div>
              </section>
              <section className="zn-card">
                <h2>Updates</h2>
                <p className="zn-muted">Check the ZN stable channel without source-repository credentials.</p>
                <div className="zn-inline-actions">
                  <button type="button" disabled={updateBusy} onClick={() => void checkUpdates()}>
                    {updateBusy ? 'Checking…' : 'Check for updates'}
                  </button>
                  {updateStatus?.updateAvailable ? (
                    <button
                      className="zn-primary"
                      type="button"
                      disabled={updateBusy}
                      onClick={() => void applyUpdate()}
                    >
                      Apply {updateStatus.availableVersion || 'update'}
                    </button>
                  ) : null}
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

              {activeThread && activeThread.messages.length > 0 ? (
                <div className="zn-messages">
                  {activeThread.messages.map(message => (
                    <article className={`zn-message ${message.role}`} key={message.id}>
                      <div className="zn-message-label">
                        {message.role === 'user' ? 'You' : message.role === 'zn' ? 'ZN' : 'Activity'}
                      </div>
                      <div className="zn-message-body">{message.text}</div>
                      {message.detail ? (
                        <pre className="zn-activity-detail">{renderUnknown(message.detail)}</pre>
                      ) : null}
                    </article>
                  ))}
                </div>
              ) : (
                <div className="zn-empty-thread">
                  <span className="zn-eyebrow">Persistent resident</span>
                  <h1>What should ZN attend to?</h1>
                  <p>
                    Work enters the resident's own event loop. Models may assist when needed, but they do not own this thread or ZN's continuity.
                  </p>
                </div>
              )}
            </main>

            <form className="zn-composer-wrap" onSubmit={submit}>
              <div className="zn-composer">
                <textarea
                  aria-label="Message ZN"
                  placeholder="Message ZN"
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
                <button className="zn-send" type="submit" disabled={busy || !draft.trim()}>
                  {busy ? '…' : '↑'}
                </button>
              </div>
              <div className="zn-composer-caption">Enter to send · Shift+Enter for newline</div>
            </form>
          </>
        )}
      </section>

      {contextOpen ? (
        <aside className="zn-context-panel">
          <div className="zn-context-header">
            <div>
              <div className="zn-section-label">Context</div>
              <strong>Resident</strong>
            </div>
            <button type="button" aria-label="Close context panel" onClick={() => setContextOpen(false)}>×</button>
          </div>
          <section className="zn-context-section">
            <div className="zn-context-title">Runtime health</div>
            <div className="zn-context-value">
              <span className={`zn-health-dot ${residentHealth}`} />
              {residentHealth}
            </div>
            {residentError ? <div className="zn-error-text">{residentError}</div> : null}
          </section>
          <section className="zn-context-section zn-context-grow">
            <div className="zn-context-title">Current resident state</div>
            <pre>{residentSnapshot ? renderUnknown(residentSnapshot) : 'Waiting for resident…'}</pre>
          </section>
          <section className="zn-context-section">
            <div className="zn-context-title">Artifacts</div>
            <p className="zn-muted zn-small">Artifacts appear here contextually when work produces them.</p>
          </section>
        </aside>
      ) : null}
    </div>
  )
}
