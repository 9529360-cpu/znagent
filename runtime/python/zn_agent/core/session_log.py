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

Retention: the log grows with every model call, so :meth:`SessionLog.prune_sessions`
applies a bounded retention policy (:class:`SessionLogRetentionPolicy`) --
whole closed sessions older than ``max_age_days`` or beyond the newest
``max_sessions`` are deleted, and every run (including dry runs) writes a
journal record. Fail closed: a session whose activity timestamps cannot be
determined is never a deletion candidate.

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
from datetime import datetime, timedelta, timezone
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


@dataclass(frozen=True, slots=True)
class SessionLogRetentionPolicy:
    """Bounded retention for the DSH-1 session log.

    A session is a deletion candidate when its newest event is older than
    ``max_age_days`` **or** when more than ``max_sessions`` newer sessions
    exist (explicit "keep the newest N sessions" semantics). Deletion always
    removes whole sessions -- never partial sessions, never the newest
    activity -- and sessions whose timestamps cannot be determined are kept
    (fail closed).

    Defaults are conservative: three months of history and the newest 1000
    sessions survive every prune.
    """

    max_age_days: int = 90
    max_sessions: int = 1000

    def __post_init__(self) -> None:
        for name in ("max_age_days", "max_sessions"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(
                    f"SessionLogRetentionPolicy.{name} must be a positive int, got {value!r}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {"max_age_days": self.max_age_days, "max_sessions": self.max_sessions}


@dataclass(slots=True)
class SessionPruneReport:
    """Outcome of one :meth:`SessionLog.prune_sessions` run (the journal entry)."""

    prune_id: str
    started_at: str
    finished_at: str
    dry_run: bool
    policy: dict[str, Any]
    candidates: list[str]
    deleted_sessions: list[str]
    deleted_events: int
    skipped_sessions: int
    retained_boundary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_created_at(raw: Any) -> datetime | None:
    """Parse a stored ``created_at`` for prune comparisons; None when unknown.

    Fail closed: anything unparseable (or missing) yields None, and callers
    must keep such sessions instead of deleting them.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _coerce_now(now: Any) -> datetime:
    """Normalize the ``now`` argument of ``prune_sessions`` to aware UTC.

    Raises ``ValueError`` when ``now`` is unparseable -- pruning at an
    unknown time must not delete anything (fail closed).
    """
    if now is None:
        parsed = _parse_created_at(utc_now())
        assert parsed is not None  # utc_now() always parses; internal invariant
        return parsed
    if isinstance(now, datetime):
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now
    parsed = _parse_created_at(now)
    if parsed is None:
        raise ValueError(f"prune_sessions: unparseable now={now!r}; refusing to prune")
    return parsed


class SessionLog:
    """Append-only session event log, durable when a store is given."""

    def __init__(
        self,
        store: Any | None = None,
        retention: SessionLogRetentionPolicy | None = None,
    ) -> None:
        self._store = store
        self._retention = retention
        self._memory: list[SessionEvent] = []
        self._prune_journal: list[SessionPruneReport] = []
        self._next_seq = 0

    @property
    def store(self) -> Any | None:
        return self._store

    @property
    def retention(self) -> SessionLogRetentionPolicy:
        """Effective retention policy (explicit or the conservative default)."""
        return self._retention or SessionLogRetentionPolicy()

    @property
    def prune_journal(self) -> list[SessionPruneReport]:
        """Prune records for the in-memory log.

        With a store, prune records live in the durable ``session_log_prunes``
        table instead; read them via ``store.session_log_prunes()``.
        """
        return list(self._prune_journal)

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

    def prune_sessions(
        self,
        policy: SessionLogRetentionPolicy | None = None,
        *,
        dry_run: bool = False,
        now: Any = None,
    ) -> SessionPruneReport:
        """Apply the retention policy: delete old sessions, keep the journal.

        A session is deleted when its newest event is older than
        ``policy.max_age_days`` **or** more than ``policy.max_sessions``
        newer sessions exist. Deletion removes whole sessions only; sessions
        with undeterminable timestamps (or no session id) are never deleted.
        With ``dry_run=True`` nothing is deleted but the candidate plan is
        still journaled. Every run -- dry or real -- writes a journal record
        (durable ``session_log_prunes`` table with a store, in-memory
        :attr:`prune_journal` without one).

        ``now`` accepts a datetime or ISO-8601 string for tests; an
        unparseable ``now`` raises ``ValueError`` and deletes nothing.
        """
        effective = policy or self.retention
        started_at = utc_now()
        now_dt = _coerce_now(now)
        cutoff = now_dt - timedelta(days=effective.max_age_days)

        stats = self._session_stats()
        eligible: list[tuple[str, datetime, int]] = []
        skipped = 0
        for entry in stats:
            session_id = str(entry.get("session_id") or "")
            newest = _parse_created_at(entry.get("newest_created_at"))
            if (
                not session_id
                or not entry.get("timestamps_complete")
                or newest is None
            ):
                # Fail closed: unknown session boundary -> keep everything.
                skipped += 1
                continue
            eligible.append((session_id, newest, int(entry.get("event_count") or 0)))

        # Recency rank: newest session first; session_id breaks ties so the
        # plan is deterministic.
        ranked = sorted(eligible, key=lambda item: (item[1], item[0]), reverse=True)
        candidates = [
            session_id
            for rank, (session_id, newest, _count) in enumerate(ranked)
            if newest < cutoff or rank >= effective.max_sessions
        ]

        report = SessionPruneReport(
            prune_id=f"prune-{uuid.uuid4().hex[:16]}",
            started_at=started_at,
            finished_at="",
            dry_run=bool(dry_run),
            policy=effective.to_dict(),
            candidates=list(candidates),
            deleted_sessions=[],
            deleted_events=0,
            skipped_sessions=skipped,
            retained_boundary={},
        )

        if candidates and not dry_run:
            deleted_events = 0
            store = self._store
            for session_id in candidates:
                if store is not None:
                    deleted_events += int(store.delete_session_events(session_id))
                else:
                    before = len(self._memory)
                    self._memory = [
                        event
                        for event in self._memory
                        if event.session_id != session_id
                    ]
                    deleted_events += before - len(self._memory)
            report.deleted_sessions = list(candidates)
            report.deleted_events = deleted_events

        deleted = set(report.deleted_sessions)
        remaining = [
            (session_id, newest)
            for session_id, newest, _count in ranked
            if session_id not in deleted
        ]
        if remaining:
            oldest = min(remaining, key=lambda item: (item[1], item[0]))
            report.retained_boundary = {
                "oldest_retained_session_id": oldest[0],
                "oldest_retained_last_activity": oldest[1].isoformat(),
                "retained_sessions": len(remaining),
            }
        else:
            report.retained_boundary = {
                "oldest_retained_session_id": None,
                "oldest_retained_last_activity": None,
                "retained_sessions": 0,
            }

        report.finished_at = utc_now()
        self._write_prune_journal(report)
        return report

    def _session_stats(self) -> list[dict[str, Any]]:
        """Per-session aggregates: session_id, event_count, oldest/newest
        created_at (ISO strings), timestamps_complete."""
        store = self._store
        if store is not None:
            return list(store.session_prune_stats())
        by_id: dict[str, dict[str, Any]] = {}
        for event in self._memory:
            session_id = str(event.session_id or "")
            entry = by_id.setdefault(
                session_id,
                {
                    "session_id": session_id,
                    "event_count": 0,
                    "oldest_created_at": None,
                    "newest_created_at": None,
                    "timestamps_complete": True,
                },
            )
            entry["event_count"] += 1
            created = _parse_created_at(event.created_at)
            if created is None:
                entry["timestamps_complete"] = False
                continue
            iso = created.isoformat()
            if entry["oldest_created_at"] is None or iso < entry["oldest_created_at"]:
                entry["oldest_created_at"] = iso
            if entry["newest_created_at"] is None or iso > entry["newest_created_at"]:
                entry["newest_created_at"] = iso
        return list(by_id.values())

    def _write_prune_journal(self, report: SessionPruneReport) -> None:
        store = self._store
        if store is not None:
            store.record_session_prune(
                {
                    "prune_id": report.prune_id,
                    "started_at": report.started_at,
                    "finished_at": report.finished_at,
                    "dry_run": report.dry_run,
                    "policy": report.policy,
                    "candidate_sessions": len(report.candidates),
                    "deleted_sessions": len(report.deleted_sessions),
                    "deleted_events": report.deleted_events,
                    "skipped_sessions": report.skipped_sessions,
                    "retained_boundary": report.retained_boundary,
                }
            )
        else:
            self._prune_journal.append(report)


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
    "SessionLogRetentionPolicy",
    "SessionPruneReport",
    "content_fingerprint",
    "image_fingerprint",
    "new_request_id",
    "rebuild_model_request",
]
