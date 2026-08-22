from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent.kernel.channel import ChannelDelivery, ChannelEvent
from agent.kernel.channel_runtime import (
    ResidentChannelSupervisor,
    build_zn_channel_adapters,
)


class _Resident:
    def __init__(self, store_path: Path, *, auto_complete: bool = True):
        self.store = SimpleNamespace(path=store_path)
        self.calls = []
        self.outcomes = {}
        self.auto_complete = auto_complete

    def enqueue(self, task, **kwargs):
        event_id = f"evt-test-{len(self.calls) + 1}"
        self.calls.append((task, kwargs, event_id))
        if self.auto_complete:
            self.outcomes[event_id] = SimpleNamespace(
                success=True,
                response="reply",
                reason="",
            )
        return SimpleNamespace(event_id=event_id)

    def result_for(self, event_id):
        return self.outcomes.get(event_id)


class _FlakyAdapter:
    name = "telegram"

    def __init__(self):
        self.polls = 0
        self.sent = []
        self.closed = False
        self.delivered = threading.Event()

    @staticmethod
    def event():
        return ChannelEvent(
            channel="telegram",
            conversation_id="c",
            sender_id="u",
            text="hello",
            message_id="m",
            metadata={"update_id": 42, "update_type": "message"},
        )

    def poll(self, *, timeout=0.0):
        self.polls += 1
        if self.polls == 1:
            raise RuntimeError("temporary network failure")
        if self.polls == 2:
            return [self.event()]
        time.sleep(min(0.01, timeout))
        return []

    def send(self, message):
        self.sent.append(message)
        self.delivered.set()
        return ChannelDelivery(
            True,
            "telegram",
            message.conversation_id,
            ("out",),
        )

    def close(self):
        self.closed = True


class _ReplayAdapter:
    name = "telegram"

    def __init__(self, *, replay: bool):
        self.replay = replay
        self.polled = False
        self.sent = []
        self.closed = False
        self.delivered = threading.Event()
        self.offset = 0
        self.restored = []

    def checkpoint(self):
        return {"offset": self.offset}

    def restore_checkpoint(self, checkpoint):
        self.restored.append(dict(checkpoint))
        self.offset = max(self.offset, int(checkpoint.get("offset") or 0))

    def poll(self, *, timeout=0.0):
        if not self.polled:
            self.polled = True
            if self.replay:
                self.offset = max(self.offset, 43)
                return [_FlakyAdapter.event()]
            return []
        time.sleep(min(0.01, timeout))
        return []

    def send(self, message):
        self.sent.append(message)
        self.delivered.set()
        return ChannelDelivery(
            True,
            "telegram",
            message.conversation_id,
            ("out-restart",),
        )

    def close(self):
        self.closed = True


class ResidentChannelSupervisorTests(unittest.TestCase):
    def test_failure_isolated_then_same_resident_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = _Resident(Path(tmp) / "kernel.db")
            adapter = _FlakyAdapter()
            supervisor = ResidentChannelSupervisor(
                resident,
                [adapter],
                poll_timeout=0.01,
                min_backoff=0.01,
                max_backoff=0.02,
            )

            supervisor.start()
            self.assertTrue(adapter.delivered.wait(1.0))
            supervisor.stop()

            self.assertEqual([call[0] for call in resident.calls], ["hello"])
            self.assertEqual(adapter.sent[0].text, "reply")
            state = supervisor.status()[0]
            self.assertGreaterEqual(state["total_failures"], 1)
            self.assertEqual(state["enqueued"], 1)
            self.assertGreaterEqual(state["deliveries"], 1)
            self.assertTrue(adapter.closed)
            self.assertFalse(state["running"])

    def test_restart_restores_checkpoint_delivers_outcome_and_deduplicates_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = _Resident(store_path, auto_complete=False)
            first = _ReplayAdapter(replay=True)
            first_supervisor = ResidentChannelSupervisor(
                resident,
                [first],
                poll_timeout=0.01,
                min_backoff=0.01,
            )
            first_supervisor.start()

            deadline = time.monotonic() + 1.0
            while len(resident.calls) < 1 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(len(resident.calls), 1)
            event_id = resident.calls[0][2]
            deadline = time.monotonic() + 1.0
            while first_supervisor.ledger.load_checkpoint("telegram") != {"offset": 43} and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(
                first_supervisor.ledger.load_checkpoint("telegram"),
                {"offset": 43},
            )
            first_supervisor.stop()
            self.assertEqual(first.sent, [])

            resident.outcomes[event_id] = SimpleNamespace(
                success=True,
                response="completed after restart",
                reason="",
            )
            second = _ReplayAdapter(replay=True)
            second_supervisor = ResidentChannelSupervisor(
                resident,
                [second],
                poll_timeout=0.01,
                min_backoff=0.01,
            )
            second_supervisor.start()
            self.assertTrue(second.delivered.wait(1.0))
            time.sleep(0.05)
            second_supervisor.stop()

            self.assertEqual(second.restored[0], {"offset": 43})
            self.assertEqual(len(resident.calls), 1)
            self.assertEqual(second.sent[0].text, "completed after restart")
            route = second_supervisor.ledger.route_for_event(event_id)
            self.assertIsNotNone(route)
            self.assertEqual(route.status, "delivered")
            self.assertGreaterEqual(
                second_supervisor.status()[0]["duplicate_percepts"],
                1,
            )

    def test_duplicate_adapter_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = _Resident(Path(tmp) / "kernel.db")
            with self.assertRaises(ValueError):
                ResidentChannelSupervisor(
                    resident,
                    [_FlakyAdapter(), _FlakyAdapter()],
                )

    def test_channel_requires_explicit_enable(self):
        self.assertEqual(
            build_zn_channel_adapters(
                {"channels": {"telegram": {}}},
                environ={},
            ),
            (),
        )

        with patch(
            "agent.kernel.telegram_resident_channel.ResidentTelegramBotApiChannel.from_zn_config"
        ) as build:
            marker = _FlakyAdapter()
            build.return_value = marker
            adapters = build_zn_channel_adapters(
                {"channels": {"telegram": {"enabled": True}}},
                environ={"TELEGRAM_BOT_TOKEN": "token"},
            )

        self.assertEqual(adapters, (marker,))
        build.assert_called_once()


if __name__ == "__main__":
    unittest.main()
