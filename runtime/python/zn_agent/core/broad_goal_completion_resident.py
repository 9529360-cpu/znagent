from __future__ import annotations

"""Independent Root acceptance for rolling Broad Work.

The model may propose a bounded final verifier, but it cannot mark Root Work
complete. ZN materializes the verifier as a new current-plan WorkItem, binds the
command to that durable child identity, executes it through the existing Body,
then freshly reads the declared persisted result through the Body before asking
the evidence-bound ledger to accept the Root. No second scheduler, router,
worker, or store exists.
"""

import hashlib
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from .action import NativeActionIntent
from .broad_goal_research_resident import BroadGoalResearchResidentRuntime
from .cognition import CognitiveIncrement
from .models import ExecutionPath, ResidentRunResult, utc_now
from .steerable_work import WorkItem
from .structured_proposal import parse_exact_json_payload
from .work import title_for_work_task


class BroadGoalCompletionResidentRuntime(BroadGoalResearchResidentRuntime):
    """Finish criterion-bound Broad Work only from current-plan execution evidence."""

    _MODEL_INVOCATION_TOTAL_KEY = "broad_goal_model_invocations"

    def _promote_external_completion(self, event, state, run):
        result = super()._promote_external_completion(event, state, run)
        state.data[self._MODEL_INVOCATION_TOTAL_KEY] = max(
            0, int(state.data.get(self._MODEL_INVOCATION_TOTAL_KEY) or 0)
        ) + max(0, int(run.model_invocations))
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return result

    def _build_cognition_request(self, event, impasse, required, deliberation=None):
        request = super()._build_cognition_request(event, impasse, required, deliberation)
        root = self._criterion_bound_root(event)
        if root is None:
            return request
        completed = [
            item
            for item in self.work_ledger.list_work_items(root.work_thread_id, limit=256)
            if item.parent_work_item_id == root.work_item_id
            and item.plan_version == root.plan_version
            and item.status == "completed"
        ]
        request.question += (
            " Only when the current plan already has completed real work and the runnable result is ready "
            "for a final independent execution probe, you may propose this fourth V1 form: "
            '{"zn_work_step":{"objective":"...","action":{"kind":"verify_python",'
            '"path":"relative/app.py","args":[]},"acceptance":{"kind":"root_verified",'
            '"criteria":["copy every Root acceptance criterion exactly"],"expected_exit_code":0,'
            '"output_contains":["specific observed output fragment"],"persisted_read":{'
            '"path":"relative/data.json","contains":["specific persisted fragment"]}}}}. '
            "The Python artifact and persisted text file must be inside the attached workspace. "
            "output_contains and persisted_read.contains must both be non-empty. Copy the Root criteria "
            "exactly; do not weaken, summarize, or replace them. The persisted path must name the actual "
            "local state used by the runnable product, not source code or a model explanation. ZN will "
            "create a separate verifier WorkItem, choose the interpreter, execute the process, then perform "
            "a fresh Body read of that persisted path and require every declared persisted fragment before "
            "the evidence ledger can accept the Root. "
            f"Current-plan completed child count: {len(completed)}."
        )
        request.context = {
            **dict(request.context or {}),
            "root_finish_contract": "current-plan-python-plus-persisted-read-verifier-v2",
        }
        return request

    def _cognition_integration_step(self, event, state, *, readiness, thought=None):
        raw = state.data.get("cognitive_increment")
        root = self._criterion_bound_root(event)
        if root is None or not isinstance(raw, dict):
            return super()._cognition_integration_step(
                event, state, readiness=readiness, thought=thought
            )
        increment = CognitiveIncrement.from_dict(raw)
        proposal = self._parse_verify_python_step(event, root, increment.content)
        if proposal is not None:
            return self._begin_root_verification(event, state, root, increment, proposal)

        if self._looks_like_work_step(increment.content):
            research = self._parse_research_page_step(root, increment.content)
            run_python = self._parse_run_python_step(event, root, increment.content)
            write_file = self._parse_write_file_step(event, root, increment.content)
            if research is None and run_python is None and write_file is None:
                self._accept_borrowed_increment(event, state, increment)
                failure = (
                    "ZN rejected the proposed Broad Work step because it did not match any bounded "
                    "current-plan research/write/run/verification contract"
                )
                state.data["local_failure"] = failure
                investigation = self.investigator.current(event.event_id)
                if investigation is not None and investigation.status == "resolved_external":
                    evidence = list(investigation.evidence)
                    if failure not in evidence:
                        evidence.append(failure)
                    investigation.status = "open"
                    investigation.resolution = None
                    investigation.unresolved = failure
                    investigation.next_probe = None
                    investigation.evidence = tuple(evidence[-64:])
                    self.investigator._save(investigation)
                state.data.pop("cognitive_increment", None)
                state.data.pop("external_cognition_result", None)
                state.data.pop("cognition_integration", None)
                state.data.pop("cognition_request", None)
                state.data.pop("impasse_id", None)
                state.stage = "native_investigation"
                state.next_action = "repair the rejected bounded Work proposal"
                self._sync_execution_context(event, state)
                self.store.save_working_state(state)
                return None

        return super()._cognition_integration_step(
            event, state, readiness=readiness, thought=thought
        )

    def _begin_root_verification(self, event, state, root, increment, proposal):
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
            acceptance_criteria=[
                f'independent_python_verification: {proposal["relative_path"]}; '
                f'fresh_persisted_read: {proposal["persisted_relative_path"]}'
            ],
        )
        self.work_ledger._save_item(child)

        command = shlex.join([sys.executable, proposal["absolute_path"], *proposal["args"]])
        intent = NativeActionIntent(
            intent_id=f"broad-root-verify-{identity[:12]}",
            event_id=event.event_id,
            kind="command",
            args={
                "command": command,
                "workdir": proposal["workspace"],
                "task_id": child.work_item_id,
                "timeout": proposal["timeout"],
                "max_output_chars": 50_000,
            },
            expected_outcome={
                "kind": "command",
                "command": command,
                "workdir": proposal["workspace"],
                "expected_exit_code": proposal["expected_exit_code"],
                "output_contains": list(proposal["output_contains"]),
                "timeout": proposal["timeout"],
                "max_output_chars": 50_000,
            },
            reason=(
                "ZN bound a model-proposed final probe to a separate durable verifier WorkItem; "
                "the evidence-bound ledger remains the only Root acceptance authority"
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
            "action_kind": "verify_root_python",
            "root_acceptance_criteria": list(root.acceptance_criteria),
            "persisted_relative_path": proposal["persisted_relative_path"],
            "persisted_absolute_path": proposal["persisted_absolute_path"],
            "persisted_contains": list(proposal["persisted_contains"]),
        }
        self._begin_native_action_cycle(event, state, intent)
        state.next_action = "execute the separate current-plan Root verifier through the Terminal Body"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _roll_forward_verified_child(self, event, state, *, result):
        raw = state.data.get(self._ROLLING_STEP_KEY)
        rolling = dict(raw) if isinstance(raw, dict) else None
        finish = bool(rolling and rolling.get("action_kind") == "verify_root_python")
        child_id = str((rolling or {}).get("work_item_id") or "")
        outcome = super()._roll_forward_verified_child(event, state, result=result)
        if not finish or outcome is not None:
            return outcome

        root = self._criterion_bound_root(event)
        if root is None:
            return result
        child = next(
            (
                item
                for item in self.work_ledger.list_work_items(root.work_thread_id, limit=256)
                if item.work_item_id == child_id
            ),
            None,
        )
        if child is None or child.status != "completed":
            return result

        persisted_path = str((rolling or {}).get("persisted_absolute_path") or "").strip()
        persisted_relative = str((rolling or {}).get("persisted_relative_path") or "").strip()
        expected_fragments = [
            str(item)
            for item in ((rolling or {}).get("persisted_contains") or [])
            if str(item)
        ]
        fresh = self.body.act(
            "read_text",
            event_id=event.event_id,
            path=persisted_path,
            max_chars=50_000,
        )
        fresh_text = str(fresh.output or "")
        missing = [fragment for fragment in expected_fragments if fragment not in fresh_text]
        if not fresh.success or not fresh_text.strip() or missing:
            detail = str(fresh.error or "").strip()
            if missing:
                detail = "missing persisted fragments: " + " | ".join(missing[:8])
            if not detail:
                detail = "persisted file was empty after the independent verifier"
            failure = (
                f"fresh persisted-state verification failed for {persisted_relative or persisted_path}: "
                f"{detail}"
            )
            child.status = "blocked"
            child.blocker = failure[:6000]
            child.result = failure[:6000]
            child.completed_at = None
            child.updated_at = utc_now()
            self.work_ledger._save_item(child)
            state.data["local_failure"] = failure
            state.data["fresh_persisted_verification"] = {
                "path": persisted_relative or persisted_path,
                "success": False,
                "missing": missing[:8],
                "error": str(fresh.error or "")[:1000],
            }
            investigation = self.investigator.current(event.event_id)
            if investigation is not None:
                evidence = list(investigation.evidence)
                evidence_line = failure[:1000]
                if evidence_line not in evidence:
                    evidence.append(evidence_line)
                investigation.status = "open"
                investigation.resolution = None
                investigation.unresolved = failure[:1000]
                investigation.next_probe = None
                investigation.updated_at = utc_now()
                investigation.evidence = tuple(evidence[-64:])
                self.investigator._save(investigation)
            state.stage = "native_investigation"
            state.next_action = "repair the product from fresh persisted-state verification evidence"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        persisted_summary = {
            "terminal": str(child.result or result.response or "")[:3000],
            "fresh_persisted_read": {
                "path": persisted_relative,
                "contains": expected_fragments,
                "observed_chars": len(fresh_text),
                "observed_excerpt": fresh_text[:3000],
            },
        }
        child.result = json.dumps(persisted_summary, ensure_ascii=False, sort_keys=True)
        child.updated_at = utc_now()
        self.work_ledger._save_item(child)
        state.data["fresh_persisted_verification"] = {
            "path": persisted_relative,
            "success": True,
            "observed_chars": len(fresh_text),
            "contains": expected_fragments,
        }
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)

        accepted = self.work_ledger.accept_root_with_current_evidence(
            event.event_id,
            verifier_work_item_id=child.work_item_id,
            verification_summary=str(child.result or result.response or "")[:4000],
        )
        if accepted.status != "completed":
            return result
        return ResidentRunResult(
            event=event,
            execution_path=ExecutionPath.BODY,
            success=True,
            response=(
                "Broad Work accepted from current-plan execution evidence and a fresh persisted-state read: "
                + str(result.response or child.result or "verification passed")
            ),
            model_invocations=max(
                0, int(state.data.get(self._MODEL_INVOCATION_TOTAL_KEY) or 0)
            ),
            reason=(
                "criterion-bound Root Work completed only after a separate verifier WorkItem passed real "
                "Terminal execution, ZN freshly reread declared persisted state through its Body, and the "
                "evidence ledger revalidated current plan identity"
            ),
        )

    def _parse_verify_python_step(
        self,
        event,
        root: WorkItem,
        content: str,
    ) -> dict[str, Any] | None:
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
        if str(action.get("kind") or "").strip() != "verify_python":
            return None
        if str(acceptance.get("kind") or "").strip() != "root_verified":
            return None
        raw_criteria = acceptance.get("criteria")
        if not isinstance(raw_criteria, list):
            return None
        criteria = [str(item) for item in raw_criteria]
        if criteria != list(root.acceptance_criteria):
            return None
        raw_output = acceptance.get("output_contains")
        if not isinstance(raw_output, list) or not raw_output:
            return None
        persisted = acceptance.get("persisted_read")
        if not isinstance(persisted, dict) or set(persisted) != {"path", "contains"}:
            return None
        persisted_relative = str(persisted.get("path") or "").strip()
        persisted_rel = Path(persisted_relative)
        raw_persisted_contains = persisted.get("contains")
        if (
            not persisted_relative
            or persisted_rel.is_absolute()
            or not persisted_rel.parts
            or any(part in {"", ".", ".."} for part in persisted_rel.parts)
            or not isinstance(raw_persisted_contains, list)
            or not raw_persisted_contains
            or len(raw_persisted_contains) > 8
        ):
            return None
        persisted_contains: list[str] = []
        for value in raw_persisted_contains:
            if not isinstance(value, str) or not value or len(value) > 1000:
                return None
            persisted_contains.append(value)

        run_shape = {
            "zn_work_step": {
                "objective": objective,
                "action": {
                    "kind": "run_python",
                    "path": action.get("path"),
                    "args": action.get("args") or [],
                },
                "acceptance": {
                    "kind": "command",
                    "expected_exit_code": acceptance.get("expected_exit_code", 0),
                    "output_contains": raw_output,
                    "timeout": acceptance.get("timeout", 20.0),
                },
            }
        }
        parsed = self._parse_run_python_step(
            event, root, json.dumps(run_shape, ensure_ascii=False)
        )
        if parsed is None:
            return None
        try:
            root_path = Path(parsed["workspace"]).resolve(strict=True)
            persisted_path = root_path.joinpath(*persisted_rel.parts).resolve(strict=True)
            persisted_path.relative_to(root_path)
            if not persisted_path.is_file():
                return None
        except (OSError, RuntimeError, ValueError):
            return None
        if persisted_path == Path(parsed["absolute_path"]):
            return None

        prior = [
            item
            for item in self.work_ledger.list_work_items(root.work_thread_id, limit=256)
            if item.parent_work_item_id == root.work_item_id
            and item.plan_version == root.plan_version
            and item.status == "completed"
        ]
        if not prior:
            return None
        return {
            **parsed,
            "persisted_relative_path": persisted_rel.as_posix(),
            "persisted_absolute_path": str(persisted_path),
            "persisted_contains": persisted_contains,
        }

    @staticmethod
    def _looks_like_work_step(content: str) -> bool:
        raw = parse_exact_json_payload(content)
        return isinstance(raw, dict) and "zn_work_step" in raw
