from __future__ import annotations

"""Independent Root acceptance for rolling Broad Work.

The model may propose a bounded final verifier, but it cannot mark Root Work
complete. ZN materializes the verifier as a new current-plan WorkItem, binds the
command to that durable child identity, executes it through the existing Body,
validates the durable observed process result, then asks the evidence-bound
ledger to accept the Root. No second scheduler, router, worker, or store exists.
"""

import hashlib
import json
import shlex
import sys
from typing import Any

from .action import NativeActionIntent
from .broad_goal_research_resident import BroadGoalResearchResidentRuntime
from .cognition import CognitiveIncrement
from .models import ExecutionPath, ResidentRunResult
from .steerable_work import WorkItem
from .structured_cognition import decode_structured_cognition_object
from .work import title_for_work_task


class BroadGoalCompletionResidentRuntime(BroadGoalResearchResidentRuntime):
    """Finish criterion-bound Broad Work only from current-plan execution evidence."""

    _MODEL_INVOCATION_TOTAL_KEY = "broad_goal_model_invocations"
    _PROTOCOL_REPAIR_KEY = "broad_goal_protocol_repair"
    _MAX_REJECTED_PROTOCOL_CHARS = 12_000

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
        completed_commands = [
            item
            for item in self.work_ledger.list_work_items(root.work_thread_id, limit=256)
            if item.parent_work_item_id == root.work_item_id
            and item.plan_version == root.plan_version
            and item.status == "completed"
            and any(
                criterion.startswith("command_exit:")
                for criterion in item.acceptance_criteria
            )
        ]

        state = self.store.get_working_state()
        repair = state.data.get(self._PROTOCOL_REPAIR_KEY)
        if isinstance(repair, dict):
            request.question = self._build_protocol_repair_question(
                root,
                repair,
                allow_verify=bool(completed_commands),
            )
            request.context = {
                **dict(request.context or {}),
                "protocol_repair": True,
                "protocol_repair_kind": str(repair.get("kind") or "unknown"),
                "root_finish_contract": (
                    "current-plan-python-verifier-v1"
                    if completed_commands
                    else "blocked-until-current-plan-command-evidence"
                ),
                "current_plan_completed_command_count": len(completed_commands),
            }
            return request

        if completed_commands:
            request.question += (
                " The current plan now has a completed real Terminal execution, so if the runnable result "
                "is genuinely ready for a final independent execution probe, you may propose this fourth "
                "V1 form: "
                '{"zn_work_step":{"objective":"...","action":{"kind":"verify_python",'
                '"path":"relative/app.py","args":[]},"acceptance":{"kind":"root_verified",'
                '"criteria":["copy every Root acceptance criterion exactly"],"expected_exit_code":0,'
                '"output_contains":["specific observed output fragment"]}}}. '
                "The Python artifact must already exist in the attached workspace and output_contains must be "
                "non-empty. Copy the Root criteria exactly; do not weaken, summarize, or replace them. ZN will "
                "create a separate verifier WorkItem, choose the interpreter, execute the process, inspect real "
                "exit/output evidence, and decide whether Root acceptance is allowed. "
                f"Current-plan completed Terminal child count: {len(completed_commands)}."
            )
            finish_contract = "current-plan-python-verifier-v1"
        else:
            request.question += (
                " Final Root verification is NOT available yet because the current plan has no completed "
                "normal Terminal execution evidence. Do not emit verify_python or root_verified. First propose "
                "exactly one research_page, write_file, or run_python step using its exact acceptance form; "
                "run_python may only target a Python file that already exists in the attached workspace."
            )
            finish_contract = "blocked-until-current-plan-command-evidence"
        request.context = {
            **dict(request.context or {}),
            "root_finish_contract": finish_contract,
            "current_plan_completed_command_count": len(completed_commands),
        }
        return request

    def _build_protocol_repair_question(
        self,
        root: WorkItem,
        repair: dict[str, Any],
        *,
        allow_verify: bool,
    ) -> str:
        kind = str(repair.get("kind") or "unknown").strip()
        error = str(repair.get("error") or "invalid bounded Work protocol").strip()
        rejected = str(repair.get("content") or "")[: self._MAX_REJECTED_PROTOCOL_CHARS]
        contracts = {
            "write_file": (
                '{"zn_work_step":{"objective":"...","action":{"kind":"write_file",'
                '"path":"relative/path","content":"..."},"acceptance":{"kind":"text_equals",'
                '"path":"same relative/path","expected_text":"exact same full text"}}}'
            ),
            "run_python": (
                '{"zn_work_step":{"objective":"...","action":{"kind":"run_python",'
                '"path":"relative/script.py","args":[]},"acceptance":{"kind":"command",'
                '"expected_exit_code":0,"output_contains":["optional expected stdout"]}}}'
            ),
            "research_page": (
                '{"zn_work_step":{"objective":"...","action":{"kind":"research_page",'
                '"url":"https://..."},"acceptance":{"kind":"page_read",'
                '"url":"exact same https://..."}}}'
            ),
            "verify_python": (
                '{"zn_work_step":{"objective":"...","action":{"kind":"verify_python",'
                '"path":"relative/app.py","args":[]},"acceptance":{"kind":"root_verified",'
                '"criteria":["copy every Root acceptance criterion exactly"],"expected_exit_code":0,'
                '"output_contains":["specific observed output fragment"]}}}'
            ),
        }
        if kind in contracts and (kind != "verify_python" or allow_verify):
            allowed = contracts[kind]
        else:
            names = ["research_page", "write_file", "run_python"]
            if allow_verify:
                names.append("verify_python")
            allowed = " OR ".join(contracts[name] for name in names)
        verify_note = (
            "verify_python is allowed because current-plan Terminal evidence exists."
            if allow_verify
            else "verify_python/root_verified is not allowed until a normal current-plan Terminal child completes."
        )
        return (
            "You are a bounded coding/reasoning resource assisting one durable ZN Work. "
            "Repair the immediately previous bounded ZN Work protocol proposal; do not redo planning or emit "
            "a summary. Return exactly ONE strict JSON object and nothing else. Do not use markdown fences. "
            "Inside JSON string values, encode source-code line breaks as \\n and escape quotes/backslashes as JSON "
            "requires; raw control characters make the object invalid. "
            f"Validation error: {error}. "
            f"Previous rejected proposal: {rejected}. "
            f"Use exactly this currently allowed contract: {allowed}. "
            "For write_file, acceptance.expected_text must be byte-for-byte identical to action.content and "
            "acceptance.path must equal action.path. For run_python, target an existing workspace Python file. "
            f"{verify_note} Root objective: {root.objective}. "
            f"Root acceptance criteria: {json.dumps(root.acceptance_criteria, ensure_ascii=False)}."
        )

    def _cognition_integration_step(self, event, state, *, readiness, thought=None):
        raw = state.data.get("cognitive_increment")
        root = self._criterion_bound_root(event)
        if root is None or not isinstance(raw, dict):
            return super()._cognition_integration_step(
                event, state, readiness=readiness, thought=thought
            )
        increment = CognitiveIncrement.from_dict(raw)
        repair_active = isinstance(state.data.get(self._PROTOCOL_REPAIR_KEY), dict)
        proposal = self._parse_verify_python_step(event, root, increment.content)
        if proposal is not None:
            return self._begin_root_verification(event, state, root, increment, proposal)

        if repair_active or self._looks_like_work_protocol_attempt(increment.content):
            research = self._parse_research_page_step(root, increment.content)
            run_python = self._parse_run_python_step(event, root, increment.content)
            write_file = self._parse_write_file_step(event, root, increment.content)
            if research is None and run_python is None and write_file is None:
                return self._reject_invalid_work_step(event, state, increment)

        return super()._cognition_integration_step(
            event, state, readiness=readiness, thought=thought
        )

    def _reject_invalid_work_step(self, event, state, increment: CognitiveIncrement):
        prior_repair = state.data.get(self._PROTOCOL_REPAIR_KEY)
        self._accept_borrowed_increment(event, state, increment)
        structured = decode_structured_cognition_object(increment.content)
        kind = self._protocol_attempt_kind(increment.content, structured)
        if kind == "unknown" and isinstance(prior_repair, dict):
            kind = str(prior_repair.get("kind") or "unknown").strip() or "unknown"
        if structured is None:
            stripped = str(increment.content or "").strip()
            if "```" in stripped:
                detail = "markdown fences are not allowed around the JSON object"
            else:
                try:
                    json.loads(stripped)
                except json.JSONDecodeError as exc:
                    detail = (
                        f"JSON decode error {exc.msg!r} at line {exc.lineno} column {exc.colno}; "
                        "escape source-code newlines and other control characters inside JSON strings"
                    )
                except (TypeError, ValueError):
                    detail = "the response is not one complete JSON object"
                else:
                    detail = "the response is not one complete zn_work_step JSON object"
            failure = (
                "ZN rejected the proposed Broad Work step: " + detail + ". Return one strict zn_work_step "
                "JSON object with no prose or markdown fences"
            )
        else:
            failure = "ZN rejected the proposed Broad Work step: " + self._structured_contract_error(
                event, structured
            )
        state.data[self._PROTOCOL_REPAIR_KEY] = {
            "error": failure,
            "kind": kind,
            "content": str(increment.content or "")[: self._MAX_REJECTED_PROTOCOL_CHARS],
        }
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

    @staticmethod
    def _protocol_attempt_kind(content: str, structured: dict[str, Any] | None) -> str:
        if isinstance(structured, dict):
            step = structured.get("zn_work_step")
            if isinstance(step, dict):
                action = step.get("action")
                if isinstance(action, dict):
                    kind = str(action.get("kind") or "").strip()
                    if kind:
                        return kind
        raw = str(content or "")
        for kind in ("write_file", "run_python", "research_page", "verify_python"):
            if kind in raw:
                return kind
        return "unknown"

    def _structured_contract_error(self, event, structured: dict[str, Any]) -> str:
        if set(structured) != {"zn_work_step"}:
            return "top level must contain only the zn_work_step key"
        step = structured.get("zn_work_step")
        if not isinstance(step, dict):
            return "zn_work_step must be an object"
        objective = " ".join(str(step.get("objective") or "").strip().split())
        if not objective or len(objective) > 600:
            return "objective must be non-empty and at most 600 characters"
        action = step.get("action")
        acceptance = step.get("acceptance")
        if not isinstance(action, dict) or not isinstance(acceptance, dict):
            return "action and acceptance must both be JSON objects"
        kind = str(action.get("kind") or "").strip()
        acceptance_kind = str(acceptance.get("kind") or "").strip()
        if kind == "write_file":
            if acceptance_kind != "text_equals":
                return "write_file requires acceptance.kind=text_equals"
            action_path = str(action.get("path") or "").strip()
            acceptance_path = str(acceptance.get("path") or "").strip()
            if not action_path or action_path != acceptance_path:
                return "write_file requires acceptance.path to exactly equal action.path"
            body = action.get("content")
            expected = acceptance.get("expected_text")
            if not isinstance(body, str):
                return "write_file requires action.content to be a JSON string"
            if not isinstance(expected, str) or expected != body:
                return "write_file requires acceptance.expected_text to exactly equal action.content"
            return "write_file path/content did not satisfy the attached-workspace safety contract"
        if kind == "run_python":
            if acceptance_kind != "command":
                return "run_python requires acceptance.kind=command"
            if not str(action.get("path") or "").strip():
                return "run_python requires action.path naming an existing workspace .py file"
            return "run_python must target an existing safe workspace .py file with valid args/command acceptance"
        if kind == "research_page":
            if acceptance_kind != "page_read":
                return "research_page requires acceptance.kind=page_read"
            if str(action.get("url") or "").strip() != str(acceptance.get("url") or "").strip():
                return "research_page requires acceptance.url to exactly equal action.url"
            return "research_page requires a valid http/https URL allowed by the managed browser contract"
        if kind == "verify_python":
            if acceptance_kind != "root_verified":
                return "verify_python requires acceptance.kind=root_verified"
            root = self._criterion_bound_root(event)
            criteria = acceptance.get("criteria")
            if root is not None and criteria != list(root.acceptance_criteria):
                return "verify_python requires acceptance.criteria to copy every current Root criterion exactly"
            return "verify_python requires prior current-plan Terminal evidence, an existing .py file, and non-empty output_contains"
        return "action.kind must be one of the currently advertised bounded Work actions"

    def _accept_borrowed_increment(self, event, state, increment: CognitiveIncrement) -> None:
        state.data.pop(self._PROTOCOL_REPAIR_KEY, None)
        super()._accept_borrowed_increment(event, state, increment)

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
                f'independent_python_verification: {proposal["relative_path"]}'
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
                "Broad Work accepted from current-plan execution evidence: "
                + str(result.response or child.result or "verification passed")
            ),
            model_invocations=max(
                0, int(state.data.get(self._MODEL_INVOCATION_TOTAL_KEY) or 0)
            ),
            reason=(
                "criterion-bound Root Work completed only after a separate verifier WorkItem "
                "passed real Terminal execution and the evidence ledger revalidated current plan identity"
            ),
        )

    def _parse_verify_python_step(
        self,
        event,
        root: WorkItem,
        content: str,
    ) -> dict[str, Any] | None:
        try:
            raw = json.loads(str(content or "").strip())
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
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
        prior_commands = [
            item
            for item in self.work_ledger.list_work_items(root.work_thread_id, limit=256)
            if item.parent_work_item_id == root.work_item_id
            and item.plan_version == root.plan_version
            and item.status == "completed"
            and any(
                criterion.startswith("command_exit:")
                for criterion in item.acceptance_criteria
            )
        ]
        if not prior_commands:
            return None
        return parsed

    @staticmethod
    def _looks_like_work_step(content: str) -> bool:
        try:
            raw = json.loads(str(content or "").strip())
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
        return isinstance(raw, dict) and "zn_work_step" in raw

    @classmethod
    def _looks_like_work_protocol_attempt(cls, content: str) -> bool:
        if cls._looks_like_work_step(content):
            return True
        return "zn_work_step" in str(content or "")
