from __future__ import annotations

"""Independent Root acceptance plus flat delegated WorkerRun composition.

The model may propose a bounded final verifier, but it cannot mark Root Work
complete. ZN materializes the verifier as a new current-plan WorkItem, binds the
command to that durable child identity, executes it through the existing Body,
then freshly reads the declared persisted result through the Body before asking
the evidence-bound ledger to accept the Root.

E2E-29 delegation stays flat: the Resident creates bounded research/coding/review
WorkerRuns in the existing Work ledger, while the existing Research/Coding/Body
layers execute admitted proposals. No second scheduler, router, agent identity,
provider retry machine, or store is introduced.
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
from .evidence_bound_work import WorkerContextPack, WorkerRun
from .models import ExecutionPath, ResidentRunResult, utc_now
from .steerable_work import WorkItem
from .structured_proposal import parse_exact_json_payload
from .work import title_for_work_task


class BroadGoalCompletionResidentRuntime(BroadGoalResearchResidentRuntime):
    """Finish Root Work from evidence while supervising bounded WorkerRuns."""

    _MODEL_INVOCATION_TOTAL_KEY = "broad_goal_model_invocations"
    _DELEGATED_PENDING_KEY = "delegated_worker_pending_verification"
    _DELEGATED_CONTEXT_KEY = "delegated_worker"
    _WORKER_SCOPE_PROFILES = {
        "research": {
            "tool_scope": ("managed_browser.navigate", "managed_browser.read"),
            "authority_scope": ("web_read",),
            "forbidden_actions": (
                "workspace_write",
                "terminal_execute",
                "git_mutation",
                "git_push",
                "release",
                "messaging",
                "root_acceptance",
            ),
        },
        "coding": {
            "tool_scope": (
                "workspace.read",
                "workspace.write",
                "terminal.python",
                "terminal.test",
                "git.status",
                "git.diff",
            ),
            "authority_scope": ("workspace_read", "workspace_write", "terminal_execute"),
            "forbidden_actions": (
                "outside_workspace_write",
                "git_push",
                "release",
                "messaging",
                "root_acceptance",
            ),
        },
        "review": {
            "tool_scope": (
                "workspace.read",
                "terminal.python",
                "terminal.test",
                "git.status",
                "git.diff",
            ),
            "authority_scope": ("workspace_read", "terminal_verify"),
            "forbidden_actions": (
                "workspace_write",
                "git_mutation",
                "git_push",
                "release",
                "messaging",
                "root_acceptance",
            ),
        },
    }

    def _promote_external_completion(self, event, state, run):
        result = super()._promote_external_completion(event, state, run)
        state.data[self._MODEL_INVOCATION_TOTAL_KEY] = max(
            0, int(state.data.get(self._MODEL_INVOCATION_TOTAL_KEY) or 0)
        ) + max(0, int(run.model_invocations))
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return result

    def _external_cognition_step(self, event, state):
        run = super()._external_cognition_step(event, state)
        if run is not None and not run.success:
            self._fail_delegated_provider_run(state, run)
        return run

    def _advance_event_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        result = super()._advance_event_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )
        if result is not None and not result.success:
            self._fail_delegated_provider_run(state, result)
        return result

    @staticmethod
    def _root_requests_delegated_worker_sequence(root: WorkItem) -> bool:
        text = " ".join(str(root.objective or "").casefold().split())
        required_groups = (
            ("调研", "研究", "research"),
            ("开发", "实现", "做出", "build", "implement", "develop"),
            ("review", "评审", "审查", "复核"),
        )
        return all(any(marker in text for marker in markers) for markers in required_groups)

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
        if not self._root_requests_delegated_worker_sequence(root):
            return request
        return self._prepare_delegated_worker_request(event, root, request, completed)

    def _prepare_delegated_worker_request(self, event, root, request, completed):
        self.work_ledger.reconcile_stale_worker_runs(thread_id=root.work_thread_id)
        items = self.work_ledger.list_work_items(root.work_thread_id, limit=256)
        item_by_id = {item.work_item_id: item for item in items}
        current_runs = [
            run
            for run in self.work_ledger.list_worker_runs(thread_id=root.work_thread_id, limit=256)
            if run.plan_version == root.plan_version
        ]
        active = next(
            (
                run
                for run in reversed(current_runs)
                if run.state in {"queued", "running"}
                and item_by_id.get(run.work_item_id) is not None
                and item_by_id[run.work_item_id].status in {"running", "ready"}
            ),
            None,
        )
        if active is not None:
            child = item_by_id[active.work_item_id]
            expected_action = self._worker_expected_action(child)
            if expected_action is None:
                raise RuntimeError("active delegated WorkerRun lost its expected action contract")
            return self._bind_worker_request(
                event,
                root,
                request,
                active,
                child,
                expected_action=expected_action,
                completed=completed,
            )

        phase = self._next_worker_phase(root, items, current_runs)
        if phase is None:
            return request
        executor_kind, expected_action = phase
        child = self.work_ledger.create_child_item(
            root_work_item_id=root.work_item_id,
            objective=self._worker_objective(executor_kind, expected_action),
            acceptance_criteria=[f"delegated_worker_evidence: {executor_kind}/{expected_action}"],
            title=f"{executor_kind.title()} worker",
        )
        profile = self._WORKER_SCOPE_PROFILES[executor_kind]
        worker = self.work_ledger.start_worker_run(
            work_item_id=child.work_item_id,
            executor_kind=executor_kind,
            tool_scope=profile["tool_scope"],
            authority_scope=profile["authority_scope"],
        )
        return self._bind_worker_request(
            event,
            root,
            request,
            worker,
            child,
            expected_action=expected_action,
            completed=completed,
        )

    def _next_worker_phase(self, root, items, runs):
        current_children = [
            item
            for item in items
            if item.parent_work_item_id == root.work_item_id
            and item.plan_version == root.plan_version
        ]
        positions = {
            item.work_item_id: index
            for index, item in enumerate(current_children)
        }
        item_by_id = {item.work_item_id: item for item in current_children}
        accepted_run_items: dict[str, WorkerRun] = {}
        for run in runs:
            item = item_by_id.get(run.work_item_id)
            if (
                run.state == "completed"
                and run.verification_status == "accepted"
                and item is not None
                and item.status == "completed"
            ):
                accepted_run_items[run.work_item_id] = run
        if not any(run.executor_kind == "research" for run in accepted_run_items.values()):
            return "research", "research_page"

        def has_criterion(item: WorkItem, prefix: str) -> bool:
            return any(
                criterion.startswith(prefix)
                for criterion in item.acceptance_criteria
            )

        real_children = [
            item
            for item in current_children
            if not has_criterion(item, "delegated_worker_evidence:")
        ]
        completed_writes = [
            item
            for item in real_children
            if item.status == "completed" and has_criterion(item, "text_equals:")
        ]
        if not completed_writes:
            return "coding", "write_file"

        completed_commands = [
            item
            for item in real_children
            if item.status == "completed" and has_criterion(item, "command_exit:")
        ]
        blocked_commands = [
            item
            for item in real_children
            if item.status == "blocked" and has_criterion(item, "command_exit:")
        ]
        latest_write = completed_writes[-1]
        latest_completed_command = completed_commands[-1] if completed_commands else None
        latest_blocked_command = blocked_commands[-1] if blocked_commands else None

        if latest_completed_command is None:
            if (
                latest_blocked_command is not None
                and positions[latest_blocked_command.work_item_id]
                > positions[latest_write.work_item_id]
            ):
                return "coding", "write_file"
            return "coding", "run_python"

        latest_write_position = positions[latest_write.work_item_id]
        latest_completed_command_position = positions[latest_completed_command.work_item_id]
        if latest_write_position > latest_completed_command_position:
            return "coding", "run_python"
        if (
            latest_blocked_command is not None
            and positions[latest_blocked_command.work_item_id]
            > max(latest_write_position, latest_completed_command_position)
        ):
            return "coding", "write_file"

        if not any(run.executor_kind == "review" for run in accepted_run_items.values()):
            return "review", "run_python"
        return None

    def _bind_worker_request(
        self,
        event,
        root,
        request,
        worker: WorkerRun,
        child: WorkItem,
        *,
        expected_action: str,
        completed: list[WorkItem],
    ):
        profile = self._WORKER_SCOPE_PROFILES[worker.executor_kind]
        accepted_evidence = [
            {
                "kind": "accepted_effect",
                "work_item_id": item.work_item_id,
                "objective": item.objective[:400],
                "acceptance": list(item.acceptance_criteria)[:4],
                "result": str(item.result or "")[:1200],
            }
            for item in completed[-6:]
            if item.work_item_id != child.work_item_id
        ]
        current_items = [
            item
            for item in self.work_ledger.list_work_items(root.work_thread_id, limit=256)
            if item.parent_work_item_id == root.work_item_id
            and item.plan_version == root.plan_version
            and item.work_item_id != child.work_item_id
        ]
        failed_evidence = [
            {
                "kind": "failed_effect",
                "work_item_id": item.work_item_id,
                "objective": item.objective[:400],
                "acceptance": list(item.acceptance_criteria)[:4],
                "blocker": str(item.blocker or "")[:1200],
                "result": str(item.result or "")[:1200],
            }
            for item in current_items
            if item.status == "blocked"
            and (item.blocker or item.result)
            and not any(
                criterion.startswith("delegated_worker_evidence:")
                for criterion in item.acceptance_criteria
            )
        ][-4:]
        evidence = tuple((accepted_evidence + failed_evidence)[-8:])
        refs: list[dict[str, Any]] = []
        workspace = str(event.payload.get("workspace_path") or "").strip()
        if workspace and worker.executor_kind in {"coding", "review"}:
            refs.append({"kind": "workspace", "path": workspace})
        for item in completed[-6:]:
            if not item.result:
                continue
            try:
                parsed = json.loads(item.result)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(parsed, dict) and str(parsed.get("url") or "").strip():
                refs.append({"kind": "url", "url": str(parsed["url"])[:2048]})
        pack = WorkerContextPack(
            root_goal_summary=root.objective[:2000],
            work_item_objective=child.objective,
            acceptance_criteria=tuple(child.acceptance_criteria),
            plan_version=root.plan_version,
            relevant_evidence=evidence,
            artifact_refs=tuple(refs[:12]),
            tool_scope=worker.tool_scope,
            authority_scope=worker.authority_scope,
            forbidden_actions=tuple(profile["forbidden_actions"]),
            expected_result_schema=self._expected_worker_schema(expected_action),
        )
        request.request_id = worker.cognition_request_id
        request.required_capabilities = self._worker_required_capabilities(worker.executor_kind)
        request.context = {
            **dict(request.context or {}),
            self._DELEGATED_CONTEXT_KEY: {
                "worker_run_id": worker.worker_run_id,
                "work_item_id": child.work_item_id,
                "root_work_item_id": root.work_item_id,
                "plan_version": root.plan_version,
                "executor_kind": worker.executor_kind,
                "expected_action": expected_action,
                "model_goal_id": worker.model_goal_id,
            },
            "worker_context_pack": pack.to_dict(),
        }
        request.question += self._delegated_worker_instruction(worker.executor_kind, expected_action)
        return request

    @staticmethod
    def _worker_required_capabilities(executor_kind: str) -> tuple[str, ...]:
        if executor_kind == "research":
            return ("research", "reasoning")
        return ("coding", "reasoning")

    @staticmethod
    def _worker_objective(executor_kind: str, expected_action: str) -> str:
        if executor_kind == "research":
            return "Research one authoritative current source needed by the Root Work"
        if executor_kind == "review":
            return "Review the current implementation by running a bounded verification without mutating it"
        if expected_action == "write_file":
            return "Implement the next bounded workspace change needed by the Root Work"
        return "Run the current workspace product or test and return the observed result"

    @staticmethod
    def _expected_worker_schema(expected_action: str) -> dict[str, Any]:
        if expected_action == "research_page":
            return {"zn_work_step": {"objective": "...", "action": {"kind": "research_page", "url": "https://..."}, "acceptance": {"kind": "page_read", "url": "same URL"}}}
        if expected_action == "write_file":
            return {"zn_work_step": {"objective": "...", "action": {"kind": "write_file", "path": "relative/path", "content": "..."}, "acceptance": {"kind": "text_equals", "path": "same path", "expected_text": "same content"}}}
        return {"zn_work_step": {"objective": "...", "action": {"kind": "run_python", "path": "relative/app.py", "args": []}, "acceptance": {"kind": "command", "expected_exit_code": 0, "output_contains": ["specific output"]}}}

    @staticmethod
    def _delegated_worker_instruction(executor_kind: str, expected_action: str) -> str:
        if executor_kind == "research":
            return (
                " DELEGATED WORKER: research. Return ONLY the research_page form. You have managed-browser "
                "read authority only. Use worker_context_pack.relevant_evidence, including prior failed real "
                "page effects, and do not blindly repeat an already failed URL or assumption; choose another "
                "authoritative primary source when the evidence supports that repair. Workspace writes, Terminal "
                "execution, messaging, releases, and Root acceptance are forbidden."
            )
        if executor_kind == "review":
            return (
                " DELEGATED WORKER: review. Return ONLY the run_python form against an existing workspace "
                "artifact. Use worker_context_pack.relevant_evidence and choose a root-relevant output_contains "
                "fragment that the existing artifact should really emit; do not invent output to force success. "
                "A failed review is durable evidence and ZN may route it back to a coding repair phase. You may "
                "inspect/run verification but must not write workspace files, mutate Git, push/release/message, "
                "or accept the Root."
            )
        if expected_action == "write_file":
            return (
                " DELEGATED WORKER: coding. Return ONLY the write_file form. The write must stay inside the "
                "attached workspace. Use worker_context_pack.relevant_evidence. If the latest failed_effect is "
                "a real command/output mismatch, repair the existing implementation or its observable test "
                "signal instead of replaying the same run unchanged. Git push, release, messaging, "
                "outside-workspace mutation, and Root acceptance are forbidden."
            )
        return (
            " DELEGATED WORKER: coding. Return ONLY the run_python form for an existing workspace artifact. "
            "ZN chooses the Python interpreter. Use worker_context_pack.relevant_evidence and set "
            "output_contains only to root-relevant output that this exact artifact is expected to emit; do not "
            "invent fragments merely to make verification pass. If real execution proves a write repair is "
            "needed, that failed effect must remain evidence and ZN will route the next coding phase back to "
            "write_file. Git push, release, messaging, outside-workspace mutation, and Root acceptance are "
            "forbidden."
        )

    @staticmethod
    def _worker_expected_action(item: WorkItem) -> str | None:
        prefix = "delegated_worker_evidence: "
        for criterion in item.acceptance_criteria:
            if criterion.startswith(prefix) and "/" in criterion[len(prefix):]:
                return criterion[len(prefix):].split("/", 1)[1].strip() or None
        return None

    @classmethod
    def _delegated_meta_from_state(cls, state) -> dict[str, Any] | None:
        request = state.data.get("cognition_request")
        if not isinstance(request, dict):
            return None
        context = request.get("context")
        if not isinstance(context, dict):
            return None
        raw = context.get(cls._DELEGATED_CONTEXT_KEY)
        return dict(raw) if isinstance(raw, dict) else None

    @staticmethod
    def _route_id_from_increment(increment: CognitiveIncrement) -> str | None:
        source = str(increment.source or "").strip()
        return source.split(":", 1)[1] if source.startswith("external:") and ":" in source else None

    @staticmethod
    def _claims_completion(content: str) -> bool:
        text = str(content or "").strip().lower()
        return any(marker in text for marker in ("任务已完成", "task complete", "task completed", "root complete", "root completed", '"done":true', '"completed":true'))

    def _scope_allows(self, worker: WorkerRun, expected_action: str) -> bool:
        tools = set(worker.tool_scope)
        authority = set(worker.authority_scope)
        if worker.executor_kind == "research" and expected_action == "research_page":
            return "managed_browser.read" in tools and "web_read" in authority
        if worker.executor_kind == "coding" and expected_action == "write_file":
            return "workspace.write" in tools and "workspace_write" in authority
        if worker.executor_kind == "coding" and expected_action == "run_python":
            return "terminal.python" in tools and "terminal_execute" in authority
        if worker.executor_kind == "review" and expected_action == "run_python":
            return "terminal.test" in tools and "terminal_verify" in authority
        return False

    def _proposal_contract_valid(self, event, root, expected_action: str, content: str) -> bool:
        if expected_action == "research_page":
            return self._parse_research_page_step(root, content) is not None
        if expected_action == "write_file":
            return self._parse_write_file_step(event, root, content) is not None
        if expected_action == "run_python":
            return self._parse_run_python_step(event, root, content) is not None
        return False

    @staticmethod
    def _proposal_action_kind(content: str) -> str | None:
        raw = parse_exact_json_payload(content)
        if not isinstance(raw, dict) or set(raw) != {"zn_work_step"}:
            return None
        step = raw.get("zn_work_step")
        if not isinstance(step, dict):
            return None
        action = step.get("action")
        if not isinstance(action, dict):
            return None
        return str(action.get("kind") or "").strip() or None

    def _cognition_integration_step(self, event, state, *, readiness, thought=None):
        raw = state.data.get("cognitive_increment")
        root = self._criterion_bound_root(event)
        if root is None or not isinstance(raw, dict):
            return super()._cognition_integration_step(event, state, readiness=readiness, thought=thought)
        increment = CognitiveIncrement.from_dict(raw)
        delegated = self._delegated_meta_from_state(state)
        if delegated is not None:
            worker_run_id = str(delegated.get("worker_run_id") or "").strip()
            work_item_id = str(delegated.get("work_item_id") or "").strip()
            expected_action = str(delegated.get("expected_action") or "").strip()
            worker = self.work_ledger.worker_run(worker_run_id)
            action_kind = self._proposal_action_kind(increment.content)
            claimed = self._claims_completion(increment.content)
            route_id = self._route_id_from_increment(increment)
            valid = bool(
                worker is not None
                and worker.work_item_id == work_item_id
                and worker.plan_version == root.plan_version
                and expected_action
                and action_kind == expected_action
                and self._scope_allows(worker, expected_action)
                and self._proposal_contract_valid(event, root, expected_action, increment.content)
            )
            if not valid:
                status = "scope_rejected" if action_kind and action_kind != expected_action else "schema_rejected"
                failure = (
                    f"ZN rejected delegated {str(delegated.get('executor_kind') or 'worker')} proposal: "
                    f"expected {expected_action or 'bounded schema'}, received {action_kind or 'unstructured result'}; "
                    "WorkerRun self-report cannot expand tool/authority scope or accept Root Work"
                )
                if worker is not None:
                    self.work_ledger.fail_worker_run(
                        worker.worker_run_id,
                        error=failure,
                        result_summary=increment.content,
                        claimed_completion=claimed,
                        verification_status=status,
                        model_route_id=route_id,
                        metrics={"source": increment.source, "increment_id": increment.increment_id},
                    )
                if work_item_id:
                    self.work_ledger.block_child_item(work_item_id, blocker=failure)
                self._accept_borrowed_increment(event, state, increment)
                return self._return_to_investigation_after_rejection(event, state, failure)

            assert worker is not None
            self.work_ledger.complete_worker_run(
                worker.worker_run_id,
                result_summary=increment.content,
                claimed_completion=claimed,
                verification_status="scope_admitted",
                model_route_id=route_id,
                metrics={"source": increment.source, "increment_id": increment.increment_id},
            )
            state.data[self._DELEGATED_PENDING_KEY] = dict(delegated)
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)

        if delegated is None:
            proposal = self._parse_verify_python_step(event, root, increment.content)
            if proposal is not None:
                return self._begin_root_verification(event, state, root, increment, proposal)

        if self._looks_like_work_step(increment.content):
            research = self._parse_research_page_step(root, increment.content)
            run_python = self._parse_run_python_step(event, root, increment.content)
            write_file = self._parse_write_file_step(event, root, increment.content)
            if research is None and run_python is None and write_file is None:
                self._accept_borrowed_increment(event, state, increment)
                failure = "ZN rejected the proposed Broad Work step because it did not match any bounded current-plan research/write/run/verification contract"
                return self._return_to_investigation_after_rejection(event, state, failure)

        return super()._cognition_integration_step(event, state, readiness=readiness, thought=thought)

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
        state.data.pop(self._DELEGATED_PENDING_KEY, None)
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

    def _fail_delegated_provider_run(self, state, run) -> None:
        delegated = self._delegated_meta_from_state(state)
        if delegated is None:
            return
        worker_run_id = str(delegated.get("worker_run_id") or "").strip()
        work_item_id = str(delegated.get("work_item_id") or "").strip()
        worker = self.work_ledger.worker_run(worker_run_id)
        if worker is None or worker.state not in {"queued", "running"}:
            return
        route_id = run.kernel_result.route.route_id if run.kernel_result is not None else None
        failure = str(run.reason or "delegated provider cognition failed")[:6000]
        self.work_ledger.fail_worker_run(
            worker.worker_run_id,
            error=failure,
            result_summary=str(run.response or "")[:12000],
            verification_status="provider_failed",
            model_route_id=route_id,
            metrics={"model_invocations": int(run.model_invocations)},
        )
        if work_item_id:
            self.work_ledger.block_child_item(work_item_id, blocker=failure)

    def _accept_delegated_execution_evidence(
        self,
        state,
        *,
        effect_work_item_id: str,
        result_summary: str,
        artifact_refs: list[dict[str, Any]] | None = None,
    ) -> None:
        pending = state.data.get(self._DELEGATED_PENDING_KEY)
        if not isinstance(pending, dict):
            return
        worker_run_id = str(pending.get("worker_run_id") or "").strip()
        work_item_id = str(pending.get("work_item_id") or "").strip()
        if not worker_run_id or not work_item_id:
            state.data.pop(self._DELEGATED_PENDING_KEY, None)
            return
        try:
            self.work_ledger.complete_child_item(
                work_item_id,
                result=f"accepted from verified effect WorkItem {effect_work_item_id}: {str(result_summary or 'verified')[:5000]}",
            )
            self.work_ledger.record_worker_verification(
                worker_run_id,
                verification_status="accepted",
                artifact_refs=artifact_refs or [{"kind": "work_item", "work_item_id": effect_work_item_id}],
            )
            state.data.pop(self._DELEGATED_PENDING_KEY, None)
        except ValueError:
            self.work_ledger.mark_worker_stale(worker_run_id, reason="verified delegated evidence arrived after the plan changed")
            state.data.pop(self._DELEGATED_PENDING_KEY, None)

    def _reject_delegated_execution_evidence(self, state, *, failure: str) -> None:
        pending = state.data.get(self._DELEGATED_PENDING_KEY)
        if not isinstance(pending, dict):
            return
        worker_run_id = str(pending.get("worker_run_id") or "").strip()
        work_item_id = str(pending.get("work_item_id") or "").strip()
        if work_item_id:
            try:
                self.work_ledger.block_child_item(work_item_id, blocker=failure)
            except ValueError:
                pass
        if worker_run_id:
            try:
                self.work_ledger.record_worker_verification(worker_run_id, verification_status="execution_failed")
            except ValueError:
                pass
        state.data.pop(self._DELEGATED_PENDING_KEY, None)

    def _reconcile_failed_rolling_step(self, event, state) -> None:
        failure = str(state.data.get("local_failure") or "").strip()
        super()._reconcile_failed_rolling_step(event, state)
        if failure:
            self._reject_delegated_execution_evidence(state, failure=failure)

    def _fail_research_step(self, event, state, child: WorkItem, failure: str):
        result = super()._fail_research_step(event, state, child, failure)
        self._reject_delegated_execution_evidence(state, failure=failure)
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return result

    def _roll_forward_research_state(self, event, state):
        raw = state.data.get(self._BROAD_RESEARCH_KEY)
        research = dict(raw) if isinstance(raw, dict) else {}
        effect_id = str(research.get("work_item_id") or "").strip()
        thread_id = str(research.get("work_thread_id") or "").strip()
        effect = next((item for item in self.work_ledger.list_work_items(thread_id, limit=256) if item.work_item_id == effect_id), None) if effect_id and thread_id else None
        if effect is not None and effect.status == "completed":
            refs: list[dict[str, Any]] = [{"kind": "work_item", "work_item_id": effect.work_item_id}]
            try:
                evidence = json.loads(str(effect.result or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                evidence = {}
            if isinstance(evidence, dict) and str(evidence.get("url") or "").strip():
                refs.append({"kind": "url", "url": str(evidence["url"])[:2048]})
            self._accept_delegated_execution_evidence(state, effect_work_item_id=effect.work_item_id, result_summary=str(effect.result or "managed-browser evidence")[:5000], artifact_refs=refs)
        return super()._roll_forward_research_state(event, state)

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
        pending = state.data.get(self._DELEGATED_PENDING_KEY)
        delegated_pending = dict(pending) if isinstance(pending, dict) else None
        outcome = super()._roll_forward_verified_child(event, state, result=result)
        if not finish:
            if delegated_pending is not None:
                state.data[self._DELEGATED_PENDING_KEY] = delegated_pending
                root = self._criterion_bound_root(event)
                effect = next((item for item in self.work_ledger.list_work_items(root.work_thread_id, limit=256) if item.work_item_id == child_id), None) if root is not None and child_id else None
                if effect is not None and effect.status == "completed":
                    self._accept_delegated_execution_evidence(
                        state,
                        effect_work_item_id=effect.work_item_id,
                        result_summary=str(effect.result or result.response or "verified")[:5000],
                        artifact_refs=[{"kind": "work_item", "work_item_id": effect.work_item_id}, {"kind": "path", "path": str((rolling or {}).get("relative_path") or "")}],
                    )
                    self._sync_execution_context(event, state)
                    self.store.save_working_state(state)
                elif outcome is not None:
                    self._reject_delegated_execution_evidence(state, failure="delegated effect did not produce current-plan accepted evidence")
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
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)

        accepted = self.work_ledger.accept_root_with_current_evidence(event.event_id, verifier_work_item_id=child.work_item_id, verification_summary=str(child.result or result.response or "")[:4000])
        if accepted.status != "completed":
            return result
        return ResidentRunResult(
            event=event,
            execution_path=ExecutionPath.BODY,
            success=True,
            response="Broad Work accepted from current-plan execution evidence and a fresh persisted-state read: " + str(result.response or child.result or "verification passed"),
            model_invocations=max(0, int(state.data.get(self._MODEL_INVOCATION_TOTAL_KEY) or 0)),
            reason="criterion-bound Root Work completed only after a separate verifier WorkItem passed real Terminal execution, ZN freshly reread declared persisted state through its Body, and the evidence ledger revalidated current plan identity",
        )

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
