from __future__ import annotations

"""Tiered repeat reminders (DSH-4): advisory-only nudges, never a gate.

When a specialist repeats the *same tool call* -- same tool, same
parameters -- the resident injects a graded reminder into the next
cognition question: a short reminder at 3 consecutive repeats, a
detailed reminder naming the tool and its parameters at 5 and at 8.
The reminder is advice, not enforcement: it never blocks, rejects,
escalates, or changes execution. The run continues exactly as it would
without the reminder.

Complement to #493 (hard rewrite-loop escalation), not a second copy:
#493 counts *verified evidence* -- identical (objective, path, content)
twice or the same (objective, path) four times -- and escalates. This
module counts *dispatched tool calls* -- (tool, params) with no
objective in the identity -- so it also catches repeats #493 cannot
see (the same call re-proposed under a different objective, or a
run_python call with identical args), and it nudges *before* the hard
escalation fires instead of replacing it.

Identity is exact matching over a canonical form: parameters are
normalized with deep-sorted keys and serialized deterministically
before hashing, so ``{"a": 1, "b": 2}`` and ``{"b": 2, "a": 1}`` are
the same call, and any difference in value is a different call.

State shape (a plain JSON-safe dict, kept in the resident's working
state under one key)::

    {
        "run_id": str,          # live run the streak belongs to
        "message_id": str,      # user message the streak belongs to
        "last_identity": str,   # canonical identity of the last call
        "streak": int,          # consecutive repeats of that identity
        "tool": str,            # tool of the current streak
        "params_display": str,  # truncated display string for reminders
        "pending_reminder": str | None,  # reminder for the next question
    }

A new user message (a different ``work_message_id``) or a new run
clears the count: the next call starts a fresh streak of 1. Reads are
gated on the same run/message, so a stale history is never shown
after the user has spoken again.

Every function here is total: unusual inputs normalize instead of
raising, so the advisory path can never break a dispatch.
"""

import hashlib
import json
from typing import Any, Mapping

#: Consecutive-repeat thresholds that produce a reminder. 3 is a short
#: reminder; 5 and 8 are detailed reminders naming tool + parameters.
REPEAT_REMINDER_THRESHOLDS: tuple[int, ...] = (3, 5, 8)

#: Max characters of the parameter display kept for a detailed reminder.
MAX_PARAMS_DISPLAY_CHARS = 300


def _normalize(value: Any) -> Any:
    """Recursively normalize a value for deterministic serialization."""
    if isinstance(value, Mapping):
        return {str(key): _normalize(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_normalize(item) for item in value), key=repr)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def canonical_tool_identity(tool: str, params: Mapping[str, Any]) -> str:
    """Deterministic identity for one tool call (tool + exact params).

    The canonical form sorts keys at every depth before serializing,
    so key order never changes the identity. The returned value is the
    SHA-256 of that canonical JSON (first 16 hex chars, same convention
    as the rewrite-loop content hash) so a large parameter payload
    never bloats durable state.
    """
    canonical = json.dumps(
        {"tool": str(tool), "params": _normalize(params)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8", errors="replace")).hexdigest()[
        :16
    ]


def reminder_for_streak(
    *, streak: int, tool: str, params_display: str
) -> str | None:
    """Reminder text for a consecutive-repeat streak, else None.

    Only the threshold streaks (3, 5, 8) produce a reminder. Streak 3
    is short (no parameters named); streaks 5 and 8 are detailed and
    name the tool and its parameters. Advisory wording only: the text
    says it is a suggestion and that execution continues.
    """
    if streak == 3:
        return (
            "提醒：你已连续 3 次重复相同的工具调用。"
            "请先检查上一次调用的实际结果，再决定下一步，"
            "不要原样重复同一调用。（建议，仅提醒，不拦截）"
        )
    if streak in (5, 8):
        return (
            f"提醒：你已连续 {streak} 次调用相同工具 {tool}，"
            f"参数为 {params_display}。"
            "这看起来像在原地重复：请停下来，检查上一次调用的"
            "实际结果或报错，换一个做法，或上报你卡在哪里；"
            "不要再次发出相同的调用。"
            "（建议，仅提醒，不拦截，执行照常继续）"
        )
    return None


def observe_tool_call(
    history: dict[str, Any],
    *,
    run_id: str,
    message_id: str,
    tool: str,
    params: Mapping[str, Any],
    params_display: str,
) -> None:
    """Record one dispatched tool call into ``history`` (mutated in place).

    A new run or a new user message resets the streak first. An
    identical consecutive call extends the streak; any other call
    starts a fresh streak of 1. When the new streak hits a threshold,
    ``pending_reminder`` is set to that reminder; otherwise it is
    cleared, so the next cognition question shows at most the
    reminder for the latest threshold crossing.
    """
    if (
        str(history.get("run_id") or "") != str(run_id)
        or str(history.get("message_id") or "") != str(message_id)
    ):
        history.clear()
        history["run_id"] = str(run_id)
        history["message_id"] = str(message_id)
        history["last_identity"] = ""
        history["streak"] = 0
        history["tool"] = ""
        history["params_display"] = ""
        history["pending_reminder"] = None
    identity = canonical_tool_identity(tool, params)
    if identity and identity == str(history.get("last_identity") or ""):
        streak = int(history.get("streak") or 0) + 1
    else:
        streak = 1
    display = str(params_display)[:MAX_PARAMS_DISPLAY_CHARS]
    history["last_identity"] = identity
    history["streak"] = streak
    history["tool"] = str(tool)
    history["params_display"] = display
    history["pending_reminder"] = reminder_for_streak(
        streak=streak, tool=str(tool), params_display=display
    )


def pending_reminder(
    history: Any, *, run_id: str, message_id: str
) -> str | None:
    """Reminder for the next cognition question, else None.

    Returns the stored pending reminder only when it belongs to the
    current run and the current user message; a new message or a new
    run means no reminder is shown, even before the next call resets
    the stored history.
    """
    if not isinstance(history, dict):
        return None
    if (
        str(history.get("run_id") or "") != str(run_id)
        or str(history.get("message_id") or "") != str(message_id)
    ):
        return None
    reminder = history.get("pending_reminder")
    return str(reminder) if isinstance(reminder, str) and reminder else None


__all__ = [
    "MAX_PARAMS_DISPLAY_CHARS",
    "REPEAT_REMINDER_THRESHOLDS",
    "canonical_tool_identity",
    "observe_tool_call",
    "pending_reminder",
    "reminder_for_streak",
]
