from __future__ import annotations

"""Hard termination for project teams (CP-1).

Mechanism copied from two mature patterns, implemented here from scratch
with no new dependency and no copied code:

- AutoGen's composable termination conditions (``MaxMessage`` /
  ``TextMention`` / ``TokenUsage`` combined with ``|`` as OR, plus a hard
  ceiling): termination is a first-class, check-every-step condition, not
  an afterthought bolted onto a stall timeout.
- CrewAI's Flow skeleton (deterministic control flow around the judging
  Crew): the runner is the Flow -- it evaluates the stop condition on
  every pulse and halts before dispatching more work.

Four hard caps, checked every pulse, any one of which stops the team::

    pulses (runner steps) | wall-clock time | token budget | tool calls

A stop produces a structured ``STOP_REASON`` plus the trigger value that
fired and a progress snapshot, so "the team stopped" is always answerable
as *why*, *at what value*, and *how far it got*::

    time_cap | token_cap | tool_cap | max_pulses
    | converged | user_cancel | error

``converged`` is deliberately NOT producible here: only the CP-3
structured completion verdict may declare convergence. This module
refuses to record ``converged`` (see :func:`request_stop`), and the
runner never emits it -- a team that finishes all plan items reports
``team_complete``, not ``converged``.

Counter sources (all durable, all read from real truth each pulse):

- pulses: incremented once per ``TeamRunner.step()`` call, persisted in
  team shared memory, so a restart resumes the count instead of
  resetting it.
- wall clock: ``started_at`` persisted on the first step; elapsed is
  measured against it.
- tool calls: incremented by the resident at the single point where a
  verified Body step lands on a WorkerRun
  (``TeamWorkResidentRuntime._record_team_evidence``) -- one increment
  per executed specialist tool step, no estimate.
- tokens: accumulated only via :func:`record_token_usage` from a caller
  that has a real provider usage figure. The team path's cognition
  increments currently carry no token usage (``CognitiveIncrement`` has
  no usage field), so the counter starts at 0 and the cap is enforced as
  soon as any caller reports real usage. Nothing here estimates or
  invents token counts.

This module is pure state + a pure checker plus tiny persistence helpers
over team shared memory. It never dispatches, verifies, or completes
anything itself.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

#: Every STOP_REASON the team can stop with. ``converged`` is listed
#: because it is part of the shared vocabulary, but nothing in this module
#: (or in the runner) may produce it -- see the module docstring.
STOP_REASONS: tuple[str, ...] = (
    "time_cap",
    "token_cap",
    "tool_cap",
    "max_pulses",
    "converged",
    "user_cancel",
    "error",
)

#: Reasons that may only be computed by the cap checker, never requested.
_CAP_REASONS = frozenset({"time_cap", "token_cap", "tool_cap", "max_pulses"})

#: Reasons a caller may request explicitly (an external stop, not a cap).
_EXTERNALLY_REQUESTABLE = frozenset({"user_cancel", "error"})


@dataclass(slots=True)
class TerminationLimits:
    """Hard ceilings for one team run. Any one hit stops the team."""

    # Generous backstops, not normal-case budgets: a healthy two-item team
    # finishes in well under 30 pulses / a handful of tool steps. The wall
    # clock matches the coordinator's stall timeout so the two agree on
    # "too long".
    max_pulses: int = 300
    max_wall_clock_seconds: float = 1800.0
    max_total_tokens: int = 1_000_000
    max_tool_calls: int = 300

    def __post_init__(self) -> None:
        for name in (
            "max_pulses",
            "max_wall_clock_seconds",
            "max_total_tokens",
            "max_tool_calls",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(
                value, (int, float)
            ):
                raise ValueError(f"{name} must be a number, got {value!r}")
            if value <= 0:
                raise ValueError(f"{name} must be positive, got {value!r}")


@dataclass(slots=True)
class TerminationState:
    """Durable per-team termination counters + stop record."""

    pulses: int = 0
    started_at: str | None = None  # ISO-8601 UTC, set on the first step
    tokens_used: int = 0
    tool_calls: int = 0
    # An external stop requested before the next cap check
    # ("user_cancel" | "error" | None), with its detail.
    requested_stop: str | None = None
    requested_stop_detail: str = ""
    # The final stop, once taken ("STOP_REASON" | None).
    stop_reason: str | None = None
    stopped_at: str | None = None
    trigger: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pulses": max(0, int(self.pulses or 0)),
            "started_at": self.started_at,
            "tokens_used": max(0, int(self.tokens_used or 0)),
            "tool_calls": max(0, int(self.tool_calls or 0)),
            "requested_stop": self.requested_stop,
            "requested_stop_detail": self.requested_stop_detail,
            "stop_reason": self.stop_reason,
            "stopped_at": self.stopped_at,
            "trigger": dict(self.trigger or {}),
            "progress": dict(self.progress or {}),
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "TerminationState":
        if not isinstance(raw, dict):
            return cls()
        state = cls()
        try:
            state.pulses = max(0, int(raw.get("pulses") or 0))
        except (TypeError, ValueError):
            state.pulses = 0
        try:
            state.tokens_used = max(0, int(raw.get("tokens_used") or 0))
        except (TypeError, ValueError):
            state.tokens_used = 0
        try:
            state.tool_calls = max(0, int(raw.get("tool_calls") or 0))
        except (TypeError, ValueError):
            state.tool_calls = 0
        started = raw.get("started_at")
        state.started_at = str(started) if started else None
        requested = raw.get("requested_stop")
        state.requested_stop = (
            str(requested)
            if requested in _EXTERNALLY_REQUESTABLE
            else None
        )
        detail = raw.get("requested_stop_detail")
        state.requested_stop_detail = str(detail or "")
        reason = raw.get("stop_reason")
        state.stop_reason = str(reason) if reason in STOP_REASONS else None
        stopped = raw.get("stopped_at")
        state.stopped_at = str(stopped) if stopped else None
        if isinstance(raw.get("trigger"), dict):
            state.trigger = dict(raw["trigger"])
        if isinstance(raw.get("progress"), dict):
            state.progress = dict(raw["progress"])
        return state


@dataclass(slots=True)
class TerminationResult:
    """One taken stop: why, at what value, how far the team got."""

    stop_reason: str
    trigger: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, Any] = field(default_factory=dict)


def parse_instant(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp (``Z`` or offset) to aware UTC."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def elapsed_seconds(state: TerminationState, *, now: datetime) -> float:
    """Wall-clock seconds since the team's first step (0 when unknown)."""
    started = parse_instant(state.started_at)
    if started is None:
        return 0.0
    return max(0.0, (now - started).total_seconds())


def evaluate_termination(
    state: TerminationState,
    limits: TerminationLimits,
    *,
    now: datetime,
) -> TerminationResult | None:
    """Pure cap check: return the stop to take, or None to keep going.

    Fixed priority when several caps fire on the same pulse:
    time_cap > token_cap > tool_cap > max_pulses. ``converged`` is never
    returned -- convergence is CP-3's verdict, not a cap.
    """
    elapsed = elapsed_seconds(state, now=now)
    if elapsed >= float(limits.max_wall_clock_seconds):
        return TerminationResult(
            stop_reason="time_cap",
            trigger={
                "elapsed_seconds": elapsed,
                "limit_seconds": float(limits.max_wall_clock_seconds),
            },
        )
    if int(state.tokens_used or 0) >= int(limits.max_total_tokens):
        return TerminationResult(
            stop_reason="token_cap",
            trigger={
                "tokens_used": int(state.tokens_used or 0),
                "limit_tokens": int(limits.max_total_tokens),
            },
        )
    if int(state.tool_calls or 0) >= int(limits.max_tool_calls):
        return TerminationResult(
            stop_reason="tool_cap",
            trigger={
                "tool_calls": int(state.tool_calls or 0),
                "limit_tool_calls": int(limits.max_tool_calls),
            },
        )
    if int(state.pulses or 0) >= int(limits.max_pulses):
        return TerminationResult(
            stop_reason="max_pulses",
            trigger={
                "pulses": int(state.pulses or 0),
                "limit_pulses": int(limits.max_pulses),
            },
        )
    return None


def request_stop(
    state: TerminationState, reason: str, *, detail: str = ""
) -> None:
    """Record an externally requested stop (user_cancel | error).

    Rejects cap reasons (those are computed, never requested) and
    ``converged`` -- convergence may only come from the CP-3 structured
    completion verdict, never from a stop request. A stop that was
    already taken wins: requesting after the fact is a no-op.
    """
    if state.stop_reason is not None:
        return
    if reason == "converged":
        raise ValueError(
            "converged may only be declared by the CP-3 structured "
            "completion verdict, never by a stop request"
        )
    if reason in _CAP_REASONS:
        raise ValueError(
            f"{reason!r} is computed by the cap checker, not requestable"
        )
    if reason not in _EXTERNALLY_REQUESTABLE:
        raise ValueError(
            f"unknown STOP_REASON {reason!r}; expected one of "
            f"{sorted(_EXTERNALLY_REQUESTABLE)}"
        )
    state.requested_stop = reason
    state.requested_stop_detail = str(detail or "")[:2000]


def record_token_usage(state: TerminationState, total_tokens: int) -> None:
    """Add real provider token usage to the running total.

    Callers must pass a real usage figure (prompt + completion tokens
    from a provider response). Never pass an estimate.
    """
    try:
        tokens = int(total_tokens)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"total_tokens must be an int, got {total_tokens!r}") from exc
    if tokens < 0:
        raise ValueError("total_tokens must not be negative")
    state.tokens_used = max(0, int(state.tokens_used or 0)) + tokens


def record_tool_call(state: TerminationState) -> None:
    """Count one executed specialist tool step."""
    state.tool_calls = max(0, int(state.tool_calls or 0)) + 1


def take_stop(
    state: TerminationState,
    result: TerminationResult,
    *,
    now: datetime,
    progress: dict[str, Any] | None = None,
) -> TerminationResult:
    """Fill in the final stop record (first stop wins)."""
    if state.stop_reason is not None:
        return TerminationResult(
            stop_reason=state.stop_reason,
            trigger=dict(state.trigger or {}),
            progress=dict(state.progress or {}),
        )
    state.stop_reason = result.stop_reason
    state.stopped_at = now.isoformat()
    state.trigger = dict(result.trigger or {})
    state.progress = dict(progress or {})
    result.trigger = dict(state.trigger)
    result.progress = dict(state.progress)
    return result


# -- persistence helpers over team shared memory ------------------------

def load_termination_state(shared: Any) -> TerminationState:
    """Read the team's termination state from shared memory (fresh if none)."""
    match = shared.recall("termination_state")
    if match is None:
        return TerminationState()
    return TerminationState.from_dict(match.value)


def save_termination_state(shared: Any, state: TerminationState) -> None:
    shared.remember("termination_state", state.to_dict())


def record_team_tool_call(memory: Any, team_id: str) -> None:
    """Durable +1 tool call for one team (resident evidence path).

    The single writer is the resident's verified-evidence path, so each
    increment corresponds to one executed specialist tool step.
    """
    from .team_memory import team_shared_memory

    clean = str(team_id or "").strip()
    if not clean:
        return
    shared = team_shared_memory(memory, clean)
    state = load_termination_state(shared)
    if state.stop_reason is not None:
        return
    record_tool_call(state)
    save_termination_state(shared, state)


__all__ = [
    "STOP_REASONS",
    "TerminationLimits",
    "TerminationResult",
    "TerminationState",
    "elapsed_seconds",
    "evaluate_termination",
    "load_termination_state",
    "parse_instant",
    "record_team_tool_call",
    "record_token_usage",
    "record_tool_call",
    "request_stop",
    "save_termination_state",
    "take_stop",
]
