from __future__ import annotations

"""Rolling broad-Work execution on top of the existing Resident/Work/Body stack.

This is intentionally not a planner, scheduler, worker runtime, or second task
engine. A criterion-bound durable Work item may ask an external cognitive
resource for exactly one proposed next step. ZN validates that proposal,
materializes it as an existing child WorkItem, executes it through the existing
NativeActionIntent/Body lifecycle, freshly verifies the postcondition, and only
then accepts that child. The Root Work remains live for the next roll.
"""

import hashlib
import json
from pathlib import Path

from .action import NativeActionIntent
from .cognition import CognitiveIncrement
from .evidence_bound_work import EvidenceBoundSteerableWorkLedger
from .execution_mode import event_allows_effects
from .models import ExecutionPath, ResidentRunResult, utc_now
from .user_browser_extension_resident import UserBrowserExtensionResidentRuntime
from .steerable_work import WorkItem
from .structured_proposal import parse_exact_json_payload
from .work import title_for_work_task


class BroadGoalWorkResidentRuntime(UserBrowserExtensionResidentRuntime):
    """Add a bounded rolling-decomposition bridge over durable Work."""

    _ROLLING_STEP_KEY = "broad_goal_rolling_step"
    _ROLLING_HISTORY_KEY = "broad_goal_rolling_history"
    _MAX_STEP_CONTENT = 200_000

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        # Same SQLite truth and same WorkItem schema. This helper does not own a
        # scheduler or event loop; the Resident event remains the execution owner.
        self.work_ledger = EvidenceBoundSteerableWorkLedger(self)

    def _criterion_bound_root(self, event) -> WorkItem | None:
        if not event_allows_effects(event):
            return None
        thread_id = str(event.payload.get("work_thread_id") or "").strip()
        item_id = str(event.payload.get("work_item_id") or "").strip()
        if not thread_id or not item_id or not event.payload.get("workspace_path"):
            return None
        item = self.work_ledger.work_item_for_event(event.event_id)
        if item is None or item.work_item_id != item_id:
            return None
        if item.parent_work_item_id is not None or not item.acceptance_criteria:
            return None
        if item.plan_version != self.work_ledger.plan_version(thread_id):
            return None
        return item

    def _build_cognition_request(self, event, impasse, required, deliberation=None):
        request = super()._build_cognition_request(
            event,
            impasse,
            required,
            deliberation,
        )
        root = self._criterion_bound_root(event)
        if root is None:
            return request

        completed = [
            item
            for item in self.work_ledger.list_work_items(root.work_thread_id)
            if item.parent_work_item_id == root.work_item_id
            and item.plan_version == root.plan_version
            and item.status == "completed"
        ]
        history = [
            {
                "objective": item.objective[:300],
                "acceptance": list(item.acceptance_criteria)[:4],
                "result": str(item.result or "")[:500],
            }
            for item in completed[-6:]
        ]
        state = self.store.get_working_state()
        local_failure = str(state.data.get("local_failure") or "").strip()

        request.question = (
            "You are a bounded cognitive resource assisting one durable ZN Work. "
            "ZN owns the Work lifecycle, tools, permissions, execution, evidence and completion. "
            "Propose exactly ONE smallest useful next workspace step; do not claim the Root Work is complete. "
            "Return ONLY one JSON object with this shape: "
            '{"zn_work_step":{"objective":"...","action":{"kind":"write_file",'
            '"path":"relative/path","content":"..."},"acceptance":{"kind":"text_equals",'
            '"path":"relative/path","expected_text":"..."}}}. '
            "The path must be relative to the attached workspace. The acceptance path and text must exactly "
            "match the proposed write. Do not emit shell commands or tool calls in this V1 step. "
            f"Root objective: {root.objective}. "
            f"Root acceptance criteria: {json.dumps(root.acceptance_criteria, ensure_ascii=False)}. "
            f"Already accepted child evidence: {json.dumps(history, ensure_ascii=False)}. "
            f"Latest real execution failure, if any: {local_failure or 'none'}."
        )
        request.context = {
            **dict(request.context or {}),
            "work_thread_id": root.work_thread_id,
            "root_work_item_id": root.work_item_id,
            "plan_version": root.plan_version,
            "completed_child_count": len(completed),
            "rolling_step_contract": "write_file/text_equals-v1",
        }
        return request

    def _cognition_integration_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        raw = state.data.get("cognitive_increment")
        root = self._criterion_bound_root(event)
        if root is None or not isinstance(raw, dict):
            return super()._cognition_integration_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        increment = CognitiveIncrement.from_dict(raw)
        proposal = self._parse_write_file_step(event, root, increment.content)
        if proposal is None:
            # Ordinary prose cognition keeps the existing bounded-increment
            # behavior. In particular, model planning text still cannot satisfy
            # Work acceptance because the evidence-bound ledger owns that gate.
            return super()._cognition_integration_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        self._accept_borrowed_increment(event, state, increment)
        identity = hashlib.sha256(
            f"{event.event_id}\0{increment.increment_id}".encode("utf-8", errors="replace")
        ).hexdigest()[:16]
        child = WorkItem(
            work_item_id=f"item-{identity}",
            work_thread_id=root.work_thread_id,
            parent_work_item_id=root.work_item_id,
            title=title_for_work_task(proposal["objective"]),
            objective=proposal["objective"],
            status="running",
            plan_version=root.plan_version,
            acceptance_criteria=[f'text_equals: {proposal["relative_path"]}'],
        )
        # Deterministic identity closes the crash window between child materialization
        # and the durable action checkpoint: replaying integration reuses this row.
        self.work_ledger._save_item(child)

        intent = NativeActionIntent(
            intent_id=f"broad-step-{identity[:12]}",
            event_id=event.event_id,
            kind="write_text",
            args={
                "path": proposal["absolute_path"],
                "content": proposal["content"],
                "append": False,
                "create_parents": False,
            },
            expected_outcome={
                "kind": "text_equals",
                "path": proposal["absolute_path"],
                "expected_text": proposal["content"],
            },
            reason=(
                "ZN validated one bounded external cognition proposal against the attached "
                "workspace and chose the concrete Body movement itself"
            ),
            source="resident_broad_goal_choice",
        )
        state.data[self._ROLLING_STEP_KEY] = {
            "work_item_id": child.work_item_id,
            "root_work_item_id": root.work_item_id,
            "work_thread_id": root.work_thread_id,
            "plan_version": root.plan_version,
            "relative_path": proposal["relative_path"],
            "objective": proposal["objective"],
            "increment_id": increment.increment_id,
        }
        self._begin_native_action_cycle(event, state, intent)
        state.next_action = "execute one ZN-owned rolling Work step through the Body"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _complete_successful_body_action(
        self,
        event,
        state,
        intent,
        *,
        response: str,
        reason: str,
    ):
        rolling = state.data.get(self._ROLLING_STEP_KEY)
        if not isinstance(rolling, dict):
            return super()._complete_successful_body_action(
                event,
                state,
                intent,
                response=response,
                reason=reason,
            )

        # Reuse the complete mature Body accounting/recovery path first. We only
        # intercept the semantic level above it: this is a verified child step,
        # not yet terminal Root Work completion.
        result = super()._complete_successful_body_action(
            event,
            state,
            intent,
            response=response,
            reason=reason,
        )
        return self._roll_forward_verified_child(event, state, result=result)

    def _resume_native_completion(self, event, state):
        rolling = state.data.get(self._ROLLING_STEP_KEY)
        if not isinstance(rolling, dict):
            return super()._resume_native_completion(event, state)

        # If the process died after the mature Body completion checkpoint but
        # before Root roll-forward, recovery must accept/reconcile the child and
        # continue the same Root instead of publishing a terminal Root outcome.
        result = super()._resume_native_completion(event, state)
        if result is None or not result.success:
            return result
        return self._roll_forward_verified_child(event, state, result=result)

    def _roll_forward_verified_child(self, event, state, *, result):
        rolling = state.data.get(self._ROLLING_STEP_KEY)
        if not isinstance(rolling, dict):
            return result

        child_id = str(rolling.get("work_item_id") or "").strip()
        thread_id = str(rolling.get("work_thread_id") or "").strip()
        plan_version = int(rolling.get("plan_version") or 0)
        child = next(
            (
                item
                for item in self.work_ledger.list_work_items(thread_id)
                if item.work_item_id == child_id
            ),
            None,
        )
        current_version = self.work_ledger.plan_version(thread_id)
        if child is None:
            raise RuntimeError("verified rolling Body step lost its durable WorkItem")
        if plan_version != current_version or child.plan_version != current_version:
            child.status = "superseded"
            child.blocker = "verified child result belongs to a stale Work plan"
            child.updated_at = utc_now()
            self.work_ledger._save_item(child)
            return result

        if child.status != "completed":
            child.status = "completed"
            child.result = str(result.response or rolling.get("relative_path") or "")
            child.blocker = None
            child.completed_at = utc_now()
            child.updated_at = child.completed_at
            self.work_ledger._save_item(child)

        raw_history = state.data.get(self._ROLLING_HISTORY_KEY)
        history = list(raw_history) if isinstance(raw_history, list) else []
        if not any(
            isinstance(item, dict) and item.get("work_item_id") == child.work_item_id
            for item in history
        ):
            history.append(
                {
                    "work_item_id": child.work_item_id,
                    "objective": child.objective,
                    "acceptance_criteria": list(child.acceptance_criteria),
                    "result": child.result,
                    "completed_at": child.completed_at,
                }
            )
        state.data[self._ROLLING_HISTORY_KEY] = history[-12:]
        state.data.pop(self._ROLLING_STEP_KEY, None)
        state.data.pop("native_completion", None)
        state.data.pop("cognitive_increment", None)
        state.data.pop("external_cognition_result", None)
        state.data.pop("cognition_integration", None)
        state.data.pop("cognition_request", None)
        state.data.pop("impasse_id", None)
        state.stage = "native_deliberation"
        state.next_action = "choose the next bounded Work step from fresh evidence"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _accept_borrowed_increment(self, event, state, increment: CognitiveIncrement) -> None:
        external = state.data.get("external_cognition_result")
        external_data = external if isinstance(external, dict) else {}
        invocations = max(0, int(external_data.get("model_invocations") or 0))
        accepted_run = ResidentRunResult(
            event=event,
            execution_path=ExecutionPath.MODEL,
            success=True,
            response=increment.content,
            model_invocations=invocations,
            reason=f"accepted bounded rolling Work proposal from {increment.source}",
        )
        self.life.resolve_impasse(
            event,
            accepted_run,
            resolution_source=increment.source,
        )
        self.investigator.resolve_from_external(
            event.event_id,
            increment.content or "external cognition proposed one bounded Work step",
        )
        domains = self.kernel.self_model.integrate_external_learning(
            event.task,
            self._required_capabilities(event),
            quality=increment.quality,
            confidence=increment.confidence,
        )
        state.data["cognition_integration"] = {
            "increment_id": increment.increment_id,
            "accepted": True,
            "source": increment.source,
            "quality": increment.quality,
            "confidence": increment.confidence,
        }
        state.data["integrated_learning_domains"] = list(domains)

    def _parse_write_file_step(
        self,
        event,
        root: WorkItem,
        content: str,
    ) -> dict[str, str] | None:
        raw = parse_exact_json_payload(content)
        if not isinstance(raw, dict) or set(raw) != {"zn_work_step"}:
            return None
        step = raw.get("zn_work_step")
        if not isinstance(step, dict):
            return None
        objective = " ".join(str(step.get("objective") or "").strip().split())
        action = step.get("action")
        acceptance = step.get("acceptance")
        if not objective or len(objective) > 600:
            return None
        if not isinstance(action, dict) or not isinstance(acceptance, dict):
            return None
        if str(action.get("kind") or "").strip() != "write_file":
            return None
        if str(acceptance.get("kind") or "").strip() != "text_equals":
            return None

        relative_path = str(action.get("path") or "").strip()
        acceptance_path = str(acceptance.get("path") or "").strip()
        body = action.get("content")
        expected = acceptance.get("expected_text")
        if not relative_path or relative_path != acceptance_path:
            return None
        if not isinstance(body, str) or not isinstance(expected, str) or body != expected:
            return None
        if len(body) > self._MAX_STEP_CONTENT:
            return None

        rel = Path(relative_path)
        if rel.is_absolute() or not rel.parts or any(part in {"", ".", ".."} for part in rel.parts):
            return None
        workspace = Path(str(event.payload.get("workspace_path") or "")).expanduser()
        try:
            root_path = workspace.resolve(strict=True)
            candidate = root_path.joinpath(*rel.parts)
            parent = candidate.parent.resolve(strict=True)
            parent.relative_to(root_path)
            if candidate.exists():
                candidate.resolve(strict=True).relative_to(root_path)
        except (OSError, RuntimeError, ValueError):
            return None

        if root.plan_version != self.work_ledger.plan_version(root.work_thread_id):
            return None
        return {
            "objective": objective,
            "relative_path": rel.as_posix(),
            "absolute_path": str(candidate),
            "content": body,
        }
