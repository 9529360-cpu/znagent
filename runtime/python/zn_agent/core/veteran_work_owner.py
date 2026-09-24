from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .home import get_zn_home
from .router import ModelRouter, NoRouteAvailable
from .veteran_candidate_projection import (
    VeteranCandidateProjector,
    VeteranProjectionError,
    final_candidate_from_status,
)
from .veteran_engineering import (
    VeteranEngineeringCapability,
    VeteranMcpClient,
    VeteranSidecarError,
    VeteranWorkerRunExecutor,
    configure_veteran_project_validation,
    default_veteran_state_root,
    ensure_veteran_operator_policy,
)


_VETERAN_CHILD_CRITERION = "veteran_engineering_mission: proved_candidate_projected_v1"
_TERMINAL_FAILURES = frozenset({"failed", "blocked", "cancelled"})
_CODING_TOOL_SCOPE = (
    "workspace.read",
    "workspace.write",
    "terminal.python",
    "terminal.test",
    "git.status",
    "git.diff",
)
_CODING_AUTHORITY_SCOPE = (
    "workspace_read",
    "workspace_write",
    "terminal_execute",
)


@dataclass(frozen=True, slots=True)
class VeteranWorkOwnerStep:
    state: str
    worker_run_id: str
    work_item_id: str
    mission_id: str | None = None
    phase: str | None = None
    message: str | None = None
    candidate_commit: str | None = None
    projected_paths: tuple[str, ...] = ()


class VeteranEngineeringWorkOwner:
    """Own one broad coding Work through one durable Veteran Mission.

    ZN owns Root/child Work, permissions and completion. Veteran owns the
    repository-local engineering Mission. Each call advances at most one
    durable Mission transition so Resident pulses remain resumable.
    """

    def __init__(
        self,
        *,
        ledger: Any,
        env: Mapping[str, str] | None = None,
        client_factory: Any = VeteranMcpClient,
        projector_factory: Any = VeteranCandidateProjector,
    ) -> None:
        self.ledger = ledger
        self.env = dict(os.environ if env is None else env)
        self.client_factory = client_factory
        self.projector_factory = projector_factory

    @staticmethod
    def handles(event: Any) -> bool:
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            return False
        return str(payload.get("engineering_mode") or "").strip().lower() == "veteran"

    @staticmethod
    def policy_block_reason(event: Any) -> str | None:
        """Fail closed when direct Codex execution cannot honor ZN route policy."""
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            return "Veteran engineering requires an explicit event payload"

        model_policy = str(payload.get("model_policy") or "on_demand").strip().lower()
        if model_policy in {"never", "off", "local_only"}:
            return f"Veteran engineering requires cloud model use, disabled by policy '{model_policy}'"

        raw_policy = payload.get("route_policy")
        if raw_policy is not None and not isinstance(raw_policy, dict):
            return "Veteran engineering route_policy is malformed"
        policy = dict(raw_policy or {})
        try:
            ModelRouter.validate_route_policy(policy)
        except (NoRouteAvailable, TypeError, ValueError) as exc:
            return f"Veteran engineering route_policy is invalid: {exc}"

        direct_classification = str(payload.get("data_classification") or "").strip().lower()
        classification = direct_classification or str(
            policy.get("data_classification") or ""
        ).strip().lower()
        if (
            classification in {"local_only", "cloud_denied"}
            or policy.get("local_only") is True
            or policy.get("cloud_forbidden") is True
        ):
            return "Veteran engineering is blocked because cloud model use is forbidden"

        provider_aliases = {"openai", "codex", "openai-codex"}
        pinned = str(policy.get("pinned_provider") or "").strip().lower()
        if pinned and pinned not in provider_aliases:
            return "Veteran engineering Codex provider conflicts with pinned_provider"

        allowed = VeteranEngineeringWorkOwner._policy_string_set(
            policy.get("allowed_providers")
        )
        if ("allowed_providers" in policy or policy.get("allow_local") is True) and not (
            allowed & provider_aliases
        ):
            return "Veteran engineering Codex provider is outside the provider allowlist"

        denied = VeteranEngineeringWorkOwner._policy_string_set(
            policy.get("denied_providers")
        )
        if denied & provider_aliases:
            return "Veteran engineering Codex provider is explicitly denied"

        if policy.get("pinned_model") or policy.get("denied_models"):
            return (
                "Veteran engineering cannot yet prove Codex model identity against "
                "pinned/denied model policy"
            )
        if policy.get("required_policy_tags") or policy.get("required_authority_scopes"):
            return (
                "Veteran engineering cannot yet prove the requested route policy tags "
                "or provider authority scopes"
            )
        return None

    @staticmethod
    def _policy_string_set(value: object) -> set[str]:
        if value is None:
            return set()
        if isinstance(value, str):
            values = (value,)
        elif isinstance(value, (list, tuple, set, frozenset)):
            values = value
        else:
            return set()
        return {
            str(item).strip().lower()
            for item in values
            if str(item).strip()
        }

    def advance(
        self,
        *,
        root: Any,
        workspace: str | os.PathLike[str],
        goal: str,
        done_definition: str,
        risk_envelope: str = "medium",
        non_goals: tuple[str, ...] = (),
    ) -> VeteranWorkOwnerStep:
        repo = Path(workspace).expanduser().resolve(strict=True)
        if not repo.is_dir():
            raise VeteranSidecarError("Veteran engineering workspace must be a directory")

        child = self._ensure_child(root, goal=goal)
        run = self._ensure_worker_run(child)
        if run.state == "completed":
            return self._completed_step(child, run)
        if run.state in {"failed", "stale"}:
            return VeteranWorkOwnerStep(
                state="blocked",
                worker_run_id=run.worker_run_id,
                work_item_id=child.work_item_id,
                message=run.error or run.result_summary or f"WorkerRun is {run.state}",
            )

        state_root = self._state_root()
        operator = ensure_veteran_operator_policy(state_root, env=self.env)
        if operator is None:
            raise VeteranSidecarError(
                "Veteran engineering is enabled but no bounded Codex worker is configured"
            )

        with self.client_factory(
            state_root=state_root,
            timeout_seconds=300,
        ) as client:
            capability = VeteranEngineeringCapability(
                client,
                namespace=run.worker_run_id,
            )
            executor = VeteranWorkerRunExecutor(
                ledger=self.ledger,
                capability=capability,
            )
            checkpoint = self._mission_checkpoint(run)
            if checkpoint is None and Path(operator).is_file():
                before_policy = Path(operator).read_bytes()
                project_probe = capability.open_project(
                    repo,
                    name=f"zn-{run.worker_run_id}",
                    request_scope="project_environment_probe",
                )
                configure_veteran_project_validation(
                    state_root,
                    workspace=repo,
                    project=project_probe,
                )
                after_policy = Path(operator).read_bytes()
                if before_policy != after_policy:
                    return VeteranWorkOwnerStep(
                        state="configured",
                        worker_run_id=run.worker_run_id,
                        work_item_id=child.work_item_id,
                        phase="planning",
                        message=(
                            "Veteran repository validation policy bound from "
                            "current project environment; restart sidecar before planning"
                        ),
                    )
            if checkpoint is None:
                ref = executor.prepare(
                    worker_run_id=run.worker_run_id,
                    repo_path=repo,
                    goal=goal,
                    done_definition=done_definition,
                    tasks=None,
                    risk_envelope=self._risk(risk_envelope),
                    non_goals=non_goals,
                )
                return VeteranWorkOwnerStep(
                    state="planned",
                    worker_run_id=run.worker_run_id,
                    work_item_id=child.work_item_id,
                    mission_id=ref.mission_id,
                    phase="execution",
                    message="Veteran mission planned from current repository truth",
                )

            outcome = executor.refresh(worker_run_id=run.worker_run_id)
            if self._is_final_candidate(outcome.raw_status):
                return self._project_final_candidate(
                    child=child,
                    run_id=run.worker_run_id,
                    workspace=repo,
                    outcome=outcome,
                )
            if outcome.status in _TERMINAL_FAILURES:
                return self._record_failure(
                    child=child,
                    run_id=run.worker_run_id,
                    outcome=outcome,
                )

            transition = capability.advance(
                outcome.mission_id,
                run_workers=True,
            )
            refreshed = executor.refresh(worker_run_id=run.worker_run_id)
            if bool(transition.get("blocked")):
                return self._record_proof_gate_blocker(
                    child=child,
                    run_id=run.worker_run_id,
                    outcome=refreshed,
                    transition=transition,
                )
            return VeteranWorkOwnerStep(
                state="advanced",
                worker_run_id=run.worker_run_id,
                work_item_id=child.work_item_id,
                mission_id=refreshed.mission_id,
                phase=refreshed.phase,
                message=f"Veteran mission advanced to {refreshed.phase or 'unknown'}",
            )

    def _ensure_child(self, root: Any, *, goal: str) -> Any:
        current_plan = self.ledger.plan_version(root.work_thread_id)
        matches = [
            item
            for item in self.ledger.list_work_items(root.work_thread_id)
            if item.parent_work_item_id == root.work_item_id
            and item.plan_version == current_plan
            and _VETERAN_CHILD_CRITERION in tuple(item.acceptance_criteria or ())
        ]
        if len(matches) > 1:
            raise VeteranSidecarError(
                "current Work plan contains multiple Veteran engineering owners"
            )
        if matches:
            return matches[0]
        return self.ledger.create_child_item(
            root_work_item_id=root.work_item_id,
            title="Engineering Mission",
            objective=(" ".join(str(goal or "").strip().split())[:1200] or root.objective),
            acceptance_criteria=[_VETERAN_CHILD_CRITERION],
        )

    def _ensure_worker_run(self, child: Any) -> Any:
        runs = [
            run
            for run in self.ledger.list_worker_runs(work_item_id=child.work_item_id)
            if run.plan_version == child.plan_version and run.executor_kind == "coding"
        ]
        live = [run for run in runs if run.state in {"queued", "running"}]
        if len(live) > 1:
            raise VeteranSidecarError(
                "Veteran engineering child has multiple live coding WorkerRuns"
            )
        if live:
            return live[-1]
        completed = [run for run in runs if run.state == "completed"]
        if completed:
            return completed[-1]
        failed = [run for run in runs if run.state in {"failed", "stale"}]
        if failed:
            return failed[-1]
        return self.ledger.start_worker_run(
            work_item_id=child.work_item_id,
            executor_kind="coding",
            tool_scope=_CODING_TOOL_SCOPE,
            authority_scope=_CODING_AUTHORITY_SCOPE,
        )

    def _project_final_candidate(
        self,
        *,
        child: Any,
        run_id: str,
        workspace: Path,
        outcome: Any,
    ) -> VeteranWorkOwnerStep:
        candidate = final_candidate_from_status(outcome.raw_status)
        projection = self.projector_factory(workspace).project(candidate)
        run = self.ledger.worker_run(run_id)
        if run is None:
            raise VeteranSidecarError("Veteran WorkerRun disappeared before projection")
        metrics = dict(run.metrics or {})
        checkpoint = dict(metrics.get("veteran_engineering") or {})
        checkpoint.update(
            {
                "state": "candidate_projected",
                "phase": "finalize",
                "candidate_id": candidate.candidate_id,
                "candidate_commit": candidate.candidate_commit,
                "merge_proposal_id": candidate.merge_proposal_id,
                "projected_paths": list(projection.paths),
                "projection_already_applied": projection.already_applied,
            }
        )
        metrics["veteran_engineering"] = checkpoint
        run = self.ledger.update_worker_run_metrics(run_id, metrics=metrics)
        result = {
            "contract": "zn-veteran-proved-candidate-v1",
            "mission_id": candidate.mission_id,
            "candidate_id": candidate.candidate_id,
            "candidate_commit": candidate.candidate_commit,
            "source_head": candidate.source_head,
            "projected_paths": list(projection.paths),
            "head_unchanged": True,
            "index_unchanged": True,
        }
        persisted = self.ledger.complete_worker_run(
            run_id,
            result_summary=json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            artifact_refs=[
                {
                    "kind": "veteran_candidate",
                    "mission_id": candidate.mission_id,
                    "candidate_id": candidate.candidate_id,
                    "commit": candidate.candidate_commit,
                    "source_head": candidate.source_head,
                    "paths": list(projection.paths)[:128],
                }
            ],
            claimed_completion=True,
            verification_status="veteran_candidate_projected",
            metrics=run.metrics,
        )
        self.ledger.complete_child_item(
            child.work_item_id,
            result=persisted.result_summary or "Veteran candidate projected",
        )
        return VeteranWorkOwnerStep(
            state="projected",
            worker_run_id=run_id,
            work_item_id=child.work_item_id,
            mission_id=candidate.mission_id,
            phase="finalize",
            message="proved Veteran candidate projected into ZN workspace",
            candidate_commit=candidate.candidate_commit,
            projected_paths=projection.paths,
        )

    def _record_proof_gate_blocker(
        self,
        *,
        child: Any,
        run_id: str,
        outcome: Any,
        transition: Mapping[str, Any],
    ) -> VeteranWorkOwnerStep:
        action = str(transition.get("action") or "proof-gate").strip()[:120]
        message = (
            f"Veteran mission {outcome.mission_id} proof gate blocked "
            f"at {outcome.phase or 'unknown'} during {action}"
        )
        run = self.ledger.worker_run(run_id)
        metrics = dict(getattr(run, "metrics", {}) or {})
        checkpoint = dict(metrics.get("veteran_engineering") or {})
        checkpoint.update(
            {
                "state": "proof_gate_blocked",
                "phase": outcome.phase or "unknown",
                "blocked_action": action,
            }
        )
        metrics["veteran_engineering"] = checkpoint
        self.ledger.fail_worker_run(
            run_id,
            error=message,
            result_summary=message,
            claimed_completion=False,
            verification_status="veteran_proof_gate_blocked",
            metrics=metrics,
        )
        self.ledger.block_child_item(child.work_item_id, blocker=message)
        return VeteranWorkOwnerStep(
            state="blocked",
            worker_run_id=run_id,
            work_item_id=child.work_item_id,
            mission_id=outcome.mission_id,
            phase=outcome.phase,
            message=message,
        )

    def _record_failure(self, *, child: Any, run_id: str, outcome: Any) -> VeteranWorkOwnerStep:
        message = (
            f"Veteran mission {outcome.mission_id} stopped "
            f"at {outcome.phase or 'unknown'} with status {outcome.status or 'unknown'}"
        )
        run = self.ledger.worker_run(run_id)
        metrics = dict(getattr(run, "metrics", {}) or {})
        self.ledger.fail_worker_run(
            run_id,
            error=message,
            result_summary=message,
            claimed_completion=False,
            verification_status="veteran_mission_failed",
            metrics=metrics,
        )
        self.ledger.block_child_item(child.work_item_id, blocker=message)
        return VeteranWorkOwnerStep(
            state="blocked",
            worker_run_id=run_id,
            work_item_id=child.work_item_id,
            mission_id=outcome.mission_id,
            phase=outcome.phase,
            message=message,
        )

    def _completed_step(self, child: Any, run: Any) -> VeteranWorkOwnerStep:
        checkpoint = self._mission_checkpoint(run) or {}
        if child.status != "completed":
            self.ledger.complete_child_item(
                child.work_item_id,
                result=run.result_summary or "Veteran engineering WorkerRun completed",
            )
        return VeteranWorkOwnerStep(
            state="projected",
            worker_run_id=run.worker_run_id,
            work_item_id=child.work_item_id,
            mission_id=str(checkpoint.get("mission_id") or "") or None,
            phase=str(checkpoint.get("phase") or "") or None,
            candidate_commit=str(checkpoint.get("candidate_commit") or "") or None,
            projected_paths=tuple(
                str(path)
                for path in checkpoint.get("projected_paths") or ()
                if str(path)
            ),
            message="Veteran engineering Work already completed",
        )

    def _state_root(self) -> Path:
        explicit = str(self.env.get("ZN_VETERAN_STATE_ROOT") or "").strip()
        if explicit:
            return Path(explicit).expanduser().resolve()
        return default_veteran_state_root(get_zn_home())

    @staticmethod
    def _mission_checkpoint(run: Any) -> dict[str, Any] | None:
        metrics = getattr(run, "metrics", None)
        if not isinstance(metrics, dict):
            return None
        checkpoint = metrics.get("veteran_engineering")
        return dict(checkpoint) if isinstance(checkpoint, dict) else None

    @staticmethod
    def _risk(value: str) -> str:
        normalized = str(value or "").strip().lower()
        return normalized if normalized in {"low", "medium", "high", "critical"} else "medium"

    @staticmethod
    def _is_final_candidate(status: Mapping[str, Any]) -> bool:
        mission = status.get("mission")
        return (
            isinstance(mission, dict)
            and mission.get("phase") == "finalize"
            and mission.get("status") == "awaiting-operator-merge"
        )
