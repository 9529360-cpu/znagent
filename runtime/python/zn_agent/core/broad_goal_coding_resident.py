from __future__ import annotations

"""Bounded Python execution for rolling broad Work.

This layer extends the existing broad-Work bridge with one deliberately narrow
coding movement: run a Python file that already exists inside the attached
workspace. The model never supplies shell text or the Python executable; ZN
binds the script to the workspace, chooses its own interpreter, quotes argv,
executes through the existing Terminal Body, and feeds real failures back into
the same Root Work.
"""

import hashlib
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from .action import NativeActionIntent
from .broad_goal_work_resident import BroadGoalWorkResidentRuntime
from .cognition import CognitiveIncrement
from .models import utc_now
from .steerable_work import WorkItem
from .structured_proposal import parse_exact_json_payload
from .work import title_for_work_task


class BroadGoalCodingResidentRuntime(BroadGoalWorkResidentRuntime):
    """Add the smallest real Modify -> Run -> Observe -> Fix loop for E2E-26."""

    _MAX_PYTHON_ARGS = 24
    _MAX_ARG_CHARS = 2048

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

        items = [
            item
            for item in self.work_ledger.list_work_items(root.work_thread_id)
            if item.parent_work_item_id == root.work_item_id
            and item.plan_version == root.plan_version
        ]
        evidence = [
            {
                "status": item.status,
                "objective": item.objective[:300],
                "acceptance": list(item.acceptance_criteria)[:4],
                "result": str(item.result or "")[:900],
                "blocker": str(item.blocker or "")[:900],
            }
            for item in items[-8:]
        ]
        state = self.store.get_working_state()
        raw_action = state.data.get("native_action_result")
        action_result = raw_action if isinstance(raw_action, dict) else {}
        latest_execution = {
            "success": action_result.get("success"),
            "kind": action_result.get("kind"),
            "output": str(action_result.get("output") or "")[-4000:],
            "error": str(action_result.get("error") or "")[:1000],
            "exit_code": (
                action_result.get("data", {}).get("exit_code")
                if isinstance(action_result.get("data"), dict)
                else None
            ),
            "timed_out": (
                action_result.get("data", {}).get("timed_out")
                if isinstance(action_result.get("data"), dict)
                else None
            ),
        }
        local_failure = str(state.data.get("local_failure") or "").strip()

        request.question = (
            "You are a bounded coding/reasoning resource assisting one durable ZN Work. "
            "ZN owns the Work lifecycle, tools, permissions, execution, evidence and completion. "
            "Propose exactly ONE smallest useful next workspace step. Return ONLY JSON. "
            "Allowed V1 forms are either: "
            '{"zn_work_step":{"objective":"...","action":{"kind":"write_file",'
            '"path":"relative/path","content":"..."},"acceptance":{"kind":"text_equals",'
            '"path":"relative/path","expected_text":"..."}}} OR '
            '{"zn_work_step":{"objective":"...","action":{"kind":"run_python",'
            '"path":"relative/script.py","args":[]},"acceptance":{"kind":"command",'
            '"expected_exit_code":0,"output_contains":["..."]}}}. '
            "Do not emit shell commands, executable paths, background-process controls, or tool calls. "
            "For run_python, the script must already exist inside the attached workspace; ZN chooses "
            "the interpreter and workdir. If the latest real execution failed, use that exact evidence "
            "to propose the smallest repair rather than repeating the failed assumption. "
            f"Root objective: {root.objective}. "
            f"Root acceptance criteria: {json.dumps(root.acceptance_criteria, ensure_ascii=False)}. "
            f"Durable child evidence: {json.dumps(evidence, ensure_ascii=False)}. "
            f"Latest real failure: {local_failure or 'none'}. "
            f"Latest real execution result: {json.dumps(latest_execution, ensure_ascii=False)}."
        )
        request.context = {
            **dict(request.context or {}),
            "rolling_step_contract": "write_file-or-run_python-v1",
            "child_count": len(items),
            "latest_execution": latest_execution,
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
        proposal = self._parse_run_python_step(event, root, increment.content)
        if proposal is None:
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
        output_fragments = list(proposal["output_contains"])
        criterion = f'command_exit: {proposal["expected_exit_code"]}'
        if output_fragments:
            criterion += "; output_contains: " + " | ".join(output_fragments)
        child = WorkItem(
            work_item_id=f"item-{identity}",
            work_thread_id=root.work_thread_id,
            parent_work_item_id=root.work_item_id,
            title=title_for_work_task(proposal["objective"]),
            objective=proposal["objective"],
            status="running",
            plan_version=root.plan_version,
            acceptance_criteria=[criterion],
        )
        self.work_ledger._save_item(child)

        command = shlex.join(
            [sys.executable, proposal["absolute_path"], *proposal["args"]]
        )
        intent = NativeActionIntent(
            intent_id=f"broad-python-{identity[:12]}",
            event_id=event.event_id,
            kind="command",
            args={
                "command": command,
                "workdir": proposal["workspace"],
                "timeout": proposal["timeout"],
                "max_output_chars": 50_000,
            },
            expected_outcome={
                "kind": "command",
                "command": command,
                "workdir": proposal["workspace"],
                "expected_exit_code": proposal["expected_exit_code"],
                "output_contains": output_fragments,
                "timeout": proposal["timeout"],
                "max_output_chars": 50_000,
            },
            reason=(
                "ZN bound one cognition-proposed Python script to the attached workspace, "
                "selected its own interpreter, and chose the Terminal movement itself"
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
            "action_kind": "run_python",
        }
        self._begin_native_action_cycle(event, state, intent)
        state.next_action = "run one workspace Python artifact through the existing Terminal Body"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _verification_contract(self, event, intent, *, result=None):
        raw = intent.expected_outcome
        if (
            intent.source != "resident_broad_goal_choice"
            or intent.kind != "command"
            or not isinstance(raw, dict)
        ):
            return super()._verification_contract(event, intent, result=result)
        if str(raw.get("kind") or "").strip().lower() != "command":
            return super()._verification_contract(event, intent, result=result)

        command = str(raw.get("command") or "").strip()
        intent_command = str(intent.args.get("command") or "").strip()
        workdir = str(raw.get("workdir") or "").strip() or None
        intent_workdir = str(intent.args.get("workdir") or "").strip() or None
        if not command or command != intent_command or workdir != intent_workdir:
            return {
                "kind": "unsupported",
                "requested_kind": "command",
                "error": "rolling command verification must exactly match the current ZN-owned movement",
                "intent_id": intent.intent_id,
                "action_signature": self._intent_signature(intent),
            }
        try:
            expected_exit = int(raw.get("expected_exit_code", 0))
            timeout = max(0.05, min(120.0, float(raw.get("timeout", 20.0))))
            max_output = max(128, min(100_000, int(raw.get("max_output_chars", 50_000))))
        except (TypeError, ValueError):
            return {
                "kind": "unsupported",
                "requested_kind": "command",
                "error": "rolling command verification has invalid numeric limits",
                "intent_id": intent.intent_id,
                "action_signature": self._intent_signature(intent),
            }
        raw_output = raw.get("output_contains") or []
        if not isinstance(raw_output, list):
            return {
                "kind": "unsupported",
                "requested_kind": "command",
                "error": "rolling command verification output_contains must be a list",
                "intent_id": intent.intent_id,
                "action_signature": self._intent_signature(intent),
            }
        output_contains = [str(item) for item in raw_output if str(item)]
        return {
            "kind": "command",
            "command": command,
            "workdir": workdir,
            "expected_exit_code": expected_exit,
            "output_contains": output_contains,
            "timeout": timeout,
            "max_output_chars": max_output,
            "intent_id": intent.intent_id,
            "action_signature": self._intent_signature(intent),
        }

    def _native_action_step(self, event, state, *, readiness, thought=None):
        result = super()._native_action_step(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )
        self._reconcile_failed_rolling_step(event, state)
        return result

    def _investigation_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        # Recovery boundary: the mature Body persists native_investigation before
        # this rolling layer records its child/failure semantics. Reconcile from
        # that durable truth on the next pulse instead of leaving a running child
        # or a stale resolved_external investigation after a crash.
        self._reconcile_failed_rolling_step(event, state)
        return super()._investigation_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    def _fail_postcondition_verification(
        self,
        event,
        state,
        intent,
        *,
        failure: str,
        thought=None,
    ):
        result = super()._fail_postcondition_verification(
            event,
            state,
            intent,
            failure=failure,
            thought=thought,
        )
        self._reconcile_failed_rolling_step(event, state)
        return result

    def _reconcile_failed_rolling_step(self, event, state) -> None:
        failure = str(state.data.get("local_failure") or "").strip()
        rolling = state.data.get(self._ROLLING_STEP_KEY)
        if not failure or not isinstance(rolling, dict):
            return
        self._block_failed_rolling_child(state)

        investigation = self.investigator.current(event.event_id)
        if investigation is None or investigation.status != "resolved_external":
            return
        evidence = list(investigation.evidence)
        failure_evidence = f"new local failure after external cognition: {failure[:1000]}"
        if failure_evidence not in evidence:
            evidence.append(failure_evidence)
        investigation.status = "open"
        investigation.resolution = None
        investigation.unresolved = failure[:1000]
        investigation.next_probe = None
        investigation.updated_at = utc_now()
        investigation.evidence = tuple(evidence[-64:])
        self.investigator._save(investigation)

    def _block_failed_rolling_child(self, state) -> None:
        rolling = state.data.get(self._ROLLING_STEP_KEY)
        failure = str(state.data.get("local_failure") or "").strip()
        if not isinstance(rolling, dict) or not failure:
            return
        child_id = str(rolling.get("work_item_id") or "").strip()
        thread_id = str(rolling.get("work_thread_id") or "").strip()
        if not child_id or not thread_id:
            return
        child = next(
            (
                item
                for item in self.work_ledger.list_work_items(thread_id)
                if item.work_item_id == child_id
            ),
            None,
        )
        if child is None or child.status in {"completed", "superseded"}:
            return
        raw_action = state.data.get("native_action_result")
        action = raw_action if isinstance(raw_action, dict) else {}
        data = action.get("data") if isinstance(action.get("data"), dict) else {}
        output = str(action.get("output") or "").strip()
        pieces = [failure]
        if data.get("exit_code") is not None:
            pieces.append(f"exit_code={data.get('exit_code')}")
        if output:
            pieces.append("output=" + output[-4000:])
        child.status = "blocked"
        child.blocker = "; ".join(pieces)[:6000]
        child.result = child.blocker
        child.updated_at = utc_now()
        self.work_ledger._save_item(child)

    def _parse_run_python_step(
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
        if str(action.get("kind") or "").strip() != "run_python":
            return None
        if str(acceptance.get("kind") or "").strip() != "command":
            return None

        relative_path = str(action.get("path") or "").strip()
        rel = Path(relative_path)
        if (
            not relative_path
            or rel.is_absolute()
            or not rel.parts
            or any(part in {"", ".", ".."} for part in rel.parts)
            or rel.suffix.lower() != ".py"
        ):
            return None
        raw_args = action.get("args") or []
        if not isinstance(raw_args, list) or len(raw_args) > self._MAX_PYTHON_ARGS:
            return None
        args: list[str] = []
        for value in raw_args:
            if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                return None
            rendered = str(value)
            if (
                len(rendered) > self._MAX_ARG_CHARS
                or any(ord(char) < 32 or ord(char) == 127 for char in rendered)
            ):
                return None
            args.append(rendered)

        workspace = Path(str(event.payload.get("workspace_path") or "")).expanduser()
        try:
            root_path = workspace.resolve(strict=True)
            script = root_path.joinpath(*rel.parts).resolve(strict=True)
            script.relative_to(root_path)
            if not script.is_file():
                return None
        except (OSError, RuntimeError, ValueError):
            return None

        raw_exit = acceptance.get("expected_exit_code", 0)
        if isinstance(raw_exit, bool):
            return None
        try:
            expected_exit = int(raw_exit)
        except (TypeError, ValueError):
            return None
        raw_output = acceptance.get("output_contains") or []
        if not isinstance(raw_output, list) or len(raw_output) > 8:
            return None
        output_contains: list[str] = []
        for value in raw_output:
            if not isinstance(value, str) or not value or len(value) > 1000:
                return None
            output_contains.append(value)
        raw_timeout = acceptance.get("timeout", 20.0)
        if isinstance(raw_timeout, bool):
            return None
        try:
            timeout = max(0.1, min(120.0, float(raw_timeout)))
        except (TypeError, ValueError):
            return None

        if root.plan_version != self.work_ledger.plan_version(root.work_thread_id):
            return None
        return {
            "objective": objective,
            "relative_path": rel.as_posix(),
            "absolute_path": str(script),
            "workspace": str(root_path),
            "args": args,
            "expected_exit_code": expected_exit,
            "output_contains": output_contains,
            "timeout": timeout,
        }
