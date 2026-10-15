from __future__ import annotations

"""Append-only session event log: the source of truth for model-visible context.

DSH-1. Every model request ZN sends must be rebuildable from this log alone,
and everything the model sees must land in this log. The log records the
post-egress-redaction provider request exactly as it was sent -- never the
pre-redaction text, never credentials, never image bytes (images are referenced
by content hash).

Event kinds (the only four):

- ``model_request_planned`` -- ZN-side intent for one model call. Carries
  correlation ids plus only lengths and hashes of the pre-redaction
  question/context, so a planned call can be matched to what was sent
  without storing secret-shaped text the model never saw.
- ``model_request_sent`` -- the exact provider request body that was sent,
  recorded *before* the network call, so an interrupted dispatch is still
  reconstructable (the request is known even when the result is unknown).
- ``model_response`` -- what came back: text, finish reason, usage. Model
  thinking/reasoning blocks are deliberately not logged.
- ``model_request_failed`` -- the send failed or the provider errored.
  Carries only the exception type, never exception text (which may echo
  request content).

A ``SessionLog`` is a thin wrapper around :class:`KernelStore` when a store
is given (durable, append-only ``session_events`` table -- inserts only,
no update/delete path exists), or an in-memory list when it is not (tests
and callers without a store). Logging must never break cognition: ``emit``
lets storage errors propagate so callers decide, and every production call
site wraps ``emit`` and swallows logging failures.

Rebuild: :func:`rebuild_model_request` returns the exact sent request plus
its paired response/failure (if any) and the planned correlation event (if
any) for one ``request_id``. It raises ``KeyError`` when no sent event
exists -- a request that was never logged cannot be rebuilt, by design.
"""

import copy
import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from .models import utc_now

SESSION_EVENT_KINDS = frozenset(
    {
        "model_request_planned",
        "model_request_sent",
        "model_response",
        "model_request_failed",
    }
)


def new_request_id() -> str:
    """Fresh correlation id for one model request (one attempt, one send)."""
    return f"req-{uuid.uuid4().hex[:16]}"


def content_fingerprint(text: str) -> str:
    """SHA-256 of text, for matching planned vs. sent content without storing it."""
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def image_fingerprint(image_bytes: bytes) -> dict[str, Any]:
    """Identity descriptor for one image sent to a model (bytes never logged)."""
    raw = bytes(image_bytes or b"")
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


@dataclass(slots=True)
class SessionEvent:
    """One append-only entry in the session log."""

    seq: int
    event_id: str
    session_id: str
    request_id: str
    kind: str
    created_at: str = field(default_factory=utc_now)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SessionEvent":
        data = dict(raw or {})
        data["payload"] = dict(data.get("payload") or {})
        return cls(**data)


class SessionEventSink(Protocol):
    """Emit side of the log; resources depend on this, not on the store."""

    def emit(
        self,
        kind: str,
        *,
        request_id: str,
        session_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> SessionEvent: ...


class SessionLog:
    """Append-only session event log, durable when a store is given."""

    def __init__(self, store: Any | None = None) -> None:
        self._store = store
        self._memory: list[SessionEvent] = []
        self._next_seq = 0

    @property
    def store(self) -> Any | None:
        return self._store

    def emit(
        self,
        kind: str,
        *,
        request_id: str,
        session_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> SessionEvent:
        if kind not in SESSION_EVENT_KINDS:
            raise ValueError(f"unknown session event kind: {kind!r}")
        if not str(request_id or "").strip():
            raise ValueError("session event request_id must not be empty")
        body = dict(payload or {})
        # Fail fast on non-JSON payloads: a half-logged event that the store
        # cannot persist is worse than a loud error at the call site.
        try:
            json.dumps(body, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("session event payload must be JSON serializable") from exc
        event = SessionEvent(
            seq=0,
            event_id=f"sev-{uuid.uuid4().hex[:16]}",
            session_id=str(session_id or ""),
            request_id=str(request_id),
            kind=kind,
            payload=body,
        )
        store = self._store
        if store is not None:
            event.seq = int(store.append_session_event(event.to_dict()))
        else:
            self._next_seq += 1
            event.seq = self._next_seq
            self._memory.append(event)
        return event

    def events_for_request(self, request_id: str) -> list[SessionEvent]:
        store = self._store
        if store is not None:
            return [
                SessionEvent.from_dict(raw)
                for raw in store.session_events_for_request(str(request_id))
            ]
        return [
            event
            for event in self._memory
            if event.request_id == str(request_id)
        ]

    def events_for_session(self, session_id: str) -> list[SessionEvent]:
        """All events for one session, resolved via planned events' request ids."""
        target = str(session_id or "")
        if not target:
            return []
        store = self._store
        if store is not None:
            request_ids = store.session_planned_request_ids(target)
        else:
            request_ids = []
            seen: set[str] = set()
            for event in self._memory:
                if (
                    event.session_id == target
                    and event.kind == "model_request_planned"
                    and event.request_id not in seen
                ):
                    seen.add(event.request_id)
                    request_ids.append(event.request_id)
        ordered: list[SessionEvent] = []
        for request_id in request_ids:
            ordered.extend(self.events_for_request(request_id))
        ordered.sort(key=lambda event: event.seq)
        return ordered


def rebuild_model_request(
    log: SessionLog,
    request_id: str,
) -> dict[str, Any]:
    """Rebuild one model request from the log alone.

    Returns the exact sent provider request plus its paired response/failure
    (when logged) and the planned correlation event (when logged). Raises
    ``KeyError`` when no sent event exists for ``request_id`` -- an unlogged
    request is unreconstructable, and this function must say so instead of
    guessing from live state.
    """
    events = log.events_for_request(str(request_id))
    sent = next(
        (event for event in events if event.kind == "model_request_sent"),
        None,
    )
    if sent is None:
        raise KeyError(f"no logged model request for request_id={request_id!r}")
    planned = next(
        (event for event in events if event.kind == "model_request_planned"),
        None,
    )
    response = next(
        (event for event in events if event.kind == "model_response"),
        None,
    )
    failure = next(
        (event for event in events if event.kind == "model_request_failed"),
        None,
    )
    rebuilt: dict[str, Any] = {
        "request_id": str(request_id),
        "provider": sent.payload.get("provider"),
        "model": sent.payload.get("model"),
        "api_mode": sent.payload.get("api_mode"),
        "request": copy.deepcopy(sent.payload.get("request")),
        "response": copy.deepcopy(response.payload) if response is not None else None,
        "failure": copy.deepcopy(failure.payload) if failure is not None else None,
    }
    if planned is not None:
        rebuilt["planned"] = copy.deepcopy(planned.payload)
        rebuilt["session_id"] = planned.session_id
    return rebuilt


__all__ = [
    "SESSION_EVENT_KINDS",
    "SessionEvent",
    "SessionEventSink",
    "SessionLog",
    "content_fingerprint",
    "image_fingerprint",
    "new_request_id",
    "rebuild_model_request",
]
