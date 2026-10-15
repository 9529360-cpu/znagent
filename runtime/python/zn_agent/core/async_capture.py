from __future__ import annotations

"""Async capture discipline (CM-2): hook thin, spool durable, worker async.

Problem: capturing agent events into memory must never slow down, break,
or loop the thing being observed. A capture hook that calls memory, does
network I/O, or raises will drag the caller's main loop down with it --
and if the memory write itself emits an event, a naive hook re-captures
it forever.

Discipline, enforced by code:

1. The hook is thin, pure, and never blocks.
   ``CaptureHook.capture`` only (a) runs pure field checks on the event
   dict, (b) stamps it, trims it, and (c) appends one JSON line to the
   spool. It never calls memory, cognition, or the network, never holds
   a lock across I/O, and never raises: every failure path returns ``0``.
   Return value is an exit code: ``0`` means "captured or cleanly
   dropped", and a non-zero exit is impossible by construction.

2. Spool is durable and append-only.
   The hook appends one JSON line per event to ``spool.jsonl``. The
   worker owns the cursor (``spool.cursor``) and only advances it past
   entries it has processed, so a crash replays unprocessed entries
   instead of losing them. A torn last line (crash mid-append) is
   skipped, not fatal.

3. The background worker does all the expensive work.
   ``CaptureWorker`` drains the spool on its own thread and calls the
   injected ``sink`` (e.g. a ``memory.remember`` adapter) for surviving
   events. The sink is caller-provided: this module never imports the
   memory store, so capture can never deadlock with memory writes.

4. Only supervisor / decision-layer events are worth memory.
   Worker tool events are high-volume chatter and never enter memory.
   The worker keeps an event only when it is decision-class (kind in
   ``DECISION_KINDS``) or supervisor/coordinator-issued and not skipped.

5. Drop rules, applied by hook (cheap) and re-applied by worker
   (authoritative, so spool entries from any producer get filtered):
   - self-loop: events originating from memory tools / the capture
     pipeline itself (``source`` in ``MEMORY_ORIGIN_SOURCES`` or
     ``tool_name`` in ``MEMORY_TOOL_NAMES``). The hook additionally
     drops events that already carry the capture marker, so a spooled
     event re-emitted downstream is never spooled twice.
   - sub-agent observation: ``actor_role`` / ``source`` / ``kind``
     marking the event as a sub-agent observation. Sub-agent output is
     the parent's evidence, not memory.
   - skip list: high-volume / low-signal kinds (heartbeats, polls,
     tool calls/results, progress pings, raw logs).

6. Sink failure stops the run without losing the entry.
   If the sink raises for an entry, the worker stops, leaves the cursor
   before that entry, and reports ``failed=1``. The next run retries it.
   Failures never poison the spool and never crash the worker.
"""

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .models import utc_now

#: Marker stamped on every event the hook spools. The hook drops events
#: that already carry it (re-emission loop guard); the worker does NOT
#: treat the marker as a self-loop, because every legitimate spool entry
#: carries it.
CAPTURE_MARKER = "cm2-async-capture"

#: Spool file names inside the spool directory.
SPOOL_FILENAME = "spool.jsonl"
CURSOR_FILENAME = "spool.cursor"

#: Hard cap on one spool line (bytes). Oversized payloads are trimmed in
#: ``sanitize_event``; a line that still exceeds the cap loses its
#: payload instead of being dropped silently.
MAX_SPOOL_LINE_BYTES = 64 * 1024

#: Hard cap on the JSON-serialised payload (chars) before trimming.
MAX_PAYLOAD_CHARS = 8000

#: Longest single string kept inside a payload (chars).
MAX_PAYLOAD_STRING_CHARS = 2000

#: Event kinds that are never worth spooling: heartbeats, polls, raw
#: tool chatter, progress pings, logs. High volume, no decision content.
DEFAULT_SKIP_KINDS: frozenset[str] = frozenset(
    {
        "heartbeat",
        "poll",
        "tick",
        "tool_call",
        "tool_result",
        "worker_progress",
        "progress",
        "log",
        "debug",
        "trace",
        "metric",
        "health_check",
    }
)

#: Event kinds that are decision-class and therefore worth memory.
DEFAULT_DECISION_KINDS: frozenset[str] = frozenset(
    {
        "decision",
        "approval_decide",
        "approval_reconsider",
        "verdict",
        "escalation",
        "handoff",
        "plan_created",
        "plan_completed",
        "task_completed",
        "task_failed",
        "merge",
        "deploy",
        "incident",
        "retrospective",
        "milestone",
        "goal_update",
        "supervisor_note",
    }
)

#: Actor roles whose events count as supervisor / decision layer.
SUPERVISOR_ROLES: frozenset[str] = frozenset({"supervisor", "coordinator"})

#: Actor roles / sources that mark an event as sub-agent observation.
SUBAGENT_ROLES: frozenset[str] = frozenset(
    {"subagent", "sub_agent", "child_agent", "worker_agent"}
)
SUBAGENT_SOURCES: frozenset[str] = frozenset({"subagent", "sub_agent"})
SUBAGENT_KINDS: frozenset[str] = frozenset(
    {
        "subagent_observation",
        "subagent_tool_call",
        "subagent_tool_result",
        "subagent_progress",
    }
)

#: Sources that mark an event as produced by the memory pipeline itself.
MEMORY_ORIGIN_SOURCES: frozenset[str] = frozenset(
    {"memory_capture", "memory_tool", "memory"}
)

#: Tool names that belong to the memory system. Events produced by these
#: tools must never be captured, or the capture pipeline observes its
#: own writes forever.
MEMORY_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "memory_read",
        "memory_write",
        "memory_search",
        "memory_get",
        "memory_explain",
        "memory_recall",
        "memory_forget",
        "memory_consolidate",
        "memory_supersession",
        "memory_context",
    }
)


@dataclass(frozen=True, slots=True)
class CaptureConfig:
    """Tunable filter sets. Defaults encode the CM-2 discipline."""

    skip_kinds: frozenset[str] = DEFAULT_SKIP_KINDS
    decision_kinds: frozenset[str] = DEFAULT_DECISION_KINDS
    supervisor_roles: frozenset[str] = SUPERVISOR_ROLES
    subagent_roles: frozenset[str] = SUBAGENT_ROLES
    subagent_sources: frozenset[str] = SUBAGENT_SOURCES
    subagent_kinds: frozenset[str] = SUBAGENT_KINDS
    memory_origin_sources: frozenset[str] = MEMORY_ORIGIN_SOURCES
    memory_tool_names: frozenset[str] = MEMORY_TOOL_NAMES
    max_payload_chars: int = MAX_PAYLOAD_CHARS
    max_payload_string_chars: int = MAX_PAYLOAD_STRING_CHARS
    max_spool_line_bytes: int = MAX_SPOOL_LINE_BYTES


def _as_str(value: Any) -> str:
    return str(value) if value is not None else ""


def _norm(value: Any) -> str:
    """Lowercase, stripped string used for all field comparisons."""
    return str(value or "").strip().lower()


def _trim_string(value: str, *, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "...[truncated]"


def _json_safe(value: Any, *, depth: int, string_limit: int) -> Any:
    """Coerce ``value`` to JSON-safe data, truncating long strings."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _trim_string(value, limit=string_limit)
    if depth <= 0:
        return _trim_string(str(value), limit=string_limit)
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item, depth=depth - 1, string_limit=string_limit)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _json_safe(item, depth=depth - 1, string_limit=string_limit)
            for item in value
        ]
    return _trim_string(str(value), limit=string_limit)


def _trim_payload(payload: Mapping[str, Any], *, config: CaptureConfig) -> dict[str, Any]:
    """Trim a payload to the char budget, dropping keys from the end."""
    trimmed = _json_safe(dict(payload), depth=4, string_limit=config.max_payload_string_chars)
    if not isinstance(trimmed, dict):
        return {}
    while True:
        try:
            text = json.dumps(trimmed, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return {}
        if len(text) <= config.max_payload_chars or not trimmed:
            return trimmed
        trimmed.pop(next(reversed(trimmed)))


def sanitize_event(
    event: Mapping[str, Any],
    *,
    config: CaptureConfig | None = None,
) -> dict[str, Any]:
    """Normalise one event for spooling (pure: no I/O, no mutation).

    Stamps ``capture_origin`` with :data:`CAPTURE_MARKER`, fills a
    missing ``event_id`` / ``at``, and trims the payload to budget.
    Raises ``TypeError`` / ``ValueError`` on a non-mapping or missing
    ``kind`` -- callers that must never raise (the hook) catch those.
    """
    config = config or CaptureConfig()
    if not isinstance(event, Mapping):
        raise TypeError("capture event must be a mapping")
    kind = _norm(event.get("kind"))
    if not kind:
        raise ValueError("capture event requires a non-empty kind")
    payload = event.get("payload")
    if payload is None:
        payload = {}
    if not isinstance(payload, Mapping):
        payload = {"value": payload}
    cleaned: dict[str, Any] = {
        "event_id": _as_str(event.get("event_id") or "").strip(),
        "kind": kind,
        "source": _norm(event.get("source")),
        "actor_role": _norm(event.get("actor_role")),
        "tool_name": _norm(event.get("tool_name")),
        "payload": _trim_payload(payload, config=config),
        "at": _as_str(event.get("at") or "").strip() or utc_now(),
        "capture_origin": CAPTURE_MARKER,
    }
    if not cleaned["event_id"]:
        digest = hashlib.sha256(
            json.dumps(cleaned, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:16]
        cleaned["event_id"] = f"evt-{digest}"
    return cleaned


def is_memory_origin(event: Mapping[str, Any], *, config: CaptureConfig | None = None) -> bool:
    """True when the event was produced by the memory pipeline itself."""
    config = config or CaptureConfig()
    if _norm(event.get("source")) in config.memory_origin_sources:
        return True
    return _norm(event.get("tool_name")) in config.memory_tool_names


def is_subagent_observation(
    event: Mapping[str, Any], *, config: CaptureConfig | None = None
) -> bool:
    """True when the event is sub-agent observation, not parent evidence."""
    config = config or CaptureConfig()
    if _norm(event.get("actor_role")) in config.subagent_roles:
        return True
    if _norm(event.get("source")) in config.subagent_sources:
        return True
    return _norm(event.get("kind")) in config.subagent_kinds


def is_skipped(event: Mapping[str, Any], *, config: CaptureConfig | None = None) -> bool:
    """True when the event kind is on the skip list (pure)."""
    config = config or CaptureConfig()
    return _norm(event.get("kind")) in config.skip_kinds


def is_eligible(event: Mapping[str, Any], *, config: CaptureConfig | None = None) -> bool:
    """True when the event is supervisor / decision-layer (pure).

    Decision-class kinds always qualify. Supervisor / coordinator
    events qualify for any non-skipped kind; everything else does not.
    """
    config = config or CaptureConfig()
    kind = _norm(event.get("kind"))
    if kind in config.decision_kinds:
        return True
    if _norm(event.get("actor_role")) in config.supervisor_roles:
        return kind not in config.skip_kinds
    return False


def classify(event: Mapping[str, Any], *, config: CaptureConfig | None = None) -> str:
    """Worker-side verdict for one event: ``keep`` or a ``drop_*`` reason.

    Order is deliberate: self-loop first (a memory-tool event must never
    survive even if it looks decision-class), then sub-agent, then skip
    list, then eligibility.
    """
    config = config or CaptureConfig()
    if is_memory_origin(event, config=config):
        return "drop_self_loop"
    if is_subagent_observation(event, config=config):
        return "drop_subagent"
    if is_skipped(event, config=config):
        return "drop_skip"
    if not is_eligible(event, config=config):
        return "drop_ineligible"
    return "keep"


class Spool:
    """Durable append-only spool: ``spool.jsonl`` + ``spool.cursor``.

    ``append`` is the only writer the hook needs; it never raises.
    ``pending`` yields ``(end_offset, parsed_or_None)`` pairs past the
    cursor; malformed / torn lines parse to ``None`` and are skipped by
    the worker. ``advance`` persists the cursor. All methods are
    defensive: a missing / unreadable spool behaves as empty.
    """

    def __init__(self, directory: str | Path, *, config: CaptureConfig | None = None) -> None:
        self.directory = Path(directory)
        self.config = config or CaptureConfig()
        self._lock = threading.Lock()
        self._file = self.directory / SPOOL_FILENAME
        self._cursor_file = self.directory / CURSOR_FILENAME
        #: Cursor-persist failures swallowed by :meth:`advance`, counted
        #: (never logged: this path must stay non-blocking and non-raising).
        self.advance_failures: int = 0

    def append(self, event: Mapping[str, Any]) -> bool:
        """Append one JSON line. Never raises; False means not stored."""
        try:
            line = json.dumps(dict(event), ensure_ascii=False, default=str)
            if len(line.encode("utf-8")) > self.config.max_spool_line_bytes:
                trimmed = dict(event)
                trimmed["payload"] = {}
                trimmed["payload_dropped"] = True
                line = json.dumps(trimmed, ensure_ascii=False, default=str)
            with self._lock:
                self.directory.mkdir(parents=True, exist_ok=True)
                with open(self._file, "a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
                    handle.flush()
            return True
        except BaseException:
            return False

    def cursor(self) -> int:
        """Last processed byte offset (0 when unknown / corrupt)."""
        try:
            value = int(self._cursor_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return 0
        if value < 0:
            return 0
        try:
            size = self._file.stat().st_size
        except OSError:
            return 0
        return min(value, size)

    def advance(self, offset: int) -> None:
        """Persist the cursor. Never raises; a lost cursor only replays.

        A persist failure is counted in :attr:`advance_failures` so the
        loss is observable instead of silently swallowed.
        """
        try:
            with self._lock:
                self.directory.mkdir(parents=True, exist_ok=True)
                tmp = self._cursor_file.with_suffix(".tmp")
                tmp.write_text(str(int(offset)), encoding="utf-8")
                tmp.replace(self._cursor_file)
        except BaseException:
            self.advance_failures += 1

    def pending(self) -> list[tuple[int, dict[str, Any] | None]]:
        """Entries after the cursor as ``(end_offset, parsed_or_None)``."""
        try:
            raw = self._file.read_bytes()
        except OSError:
            return []
        start = self.cursor()
        if start >= len(raw):
            return []
        entries: list[tuple[int, dict[str, Any] | None]] = []
        offset = start
        for chunk in raw[start:].splitlines(keepends=True):
            offset += len(chunk)
            text = chunk.decode("utf-8", errors="replace").strip()
            if not text:
                entries.append((offset, None))
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                entries.append((offset, None))
                continue
            entries.append((offset, parsed if isinstance(parsed, dict) else None))
        return entries


class CaptureHook:
    """The thin capture hook: pure checks + one spool append, exit 0 always.

    ``capture`` never raises and never returns non-zero, even when the
    event is malformed or the spool is unwritable. It never touches
    memory, cognition, or the network -- the background worker owns all
    expensive work. Use the instance as a callback: ``hook(event)``.
    """

    def __init__(self, spool: Spool, *, config: CaptureConfig | None = None) -> None:
        self.spool = spool
        self.config = config or CaptureConfig()

    def capture(self, event: Any) -> int:
        """Capture or cleanly drop one event. Always returns 0."""
        try:
            if not isinstance(event, Mapping):
                return 0
            # Already spooled once: never spool twice (re-emission guard).
            if event.get("capture_origin") == CAPTURE_MARKER:
                return 0
            if is_memory_origin(event, config=self.config):
                return 0
            if is_subagent_observation(event, config=self.config):
                return 0
            if is_skipped(event, config=self.config):
                return 0
            try:
                cleaned = sanitize_event(event, config=self.config)
            except (TypeError, ValueError):
                return 0
            self.spool.append(cleaned)
            return 0
        except BaseException:
            return 0

    __call__ = capture


def capture_event(
    spool: Spool, event: Any, *, config: CaptureConfig | None = None
) -> int:
    """Module-level convenience: thin-hook capture, always returns 0."""
    return CaptureHook(spool, config=config).capture(event)


@dataclass(slots=True)
class WorkerResult:
    """Outcome of one worker drain: counts + the cursor after the run."""

    processed: int = 0
    kept: int = 0
    failed: int = 0
    dropped: dict[str, int] = field(default_factory=dict)
    cursor_after: int = 0


class CaptureWorker:
    """Background worker: drains the spool, filters, calls the sink.

    The ``sink`` is caller-provided (e.g. a ``memory.remember`` adapter)
    and receives sanitized event dicts that passed :func:`classify`.
    On sink failure the run stops and the cursor stays before the failed
    entry, so the next run retries it. ``run_once`` never raises.
    """

    def __init__(self, spool: Spool, *, config: CaptureConfig | None = None) -> None:
        self.spool = spool
        self.config = config or CaptureConfig()
        #: Unexpected errors escaping one :meth:`run_once` drain, counted
        #: by :meth:`run_forever` instead of silently swallowed.
        self.loop_errors: int = 0

    def run_once(self, sink: Callable[[dict[str, Any]], None]) -> WorkerResult:
        """Drain pending entries once. Never raises."""
        result = WorkerResult()
        try:
            entries = self.spool.pending()
        except BaseException:
            return result
        for end_offset, parsed in entries:
            result.processed += 1
            if parsed is None:
                result.dropped["drop_malformed"] = result.dropped.get("drop_malformed", 0) + 1
                self.spool.advance(end_offset)
                continue
            verdict = classify(parsed, config=self.config)
            if verdict != "keep":
                result.dropped[verdict] = result.dropped.get(verdict, 0) + 1
                self.spool.advance(end_offset)
                continue
            try:
                sink(parsed)
            except BaseException:
                # Stop here; cursor stays before the failed entry so the
                # next run retries it. Nothing is lost, nothing poisoned.
                result.failed += 1
                break
            result.kept += 1
            self.spool.advance(end_offset)
        result.cursor_after = self.spool.cursor()
        return result

    def run_forever(
        self,
        sink: Callable[[dict[str, Any]], None],
        *,
        interval_seconds: float = 5.0,
        stop_event: threading.Event,
    ) -> None:
        """Drain in a loop until ``stop_event`` is set. Never raises.

        An unexpected error escaping one drain is counted in
        :attr:`loop_errors` so a repeatedly failing loop is observable.
        """
        interval = max(0.0, float(interval_seconds))
        while not stop_event.is_set():
            try:
                self.run_once(sink)
            except BaseException:
                self.loop_errors += 1
            stop_event.wait(interval)

    def start_background(
        self,
        sink: Callable[[dict[str, Any]], None],
        *,
        interval_seconds: float = 5.0,
    ) -> tuple[threading.Thread, threading.Event]:
        """Spawn the drain loop on a daemon thread; never keeps the process alive."""
        stop_event = threading.Event()
        worker_thread = threading.Thread(
            target=self.run_forever,
            kwargs={
                "sink": sink,
                "interval_seconds": interval_seconds,
                "stop_event": stop_event,
            },
            daemon=True,
            name="cm2-capture-worker",
        )
        worker_thread.start()
        return worker_thread, stop_event


__all__ = [
    "CAPTURE_MARKER",
    "CURSOR_FILENAME",
    "DEFAULT_DECISION_KINDS",
    "DEFAULT_SKIP_KINDS",
    "MAX_PAYLOAD_CHARS",
    "MAX_PAYLOAD_STRING_CHARS",
    "MAX_SPOOL_LINE_BYTES",
    "MEMORY_ORIGIN_SOURCES",
    "MEMORY_TOOL_NAMES",
    "SPOOL_FILENAME",
    "SUBAGENT_KINDS",
    "SUBAGENT_ROLES",
    "SUBAGENT_SOURCES",
    "SUPERVISOR_ROLES",
    "CaptureConfig",
    "CaptureHook",
    "CaptureWorker",
    "Spool",
    "WorkerResult",
    "capture_event",
    "classify",
    "is_eligible",
    "is_memory_origin",
    "is_skipped",
    "is_subagent_observation",
    "sanitize_event",
]
