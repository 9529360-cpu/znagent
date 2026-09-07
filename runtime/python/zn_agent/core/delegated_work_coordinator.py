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
from .route_policy_intake import infer_thread_route_policy, merge_route_policy
from .steerable_work import WorkItem
from .worker_context_boundary import WorkerContextPack
from .worker_progress import record_worker_progress, worker_stalled


class DelegatedWorkCoordinator:
    """Coordinate one Resident's current flat delegated-work lifecycle."""

    _WORKER_STALL_SECONDS = 120.0
    _MAX_PHASE_ATTEMPTS = 3

    def __init__(self, resident) -> None:
        self.resident = resident

    def decide(self, root: WorkItem) -> DelegatedPlanDecision:
        return BoundedDelegationPlanner.decide(root)

    def reconcile(self, *, thread_id: str) -> None:
        """Reconcile durable worker records without replaying unknown effects.

        Kernel owns external-provider dispatch durability. Work owns WorkerRun
        lifecycle. If a restart happens after Kernel has durably finalized a
        provider result but before Resident/Work consumes it, the result is real
        progress and must be observed before stall detection. Observation here
        never completes the WorkerRun or WorkItem; normal Resident integration
        still validates schema/scope and later Body evidence.
        """

        ledger = self.resident.work_ledger
        ledger.reconcile_stale_worker_runs(thread_id=thread_id)
        kernel = getattr(self.resident, "kernel", None)
        load_result = getattr(kernel, "load_goal_result", None)
        if not callable(load_result):
            return
        for run in ledger.list_worker_runs(thread_id=thread_id, limit=256):
            if run.state not in {"queued", "running"}:
                continue
            result = load_result(run.model_goal_id)
            if result is None:
                continue
            route = getattr(result, "route", None)
            assessment = getattr(result, "assessment", None)
            record_worker_progress(
                ledger,
                run.worker_run_id,
                stage="provider_result_persisted",
                evidence={
                    "model_goal_id": run.model_goal_id,
                    "route_id": str(getattr(route, "route_id", "") or ""),
                    "provider": str(getattr(route, "provider", "") or ""),
                    "success": bool(getattr(assessment, "success", False)),
                },
            )

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
        if active is not None and worker_stalled(
            active,
            timeout_seconds=self._worker_stall_seconds(event),
        ):
            child = item_by_id[active.work_item_id]
            expected_action = self.resident._worker_expected_action(child) or "unknown"
            failure = (
                "delegated WorkerRun made no new durable progress within the bounded "
                f"stall window while waiting for {active.executor_kind}/{expected_action}"
            )
            self.resident.work_ledger.fail_worker_run(
                active.worker_run_id,
                error=failure,
                result_summary=None,
                verification_status="stalled",
                metrics={
                    **dict(active.metrics or {}),
                    "supervision_failure": "no_progress",
                },
            )
            self.resident.work_ledger.block_child_item(child.work_item_id, blocker=failure)
            active = None
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
        attempts = self._phase_attempt_count(
            current_runs,
            item_by_id,
            executor_kind=executor_kind,
            expected_action=expected_action,
        )
        if attempts >= self._MAX_PHASE_ATTEMPTS:
            request.context = {
                **dict(request.context or {}),
                "delegated_supervision": {
                    "status": "attempt_budget_exhausted",
                    "executor_kind": executor_kind,
                    "expected_action": expected_action,
                    "attempts": attempts,
                },
            }
            request.question += (
                " Delegated execution for this phase exhausted its bounded WorkerRun retry "
                "budget. Use the current failure evidence to choose a materially different "
                "safe approach; do not request another equivalent WorkerRun retry."
            )
            return request

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
        record_worker_progress(
            self.resident.work_ledger,
            worker.worker_run_id,
            stage="worker_started",
            evidence={
                "work_item_id": child.work_item_id,
                "plan_version": root.plan_version,
                "executor_kind": executor_kind,
                "expected_action": expected_action,
            },
        )
        worker = self.resident.work_ledger.worker_run(worker.worker_run_id) or worker
        return self.bind_worker_request(
            event,
            root,
            request,
            worker,
            child,
            expected_action=expected_action,
            completed=completed,
        )

    def _worker_stall_seconds(self, event) -> float:
        payload = event.payload if isinstance(getattr(event, "payload", None), dict) else {}
        raw = payload.get("worker_stall_seconds", self._WORKER_STALL_SECONDS)
        try:
            return max(1.0, min(3600.0, float(raw)))
        except (TypeError, ValueError):
            return self._WORKER_STALL_SECONDS

    @staticmethod
    def _phase_attempt_count(
        runs: list[WorkerRun],
        item_by_id: dict[str, WorkItem],
        *,
        executor_kind: str,
        expected_action: str,
    ) -> int:
        prefix = f"delegated_worker_evidence: {executor_kind}/{expected_action}"
        count = 0
        for run in runs:
            if run.executor_kind != executor_kind:
                continue
            item = item_by_id.get(run.work_item_id)
            if item is None:
                continue
            if any(str(criterion).strip() == prefix for criterion in item.acceptance_criteria):
                count += 1
        return count

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

    def _durable_route_policy(self, event, root: WorkItem) -> object:
        """Resolve project policy from durable Work truth before model routing.

        Explicit natural-language restrictions are persisted on WorkThread, not
        in model memory. A later delegated WorkerRun in the same thread therefore
        inherits the policy after restart. Per-event policy remains supported as
        a narrower/current-call overlay. Malformed explicit values are preserved
        for ModelRouter to reject fail-closed.
        """

        thread = self.resident.work_ledger.get_thread(root.work_thread_id)
        persisted: object = None
        if thread is not None:
            persisted = thread.metadata.get("route_policy")

        inferred = infer_thread_route_policy(str(getattr(event, "task", "") or ""))
        if inferred is not None:
            durable = merge_route_policy(persisted, inferred)
            if thread is None:
                raise RuntimeError("delegated route policy lost its durable WorkThread")
            metadata = dict(thread.metadata)
            metadata["route_policy"] = durable
            thread.metadata = metadata
            from .models import utc_now

            thread.updated_at = utc_now()
            self.resident.work_ledger._save_thread(thread)
            persisted = durable

        explicit = event.payload.get("route_policy")
        if explicit is not None and not isinstance(explicit, dict):
            return explicit
        return merge_route_policy(persisted, explicit)

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
        route_policy = self._durable_route_policy(event, root)
        request.context = {
            **dict(request.context or {}),
            **({"route_policy": route_policy} if route_policy else {}),
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
        record_worker_progress(
            self.resident.work_ledger,
            worker.worker_run_id,
            stage="context_bound",
            evidence={
                "model_goal_id": worker.model_goal_id,
                "work_item_id": child.work_item_id,
                "plan_version": root.plan_version,
                "expected_action": expected_action,
            },
        )
        return request
