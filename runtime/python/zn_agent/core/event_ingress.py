from __future__ import annotations

"""Idempotent ingress for durable external resident percepts.

External organs may need restart-safe event identity before a route/checkpoint is
persisted. This helper derives/stores an explicit AgentEvent without creating a
second task system. Existing resident events are never replaced or re-queued.
"""

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping

from .models import AgentEvent


@dataclass(frozen=True, slots=True)
class IngressResult:
    event: AgentEvent
    created: bool


def stable_external_event_id(namespace: str, source_key: str) -> str:
    scope = str(namespace or "external").strip().lower() or "external"
    key = str(source_key or "").strip()
    if not key:
        raise ValueError("stable external event id requires source key")
    digest = hashlib.sha256(f"{scope}\0{key}".encode("utf-8")).hexdigest()[:24]
    return f"evt-{scope}-{digest}"


def enqueue_event_once(
    resident,
    *,
    event_id: str,
    task: str,
    kind: str,
    payload: Mapping[str, Any] | None = None,
) -> IngressResult:
    """Insert one durable resident event unless that exact id already exists."""
    key = str(event_id or "").strip()
    if not key:
        raise ValueError("resident ingress event_id must not be empty")
    existing = resident.store.get_event(key)
    if existing is not None:
        return IngressResult(existing, False)
    event = AgentEvent(
        event_id=key,
        task=str(task or ""),
        kind=str(kind or "interactive"),
        payload=dict(payload or {}),
    )
    resident.store.enqueue_event(event)
    return IngressResult(event, True)
