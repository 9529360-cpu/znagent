from __future__ import annotations

"""Natural-language routines: one sentence -> confirmed schedule -> run history.

This is the layer the P1-2 design calls for *on top of*
``RecurringWillTriggers``: the trigger organ still owns "when an occurrence
is due" and the Will still owns execution. This module owns only what the
trigger organ deliberately does not:

- the six confirmations a routine needs before it may run (owner,
  schedule + timezone, input source, expected result, approval boundary,
  missing-data policy);
- run history: one durable row per occurrence (Running / Succeeded /
  Failed + failure reason), capped at the latest 20 per routine;
- pause / resume / edit / delete / test run;
- auto-pause after a configurable stretch with no user response, with a
  notification, so an unattended routine cannot run forever unnoticed.

A test run is real execution, not a dry run: it hands the routine's task to
Will through the same path a scheduled occurrence uses, and its run row is
closed by the same outcome observation. The only difference is the
``trigger_kind`` recorded on the row.

The approval boundary is enforced, not just recorded. Before an
occurrence hands its task to Will, the routine layer checks the boundary
through the existing approval gate (``ApprovalGate``):

- an empty boundary means unrestricted: the occurrence hands off exactly
  like before, with no approval card;
- a non-empty boundary means the occurrence needs approval: it is held
  (run status ``awaiting_approval``) and an approval card is created
  (source ``routine``, kind ``production_change``). Nothing executes
  until the user decides on the card. ``allow_once`` releases that one
  occurrence; ``always_allow`` records an auto-allow rule so later
  occurrences of the same routine pass without a card; ``deny`` voids
  the occurrence (and stays sticky for the routine's task, per the
  gate's deny semantics — only an explicit reconsideration re-asks it).

Held occurrences are durable: a scheduled hold keeps the trigger
organ's pending stamp, so the next pulse retries the handoff and the
gate is re-evaluated (approval -> hand off, still pending -> keep
holding, denied/expired -> void). A test-run hold is resumed by the
routine sweep on the next pulse. Editing or pausing a routine voids its
held occurrences, because the approval was for the pre-edit task.
"""

import sqlite3
import threading
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from .approval_cards import (
    ApprovalCardStore,
    ApprovalGate,
    ApprovalGateOutcome,
    ApprovalRequest,
)
from .models import utc_now
from .routine_request import (
    DEFAULT_AUTO_PAUSE_AFTER_DAYS,
    RoutineDraft,
    parse_routine_request,
    validate_routine_draft,
)
from .routine_schedule import RoutineSchedule

MAX_RUNS_PER_ROUTINE = 20
_STALE_RUN_AFTER = timedelta(hours=24)
_INSTALL_MARKER = "_zn_routine_behavior_installed"


@dataclass(slots=True)
class Routine:
    routine_id: str
    intention_id: str
    title: str
    task: str
    owner: str
    schedule_kind: str
    schedule_spec: str
    timezone: str
    input_source: str
    expected_result: str
    approval_boundary: str
    missing_data_policy: str
    auto_pause_after_days: int = DEFAULT_AUTO_PAUSE_AFTER_DAYS
    status: str = "active"  # active | paused
    paused_reason: str | None = None
    last_confirmed_at: str = ""
    last_run_at: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class RoutineRun:
    run_id: str
    routine_id: str
    trigger_kind: str  # scheduled | test_run
    scheduled_at: str
    started_at: str
    finished_at: str | None = None
    status: str = "running"  # running | awaiting_approval | succeeded | failed
    failure_reason: str | None = None
    summary: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class RoutineManager:
    """Routine records + run history on top of the existing trigger organ."""

    def __init__(self, resident):
        self.resident = resident
        self.store = resident.store
        self._lock = threading.RLock()
        # The approval ledger lives in the same SQLite file as the
        # routine tables (daemon's ApprovalCardStore uses the same path),
        # so the routine layer shares that ledger instead of forking it.
        self._approval_store_cache: ApprovalCardStore | None = None
        self._init_schema()

    # -- creation: propose -> confirm -------------------------------------

    def propose(self, text: str) -> dict:
        """One sentence -> a draft carrying all six confirmations."""
        draft = parse_routine_request(text)
        if draft is None:
            raise ValueError("routine request must not be empty")
        return draft.to_dict()

    def confirm(self, raw_draft: dict) -> dict:
        """Validate a (possibly user-edited) draft and create the routine."""
        draft = validate_routine_draft(raw_draft)
        schedule = draft.schedule()
        title = draft.task
        intention = self.resident.intend(
            title,
            source="routine",
            priority=0,
            complete_on_step_success=False,
        )
        try:
            self._register_trigger(intention.intention_id, draft, schedule)
        except Exception:
            try:
                self.resident.will.pause(
                    intention.intention_id,
                    reason="routine trigger registration failed",
                )
            except Exception:
                pass
            raise
        now = utc_now()
        routine_id = f"routine-{uuid.uuid4().hex[:12]}"
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO resident_routines(
                    routine_id,intention_id,title,task,owner,schedule_kind,
                    schedule_spec,timezone,input_source,expected_result,
                    approval_boundary,missing_data_policy,auto_pause_after_days,
                    status,paused_reason,last_confirmed_at,last_run_at,
                    created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,?)
                """,
                (
                    routine_id,
                    intention.intention_id,
                    title,
                    draft.task,
                    draft.owner,
                    draft.schedule_kind,
                    self._schedule_spec(schedule),
                    draft.timezone,
                    draft.input_source,
                    draft.expected_result,
                    draft.approval_boundary,
                    draft.missing_data_policy,
                    draft.auto_pause_after_days,
                    "active",
                    None,
                    now,
                    now,
                    now,
                ),
            )
            conn.commit()
        routine = self.get(routine_id)
        if routine is None:
            raise RuntimeError("routine did not persist")
        self._notify(
            "routine",
            f"I created routine {routine_id}: {title}",
            features=("routine", "created"),
            salience=0.55,
            valence=0.2,
            arousal=0.3,
            metadata={"routine_id": routine_id},
        )
        return self._snapshot(routine_id)

    # -- reads ---------------------------------------------------------------

    def get(self, routine_id: str) -> Routine | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM resident_routines WHERE routine_id=?",
                (str(routine_id),),
            ).fetchone()
        return self._routine_from_row(row) if row else None

    def get_by_intention(self, intention_id: str) -> Routine | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM resident_routines WHERE intention_id=?",
                (str(intention_id),),
            ).fetchone()
        return self._routine_from_row(row) if row else None

    def list_routines(self, *, limit: int = 100) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM resident_routines "
                "ORDER BY created_at DESC, routine_id DESC LIMIT ?",
                (max(1, min(500, int(limit))),),
            ).fetchall()
        return [
            self._snapshot(str(row["routine_id"]))
            for row in rows
            if self._snapshot(str(row["routine_id"])) is not None
        ]

    def snapshot(self, routine_id: str) -> dict:
        """Full snapshot of one routine, including its recent runs."""
        routine = self.get(routine_id)
        if routine is None:
            raise KeyError(f"unknown routine: {routine_id}")
        return self._snapshot(routine_id)

    def runs(self, routine_id: str, *, limit: int = MAX_RUNS_PER_ROUTINE) -> list[dict]:
        routine = self._require(routine_id)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM resident_routine_runs WHERE routine_id=? "
                "ORDER BY started_at DESC, run_id DESC LIMIT ?",
                (routine.routine_id, max(1, min(100, int(limit)))),
            ).fetchall()
        return [self._run_from_row(row).to_dict() for row in rows]

    # -- lifecycle ------------------------------------------------------------

    def pause(self, routine_id: str, *, reason: str | None = None) -> dict:
        routine = self._require(routine_id)
        self._reject_if_engaged(routine, "pause")
        self._pause_row(routine, reason or "paused by user")
        self._notify(
            "routine",
            f"Routine {routine_id} paused",
            features=("routine", "paused"),
            salience=0.5,
            valence=0.0,
            arousal=0.25,
            metadata={"routine_id": routine_id},
        )
        return self._snapshot(routine_id)

    def resume(self, routine_id: str) -> dict:
        routine = self._require(routine_id)
        if routine.status != "paused":
            return self._snapshot(routine_id)
        schedule = self._schedule_of(routine)
        self._register_trigger(routine.intention_id, None, schedule)
        self.resident.will.resume(routine.intention_id)
        now = utc_now()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE resident_routines
                SET status='active',paused_reason=NULL,
                    last_confirmed_at=?,updated_at=?
                WHERE routine_id=?
                """,
                (now, now, routine.routine_id),
            )
            conn.commit()
        self._notify(
            "routine",
            f"Routine {routine_id} resumed",
            features=("routine", "resumed"),
            salience=0.5,
            valence=0.15,
            arousal=0.25,
            metadata={"routine_id": routine_id},
        )
        return self._snapshot(routine_id)

    def edit(self, routine_id: str, *, fields: dict) -> dict:
        routine = self._require(routine_id)
        if not isinstance(fields, dict) or not fields:
            raise ValueError("routine edit requires at least one field")
        allowed = {
            "title",
            "task",
            "owner",
            "input_source",
            "expected_result",
            "approval_boundary",
            "missing_data_policy",
            "auto_pause_after_days",
            "schedule_kind",
            "interval_seconds",
            "cron_expression",
            "timezone",
        }
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise ValueError(f"unknown routine fields: {', '.join(unknown)}")
        merged = routine.to_dict()
        merged.update({key: value for key, value in fields.items() if value is not None})
        # The stored schedule lives in schedule_spec; carry it into validation
        # when the edit does not change the schedule itself.
        if merged.get("schedule_kind") == "interval" and merged.get("interval_seconds") is None:
            merged["interval_seconds"] = int(routine.schedule_spec)
        if merged.get("schedule_kind") == "cron" and not merged.get("cron_expression"):
            merged["cron_expression"] = routine.schedule_spec
        # Reuse the confirm-time validation so an edit cannot smuggle in an
        # unconfirmed draft: all six confirmations must still hold.
        draft = validate_routine_draft(merged)
        schedule = draft.schedule()
        self._register_trigger(routine.intention_id, draft, schedule)
        now = utc_now()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE resident_routines
                SET title=?,task=?,owner=?,schedule_kind=?,schedule_spec=?,
                    timezone=?,input_source=?,expected_result=?,
                    approval_boundary=?,missing_data_policy=?,
                    auto_pause_after_days=?,last_confirmed_at=?,updated_at=?
                WHERE routine_id=?
                """,
                (
                    draft.task,
                    draft.task,
                    draft.owner,
                    draft.schedule_kind,
                    self._schedule_spec(schedule),
                    draft.timezone,
                    draft.input_source,
                    draft.expected_result,
                    draft.approval_boundary,
                    draft.missing_data_policy,
                    draft.auto_pause_after_days,
                    now,
                    now,
                    routine.routine_id,
                ),
            )
            conn.commit()
        # Re-registering the trigger already cleared any stamped pending
        # occurrence; void the held runs so an occurrence approved for
        # the pre-edit task never executes the edited task.
        self._void_held_runs_of_routine(
            routine, "routine edited before approval; occurrence voided"
        )
        return self._snapshot(routine_id)

    def delete(self, routine_id: str) -> dict:
        routine = self._require(routine_id)
        self._reject_if_engaged(routine, "delete")
        triggers = self.resident.recurring_will
        if triggers is not None:
            try:
                triggers.disable(routine.intention_id)
            except Exception:
                pass
        try:
            self.resident.will.complete(
                routine.intention_id,
                summary="routine deleted by user",
            )
        except KeyError:
            pass
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "DELETE FROM resident_routine_held_occurrences WHERE routine_id=?",
                (routine.routine_id,),
            )
            conn.execute(
                "DELETE FROM resident_routine_runs WHERE routine_id=?",
                (routine.routine_id,),
            )
            conn.execute(
                "DELETE FROM resident_routines WHERE routine_id=?",
                (routine.routine_id,),
            )
            conn.commit()
        return {"routine_id": routine.routine_id, "deleted": True}

    def acknowledge(self, routine_id: str) -> dict:
        """The user looked at this routine: reset the auto-pause clock."""
        routine = self._require(routine_id)
        now = utc_now()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "UPDATE resident_routines SET last_confirmed_at=?,updated_at=? "
                "WHERE routine_id=?",
                (now, now, routine.routine_id),
            )
            conn.commit()
        return self._snapshot(routine_id)

    def test_run(self, routine_id: str) -> dict:
        """Execute the routine's task once, now, through the normal Will path.

        This is real execution, not a dry run: the task is handed to Will
        exactly like a scheduled occurrence, and the run row closes on the
        same outcome observation.

        The approval boundary is enforced first. An unrestricted routine
        (empty boundary) executes immediately. A boundary-carrying routine
        whose approval card is still pending returns a run in
        ``awaiting_approval`` without handing anything to Will; the sweep
        resumes it on the next pulse once the card is approved. A denied
        or expired boundary raises instead of executing.
        """
        routine = self._require(routine_id)
        self._reject_if_engaged(routine, "test run")
        intention = self.resident.will.get(routine.intention_id)
        if intention is None:
            raise KeyError(f"unknown resident intention: {routine.intention_id}")
        outcome, request = self._gate_decision(routine)
        if not outcome.allowed:
            if request is not None and request.status == "pending":
                run = self._start_run(
                    routine,
                    trigger_kind="test_run",
                    scheduled_at=None,
                    initial_status="awaiting_approval",
                )
                self._save_held_occurrence(
                    run,
                    routine,
                    request_id=request.request_id,
                    task=routine.task,
                )
                return run.to_dict()
            raise ValueError(
                "routine test run blocked by its approval boundary: "
                f"{outcome.reason}"
            )
        run = self._start_run(routine, trigger_kind="test_run", scheduled_at=None)
        payload = {
            "routine_test_run": True,
            "execution_authority": False,
            "fresh_revalidation_required": True,
        }
        self._enrich_occurrence_payload(payload, routine, run)
        self.resident.will.set_next_step(
            routine.intention_id,
            routine.task,
            payload=payload,
        )
        self._touch_run(routine)
        return run.to_dict()

    # -- run history: open on handoff, close on outcome ------------------------

    def _on_trigger_handoff(self, trigger, payload: dict) -> bool | str | None:
        """Seam called by the trigger organ just before Will handoff.

        Returns None to hand off as before, False to hold the occurrence
        (the trigger organ keeps the pending stamp so the next pulse
        retries and the gate is re-evaluated), or "void" to drop the
        occurrence without handing it to Will. Never raises: a hook
        failure holds the occurrence (fail closed) instead of handing an
        ungated occurrence to Will.
        """
        try:
            return self._on_trigger_handoff_inner(trigger, payload)
        except Exception:
            return False

    def _on_trigger_handoff_inner(
        self, trigger, payload: dict
    ) -> bool | str | None:
        routine = self.get_by_intention(trigger.intention_id)
        if routine is None or routine.status != "active":
            return None
        scheduled_at = str(payload.get("recurring_scheduled_at") or "").strip()
        if not scheduled_at:
            return None
        outcome, request = self._gate_decision(routine)
        run = self._start_run(
            routine,
            trigger_kind="scheduled",
            scheduled_at=scheduled_at,
            initial_status=(
                "awaiting_approval"
                if (not outcome.allowed and request is not None and request.status == "pending")
                else "running"
            ),
        )
        if run.status in ("succeeded", "failed"):
            # A terminal run row for this occurrence means it already
            # ended (e.g. voided earlier); never hand it off again.
            self._delete_held_occurrence(run.run_id)
            return "void"
        if outcome.allowed:
            self._set_run_status(run.run_id, "running")
            self._enrich_occurrence_payload(payload, routine, run)
            self._delete_held_occurrence(run.run_id)
            self._touch_run(routine)
            return None
        if request is not None and request.status == "pending":
            self._set_run_status(run.run_id, "awaiting_approval")
            self._save_held_occurrence(
                run,
                routine,
                request_id=request.request_id,
                task=routine.task,
            )
            return False
        # Denied / expired / undecidable: the occurrence never executes.
        self._fail_run(
            run.run_id, f"routine occurrence voided: {outcome.reason}"
        )
        self._delete_held_occurrence(run.run_id)
        return "void"

    def close_run_from_event(
        self,
        event_id: str,
        *,
        success: bool,
        summary: str,
    ) -> None:
        """Close the run row for a completed event, if it was a routine run."""
        try:
            event = self.resident.store.get_event(event_id)
        except Exception:
            return
        if event is None:
            return
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            return
        run_id = str(payload.get("routine_run_id") or "").strip()
        if not run_id:
            return
        self._close_run(
            run_id,
            success=success,
            summary=summary,
        )

    def sweep(self, *, now: datetime | None = None) -> list[str]:
        """Auto-pause unattended routines + close stale runs. Never raises."""
        try:
            return self._sweep(now=now)
        except Exception:
            return []

    def _sweep(self, *, now: datetime | None = None) -> list[str]:
        current = now or datetime.now(timezone.utc)
        paused: list[str] = []
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM resident_routines WHERE status='active'"
            ).fetchall()
        for row in rows:
            routine = self._routine_from_row(row)
            if self._should_auto_pause(routine, current):
                self._auto_pause(routine, current)
                paused.append(routine.routine_id)
        self._resume_test_run_holds()
        self._close_stale_runs(current)
        return paused

    # -- approval boundary enforcement -------------------------------------

    def _approval_store(self) -> ApprovalCardStore:
        if self._approval_store_cache is None:
            self._approval_store_cache = ApprovalCardStore(self.store.path)
        return self._approval_store_cache

    def _gate_decision(
        self, routine: Routine
    ) -> tuple[ApprovalGateOutcome, ApprovalRequest | None]:
        """Evaluate a routine's approval_boundary through the approval gate.

        An empty boundary means unrestricted: allowed, with no approval
        card and no ledger touch. Otherwise the gate decides from the
        routine's own (kind, scope, target) triple — kind
        ``production_change``, scope ``routine:<routine_id>``, target the
        routine task — so one card (or one auto-allow rule) covers exactly
        this routine's occurrences. The returned request is the gate's
        latest request for the triple, if any.
        """
        if not str(routine.approval_boundary or "").strip():
            return (
                ApprovalGateOutcome(
                    True, reason="approval boundary is empty: unrestricted"
                ),
                None,
            )
        store = self._approval_store()
        gate = ApprovalGate(store)
        outcome = gate.check(
            action_kind="production_change",
            target=routine.task,
            scope=f"routine:{routine.routine_id}",
            value_text=(
                f"Routine {routine.routine_id}: {routine.task}. "
                f"Expected result: {routine.expected_result}. "
                f"Approval boundary: {routine.approval_boundary}"
            ),
            source="routine",
        )
        request = (
            store.get_request(outcome.request_id)
            if outcome.request_id
            else None
        )
        return outcome, request

    @staticmethod
    def _enrich_occurrence_payload(
        payload: dict, routine: Routine, run: RoutineRun
    ) -> None:
        """Add the routine context an occurrence carries into Will."""
        payload["routine_id"] = routine.routine_id
        payload["routine_run_id"] = run.run_id
        payload["routine_owner"] = routine.owner
        payload["routine_approval_boundary"] = routine.approval_boundary
        payload["routine_missing_data_policy"] = routine.missing_data_policy
        payload["routine_expected_result"] = routine.expected_result
        payload["routine_input_source"] = routine.input_source

    def _set_run_status(self, run_id: str, status: str) -> None:
        """Move a run between running and awaiting_approval.

        Moving to running refreshes started_at: execution starts when the
        occurrence is released, not when it was first held.
        """
        now = utc_now()
        with self._lock, closing(self._connect()) as conn:
            if status == "running":
                conn.execute(
                    "UPDATE resident_routine_runs "
                    "SET status='running',started_at=? WHERE run_id=? "
                    "AND status IN ('running','awaiting_approval')",
                    (now, str(run_id)),
                )
            else:
                conn.execute(
                    "UPDATE resident_routine_runs SET status=? WHERE run_id=? "
                    "AND status IN ('running','awaiting_approval')",
                    (status, str(run_id)),
                )
            conn.commit()

    def _fail_run(self, run_id: str, reason: str) -> None:
        """Close a running or held run as failed with a reason."""
        now = utc_now()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE resident_routine_runs
                SET finished_at=?,status='failed',failure_reason=?
                WHERE run_id=? AND status IN ('running','awaiting_approval')
                """,
                (now, str(reason or "").strip() or "运行失败", str(run_id)),
            )
            conn.commit()

    # -- held occurrences --------------------------------------------------

    def _save_held_occurrence(
        self,
        run: RoutineRun,
        routine: Routine,
        *,
        request_id: str,
        task: str,
    ) -> None:
        """Snapshot a held occurrence: the task as approved, plus its card.

        The snapshot task is the source of truth when the occurrence is
        later released, so a routine edit in between cannot swap the
        approved task (edits void held occurrences anyway; this is the
        second lock). A re-save never overwrites the original task, only
        the card id, so a re-evaluation cannot smuggle in a new task.
        """
        now = utc_now()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO resident_routine_held_occurrences(
                    run_id,routine_id,task,approval_request_id,created_at
                ) VALUES(?,?,?,?,?)
                ON CONFLICT(run_id) DO UPDATE SET
                    approval_request_id=excluded.approval_request_id
                """,
                (
                    run.run_id,
                    routine.routine_id,
                    str(task or ""),
                    str(request_id or ""),
                    now,
                ),
            )
            conn.commit()

    def _held_occurrence(self, run_id: str) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM resident_routine_held_occurrences WHERE run_id=?",
                (str(run_id),),
            ).fetchone()
        return dict(row) if row is not None else None

    def _delete_held_occurrence(self, run_id: str) -> None:
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "DELETE FROM resident_routine_held_occurrences WHERE run_id=?",
                (str(run_id),),
            )
            conn.commit()

    def _held_runs(self) -> list[dict]:
        """Awaiting runs joined with their held-occurrence snapshot."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT r.*, h.task AS held_task,
                       h.approval_request_id AS held_request_id
                FROM resident_routine_runs r
                JOIN resident_routine_held_occurrences h
                  ON h.run_id = r.run_id
                WHERE r.status='awaiting_approval'
                ORDER BY r.started_at ASC, r.run_id ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def _void_held_run(
        self,
        held: dict,
        routine: Routine | None,
        reason: str,
        *,
        clear_trigger_pending: bool = False,
    ) -> None:
        """Close a held occurrence as failed and drop its snapshot.

        When ``clear_trigger_pending`` is set (the stale sweep's backstop),
        the trigger organ's pending stamp for a scheduled hold is cleared
        too, so the occurrence is not retried. Callers that already clear
        the stamp themselves (pause/edit/delete re-register or disable
        the trigger) leave it unset.
        """
        run_id = str(held.get("run_id") or "")
        self._fail_run(run_id, reason)
        self._delete_held_occurrence(run_id)
        if (
            clear_trigger_pending
            and routine is not None
            and str(held.get("trigger_kind") or "") == "scheduled"
            and self.resident.recurring_will is not None
        ):
            try:
                self.resident.recurring_will.clear_pending_occurrence(
                    routine.intention_id,
                    scheduled_at=str(held.get("scheduled_at") or ""),
                )
            except Exception:
                # The run is already failed and the snapshot dropped, so
                # the worst case is a later hook retry seeing the
                # terminal run and voiding the occurrence then. Record
                # the miss instead of swallowing it silently.
                self._notify(
                    "routine",
                    f"Routine {routine.routine_id}: could not clear the "
                    "pending stamp for a voided occurrence",
                    features=("routine", "held_occurrence"),
                    salience=0.4,
                    valence=-0.1,
                    arousal=0.2,
                    metadata={"routine_id": routine.routine_id, "run_id": run_id},
                )

    def _void_held_runs_of_routine(self, routine: Routine, reason: str) -> None:
        """Void every held occurrence of one routine.

        Used when the routine is edited or paused: the approval (if any)
        was for the pre-edit task, so held occurrences must not run.
        """
        for held in self._held_runs():
            if str(held.get("routine_id") or "") == routine.routine_id:
                self._void_held_run(held, routine, reason)

    def _resume_test_run_holds(self) -> None:
        """Resume or void test-run holds whose approval card was decided.

        Scheduled holds resume through the trigger organ's retry path
        (the handoff hook re-evaluates the gate on the next pulse), so
        the sweep only handles test-run holds, which have no trigger.
        The intention is checked free BEFORE the gate is consulted, so a
        busy intention never consumes an approved_once approval.
        """
        for held in self._held_runs():
            if str(held.get("trigger_kind") or "") != "test_run":
                continue
            routine = self.get(str(held.get("routine_id") or ""))
            if routine is None or routine.status != "active":
                self._void_held_run(
                    held, routine, "routine is no longer active"
                )
                continue
            intention = self.resident.will.get(routine.intention_id)
            if intention is None:
                self._void_held_run(
                    held, routine, "routine intention is gone"
                )
                continue
            if intention.related_event_id or intention.next_task:
                continue  # busy; retry on a later pulse
            outcome, request = self._gate_decision(routine)
            if outcome.allowed:
                run = RoutineRun(
                    run_id=str(held["run_id"]),
                    routine_id=routine.routine_id,
                    trigger_kind="test_run",
                    scheduled_at=str(held.get("scheduled_at") or ""),
                    started_at=str(held.get("started_at") or ""),
                )
                self._set_run_status(run.run_id, "running")
                payload = {
                    "routine_test_run": True,
                    "execution_authority": False,
                    "fresh_revalidation_required": True,
                }
                self._enrich_occurrence_payload(payload, routine, run)
                self.resident.will.set_next_step(
                    routine.intention_id,
                    str(held.get("held_task") or routine.task),
                    payload=payload,
                )
                self._delete_held_occurrence(run.run_id)
                self._touch_run(routine)
            elif request is not None and request.status == "pending":
                continue  # still waiting on the user
            else:
                self._void_held_run(
                    held,
                    routine,
                    f"routine occurrence voided: {outcome.reason}",
                )

    # -- internals --------------------------------------------------------------

    def _should_auto_pause(self, routine: Routine, current: datetime) -> bool:
        if routine.auto_pause_after_days <= 0:
            return False
        try:
            confirmed = datetime.fromisoformat(
                routine.last_confirmed_at.replace("Z", "+00:00")
            )
        except ValueError:
            return False
        if current - confirmed < timedelta(days=routine.auto_pause_after_days):
            return False
        # Only pause when the routine actually ran since the user last
        # looked at it: silence is not "no response".
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n FROM resident_routine_runs
                WHERE routine_id=? AND finished_at IS NOT NULL
                  AND finished_at > ?
                """,
                (routine.routine_id, routine.last_confirmed_at),
            ).fetchone()
        if not row or int(row["n"]) <= 0:
            return False
        # Never pause under a run that is still in flight.
        intention = self.resident.will.get(routine.intention_id)
        if intention is not None and (
            intention.related_event_id or intention.next_task
        ):
            return False
        return True

    def _auto_pause(self, routine: Routine, current: datetime) -> None:
        reason = (
            "已自动暂停：超过 "
            f"{routine.auto_pause_after_days} 天无人回应；点恢复继续"
        )
        self._pause_row(routine, reason)
        self._notify(
            "routine",
            f"Routine {routine.routine_id} auto-paused: no response for "
            f"{routine.auto_pause_after_days} days",
            features=("routine", "auto_paused"),
            salience=0.7,
            valence=-0.2,
            arousal=0.5,
            metadata={"routine_id": routine.routine_id, "reason": reason},
        )

    def _pause_row(self, routine: Routine, reason: str) -> None:
        triggers = self.resident.recurring_will
        if triggers is not None:
            try:
                triggers.disable(routine.intention_id)
            except Exception:
                pass
        try:
            self.resident.will.pause(routine.intention_id, reason=reason)
        except KeyError:
            pass
        now = utc_now()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE resident_routines
                SET status='paused',paused_reason=?,last_confirmed_at=?,updated_at=?
                WHERE routine_id=?
                """,
                (reason, now, now, routine.routine_id),
            )
            conn.commit()
        # Disabling the trigger already cleared any stamped pending
        # occurrence; void the held runs so they never execute later.
        # The approval (if any) was for the pre-pause state.
        self._void_held_runs_of_routine(
            routine, "routine paused before approval; occurrence voided"
        )

    def _close_stale_runs(self, current: datetime) -> None:
        cutoff = (current - _STALE_RUN_AFTER).isoformat()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE resident_routine_runs
                SET finished_at=?,status='failed',
                    failure_reason='未在 24 小时内收到运行结果'
                WHERE status='running' AND started_at < ?
                """,
                (current.isoformat(), cutoff),
            )
            conn.commit()
        # Backstop for held occurrences the handoff hook / sweep never
        # resolved (e.g. no pulse ran for a day): fail them so they do
        # not linger in awaiting_approval forever. The approval card
        # itself expired after 10 minutes; this only closes the record.
        # Queried from the runs table directly (not the snapshot join)
        # so a held run without a snapshot is closed too.
        with closing(self._connect()) as conn:
            stale_held = conn.execute(
                """
                SELECT * FROM resident_routine_runs
                WHERE status='awaiting_approval' AND started_at < ?
                """,
                (cutoff,),
            ).fetchall()
        for row in stale_held:
            held = dict(row)
            routine = self.get(str(held.get("routine_id") or ""))
            self._void_held_run(
                held,
                routine,
                "等待审批超过 24 小时，occurrence 已作废",
                clear_trigger_pending=True,
            )

    def _start_run(
        self,
        routine: Routine,
        *,
        trigger_kind: str,
        scheduled_at: str | None,
        initial_status: str = "running",
    ) -> RoutineRun:
        if initial_status not in ("running", "awaiting_approval"):
            raise ValueError(f"unsupported initial run status: {initial_status}")
        now = utc_now()
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        scheduled = scheduled_at or now
        with self._lock, closing(self._connect()) as conn:
            # INSERT OR IGNORE makes the trigger-handoff seam crash-safe: a
            # crash between run-row insert and Will handoff reuses the same
            # row on recovery instead of duplicating the occurrence.
            conn.execute(
                """
                INSERT OR IGNORE INTO resident_routine_runs(
                    run_id,routine_id,trigger_kind,scheduled_at,started_at,
                    finished_at,status,failure_reason,summary
                ) VALUES(?,?,?,?,?,NULL,?,NULL,NULL)
                """,
                (run_id, routine.routine_id, trigger_kind, scheduled, now, initial_status),
            )
            existing = conn.execute(
                """
                SELECT * FROM resident_routine_runs
                WHERE routine_id=? AND scheduled_at=? AND trigger_kind=?
                """,
                (routine.routine_id, scheduled, trigger_kind),
            ).fetchone()
            conn.commit()
            # Keep only the latest 20 runs per routine.
            conn.execute(
                """
                DELETE FROM resident_routine_runs
                WHERE routine_id=? AND run_id NOT IN (
                    SELECT run_id FROM resident_routine_runs
                    WHERE routine_id=? ORDER BY started_at DESC, run_id DESC
                    LIMIT ?
                )
                """,
                (routine.routine_id, routine.routine_id, MAX_RUNS_PER_ROUTINE),
            )
            conn.commit()
        if existing is None:
            raise RuntimeError("routine run did not persist")
        return self._run_from_row(existing)

    def _close_run(self, run_id: str, *, success: bool, summary: str) -> None:
        now = utc_now()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """
                UPDATE resident_routine_runs
                SET finished_at=?,status=?,failure_reason=?,summary=?
                WHERE run_id=? AND status='running'
                """,
                (
                    now,
                    "succeeded" if success else "failed",
                    None if success else (str(summary or "").strip() or "运行失败"),
                    str(summary or "")[:2000],
                    str(run_id),
                ),
            )
            conn.commit()

    def _touch_run(self, routine: Routine) -> None:
        now = utc_now()
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                "UPDATE resident_routines SET last_run_at=?,updated_at=? "
                "WHERE routine_id=?",
                (now, now, routine.routine_id),
            )
            conn.commit()

    def _reject_if_engaged(self, routine: Routine, action: str) -> None:
        intention = self.resident.will.get(routine.intention_id)
        if intention is not None and (
            intention.related_event_id or intention.next_task
        ):
            raise ValueError(
                f"routine has a run in flight; wait for it to finish before {action}"
            )

    def _register_trigger(
        self,
        intention_id: str,
        draft: RoutineDraft | None,
        schedule: RoutineSchedule,
    ) -> None:
        triggers = self.resident.recurring_will
        if triggers is None:
            raise RuntimeError("recurring Will triggers are unavailable")
        task = draft.task if draft is not None else None
        if task is None:
            routine = self.get_by_intention(intention_id)
            if routine is None:
                raise RuntimeError("routine task is unknown for re-registration")
            task = routine.task
        if schedule.kind == "interval":
            triggers.register(
                intention_id,
                task=task,
                interval_seconds=int(schedule.interval_seconds or 0),
            )
        else:
            triggers.register(
                intention_id,
                task=task,
                interval_seconds=None,
                schedule_kind="cron",
                cron_expression=schedule.cron_expression,
                tz_name=schedule.timezone,
            )

    def _schedule_of(self, routine: Routine) -> RoutineSchedule:
        if routine.schedule_kind == "interval":
            return RoutineSchedule(
                kind="interval",
                interval_seconds=int(routine.schedule_spec),
                timezone=routine.timezone,
            )
        return RoutineSchedule(
            kind="cron",
            cron_expression=routine.schedule_spec,
            timezone=routine.timezone,
        )

    @staticmethod
    def _schedule_spec(schedule: RoutineSchedule) -> str:
        if schedule.kind == "interval":
            return str(int(schedule.interval_seconds or 0))
        return str(schedule.cron_expression or "")

    def _require(self, routine_id: str) -> Routine:
        routine = self.get(routine_id)
        if routine is None:
            raise KeyError(f"unknown routine: {routine_id}")
        return routine

    def _snapshot(self, routine_id: str) -> dict:
        routine = self.get(routine_id)
        if routine is None:
            return {}
        data = routine.to_dict()
        data["recent_runs"] = self.runs(routine_id, limit=3)
        data["schedule_description"] = self._schedule_of(routine).describe()
        return data

    def _notify(self, channel: str, text: str, **kwargs) -> None:
        try:
            self.resident.nervous.perceive(channel, text, **kwargs)
        except Exception:
            pass

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS resident_routines(
                    routine_id TEXT PRIMARY KEY,
                    intention_id TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    task TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    schedule_kind TEXT NOT NULL,
                    schedule_spec TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    input_source TEXT NOT NULL,
                    expected_result TEXT NOT NULL,
                    approval_boundary TEXT NOT NULL,
                    missing_data_policy TEXT NOT NULL,
                    auto_pause_after_days INTEGER NOT NULL DEFAULT 14,
                    status TEXT NOT NULL DEFAULT 'active',
                    paused_reason TEXT,
                    last_confirmed_at TEXT NOT NULL,
                    last_run_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_routines_status
                    ON resident_routines(status, updated_at);
                CREATE TABLE IF NOT EXISTS resident_routine_runs(
                    run_id TEXT PRIMARY KEY,
                    routine_id TEXT NOT NULL,
                    trigger_kind TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL DEFAULT 'running',
                    failure_reason TEXT,
                    summary TEXT,
                    UNIQUE(routine_id, scheduled_at, trigger_kind),
                    FOREIGN KEY(routine_id) REFERENCES resident_routines(routine_id)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_routine_runs_recent
                    ON resident_routine_runs(routine_id, started_at DESC);
                CREATE TABLE IF NOT EXISTS resident_routine_held_occurrences(
                    run_id TEXT PRIMARY KEY,
                    routine_id TEXT NOT NULL,
                    task TEXT NOT NULL,
                    approval_request_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES resident_routine_runs(run_id)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_routine_held_routine
                    ON resident_routine_held_occurrences(routine_id);
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _routine_from_row(row: sqlite3.Row) -> Routine:
        return Routine(
            routine_id=str(row["routine_id"]),
            intention_id=str(row["intention_id"]),
            title=str(row["title"]),
            task=str(row["task"]),
            owner=str(row["owner"]),
            schedule_kind=str(row["schedule_kind"]),
            schedule_spec=str(row["schedule_spec"]),
            timezone=str(row["timezone"]),
            input_source=str(row["input_source"]),
            expected_result=str(row["expected_result"]),
            approval_boundary=str(row["approval_boundary"]),
            missing_data_policy=str(row["missing_data_policy"]),
            auto_pause_after_days=int(row["auto_pause_after_days"] or 0),
            status=str(row["status"]),
            paused_reason=(
                str(row["paused_reason"]) if row["paused_reason"] else None
            ),
            last_confirmed_at=str(row["last_confirmed_at"] or ""),
            last_run_at=str(row["last_run_at"]) if row["last_run_at"] else None,
            created_at=str(row["created_at"] or ""),
            updated_at=str(row["updated_at"] or ""),
        )

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> RoutineRun:
        return RoutineRun(
            run_id=str(row["run_id"]),
            routine_id=str(row["routine_id"]),
            trigger_kind=str(row["trigger_kind"]),
            scheduled_at=str(row["scheduled_at"]),
            started_at=str(row["started_at"]),
            finished_at=str(row["finished_at"]) if row["finished_at"] else None,
            status=str(row["status"]),
            failure_reason=(
                str(row["failure_reason"]) if row["failure_reason"] else None
            ),
            summary=str(row["summary"]) if row["summary"] else None,
        )


def install_routine_behavior(resident) -> None:
    """Attach natural-language routines to the existing product Resident.

    Requires the recurring Will triggers (the "when") to already be
    installed; this layer adds the six confirmations, run history, and
    lifecycle on top of them.
    """

    if getattr(resident, _INSTALL_MARKER, False):
        return
    if not hasattr(resident, "will"):
        raise ValueError("routine behavior requires the existing NativeWill")
    if getattr(resident, "recurring_will", None) is None:
        raise ValueError(
            "routine behavior requires install_recurring_will_behavior first"
        )

    manager = RoutineManager(resident)
    triggers = resident.recurring_will
    triggers._on_handoff = manager._on_trigger_handoff

    original_observe = resident.will.observe_event_outcome

    def observe_event_outcome(intention_id, **kwargs):
        result = original_observe(intention_id, **kwargs)
        # The run row closes on the same outcome observation that closes the
        # Will step. A failure here must never break the Will path.
        try:
            manager.close_run_from_event(
                str(kwargs.get("event_id") or ""),
                success=bool(kwargs.get("success", False)),
                summary=str(kwargs.get("summary") or ""),
            )
        except Exception:
            pass
        return result

    resident.will.observe_event_outcome = observe_event_outcome

    original_pulse = resident.pulse
    original_status = resident.status

    def pulse():
        result = original_pulse()
        # Routine bookkeeping must never replace the Resident life loop.
        try:
            manager.sweep()
        except Exception:
            pass
        return result

    def status():
        data = original_status()
        items = manager.list_routines(limit=100)
        data["routines"] = {
            "routine_count": len(items),
            "active_count": sum(1 for item in items if item.get("status") == "active"),
            "paused_count": sum(1 for item in items if item.get("status") == "paused"),
            "needs_attention": [
                item["routine_id"]
                for item in items
                if item.get("status") == "paused"
                and str(item.get("paused_reason") or "").startswith("已自动暂停")
            ],
            "routines": items,
        }
        return data

    resident.routines = manager
    resident.pulse = pulse
    resident.status = status
    setattr(resident, _INSTALL_MARKER, True)


__all__ = [
    "Routine",
    "RoutineManager",
    "RoutineRun",
    "install_routine_behavior",
]
