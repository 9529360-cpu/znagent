from __future__ import annotations

"""ZN-owned native Gemini cognitive resource.

The mature reference implementation learned that Google's OpenAI-compatible
endpoint is a poor ownership boundary for Gemini-specific thinking and replay
semantics. ZN therefore keeps a native ``generateContent`` transport here and
normalizes only the bounded cognitive increment the resident asked for.
"""

import base64
import copy
import hashlib
import json
import logging
import os
import re
from typing import Any, Mapping
from urllib.parse import quote

from .cognitive_resource import CognitiveIncrement
from .models import ModelRoute
from .privacy_choke import redact_for_egress
from .proxy_env import build_httpx_client
from .session_log import SessionEventSink, new_request_id

_LOG = logging.getLogger(__name__)


def _emit_session_event(
    sink: SessionEventSink | None,
    kind: str,
    *,
    request_id: str,
    payload: dict[str, Any],
) -> None:
    # DSH-1: session logging must never break cognition.
    if sink is None:
        return
    try:
        sink.emit(kind, request_id=request_id, payload=payload)
    except Exception as exc:
        _LOG.warning("Session log emit failed (%s)", type(exc).__name__)


def _loggable_parts(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy request parts for the log, replacing image bytes with identity.

    DSH-1: the log proves *which* image the model saw (hash + mime + size)
    without duplicating screenshot bytes into the store.
    """
    logged: list[dict[str, Any]] = []
    for part in parts:
        if not isinstance(part, dict):
            logged.append(copy.deepcopy(part))
            continue
        inline = part.get("inlineData")
        if not isinstance(inline, dict) or "data" not in inline:
            logged.append(copy.deepcopy(part))
            continue
        try:
            raw = base64.b64decode(str(inline.get("data") or ""))
            digest = hashlib.sha256(raw).hexdigest()
            size = len(raw)
        except Exception:
            digest = ""
            size = 0
        replacement = {
            key: value for key, value in inline.items() if key != "data"
        }
        replacement["data"] = {"sha256": digest, "bytes": size, "logged": "by-hash"}
        logged.append({**copy.deepcopy(part), "inlineData": replacement})
    return logged


DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_DEFAULT_MAX_OUTPUT_TOKENS = 65_535
GEMINI_MAX_INLINE_IMAGE_BYTES = 12 * 1024 * 1024
GEMINI_MAX_RESPONSE_SCHEMA_CHARS = 16_384
_SUPPORTED_INLINE_IMAGE_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/jpg", "image/webp"})

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
        session_sink: SessionEventSink | None = None,
    ):
        self.route = resolve_gemini_route(route)
        # Malformed proxy env must never take cognition offline: fall back to
        # a direct connection instead of crashing at construction.
        self._client = client or build_httpx_client()
        self._owns_client = client is None
        self._session_sink = session_sink

    def close(self) -> None:
        if self._owns_client:
            close = getattr(self._client, "close", None)
            if callable(close):
                close()

    def invoke(
        self,
        *,
        question: str,
        context: str,
        request_id: str | None = None,
    ) -> CognitiveIncrement:
        text = str(question or "").strip()
        if not text:
            raise ValueError("bounded cognition question must not be empty")
        return self._invoke_parts(
            parts=[{"text": text}],
            context=context,
            generation=self._generation_config(),
            request_id=request_id,
        )

    def invoke_image(
        self,
        *,
        question: str,
        context: str,
        image_bytes: bytes | bytearray | memoryview,
        mime_type: str = "image/png",
        response_schema: Mapping[str, Any] | None = None,
        request_id: str | None = None,
    ) -> CognitiveIncrement:
        """Ask one bounded visual question about one inline image.

        This is a cognitive resource call only. It never owns screen capture,
        pointer authority, task state, or any action loop.
        """

        text = str(question or "").strip()
        if not text:
            raise ValueError("bounded visual cognition question must not be empty")
        if not isinstance(image_bytes, (bytes, bytearray, memoryview)):
            raise ValueError("inline image must be bytes-like")
        image = bytes(image_bytes)
        if not image:
            raise ValueError("inline image must not be empty")
        if len(image) > GEMINI_MAX_INLINE_IMAGE_BYTES:
            raise ValueError(
                f"inline image exceeds {GEMINI_MAX_INLINE_IMAGE_BYTES} bytes"
            )

        normalized_mime = str(mime_type or "").strip().lower()
        if normalized_mime not in _SUPPORTED_INLINE_IMAGE_MIME_TYPES:
            raise ValueError(
                "inline image mime_type must be image/png, image/jpeg, image/jpg, or image/webp"
            )

        increment = self._invoke_parts(
            parts=[
                {
                    "inlineData": {
                        "mimeType": normalized_mime,
                        "data": base64.b64encode(image).decode("ascii"),
                    }
                },
                {"text": text},
            ],
            context=context,
            generation=self._generation_config(response_schema=response_schema),
            request_id=request_id,
        )
        increment.metadata.update(
            {
                "input_media_mime_type": normalized_mime,
                "input_media_bytes": len(image),
                "structured_output": response_schema is not None,
            }
        )
        return increment

    def _generation_config(
        self,
        *,
        response_schema: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
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

        if response_schema is not None:
            if not isinstance(response_schema, Mapping) or not response_schema:
                raise ValueError("response_schema must be a non-empty mapping")
            schema = dict(response_schema)
            try:
                encoded = json.dumps(
                    schema,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("response_schema must be JSON serializable") from exc
            if len(encoded) > GEMINI_MAX_RESPONSE_SCHEMA_CHARS:
                raise ValueError(
                    f"response_schema exceeds {GEMINI_MAX_RESPONSE_SCHEMA_CHARS} characters"
                )
            generation["responseMimeType"] = "application/json"
            generation["responseJsonSchema"] = schema
        return generation

    def _invoke_parts(
        self,
        *,
        parts: list[dict[str, Any]],
        context: str,
        generation: Mapping[str, Any],
        request_id: str | None = None,
    ) -> CognitiveIncrement:
        if not parts:
            raise ValueError("Gemini request parts must not be empty")

        # W-2 egress redaction (single point for invoke + invoke_image):
        # only ``text`` leaves are scrubbed. ``inlineData`` (base64 image
        # bytes) is deliberately left untouched -- scrubbing it could
        # corrupt the payload if encoded bytes happen to spell a
        # credential-shaped pattern, and image bytes are not user text.
        scrubbed_parts = [
            {**part, "text": redact_for_egress(part["text"])}
            if isinstance(part, dict) and isinstance(part.get("text"), str)
            else part
            for part in parts
        ]
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": scrubbed_parts}],
            "generationConfig": dict(generation),
        }
        bounded_context = redact_for_egress(str(context or "").strip())
        if bounded_context:
            payload["systemInstruction"] = {"parts": [{"text": bounded_context}]}

        rid = str(request_id or "").strip() or new_request_id()

        def _fail(error_type: str) -> None:
            _emit_session_event(
                self._session_sink,
                "model_request_failed",
                request_id=rid,
                payload={"error_type": error_type},
            )

        # DSH-1: log the exact post-redaction request BEFORE sending. The
        # logged copy replaces image bytes with their identity (hash +
        # mime + size) and never includes the api key, which travels as a
        # URL param, not in this body.
        has_image = any(
            isinstance(part, dict) and isinstance(part.get("inlineData"), dict)
            for part in scrubbed_parts
        )
        log_payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": _loggable_parts(scrubbed_parts)}],
            "generationConfig": dict(generation),
        }
        if bounded_context:
            log_payload["systemInstruction"] = {"parts": [{"text": bounded_context}]}
        _emit_session_event(
            self._session_sink,
            "model_request_sent",
            request_id=rid,
            payload={
                "provider": "gemini",
                "model": self.route.model,
                "api_mode": "gemini_native",
                "has_image": has_image,
                "request": log_payload,
            },
        )

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
            _fail(type(exc).__name__)
            raise GeminiResourceError(f"Gemini request failed: {exc}") from exc

        status = int(getattr(response, "status_code", 0) or 0)
        try:
            data = response.json()
        except Exception as exc:
            _fail("GeminiResourceError")
            raise GeminiResourceError(
                f"Gemini returned invalid JSON (HTTP {status})",
                status_code=status,
            ) from exc
        if not isinstance(data, dict):
            _fail("GeminiResourceError")
            raise GeminiResourceError("Gemini returned an invalid response", status_code=status)
        if status < 200 or status >= 300:
            error = data.get("error") or {}
            if isinstance(error, dict):
                message = str(error.get("message") or f"HTTP {status}")
            else:
                message = str(error or f"HTTP {status}")
            _fail("GeminiResourceError")
            raise GeminiResourceError(
                f"Gemini request failed: {message[:1500]}",
                status_code=status,
            )

        candidates = data.get("candidates") or []
        if not isinstance(candidates, list) or not candidates:
            prompt_feedback = data.get("promptFeedback")
            _fail("GeminiResourceError")
            raise GeminiResourceError(
                f"Gemini returned no candidates: {prompt_feedback!r}"
            )
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            _fail("GeminiResourceError")
            raise GeminiResourceError("Gemini returned an invalid candidate")
        content = candidate.get("content") or {}
        candidate_parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(candidate_parts, list):
            candidate_parts = []

        text_parts: list[str] = []
        thought_parts: list[str] = []
        thought_signatures: list[str] = []
        for part in candidate_parts:
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
        finish_reason = _FINISH_REASON_MAP.get(
            finish_raw,
            finish_raw.lower() or "stop",
        )
        result_text = "\n".join(text_parts).strip()
        if not result_text and finish_raw not in {
            "SAFETY",
            "RECITATION",
            "BLOCKLIST",
            "PROHIBITED_CONTENT",
            "SPII",
        }:
            _fail("GeminiResourceError")
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

        increment = CognitiveIncrement(
            text=result_text,
            provider="gemini",
            model=self.route.model,
            finish_reason=finish_reason,
            usage=_usage_dict(data.get("usageMetadata")),
            metadata=metadata,
        )
        # DSH-1: log the returned text (never reasoning/thought content).
        _emit_session_event(
            self._session_sink,
            "model_response",
            request_id=rid,
            payload={
                "text": increment.text,
                "finish_reason": increment.finish_reason,
                "usage": dict(increment.usage or {}),
            },
        )
        return increment
