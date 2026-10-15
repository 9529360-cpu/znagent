import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import {
  createZnApprovalRule,
  decideZnApproval,
  deleteZnApprovalRule,
  loadZnApprovals
} from './resident-client'
import type {
  ZnApprovalActionKind,
  ZnApprovalDecision,
  ZnApprovalList,
  ZnApprovalRequest,
  ZnApprovalRule,
  ZnApprovalRuleEffect
} from './state'

function approvalKindLabel(kind: ZnApprovalActionKind, t: (key: string) => string): string {
  if (kind === 'send') return t('approval.kind.send')
  if (kind === 'publish') return t('approval.kind.publish')
  if (kind === 'purchase') return t('approval.kind.purchase')
  if (kind === 'delete') return t('approval.kind.delete')
  return t('approval.kind.productionChange')
}

function approvalSourceLabel(source: string, t: (key: string) => string): string {
  if (source === 'user_chat') return t('approval.source.userChat')
  if (source === 'routine') return t('approval.source.routine')
  if (source === 'specialist') return t('approval.source.specialist')
  if (source === 'other_bot') return t('approval.source.otherBot')
  if (source === 'trigger') return t('approval.source.trigger')
  if (source === 'mcp') return t('approval.source.mcp')
  return t('approval.source.resident')
}

const APPROVAL_KINDS: ZnApprovalActionKind[] = ['send', 'publish', 'purchase', 'delete', 'production_change']

export function ZnApprovalPanel() {
  const { t } = useTranslation()
  const [approvals, setApprovals] = useState<ZnApprovalList | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [newKind, setNewKind] = useState<ZnApprovalActionKind>('send')
  const [newScope, setNewScope] = useState('')
  const [newEffect, setNewEffect] = useState<ZnApprovalRuleEffect>('ask_first')
  const [ruleError, setRuleError] = useState<string | null>(null)
  const [ruleBusy, setRuleBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setError(null)
      setApprovals(await loadZnApprovals())
    } catch {
      setError(t('approval.loadFailed'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), 30_000)
    return () => window.clearInterval(timer)
  }, [refresh])

  const decide = useCallback(async (request: ZnApprovalRequest, decision: ZnApprovalDecision) => {
    setBusyId(request.id)
    setError(null)
    try {
      await decideZnApproval(request.id, decision)
      await refresh()
    } catch {
      setError(t('approval.decideFailed'))
    } finally {
      setBusyId(null)
    }
  }, [refresh, t])

  // Keyboard: with focus inside the approval panel, A approves the first
  // pending request and D denies it. Typing in a field never triggers this.
  const handlePanelKeyDown = useCallback((event: React.KeyboardEvent) => {
    if (event.repeat || event.ctrlKey || event.metaKey || event.altKey) return
    const target = event.target as HTMLElement | null
    if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable)) return
    const first = approvals?.pending[0]
    if (!first || busyId) return
    if (event.key === 'a' || event.key === 'A') {
      event.preventDefault()
      void decide(first, 'allow_once')
    } else if (event.key === 'd' || event.key === 'D') {
      event.preventDefault()
      void decide(first, 'deny')
    }
  }, [approvals?.pending, busyId, decide])

  const addRule = useCallback(async () => {
    const scope = newScope.trim()
    if (!scope) return
    setRuleBusy(true)
    setRuleError(null)
    try {
      await createZnApprovalRule(newKind, scope, newEffect)
      setNewScope('')
      await refresh()
    } catch {
      setRuleError(t('approval.ruleFailed'))
    } finally {
      setRuleBusy(false)
    }
  }, [newKind, newScope, newEffect, refresh, t])

  const removeRule = useCallback(async (rule: ZnApprovalRule) => {
    setBusyId(rule.id)
    setRuleError(null)
    try {
      await deleteZnApprovalRule(rule.id)
      await refresh()
    } catch {
      setRuleError(t('approval.ruleFailed'))
    } finally {
      setBusyId(null)
    }
  }, [refresh, t])

  if (loading && !approvals) {
    return (
      <section className="zn-card" aria-label={t('approval.title')}>
        <h2>{t('approval.title')}</h2>
        <p className="zn-muted zn-small">{t('common.working')}</p>
      </section>
    )
  }

  const pending = approvals?.pending ?? []
  const expired = approvals?.expired ?? []
  const rules = approvals?.rules ?? []
  const audit = approvals?.audit ?? []

  return (
    <div className="zn-approval-panel" onKeyDown={handlePanelKeyDown}>
      <section className="zn-card" aria-label={t('approval.pending')}>
        <h2>{t('approval.title')}</h2>
        <p>{t('approval.description')}</p>
        {error ? <div className="zn-error-text" role="alert">{error}</div> : null}
        {pending.length === 0 ? (
          <p className="zn-muted zn-small">{t('approval.noPending')}</p>
        ) : (
          <div className="zn-approval-cards">
            {pending.map(request => (
              <article className="zn-approval-card" key={request.id}>
                <div className="zn-approval-meta">
                  <div><span>{t('approval.action')}</span><strong>{approvalKindLabel(request.actionKind, t)}</strong></div>
                  <div><span>{t('approval.target')}</span><strong>{request.target}</strong></div>
                  <div><span>{t('approval.scope')}</span><strong>{request.scope}</strong></div>
                  {request.valueText ? <div><span>{t('approval.value')}</span><strong>{request.valueText}</strong></div> : null}
                  <div><span>{t('approval.source')}</span><strong>{approvalSourceLabel(request.source, t)}</strong></div>
                  <div><span>{t('approval.expires')}</span><strong>{new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(new Date(request.expiresAt))}</strong></div>
                </div>
                <div className="zn-inline-actions">
                  <button className="zn-primary" type="button" disabled={busyId === request.id} aria-keyshortcuts="a" onClick={() => void decide(request, 'allow_once')}>{t('approval.allowOnce')}</button>
                  <button type="button" disabled={busyId === request.id} onClick={() => void decide(request, 'always_allow')}>{t('approval.alwaysAllow')}</button>
                  <button type="button" disabled={busyId === request.id} aria-keyshortcuts="d" onClick={() => void decide(request, 'deny')}>{t('approval.deny')}</button>
                </div>
              </article>
            ))}
          </div>
        )}
        {expired.length > 0 ? (
          <div className="zn-approval-expired">
            <h3>{t('approval.expired')}</h3>
            <p className="zn-muted zn-small">{t('approval.expiredDescription')}</p>
            {expired.map(request => (
              <div className="zn-approval-card zn-approval-card-expired" key={request.id}>
                <div className="zn-approval-meta">
                  <div><span>{t('approval.action')}</span><strong>{approvalKindLabel(request.actionKind, t)}</strong></div>
                  <div><span>{t('approval.target')}</span><strong>{request.target}</strong></div>
                  <div><span>{t('approval.scope')}</span><strong>{request.scope}</strong></div>
                </div>
                <div className="zn-inline-actions">
                  <button type="button" disabled={busyId === request.id} onClick={() => void decide(request, 'always_allow')}>{t('approval.alwaysAllowKind')}</button>
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </section>

      <section className="zn-card" aria-label={t('approval.rules')}>
        <h2>{t('approval.rules')}</h2>
        {rules.length === 0 ? (
          <p className="zn-muted zn-small">{t('approval.noRules')}</p>
        ) : (
          <ul className="zn-approval-rules">
            {rules.map(rule => (
              <li key={rule.id}>
                <span>{rule.effect === 'ask_first' ? t('approval.ruleEffect.askFirst') : t('approval.ruleEffect.autoAllow')}</span>
                <strong>{approvalKindLabel(rule.actionKind, t)}</strong>
                <span>{rule.scope}</span>
                <button type="button" disabled={busyId === rule.id} onClick={() => void removeRule(rule)}>{t('approval.deleteRule')}</button>
              </li>
            ))}
          </ul>
        )}
        <form
          className="zn-approval-rule-form"
          onSubmit={event => {
            event.preventDefault()
            void addRule()
          }}
        >
          <label>
            <span>{t('approval.action')}</span>
            <select className="zn-search" value={newKind} onChange={event => setNewKind(event.target.value as ZnApprovalActionKind)}>
              {APPROVAL_KINDS.map(kind => (
                <option key={kind} value={kind}>{approvalKindLabel(kind, t)}</option>
              ))}
            </select>
          </label>
          <label>
            <span>{t('approval.scope')}</span>
            <input className="zn-search" value={newScope} onChange={event => setNewScope(event.target.value)} placeholder={t('approval.ruleScopePlaceholder')} />
          </label>
          <label>
            <span>{t('approval.rules')}</span>
            <select className="zn-search" value={newEffect} onChange={event => setNewEffect(event.target.value as ZnApprovalRuleEffect)}>
              <option value="ask_first">{t('approval.ruleAskFirst')}</option>
              <option value="auto_allow">{t('approval.ruleAutoAllow')}</option>
            </select>
          </label>
          <button className="zn-primary" type="submit" disabled={ruleBusy || !newScope.trim()}>{t('approval.addRule')}</button>
        </form>
        {ruleError ? <div className="zn-error-text" role="alert">{ruleError}</div> : null}
        <p className="zn-muted zn-small">{t('approval.ruleTooBroad')}</p>
      </section>

      <section className="zn-card" aria-label={t('approval.audit')}>
        <h2>{t('approval.audit')}</h2>
        {audit.length === 0 ? (
          <p className="zn-muted zn-small">{t('approval.noAudit')}</p>
        ) : (
          <ul className="zn-approval-audit">
            {audit.map(entry => (
              <li key={entry.id}>
                <span>{entry.decision}</span>
                <strong>{approvalKindLabel(entry.actionKind, t)}</strong>
                <span>{entry.scope}</span>
                {entry.note ? <span className="zn-muted">{entry.note}</span> : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
