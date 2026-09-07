from __future__ import annotations

"""Explicit control-plane authority for Work restore, continuation, and steering."""

import re
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any

from .evidence_bound_work import EvidenceBoundSteerableWorkLedger
from .route_policy_intake import bind_work_event_route_policy
from .steerable_work import SteerableWorkLedger
from .work import WorkMessage
from .work_control import ResidentWorkControl


_CONTINUE = re.compile(r"(?:继续做|接着做|继续|接着)")
_LATEST_REFERENCE = ("刚才", "刚刚", "上次", "之前那个", "前面那个")
_YESTERDAY_REFERENCE = ("昨天", "昨日")
_STEERING_CUES = (
    "先别",
    "别做",
    "不要",
    "不做",
    "先把",
    "先做",
    "改成",
    "改简单",
    "简单一点",
    "简化",
    "暂停",
    "暂时不",
)
_CONTEXT_TASK_LIMIT = 500
_CONTEXT_RESULT_LIMIT = 500
_CONTEXT_FOLLOWUP_LIMIT = 1000


class RestoreAwareWorkControl(ResidentWorkControl):
    """Reconnect natural references to durable Work and steer explicit plan changes.

    Bare continuation reconnects to the exact active event. An explicit plan
    change such as ``登录先别做，先把核心记账跑起来`` increments the same Root
    Work's plan version and supersedes the old active plan. Completed Work
    follow-ups still start a fresh event without replaying the completed event.
    """

    def __init__(self, ledger):
        # The daemon historically constructs RecoveryBoundedWorkLedger directly.
        # Upgrade that face onto the same resident/store rather than creating a
        # second Work product or scheduler. Both objects point at the same SQLite
        # truth; this control surface owns the steerable path immediately.
        if not isinstance(ledger, EvidenceBoundSteerableWorkLedger):
            ledger = EvidenceBoundSteerableWorkLedger(ledger.resident)
        super().__init__(ledger)
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
        normalized = " ".join(str(task or "").strip().split())
        match = _CONTINUE.search(normalized)
        if match is None:
            return None
        followup = normalized[match.end() :].lstrip(" ，,。；;:：-—\t")
        return followup or None

    @classmethod
    def active_steering_followup(cls, task: str) -> str | None:
        """Recognize explicit active-plan edits without treating every suffix as steering."""
        followup = cls.continuation_followup(task)
        if followup is None:
            return None
        return followup if any(cue in followup for cue in _STEERING_CUES) else None

    def start(self, thread_id: str, task: str, **kwargs):
        reference = self.continuation_reference(task)
        if reference is None:
            return super().start(thread_id, task, **kwargs)

        self.reconcile_cancelled_runs()
        thread = self._referenced_thread(reference)
        active = self.ledger._active_run_for_thread(thread.thread_id)
        followup = self.continuation_followup(task)
        if active is not None:
            steering = self.active_steering_followup(task)
            if steering is not None:
                return self._steer_referenced_active_work(
                    thread,
                    active,
                    task,
                    followup=steering,
                    reference=reference,
                    ingress_thread_id=thread_id,
                    start_kwargs=kwargs,
                )
            if followup is not None:
                raise ValueError(
                    "the referenced Work is still active; the new instruction is not an explicit plan change, so ZN will not silently reinterpret or drop it"
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

    def _steer_referenced_active_work(
        self,
        thread,
        active,
        task: str,
        *,
        followup: str,
        reference: str,
        ingress_thread_id: str,
        start_kwargs: dict[str, Any],
    ):
        kwargs = dict(start_kwargs)
        raw_payload = kwargs.pop("payload", None)
        if raw_payload is not None and not isinstance(raw_payload, dict):
            raise ValueError("work steering payload must be an object")
        kind = str(kwargs.pop("kind", "desktop_user_event") or "desktop_user_event")
        priority = int(kwargs.pop("priority", 0) or 0)
        if kwargs:
            raise TypeError(
                f"unsupported Work steering options: {', '.join(sorted(kwargs))}"
            )

        bounded_followup = self._bounded_context_text(
            followup,
            limit=_CONTEXT_FOLLOWUP_LIMIT,
        )
        payload = dict(raw_payload or {})

        # Steering creates the next ResidentEvent through the plan transition
        # path rather than ordinary Work.start(). Preserve the same Work-owned
        # privacy boundary before that event can be materialized: first reject
        # an already-unsteerable live state, then validate/merge durable thread
        # policy and copy it into the exact next-event payload. The ledger still
        # repeats its own state check and owns the atomic plan transition.
        self.ledger._assert_steerable_resident_state(active.event_id)
        durable_thread = self.ledger.get_thread(thread.thread_id)
        if durable_thread is None:
            raise RuntimeError("active Work steering lost its durable WorkThread")
        bind_work_event_route_policy(
            self.ledger,
            durable_thread,
            task=task,
            event_payload=payload,
        )

        snapshot, event = self.ledger.steer_active(
            thread.thread_id,
            active.event_id,
            task,
            objective=bounded_followup,
            reference=reference,
            kind=kind,
            priority=priority,
            payload=payload,
        )
        normalized_ingress = self.ledger._normalize_thread_id(ingress_thread_id)
        if normalized_ingress != thread.thread_id:
            self._continuation_ingress_aliases[event.event_id] = normalized_ingress
        return snapshot, event

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
