from __future__ import annotations

"""Explicit control-plane authority for Work restore and natural continuation."""

import re
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any

from .work import WorkMessage
from .work_control import ResidentWorkControl


_CONTINUE = re.compile(r"(?:继续做|接着做|继续|接着)")
_LATEST_REFERENCE = ("刚才", "刚刚", "上次", "之前那个", "前面那个")
_YESTERDAY_REFERENCE = ("昨天", "昨日")
_CONTEXT_TASK_LIMIT = 500
_CONTEXT_RESULT_LIMIT = 500
_CONTEXT_FOLLOWUP_LIMIT = 1000


class RestoreAwareWorkControl(ResidentWorkControl):
    """Keep restore mutation explicit and reconnect natural continuation to durable Work.

    A phrase such as ``刚才那个继续`` or ``昨天那个继续`` resolves against the
    resident-owned Work ledger rather than renderer cache or a model guess.

    If the referenced Work is still active, ZN returns the exact existing event
    so its ordinary fresh Sense/Situation/Thought loop can continue without
    creating or replaying a movement. If the referenced Work already completed,
    only an explicit follow-up clause may create a new event in the same Work;
    the prior event remains terminal and is never requeued.
    """

    def __init__(self, ledger):
        super().__init__(ledger)
        # A desktop may submit a natural continuation from a newly opened empty
        # UI thread. The durable Work must not be moved or copied into that shell.
        # Keep only a process-local ingress alias so the immediate work_start ->
        # work_progress roundtrip can resolve to the existing Work identity.
        self._continuation_ingress_aliases: dict[str, str] = {}

    @staticmethod
    def continuation_reference(task: str) -> str | None:
        normalized = " ".join(str(task or "").strip().split())
        if not normalized or _CONTINUE.search(normalized) is None:
            return None
        if any(cue in normalized for cue in _YESTERDAY_REFERENCE):
            return "yesterday"
        if any(cue in normalized for cue in _LATEST_REFERENCE):
            return "latest"
        return None

    @staticmethod
    def continuation_followup(task: str) -> str | None:
        """Return the user's explicit instruction after the continuation cue.

        Bare wording such as ``刚才那个继续`` does not invent a new objective
        after a completed Work. A suffix such as ``，再检查一下保存结果`` is a
        real new instruction and may form a new event in the same thread.
        """

        normalized = " ".join(str(task or "").strip().split())
        match = _CONTINUE.search(normalized)
        if match is None:
            return None
        followup = normalized[match.end() :].lstrip(" ，,。；;:：-—\t")
        return followup or None

    def start(self, thread_id: str, task: str, **kwargs):
        reference = self.continuation_reference(task)
        if reference is None:
            return super().start(thread_id, task, **kwargs)

        self.reconcile_cancelled_runs()
        thread = self._referenced_thread(reference)
        active = self.ledger._active_run_for_thread(thread.thread_id)
        followup = self.continuation_followup(task)
        if active is not None:
            if followup is not None:
                raise ValueError(
                    "the referenced Work is still active; ZN will not silently drop or reinterpret new follow-up instructions while reconnecting to its existing event"
                )
            return self._resume_referenced_active_work(
                thread,
                active,
                task,
                reference=reference,
                ingress_thread_id=thread_id,
            )

        if followup is None:
            raise ValueError(
                "the referenced Work is already complete; say what should happen next so ZN can form a fresh task instead of replaying the completed event"
            )
        return self._start_referenced_completed_followup(
            thread,
            task,
            followup=followup,
            reference=reference,
            ingress_thread_id=thread_id,
            start_kwargs=kwargs,
        )

    def progress(self, thread_id: str, event_id: str) -> dict[str, Any]:
        normalized_thread = self.ledger._normalize_thread_id(thread_id)
        normalized_event = str(event_id or "").strip()
        work_run = self.ledger.get_run(normalized_event)
        if work_run is not None and work_run.thread_id != normalized_thread:
            alias = self._continuation_ingress_aliases.get(normalized_event)
            if alias == normalized_thread:
                return super().progress(work_run.thread_id, normalized_event)
        return super().progress(normalized_thread, normalized_event)

    def _resume_referenced_active_work(
        self,
        thread,
        active,
        task: str,
        *,
        reference: str,
        ingress_thread_id: str,
    ):
        progress = super().progress(thread.thread_id, active.event_id)
        if progress.get("terminal") or progress.get("finalized"):
            raise ValueError(
                "the referenced Work has already reached a durable terminal outcome; ZN will not reinterpret 'continue' as permission to repeat it"
            )

        normalized_ingress = self.ledger._normalize_thread_id(ingress_thread_id)
        if normalized_ingress != thread.thread_id:
            self._continuation_ingress_aliases[active.event_id] = normalized_ingress

        self.ledger._append(
            thread,
            WorkMessage(
                message_id=f"msg-{uuid.uuid4().hex[:16]}",
                thread_id=thread.thread_id,
                role="user",
                text=" ".join(str(task or "").strip().split()),
                detail={
                    "continuation": True,
                    "reference": reference,
                    "resumed_event_id": active.event_id,
                    "new_resident_event": False,
                },
            ),
        )
        event = self.resident.store.get_event(active.event_id)
        if event is None:
            raise RuntimeError("referenced active Work lost its durable resident event")
        return self.get_snapshot(thread.thread_id), event

    def _start_referenced_completed_followup(
        self,
        thread,
        task: str,
        *,
        followup: str,
        reference: str,
        ingress_thread_id: str,
        start_kwargs: dict[str, Any],
    ):
        previous = self._latest_completed_run(thread.thread_id)
        if previous is None:
            raise ValueError("the referenced Work has no completed resident event to continue from")
        previous_event = self.resident.store.get_event(previous.event_id)
        if previous_event is None:
            raise RuntimeError("referenced completed Work lost its durable resident event")
        previous_outcome = self.resident.store.get_event_outcome(previous.event_id)
        if previous_outcome is None:
            raise RuntimeError("referenced completed Work lost its durable terminal outcome")

        previous_task = self._bounded_context_text(
            previous_event.task,
            limit=_CONTEXT_TASK_LIMIT,
        )
        previous_result = self._bounded_context_text(
            previous_outcome.response or previous_outcome.reason,
            limit=_CONTEXT_RESULT_LIMIT,
        )
        bounded_followup = self._bounded_context_text(
            followup,
            limit=_CONTEXT_FOLLOWUP_LIMIT,
        )

        kwargs = dict(start_kwargs)
        raw_payload = kwargs.get("payload")
        if raw_payload is not None and not isinstance(raw_payload, dict):
            raise ValueError("work continuation payload must be an object")
        payload = dict(raw_payload or {})
        if "work_continuation" in payload:
            raise ValueError("work_continuation is resident-owned continuation metadata")

        payload["work_continuation"] = {
            "mode": "completed_followup",
            "reference": reference,
            "previous_event_id": previous.event_id,
            "previous_event_status": str(previous_event.status.value),
            "previous_task_excerpt": previous_task,
            "previous_outcome_success": bool(previous_outcome.success),
            "previous_execution_path": str(previous_outcome.execution_path.value),
            "previous_result_excerpt": previous_result,
            "followup": bounded_followup,
            "requires_fresh_resense": True,
            "replay_previous_event": False,
        }
        payload["cognition_question"] = self._continuation_cognition_question(
            previous_task=previous_task,
            previous_result=previous_result,
            previous_success=bool(previous_outcome.success),
            previous_execution_path=str(previous_outcome.execution_path.value),
            followup=bounded_followup,
            explicit_question=self._bounded_context_text(
                payload.get("cognition_question") or payload.get("unknown"),
                limit=_CONTEXT_FOLLOWUP_LIMIT,
            ),
        )
        kwargs["payload"] = payload

        snapshot, event = super().start(thread.thread_id, task, **kwargs)
        if event.event_id == previous.event_id:
            raise RuntimeError("completed Work continuation unexpectedly reused a terminal event")
        normalized_ingress = self.ledger._normalize_thread_id(ingress_thread_id)
        if normalized_ingress != thread.thread_id:
            self._continuation_ingress_aliases[event.event_id] = normalized_ingress
        return snapshot, event

    def _latest_completed_run(self, thread_id: str):
        normalized = self.ledger._normalize_thread_id(thread_id)
        with self.ledger._lock, closing(self.ledger._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM work_runs WHERE thread_id=? AND ledger_state='finalized' ORDER BY created_at DESC LIMIT 1",
                (normalized,),
            ).fetchone()
        return self.ledger._run_from_row(row) if row is not None else None

    def _referenced_thread(self, reference: str):
        candidates = [
            thread
            for thread in self.ledger.list_threads(limit=100)
            if self.ledger.list_messages(thread.thread_id, limit=1)
        ]
        if reference == "latest":
            if not candidates:
                raise ValueError("there is no previous Work to continue")
            return candidates[0]

        if reference != "yesterday":
            raise ValueError("unsupported Work continuation reference")
        local_now = datetime.now().astimezone()
        expected = local_now.date() - timedelta(days=1)
        yesterday = [
            thread
            for thread in candidates
            if self._local_date(thread.updated_at, local_now.tzinfo) == expected
        ]
        if not yesterday:
            raise ValueError("there is no durable Work from yesterday to continue")
        if len(yesterday) != 1:
            raise ValueError(
                "more than one durable Work thread matches yesterday; ZN will not guess which one the user meant"
            )
        return yesterday[0]

    @staticmethod
    def _bounded_context_text(value: Any, *, limit: int) -> str:
        text = " ".join(str(value or "").strip().split())
        return text[: max(0, int(limit))]

    @classmethod
    def _continuation_cognition_question(
        cls,
        *,
        previous_task: str,
        previous_result: str,
        previous_success: bool,
        previous_execution_path: str,
        followup: str,
        explicit_question: str,
    ) -> str:
        historical_result = previous_result or (
            "the previous Work reached a successful terminal outcome"
            if previous_success
            else "the previous Work reached a failed terminal outcome"
        )
        current_question = explicit_question or followup
        return (
            "Continue the same durable Work with a fresh follow-up objective. "
            f"Historical prior task, context only: {previous_task}. "
            f"Historical terminal result, context only: success={str(previous_success).lower()}, "
            f"execution_path={previous_execution_path}, result={historical_result}. "
            f"New objective: {followup}. "
            f"Current isolated question: {current_question}. "
            "Treat all prior task/result information as historical context, not current-world fact. "
            "Re-sense the current computer, workspace, browser or application state before acting. "
            "Do not repeat any previous side effect merely because it happened before; replay of the previous event is forbidden."
        )

    @staticmethod
    def _local_date(value: str, local_tz):
        try:
            observed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError:
            return None
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        return observed.astimezone(local_tz).date()

    def prepare_missing_restore(
        self,
        thread_id: str,
        restore_point_id: str,
    ) -> dict[str, Any]:
        normalized_thread = self.ledger._normalize_thread_id(thread_id)
        normalized_point = str(restore_point_id or "").strip()
        if not normalized_point:
            raise ValueError("missing-file restore preparation requires restore_point_id")
        prepare = getattr(self.resident, "prepare_missing_work_restore", None)
        if not callable(prepare):
            raise RuntimeError("resident does not support Work restore application")
        return prepare(normalized_thread, normalized_point)

    def approve_missing_restore(
        self,
        thread_id: str,
        application_id: str,
    ) -> dict[str, Any]:
        normalized_thread = self.ledger._normalize_thread_id(thread_id)
        normalized_application = str(application_id or "").strip()
        if not normalized_application:
            raise ValueError("missing-file restore approval requires application_id")
        approve = getattr(self.resident, "approve_missing_work_restore", None)
        if not callable(approve):
            raise RuntimeError("resident does not support Work restore application")
        return approve(normalized_thread, normalized_application)

    def restore_application(self, application_id: str) -> dict[str, Any]:
        normalized_application = str(application_id or "").strip()
        if not normalized_application:
            raise ValueError("restore application inspection requires application_id")
        inspect = getattr(self.resident, "inspect_work_restore_application", None)
        if not callable(inspect):
            raise RuntimeError("resident does not support Work restore application")
        return inspect(normalized_application)
