from __future__ import annotations

"""Autonomous Root acceptance formation for broad attached-workspace goals.

This layer does not add a planner, scheduler, worker runtime, or store. When one
active Root Work has an attached workspace but no acceptance criteria yet, ZN
borrows one bounded cognition increment to define observable success criteria,
persists them once into the existing WorkItem, and only then enters the mature
research/write/run/verify loop.
"""

import json
from contextlib import closing

from .broad_goal_completion_resident import BroadGoalCompletionResidentRuntime
from .cognition import CognitiveIncrement
from .models import utc_now
from .steerable_work import WorkItem


class BroadGoalAutonomousResidentRuntime(BroadGoalCompletionResidentRuntime):
    """Let ZN form the Root contract from a broad goal before executing it."""

    _ROOT_ACCEPTANCE_MARKER = "Before any execution, define the Root acceptance contract."
    _MIN_ROOT_CRITERIA = 2
    _MAX_ROOT_CRITERIA = 8
    _MAX_CRITERION_CHARS = 500

    def _autonomous_root_candidate(self, event) -> WorkItem | None:
        payload = event.payload if isinstance(getattr(event, "payload", None), dict) else {}
        thread_id = str(payload.get("work_thread_id") or "").strip()
        item_id = str(payload.get("work_item_id") or "").strip()
        if not thread_id or not item_id or not payload.get("workspace_path"):
            return None
        root = self.work_ledger.work_item_for_event(event.event_id)
        run = self.work_ledger.get_run(event.event_id)
        if root is None or run is None:
            return None
        if (
            root.work_item_id != item_id
            or root.work_thread_id != thread_id
            or root.parent_work_item_id is not None
            or root.acceptance_criteria
            or run.thread_id != thread_id
            or run.ledger_state != "active"
        ):
            return None
        current_version = self.work_ledger.plan_version(thread_id)
        if (
            root.plan_version != current_version
            or self.work_ledger._run_plan_version(event.event_id) != current_version
        ):
            return None
        return root

    def _build_cognition_request(self, event, impasse, required, deliberation=None):
        request = super()._build_cognition_request(event, impasse, required, deliberation)
        root = self._autonomous_root_candidate(event)
        if root is None:
            return request

        request.question = (
            "You are a bounded cognitive resource assisting one durable ZN Root Work. "
            "ZN owns lifecycle, tools, permissions, execution, evidence, steering, and completion. "
            f"{self._ROOT_ACCEPTANCE_MARKER} "
            "Return ONLY one JSON object shaped exactly as "
            '{"zn_root_acceptance":{"criteria":["observable criterion", "observable criterion"]}}. '
            f"Provide {self._MIN_ROOT_CRITERIA}-{self._MAX_ROOT_CRITERIA} concise criteria. "
            "Each criterion must describe user-visible or independently observable success, not an implementation "
            "recipe, model/tool action, or claim that work is already done. Cover the requested runnable core "
            "behavior and any durability/restart behavior that the user actually asked for. Respect explicit "
            "scope exclusions and simplicity constraints. Do not provide source code, shell commands, URLs, or "
            "tool calls in this response. ZN will decide research and execution steps only after this contract is "
            f"durably accepted. Root objective: {root.objective}"
        )
        request.context = {
            **dict(request.context or {}),
            "work_thread_id": root.work_thread_id,
            "root_work_item_id": root.work_item_id,
            "plan_version": root.plan_version,
            "root_acceptance_contract": "autonomous-observable-root-criteria-v1",
        }
        return request

    def _cognition_integration_step(self, event, state, *, readiness, thought=None):
        root = self._autonomous_root_candidate(event)
        raw = state.data.get("cognitive_increment")
        if root is None or not isinstance(raw, dict):
            return super()._cognition_integration_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        increment = CognitiveIncrement.from_dict(raw)
        criteria = self._parse_root_acceptance(increment.content)
        if criteria is None:
            failure = (
                "ZN rejected broad-goal intake because cognition did not return a bounded, observable Root "
                "acceptance contract"
            )
            state.data["local_failure"] = failure
            state.data.pop("cognitive_increment", None)
            state.data.pop("external_cognition_result", None)
            state.data.pop("cognition_integration", None)
            state.data.pop("cognition_request", None)
            state.data.pop("impasse_id", None)
            state.stage = "native_investigation"
            state.next_action = "re-form the broad Root acceptance contract before any execution"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        self._accept_borrowed_increment(event, state, increment)
        accepted = self._initialize_root_acceptance(event.event_id, root, criteria)
        state.data["autonomous_root_acceptance"] = {
            "work_item_id": accepted.work_item_id,
            "plan_version": accepted.plan_version,
            "criteria": list(accepted.acceptance_criteria),
            "source": increment.source,
            "accepted_at": utc_now(),
        }
        state.data.pop("local_failure", None)
        state.data.pop("cognitive_increment", None)
        state.data.pop("external_cognition_result", None)
        state.data.pop("cognition_integration", None)
        state.data.pop("cognition_request", None)
        state.data.pop("impasse_id", None)
        state.stage = "native_deliberation"
        state.next_action = "choose the first bounded Work step under the accepted Root contract"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _initialize_root_acceptance(
        self,
        event_id: str,
        root: WorkItem,
        criteria: list[str],
    ) -> WorkItem:
        """Perform one narrowly authorized empty->defined Root criteria transition."""

        run = self.work_ledger.get_run(event_id)
        current_version = self.work_ledger.plan_version(root.work_thread_id)
        if (
            run is None
            or run.ledger_state != "active"
            or run.thread_id != root.work_thread_id
            or root.parent_work_item_id is not None
            or root.plan_version != current_version
            or self.work_ledger._run_plan_version(event_id) != current_version
        ):
            raise ValueError("autonomous Root acceptance rejected stale or non-Root Work")
        existing = self.work_ledger.work_item_for_event(event_id)
        if existing is None:
            raise ValueError("autonomous Root acceptance requires a durable WorkItem")
        if existing.acceptance_criteria:
            if list(existing.acceptance_criteria) == list(criteria):
                return existing
            raise ValueError("autonomous Root acceptance is immutable once defined")

        encoded = json.dumps(criteria, ensure_ascii=False, separators=(",", ":"))
        now = utc_now()
        with self.work_ledger._lock, closing(self.work_ledger._connect()) as conn:
            updated = conn.execute(
                "UPDATE work_items SET acceptance_criteria_json=?,updated_at=? "
                "WHERE work_item_id=? AND work_thread_id=? AND plan_version=? "
                "AND parent_work_item_id IS NULL AND acceptance_criteria_json='[]'",
                (encoded, now, root.work_item_id, root.work_thread_id, current_version),
            )
            conn.commit()
        if updated.rowcount not in {0, 1}:
            raise RuntimeError("autonomous Root acceptance changed an unexpected number of rows")
        persisted = self.work_ledger.work_item_for_event(event_id)
        if persisted is None or list(persisted.acceptance_criteria) != list(criteria):
            raise RuntimeError("autonomous Root acceptance did not persist the exact criteria")
        return persisted

    def _parse_root_acceptance(self, content: str) -> list[str] | None:
        try:
            raw = json.loads(str(content or "").strip())
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict) or set(raw) != {"zn_root_acceptance"}:
            return None
        contract = raw.get("zn_root_acceptance")
        if not isinstance(contract, dict) or set(contract) != {"criteria"}:
            return None
        raw_criteria = contract.get("criteria")
        if not isinstance(raw_criteria, list):
            return None
        if not self._MIN_ROOT_CRITERIA <= len(raw_criteria) <= self._MAX_ROOT_CRITERIA:
            return None

        criteria: list[str] = []
        seen: set[str] = set()
        for raw_item in raw_criteria:
            if not isinstance(raw_item, str):
                return None
            item = " ".join(raw_item.strip().split())
            if not item or len(item) > self._MAX_CRITERION_CHARS:
                return None
            key = item.casefold()
            if key in seen:
                return None
            seen.add(key)
            criteria.append(item)
        return criteria
