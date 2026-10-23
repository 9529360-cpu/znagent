from __future__ import annotations

"""Formal Resident RPC projection for bounded recurring Will intentions.

This is a control-surface extension only. Scheduling authority remains in the
Resident-owned recurring Will organ installed by the product runtime; execution
still flows through Will -> Situation/Thought -> existing Event/Work -> Body.
No RPC request can persist Body arguments or reusable execution authority.
"""

from dataclasses import asdict
from typing import Any

from .browser_rpc import BrowserResidentRpcServer


class RecurringWillResidentRpcServer(BrowserResidentRpcServer):
    """Add bounded recurring-intention controls to the formal product RPC."""

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        method = str(request.get("method") or "").strip()
        if not method.startswith("recurring_"):
            return super().handle(request)

        request_id = request.get("id")
        params = request.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError("params must be an object")

        triggers = getattr(self.resident, "recurring_will", None)
        if triggers is None:
            raise ValueError("resident has no recurring Will organ")

        if method == "recurring_schedule":
            description = str(params.get("description") or "").strip()
            task = str(params.get("task") or "").strip()
            if not description:
                raise ValueError("recurring_schedule requires description")
            if not task:
                raise ValueError("recurring_schedule requires task")
            try:
                interval_seconds = int(params.get("interval_seconds"))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "recurring_schedule requires integer interval_seconds"
                ) from exc
            schedule = getattr(self.resident, "schedule_recurring_intention", None)
            if not callable(schedule):
                raise ValueError("resident recurring Will scheduling is unavailable")
            first_due_at = params.get("first_due_at")
            intention = schedule(
                description,
                task=task,
                interval_seconds=interval_seconds,
                source=str(params.get("source") or "user").strip() or "user",
                priority=int(params.get("priority") or 0),
                first_due_at=(
                    str(first_due_at).strip()
                    if first_due_at is not None and str(first_due_at).strip()
                    else None
                ),
            )
            trigger = triggers.get(intention.intention_id)
            if trigger is None:
                raise RuntimeError("recurring Will trigger disappeared after scheduling")
            result = self._recurring_projection(trigger)
        elif method == "recurring_list":
            result = [
                self._recurring_projection(trigger)
                for trigger in triggers.list(
                    enabled_only=bool(params.get("enabled_only", False)),
                    limit=max(1, min(100, int(params.get("limit") or 20))),
                )
            ]
        elif method == "recurring_disable":
            intention_id = str(params.get("intention_id") or "").strip()
            if not intention_id:
                raise ValueError("recurring_disable requires intention_id")
            trigger = triggers.disable(intention_id)
            if trigger is None:
                raise ValueError("unknown recurring intention")
            result = self._recurring_projection(trigger)
        else:
            raise ValueError(f"unknown method: {method}")

        return {"id": request_id, "ok": True, "result": result}

    def _recurring_projection(self, trigger) -> dict[str, Any]:
        intention = self.resident.will.get(trigger.intention_id)
        return {
            "intention_id": trigger.intention_id,
            "description": (
                intention.description if intention is not None else None
            ),
            "source": intention.source if intention is not None else None,
            "priority": intention.priority if intention is not None else 0,
            "status": intention.status if intention is not None else "missing",
            "current_step": (
                intention.current_step if intention is not None else None
            ),
            "next_task": intention.next_task if intention is not None else None,
            "trigger": asdict(trigger),
            "execution_authority": False,
            "fresh_revalidation_required": True,
        }
