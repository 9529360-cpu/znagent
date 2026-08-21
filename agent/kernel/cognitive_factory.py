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
    resolve_openai_compatible_route,
)
from .models import ModelRoute


def resolve_zn_cognitive_route(route: ModelRoute) -> ModelRoute:
    provider = str(route.provider or "auto").strip().lower() or "auto"
    api_mode = str(route.metadata.get("api_mode") or "").strip().lower()
    if provider == "anthropic" or api_mode == "anthropic_messages":
        return resolve_anthropic_route(route)
    return resolve_openai_compatible_route(route)


class ZNCognitiveResourceWorkerFactory(CognitiveResourceWorkerFactory):
    """Dispatch ZN routes to native protocol resources, never a legacy agent."""

    def __init__(
        self,
        *,
        openai_client_builder: Any | None = None,
        anthropic_client_builder: Any | None = None,
    ):
        # Keep inheritance for compatibility with callers/tests that check the
        # old factory seam while moving actual resource ownership into ZN.
        super().__init__()
        self.openai_client_builder = openai_client_builder
        self.anthropic_client_builder = anthropic_client_builder

    def create(self, route: ModelRoute) -> CognitiveResourceWorker:
        api_mode = str(route.metadata.get("api_mode") or "chat_completions").lower()
        if route.provider == "anthropic" or api_mode == "anthropic_messages":
            resource = AnthropicCognitiveResource(
                route,
                client_builder=self.anthropic_client_builder,
            )
        else:
            resource = OpenAICompatibleCognitiveResource(
                route,
                client_builder=self.openai_client_builder,
            )
        return CognitiveResourceWorker(resource)
