from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent.kernel.channel import ChannelDelivery, ChannelEvent
from agent.kernel.channel_runtime import (
    ResidentChannelSupervisor,
    build_zn_channel_adapters,
)


class _Resident:
    def __init__(self):
        self.calls = []

    def submit(self, task, **kwargs):
        self.calls.append((task, kwargs))
        return SimpleNamespace(success=True, response="reply", reason="")


class _FlakyAdapter:
    name = "telegram"

    def __init__(self):
        self.polls = 0
        self.sent = []
        self.closed = False
        self.delivered = threading.Event()

    def poll(self, *, timeout=0.0):
        self.polls += 1
        if self.polls == 1:
            raise RuntimeError("temporary network failure")
        if self.polls == 2:
            return [
                ChannelEvent(
                    channel="telegram",
                    conversation_id="c",
                    sender_id="u",
                    text="hello",
                    message_id="m",
                )
            ]
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


class ResidentChannelSupervisorTests(unittest.TestCase):
    def test_failure_isolated_then_same_resident_recovers(self):
        resident = _Resident()
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
        self.assertGreaterEqual(state["deliveries"], 1)
        self.assertTrue(adapter.closed)
        self.assertFalse(state["running"])

    def test_duplicate_adapter_name_is_rejected(self):
        with self.assertRaises(ValueError):
            ResidentChannelSupervisor(
                _Resident(),
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
            "agent.kernel.telegram_channel.TelegramBotApiChannel.from_zn_config"
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
