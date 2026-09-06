from __future__ import annotations

"""Resident-internal coordination for bounded flat WorkerRuns.

This component is composition inside the single Resident. It owns no store,
router, model identity, scheduler service, Body, or Root completion authority.
It coordinates current-plan WorkItems/WorkerRuns through the Resident's existing
Work ledger and builds the bounded context sent through the existing ModelRouter.
"""

import json
from typing import Any

from .delegation_admission import BoundedDelegationPlanner, DelegatedPlanDecision
from .evidence_bound_work import WorkerRun
from .steerable_work import WorkItem
from .worker_context_boundary import WorkerContextPack


class DelegatedWorkCoordinator:
    """Coordinate one Resident's current flat delegated-work lifecycle."""

    def __init__(self, resident) -> None:
        self.resident = resident

    def decide(self, root: WorkItem) -> DelegatedPlanDecision:
        return BoundedDelegationPlanner.decide(root)

    def reconcile(self, *, thread_id: str) -> None:
        """Reconcile durable worker records without replaying unknown effects."""

        self.resident.work_ledger.reconcile_stale_worker_runs(thread_id=thread_id)

    def prepare_request(self, event, root: WorkItem, request, completed: list[WorkItem]):
        """Resume or materialize exactly one bounded current-plan WorkerRun."""

        self.reconcile(thread_id=root.work_thread_id)
        items = self.resident.work_ledger.list_work_items(root.work_thread_id, limit=256)
        item_by_id = {item.work_item_id: item for item in items}
        current_runs = [
            run
            for run in self.resident.work_ledger.list_worker_runs(
                thread_id=root.work_thread_id,
                limit=256,
            )
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
            expected_action = self.resident._worker_expected_action(child)
            if expected_action is None:
                raise RuntimeError("active delegated WorkerRun lost its expected action contract")
            return self.bind_worker_request(
                event,
                root,
                request,
                active,
                child,
                expected_action=expected_action,
                completed=completed,
            )

        phase = self.next_worker_phase(root, items, current_runs)
        if phase is None:
            return request
        executor_kind, expected_action = phase
        child = self.resident.work_ledger.create_child_item(
            root_work_item_id=root.work_item_id,
            objective=self.resident._worker_objective(executor_kind, expected_action),
            acceptance_criteria=[
                f"delegated_worker_evidence: {executor_kind}/{expected_action}"
            ],
            title=f"{executor_kind.title()} worker",
        )
        profile = self.resident._WORKER_SCOPE_PROFILES[executor_kind]
        worker = self.resident.work_ledger.start_worker_run(
            work_item_id=child.work_item_id,
            executor_kind=executor_kind,
            tool_scope=profile["tool_scope"],
            authority_scope=profile["authority_scope"],
        )
        return self.bind_worker_request(
            event,
            root,
            request,
            worker,
            child,
            expected_action=expected_action,
            completed=completed,
        )

    def next_worker_phase(self, root: WorkItem, items, runs):
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
            return any(criterion.startswith(prefix) for criterion in item.acceptance_criteria)

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

    def bind_worker_request(
        self,
        event,
        root: WorkItem,
        request,
        worker: WorkerRun,
        child: WorkItem,
        *,
        expected_action: str,
        completed: list[WorkItem],
    ):
        """Build a strict pack and bind the request to the durable WorkerRun."""

        profile = self.resident._WORKER_SCOPE_PROFILES[worker.executor_kind]
        accepted_evidence = [
            {
                "kind": "accepted_effect",
                "work_item_id": item.work_item_id,
                "objective": item.objective,
                "acceptance": list(item.acceptance_criteria),
                "result": str(item.result or ""),
            }
            for item in completed[-6:]
            if item.work_item_id != child.work_item_id
        ]
        current_items = [
            item
            for item in self.resident.work_ledger.list_work_items(
                root.work_thread_id,
                limit=256,
            )
            if item.parent_work_item_id == root.work_item_id
            and item.plan_version == root.plan_version
            and item.work_item_id != child.work_item_id
        ]
        failed_evidence = [
            {
                "kind": "failed_effect",
                "work_item_id": item.work_item_id,
                "objective": item.objective,
                "acceptance": list(item.acceptance_criteria),
                "blocker": str(item.blocker or ""),
                "result": str(item.result or ""),
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
                refs.append({"kind": "url", "url": str(parsed["url"])})

        classification = str(event.payload.get("data_classification") or "private").strip()
        pack = WorkerContextPack(
            root_goal_summary=root.objective,
            work_item_objective=child.objective,
            acceptance_criteria=tuple(child.acceptance_criteria),
            plan_version=root.plan_version,
            relevant_evidence=evidence,
            artifact_refs=tuple(refs),
            tool_scope=worker.tool_scope,
            authority_scope=worker.authority_scope,
            forbidden_actions=tuple(profile["forbidden_actions"]),
            expected_result_schema=self.resident._expected_worker_schema(expected_action),
            provenance={
                "source": "resident_work_ledger",
                "boundary": "worker_context_pack_v1",
                "work_item_id": child.work_item_id,
                "plan_version": root.plan_version,
            },
            data_classification=classification,
        )
        request.request_id = worker.cognition_request_id
        request.required_capabilities = self.resident._worker_required_capabilities(
            worker.executor_kind
        )
        request.context = {
            **dict(request.context or {}),
            self.resident._DELEGATED_CONTEXT_KEY: {
                "worker_run_id": worker.worker_run_id,
                "work_item_id": child.work_item_id,
                "root_work_item_id": root.work_item_id,
                "work_thread_id": root.work_thread_id,
                "plan_version": root.plan_version,
                "executor_kind": worker.executor_kind,
                "expected_action": expected_action,
                "model_goal_id": worker.model_goal_id,
            },
            "worker_context_pack": pack.to_dict(),
        }
        request.question += self.resident._delegated_worker_instruction(
            worker.executor_kind,
            expected_action,
        )
        return request
