from __future__ import annotations

from typing import Protocol

from .models import Goal, ModelRoute, WorkerResult


class Worker(Protocol):
    def run(self, goal: Goal, kernel_context: str) -> WorkerResult: ...


class WorkerFactory(Protocol):
    def create(self, route: ModelRoute) -> Worker: ...


class UnavailableModelWorker:
    """System-2 placeholder used when the resident has no configured model.

    The resident organism remains alive through System 1 when no external
    cognitive resource is configured. Reaching this worker means the current
    task genuinely needs cognition that is not installed.
    """

    def run(self, goal: Goal, kernel_context: str) -> WorkerResult:
        return WorkerResult(
            success=False,
            error=(
                "No System 2 model is configured. ZN Resident is still running "
                "with local capabilities and structured memory."
            ),
            metrics={"model_invoked": False},
        )


class UnavailableModelWorkerFactory:
    def create(self, route: ModelRoute) -> UnavailableModelWorker:
        return UnavailableModelWorker()
