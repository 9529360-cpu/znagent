from __future__ import annotations

import unittest
from types import SimpleNamespace

from agent.kernel.channel import (
    ChannelDelivery,
    ChannelEvent,
    ResidentChannelService,
)


class _Adapter:
    name = "test"

    def __init__(self):
        self.sent = []
        self.closed = False

    def poll(self, *, timeout=0.0):
        return [
            ChannelEvent(
                channel="test",
                conversation_id="c1",
                sender_id="u1",
                text="do work",
                message_id="m1",
                thread_id="t1",
            )
        ]

    def send(self, message):
        self.sent.append(message)
        return ChannelDelivery(True, "test", message.conversation_id, ("out1",))

    def close(self):
        self.closed = True


class _Resident:
    def __init__(self):
        self.calls = []

    def submit(self, task, **kwargs):
        self.calls.append((task, kwargs))
        return SimpleNamespace(success=True, response="resident reply", reason="")


class ResidentChannelServiceTests(unittest.TestCase):
    def test_channel_is_io_for_same_resident_not_separate_agent(self):
        resident = _Resident()
        adapter = _Adapter()
        service = ResidentChannelService(resident, adapter)
        deliveries = service.run_once()

        self.assertEqual(len(resident.calls), 1)
        task, kwargs = resident.calls[0]
        self.assertEqual(task, "do work")
        self.assertEqual(kwargs["kind"], "channel_message")
        self.assertEqual(kwargs["payload"]["channel"], "test")
        self.assertEqual(adapter.sent[0].thread_id, "t1")
        self.assertEqual(adapter.sent[0].reply_to_message_id, "m1")
        self.assertEqual(adapter.sent[0].text, "resident reply")
        self.assertTrue(deliveries[0].ok)


if __name__ == "__main__":
    unittest.main()
