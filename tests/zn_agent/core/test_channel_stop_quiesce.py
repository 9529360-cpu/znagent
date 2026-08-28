from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from zn_agent.core.channel import ChannelEvent
from zn_agent.core.channel_runtime import ResidentChannelSupervisor
from zn_agent.core.event_ingress import stable_external_event_id
from zn_agent.core.store import KernelStore


class _Resident:
    def __init__(self, store_path: Path):
        self.store = KernelStore(store_path)

    def result_for(self, event_id):  # pragma: no cover - no event should reach delivery
        return None


class _LatePollAdapter:
    name = "telegram"

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.checkpoint_calls = 0

    def poll(self, *, timeout=0.0):
        self.entered.set()
        self.release.wait(1.0)
        return [
            ChannelEvent(
                channel="telegram",
                conversation_id="c",
                sender_id="u",
                text="late message",
                message_id="m-late",
                metadata={"update_id": 99, "update_type": "message"},
            )
        ]

    def checkpoint(self):
        self.checkpoint_calls += 1
        return {"offset": 100}

    def send(self, message):  # pragma: no cover - no delivery should happen
        raise AssertionError("send should not be called after stop")

    def close(self):
        return None


class ResidentChannelStopQuiesceTests(unittest.TestCase):
    def test_poll_return_after_stop_does_not_touch_resident_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = _Resident(Path(tmp) / "kernel.db")
            try:
                adapter = _LatePollAdapter()
                supervisor = ResidentChannelSupervisor(
                    resident,
                    [adapter],
                    poll_timeout=0.0,
                )
                supervisor.start()
                self.assertTrue(adapter.entered.wait(1.0))
                worker = supervisor._threads["telegram"]

                # Simulate the stop signal arriving while provider poll is
                # blocked. The worker must quiesce immediately after poll returns
                # and before it can enqueue/checkpoint/deliver resident state.
                supervisor._stop.set()
                adapter.release.set()
                worker.join(timeout=1.0)

                self.assertFalse(worker.is_alive())
                event_id = stable_external_event_id(
                    "channel",
                    "telegram:update:99",
                )
                self.assertIsNone(resident.store.get_event(event_id))
                self.assertEqual(adapter.checkpoint_calls, 0)
                self.assertFalse(supervisor.status()[0]["running"])

                supervisor.stop()
                self.assertEqual(supervisor._threads, {})
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
