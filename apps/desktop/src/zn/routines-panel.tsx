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
    <div className="zn-routines-field">
      <label htmlFor={`${idPrefix}-kind`}>{t('routines.schedule')}</label>
      <select
        id={`${idPrefix}-kind`}
        value={schedule.kind}
        onChange={event => setSchedule({ ...schedule, kind: event.target.value })}
      >
        <option value="interval">{t('routines.scheduleInterval')}</option>
        <option value="cron">{t('routines.scheduleCron')}</option>
      </select>
      {schedule.kind === 'interval' ? (
        <input
          aria-label={t('routines.scheduleInterval')}
          type="number"
          min={60}
          value={schedule.intervalSeconds}
          onChange={event => setSchedule({ ...schedule, intervalSeconds: event.target.value })}
        />
      ) : (
        <input
          aria-label={t('routines.scheduleCron')}
          value={schedule.cronExpression}
          onChange={event => setSchedule({ ...schedule, cronExpression: event.target.value })}
          placeholder="0 9 * * 1-5"
        />
      )}
      <label htmlFor={`${idPrefix}-tz`}>{t('routines.timezone')}</label>
      <input
        id={`${idPrefix}-tz`}
        value={schedule.timezone}
        onChange={event => setSchedule({ ...schedule, timezone: event.target.value })}
        placeholder="UTC"
      />
    </div>
  )

  return (
    <div className="zn-routines-panel">
      <div className="zn-routines-create">
        <input
          className="zn-routines-sentence"
          aria-label={t('routines.create')}
          placeholder={t('routines.newPlaceholder')}
          value={sentence}
          onChange={event => setSentence(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter') void propose()
          }}
        />
        <button type="button" disabled={proposing || !sentence.trim()} onClick={() => void propose()}>
          {proposing ? t('common.working') : t('routines.create')}
        </button>
      </div>

      {draft && draftSchedule ? (
        <div className="zn-routines-dialog">
          <div className="zn-routines-dialog-title">{t('routines.confirmTitle')}</div>
          <div className="zn-muted zn-small">{t('routines.confirmHint')}</div>
          {draft.missing.includes('schedule') ? (
            <div className="zn-routines-warning">{t('routines.missingSchedule')}</div>
          ) : null}
          <div className="zn-routines-field">
            <label htmlFor="routine-draft-task">{t('routines.task')}</label>
            <input
              id="routine-draft-task"
              value={draft.task}
              onChange={event => setDraft({ ...draft, task: event.target.value })}
            />
          </div>
          <div className="zn-routines-field">
            <label htmlFor="routine-draft-owner">{t('routines.owner')}</label>
            <input
              id="routine-draft-owner"
              value={draft.owner}
              onChange={event => setDraft({ ...draft, owner: event.target.value })}
            />
          </div>
          {scheduleEditor(draftSchedule, setDraftSchedule, 'routine-draft')}
          <div className="zn-routines-field">
            <label htmlFor="routine-draft-input">{t('routines.inputSource')}</label>
            <input
              id="routine-draft-input"
              value={draft.inputSource}
              onChange={event => setDraft({ ...draft, inputSource: event.target.value })}
            />
          </div>
          <div className="zn-routines-field">
            <label htmlFor="routine-draft-expected">{t('routines.expectedResult')}</label>
            <input
              id="routine-draft-expected"
              value={draft.expectedResult}
              onChange={event => setDraft({ ...draft, expectedResult: event.target.value })}
            />
          </div>
          <div className="zn-routines-field">
            <label htmlFor="routine-draft-approval">{t('routines.approvalBoundary')}</label>
            <input
              id="routine-draft-approval"
              value={draft.approvalBoundary}
              onChange={event => setDraft({ ...draft, approvalBoundary: event.target.value })}
            />
          </div>
          <div className="zn-routines-field">
            <label htmlFor="routine-draft-missing">{t('routines.missingDataPolicy')}</label>
            <select
              id="routine-draft-missing"
              value={draft.missingDataPolicy}
              onChange={event => setDraft({ ...draft, missingDataPolicy: event.target.value })}
            >
              <option value="skip">{t('routines.missingDataSkip')}</option>
              <option value="notify">{t('routines.missingDataNotify')}</option>
              <option value="use_last_known">{t('routines.missingDataUseLast')}</option>
            </select>
          </div>
          <div className="zn-routines-field">
            <label htmlFor="routine-draft-autopause">{t('routines.autoPause')}</label>
            <input
              id="routine-draft-autopause"
              type="number"
              min={0}
              max={365}
              value={draft.autoPauseAfterDays}
              onChange={event => setDraft({ ...draft, autoPauseAfterDays: Number(event.target.value) })}
            />
          </div>
          <div className="zn-routines-dialog-actions">
            <button type="button" disabled={confirming} onClick={() => void confirmCreate()}>
              {confirming ? t('common.working') : t('routines.confirmCreate')}
            </button>
            <button type="button" onClick={() => { setDraft(null); setDraftSchedule(null) }}>
              {t('routines.cancel')}
            </button>
          </div>
        </div>
      ) : null}

      {error ? <div className="zn-routines-error" role="alert">{error}</div> : null}

      {loading ? (
        <div className="zn-muted zn-small">{t('common.checking')}</div>
      ) : routines.length === 0 ? (
        <div className="zn-muted zn-small">{t('routines.empty')}</div>
      ) : (
        <div className="zn-routines-list">
          {routines.map(routine => {
            const autoPaused = Boolean(
              routine.status === 'paused' &&
              routine.pausedReason &&
              (routine.pausedReason.includes('自动暂停') || routine.pausedReason.includes('auto-pause'))
            )
            const runs = runsById[routine.routineId] || routine.recentRuns
            return (
              <div className="zn-routines-item" key={routine.routineId}>
                <div className="zn-routines-item-head">
                  <span className="zn-routines-item-title">{routine.title}</span>
                  <span className={'zn-routines-badge ' + routine.status}>
                    {routine.status === 'active' ? t('routines.statusActive') : t('routines.statusPaused')}
                  </span>
                </div>
                <div className="zn-muted zn-small">{routine.scheduleDescription} · {routine.timezone}</div>
                {routine.pausedReason ? (
                  <div className="zn-muted zn-small">{routine.pausedReason}</div>
                ) : null}
                <div className="zn-routines-actions">
                  {routine.status === 'active' ? (
                    <button type="button" disabled={busyId === routine.routineId} onClick={() => void mutate(routine.routineId, () => pauseZnRoutine(routine.routineId))}>
                      {t('routines.pause')}
                    </button>
                  ) : (
                    <button type="button" disabled={busyId === routine.routineId} onClick={() => void mutate(routine.routineId, () => resumeZnRoutine(routine.routineId))}>
                      {t('routines.resume')}
                    </button>
                  )}
                  <button type="button" disabled={busyId === routine.routineId} onClick={() => setTestRunTarget(routine)}>
                    {t('routines.testRun')}
                  </button>
                  <button type="button" disabled={busyId === routine.routineId} onClick={() => startEdit(routine)}>
                    {t('routines.edit')}
                  </button>
                  <button type="button" disabled={busyId === routine.routineId} onClick={() => setDeleteTarget(routine)}>
                    {t('routines.delete')}
                  </button>
                  {autoPaused ? (
                    <button type="button" disabled={busyId === routine.routineId} onClick={() => void mutate(routine.routineId, () => acknowledgeZnRoutine(routine.routineId))}>
                      {t('routines.acknowledge')}
                    </button>
                  ) : null}
                  <button type="button" onClick={() => void toggleRuns(routine)}>
                    {t('routines.runs')}
                  </button>
                </div>

                {editing?.routineId === routine.routineId && editSchedule ? (
                  <div className="zn-routines-dialog">
                    <div className="zn-routines-field">
                      <label htmlFor="routine-edit-task">{t('routines.task')}</label>
                      <input
                        id="routine-edit-task"
                        value={editFields.task || ''}
                        onChange={event => setEditFields({ ...editFields, task: event.target.value })}
                      />
                    </div>
                    <div className="zn-routines-field">
                      <label htmlFor="routine-edit-owner">{t('routines.owner')}</label>
                      <input
                        id="routine-edit-owner"
                        value={editFields.owner || ''}
                        onChange={event => setEditFields({ ...editFields, owner: event.target.value })}
                      />
                    </div>
                    {scheduleEditor(editSchedule, setEditSchedule, 'routine-edit')}
                    <div className="zn-routines-field">
                      <label htmlFor="routine-edit-input">{t('routines.inputSource')}</label>
                      <input
                        id="routine-edit-input"
                        value={editFields.input_source || ''}
                        onChange={event => setEditFields({ ...editFields, input_source: event.target.value })}
                      />
                    </div>
                    <div className="zn-routines-field">
                      <label htmlFor="routine-edit-expected">{t('routines.expectedResult')}</label>
                      <input
                        id="routine-edit-expected"
                        value={editFields.expected_result || ''}
                        onChange={event => setEditFields({ ...editFields, expected_result: event.target.value })}
                      />
                    </div>
                    <div className="zn-routines-field">
                      <label htmlFor="routine-edit-approval">{t('routines.approvalBoundary')}</label>
                      <input
                        id="routine-edit-approval"
                        value={editFields.approval_boundary || ''}
                        onChange={event => setEditFields({ ...editFields, approval_boundary: event.target.value })}
                      />
                    </div>
                    <div className="zn-routines-field">
                      <label htmlFor="routine-edit-missing">{t('routines.missingDataPolicy')}</label>
                      <select
                        id="routine-edit-missing"
                        value={editFields.missing_data_policy || 'skip'}
                        onChange={event => setEditFields({ ...editFields, missing_data_policy: event.target.value })}
                      >
                        <option value="skip">{t('routines.missingDataSkip')}</option>
                        <option value="notify">{t('routines.missingDataNotify')}</option>
                        <option value="use_last_known">{t('routines.missingDataUseLast')}</option>
                      </select>
                    </div>
                    <div className="zn-routines-field">
                      <label htmlFor="routine-edit-autopause">{t('routines.autoPause')}</label>
                      <input
                        id="routine-edit-autopause"
                        type="number"
                        min={0}
                        max={365}
                        value={editFields.auto_pause_after_days || '14'}
                        onChange={event => setEditFields({ ...editFields, auto_pause_after_days: event.target.value })}
                      />
                    </div>
                    <div className="zn-routines-dialog-actions">
                      <button type="button" disabled={busyId === routine.routineId} onClick={() => void saveEdit()}>
                        {t('routines.confirmCreate')}
                      </button>
                      <button type="button" onClick={() => { setEditing(null); setEditSchedule(null) }}>
                        {t('routines.cancel')}
                      </button>
                    </div>
                  </div>
                ) : null}

                {testRunTarget?.routineId === routine.routineId ? (
                  <div className="zn-routines-dialog">
                    <div className="zn-routines-warning">{t('routines.testRunWarning')}</div>
                    <div className="zn-routines-dialog-actions">
                      <button type="button" disabled={busyId === routine.routineId} onClick={() => void confirmTestRun()}>
                        {t('routines.testRunConfirm')}
                      </button>
                      <button type="button" onClick={() => setTestRunTarget(null)}>
                        {t('routines.cancel')}
                      </button>
                    </div>
                  </div>
                ) : null}

                {deleteTarget?.routineId === routine.routineId ? (
                  <div className="zn-routines-dialog">
                    <div className="zn-muted zn-small">{t('routines.deleteConfirm')}</div>
                    <div className="zn-routines-dialog-actions">
                      <button type="button" disabled={busyId === routine.routineId} onClick={() => void confirmDelete()}>
                        {t('routines.delete')}
                      </button>
                      <button type="button" onClick={() => setDeleteTarget(null)}>
                        {t('routines.cancel')}
                      </button>
                    </div>
                  </div>
                ) : null}

                {expanded[routine.routineId] ? (
                  <div className="zn-routines-runs">
                    <div className="zn-muted zn-small">{t('routines.runs')}</div>
                    {runsLoading[routine.routineId] ? (
                      <div className="zn-muted zn-small">{t('common.checking')}</div>
                    ) : runs.length === 0 ? (
                      <div className="zn-muted zn-small">{t('routines.noRuns')}</div>
                    ) : (
                      runs.map(run => (
                        <div className="zn-routines-run" key={run.runId}>
                          <span className={'zn-routines-badge ' + run.status}>{runStatusLabel(run, t)}</span>
                          <span className="zn-muted zn-small">
                            {run.triggerKind === 'test_run' ? t('routines.runTestRun') : t('routines.runScheduled')}
                            {' · '}
                            {timeLabel(run.startedAt)}
                          </span>
                          {run.failureReason ? (
                            <div className="zn-routines-run-reason">{run.failureReason}</div>
                          ) : run.summary ? (
                            <div className="zn-muted zn-small">{run.summary}</div>
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
