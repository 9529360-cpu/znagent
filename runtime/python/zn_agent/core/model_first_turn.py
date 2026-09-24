from __future__ import annotations

"""Model-first user-turn ingress over the existing ZN runtime.

Ordinary user messages reach the configured model before Resident Work is
materialized. The model may answer directly or hand the request to the existing
durable Work runtime. Stop/cancel and active-Work steering remain local control
boundaries and do not depend on a model round-trip.
"""

import uuid
from typing import Any

from .route_policy_intake import bind_work_event_route_policy
from .structured_proposal import looks_like_structured_payload, parse_exact_json_payload
from .work import WorkMessage, title_for_work_task


class ModelFirstTurnError(RuntimeError):
    pass


class ModelFirstTurnService:
    _HISTORY_LIMIT = 8
    _HISTORY_TEXT_LIMIT = 6000
    _OBJECTIVE_LIMIT = 1200
    _ACK_LIMIT = 1000

    def __init__(self, resident, work_control):
        self.resident = resident
        self.work_control = work_control
        self.ledger = work_control.ledger

    def submit(
        self,
        thread_id: str,
        text: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = str(text or "").strip()
        if not normalized:
            raise ValueError("turn_submit requires text")

        thread = self.ledger.create_thread(thread_id=thread_id)
        active = self.ledger._active_run_for_thread(thread.thread_id)
        if active is not None:
            snapshot, event = self.work_control.start(
                thread.thread_id,
                normalized,
                kind="desktop_user_event",
                priority=0,
                payload=payload,
            )
            return self._work_result(snapshot, event, steering=True)

        route_payload = dict(payload or {})
        route_policy = bind_work_event_route_policy(
            self.ledger,
            thread,
            task=normalized,
            event_payload=route_payload,
        )
        history = self._conversation_history(thread.thread_id)
        workspace = self.ledger.workspace_for(thread)
        turn_context: dict[str, Any] = {
            "conversation": history,
            "workspace": {
                "attached": workspace is not None,
                "name": workspace.name if workspace is not None else None,
            },
        }
        memory = getattr(self.resident, "memory", None)
        project_memory = getattr(memory, "project_cognition_memory", None)
        if callable(project_memory):
            user_history = tuple(
                item["text"] for item in history if item.get("role") == "user"
            )[-2:]
            projected = project_memory(
                normalized,
                history=user_history,
                allow_memory=route_payload.get("allow_memory", True) is True,
            )
            if projected is not None:
                turn_context["resident_memory"] = projected
        metadata: dict[str, Any] = {
            "model_first_turn": True,
            "cognition_request": {"context": turn_context},
        }
        if route_policy is not None:
            metadata["route_policy"] = route_policy

        result = self.resident.kernel.run_goal(
            normalized,
            required_capabilities=("general",),
            priority=0,
            metadata=metadata,
            max_attempts_override=1,
            goal_id=f"turn-{uuid.uuid4().hex[:12]}",
        )
        if not result.worker_result.success:
            raise ModelFirstTurnError(
                result.worker_result.error or "model-first turn failed"
            )

        response = str(result.worker_result.response or "").strip()
        decision = self._work_decision(response)
        if decision is not None:
            objective, ack = decision
            snapshot, event = self.work_control.start(
                thread.thread_id,
                normalized,
                kind="desktop_user_event",
                priority=0,
                payload=payload,
                objective=objective,
            )
            if ack:
                durable_thread = self.ledger.get_thread(thread.thread_id)
                if durable_thread is not None:
                    self._append_message(
                        durable_thread,
                        role="zn",
                        text=ack,
                        detail={"model_first_handoff": True},
                    )
                    snapshot = self.work_control.get_snapshot(durable_thread.thread_id)
            return self._work_result(snapshot, event, steering=False, ack=ack)

        if looks_like_structured_payload(response, top_level_key="zn_work"):
            raise ModelFirstTurnError("model returned an invalid Work handoff")

        thread = self.ledger.get_thread(thread.thread_id) or thread
        self._ensure_title(thread, normalized)
        self._append_message(thread, role="user", text=normalized)
        self._append_message(
            thread,
            role="zn",
            text=response,
            detail={"model_first_reply": True},
        )
        snapshot = self.work_control.get_snapshot(thread.thread_id)
        return {
            "mode": "reply",
            "thread": snapshot,
            "reply": response,
        }

    def _conversation_history(self, thread_id: str) -> list[dict[str, str]]:
        messages = self.ledger.list_messages(thread_id, limit=self._HISTORY_LIMIT)
        remaining = self._HISTORY_TEXT_LIMIT
        history: list[dict[str, str]] = []
        for message in reversed(messages):
            if remaining <= 0:
                break
            text = str(message.text or "").strip()
            if not text or message.role not in {"user", "zn"}:
                continue
            bounded = text[:remaining]
            history.append(
                {
                    "role": "user" if message.role == "user" else "assistant",
                    "text": bounded,
                }
            )
            remaining -= len(bounded)
        history.reverse()
        return history

    def _work_decision(self, response: str) -> tuple[str, str] | None:
        parsed = parse_exact_json_payload(response)
        if not isinstance(parsed, dict) or "zn_work" not in parsed:
            return None
        if set(parsed) != {"zn_work"}:
            raise ModelFirstTurnError(
                "model Work handoff has unsupported top-level fields"
            )
        raw = parsed.get("zn_work")
        if not isinstance(raw, dict):
            raise ModelFirstTurnError("model Work handoff must be an object")
        if not set(raw).issubset({"objective", "ack"}):
            raise ModelFirstTurnError("model Work handoff has unsupported fields")
        objective = " ".join(str(raw.get("objective") or "").strip().split())
        if not objective:
            raise ModelFirstTurnError("model Work handoff is missing objective")
        if len(objective) > self._OBJECTIVE_LIMIT:
            raise ModelFirstTurnError("model Work objective is too long")
        ack = " ".join(str(raw.get("ack") or "").strip().split())[: self._ACK_LIMIT]
        return objective, ack

    def _append_message(
        self,
        thread,
        *,
        role: str,
        text: str,
        detail: dict[str, Any] | None = None,
    ) -> WorkMessage:
        message = WorkMessage(
            message_id=f"msg-{uuid.uuid4().hex[:16]}",
            thread_id=thread.thread_id,
            role=role,
            text=str(text),
            detail=dict(detail or {}),
        )
        self.ledger._append(thread, message)
        return message

    def _ensure_title(self, thread, text: str) -> None:
        if (
            thread.title != "New work"
            or self.ledger.list_messages(thread.thread_id, limit=1)
        ):
            return
        thread.title = title_for_work_task(text)
        self.ledger._save_thread(thread)

    def _work_result(
        self,
        snapshot,
        event,
        *,
        steering: bool,
        ack: str = "",
    ) -> dict[str, Any]:
        thread_id = str(event.payload.get("work_thread_id") or "").strip()
        progress = self.work_control.progress(thread_id, event.event_id)
        if progress.get("finalized"):
            snapshot = self.work_control.get_snapshot(thread_id)
        return {
            "mode": "work",
            "thread": snapshot,
            "progress": progress,
            "steering": bool(steering),
            "reply": ack,
        }
