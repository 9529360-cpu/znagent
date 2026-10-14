from __future__ import annotations

"""Hook / Watch semantics tests (Muse pattern M7, ZN's own implementation).

Proves the code constraints, not just the documentation:
- Hook is polling, not listening: registering a Hook starts nothing; the
  check runs only on an explicit poll, and only when its interval is due.
- Hook execution never blocks the main flow: a failing or hanging check
  yields a failed / timed-out run record, never an exception, and the
  registry keeps polling the remaining Hooks.
- Watch only alerts, never intercepts: a Watcher returning "block" /
  "veto" / False cannot stop the observed action, and a Watcher raising
  cannot stop it either. Watch has no veto channel to read.
"""

import threading
import time
import unittest

from zn_agent.core.agentic_tool_loop import DEFAULT_SYSTEM_PROMPT
from zn_agent.core.hook_semantics import (
    HOOK_SEMANTICS_PROMPT,
    MAX_HOOK_RUNS,
    HookRun,
    PollingHook,
    PollingHookRegistry,
    WatchRegistry,
    run_bounded_hook,
    run_observed,
)
from zn_agent.core.provider_runtime import (
    CapabilityProviderDescriptor,
    CapabilityProviderRuntime,
    CapabilityProviderStatus,
)


class PollingNotListeningTests(unittest.TestCase):
    def test_registering_a_hook_starts_nothing(self) -> None:
        calls: list[str] = []
        hook = PollingHook("h", lambda: calls.append("ran"), poll_interval_seconds=60)
        registry = PollingHookRegistry()
        registry.register(hook)
        time.sleep(0.2)
        # No background thread, no subscription: nothing ran without a poll.
        self.assertEqual(calls, [])

    def test_poll_before_interval_is_due_runs_nothing(self) -> None:
        calls: list[str] = []
        hook = PollingHook("h", lambda: calls.append("ran"), poll_interval_seconds=60)
        self.assertIsNotNone(hook.poll())
        self.assertEqual(calls, ["ran"])
        # Interval has not elapsed: the second poll is a no-op, not a run.
        self.assertIsNone(hook.poll())
        self.assertEqual(calls, ["ran"])
        self.assertEqual(len(hook.runs()), 1)

    def test_poll_interval_is_configurable_per_hook(self) -> None:
        calls: list[str] = []
        fast = PollingHook(
            "fast", lambda: calls.append("fast"), poll_interval_seconds=0
        )
        slow = PollingHook(
            "slow", lambda: calls.append("slow"), poll_interval_seconds=3600
        )
        registry = PollingHookRegistry()
        registry.register(fast)
        registry.register(slow)
        registry.poll_all()
        registry.poll_all()
        # Always-due hook ran twice; hourly hook ran once.
        self.assertEqual(calls.count("fast"), 2)
        self.assertEqual(calls.count("slow"), 1)

    def test_run_history_is_recorded_and_capped(self) -> None:
        hook = PollingHook("h", lambda: None, poll_interval_seconds=0)
        for _ in range(MAX_HOOK_RUNS + 5):
            run = hook.poll()
            self.assertIsNotNone(run)
            self.assertEqual(run.status, "succeeded")
        runs = hook.runs()
        self.assertEqual(len(runs), MAX_HOOK_RUNS)
        self.assertTrue(all(isinstance(run, HookRun) for run in runs))

    def test_poll_now_runs_even_when_not_due(self) -> None:
        calls: list[str] = []
        hook = PollingHook("h", lambda: calls.append("ran"), poll_interval_seconds=3600)
        hook.poll()
        hook.poll_now()
        self.assertEqual(calls, ["ran", "ran"])

    def test_invalid_hook_config_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            PollingHook("", lambda: None)
        with self.assertRaisesRegex(ValueError, "must not be negative"):
            PollingHook("h", lambda: None, poll_interval_seconds=-1)
        with self.assertRaisesRegex(ValueError, "must be positive"):
            PollingHook("h", lambda: None, timeout_seconds=0)
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry = PollingHookRegistry()
            registry.register(PollingHook("h", lambda: None))
            registry.register(PollingHook("h", lambda: None))


class HookFailureIsolationTests(unittest.TestCase):
    def test_failing_hook_yields_a_failed_run_not_an_exception(self) -> None:
        def boom() -> None:
            raise RuntimeError("check exploded")

        hook = PollingHook("boom", boom, poll_interval_seconds=0)
        run = hook.poll()
        self.assertIsNotNone(run)
        assert run is not None
        self.assertEqual(run.status, "failed")
        self.assertIn("RuntimeError", run.error or "")
        self.assertIn("check exploded", run.error or "")

    def test_hanging_hook_times_out_and_never_blocks_the_caller(self) -> None:
        started = threading.Event()

        def hang_forever() -> None:
            started.set()
            threading.Event().wait(timeout=30)

        started_at = time.monotonic()
        run = run_bounded_hook("hang", hang_forever, timeout_seconds=0.2)
        elapsed = time.monotonic() - started_at
        self.assertEqual(run.status, "timed_out")
        self.assertIn("timeout", run.error or "")
        # Bounded: the caller was released near the timeout, not after 30s.
        self.assertLess(elapsed, 5.0)

    def test_one_bad_hook_does_not_stop_the_rest(self) -> None:
        calls: list[str] = []
        registry = PollingHookRegistry()
        registry.register(
            PollingHook(
                "bad",
                lambda: (_ for _ in ()).throw(RuntimeError("bad")),
                poll_interval_seconds=0,
            )
        )
        registry.register(
            PollingHook("good", lambda: calls.append("good"), poll_interval_seconds=0)
        )
        runs = registry.poll_all()
        self.assertEqual([run.status for run in runs], ["failed", "succeeded"])
        self.assertEqual(calls, ["good"])
        # The main flow after poll_all still runs.
        main_flow_ran = []
        registry.poll_all()
        main_flow_ran.append(True)
        self.assertEqual(main_flow_ran, [True])

    def test_hanging_hook_in_registry_does_not_block_other_hooks(self) -> None:
        calls: list[str] = []
        registry = PollingHookRegistry()
        registry.register(
            PollingHook(
                "hang",
                lambda: threading.Event().wait(timeout=30),
                poll_interval_seconds=0,
                timeout_seconds=0.2,
            )
        )
        registry.register(
            PollingHook("good", lambda: calls.append("good"), poll_interval_seconds=0)
        )
        started_at = time.monotonic()
        runs = registry.poll_all()
        elapsed = time.monotonic() - started_at
        self.assertEqual([run.status for run in runs], ["timed_out", "succeeded"])
        self.assertEqual(calls, ["good"])
        self.assertLess(elapsed, 5.0)


class WatchAlertOnlyTests(unittest.TestCase):
    def test_watch_returning_block_cannot_stop_the_action(self) -> None:
        watchers = WatchRegistry()
        seen: list[dict] = []

        def veto_watcher(event):
            seen.append(dict(event))
            return "block"  # must be discarded: Watch has no veto channel

        watchers.register("veto", veto_watcher)
        result = run_observed(
            lambda: "action-completed",
            watches=watchers,
            event={"kind": "test-action"},
        )
        self.assertEqual(result, "action-completed")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["kind"], "test-action")

    def test_watch_returning_false_or_veto_still_cannot_stop_action(self) -> None:
        for verdict in (False, "veto", {"veto": True}):
            watchers = WatchRegistry()
            watchers.register("w", lambda event, v=verdict: v)
            result = run_observed(lambda: 42, watches=watchers, event={})
            self.assertEqual(result, 42)

    def test_watch_callback_raising_cannot_stop_the_action(self) -> None:
        watchers = WatchRegistry()

        def exploding(event):
            raise RuntimeError("watcher exploded")

        watchers.register("bad", exploding)
        result = run_observed(lambda: "still-ran", watches=watchers, event={})
        self.assertEqual(result, "still-ran")
        alerts = watchers.alerts()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].status, "failed")
        self.assertIn("RuntimeError", alerts[0].error or "")

    def test_notify_returns_none_so_callers_cannot_read_a_watch_result(self) -> None:
        watchers = WatchRegistry()
        watchers.register("w", lambda event: "block")
        self.assertIsNone(watchers.notify({"kind": "x"}))
        # No veto / approval / should-block channel exists on the registry.
        for name in ("veto", "should_block", "approve", "can_proceed", "decide"):
            self.assertFalse(
                hasattr(watchers, name), f"Watch must not expose {name}"
            )

    def test_one_failing_watcher_does_not_silence_the_others(self) -> None:
        watchers = WatchRegistry()
        delivered: list[str] = []
        watchers.register("bad", lambda event: (_ for _ in ()).throw(RuntimeError("bad")))
        watchers.register("good", lambda event: delivered.append("good"))
        watchers.notify({"kind": "x"})
        self.assertEqual(delivered, ["good"])
        self.assertEqual(
            [alert.status for alert in watchers.alerts()], ["failed", "delivered"]
        )


class ProviderLifecycleHookTests(unittest.TestCase):
    @staticmethod
    def _descriptor() -> CapabilityProviderDescriptor:
        return CapabilityProviderDescriptor(
            provider_id="zn.test",
            description="Test provider",
            action_ids=(),
            lifecycle_mode="lazy",
        )

    def test_failing_start_hook_does_not_raise_out_of_activate(self) -> None:
        runtime = CapabilityProviderRuntime()
        state = {"running": False}

        def probe(descriptor):
            return CapabilityProviderStatus(
                descriptor.provider_id,
                "healthy" if state["running"] else "unavailable",
                queryable=bool(state["running"]),
                running=bool(state["running"]),
            )

        def failing_hook(_descriptor):
            raise RuntimeError("start hook exploded")

        runtime.register(
            self._descriptor(), health_probe=probe, start_hook=failing_hook
        )
        # Activate must not raise: the Hook failure is recorded, main flow continues.
        result = runtime.activate("zn.test")
        self.assertFalse(result.queryable)
        runs = runtime.hook_runs()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].status, "failed")
        self.assertIn("start hook exploded", runs[0].error or "")

    def test_hanging_start_hook_times_out_and_activate_returns(self) -> None:
        runtime = CapabilityProviderRuntime(hook_timeout_seconds=0.2)
        state = {"running": False}

        def probe(descriptor):
            return CapabilityProviderStatus(
                descriptor.provider_id,
                "healthy" if state["running"] else "unavailable",
                queryable=bool(state["running"]),
                running=bool(state["running"]),
            )

        runtime.register(
            self._descriptor(),
            health_probe=probe,
            start_hook=lambda _d: threading.Event().wait(timeout=30),
        )
        started_at = time.monotonic()
        result = runtime.activate("zn.test")
        elapsed = time.monotonic() - started_at
        self.assertFalse(result.queryable)
        self.assertLess(elapsed, 5.0)
        self.assertEqual(runtime.hook_runs()[0].status, "timed_out")

    def test_watcher_returning_block_cannot_veto_activation(self) -> None:
        runtime = CapabilityProviderRuntime()
        state = {"running": False}
        seen: list[dict] = []

        def probe(descriptor):
            return CapabilityProviderStatus(
                descriptor.provider_id,
                "healthy" if state["running"] else "unavailable",
                queryable=bool(state["running"]),
                running=bool(state["running"]),
            )

        def mark_running(_descriptor):
            state["running"] = True

        def veto_watcher(event):
            seen.append(dict(event))
            return "block"

        runtime.register(
            self._descriptor(), health_probe=probe, start_hook=mark_running
        )
        runtime.watchers.register("veto", veto_watcher)
        result = runtime.activate("zn.test")
        # The Watcher said "block"; activation still completed.
        self.assertTrue(result.queryable)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["kind"], "provider_activated")
        self.assertEqual(seen[0]["provider_id"], "zn.test")


class HookSemanticsPromptTests(unittest.TestCase):
    def test_prompt_states_polling_not_listening(self) -> None:
        self.assertIn("polling, not listening", HOOK_SEMANTICS_PROMPT)
        self.assertIn("checked every", HOOK_SEMANTICS_PROMPT)
        self.assertIn("the moment", HOOK_SEMANTICS_PROMPT)

    def test_prompt_states_watch_alert_only(self) -> None:
        self.assertIn("Watch only alerts", HOOK_SEMANTICS_PROMPT)
        self.assertIn("cannot reject, block", HOOK_SEMANTICS_PROMPT)
        self.assertIn("return value is ignored", HOOK_SEMANTICS_PROMPT)

    def test_agent_system_prompt_carries_hook_semantics(self) -> None:
        self.assertIn(HOOK_SEMANTICS_PROMPT, DEFAULT_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
