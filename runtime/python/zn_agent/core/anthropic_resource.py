from __future__ import annotations

"""ZN-owned Anthropic Messages cognitive resource.

This is source-level extraction from the mature Anthropic transport/adapter.
ZN keeps the useful wire semantics -- native Messages API shape, content-block
normalization, stop reasons and cache-aware usage -- without importing the old
agent orchestration or constructing the legacy AIAgent.
"""

import os
from typing import Any, Callable, Mapping

from .cognitive_resource import CognitiveIncrement, _owned_cognitive_client
from .models import ModelRoute


ClientBuilder = Callable[..., Any]

_STOP_REASON_MAP = {
    "end_turn": "stop",
    "tool_use": "tool_calls",
    "max_tokens": "length",
    "stop_sequence": "stop",
    "refusal": "content_filter",
    "model_context_window_exceeded": "length",
}


def resolve_anthropic_route(
    route: ModelRoute,
    *,
    environ: Mapping[str, str] | None = None,
) -> ModelRoute:
    """Resolve one native Anthropic route using ZN-owned configuration rules."""
    env = environ if environ is not None else os.environ
    metadata = dict(route.metadata or {})
    provider = str(route.provider or "anthropic").strip().lower() or "anthropic"
    api_mode = str(metadata.get("api_mode") or "anthropic_messages").strip().lower()
    if provider != "anthropic" and api_mode != "anthropic_messages":
        raise ValueError(f"route {route.route_id} is not an Anthropic Messages route")

    api_key = str(metadata.get("api_key") or env.get("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        raise ValueError(
            f"route {route.route_id} has no Anthropic credential; configure ANTHROPIC_API_KEY"
        )

    resolved = ModelRoute(
        route_id=route.route_id,
        provider="anthropic",
        model=route.model,
        capabilities=dict(route.capabilities),
        reliability=route.reliability,
        cost_weight=route.cost_weight,
        latency_weight=route.latency_weight,
        metadata=metadata,
    )
    resolved.metadata["api_key"] = api_key
    resolved.metadata["api_mode"] = "anthropic_messages"
    base_url = str(metadata.get("base_url") or "").strip()
    if base_url:
        resolved.metadata["base_url"] = base_url
    return resolved


def _usage_value(usage: Any, name: str) -> int:
    raw = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def _usage_dict(usage: Any) -> dict[str, int]:
    if usage is None:
        return {}
    input_tokens = _usage_value(usage, "input_tokens")
    output_tokens = _usage_value(usage, "output_tokens")
    cache_read = _usage_value(usage, "cache_read_input_tokens")
    cache_creation = _usage_value(usage, "cache_creation_input_tokens")
    result = {
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
    if cache_read:
        result["cache_read_input_tokens"] = cache_read
    if cache_creation:
        result["cache_creation_input_tokens"] = cache_creation
    return result


def _block_value(block: Any, name: str, default: Any = None) -> Any:
    if isinstance(block, dict):
        return block.get(name, default)
    return getattr(block, name, default)


def _build_anthropic_client(route: ModelRoute, client_builder: "ClientBuilder | None"):
    builder = client_builder
    if builder is None:
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise RuntimeError(
                "Anthropic resource requires the optional 'anthropic' dependency"
            ) from exc
        builder = Anthropic

    kwargs: dict[str, Any] = {
        "api_key": route.metadata["api_key"],
        # A single durable Worker attempt must not hide SDK retries.
        "max_retries": 0,
    }
    if route.metadata.get("base_url"):
        kwargs["base_url"] = route.metadata["base_url"]
    if route.metadata.get("timeout") is not None:
        kwargs["timeout"] = route.metadata["timeout"]
    return builder(**kwargs)


class AnthropicCognitiveResource:
    """One bounded ZN cognition call over Anthropic's native Messages API."""

    def __init__(
        self,
        route: ModelRoute,
        *,
        client_builder: ClientBuilder | None = None,
    ):
        self.route = resolve_anthropic_route(route)
        self._client_builder = client_builder

    def _client(self):
        return _build_anthropic_client(self.route, self._client_builder)

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        text = str(question or "").strip()
        if not text:
            raise ValueError("bounded cognition question must not be empty")

        request: dict[str, Any] = {
            "model": self.route.model,
            "max_tokens": max(1, int(self.route.metadata.get("max_tokens") or 16_384)),
            "messages": [{"role": "user", "content": text}],
        }
        bounded_context = str(context or "").strip()
        if bounded_context:
            request["system"] = bounded_context
        if self.route.metadata.get("temperature") is not None:
            request["temperature"] = float(self.route.metadata["temperature"])
        if self.route.metadata.get("top_p") is not None:
            request["top_p"] = float(self.route.metadata["top_p"])

        # Preserve a small native-thinking seam instead of routing Anthropic
        # through an OpenAI-compatible approximation. The exact thinking policy
        # remains ZN configuration; signed replay/tool-loop behavior is extracted
        # only when ZN adds native external tool turns.
        thinking = self.route.metadata.get("thinking")
        if isinstance(thinking, dict) and thinking:
            request["thinking"] = dict(thinking)

        with _owned_cognitive_client(self._client()) as client:
            response = client.messages.create(**request)
        blocks = getattr(response, "content", None)
        if not isinstance(blocks, list):
            raise RuntimeError("Anthropic resource returned invalid content blocks")

        text_parts: list[str] = []
        thinking_parts: list[str] = []
        block_types: list[str] = []
        for block in blocks:
            block_type = str(_block_value(block, "type", "") or "")
            if block_type:
                block_types.append(block_type)
            if block_type == "text":
                value = _block_value(block, "text", "")
                if isinstance(value, str) and value:
                    text_parts.append(value)
            elif block_type == "thinking":
                value = _block_value(block, "thinking", "")
                if isinstance(value, str) and value:
                    thinking_parts.append(value)

        stop_reason = str(getattr(response, "stop_reason", "") or "") or None
        finish_reason = _STOP_REASON_MAP.get(stop_reason or "", "stop")
        result_text = "\n".join(text_parts).strip()

        # Mature Anthropic behavior treats empty end_turn/refusal responses as
        # terminal protocol responses rather than transport corruption. The ZN
        # critic can still decide an empty increment is unusable; the resource
        # itself must not misclassify it as malformed and retry forever.
        if not result_text and blocks and stop_reason not in {"end_turn", "refusal"}:
            raise RuntimeError("Anthropic resource returned no text content")
        if not blocks and stop_reason not in {"end_turn", "refusal"}:
            raise RuntimeError("Anthropic resource returned empty content")

        metadata: dict[str, Any] = {
            "api_mode": "anthropic_messages",
            "stop_reason": stop_reason,
            "finish_reason": finish_reason,
            "content_block_types": block_types,
        }
        if thinking_parts:
            metadata["reasoning"] = "\n\n".join(thinking_parts)
        if stop_reason == "refusal":
            metadata["refused"] = True

        return CognitiveIncrement(
            text=result_text,
            provider="anthropic",
            model=self.route.model,
            finish_reason=finish_reason,
            usage=_usage_dict(getattr(response, "usage", None)),
            metadata=metadata,
        )


class AnthropicToolLoopClient:
    """Adapts native Anthropic tool-calling to AgenticToolLoop's protocol.

    Unlike AnthropicCognitiveResource.invoke (one bounded question -> one
    text answer, no tools), this speaks the real multi-turn Messages API
    with a ``tools`` schema so the model can call tools and see their
    results across turns, and decides for itself -- via stop_reason -- when
    it is done. See agentic_tool_loop.AgenticToolLoop for the loop that
    drives this client turn by turn.
    """

    def __init__(
        self,
        route: ModelRoute,
        *,
        client_builder: ClientBuilder | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.route = resolve_anthropic_route(route)
        self._client_builder = client_builder
        self._max_tokens = max_tokens

    def _client(self):
        return _build_anthropic_client(self.route, self._client_builder)

    def create_turn(
        self,
        *,
        messages: list[Mapping[str, Any]],
        system: str,
        tools: tuple[Mapping[str, Any], ...],
    ) -> dict[str, Any]:
        anthropic_tools = [
            {
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["input_schema"],
            }
            for tool in tools
        ]
        request: dict[str, Any] = {
            "model": self.route.model,
            "max_tokens": max(
                1,
                int(
                    self._max_tokens
                    or self.route.metadata.get("max_tokens")
                    or 8_192
                ),
            ),
            "messages": [dict(message) for message in messages],
        }
        if anthropic_tools:
            request["tools"] = anthropic_tools
        bounded_system = str(system or "").strip()
        if bounded_system:
            request["system"] = bounded_system
        if self.route.metadata.get("temperature") is not None:
            request["temperature"] = float(self.route.metadata["temperature"])

        with _owned_cognitive_client(self._client()) as client:
            response = client.messages.create(**request)

        blocks = getattr(response, "content", None)
        if not isinstance(blocks, list):
            raise RuntimeError("Anthropic resource returned invalid content blocks")

        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        raw_content: list[dict[str, Any]] = []
        for block in blocks:
            block_type = str(_block_value(block, "type", "") or "")
            if block_type == "text":
                value = _block_value(block, "text", "")
                if isinstance(value, str) and value:
                    text_parts.append(value)
                    raw_content.append({"type": "text", "text": value})
            elif block_type == "tool_use":
                call_id = str(_block_value(block, "id", "") or "")
                name = str(_block_value(block, "name", "") or "")
                raw_input = _block_value(block, "input", {})
                arguments = dict(raw_input) if isinstance(raw_input, dict) else {}
                tool_calls.append(
                    {"id": call_id, "name": name, "arguments": arguments}
                )
                raw_content.append(
                    {
                        "type": "tool_use",
                        "id": call_id,
                        "name": name,
                        "input": arguments,
                    }
                )
            elif block_type == "thinking":
                value = _block_value(block, "thinking", "")
                if isinstance(value, str) and value:
                    raw_content.append({"type": "thinking", "thinking": value})

        stop_reason = str(getattr(response, "stop_reason", "") or "") or None

        return {
            "text": "\n".join(text_parts).strip(),
            "tool_calls": tool_calls,
            "stop_reason": stop_reason,
            "raw_content": raw_content or (text_parts[0] if text_parts else ""),
            "usage": _usage_dict(getattr(response, "usage", None)),
        }
