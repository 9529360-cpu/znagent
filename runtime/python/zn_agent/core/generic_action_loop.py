from __future__ import annotations

"""Bounded model-to-Action-Fabric protocol for generic desktop work.

The model may propose one semantic action or cite verified executions as
completion evidence. It never receives Body authority and cannot manufacture
an action id, arguments, availability, execution result, or verification.
"""

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping

from .structured_proposal import (
    looks_like_structured_payload,
    parse_exact_json_payload,
)


ACTION_PROPOSAL_KEY = "zn_action_proposal"
ACTION_COMPLETION_KEY = "zn_action_completion"


@dataclass(frozen=True, slots=True)
class GenericActionProposal:
    action_id: str
    arguments: Mapping[str, Any]
    def __post_init__(self) -> None:
        action_id = str(self.action_id or "").strip()
        if not action_id:
            raise ValueError("generic action proposal action_id must not be empty")
        if not isinstance(self.arguments, Mapping):
            raise ValueError("generic action proposal arguments must be an object")
        object.__setattr__(self, "action_id", action_id)
        object.__setattr__(self, "arguments", dict(self.arguments))


@dataclass(frozen=True, slots=True)
class GenericActionCompletion:
    execution_ids: tuple[str, ...]
    response: str

    def __post_init__(self) -> None:
        normalized = tuple(
            dict.fromkeys(
                value
                for value in (
                    str(item or "").strip() for item in self.execution_ids
                )
                if value
            )
        )
        if not normalized:
            raise ValueError("generic action completion requires execution evidence")
        if len(normalized) > 8:
            raise ValueError("generic action completion cites too much evidence")
        object.__setattr__(self, "execution_ids", normalized)
        object.__setattr__(self, "response", str(self.response or "")[:4000])
def parse_generic_action_proposal(content: str) -> GenericActionProposal | None:
    parsed = parse_exact_json_payload(content)
    if not isinstance(parsed, dict) or set(parsed) != {ACTION_PROPOSAL_KEY}:
        return None
    raw = parsed.get(ACTION_PROPOSAL_KEY)
    if not isinstance(raw, dict) or set(raw) != {"action_id", "arguments"}:
        return None
    arguments = raw.get("arguments")
    if not isinstance(arguments, dict):
        return None
    try:
        return GenericActionProposal(
            action_id=str(raw.get("action_id") or ""),
            arguments=arguments,
        )
    except ValueError:
        return None


def parse_generic_action_completion(content: str) -> GenericActionCompletion | None:
    parsed = parse_exact_json_payload(content)
    if not isinstance(parsed, dict) or set(parsed) != {ACTION_COMPLETION_KEY}:
        return None
    raw = parsed.get(ACTION_COMPLETION_KEY)
    if not isinstance(raw, dict) or set(raw) != {"execution_ids", "response"}:
        return None
    execution_ids = raw.get("execution_ids")
    if not isinstance(execution_ids, list):
        return None
    try:
        return GenericActionCompletion(
            execution_ids=tuple(execution_ids),
            response=str(raw.get("response") or ""),
        )
    except ValueError:
        return None


def looks_like_generic_action_message(content: str) -> bool:
    return (
        looks_like_structured_payload(content, top_level_key=ACTION_PROPOSAL_KEY)
        or looks_like_structured_payload(
            content,
            top_level_key=ACTION_COMPLETION_KEY,
        )
    )


def build_generic_action_context(
    *,
    fabric: Any,
    device_capabilities: Any,
    task: str,
    history: tuple[Mapping[str, Any], ...] = (),
) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    for descriptor in fabric.descriptors():
        availability = fabric.availability(descriptor.action_id)
        if not availability.available:
            continue
        actions.append(
            {
                "action_id": descriptor.action_id,
                "provider": descriptor.provider,
                "description": descriptor.description,
                "arguments_schema": dict(descriptor.input_schema or {}),
                "effect_class": descriptor.effect_class,
                "preconditions": list(descriptor.preconditions)[:4],
                "verification": list(descriptor.verification)[:4],
            }
        )

    foreground = None
    try:
        observed = device_capabilities.foreground_application()
    except Exception:
        observed = None
    if observed is not None and getattr(observed, "application", None) is not None:
        application = observed.application
        foreground = {
            "application_id": str(getattr(application, "app_id", "")),
            "name": str(getattr(application, "display_name", "")),
        }

    return {
        "version": 1,
        "original_task": str(task or "")[:1200],
        "available_actions": actions,
        "foreground_application": foreground,
        "recent_verified_executions": [
            _bounded_value(dict(item), depth=0, max_depth=8)
            for item in history[-8:]
        ],
    }


def summarize_action_execution(execution: Any) -> dict[str, Any]:
    observations = []
    for observation in tuple(getattr(execution, "observations", ()) or ())[-4:]:
        observations.append(
            {
                "source": str(getattr(observation, "source", "")),
                "observed_at": str(getattr(observation, "observed_at", "")),
                "data": _bounded_value(
                    dict(getattr(observation, "data", {}) or {}),
                    depth=0,
                ),
            }
        )
    verification = getattr(execution, "verification", None)
    descriptor = getattr(execution, "descriptor", None)
    request = getattr(execution, "request", None)
    return {
        "execution_id": str(getattr(execution, "execution_id", "")),
        "action_id": str(getattr(request, "action_id", "")),
        "arguments": _safe_request_arguments(
            str(getattr(request, "action_id", "")),
            dict(getattr(request, "args", {}) or {}),
        ),
        "effect_class": str(getattr(descriptor, "effect_class", "")),
        "status": str(getattr(execution, "status", "")),
        "verified": bool(getattr(execution, "success", False)),
        "verification": {
            "status": str(getattr(verification, "status", "")),
            "reason": str(getattr(verification, "reason", ""))[:1200],
            "evidence": _bounded_value(
                dict(getattr(verification, "evidence", {}) or {}),
                depth=0,
            ),
            "observed_at": str(getattr(verification, "observed_at", "")),
        },
        "observations": observations,
        "error": str(getattr(execution, "error", "") or "")[:1200] or None,
    }


_SENSITIVE_ARGUMENT_NAMES = frozenset(
    {"value", "text", "content", "message", "body", "password", "secret", "token"}
)


def _safe_request_arguments(action_id: str, args: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in dict(args or {}).items():
        normalized = str(key or "").strip().lower()
        if normalized in _SENSITIVE_ARGUMENT_NAMES:
            if isinstance(value, str):
                safe[str(key)] = {
                    "redacted": True,
                    "chars": len(value),
                    "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                }
            else:
                safe[str(key)] = {
                    "redacted": True,
                    "type": type(value).__name__,
                }
            continue
        safe[str(key)] = _bounded_value(value, depth=1)
    return safe


def _bounded_value(
    value: Any,
    *,
    depth: int,
    max_depth: int = 4,
) -> Any:
    if depth >= max(1, int(max_depth)):
        return "<bounded>"
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 32:
                result["_truncated"] = True
                break
            result[str(key)] = _bounded_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
            )
        return result
    if isinstance(value, (list, tuple)):
        items = list(value)
        result = [
            _bounded_value(item, depth=depth + 1, max_depth=max_depth)
            for item in items[:24]
        ]
        if len(items) > 24:
            result.append("<truncated>")
        return result
    if isinstance(value, str):
        return value[:1600]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:800]
