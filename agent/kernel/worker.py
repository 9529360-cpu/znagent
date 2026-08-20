from __future__ import annotations

from typing import Any, Callable, Protocol

from .models import Goal, ModelRoute, WorkerResult


class Worker(Protocol):
    def run(self, goal: Goal, kernel_context: str) -> WorkerResult: ...


class WorkerFactory(Protocol):
    def create(self, route: ModelRoute) -> Worker: ...


class UnavailableModelWorker:
    """System-2 placeholder used when the resident has no configured model.

    The resident agent must remain alive and useful through System 1 even when
    no LLM exists. Reaching this worker means a task genuinely needs cognition
    that is not currently installed.
    """

    def run(self, goal: Goal, kernel_context: str) -> WorkerResult:
        return WorkerResult(
            success=False,
            error="No System 2 model is configured. ZN Resident is still running with local capabilities and structured memory.",
            metrics={"model_invoked": False},
        )


class UnavailableModelWorkerFactory:
    def create(self, route: ModelRoute) -> UnavailableModelWorker:
        return UnavailableModelWorker()


class LegacyAIAgentWorker:
    """Adapter that demotes legacy AIAgent to a cognitive worker."""

    def __init__(self, agent: Any):
        self.agent = agent

    def run(self, goal: Goal, kernel_context: str) -> WorkerResult:
        try:
            try:
                result = self.agent.run_conversation(
                    user_message=goal.task,
                    system_message=kernel_context,
                    task_id=f"zn-{goal.goal_id}",
                )
            except Exception as exc:
                return WorkerResult(
                    success=False,
                    error=f"{type(exc).__name__}: {exc}",
                    metrics={"model_invoked": True},
                )

            if isinstance(result, str):
                return WorkerResult(
                    success=bool(result.strip()),
                    response=result,
                    metrics={"model_invoked": True},
                )
            if not isinstance(result, dict):
                return WorkerResult(
                    success=False,
                    error=f"unexpected AIAgent result type: {type(result).__name__}",
                    metrics={"model_invoked": True},
                )

            response = str(
                result.get("final_response")
                or result.get("response")
                or result.get("content")
                or ""
            )
            verification = result.get("verification_passed")
            if verification is None and isinstance(result.get("verification"), dict):
                status = str(result["verification"].get("status") or "").lower()
                if status:
                    verification = status in {"passed", "success", "ok"}

            metrics: dict[str, Any] = {"model_invoked": True}
            for key in ("usage", "cost", "latency_ms", "iterations", "quality"):
                if key in result:
                    metrics[key] = result[key]
            return WorkerResult(
                success=bool(response.strip()) and not bool(result.get("error")),
                response=response,
                verification_passed=verification if isinstance(verification, bool) else None,
                error=str(result.get("error")) if result.get("error") else None,
                metrics=metrics,
            )
        finally:
            try:
                session_messages = getattr(self.agent, "_session_messages", None)
                if isinstance(session_messages, list):
                    self.agent.shutdown_memory_provider(session_messages)
                else:
                    self.agent.shutdown_memory_provider()
            except Exception:
                pass
            try:
                self.agent.close()
            except Exception:
                pass


class LegacyAIAgentWorkerFactory:
    """Build a fresh legacy AIAgent for a route.

    An optional builder makes this adapter testable and lets existing CLI or
    gateway code inject its already-correct credential/runtime construction.
    """

    def __init__(
        self,
        *,
        agent_kwargs: dict[str, Any] | None = None,
        agent_builder: Callable[..., Any] | None = None,
    ):
        self.agent_kwargs = dict(agent_kwargs or {})
        self.agent_builder = agent_builder

    def create(self, route: ModelRoute) -> LegacyAIAgentWorker:
        builder = self.agent_builder
        if builder is None:
            from run_agent import AIAgent

            builder = AIAgent

        kwargs = dict(self.agent_kwargs)
        kwargs.update({"provider": route.provider, "model": route.model})
        for key in (
            "base_url",
            "api_key",
            "api_mode",
            "requested_provider",
            "credential_pool",
        ):
            if key in route.metadata and route.metadata[key] is not None:
                kwargs[key] = route.metadata[key]
        return LegacyAIAgentWorker(builder(**kwargs))
