from __future__ import annotations

import json
import threading
import uuid
from typing import Callable

from .critic import Critic, DefaultCritic
from .evolution import EvolutionEngine
from .kernel_accounting import KernelAttemptAccountingJournal
from .models import (
    AgentIdentity,
    Assessment,
    Experience,
    Goal,
    GoalStatus,
    ImprovementProposal,
    KernelRunResult,
    ModelRoute,
    ProposalStatus,
    WorkerResult,
    utc_now,
)
from .router import ModelRouter, NoRouteAvailable
from .self_model import SelfModel
from .store import KernelStore
from .worker import WorkerFactory


class ZNKernelRuntime:
    """Persistent top-level control loop for ZN Agent V1."""

    _DURABLE_RUN_KEY = "_durable_external_run"
    _DURABLE_RUN_VERSION = 1

    def __init__(
        self,
        *,
        store: KernelStore,
        routes: list[ModelRoute],
        worker_factory: WorkerFactory,
        critic: Critic | None = None,
        identity: AgentIdentity | None = None,
        max_attempts: int = 2,
        resource_status: dict | None = None,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.store = store
        self.identity = store.get_or_create_identity(identity)
        self.self_model = SelfModel(store)
        self.attempt_accounting = KernelAttemptAccountingJournal(store)
        self._resource_lock = threading.RLock()
        self.router = ModelRouter(routes, self.self_model)
        self.worker_factory = worker_factory
        self.resource_status = dict(resource_status or {})
        self.critic = critic or DefaultCritic()
        self.evolution = EvolutionEngine(store, self.self_model)
        self.max_attempts = max_attempts

    def reconfigure_resources(
        self,
        *,
        routes: list[ModelRoute],
        worker_factory: WorkerFactory,
        max_attempts: int | None = None,
        resource_status: dict | None = None,
    ) -> None:
        """Replace external cognition resources without replacing the resident.

        An in-flight goal snapshots the previous router/factory before it starts.
        Later goals see the new resource plan. Identity, store, SelfModel, lived
        memory and the resident life loop remain untouched.
        """

        if not routes:
            raise ValueError("at least one model route is required")
        with self._resource_lock:
            self.router = ModelRouter(routes, self.self_model)
            self.worker_factory = worker_factory
            if max_attempts is not None:
                self.max_attempts = max(1, int(max_attempts))
            if resource_status is not None:
                self.resource_status = dict(resource_status)

    def run_goal(
        self,
        task: str,
        *,
        required_capabilities: tuple[str, ...] = ("general",),
        priority: int = 0,
        metadata: dict | None = None,
        max_attempts_override: int | None = None,
        goal_id: str | None = None,
        on_cognitive_delta: Callable[[str], None] | None = None,
        on_cognitive_reset: Callable[[], None] | None = None,
    ) -> KernelRunResult:
        """Run or resume one durable external-cognition goal.

        Provider dispatch is an at-most-once boundary. Before ``worker.run`` the
        selected attempt is persisted as ``dispatching``. A returned worker result
        is then persisted in full before local critique or route learning. If a
        restart finds an attempt still at ``dispatching``, the external result is
        unknowable and ZN fails that goal conservatively instead of replaying a
        potentially completed/costly provider call.
        """
        if not task or not task.strip():
            raise ValueError("task must not be empty")

        with self._resource_lock:
            router = self.router
            worker_factory = self.worker_factory
            configured_attempts = self.max_attempts

        normalized_task = task.strip()
        normalized_capabilities = tuple(required_capabilities or ("general",))
        attempt_limit = configured_attempts
        if max_attempts_override is not None:
            attempt_limit = max(1, min(configured_attempts, int(max_attempts_override)))

        normalized_goal_id = str(goal_id or "").strip() or f"goal-{uuid.uuid4().hex[:12]}"
        goal = self.store.get_goal(normalized_goal_id)
        if goal is None:
            effective_metadata = self._metadata_with_resident_event_route_policy(metadata)
            goal = Goal(
                goal_id=normalized_goal_id,
                task=normalized_task,
                required_capabilities=normalized_capabilities,
                priority=priority,
                metadata=effective_metadata,
            )
            goal.metadata[self._DURABLE_RUN_KEY] = {
                "version": self._DURABLE_RUN_VERSION,
                "attempt_limit": attempt_limit,
                "attempts": [],
                "final": None,
            }
            self.store.save_goal(goal)
        else:
            if goal.task != normalized_task:
                raise ValueError("durable goal_id already belongs to a different task")
            if tuple(goal.required_capabilities) != normalized_capabilities:
                raise ValueError(
                    "durable goal_id already belongs to different required capabilities"
                )
            durable = self._durable_state(goal)
            try:
                attempt_limit = max(1, int(durable.get("attempt_limit") or attempt_limit))
            except (TypeError, ValueError):
                attempt_limit = max(1, attempt_limit)

        completed = self.load_goal_result(goal.goal_id)
        if completed is not None:
            return completed

        while True:
            durable = self._durable_state(goal)
            attempts = durable["attempts"]
            if attempts:
                last = attempts[-1]
                status = str(last.get("status") or "")
                if status == "dispatching":
                    self._checkpoint_uncertain_dispatch(goal, last)
                    durable = self._durable_state(goal)
                    attempts = durable["attempts"]
                    last = attempts[-1]
                    status = str(last.get("status") or "")
                if status == "worker_observed":
                    self._assess_observed_attempt(goal, last)
                    durable = self._durable_state(goal)
                    attempts = durable["attempts"]
                    last = attempts[-1]
                    status = str(last.get("status") or "")
                if status in {"assessed", "settled"}:
                    self._settle_assessed_attempt(goal, last)
                    durable = self._durable_state(goal)
                    attempts = durable["attempts"]
                    last = attempts[-1]
                    assessment = self._assessment_from_data(last.get("assessment"))
                    if assessment.success:
                        return self._finish_goal(goal, last, succeeded=True)
                    if bool(last.get("outcome_uncertain")) or bool(
                        last.get("assessment_error")
                    ):
                        return self._finish_goal(
                            goal,
                            last,
                            succeeded=False,
                            allow_proposal=False,
                        )
                    if len(attempts) >= attempt_limit:
                        return self._finish_goal(goal, last, succeeded=False)

            excluded = {
                str(item.get("route", {}).get("route_id") or "")
                for item in attempts
                if isinstance(item, dict)
            }
            excluded.discard("")
            try:
                route = router.select(goal, excluded=excluded)
            except NoRouteAvailable:
                if not attempts:
                    raise
                return self._finish_goal(goal, attempts[-1], succeeded=False)

            attempt_number = len(attempts) + 1
            goal.status = GoalStatus.RUNNING
            goal.attempts = attempt_number
            goal.route_id = route.route_id
            previous_failures = self._previous_failure_summaries(attempts)

            try:
                worker = worker_factory.create(route)
            except Exception as exc:
                local_failure = WorkerResult(
                    success=False,
                    error=f"{type(exc).__name__}: {exc}",
                    metrics={"model_invoked": False, "worker_factory_failed": True},
                )
                attempt = self._new_attempt(
                    goal,
                    route,
                    attempt_number,
                    status="worker_observed",
                )
                attempt["worker_result"] = self._worker_result_data(local_failure)
                self._append_attempt_and_save(goal, attempt)
                continue

            attempt = self._new_attempt(
                goal,
                route,
                attempt_number,
                status="dispatching",
            )
            self._append_attempt_and_save(goal, attempt)
            kernel_context = self._build_worker_context(
                goal, route, attempt_number, previous_failures
            )
            try:
                if on_cognitive_reset is not None:
                    on_cognitive_reset()
                run_stream = getattr(worker, "run_stream", None)
                if on_cognitive_delta is not None and callable(run_stream):
                    result = run_stream(goal, kernel_context, on_cognitive_delta)
                else:
                    result = worker.run(goal, kernel_context)
            except Exception as exc:
                result = WorkerResult(
                    success=False,
                    error=f"{type(exc).__name__}: {exc}",
                    metrics={
                        "model_invoked": True,
                        "outcome_uncertain": True,
                        "worker_exception": True,
                    },
                )
                attempt["outcome_uncertain"] = True

            attempt["worker_result"] = self._worker_result_data(result)
            attempt["status"] = "worker_observed"
            self.store.save_goal(goal)

    def _metadata_with_resident_event_route_policy(self, metadata: dict | None) -> dict:
        """Inherit an already-bound Work event policy for direct cognition calls.

        Some specialized Resident cognition paths call Kernel directly instead of
        going through the normal CognitionRequest context builder. They already
        carry ``resident_event_id``. Work ingress owns policy inference and
        persistence; this method only follows that existing durable event link and
        copies its explicit ``route_policy`` onto a new cognition Goal when the
        caller did not already supply a direct or nested policy.

        Kernel never reads WorkThread state and never infers user language here.
        ModelRouter remains the sole hard-eligibility and fail-closed owner.
        """

        resolved = dict(metadata or {})
        if self._metadata_has_route_policy(resolved):
            return resolved
        event_id = str(resolved.get("resident_event_id") or "").strip()
        if not event_id:
            return resolved
        event = self.store.get_event(event_id)
        if event is None:
            return resolved
        payload = event.payload if isinstance(event.payload, dict) else {}
        if "route_policy" in payload and payload.get("route_policy") is not None:
            resolved["route_policy"] = payload.get("route_policy")
        return resolved

    @staticmethod
    def _metadata_has_route_policy(metadata: dict) -> bool:
        if metadata.get("route_policy") is not None:
            return True
        cognition = metadata.get("cognition_request")
        if not isinstance(cognition, dict):
            return False
        context = cognition.get("context")
        return isinstance(context, dict) and context.get("route_policy") is not None

    def load_goal_result(self, goal_id: str) -> KernelRunResult | None:
        goal = self.store.get_goal(str(goal_id or "").strip())
        if goal is None:
            return None
        durable = self._durable_state(goal, initialize=False)
        if durable is None or not isinstance(durable.get("final"), dict):
            return None
        if goal.status not in {GoalStatus.SUCCEEDED, GoalStatus.FAILED}:
            return None
        return self._result_from_goal(goal)

    def _durable_state(
        self,
        goal: Goal,
        *,
        initialize: bool = True,
    ) -> dict | None:
        raw = goal.metadata.get(self._DURABLE_RUN_KEY)
        if isinstance(raw, dict) and int(raw.get("version") or 0) == self._DURABLE_RUN_VERSION:
            attempts = raw.get("attempts")
            if not isinstance(attempts, list):
                raise RuntimeError("durable kernel attempt ledger is malformed")
            return raw
        if not initialize:
            return None
        raise RuntimeError("goal has no compatible durable kernel attempt ledger")

    def _new_attempt(
        self,
        goal: Goal,
        route: ModelRoute,
        attempt_number: int,
        *,
        status: str,
    ) -> dict:
        return {
            "attempt": int(attempt_number),
            "route": self._route_data(route),
            "status": str(status),
            "experience_id": f"exp-{goal.goal_id}-{int(attempt_number)}",
            "experience_created_at": utc_now(),
            "worker_result": None,
            "assessment": None,
            "outcome_uncertain": False,
            "assessment_error": False,
        }

    def _append_attempt_and_save(self, goal: Goal, attempt: dict) -> None:
        durable = self._durable_state(goal)
        durable["attempts"].append(attempt)
        self.store.save_goal(goal)

    def _checkpoint_uncertain_dispatch(self, goal: Goal, attempt: dict) -> None:
        attempt["worker_result"] = self._worker_result_data(
            WorkerResult(
                success=False,
                error=(
                    "external cognition was interrupted after the durable dispatch "
                    "boundary; provider outcome is unknown and replay is blocked"
                ),
                metrics={"model_invoked": True, "outcome_uncertain": True},
            )
        )
        attempt["assessment"] = self._assessment_data(
            Assessment(
                success=False,
                quality=0.0,
                confidence=0.0,
                reasons=(
                    "provider outcome is unknown after interrupted durable dispatch",
                ),
            )
        )
        attempt["outcome_uncertain"] = True
        attempt["status"] = "assessed"
        self.store.save_goal(goal)

    def _assess_observed_attempt(self, goal: Goal, attempt: dict) -> None:
        result = self._worker_result_from_data(attempt.get("worker_result"))
        if bool(attempt.get("outcome_uncertain")):
            assessment = Assessment(
                success=False,
                quality=0.0,
                confidence=0.0,
                reasons=("external provider outcome is uncertain; replay is blocked",),
            )
        else:
            try:
                assessment = self.critic.assess(goal, result)
            except Exception as exc:
                attempt["assessment_error"] = True
                assessment = Assessment(
                    success=False,
                    quality=0.0,
                    confidence=0.0,
                    reasons=(f"critic failed: {type(exc).__name__}: {exc}",),
                )
        attempt["assessment"] = self._assessment_data(assessment)
        attempt["status"] = "assessed"
        self.store.save_goal(goal)

    def _settle_assessed_attempt(self, goal: Goal, attempt: dict) -> None:
        assessment = self._assessment_from_data(attempt.get("assessment"))
        result = self._worker_result_from_data(attempt.get("worker_result"))
        route = self._route_from_data(attempt.get("route"))
        experience = Experience(
            experience_id=str(attempt.get("experience_id") or ""),
            goal_id=goal.goal_id,
            route_id=route.route_id,
            task=goal.task,
            required_capabilities=goal.required_capabilities,
            assessment=assessment,
            response_excerpt=result.response[:2000],
            error=result.error,
            metrics=dict(result.metrics),
            created_at=str(attempt.get("experience_created_at") or utc_now()),
        )
        self.store.add_experience(experience)
        if not bool(attempt.get("outcome_uncertain")) and not bool(
            attempt.get("assessment_error")
        ):
            self.attempt_accounting.record_external_route_assessment(
                goal_id=goal.goal_id,
                attempt=int(attempt.get("attempt") or 0),
                route_id=route.route_id,
                task=goal.task,
                required_capabilities=goal.required_capabilities,
                assessment=assessment,
            )
        if attempt.get("status") != "settled":
            attempt["status"] = "settled"
            self.store.save_goal(goal)

    def _finish_goal(
        self,
        goal: Goal,
        attempt: dict,
        *,
        succeeded: bool,
        allow_proposal: bool = True,
    ) -> KernelRunResult:
        durable = self._durable_state(goal)
        final = durable.get("final")
        if isinstance(final, dict):
            return self._result_from_goal(goal)

        proposal = None
        if not succeeded and allow_proposal:
            experience = self._attempt_to_experience(goal, attempt)
            proposal = self.evolution.consider(goal, experience)

        goal.status = GoalStatus.SUCCEEDED if succeeded else GoalStatus.FAILED
        goal.attempts = int(attempt.get("attempt") or goal.attempts)
        route = self._route_from_data(attempt.get("route"))
        goal.route_id = route.route_id
        durable["final"] = {
            "attempt": int(attempt.get("attempt") or 0),
            "proposal": self._proposal_data(proposal) if proposal is not None else None,
        }
        self.store.save_goal(goal)
        return self._result_from_goal(goal)

    def _result_from_goal(self, goal: Goal) -> KernelRunResult:
        durable = self._durable_state(goal)
        final = durable.get("final")
        if not isinstance(final, dict):
            raise RuntimeError("durable kernel goal has no final result")
        final_attempt_number = int(final.get("attempt") or 0)
        attempts = [item for item in durable["attempts"] if isinstance(item, dict)]
        final_attempt = next(
            (
                item
                for item in attempts
                if int(item.get("attempt") or 0) == final_attempt_number
            ),
            None,
        )
        if final_attempt is None:
            raise RuntimeError("durable kernel final attempt is missing")
        experiences = tuple(
            self._attempt_to_experience(goal, item)
            for item in attempts
            if isinstance(item.get("assessment"), dict)
            and isinstance(item.get("worker_result"), dict)
        )
        route = self._route_from_data(final_attempt.get("route"))
        worker_result = self._worker_result_from_data(final_attempt.get("worker_result"))
        assessment = self._assessment_from_data(final_attempt.get("assessment"))
        proposal_raw = final.get("proposal")
        proposal = (
            self._proposal_from_data(proposal_raw)
            if isinstance(proposal_raw, dict)
            else None
        )
        return KernelRunResult(
            goal=goal,
            route=route,
            worker_result=worker_result,
            assessment=assessment,
            experiences=experiences,
            proposal=proposal,
        )

    def _attempt_to_experience(self, goal: Goal, attempt: dict) -> Experience:
        route = self._route_from_data(attempt.get("route"))
        result = self._worker_result_from_data(attempt.get("worker_result"))
        assessment = self._assessment_from_data(attempt.get("assessment"))
        return Experience(
            experience_id=str(attempt.get("experience_id") or ""),
            goal_id=goal.goal_id,
            route_id=route.route_id,
            task=goal.task,
            required_capabilities=goal.required_capabilities,
            assessment=assessment,
            response_excerpt=result.response[:2000],
            error=result.error,
            metrics=dict(result.metrics),
            created_at=str(attempt.get("experience_created_at") or utc_now()),
        )

    @staticmethod
    def _previous_failure_summaries(attempts: list[dict]) -> list[str]:
        summaries: list[str] = []
        for item in attempts:
            if not isinstance(item, dict) or not isinstance(item.get("assessment"), dict):
                continue
            assessment = ZNKernelRuntime._assessment_from_data(item.get("assessment"))
            if assessment.success:
                continue
            route_id = str(item.get("route", {}).get("route_id") or "unknown")
            number = int(item.get("attempt") or 0)
            summaries.append(
                f"Attempt {number} via {route_id}: "
                + "; ".join(assessment.reasons or ("failed",))
            )
        return summaries

    @staticmethod
    def _route_data(route: ModelRoute) -> dict:
        return {
            "route_id": route.route_id,
            "provider": route.provider,
            "model": route.model,
            "capabilities": dict(route.capabilities),
            "reliability": route.reliability,
            "cost_weight": route.cost_weight,
            "latency_weight": route.latency_weight,
            "metadata": dict(route.metadata),
        }

    @staticmethod
    def _route_from_data(raw) -> ModelRoute:
        if not isinstance(raw, dict):
            raise RuntimeError("durable kernel route snapshot is missing")
        return ModelRoute(
            route_id=str(raw.get("route_id") or ""),
            provider=str(raw.get("provider") or ""),
            model=str(raw.get("model") or ""),
            capabilities=dict(raw.get("capabilities") or {}),
            reliability=float(raw.get("reliability", 0.8)),
            cost_weight=float(raw.get("cost_weight", 0.5)),
            latency_weight=float(raw.get("latency_weight", 0.5)),
            metadata=dict(raw.get("metadata") or {}),
        )

    @staticmethod
    def _worker_result_data(result: WorkerResult) -> dict:
        return {
            "success": bool(result.success),
            "response": str(result.response or ""),
            "verification_passed": result.verification_passed,
            "error": result.error,
            "metrics": dict(result.metrics or {}),
        }

    @staticmethod
    def _worker_result_from_data(raw) -> WorkerResult:
        if not isinstance(raw, dict):
            raise RuntimeError("durable worker result is missing")
        return WorkerResult(
            success=bool(raw.get("success")),
            response=str(raw.get("response") or ""),
            verification_passed=raw.get("verification_passed"),
            error=(str(raw.get("error")) if raw.get("error") is not None else None),
            metrics=dict(raw.get("metrics") or {}),
        )

    @staticmethod
    def _assessment_data(assessment: Assessment) -> dict:
        return {
            "success": bool(assessment.success),
            "quality": float(assessment.quality),
            "confidence": float(assessment.confidence),
            "reasons": list(assessment.reasons),
        }

    @staticmethod
    def _assessment_from_data(raw) -> Assessment:
        if not isinstance(raw, dict):
            raise RuntimeError("durable assessment is missing")
        return Assessment(
            success=bool(raw.get("success")),
            quality=float(raw.get("quality", 0.0)),
            confidence=float(raw.get("confidence", 0.0)),
            reasons=tuple(str(item) for item in raw.get("reasons") or ()),
        )

    @staticmethod
    def _proposal_data(proposal: ImprovementProposal) -> dict:
        return {
            "proposal_id": proposal.proposal_id,
            "goal_id": proposal.goal_id,
            "capability": proposal.capability,
            "hypothesis": proposal.hypothesis,
            "experiment": proposal.experiment,
            "scope": proposal.scope,
            "benchmark_required": proposal.benchmark_required,
            "status": proposal.status.value,
            "created_at": proposal.created_at,
        }

    @staticmethod
    def _proposal_from_data(raw: dict) -> ImprovementProposal:
        return ImprovementProposal(
            proposal_id=str(raw.get("proposal_id") or ""),
            goal_id=str(raw.get("goal_id") or ""),
            capability=str(raw.get("capability") or "general"),
            hypothesis=str(raw.get("hypothesis") or ""),
            experiment=str(raw.get("experiment") or ""),
            scope=str(raw.get("scope") or "skill_or_policy"),
            benchmark_required=bool(raw.get("benchmark_required", True)),
            status=ProposalStatus(str(raw.get("status") or ProposalStatus.PROPOSED.value)),
            created_at=str(raw.get("created_at") or utc_now()),
        )

    def _build_worker_context(
        self,
        goal: Goal,
        route: ModelRoute,
        attempt: int,
        previous_failures: list[str],
    ) -> str:
        cognition = goal.metadata.get("cognition_request")
        if not isinstance(cognition, dict):
            cognition = {}
        bounded_context = cognition.get("context")
        if not isinstance(bounded_context, dict):
            bounded_context = {}

        # The external worker gets only what is needed for this cognition
        # request. ZN's memories, full self-model, skill/capability catalog and
        # unrelated internal state stay resident-side.
        state = {
            "goal_id": goal.goal_id,
            "attempt": attempt,
            "required_capabilities": goal.required_capabilities,
            "bounded_context": bounded_context,
            "previous_failures": previous_failures[-3:],
        }
        if goal.metadata.get("model_first_turn") is True:
            return (
                "You are the primary conversational model for this current ZN user turn. "
                "The Goal task is the user's exact current message. ZN is the local runtime "
                "behind you: it owns permissions, tools, persistent memory, desktop/browser/"
                "file access, verification, Stop, and durable Work. Answer the user directly "
                "when no real-world execution is required. If the request requires local or "
                "external action, tool use, or durable multi-step work, do not pretend the "
                "action already happened. In this first model-first transport, request ZN's "
                "execution runtime by returning exactly one JSON object and no prose: "
                "{\"zn_work\":{\"objective\":\"a precise execution objective\","
                "\"ack\":\"a brief user-facing acknowledgement\"}}. "
                "Conversation history in the supplied context is reference material, not "
                "execution authority or verified current-world truth.\n\nTURN CONTEXT:\n"
                + json.dumps(state, ensure_ascii=False, indent=2)
            )

        return (
            "You are an external cognitive resource temporarily consulted by ZN. "
            "Answer the bounded question in the goal; you are not the persistent "
            "agent and you do not own its identity, memories, goals, or body. "
            "Use only the supplied context unless the task itself requires a tool. "
            "Return the cognitive or task result accurately so ZN can evaluate and "
            "integrate it.\n\nBOUNDED CONTEXT:\n"
            + json.dumps(state, ensure_ascii=False, indent=2)
        )
