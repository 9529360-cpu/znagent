import type { TFunction } from 'i18next'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import {
  acknowledgeZnRoutine,
  confirmZnRoutine,
  deleteZnRoutine,
  editZnRoutine,
  loadZnRoutineRuns,
  loadZnRoutines,
  pauseZnRoutine,
  proposeZnRoutine,
  resumeZnRoutine,
  testRunZnRoutine
} from './resident-client'
import type { ZnRoutine, ZnRoutineDraft, ZnRoutineRun } from './resident-client'
import { CdsButton, ConfirmationDialog } from './cds'

type ScheduleEdit = {
  kind: string
  intervalSeconds: string
  cronExpression: string
  timezone: string
}

function scheduleEditFromDraft(draft: ZnRoutineDraft): ScheduleEdit {
  return {
    kind: draft.scheduleKind || 'interval',
    intervalSeconds: String(draft.intervalSeconds ?? 3600),
    cronExpression: draft.cronExpression || '0 9 * * *',
    timezone: draft.timezone || 'UTC'
  }
}

function scheduleEditFromRoutine(routine: ZnRoutine): ScheduleEdit {
  return {
    kind: routine.scheduleKind || 'interval',
    intervalSeconds: routine.scheduleKind === 'interval' ? routine.scheduleSpec : '3600',
    cronExpression: routine.scheduleKind === 'cron' ? routine.scheduleSpec : '0 9 * * *',
    timezone: routine.timezone || 'UTC'
  }
}

function runStatusLabel(run: ZnRoutineRun, t: TFunction): string {
  if (run.status === 'running') return t('status.running')
  if (run.status === 'succeeded') return t('status.completed')
  return t('status.failed')
}

function timeLabel(value: string): string {
  if (!value) return ''
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString()
}

export function RoutinesPanel() {
  const { t } = useTranslation()
  const [routines, setRoutines] = useState<ZnRoutine[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sentence, setSentence] = useState('')
  const [proposing, setProposing] = useState(false)
  const [draft, setDraft] = useState<ZnRoutineDraft | null>(null)
  const [draftSchedule, setDraftSchedule] = useState<ScheduleEdit | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [runsById, setRunsById] = useState<Record<string, ZnRoutineRun[]>>({})
  const [runsLoading, setRunsLoading] = useState<Record<string, boolean>>({})
  const [testRunTarget, setTestRunTarget] = useState<ZnRoutine | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<ZnRoutine | null>(null)
  const [editing, setEditing] = useState<ZnRoutine | null>(null)
  const [editFields, setEditFields] = useState<Record<string, string>>({})
  const [editSchedule, setEditSchedule] = useState<ScheduleEdit | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setError(null)
    try {
      setRoutines(await loadZnRoutines())
    } catch (value) {
      setError(value instanceof Error ? value.message : t('routines.loadFailed'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const propose = async () => {
    const text = sentence.trim()
    if (!text || proposing) return
    setProposing(true)
    setError(null)
    try {
      const next = await proposeZnRoutine(text)
      setDraft(next)
      setDraftSchedule(scheduleEditFromDraft(next))
    } catch (value) {
      setError(value instanceof Error ? value.message : t('routines.loadFailed'))
    } finally {
      setProposing(false)
    }
  }

  const confirmCreate = async () => {
    if (!draft || !draftSchedule || confirming) return
    const intervalSeconds = Number(draftSchedule.intervalSeconds)
    const scheduleOk =
      draftSchedule.kind === 'interval'
        ? Number.isFinite(intervalSeconds) && intervalSeconds >= 60
        : draftSchedule.cronExpression.trim().length > 0
    if (!draft.task.trim() || !scheduleOk || !draftSchedule.timezone.trim()) return
    setConfirming(true)
    setError(null)
    try {
      await confirmZnRoutine({
        ...draft,
        scheduleKind: draftSchedule.kind,
        intervalSeconds: draftSchedule.kind === 'interval' ? intervalSeconds : null,
        cronExpression: draftSchedule.kind === 'cron' ? draftSchedule.cronExpression.trim() : null,
        timezone: draftSchedule.timezone.trim()
      })
      setDraft(null)
      setDraftSchedule(null)
      setSentence('')
      await refresh()
    } catch (value) {
      setError(value instanceof Error ? value.message : t('routines.saveFailed'))
    } finally {
      setConfirming(false)
    }
  }

  const toggleRuns = async (routine: ZnRoutine) => {
    const open = !expanded[routine.routineId]
    setExpanded(current => ({ ...current, [routine.routineId]: open }))
    if (open && !runsById[routine.routineId]) {
      setRunsLoading(current => ({ ...current, [routine.routineId]: true }))
      try {
        const runs = await loadZnRoutineRuns(routine.routineId, 20)
        setRunsById(current => ({ ...current, [routine.routineId]: runs }))
      } catch (value) {
        setError(value instanceof Error ? value.message : t('routines.loadFailed'))
      } finally {
        setRunsLoading(current => ({ ...current, [routine.routineId]: false }))
      }
    }
  }

  const mutate = async (routineId: string, action: () => Promise<unknown>) => {
    if (busyId) return
    setBusyId(routineId)
    setError(null)
    try {
      await action()
      await refresh()
    } catch (value) {
      setError(value instanceof Error ? value.message : t('routines.saveFailed'))
    } finally {
      setBusyId(null)
    }
  }

  const startEdit = (routine: ZnRoutine) => {
    setEditing(routine)
    setEditFields({
      task: routine.task,
      owner: routine.owner,
      input_source: routine.inputSource,
      expected_result: routine.expectedResult,
      approval_boundary: routine.approvalBoundary,
      missing_data_policy: routine.missingDataPolicy,
      auto_pause_after_days: String(routine.autoPauseAfterDays)
    })
    setEditSchedule(scheduleEditFromRoutine(routine))
  }

  const saveEdit = async () => {
    if (!editing || !editSchedule || busyId) return
    const intervalSeconds = Number(editSchedule.intervalSeconds)
    const scheduleOk =
      editSchedule.kind === 'interval'
        ? Number.isFinite(intervalSeconds) && intervalSeconds >= 60
        : editSchedule.cronExpression.trim().length > 0
    if (!editFields.task?.trim() || !scheduleOk) return
    setBusyId(editing.routineId)
    setError(null)
    try {
      await editZnRoutine(editing.routineId, {
        task: editFields.task.trim(),
        owner: editFields.owner?.trim(),
        input_source: editFields.input_source?.trim(),
        expected_result: editFields.expected_result?.trim(),
        approval_boundary: editFields.approval_boundary?.trim(),
        missing_data_policy: editFields.missing_data_policy,
        auto_pause_after_days: Number(editFields.auto_pause_after_days),
        schedule_kind: editSchedule.kind,
        interval_seconds: editSchedule.kind === 'interval' ? intervalSeconds : null,
        cron_expression: editSchedule.kind === 'cron' ? editSchedule.cronExpression.trim() : null,
        timezone: editSchedule.timezone.trim()
      })
      setEditing(null)
      setEditSchedule(null)
      await refresh()
    } catch (value) {
      setError(value instanceof Error ? value.message : t('routines.saveFailed'))
    } finally {
      setBusyId(null)
    }
  }

  const confirmTestRun = async () => {
    if (!testRunTarget || busyId) return
    setBusyId(testRunTarget.routineId)
    setError(null)
    try {
      await testRunZnRoutine(testRunTarget.routineId)
      setTestRunTarget(null)
      await refresh()
    } catch (value) {
      setError(value instanceof Error ? value.message : t('routines.saveFailed'))
    } finally {
      setBusyId(null)
    }
  }

  const confirmDelete = async () => {
    if (!deleteTarget || busyId) return
    setBusyId(deleteTarget.routineId)
    setError(null)
    try {
      await deleteZnRoutine(deleteTarget.routineId)
      setDeleteTarget(null)
      await refresh()
    } catch (value) {
      setError(value instanceof Error ? value.message : t('routines.saveFailed'))
    } finally {
      setBusyId(null)
    }
  }

  const scheduleEditor = (
    schedule: ScheduleEdit,
    setSchedule: (next: ScheduleEdit) => void,
    idPrefix: string
  ) => (
    <div className="flex flex-col gap-1 text-sm">
      <label htmlFor={`${idPrefix}-kind`}>{t('routines.schedule')}</label>
      <select
          className="rounded-lg bg-[var(--cds-surface-1)] px-2 py-1.5 text-sm text-[var(--cds-text-primary)]"
        id={`${idPrefix}-kind`}
        value={schedule.kind}
        onChange={event => setSchedule({ ...schedule, kind: event.target.value })}
      >
        <option value="interval">{t('routines.scheduleInterval')}</option>
        <option value="cron">{t('routines.scheduleCron')}</option>
      </select>
      {schedule.kind === 'interval' ? (
        <input
          className="rounded-lg bg-[var(--cds-surface-1)] px-2 py-1.5 text-sm text-[var(--cds-text-primary)] outline-none"
          aria-label={t('routines.scheduleInterval')}
          type="number"
          min={60}
          value={schedule.intervalSeconds}
          onChange={event => setSchedule({ ...schedule, intervalSeconds: event.target.value })}
        />
      ) : (
        <input
          className="rounded-lg bg-[var(--cds-surface-1)] px-2 py-1.5 text-sm text-[var(--cds-text-primary)] outline-none"
          aria-label={t('routines.scheduleCron')}
          value={schedule.cronExpression}
          onChange={event => setSchedule({ ...schedule, cronExpression: event.target.value })}
          placeholder="0 9 * * 1-5"
        />
      )}
      <label htmlFor={`${idPrefix}-tz`}>{t('routines.timezone')}</label>
      <input
          className="rounded-lg bg-[var(--cds-surface-1)] px-2 py-1.5 text-sm text-[var(--cds-text-primary)] outline-none"
        id={`${idPrefix}-tz`}
        value={schedule.timezone}
        onChange={event => setSchedule({ ...schedule, timezone: event.target.value })}
        placeholder="UTC"
      />
    </div>
  )

  return (
    <div className="flex flex-col gap-3 px-1 py-1">
      <div className="flex flex-col gap-2">
        <input
          className="w-full rounded-lg bg-[var(--cds-surface-2)] px-2 py-2 text-sm text-[var(--cds-text-primary)] outline-none placeholder:text-[var(--cds-text-muted)]"
          aria-label={t('routines.create')}
          placeholder={t('routines.newPlaceholder')}
          value={sentence}
          onChange={event => setSentence(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter') void propose()
          }}
        />
        <CdsButton type="button" disabled={proposing || !sentence.trim()} onClick={() => void propose()}>
          {proposing ? t('common.working') : t('routines.create')}
        </CdsButton>
      </div>

      {draft && draftSchedule ? (
        <div className="flex flex-col gap-2 rounded-xl border border-[var(--cds-border)] bg-[var(--cds-surface-2)] px-3 py-2">
          <div className="text-sm font-medium text-[var(--cds-text-primary)]">{t('routines.confirmTitle')}</div>
          <div className="text-xs text-[var(--cds-text-secondary)]">{t('routines.confirmHint')}</div>
          {draft.missing.includes('schedule') ? (
            <div className="rounded-lg bg-[var(--cds-fill-brand-subtle)] px-2 py-1.5 text-xs text-[var(--cds-text-primary)]">{t('routines.missingSchedule')}</div>
          ) : null}
          <div className="flex flex-col gap-1 text-sm">
            <label htmlFor="routine-draft-task">{t('routines.task')}</label>
            <input
          className="rounded-lg bg-[var(--cds-surface-1)] px-2 py-1.5 text-sm text-[var(--cds-text-primary)] outline-none"
              id="routine-draft-task"
              value={draft.task}
              onChange={event => setDraft({ ...draft, task: event.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1 text-sm">
            <label htmlFor="routine-draft-owner">{t('routines.owner')}</label>
            <input
          className="rounded-lg bg-[var(--cds-surface-1)] px-2 py-1.5 text-sm text-[var(--cds-text-primary)] outline-none"
              id="routine-draft-owner"
              value={draft.owner}
              onChange={event => setDraft({ ...draft, owner: event.target.value })}
            />
          </div>
          {scheduleEditor(draftSchedule, setDraftSchedule, 'routine-draft')}
          <div className="flex flex-col gap-1 text-sm">
            <label htmlFor="routine-draft-input">{t('routines.inputSource')}</label>
            <input
          className="rounded-lg bg-[var(--cds-surface-1)] px-2 py-1.5 text-sm text-[var(--cds-text-primary)] outline-none"
              id="routine-draft-input"
              value={draft.inputSource}
              onChange={event => setDraft({ ...draft, inputSource: event.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1 text-sm">
            <label htmlFor="routine-draft-expected">{t('routines.expectedResult')}</label>
            <input
          className="rounded-lg bg-[var(--cds-surface-1)] px-2 py-1.5 text-sm text-[var(--cds-text-primary)] outline-none"
              id="routine-draft-expected"
              value={draft.expectedResult}
              onChange={event => setDraft({ ...draft, expectedResult: event.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1 text-sm">
            <label htmlFor="routine-draft-approval">{t('routines.approvalBoundary')}</label>
            <input
          className="rounded-lg bg-[var(--cds-surface-1)] px-2 py-1.5 text-sm text-[var(--cds-text-primary)] outline-none"
              id="routine-draft-approval"
              value={draft.approvalBoundary}
              onChange={event => setDraft({ ...draft, approvalBoundary: event.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1 text-sm">
            <label htmlFor="routine-draft-missing">{t('routines.missingDataPolicy')}</label>
            <select
          className="rounded-lg bg-[var(--cds-surface-1)] px-2 py-1.5 text-sm text-[var(--cds-text-primary)]"
              id="routine-draft-missing"
              value={draft.missingDataPolicy}
              onChange={event => setDraft({ ...draft, missingDataPolicy: event.target.value })}
            >
              <option value="skip">{t('routines.missingDataSkip')}</option>
              <option value="notify">{t('routines.missingDataNotify')}</option>
              <option value="use_last_known">{t('routines.missingDataUseLast')}</option>
            </select>
          </div>
          <div className="flex flex-col gap-1 text-sm">
            <label htmlFor="routine-draft-autopause">{t('routines.autoPause')}</label>
            <input
          className="rounded-lg bg-[var(--cds-surface-1)] px-2 py-1.5 text-sm text-[var(--cds-text-primary)] outline-none"
              id="routine-draft-autopause"
              type="number"
              min={0}
              max={365}
              value={draft.autoPauseAfterDays}
              onChange={event => setDraft({ ...draft, autoPauseAfterDays: Number(event.target.value) })}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <CdsButton type="button" disabled={confirming} onClick={() => void confirmCreate()}>
              {confirming ? t('common.working') : t('routines.confirmCreate')}
            </CdsButton>
            <CdsButton type="button" onClick={() => { setDraft(null); setDraftSchedule(null) }}>
              {t('routines.cancel')}
            </CdsButton>
          </div>
        </div>
      ) : null}

      {error ? <div className="text-sm text-[var(--cds-fill-danger)]" role="alert">{error}</div> : null}

      {loading ? (
        <div className="text-xs text-[var(--cds-text-secondary)]">{t('common.checking')}</div>
      ) : routines.length === 0 ? (
        <div className="text-xs text-[var(--cds-text-secondary)]">{t('routines.empty')}</div>
      ) : (
        <div className="flex flex-col gap-2">
          {routines.map(routine => {
            const autoPaused = Boolean(
              routine.status === 'paused' &&
              routine.pausedReason &&
              (routine.pausedReason.includes('自动暂停') || routine.pausedReason.includes('auto-pause'))
            )
            const runs = runsById[routine.routineId] || routine.recentRuns
            return (
              <div className="flex flex-col gap-1 rounded-xl border border-[var(--cds-border)] bg-[var(--cds-surface-2)] px-3 py-2" key={routine.routineId}>
                <div className="flex items-start justify-between gap-2">
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-[var(--cds-text-primary)]">{routine.title}</span>
                  <span className={'shrink-0 rounded-full px-2 py-0.5 text-xs ' + (routine.status === 'active' ? 'bg-[var(--cds-fill-brand-subtle)] text-[var(--cds-text-primary)]' : 'bg-[var(--cds-surface-1)] text-[var(--cds-text-secondary)]')}>
                    {routine.status === 'active' ? t('routines.statusActive') : t('routines.statusPaused')}
                  </span>
                </div>
                <div className="text-xs text-[var(--cds-text-secondary)]">{routine.scheduleDescription} · {routine.timezone}</div>
                {routine.pausedReason ? (
                  <div className="text-xs text-[var(--cds-text-secondary)]">{routine.pausedReason}</div>
                ) : null}
                <div className="flex flex-wrap gap-1">
                  {routine.status === 'active' ? (
                    <CdsButton type="button" disabled={busyId === routine.routineId} onClick={() => void mutate(routine.routineId, () => pauseZnRoutine(routine.routineId))}>
                      {t('routines.pause')}
                    </CdsButton>
                  ) : (
                    <CdsButton type="button" disabled={busyId === routine.routineId} onClick={() => void mutate(routine.routineId, () => resumeZnRoutine(routine.routineId))}>
                      {t('routines.resume')}
                    </CdsButton>
                  )}
                  <CdsButton type="button" disabled={busyId === routine.routineId} onClick={() => setTestRunTarget(routine)}>
                    {t('routines.testRun')}
                  </CdsButton>
                  <CdsButton type="button" disabled={busyId === routine.routineId} onClick={() => startEdit(routine)}>
                    {t('routines.edit')}
                  </CdsButton>
                  <CdsButton type="button" disabled={busyId === routine.routineId} onClick={() => setDeleteTarget(routine)}>
                    {t('routines.delete')}
                  </CdsButton>
                  {autoPaused ? (
                    <CdsButton type="button" disabled={busyId === routine.routineId} onClick={() => void mutate(routine.routineId, () => acknowledgeZnRoutine(routine.routineId))}>
                      {t('routines.acknowledge')}
                    </CdsButton>
                  ) : null}
                  <CdsButton type="button" onClick={() => void toggleRuns(routine)}>
                    {t('routines.runs')}
                  </CdsButton>
                </div>

                {editing?.routineId === routine.routineId && editSchedule ? (
                  <div className="flex flex-col gap-2 rounded-xl border border-[var(--cds-border)] bg-[var(--cds-surface-2)] px-3 py-2">
                    <div className="flex flex-col gap-1 text-sm">
                      <label htmlFor="routine-edit-task">{t('routines.task')}</label>
                      <input
          className="rounded-lg bg-[var(--cds-surface-1)] px-2 py-1.5 text-sm text-[var(--cds-text-primary)] outline-none"
                        id="routine-edit-task"
                        value={editFields.task || ''}
                        onChange={event => setEditFields({ ...editFields, task: event.target.value })}
                      />
                    </div>
                    <div className="flex flex-col gap-1 text-sm">
                      <label htmlFor="routine-edit-owner">{t('routines.owner')}</label>
                      <input
          className="rounded-lg bg-[var(--cds-surface-1)] px-2 py-1.5 text-sm text-[var(--cds-text-primary)] outline-none"
                        id="routine-edit-owner"
                        value={editFields.owner || ''}
                        onChange={event => setEditFields({ ...editFields, owner: event.target.value })}
                      />
                    </div>
                    {scheduleEditor(editSchedule, setEditSchedule, 'routine-edit')}
                    <div className="flex flex-col gap-1 text-sm">
                      <label htmlFor="routine-edit-input">{t('routines.inputSource')}</label>
                      <input
          className="rounded-lg bg-[var(--cds-surface-1)] px-2 py-1.5 text-sm text-[var(--cds-text-primary)] outline-none"
                        id="routine-edit-input"
                        value={editFields.input_source || ''}
                        onChange={event => setEditFields({ ...editFields, input_source: event.target.value })}
                      />
                    </div>
                    <div className="flex flex-col gap-1 text-sm">
                      <label htmlFor="routine-edit-expected">{t('routines.expectedResult')}</label>
                      <input
          className="rounded-lg bg-[var(--cds-surface-1)] px-2 py-1.5 text-sm text-[var(--cds-text-primary)] outline-none"
                        id="routine-edit-expected"
                        value={editFields.expected_result || ''}
                        onChange={event => setEditFields({ ...editFields, expected_result: event.target.value })}
                      />
                    </div>
                    <div className="flex flex-col gap-1 text-sm">
                      <label htmlFor="routine-edit-approval">{t('routines.approvalBoundary')}</label>
                      <input
          className="rounded-lg bg-[var(--cds-surface-1)] px-2 py-1.5 text-sm text-[var(--cds-text-primary)] outline-none"
                        id="routine-edit-approval"
                        value={editFields.approval_boundary || ''}
                        onChange={event => setEditFields({ ...editFields, approval_boundary: event.target.value })}
                      />
                    </div>
                    <div className="flex flex-col gap-1 text-sm">
                      <label htmlFor="routine-edit-missing">{t('routines.missingDataPolicy')}</label>
                      <select
          className="rounded-lg bg-[var(--cds-surface-1)] px-2 py-1.5 text-sm text-[var(--cds-text-primary)]"
                        id="routine-edit-missing"
                        value={editFields.missing_data_policy || 'skip'}
                        onChange={event => setEditFields({ ...editFields, missing_data_policy: event.target.value })}
                      >
                        <option value="skip">{t('routines.missingDataSkip')}</option>
                        <option value="notify">{t('routines.missingDataNotify')}</option>
                        <option value="use_last_known">{t('routines.missingDataUseLast')}</option>
                      </select>
                    </div>
                    <div className="flex flex-col gap-1 text-sm">
                      <label htmlFor="routine-edit-autopause">{t('routines.autoPause')}</label>
                      <input
          className="rounded-lg bg-[var(--cds-surface-1)] px-2 py-1.5 text-sm text-[var(--cds-text-primary)] outline-none"
                        id="routine-edit-autopause"
                        type="number"
                        min={0}
                        max={365}
                        value={editFields.auto_pause_after_days || '14'}
                        onChange={event => setEditFields({ ...editFields, auto_pause_after_days: event.target.value })}
                      />
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <CdsButton type="button" disabled={busyId === routine.routineId} onClick={() => void saveEdit()}>
                        {t('routines.confirmCreate')}
                      </CdsButton>
                      <CdsButton type="button" onClick={() => { setEditing(null); setEditSchedule(null) }}>
                        {t('routines.cancel')}
                      </CdsButton>
                    </div>
                  </div>
                ) : null}

                <ConfirmationDialog
                  isOpen={testRunTarget?.routineId === routine.routineId}
                  onClose={() => setTestRunTarget(null)}
                  onConfirm={() => void confirmTestRun()}
                  title={t('routines.testRun')}
                  description={t('routines.testRunWarning')}
                  confirmLabel={t('routines.testRunConfirm')}
                  cancelLabel={t('routines.cancel')}
                  variant="default"
                />

                <ConfirmationDialog
                  isOpen={deleteTarget?.routineId === routine.routineId}
                  onClose={() => setDeleteTarget(null)}
                  onConfirm={() => void confirmDelete()}
                  title={t('routines.delete')}
                  description={t('routines.deleteConfirm')}
                  confirmLabel={t('routines.delete')}
                  cancelLabel={t('routines.cancel')}
                  variant="danger"
                />

                {expanded[routine.routineId] ? (
                  <div className="flex flex-col gap-1 border-t border-[var(--cds-border)] pt-1">
                    <div className="text-xs text-[var(--cds-text-secondary)]">{t('routines.runs')}</div>
                    {runsLoading[routine.routineId] ? (
                      <div className="text-xs text-[var(--cds-text-secondary)]">{t('common.checking')}</div>
                    ) : runs.length === 0 ? (
                      <div className="text-xs text-[var(--cds-text-secondary)]">{t('routines.noRuns')}</div>
                    ) : (
                      runs.map(run => (
                        <div className="flex flex-col gap-0.5" key={run.runId}>
                          <span className={'w-fit rounded-full px-2 py-0.5 text-xs ' + (run.status === 'succeeded' ? 'bg-[var(--cds-fill-brand-subtle)] text-[var(--cds-text-primary)]' : run.status === 'running' ? 'bg-[var(--cds-surface-1)] text-[var(--cds-text-secondary)]' : 'bg-[var(--cds-fill-danger)]/10 text-[var(--cds-fill-danger)]')}>{runStatusLabel(run, t)}</span>
                          <span className="text-xs text-[var(--cds-text-secondary)]">
                            {run.triggerKind === 'test_run' ? t('routines.runTestRun') : t('routines.runScheduled')}
                            {' · '}
                            {timeLabel(run.startedAt)}
                          </span>
                          {run.failureReason ? (
                            <div className="text-xs text-[var(--cds-fill-danger)]">{run.failureReason}</div>
                          ) : run.summary ? (
                            <div className="text-xs text-[var(--cds-text-secondary)]">{run.summary}</div>
                          ) : null}
                        </div>
                      ))
                    )}
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
