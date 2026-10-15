from __future__ import annotations

"""Async capture discipline tests (CM-2).

Proves the code constraints, not just the documentation:
- Hook is thin, pure, never blocking, never non-zero exit: every input
  (including garbage and an unwritable spool) returns 0, never raises.
- Spool is durable append-only JSONL with a cursor the worker owns.
- Worker applies the full filter chain: self-loop first, then sub-agent,
  then skip list, then supervisor/decision eligibility.
- Sink failure stops the run without losing the entry (cursor stays).
"""

import json
import tempfile
import threading
import time
import unittest

from zn_agent.core.async_capture import (
    CAPTURE_MARKER,
    CaptureConfig,
    CaptureHook,
    CaptureWorker,
    Spool,
    WorkerResult,
    capture_event,
    classify,
    is_eligible,
    is_memory_origin,
    is_skipped,
    is_subagent_observation,
    sanitize_event,
)


def _decision(**overrides):
    event = {
        "event_id": "evt-1",
        "kind": "decision",
        "source": "supervisor",
        "actor_role": "supervisor",
        "payload": {"note": "approve rollout"},
    }
    event.update(overrides)
    return event


class HookNeverFailsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.spool = Spool(self._tmp.name)
        self.hook = CaptureHook(self.spool)

    def tearDown(self):
        self._tmp.cleanup()

    def test_capture_never_raises_and_never_nonzero(self):
        bad_inputs = [None, "junk", 123, [], {}, {"kind": ""}, {"kind": "decision", "payload": object()}]
        for bad in bad_inputs:
            with self.subTest(bad=repr(bad)[:40]):
                self.assertEqual(self.hook.capture(bad), 0)
                self.assertEqual(capture_event(self.spool, bad), 0)

    def test_capture_with_unwritable_spool_returns_zero(self):
        # Spool directory is a file: every append fails, hook still returns 0.
        with tempfile.NamedTemporaryFile() as blocker:
            hook = CaptureHook(Spool(blocker.name))
            self.assertEqual(hook.capture(_decision()), 0)

    def test_hook_returns_zero_for_dropped_events(self):
        dropped = [
            _decision(kind="heartbeat"),
            _decision(kind="tool_call"),
            _decision(actor_role="subagent"),
            _decision(source="subagent"),
            _decision(tool_name="memory_write"),
            _decision(source="memory_capture"),
            {**_decision(), "capture_origin": CAPTURE_MARKER},
        ]
        for event in dropped:
            with self.subTest(event=event.get("kind"), role=event.get("actor_role")):
                self.assertEqual(self.hook.capture(event), 0)
        self.assertEqual(self.spool.pending(), [])


class HookSpoolTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.spool = Spool(self._tmp.name)
        self.hook = CaptureHook(self.spool)

    def tearDown(self):
        self._tmp.cleanup()

    def test_spooled_line_carries_marker_and_event_id(self):
        self.assertEqual(self.hook.capture(_decision()), 0)
        pending = self.spool.pending()
        self.assertEqual(len(pending), 1)
        _, parsed = pending[0]
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["capture_origin"], CAPTURE_MARKER)
        self.assertEqual(parsed["event_id"], "evt-1")
        self.assertEqual(parsed["payload"], {"note": "approve rollout"})

    def test_hook_generates_event_id_when_missing(self):
        event = _decision()
        del event["event_id"]
        self.hook.capture(event)
        _, parsed = self.spool.pending()[0]
        assert parsed is not None
        self.assertTrue(parsed["event_id"].startswith("evt-"))

    def test_hook_trims_oversized_payload(self):
        big = "x" * 100_000
        self.hook.capture(_decision(payload={"blob": big}))
        with open(f"{self._tmp.name}/spool.jsonl", encoding="utf-8") as handle:
            raw = handle.read()
        self.assertLessEqual(len(raw.encode("utf-8")), 64 * 1024)
        self.assertIn("[truncated]", raw)

    def test_hook_does_not_touch_memory_sink(self):
        # The hook has no sink parameter at all: capture cannot call memory.
        self.assertEqual(self.hook.capture(_decision()), 0)
        self.assertEqual(len(self.spool.pending()), 1)


class ClassifyTests(unittest.TestCase):
    def test_self_loop_beats_decision_kind(self):
        # A memory-tool event that looks decision-class must still drop.
        event = _decision(tool_name="memory_write")
        self.assertTrue(is_memory_origin(event))
        self.assertEqual(classify(event), "drop_self_loop")

    def test_subagent_dropped_even_when_supervisor_kind(self):
        event = _decision(actor_role="subagent")
        self.assertTrue(is_subagent_observation(event))
        self.assertEqual(classify(event), "drop_subagent")

    def test_skip_list(self):
        self.assertTrue(is_skipped({"kind": "tool_call"}))
        self.assertTrue(is_skipped({"kind": "heartbeat"}))
        self.assertFalse(is_skipped({"kind": "decision"}))
        self.assertEqual(classify(_decision(kind="tool_call")), "drop_skip")

    def test_eligibility_supervisor_vs_worker(self):
        # Supervisor "note" qualifies; the same kind from a worker does not.
        self.assertTrue(is_eligible({"kind": "note", "actor_role": "supervisor"}))
        self.assertFalse(is_eligible({"kind": "note", "actor_role": "worker"}))
        self.assertEqual(classify(_decision(kind="note", actor_role="worker")), "drop_ineligible")
        self.assertEqual(classify(_decision(kind="note", actor_role="supervisor")), "keep")
        self.assertEqual(classify(_decision()), "keep")

    def test_sanitize_rejects_non_mapping_and_missing_kind(self):
        with self.assertRaises(TypeError):
            sanitize_event("junk")
        with self.assertRaises(ValueError):
            sanitize_event({"kind": "  "})


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.spool = Spool(self._tmp.name)
        self.hook = CaptureHook(self.spool)
        self.worker = CaptureWorker(self.spool)
        self.sink_calls: list[dict] = []

    def tearDown(self):
        self._tmp.cleanup()

    def _sink(self, event):
        self.sink_calls.append(event)

    def test_worker_keeps_decision_events_and_advances_cursor(self):
        self.hook.capture(_decision(event_id="evt-keep"))
        self.hook.capture(_decision(event_id="evt-drop", kind="heartbeat"))
        result = self.worker.run_once(self._sink)
        self.assertIsInstance(result, WorkerResult)
        self.assertEqual(result.kept, 1)
        self.assertEqual(result.dropped, {})
        self.assertEqual([c["event_id"] for c in self.sink_calls], ["evt-keep"])
        # Second run is a no-op: cursor advanced past everything.
        again = self.worker.run_once(self._sink)
        self.assertEqual(again.processed, 0)
        self.assertEqual(len(self.sink_calls), 1)

    def test_worker_drop_reasons_counted(self):
        self.hook.capture(_decision(event_id="e1", kind="decision"))
        # Bypass the hook to place entries the hook would drop: the worker
        # must re-apply the full chain to spool entries from any producer.
        self.spool.append({"event_id": "e2", "kind": "tool_call", "payload": {}})
        self.spool.append(
            {"event_id": "e3", "kind": "decision", "actor_role": "subagent", "payload": {}}
        )
        self.spool.append(
            {"event_id": "e4", "kind": "decision", "tool_name": "memory_write", "payload": {}}
        )
        self.spool.append({"event_id": "e5", "kind": "note", "actor_role": "worker", "payload": {}})
        result = self.worker.run_once(self._sink)
        self.assertEqual(result.kept, 1)
        self.assertEqual(
            result.dropped,
            {
                "drop_skip": 1,
                "drop_subagent": 1,
                "drop_self_loop": 1,
                "drop_ineligible": 1,
            },
        )
        self.assertEqual([c["event_id"] for c in self.sink_calls], ["e1"])

    def test_worker_skips_malformed_and_torn_lines(self):
        self.hook.capture(_decision(event_id="good"))
        with open(f"{self._tmp.name}/spool.jsonl", "a", encoding="utf-8") as handle:
            handle.write('{"event_id": "torn", "kind": "decis\n')  # torn last line
            handle.write("not json at all\n")
        result = self.worker.run_once(self._sink)
        self.assertEqual(result.kept, 1)
        self.assertEqual(result.dropped.get("drop_malformed"), 2)
        self.assertEqual([c["event_id"] for c in self.sink_calls], ["good"])

    def test_sink_failure_stops_run_and_retries_next_run(self):
        self.hook.capture(_decision(event_id="bad"))
        self.hook.capture(_decision(event_id="later"))
        attempts: list[str] = []

        def flaky_sink(event):
            attempts.append(event["event_id"])
            if event["event_id"] == "bad" and len(attempts) == 1:
                raise RuntimeError("memory temporarily down")

        result = self.worker.run_once(flaky_sink)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.kept, 0)
        # Cursor stayed before the failed entry: "later" was not reached.
        self.assertEqual(attempts, ["bad"])
        # Next run retries the failed entry, then continues.
        result2 = self.worker.run_once(self._sink)
        self.assertEqual(result2.kept, 2)
        self.assertEqual([c["event_id"] for c in self.sink_calls], ["bad", "later"])

    def test_corrupt_cursor_replays_from_zero(self):
        self.hook.capture(_decision(event_id="evt-1"))
        with open(f"{self._tmp.name}/spool.cursor", "w", encoding="utf-8") as handle:
            handle.write("garbage")
        result = self.worker.run_once(self._sink)
        self.assertEqual(result.kept, 1)


class BackgroundWorkerTests(unittest.TestCase):
    def test_start_background_drains_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            spool = Spool(tmp)
            worker = CaptureWorker(spool)
            seen: list[dict] = []
            thread, stop_event = worker.start_background(
                seen.append, interval_seconds=0.05
            )
            try:
                CaptureHook(spool).capture(_decision(event_id="bg-1"))
                deadline = time.monotonic() + 5.0
                while not seen and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertEqual([c["event_id"] for c in seen], ["bg-1"])
            finally:
                stop_event.set()
                thread.join(timeout=5.0)
            self.assertFalse(thread.is_alive())

    def test_background_worker_survives_sink_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            spool = Spool(tmp)
            worker = CaptureWorker(spool)
            calls: list[str] = []

            def sink(event):
                calls.append(event["event_id"])
                raise RuntimeError("boom")

            thread, stop_event = worker.start_background(sink, interval_seconds=0.05)
            try:
                CaptureHook(spool).capture(_decision(event_id="bg-bad"))
                time.sleep(0.5)
                self.assertTrue(thread.is_alive())
                # Worker kept retrying (at least one attempt), never died.
                self.assertGreaterEqual(len(calls), 1)
            finally:
                stop_event.set()
                thread.join(timeout=5.0)
            self.assertFalse(thread.is_alive())


class ConfigOverrideTests(unittest.TestCase):
    def test_custom_skip_and_decision_kinds(self):
        config = CaptureConfig(
            skip_kinds=frozenset({"custom_noise"}),
            decision_kinds=frozenset({"custom_decision"}),
        )
        # Default config does not know custom_noise: ineligible, not skipped.
        self.assertEqual(
            classify({"kind": "custom_noise"}), "drop_ineligible"
        )
        self.assertEqual(
            classify({"kind": "custom_noise"}, config=config), "drop_skip"
        )
        # Default config does not know custom_decision; custom config keeps it.
        self.assertEqual(
            classify({"kind": "custom_decision", "actor_role": "worker"}),
            "drop_ineligible",
        )
        self.assertEqual(
            classify({"kind": "custom_decision", "actor_role": "worker"}, config=config),
            "keep",
        )


if __name__ == "__main__":
    unittest.main()
