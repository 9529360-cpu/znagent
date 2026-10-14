from __future__ import annotations

"""Hook / Watch semantics for ZN (Muse pattern M7, own implementation).

Mechanism copied from Muse's "Hook semantics" pattern (M7); the code below
is written for ZN from scratch -- no Muse code is copied.

Two rules, enforced by code, not just by convention:

1. A Hook is polling, not listening.
   There is no event stream, no subscription, and no background thread.
   A check runs only when someone explicitly calls ``poll()`` / ``poll_all()``,
   and only when its configured interval has elapsed since the previous poll.
   A change is therefore caught at the next poll at the earliest; a change
   that happens and reverses between polls is missed entirely. Never promise
   detection "the moment it happens" -- say "checked every N seconds".

2. A Watch only alerts; it never intercepts.
   A Watch callback observes an action that already happened (or is about to
   happen regardless) and may only produce an alert. Its return value is
   discarded -- there is no veto / block / reject channel, and the caller
   never reads a Watch result. Only the tool on the source service itself
   can reject something.

Both kinds of callbacks are also bounded: a Hook check that fails or
overruns its timeout is recorded as a failed / timed-out run and never
raises into the caller's main loop; a Watch callback that raises is
recorded as a failed alert and never stops the observed action.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .models import utc_now

#: Canonical prompt block stating the Hook / Watch semantics. Agent prompts
#: that schedule checks or watches must include this text verbatim so the
#: model never promises live listening or Watch-based blocking.
HOOK_SEMANTICS_PROMPT = (
    "Hook is polling, not listening: a Hook check runs only when explicitly "
    "polled, at its configured interval -- never continuously, never the "
    "moment something happens. Say 'checked every N seconds', never "
    "'detected the moment it happened'. "
    "Watch only alerts, it never intercepts: a Watch callback observes an "
    "action and may only raise an alert afterward. It cannot reject, block, "
    "or stop the observed action, and its return value is ignored. Only the "
    "tool on the source service itself can reject something."
)

#: Maximum run/alert history retained per Hook / Watch registry.
MAX_HOOK_RUNS = 50
MAX_WATCH_ALERTS = 100

HookCheck = Callable[[], Any]
WatchCallback = Callable[[Mapping[str, Any]], None]


@dataclass(slots=True)
class HookRun:
    """One recorded Hook poll -- the run history is the truth, not the schedule."""

    hook_id: str
    started_at: str
    finished_at: str
    status: str  # succeeded | failed | timed_out
    error: str | None = None
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "hook_id": self.hook_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
        }


@dataclass(slots=True)
class WatchAlert:
    """One recorded Watch delivery. ``status`` is delivery outcome only."""

    watch_id: str
    event: dict[str, Any]
    delivered_at: str
    status: str  # delivered | failed
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "watch_id": self.watch_id,
            "event": dict(self.event),
            "delivered_at": self.delivered_at,
            "status": self.status,
            "error": self.error,
        }


def run_bounded_hook(
    hook_id: str,
    check: HookCheck,
    *,
    timeout_seconds: float,
) -> HookRun:
    """Run one Hook check in a daemon thread with a hard timeout.

    Never raises: failure and timeout are recorded on the returned
    :class:`HookRun` so the caller's main loop is never dragged down by a
    Hook. The check's return value is deliberately discarded -- a Hook
    check observes and reports; it carries no action authority.
    """
    timeout = float(timeout_seconds)
    if timeout <= 0:
        raise ValueError("hook timeout_seconds must be positive")
    started_at = utc_now()
    started_mono = time.monotonic()
    box: dict[str, Any] = {}

    def _target() -> None:
        try:
            box["result"] = check()
        except BaseException as exc:  # recorded, never re-raised here
            box["error"] = exc

    worker = threading.Thread(target=_target, daemon=True)
    worker.start()
    worker.join(timeout)
    duration = time.monotonic() - started_mono
    if worker.is_alive():
        # The worker keeps running in the background (daemon thread: it
        # cannot keep the process alive), but the caller is released.
        return HookRun(
            hook_id=hook_id,
            started_at=started_at,
            finished_at=utc_now(),
            status="timed_out",
            error=f"hook check exceeded timeout_seconds={timeout}",
            duration_seconds=duration,
        )
    if "error" in box:
        exc = box["error"]
        return HookRun(
            hook_id=hook_id,
            started_at=started_at,
            finished_at=utc_now(),
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
            duration_seconds=duration,
        )
    return HookRun(
        hook_id=hook_id,
        started_at=started_at,
        finished_at=utc_now(),
        status="succeeded",
        error=None,
        duration_seconds=duration,
    )


class PollingHook:
    """One polling Hook: explicit poll, configurable interval, bounded run.

    Deliberately there is NO subscribe / on_event / add_listener API and NO
    background thread: registering a Hook starts nothing. The check callable
    is invoked only from :meth:`poll` / :meth:`poll_now`.
    """

    def __init__(
        self,
        hook_id: str,
        check: HookCheck,
        *,
        poll_interval_seconds: float = 60.0,
        timeout_seconds: float = 10.0,
    ) -> None:
        hook_id = str(hook_id or "").strip()
        if not hook_id:
            raise ValueError("hook_id must not be empty")
        if not callable(check):
            raise ValueError("hook check must be callable")
        interval = float(poll_interval_seconds)
        if interval < 0:
            raise ValueError("poll_interval_seconds must not be negative")
        if float(timeout_seconds) <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.hook_id = hook_id
        self._check = check
        self.poll_interval_seconds = interval
        self.timeout_seconds = float(timeout_seconds)
        self._lock = threading.RLock()
        self._last_poll_mono: float | None = None
        self._runs: list[HookRun] = []

    def is_due(self) -> bool:
        """True when the configured interval has elapsed since the last poll."""
        with self._lock:
            if self._last_poll_mono is None:
                return True
            return (
                time.monotonic() - self._last_poll_mono
                >= self.poll_interval_seconds
            )

    def poll(self) -> HookRun | None:
        """Poll once if due; return None (and run nothing) when not due."""
        with self._lock:
            if not self.is_due():
                return None
            return self._poll_locked()

    def poll_now(self) -> HookRun:
        """Poll once regardless of the interval (explicit on-demand run)."""
        with self._lock:
            return self._poll_locked()

    def runs(self) -> list[HookRun]:
        """Recorded runs, oldest first, capped at the latest MAX_HOOK_RUNS."""
        with self._lock:
            return list(self._runs)

    def _poll_locked(self) -> HookRun:
        self._last_poll_mono = time.monotonic()
        run = run_bounded_hook(
            self.hook_id, self._check, timeout_seconds=self.timeout_seconds
        )
        self._runs.append(run)
        del self._runs[: max(0, len(self._runs) - MAX_HOOK_RUNS)]
        return run


class PollingHookRegistry:
    """Explicitly-polled Hooks. No background loop, no listener registration."""

    def __init__(self) -> None:
        self._hooks: dict[str, PollingHook] = {}
        self._lock = threading.RLock()

    def register(self, hook: PollingHook) -> None:
        if not isinstance(hook, PollingHook):
            raise ValueError("only a PollingHook may be registered")
        with self._lock:
            if hook.hook_id in self._hooks:
                raise ValueError(f"hook already registered: {hook.hook_id}")
            self._hooks[hook.hook_id] = hook

    def unregister(self, hook_id: str) -> PollingHook | None:
        with self._lock:
            return self._hooks.pop(str(hook_id or "").strip(), None)

    def hooks(self) -> list[PollingHook]:
        with self._lock:
            return list(self._hooks.values())

    def poll_all(self) -> list[HookRun]:
        """Poll every due Hook. One Hook failing / timing out never stops the rest."""
        runs: list[HookRun] = []
        for hook in self.hooks():
            try:
                run = hook.poll()
            except Exception as exc:  # poll() itself never raises; belt and braces
                run = HookRun(
                    hook_id=hook.hook_id,
                    started_at=utc_now(),
                    finished_at=utc_now(),
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
            if run is not None:
                runs.append(run)
        return runs

    def runs(self) -> list[HookRun]:
        """All recorded runs across Hooks, oldest first."""
        all_runs: list[HookRun] = []
        for hook in self.hooks():
            all_runs.extend(hook.runs())
        return all_runs


class WatchRegistry:
    """Alert-only Watchers. A Watch can never veto, block, or stop an action.

    Callbacks take the event and return ``None``: there is no veto channel
    in the signature, and :meth:`notify` discards any value a callback
    happens to return. :meth:`notify` itself returns ``None`` so callers
    cannot read a Watch result even by accident.
    """

    def __init__(self) -> None:
        self._callbacks: dict[str, WatchCallback] = {}
        self._alerts: list[WatchAlert] = []
        self._lock = threading.RLock()

    def register(self, watch_id: str, callback: WatchCallback) -> None:
        watch_id = str(watch_id or "").strip()
        if not watch_id:
            raise ValueError("watch_id must not be empty")
        if not callable(callback):
            raise ValueError("watch callback must be callable")
        with self._lock:
            if watch_id in self._callbacks:
                raise ValueError(f"watch already registered: {watch_id}")
            self._callbacks[watch_id] = callback

    def unregister(self, watch_id: str) -> WatchCallback | None:
        with self._lock:
            return self._callbacks.pop(str(watch_id or "").strip(), None)

    def watch_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._callbacks)

    def notify(self, event: Mapping[str, Any]) -> None:
        """Deliver an alert to every Watcher. Return value is always None.

        A Watcher returning "block" / "veto" / False is ignored: the return
        value is explicitly discarded. A Watcher raising is recorded as a
        failed alert and never propagates to the observed action.
        """
        snapshot = dict(event or {})
        with self._lock:
            callbacks = list(self._callbacks.items())
        for watch_id, callback in callbacks:
            try:
                # Deliberately discarded: Watch has no veto channel.
                _ = callback(snapshot)
                status, error = "delivered", None
            except Exception as exc:
                status, error = "failed", f"{type(exc).__name__}: {exc}"
            with self._lock:
                self._alerts.append(
                    WatchAlert(
                        watch_id=watch_id,
                        event=dict(snapshot),
                        delivered_at=utc_now(),
                        status=status,
                        error=error,
                    )
                )
                del self._alerts[: max(0, len(self._alerts) - MAX_WATCH_ALERTS)]
        return None

    def alerts(self) -> list[WatchAlert]:
        with self._lock:
            return list(self._alerts)


def run_observed(
    action: Callable[[], Any],
    *,
    watches: WatchRegistry | None = None,
    event: Mapping[str, Any] | None = None,
) -> Any:
    """Run ``action`` to completion, then alert Watchers about what happened.

    The canonical caller pattern proving Watch is alert-only: the action
    runs first and its result is returned untouched. Watchers are notified
    afterward, their return values are discarded (``notify`` returns None),
    and a Watcher failure can never change the action's outcome.
    """
    result = action()
    if watches is not None:
        watches.notify(event or {})
    return result


__all__ = [
    "HOOK_SEMANTICS_PROMPT",
    "MAX_HOOK_RUNS",
    "MAX_WATCH_ALERTS",
    "HookRun",
    "WatchAlert",
    "PollingHook",
    "PollingHookRegistry",
    "WatchRegistry",
    "run_bounded_hook",
    "run_observed",
]
