from __future__ import annotations

"""Recovery-scoped classification for bounded cognitive provider failures.

ZN keeps only the provider recovery mechanism that belongs at its existing
CognitiveResource/Resident-health boundary: distinguish route-health failures
from request-scoped rejections. This module does not own routing, retries,
provider selection, Work, or cognition policy.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CognitiveFailureDisposition:
    """One privacy-safe recovery classification for a provider exception."""

    failure_class: str
    affects_route_health: bool


_CONTENT_POLICY_PATTERNS = (
    "content policy",
    "content_policy",
    "content filter",
    "content_filter",
    "safety filter",
    "safety policy",
    "moderation blocked",
    "blocked by policy",
)
_CONTEXT_PATTERNS = (
    "context length",
    "context window",
    "maximum context",
    "context_length_exceeded",
    "prompt is too long",
    "prompt too long",
    "too many tokens",
    "maximum input tokens",
    "max input token",
    "maximum allowed input length",
)
_PAYLOAD_PATTERNS = (
    "payload too large",
    "request entity too large",
    "request_too_large",
)
_BILLING_PATTERNS = (
    "insufficient_quota",
    "insufficient credits",
    "insufficient balance",
    "payment required",
    "billing hard limit",
    "spend limit",
    "credit balance",
)
_RATE_LIMIT_PATTERNS = (
    "rate limit",
    "rate_limit",
    "too many requests",
    "resource exhausted",
    "resource_exhausted",
    "throttling",
    "throttled",
)
_OVERLOADED_PATTERNS = (
    "overloaded",
    "over capacity",
    "at capacity",
    "temporarily unavailable",
    "server busy",
)
_MODEL_PATTERNS = (
    "model not found",
    "model_not_found",
    "invalid model",
    "unknown model",
    "unsupported model",
    "no such model",
)
_REQUEST_PATTERNS = (
    "invalid request",
    "invalid_request",
    "bad request",
    "unknown parameter",
    "unsupported parameter",
    "validation error",
    "unprocessable entity",
)


def classify_cognitive_failure(
    error: BaseException,
) -> CognitiveFailureDisposition | None:
    """Classify provider evidence without replacing generic resident health.

    ``None`` means the exception carries no provider-specific evidence and the
    existing ``ResidentHealthJournal`` classification should remain authoritative.

    Request-scoped failures intentionally return ``affects_route_health=False``:
    a context overflow, content-policy rejection, or malformed request says that
    this invocation is unusable, not that the configured provider route is down.
    """

    status = _status_code(error)

    # Native transport exceptions without structured provider status are stronger
    # evidence than message text. In particular, phrases such as "temporarily
    # unavailable" must not turn a socket/connection failure into a provider
    # overload claim. If an SDK does expose an HTTP status, the structured status
    # below remains authoritative instead.
    if status is None and isinstance(error, (TimeoutError, ConnectionError)):
        return CognitiveFailureDisposition("network_or_service", True)

    code = _error_code(error)
    text = _error_text(error)
    searchable = " ".join(part for part in (code, text) if part).lower()

    # Policy/content rejection must win over the common HTTP 403 auth status.
    if _contains(searchable, _CONTENT_POLICY_PATTERNS):
        return CognitiveFailureDisposition("request_or_content_policy", False)

    # Context/payload pressure belongs to request shaping, not route health.
    if status == 413 or _contains(searchable, (*_CONTEXT_PATTERNS, *_PAYLOAD_PATTERNS)):
        return CognitiveFailureDisposition("request_context_or_payload", False)

    # Billing/quota codes can arrive as 403 from some providers, so classify
    # them before the generic authentication branch.
    if status == 402 or _contains(searchable, _BILLING_PATTERNS):
        return CognitiveFailureDisposition("billing_or_quota", True)

    if status == 429:
        if _contains(searchable, _OVERLOADED_PATTERNS):
            return CognitiveFailureDisposition("provider_overloaded", True)
        return CognitiveFailureDisposition("rate_limit", True)
    if _contains(searchable, _RATE_LIMIT_PATTERNS):
        return CognitiveFailureDisposition("rate_limit", True)

    if status in {503, 529} or _contains(searchable, _OVERLOADED_PATTERNS):
        return CognitiveFailureDisposition("provider_overloaded", True)
    if status in {500, 502, 504}:
        return CognitiveFailureDisposition("network_or_service", True)

    if status in {401, 403}:
        return CognitiveFailureDisposition("authentication_or_authorization", True)

    if status == 404 and _contains(searchable, _MODEL_PATTERNS):
        return CognitiveFailureDisposition("configuration_or_route", True)

    # Deterministic provider request rejection should not trip a route circuit.
    if status in {400, 409, 422} or _contains(searchable, _REQUEST_PATTERNS):
        return CognitiveFailureDisposition("request_or_input", False)

    return None


def _contains(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


def _status_code(error: BaseException) -> int | None:
    candidates: list[Any] = [
        getattr(error, "status_code", None),
        getattr(error, "status", None),
    ]
    response = getattr(error, "response", None)
    if response is not None:
        candidates.extend(
            (
                getattr(response, "status_code", None),
                getattr(response, "status", None),
            )
        )
    for raw in candidates:
        try:
            if raw is None:
                continue
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if 100 <= value <= 599:
            return value
    return None


def _error_code(error: BaseException) -> str:
    candidates: list[Any] = [
        getattr(error, "code", None),
        getattr(error, "error_code", None),
        getattr(error, "type", None),
    ]
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        candidates.extend((body.get("code"), body.get("type")))
        nested = body.get("error")
        if isinstance(nested, dict):
            candidates.extend((nested.get("code"), nested.get("type")))
    for raw in candidates:
        value = str(raw or "").strip()
        if value:
            return value[:160]
    return ""


def _error_text(error: BaseException) -> str:
    parts = [str(error or "")]
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        for key in ("message", "detail", "error_description"):
            value = body.get(key)
            if isinstance(value, str):
                parts.append(value)
        nested = body.get("error")
        if isinstance(nested, dict):
            for key in ("message", "detail"):
                value = nested.get(key)
                if isinstance(value, str):
                    parts.append(value)
    return " ".join(part.strip() for part in parts if part and part.strip())[:4000]
