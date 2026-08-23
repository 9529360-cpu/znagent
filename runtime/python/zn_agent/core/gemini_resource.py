from __future__ import annotations

"""ZN-owned native Gemini cognitive resource.

The mature reference implementation learned that Google's OpenAI-compatible
endpoint is a poor ownership boundary for Gemini-specific thinking and replay
semantics. ZN therefore keeps a native ``generateContent`` transport here and
normalizes only the bounded cognitive increment the resident asked for.
"""

import os
import re
from typing import Any, Mapping
from urllib.parse import quote

import httpx

from .cognitive_resource import CognitiveIncrement
from .models import ModelRoute


DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_DEFAULT_MAX_OUTPUT_TOKENS = 65_535

_FINISH_REASON_MAP = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
    "BLOCKLIST": "content_filter",
    "PROHIBITED_CONTENT": "content_filter",
    "SPII": "content_filter",
    "MALFORMED_FUNCTION_CALL": "tool_error",
    "UNEXPECTED_TOOL_CALL": "tool_error",
}


def bare_gemini_model_id(model: str) -> str:
    name = str(model or "").strip()
    lowered = name.lower()
    for prefix in ("google/", "gemini/"):
        if lowered.startswith(prefix):
            return name[len(prefix) :].strip() or name
    return name


def gemini_major_version(model: str) -> int | None:
    match = re.match(r"gemini-(\d+)", bare_gemini_model_id(model).lower())
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def resolve_gemini_route(
    route: ModelRoute,
    *,
    environ: Mapping[str, str] | None = None,
) -> ModelRoute:
    env = environ if environ is not None else os.environ
    metadata = dict(route.metadata or {})
    provider = str(route.provider or "gemini").strip().lower() or "gemini"
    api_mode = str(metadata.get("api_mode") or "gemini_native").strip().lower()
    if provider not in {"gemini", "google"} and api_mode != "gemini_native":
        raise ValueError(f"route {route.route_id} is not a native Gemini route")

    api_key = str(
        metadata.get("api_key")
        or env.get("GEMINI_API_KEY")
        or env.get("GOOGLE_API_KEY")
        or ""
    ).strip()
    if not api_key:
        raise ValueError(
            f"route {route.route_id} has no Gemini credential; configure GEMINI_API_KEY or GOOGLE_API_KEY"
        )

    base_url = str(metadata.get("base_url") or DEFAULT_GEMINI_BASE_URL).strip().rstrip("/")
    if base_url.lower().endswith("/openai"):
        base_url = base_url[: -len("/openai")]

    resolved = ModelRoute(
        route_id=route.route_id,
        provider="gemini",
        model=bare_gemini_model_id(route.model),
        capabilities=dict(route.capabilities),
        reliability=route.reliability,
        cost_weight=route.cost_weight,
        latency_weight=route.latency_weight,
        metadata=metadata,
    )
    resolved.metadata.update(
        {
            "api_key": api_key,
            "base_url": base_url,
            "api_mode": "gemini_native",
        }
    )
    return resolved


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _usage_dict(payload: Any) -> dict[str, int]:
    if not isinstance(payload, dict):
        return {}
    prompt = _as_int(payload.get("promptTokenCount"))
    candidates = _as_int(payload.get("candidatesTokenCount"))
    thoughts = _as_int(payload.get("thoughtsTokenCount"))
    total = _as_int(payload.get("totalTokenCount")) or prompt + candidates + thoughts
    result = {
        "prompt_tokens": prompt,
        "completion_tokens": candidates,
        "total_tokens": total,
    }
    cached = _as_int(payload.get("cachedContentTokenCount"))
    if cached:
        result["cached_tokens"] = cached
    if thoughts:
        result["reasoning_tokens"] = thoughts
    return result


class GeminiResourceError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class GeminiCognitiveResource:
    """One bounded native Gemini ``generateContent`` request."""

    def __init__(
        self,
        route: ModelRoute,
        *,
        client: Any | None = None,
    ):
        self.route = resolve_gemini_route(route)
        self._client = client or httpx.Client()
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            close = getattr(self._client, "close", None)
            if callable(close):
                close()

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        text = str(question or "").strip()
        if not text:
            raise ValueError("bounded cognition question must not be empty")

        generation: dict[str, Any] = {
            "maxOutputTokens": max(
                1,
                int(
                    self.route.metadata.get("max_tokens")
                    or GEMINI_DEFAULT_MAX_OUTPUT_TOKENS
                ),
            )
        }
        if self.route.metadata.get("temperature") is not None:
            generation["temperature"] = float(self.route.metadata["temperature"])
        if self.route.metadata.get("top_p") is not None:
            generation["topP"] = float(self.route.metadata["top_p"])
        thinking = self.route.metadata.get("thinking")
        if isinstance(thinking, dict) and thinking:
            generation["thinkingConfig"] = dict(thinking)

        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": generation,
        }
        bounded_context = str(context or "").strip()
        if bounded_context:
            payload["systemInstruction"] = {"parts": [{"text": bounded_context}]}

        model = quote(self.route.model, safe="-._")
        url = f"{self.route.metadata['base_url']}/models/{model}:generateContent"
        timeout = float(self.route.metadata.get("timeout") or 120.0)
        try:
            response = self._client.post(
                url,
                params={"key": self.route.metadata["api_key"]},
                json=payload,
                timeout=timeout,
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Client": "zn-agent/0.1",
                },
            )
        except Exception as exc:
            raise GeminiResourceError(f"Gemini request failed: {exc}") from exc

        status = int(getattr(response, "status_code", 0) or 0)
        try:
            data = response.json()
        except Exception as exc:
            raise GeminiResourceError(
                f"Gemini returned invalid JSON (HTTP {status})",
                status_code=status,
            ) from exc
        if not isinstance(data, dict):
            raise GeminiResourceError("Gemini returned an invalid response", status_code=status)
        if status < 200 or status >= 300:
            error = data.get("error") or {}
            if isinstance(error, dict):
                message = str(error.get("message") or f"HTTP {status}")
            else:
                message = str(error or f"HTTP {status}")
            raise GeminiResourceError(
                f"Gemini request failed: {message[:1500]}",
                status_code=status,
            )

        candidates = data.get("candidates") or []
        if not isinstance(candidates, list) or not candidates:
            prompt_feedback = data.get("promptFeedback")
            raise GeminiResourceError(
                f"Gemini returned no candidates: {prompt_feedback!r}"
            )
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise GeminiResourceError("Gemini returned an invalid candidate")
        content = candidate.get("content") or {}
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            parts = []

        text_parts: list[str] = []
        thought_parts: list[str] = []
        thought_signatures: list[str] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            part_text = part.get("text")
            if isinstance(part.get("thoughtSignature"), str):
                thought_signatures.append(part["thoughtSignature"])
            if not isinstance(part_text, str) or not part_text:
                continue
            if part.get("thought") is True:
                thought_parts.append(part_text)
            else:
                text_parts.append(part_text)

        finish_raw = str(candidate.get("finishReason") or "")
        finish_reason = _FINISH_REASON_MAP.get(finish_raw, finish_raw.lower() or "stop")
        result_text = "\n".join(text_parts).strip()
        if not result_text and finish_raw not in {
            "SAFETY",
            "RECITATION",
            "BLOCKLIST",
            "PROHIBITED_CONTENT",
            "SPII",
        }:
            raise GeminiResourceError("Gemini returned no usable text content")

        metadata: dict[str, Any] = {
            "api_mode": "gemini_native",
            "finish_reason_raw": finish_raw,
            "gemini_major_version": gemini_major_version(self.route.model),
        }
        if thought_parts:
            metadata["reasoning"] = "\n\n".join(thought_parts)
        if thought_signatures:
            metadata["thought_signatures"] = thought_signatures
        safety = candidate.get("safetyRatings")
        if isinstance(safety, list):
            metadata["safety_ratings"] = safety

        return CognitiveIncrement(
            text=result_text,
            provider="gemini",
            model=self.route.model,
            finish_reason=finish_reason,
            usage=_usage_dict(data.get("usageMetadata")),
            metadata=metadata,
        )
