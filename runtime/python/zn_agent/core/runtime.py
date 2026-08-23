from __future__ import annotations

import json
import threading
import uuid

from .critic import Critic, DefaultCritic
from .evolution import EvolutionEngine
from .models import (
    AgentIdentity,
    Experience,
    Goal,
    GoalStatus,
    KernelRunResult,
    ModelRoute,
)
from .router import ModelRouter, NoRouteAvailable
from .self_model import SelfModel
from .store import KernelStore
from .worker import WorkerFactory


class ZNKernelRuntime:
    """Persistent top-level control loop for ZN Agent V1."""

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
    ) -> KernelRunResult:
        if not task or not task.strip():
            raise ValueError("task must not be empty")

        with self._resource_lock:
            router = self.router
            worker_factory = self.worker_factory
            configured_attempts = self.max_attempts

        goal = Goal(
            goal_id=f"goal-{uuid.uuid4().hex[:12]}",
            task=task.strip(),
            required_capabilities=tuple(required_capabilities or ("general",)),
            priority=priority,
            metadata=dict(metadata or {}),
        )
        self.store.save_goal(goal)

        excluded: set[str] = set()
        experiences: list[Experience] = []
        previous_failures: list[str] = []
        last_route: ModelRoute | None = None
        last_result = None
        last_assessment = None

        attempt_limit = configured_attempts
        if max_attempts_override is not None:
            attempt_limit = max(1, min(configured_attempts, int(max_attempts_override)))

        for attempt in range(1, attempt_limit + 1):
            try:
                route = router.select(goal, excluded=excluded)
            except NoRouteAvailable:
                break

            last_route = route
            goal.status = GoalStatus.RUNNING
            goal.attempts = attempt
            goal.route_id = route.route_id
            self.store.save_goal(goal)

            kernel_context = self._build_worker_context(
                goal, route, attempt, previous_failures
            )
            worker = worker_factory.create(route)
            result = worker.run(goal, kernel_context)
            assessment = self.critic.assess(goal, result)
            last_result = result
            last_assessment = assessment

            experience = Experience(
                experience_id=f"exp-{uuid.uuid4().hex[:12]}",
                goal_id=goal.goal_id,
                route_id=route.route_id,
                task=goal.task,
                required_capabilities=goal.required_capabilities,
                assessment=assessment,
                response_excerpt=result.response[:2000],
                error=result.error,
                metrics=dict(result.metrics),
            )
            self.store.add_experience(experience)
            # A model solving a task is evidence about that external route, not
            # evidence that ZN can now perform the task independently. ZN's own
            # knowledge/ability profile is updated later by the resident life
            # cycle when learning is integrated or native work succeeds.
            self.self_model.learn_external_route(
                route.route_id,
                goal.task,
                goal.required_capabilities,
                assessment,
            )
            experiences.append(experience)

            if assessment.success:
                goal.status = GoalStatus.SUCCEEDED
                self.store.save_goal(goal)
                return KernelRunResult(
                    goal=goal,
                    route=route,
                    worker_result=result,
                    assessment=assessment,
                    experiences=tuple(experiences),
                    proposal=None,
                )

            excluded.add(route.route_id)
            previous_failures.append(
                f"Attempt {attempt} via {route.route_id}: "
                + "; ".join(assessment.reasons or ("failed",))
            )

        if last_route is None or last_result is None or last_assessment is None:
            raise NoRouteAvailable("no route could execute the goal")

        goal.status = GoalStatus.FAILED
        self.store.save_goal(goal)
        proposal = self.evolution.consider(goal, experiences[-1])
        return KernelRunResult(
            goal=goal,
            route=last_route,
            worker_result=last_result,
            assessment=last_assessment,
            experiences=tuple(experiences),
            proposal=proposal,
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
        return (
            "You are an external cognitive resource temporarily consulted by ZN. "
            "Answer the bounded question in the goal; you are not the persistent "
            "agent and you do not own its identity, memories, goals, or body. "
            "Use only the supplied context unless the task itself requires a tool. "
            "Return the cognitive or task result accurately so ZN can evaluate and "
            "integrate it.\n\nBOUNDED CONTEXT:\n"
            + json.dumps(state, ensure_ascii=False, indent=2)
        )
