from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.channel_runtime import ResidentChannelSupervisor
from zn_agent.core.health_observation import ResidentHealthJournal
from zn_agent.core.store import KernelStore


class _Resident:
    def __init__(self, store_path: Path):
        self.store = KernelStore(store_path)


class _CheckpointAdapter:
    def __init__(self, name: str, *, fail_restore: bool = False):
        self.name = name
        self.fail_restore = fail_restore
        self.restored = []
        self.poll_calls = 0
        self.closed = 0

    def restore_checkpoint(self, checkpoint):
        self.restored.append(dict(checkpoint))
        if self.fail_restore:
            raise ValueError(f"{self.name} checkpoint rejected")

    def poll(self, *, timeout=0.0):
        self.poll_calls += 1
        return []

    def send(self, message):  # pragma: no cover - not used here
        raise AssertionError("send should not be called")

    def close(self):
        self.closed += 1


class _Adapter:
    name = "telegram"

    def __init__(self):
        self.closed = 0

    def poll(self, *, timeout=0.0):
        return []

    def send(self, message):  # pragma: no cover - not used here
        raise AssertionError("send should not be called")

    def close(self):
        self.closed += 1


class _StuckThread:
    def __init__(self):
        self.alive = True
        self.join_calls = []

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        self.join_calls.append(timeout)


class ResidentChannelLifecycleHealthTests(unittest.TestCase):
    def test_checkpoint_restore_failure_is_durable_and_no_channel_starts_partially(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = _Resident(db)
            try:
                first = _CheckpointAdapter("first")
                second = _CheckpointAdapter("second", fail_restore=True)
                supervisor = ResidentChannelSupervisor(
                    resident,
                    [first, second],
                    poll_timeout=0.0,
                )
                supervisor.ledger.save_checkpoint("first", {"cursor": 1})
                supervisor.ledger.save_checkpoint("second", {"cursor": 2})

                with self.assertRaisesRegex(ValueError, "second checkpoint rejected"):
                    supervisor.start()

                self.assertEqual(first.restored, [{"cursor": 1}])
                self.assertEqual(second.restored, [{"cursor": 2}])
                self.assertEqual(supervisor._threads, {})
                self.assertEqual(first.poll_calls, 0)
                self.assertEqual(second.poll_calls, 0)

                health = supervisor.health.get("channel:second")
                self.assertIsNotNone(health)
                self.assertFalse(health["healthy"])
                self.assertEqual(health["consecutive_failures"], 1)
                self.assertEqual(health["last_failure_class"], "configuration_or_input")
            finally:
                resident.store.close()

            reopened = ResidentHealthJournal(type("Store", (), {"path": db})())
            durable = reopened.get("channel:second")
            self.assertIsNotNone(durable)
            self.assertEqual(durable["total_failures"], 1)
            self.assertEqual(durable["last_failure_class"], "configuration_or_input")

    def test_stuck_shutdown_worker_records_fail_closed_durable_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = _Resident(db)
            try:
                adapter = _Adapter()
                supervisor = ResidentChannelSupervisor(
                    resident,
                    [adapter],
                    poll_timeout=0.0,
                )
                stuck = _StuckThread()
                supervisor._threads["telegram"] = stuck
                supervisor._states["telegram"].running = True

                supervisor.stop()

                self.assertEqual(adapter.closed, 1)
                self.assertEqual(len(stuck.join_calls), 1)
                self.assertIs(supervisor._threads["telegram"], stuck)
                state = supervisor.status()[0]
                self.assertTrue(state["running"])
                self.assertIn("worker remains owned", state["last_error"])

                health = supervisor.health.get("channel:telegram")
                self.assertIsNotNone(health)
                self.assertFalse(health["healthy"])
                self.assertEqual(health["total_failures"], 1)
                self.assertEqual(health["last_exception_type"], "TimeoutError")
                self.assertEqual(health["last_failure_class"], "network_or_service")
            finally:
                resident.store.close()

            reopened = ResidentHealthJournal(type("Store", (), {"path": db})())
            durable = reopened.get("channel:telegram")
            self.assertIsNotNone(durable)
            self.assertEqual(durable["total_failures"], 1)
            self.assertEqual(durable["last_failure_class"], "network_or_service")


if __name__ == "__main__":
    unittest.main(verbosity=2)
