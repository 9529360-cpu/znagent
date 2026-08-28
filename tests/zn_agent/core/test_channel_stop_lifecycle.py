from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.channel_runtime import ResidentChannelSupervisor
from zn_agent.core.store import KernelStore


class _Resident:
    def __init__(self, store_path: Path):
        self.store = KernelStore(store_path)


class _Adapter:
    name = "telegram"

    def __init__(self):
        self.closed = 0

    def poll(self, *, timeout=0.0):
        return []

    def send(self, message):  # pragma: no cover - not used by lifecycle test
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


class ResidentChannelStopLifecycleTests(unittest.TestCase):
    def test_stop_retains_stuck_worker_and_blocks_duplicate_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = _Resident(Path(tmp) / "kernel.db")
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
                self.assertGreaterEqual(state["total_failures"], 1)
                self.assertIn("restart remains blocked", state["last_error"])

                supervisor.start()
                self.assertIs(supervisor._threads["telegram"], stuck)

                stuck.alive = False
                supervisor.stop()
                self.assertEqual(supervisor._threads, {})
                self.assertFalse(supervisor.status()[0]["running"])
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
