from __future__ import annotations

"""Independent Root acceptance from current-plan execution evidence.

The model may propose a bounded final verifier, but it cannot mark Root Work
complete. ZN materializes the verifier as a new current-plan WorkItem, binds the
command to that durable child identity, executes it through the existing Body,
then freshly reads the declared persisted result before the evidence-bound
ledger may accept the Root.
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
from .completion_verdict import (
    REPORT_SHAPE_HINT,
    CompletionVerdictError,
    record_verdict_attempt,
)
from .evidence_bound_work import single_work_evidence_entries
from .models import ExecutionPath, ResidentRunResult, utc_now
from .steerable_work import WorkItem
from .structured_proposal import parse_exact_json_payload
from .work import title_for_work_task


class BroadGoalCompletionResidentRuntime(BroadGoalResearchResidentRuntime):
    """Finish Root Work only from independently verified current-plan evidence."""

    _MODEL_INVOCATION_TOTAL_KEY = "broad_goal_model_invocations"
    # M-5 (CP-3 for single Work): once the independent verifier passed,
    # the Root waits for a structured completion report instead of being
    # accepted on the verifier pass alone. The pending claim carries the
    # verifier identity + verification summary for the ledger gate; the
    # verdict retry tracking mirrors the team owner's
    # ``record_verdict_attempt`` budget (identical rejection escalates at
    # once, distinct rejections escalate past the budget).
    _SINGLE_CLAIM_KEY = "single_work_completion_claim"
    _SINGLE_VERDICT_KEY = "single_work_completion_verdict"
    def _promote_external_completion(self, event, state, run):
        result = super()._promote_external_completion(event, state, run)
        state.data[self._MODEL_INVOCATION_TOTAL_KEY] = max(
            0, int(state.data.get(self._MODEL_INVOCATION_TOTAL_KEY) or 0)
        ) + max(0, int(run.model_invocations))
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return result

    def _pending_single_claim(self, event, root) -> dict[str, Any] | None:
        """The pending single-Work completion claim for this event/Root.

        Returns None when there is no claim or the stored claim belongs
        to a different event / Root (stale after steering / replan).
        Read-only: callers that own the state decide whether to drop a
        stale claim.
        """
        state = self.store.get_working_state()
        raw = state.data.get(self._SINGLE_CLAIM_KEY)
        if not isinstance(raw, dict):
            return None
        if str(raw.get("event_id") or "") != str(event.event_id or ""):
            return None
        if str(raw.get("root_work_item_id") or "") != str(
            root.work_item_id or ""
        ):
            return None
        return dict(raw)

    def _build_cognition_request(self, event, impasse, required, deliberation=None):
        request = super()._build_cognition_request(event, impasse, required, deliberation)
        root = self._criterion_bound_root(event)
        if root is None:
            return request
        claim = self._pending_single_claim(event, root)
        if claim is not None:
            # M-5: the verifier already passed; this round asks for
            # ONLY the structured completion report. It replaces the
            # step-proposal question from the layers below -- a new
            # work step here would not advance completion.
            completed = [
                item
                for item in self.work_ledger.list_work_items(
                    root.work_thread_id, limit=256
                )
                if item.parent_work_item_id == root.work_item_id
                and item.plan_version == root.plan_version
                and item.status == "completed"
            ]
            evidence_lines = []
            for entry in single_work_evidence_entries(completed):
                evidence_lines.append(
                    "- objective: "
                    + str(entry.get("objective") or "")[:300]
                    + " | evidence_ref candidate: "
                    + (
                        str(entry.get("relative_path") or "")
                        or str(entry.get("result") or "")[:300]
                    )
                )
            feedback = str(claim.get("last_feedback") or "").strip()
            request.question = (
                "You are a bounded cognitive resource assisting one durable ZN Work. "
                "The independent verifier already passed and ZN freshly reread the persisted state. "
                "Do NOT propose another work step. Return ONLY one JSON object with this shape: "
                f"{REPORT_SHAPE_HINT} "
                "Cite EVERY Root acceptance criterion exactly once in evidence, each with an evidence_ref "
                "that matches one listed verified-evidence entry below (a file path, an objective, or a "
                "distinctive result excerpt). A criterion with no matching evidence, or listed in "
                "unfinished, does not complete. The standing_dod section must attest all five items: "
                "no_regression and runtime_verified (when satisfied) MUST cite a real evidence entry; "
                "docs / rollback / approval need a concrete detail, or not_applicable with a reason. "
                f"Root acceptance criteria: {json.dumps(root.acceptance_criteria, ensure_ascii=False)}. "
                "Verified evidence (only these may be cited): "
                + (" ".join(evidence_lines) if evidence_lines else "none")
                + (" Previous completion verdict (fix this, do not repeat it): " + feedback if feedback else "")
            )
            request.context = {
                **dict(request.context or {}),
                "single_work_completion_claim": "completion_report-v1",
            }
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
        # M-5: a pending completion claim means this round was asked for
        # a completion report -- any output is a claim attempt, judged
        # by the same CP-3 adjudicator as the team path.
        raw_claim = state.data.get(self._SINGLE_CLAIM_KEY)
        if isinstance(raw_claim, dict):
            claim = self._pending_single_claim(event, root)
            if claim is None:
                # Stale claim (steering / replan moved the Root): drop
                # it and fall through to the normal step handling.
                state.data.pop(self._SINGLE_CLAIM_KEY, None)
                state.data.pop(self._SINGLE_VERDICT_KEY, None)
            else:
                return self._attempt_single_work_claim(
                    event, state, root, increment, claim
                )

        proposal = self._parse_verify_python_step(event, root, increment.content)
        if proposal is not None:
            return self._begin_root_verification(event, state, root, increment, proposal)

        if self._looks_like_work_step(increment.content):
            research = self._parse_research_page_step(root, increment.content)
            run_python = self._parse_run_python_step(event, root, increment.content)
            write_file = self._parse_write_file_step(event, root, increment.content)
            if research is None and run_python is None and write_file is None:
                self._accept_borrowed_increment(event, state, increment)
                return self._return_to_investigation_after_rejection(
                    event,
                    state,
                    "ZN rejected the proposed Broad Work step because it did not match any "
                    "bounded current-plan research/write/run/verification contract",
                )

        return super()._cognition_integration_step(
            event, state, readiness=readiness, thought=thought
        )

    def _attempt_single_work_claim(
        self, event, state, root, increment, claim: dict[str, Any]
    ):
        """Judge one single-Work completion report at the ledger gate.

        M-5: the report goes through ``accept_root_with_current_evidence``,
        whose final gate is the same CP-3 adjudicator as the team path.
        ``verified`` accepts the Root. ``partial`` / ``rejected`` raise
        :class:`CompletionVerdictError` carrying the verdict: the reason
        + missing list + actionable fix are fed back into the next
        cognition call, with the same bounded retry budget as the team
        owner (identical rejection escalates at once, distinct
        rejections escalate past the budget -- then fail closed instead
        of re-asking cognition).
        """
        self._accept_borrowed_increment(event, state, increment)
        try:
            accepted = self.work_ledger.accept_root_with_current_evidence(
                event.event_id,
                verifier_work_item_id=str(claim.get("verifier_work_item_id") or ""),
                verification_summary=str(claim.get("verification_summary") or ""),
                completion_report=increment.content,
            )
        except CompletionVerdictError as exc:
            verdict = exc.verdict
            tracking, escalate, escalate_reason = record_verdict_attempt(
                state.data.get(self._SINGLE_VERDICT_KEY),
                run_id=str(event.event_id or ""),
                verdict=verdict,
            )
            if escalate:
                state.data.pop(self._SINGLE_CLAIM_KEY, None)
                state.data.pop(self._SINGLE_VERDICT_KEY, None)
                self._sync_execution_context(event, state)
                self.store.save_working_state(state)
                return self._checkpoint_terminal_failure(
                    event,
                    state,
                    reason=escalate_reason or verdict.feedback_text(),
                )
            state.data[self._SINGLE_VERDICT_KEY] = tracking
            updated_claim = dict(claim)
            updated_claim["last_feedback"] = verdict.feedback_text()
            state.data[self._SINGLE_CLAIM_KEY] = updated_claim
            return self._return_to_investigation_after_rejection(
                event,
                state,
                "单人 Work 完成裁决未通过："
                + verdict.feedback_text(),
            )
        if accepted.status != "completed":
            raise RuntimeError(
                "single-Work completion gate returned without completing the Root"
            )
        state.data.pop(self._SINGLE_CLAIM_KEY, None)
        state.data.pop(self._SINGLE_VERDICT_KEY, None)
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return ResidentRunResult(
            event=event,
            execution_path=ExecutionPath.BODY,
            success=True,
            response="Broad Work accepted from current-plan execution evidence, a fresh "
            "persisted-state read, and a CP-3 verified completion report: "
            + str(accepted.result or "")[:4000],
            model_invocations=max(
                0, int(state.data.get(self._MODEL_INVOCATION_TOTAL_KEY) or 0)
            ),
            reason="criterion-bound Root Work completed only after a separate verifier WorkItem "
            "passed real Terminal execution, ZN freshly reread declared persisted state through "
            "its Body, and the evidence ledger verified a structured completion report against "
            "every Root acceptance criterion (CP-3 verdict)",
        )

    def _return_to_investigation_after_rejection(self, event, state, failure: str):
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

    def _begin_root_verification(self, event, state, root, increment, proposal):
        self._accept_borrowed_increment(event, state, increment)
        identity = hashlib.sha256(f"{event.event_id}\0{increment.increment_id}".encode("utf-8", errors="replace")).hexdigest()[:16]
        child = WorkItem(
            work_item_id=f"item-{identity}",
            work_thread_id=root.work_thread_id,
            parent_work_item_id=root.work_item_id,
            title=title_for_work_task(proposal["objective"]),
            objective=proposal["objective"],
            status="running",
            plan_version=root.plan_version,
            acceptance_criteria=[f'independent_python_verification: {proposal["relative_path"]}; fresh_persisted_read: {proposal["persisted_relative_path"]}'],
        )
        self.work_ledger._save_item(child)
        command = shlex.join([sys.executable, proposal["absolute_path"], *proposal["args"]])
        intent = NativeActionIntent(
            intent_id=f"broad-root-verify-{identity[:12]}",
            event_id=event.event_id,
            kind="command",
            args={"command": command, "workdir": proposal["workspace"], "task_id": child.work_item_id, "timeout": proposal["timeout"], "max_output_chars": 50_000},
            expected_outcome={"kind": "command", "command": command, "workdir": proposal["workspace"], "expected_exit_code": proposal["expected_exit_code"], "output_contains": list(proposal["output_contains"]), "timeout": proposal["timeout"], "max_output_chars": 50_000},
            reason="ZN bound a model-proposed final probe to a separate durable verifier WorkItem; the evidence-bound ledger remains the only Root acceptance authority",
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
        if not finish:
            return outcome
        if outcome is not None:
            return outcome

        root = self._criterion_bound_root(event)
        if root is None:
            return result
        child = next((item for item in self.work_ledger.list_work_items(root.work_thread_id, limit=256) if item.work_item_id == child_id), None)
        if child is None or child.status != "completed":
            return result

        persisted_path = str((rolling or {}).get("persisted_absolute_path") or "").strip()
        persisted_relative = str((rolling or {}).get("persisted_relative_path") or "").strip()
        expected_fragments = [str(item) for item in ((rolling or {}).get("persisted_contains") or []) if str(item)]
        fresh = self.body.act("read_text", event_id=event.event_id, path=persisted_path, max_chars=50_000)
        fresh_text = str(fresh.output or "")
        missing = [fragment for fragment in expected_fragments if fragment not in fresh_text]
        if not fresh.success or not fresh_text.strip() or missing:
            detail = str(fresh.error or "").strip()
            if missing:
                detail = "missing persisted fragments: " + " | ".join(missing[:8])
            if not detail:
                detail = "persisted file was empty after the independent verifier"
            failure = f"fresh persisted-state verification failed for {persisted_relative or persisted_path}: {detail}"
            child.status = "blocked"
            child.blocker = failure[:6000]
            child.result = failure[:6000]
            child.completed_at = None
            child.updated_at = utc_now()
            self.work_ledger._save_item(child)
            state.data["local_failure"] = failure
            state.data["fresh_persisted_verification"] = {"path": persisted_relative or persisted_path, "success": False, "missing": missing[:8], "error": str(fresh.error or "")[:1000]}
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

        persisted_summary = {"terminal": str(child.result or result.response or "")[:3000], "fresh_persisted_read": {"path": persisted_relative, "contains": expected_fragments, "observed_chars": len(fresh_text), "observed_excerpt": fresh_text[:3000]}}
        child.result = json.dumps(persisted_summary, ensure_ascii=False, sort_keys=True)
        child.updated_at = utc_now()
        self.work_ledger._save_item(child)
        state.data["fresh_persisted_verification"] = {"path": persisted_relative, "success": True, "observed_chars": len(fresh_text), "contains": expected_fragments}
        # M-5 (CP-3 for single Work): the verifier pass alone no longer
        # accepts the Root. The next cognition round must submit a
        # structured completion report citing every Root acceptance
        # criterion against the completed children's verified evidence;
        # the ledger gate adjudicates it with the same CP-3 verdict as
        # the team path. Preserve any previous verdict feedback for this
        # verifier across a crash-recovery re-roll.
        previous_claim = state.data.get(self._SINGLE_CLAIM_KEY)
        previous_feedback = (
            str(previous_claim.get("last_feedback") or "")
            if isinstance(previous_claim, dict)
            and str(previous_claim.get("verifier_work_item_id") or "")
            == child.work_item_id
            else ""
        )
        state.data[self._SINGLE_CLAIM_KEY] = {
            "event_id": event.event_id,
            "root_work_item_id": root.work_item_id,
            "verifier_work_item_id": child.work_item_id,
            "verification_summary": str(child.result or result.response or "")[:4000],
            "last_feedback": previous_feedback,
        }
        state.stage = "native_deliberation"
        state.next_action = (
            "submit a structured completion report citing every Root "
            "acceptance criterion against verified child evidence"
        )
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _parse_verify_python_step(self, event, root: WorkItem, content: str) -> dict[str, Any] | None:
        raw = parse_exact_json_payload(content)
        if not isinstance(raw, dict) or set(raw) != {"zn_work_step"}:
            return None
        step = raw.get("zn_work_step")
        if not isinstance(step, dict):
            return None
        objective = " ".join(str(step.get("objective") or "").strip().split())
        action = step.get("action")
        acceptance = step.get("acceptance")
        if not objective or len(objective) > 600 or not isinstance(action, dict) or not isinstance(acceptance, dict):
            return None
        if str(action.get("kind") or "").strip() != "verify_python" or str(acceptance.get("kind") or "").strip() != "root_verified":
            return None
        raw_criteria = acceptance.get("criteria")
        if not isinstance(raw_criteria, list) or [str(item) for item in raw_criteria] != list(root.acceptance_criteria):
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
        if not persisted_relative or persisted_rel.is_absolute() or not persisted_rel.parts or any(part in {"", ".", ".."} for part in persisted_rel.parts) or not isinstance(raw_persisted_contains, list) or not raw_persisted_contains or len(raw_persisted_contains) > 8:
            return None
        persisted_contains: list[str] = []
        for value in raw_persisted_contains:
            if not isinstance(value, str) or not value or len(value) > 1000:
                return None
            persisted_contains.append(value)
        run_shape = {"zn_work_step": {"objective": objective, "action": {"kind": "run_python", "path": action.get("path"), "args": action.get("args") or []}, "acceptance": {"kind": "command", "expected_exit_code": acceptance.get("expected_exit_code", 0), "output_contains": raw_output, "timeout": acceptance.get("timeout", 20.0)}}}
        parsed = self._parse_run_python_step(event, root, json.dumps(run_shape, ensure_ascii=False))
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
        prior = [item for item in self.work_ledger.list_work_items(root.work_thread_id, limit=256) if item.parent_work_item_id == root.work_item_id and item.plan_version == root.plan_version and item.status == "completed"]
        if not prior:
            return None
        return {**parsed, "persisted_relative_path": persisted_rel.as_posix(), "persisted_absolute_path": str(persisted_path), "persisted_contains": persisted_contains}

    @staticmethod
    def _looks_like_work_step(content: str) -> bool:
        raw = parse_exact_json_payload(content)
        return isinstance(raw, dict) and "zn_work_step" in raw
