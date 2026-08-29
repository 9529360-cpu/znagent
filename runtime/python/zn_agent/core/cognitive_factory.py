from __future__ import annotations

"""ZN-owned cognitive resource selection.

Provider selection lives here so adding a native protocol does not turn the
resident into a provider-specific agent. Every route still produces the same
CognitiveResourceWorker boundary and returns a bounded cognitive increment.
"""

from typing import Any

from .anthropic_resource import AnthropicCognitiveResource, resolve_anthropic_route
from .cognitive_resource import (
    CognitiveResourceWorker,
    CognitiveResourceWorkerFactory,
    OpenAICompatibleCognitiveResource,
    ResourceHealthObserver,
    resolve_openai_compatible_route,
)
from .gemini_resource import GeminiCognitiveResource, resolve_gemini_route
from .models import ModelRoute


def resolve_zn_cognitive_route(route: ModelRoute) -> ModelRoute:
    provider = str(route.provider or "auto").strip().lower() or "auto"
    api_mode = str(route.metadata.get("api_mode") or "").strip().lower()
    if provider == "anthropic" or api_mode == "anthropic_messages":
        return resolve_anthropic_route(route)
    if provider in {"gemini", "google"} or api_mode == "gemini_native":
        return resolve_gemini_route(route)
    return resolve_openai_compatible_route(route)


class ZNCognitiveResourceWorkerFactory(CognitiveResourceWorkerFactory):
    """Dispatch ZN routes to native protocol resources, never a legacy agent."""

    def __init__(
        self,
        *,
        openai_client_builder: Any | None = None,
        anthropic_client_builder: Any | None = None,
        gemini_client: Any | None = None,
        health_observer: ResourceHealthObserver | None = None,
    ):
        # Keep inheritance for compatibility with callers/tests that check the
        # old factory seam while moving actual resource ownership into ZN.
        super().__init__(health_observer=health_observer)
        self.openai_client_builder = openai_client_builder
        self.anthropic_client_builder = anthropic_client_builder
        self.gemini_client = gemini_client

    def create(self, route: ModelRoute) -> CognitiveResourceWorker:
        """Construct one provider resource and observe construction failures.

        ``ZNKernelRuntime`` intentionally catches factory exceptions and turns
        them into a non-invoked WorkerResult. This is therefore the last point
        where the original configuration/client-construction exception exists.
        Record only failures here: successful construction is not provider
        recovery and must not clear a prior invocation failure before a real
        invocation succeeds.
        """
        try:
            api_mode = str(route.metadata.get("api_mode") or "chat_completions").lower()
            if route.provider == "anthropic" or api_mode == "anthropic_messages":
                resource = AnthropicCognitiveResource(
                    route,
                    client_builder=self.anthropic_client_builder,
                )
            elif route.provider == "gemini" or api_mode == "gemini_native":
                resource = GeminiCognitiveResource(
                    route,
                    client=self.gemini_client,
                )
            else:
                resource = OpenAICompatibleCognitiveResource(
                    route,
                    client_builder=self.openai_client_builder,
                )
        except Exception as exc:
            self._observe_factory_failure(route, exc)
            raise
        return CognitiveResourceWorker(
            resource,
            route=route,
            health_observer=self.health_observer,
        )

    def _observe_factory_failure(self, route: ModelRoute, error: BaseException) -> None:
        observer = self.health_observer
        if observer is None:
            return
        try:
            observer(route, error)
        except Exception:
            # Health is secondary to resource construction. Preserve the exact
            # provider/factory exception for the kernel's existing failure path.
            return
