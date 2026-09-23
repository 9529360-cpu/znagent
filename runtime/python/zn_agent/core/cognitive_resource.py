from __future__ import annotations

"""ZN-owned external cognitive resources.

This is the first source-level extraction from the mature provider stack.
The reference implementation under ``agent/transports/chat_completions.py``
contains years of OpenAI-compatible provider edge cases. ZN adopts the useful
wire-level pattern here without adopting the old AIAgent/conversation owner.

A resource answers one bounded cognition request. It does not own ZN's
identity, memory, tools, session, planning loop or final decision.
"""

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Mapping, Protocol
from urllib.parse import urlparse

from .models import Goal, ModelRoute, WorkerResult


@dataclass(slots=True)
class CognitiveIncrement:
    """One bounded result returned by an external cognitive resource."""

    text: str
    provider: str
    model: str
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class CognitiveResource(Protocol):
    def invoke(self, *, question: str, context: str) -> CognitiveIncrement: ...


ClientBuilder = Callable[..., Any]
ResourceBuilder = Callable[[ModelRoute], CognitiveResource]
ResourceHealthObserver = Callable[[ModelRoute, BaseException | None], None]


_LOG = logging.getLogger(__name__)


@contextmanager
def _owned_cognitive_client(client: Any) -> Iterator[Any]:
    """Close the per-invocation SDK client without changing provider outcome.

    The response is non-streaming and detached from its transport. Cleanup must
    also run for transport failure or cancellation, but an ordinary close error
    must not turn an already-returned answer into a retryable provider failure.
    Builder-supplied lightweight clients may omit close; actual SDK clients own
    their HTTP pool. Never log credential-bearing exception text from cleanup.
    """
    try:
        yield client
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception as exc:
                _LOG.warning("Cognitive client cleanup failed (%s)", type(exc).__name__)


# Defaults are intentionally only wire endpoints/credential names. Product
# selection/configuration belongs to ZN; these constants do not import the old
# CLI provider registry. More provider-specific transports are extracted into
# their own modules rather than making this table another agent framework.
_OPENAI_COMPAT_DEFAULTS: dict[str, tuple[str | None, str | None]] = {
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
    "xai": ("https://api.x.ai/v1", "XAI_API_KEY"),
    "ollama": ("http://127.0.0.1:11434/v1", None),
    "lmstudio": ("http://127.0.0.1:1234/v1", None),
    "vllm": ("http://127.0.0.1:8000/v1", None),
    "custom": (None, None),
}

_LOCAL_PROVIDERS = frozenset({"ollama", "lmstudio", "vllm"})


def _hostname(value: str | None) -> str:
    try:
        return (urlparse(str(value or "")).hostname or "").lower()
    except ValueError:
        return ""


def _is_loopback_url(value: str | None) -> bool:
    return _hostname(value) in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _infer_provider(base_url: str | None, environ: Mapping[str, str]) -> str:
    host = _hostname(base_url)
    if host == "openrouter.ai":
        return "openrouter"
    if host == "api.openai.com":
        return "openai"
    if host == "api.deepseek.com":
        return "deepseek"
    if host == "api.groq.com":
        return "groq"
    if host == "api.mistral.ai":
        return "mistral"
    if host == "api.x.ai":
        return "xai"
    if _is_loopback_url(base_url):
        return "custom"

    # Keep auto-resolution intentionally small and deterministic. This is
    # extracted provider plumbing, not a resurrection of the old CLI resolver.
    for provider, env_name in (
        ("openrouter", "OPENROUTER_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
        ("deepseek", "DEEPSEEK_API_KEY"),
        ("groq", "GROQ_API_KEY"),
        ("mistral", "MISTRAL_API_KEY"),
        ("xai", "XAI_API_KEY"),
    ):
        if str(environ.get(env_name) or "").strip():
            return provider
    return "custom"


def resolve_openai_compatible_route(
    route: ModelRoute,
    *,
    environ: Mapping[str, str] | None = None,
) -> ModelRoute:
    """Resolve one OpenAI-compatible route without retired product imports.

    Explicit ZN route metadata wins. Standard provider credential environment
    variables remain supported because they are provider conventions, not
    product identity. Local OpenAI-compatible servers do not require a secret.
    """

    env = environ if environ is not None else os.environ
    metadata = dict(route.metadata or {})
    api_mode = str(metadata.get("api_mode") or "chat_completions").strip().lower()
    if api_mode not in {"chat_completions", "openai_compat"}:
        raise ValueError(
            f"route {route.route_id} uses {api_mode!r}; a dedicated ZN transport is required"
        )

    provider = str(route.provider or "auto").strip().lower() or "auto"
    explicit_base = str(metadata.get("base_url") or "").strip() or None
    if provider == "auto":
        provider = _infer_provider(explicit_base, env)

    default_base, key_env = _OPENAI_COMPAT_DEFAULTS.get(provider, (None, None))
    base_url = explicit_base or default_base
    if not base_url:
        raise ValueError(
            f"route {route.route_id} provider {provider!r} requires an explicit base_url"
        )

    api_key = str(metadata.get("api_key") or "").strip()
    if not api_key and key_env:
        api_key = str(env.get(key_env) or "").strip()

    local_no_auth = provider in _LOCAL_PROVIDERS or _is_loopback_url(base_url)
    if not api_key and not local_no_auth:
        expected = key_env or "an explicit api_key"
        raise ValueError(
            f"route {route.route_id} has no credential for {provider}; configure {expected}"
        )

    resolved = ModelRoute(
        route_id=route.route_id,
        provider=provider,
        model=route.model,
        capabilities=dict(route.capabilities),
        reliability=route.reliability,
        cost_weight=route.cost_weight,
        latency_weight=route.latency_weight,
        metadata=metadata,
    )
    resolved.metadata.update(
        {
            "base_url": base_url,
            "api_key": api_key or "zn-local-noauth",
            "api_mode": "chat_completions",
        }
    )
    return resolved


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
            else:
                text = getattr(item, "text", None) or getattr(item, "content", None)
            if isinstance(text, str) and text:
                parts.append(text)
        return "\n".join(parts)
    return str(content or "")


def _usage_dict(usage: Any) -> dict[str, int]:
    if usage is None:
        return {}
    values: dict[str, int] = {}
    for source, target in (
        ("prompt_tokens", "prompt_tokens"),
        ("completion_tokens", "completion_tokens"),
        ("total_tokens", "total_tokens"),
        ("input_tokens", "prompt_tokens"),
        ("output_tokens", "completion_tokens"),
    ):
        raw = usage.get(source) if isinstance(usage, dict) else getattr(usage, source, None)
        if raw is None:
            continue
        try:
            values[target] = int(raw)
        except (TypeError, ValueError):
            continue
    return values


class OpenAICompatibleCognitiveResource:
    """Bounded text cognition over the mature OpenAI-compatible wire shape.

    The old provider transport supported full agent tool loops. ZN deliberately
    extracts only the transport mechanism needed here: a system context plus one
    bounded question, provider-specific endpoint/credential resolution, response
    normalization and usage accounting. Tool/body execution remains resident-
    owned and is never delegated by constructing an old AIAgent.
    """

    def __init__(
        self,
        route: ModelRoute,
        *,
        client_builder: ClientBuilder | None = None,
    ):
        self.route = resolve_openai_compatible_route(route)
        self._client_builder = client_builder

    def _client(self):
        builder = self._client_builder
        if builder is None:
            from openai import OpenAI

            builder = OpenAI
        kwargs: dict[str, Any] = {
            "api_key": self.route.metadata["api_key"],
            "base_url": self.route.metadata["base_url"],
            # Kernel owns explicit attempts and their durable accounting.
            "max_retries": 0,
        }
        timeout = self.route.metadata.get("timeout")
        if timeout is not None:
            kwargs["timeout"] = timeout
        return builder(**kwargs)

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        text = str(question or "").strip()
        if not text:
            raise ValueError("bounded cognition question must not be empty")

        messages: list[dict[str, str]] = []
        bounded_context = str(context or "").strip()
        if bounded_context:
            messages.append({"role": "system", "content": bounded_context})
        messages.append({"role": "user", "content": text})

        request: dict[str, Any] = {
            "model": self.route.model,
            "messages": messages,
        }
        for key in ("temperature", "max_tokens", "top_p", "seed"):
            if self.route.metadata.get(key) is not None:
                request[key] = self.route.metadata[key]
        if isinstance(self.route.metadata.get("extra_body"), dict):
            request["extra_body"] = dict(self.route.metadata["extra_body"])

        with _owned_cognitive_client(self._client()) as client:
            response = client.chat.completions.create(**request)
        choices = getattr(response, "choices", None) or []
        if not choices:
            raise RuntimeError("cognitive resource returned no choices")
        choice = choices[0]
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None) if message is not None else None
        result_text = _content_text(content).strip()
        if not result_text:
            raise RuntimeError("cognitive resource returned an empty response")

        return CognitiveIncrement(
            text=result_text,
            provider=self.route.provider,
            model=self.route.model,
            finish_reason=str(getattr(choice, "finish_reason", "") or "") or None,
            usage=_usage_dict(getattr(response, "usage", None)),
            metadata={"api_mode": "chat_completions"},
        )


class CognitiveResourceWorker:
    """Adapter from the kernel Worker seam to one bounded ZN resource.

    Resource exceptions are observed here while the real exception object still
    exists. The observer is strictly secondary: it cannot replace the worker's
    existing success/failure result or make an external provider own resident
    health semantics.
    """

    def __init__(
        self,
        resource: CognitiveResource,
        *,
        route: ModelRoute | None = None,
        health_observer: ResourceHealthObserver | None = None,
    ):
        self.resource = resource
        self.route = route
        self.health_observer = health_observer

    def run(self, goal: Goal, kernel_context: str) -> WorkerResult:
        try:
            increment = self.resource.invoke(question=goal.task, context=kernel_context)
        except Exception as exc:
            self._observe(exc)
            return WorkerResult(
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                metrics={"model_invoked": True, "resource_owner": "zn"},
            )

        self._observe(None)
        metrics: dict[str, Any] = {
            "model_invoked": True,
            "resource_owner": "zn",
            "provider": increment.provider,
            "model": increment.model,
        }
        metrics.update(increment.usage)
        if increment.finish_reason:
            metrics["finish_reason"] = increment.finish_reason
        if increment.finish_reason == "length":
            # The transport returned successfully, but its answer is incomplete.
            # Keep usage accounting without promoting partial prose or JSON into
            # an answer/action proposal. Kernel owns any later explicit attempt;
            # this boundary never extends the budget or continues the request.
            metrics["response_truncated"] = True
            return WorkerResult(
                success=False,
                error="cognitive response was truncated at the provider token/context limit",
                metrics=metrics,
            )
        return WorkerResult(success=True, response=increment.text, metrics=metrics)

    def _observe(self, error: BaseException | None) -> None:
        observer = self.health_observer
        route = self.route
        if observer is None or route is None:
            return
        try:
            observer(route, error)
        except Exception:
            # Health observation must never replace provider behavior or worker
            # result semantics. The provider invocation remains authoritative.
            return


class CognitiveResourceWorkerFactory:
    def __init__(
        self,
        resource_builder: ResourceBuilder | None = None,
        *,
        health_observer: ResourceHealthObserver | None = None,
    ):
        self.resource_builder = resource_builder or OpenAICompatibleCognitiveResource
        self.health_observer = health_observer

    def set_health_observer(self, observer: ResourceHealthObserver | None) -> None:
        self.health_observer = observer

    def create(self, route: ModelRoute) -> CognitiveResourceWorker:
        return CognitiveResourceWorker(
            self.resource_builder(route),
            route=route,
            health_observer=self.health_observer,
        )
