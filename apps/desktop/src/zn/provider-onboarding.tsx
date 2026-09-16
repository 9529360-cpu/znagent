import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'

import {
  loadZnProviderSettings,
  updateZnProviderSettings,
  type ZnProviderSettings
} from './resident-client'
import {
  describeZnProviderReadiness,
  providerUpdateNotice
} from './provider-readiness'
import { ZnWorkbench } from './workbench'
import './provider-onboarding.css'

type OnboardingState = 'checking' | 'setup' | 'work'

export function ZnProviderOnboarding() {
  const [state, setState] = useState<OnboardingState>('checking')
  const [settings, setSettings] = useState<ZnProviderSettings | null>(null)
  const [provider, setProvider] = useState('openai')
  const [model, setModel] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const readiness = useMemo(() => describeZnProviderReadiness(settings), [settings])

  const applySettings = useCallback((next: ZnProviderSettings) => {
    setSettings(next)
    setProvider(next.provider && next.provider !== 'auto' ? next.provider : 'openai')
    setModel(next.model)
    setBaseUrl(next.baseUrl)
    setApiKey('')
  }, [])

  useEffect(() => {
    let active = true
    void loadZnProviderSettings()
      .then(next => {
        if (!active) return
        applySettings(next)
        setState(next.cognitionAvailable ? 'work' : 'setup')
      })
      .catch(error => {
        if (!active) return
        setNotice(error instanceof Error ? error.message : String(error))
        setState('setup')
      })
    return () => {
      active = false
    }
  }, [applySettings])

  const save = useCallback(async (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setNotice(null)
    try {
      const next = await updateZnProviderSettings({
        provider,
        model,
        baseUrl,
        ...(apiKey.trim() ? { apiKey } : {})
      })
      applySettings(next)
      setNotice(providerUpdateNotice(next))
      if (next.cognitionAvailable) setState('work')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }, [apiKey, applySettings, baseUrl, busy, model, provider])

  if (state === 'work') return <ZnWorkbench />

  const advancedUnavailable = settings?.editable === false

  return (
    <main className="zn-onboarding-shell">
      <section className="zn-onboarding-card" aria-live="polite">
        <div className="zn-mark">ZN</div>
        <span className="zn-eyebrow">Resident setup</span>
        <h1>{readiness.headline}</h1>
        <p className="zn-muted">{readiness.detail}</p>

        {state === 'checking' ? (
          <div className="zn-setting-state">Checking the resident's current model resources…</div>
        ) : advancedUnavailable ? (
          <>
            <div className="zn-setting-state">
              Advanced {settings?.mode || 'route'} configuration is active. The first-run editor will not overwrite it.
            </div>
            {notice ? <div className="zn-error-text">{notice}</div> : null}
            <div className="zn-inline-actions zn-onboarding-actions">
              <button className="zn-primary" type="button" onClick={() => setState('work')}>
                Open ZN
              </button>
            </div>
          </>
        ) : (
          <form onSubmit={save}>
            <label className="zn-context-title" htmlFor="zn-onboarding-provider">Provider</label>
            <input
              id="zn-onboarding-provider"
              className="zn-search"
              value={provider}
              disabled={busy}
              onChange={event => setProvider(event.target.value)}
              placeholder="openai, anthropic, gemini, ollama…"
            />

            <label className="zn-context-title zn-context-title-spaced" htmlFor="zn-onboarding-model">Model</label>
            <input
              id="zn-onboarding-model"
              className="zn-search"
              value={model}
              disabled={busy}
              onChange={event => setModel(event.target.value)}
              placeholder="Model ID"
            />

            <label className="zn-context-title zn-context-title-spaced" htmlFor="zn-onboarding-base-url">Base URL</label>
            <input
              id="zn-onboarding-base-url"
              className="zn-search"
              value={baseUrl}
              disabled={busy}
              onChange={event => setBaseUrl(event.target.value)}
              placeholder="Optional custom endpoint"
            />

            <label className="zn-context-title zn-context-title-spaced" htmlFor="zn-onboarding-api-key">Credential</label>
            <input
              id="zn-onboarding-api-key"
              className="zn-search"
              type="password"
              autoComplete="new-password"
              value={apiKey}
              disabled={busy}
              onChange={event => setApiKey(event.target.value)}
              placeholder={settings?.credential.configured ? 'Leave blank to keep current credential' : 'API key, when required'}
            />

            <p className="zn-muted zn-small">
              Credentials are sent to the Resident secure-store boundary and are never returned to this renderer.
            </p>
            {notice ? <div className={settings?.cognitionAvailable ? 'zn-setting-state' : 'zn-error-text'}>{notice}</div> : null}
            <div className="zn-inline-actions zn-onboarding-actions">
              <button className="zn-primary" type="submit" disabled={busy || !provider.trim() || !model.trim()}>
                {busy ? 'Checking…' : 'Save and verify'}
              </button>
              <button type="button" disabled={busy} onClick={() => setState('work')}>
                Continue without model
              </button>
            </div>
            <p className="zn-muted zn-small">
              Continuing without a model keeps the Resident available for deterministic and local paths. Model-backed work will remain unavailable until configuration is ready.
            </p>
          </form>
        )}
      </section>
    </main>
  )
}
