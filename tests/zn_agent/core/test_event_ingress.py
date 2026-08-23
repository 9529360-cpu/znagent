from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.event_ingress import enqueue_event_once, stable_external_event_id
from zn_agent.core.store import KernelStore


class EventIngressTests(unittest.TestCase):
    def test_stable_external_event_id_is_deterministic_and_namespaced(self):
        one = stable_external_event_id("channel", "telegram:update:42")
        two = stable_external_event_id("channel", "telegram:update:42")
        other = stable_external_event_id("world", "telegram:update:42")
        self.assertEqual(one, two)
        self.assertNotEqual(one, other)
        self.assertTrue(one.startswith("evt-channel-"))

    def test_existing_event_is_never_replaced_or_requeued(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            resident = SimpleNamespace(store=store)
            try:
                event_id = stable_external_event_id("channel", "telegram:update:42")
                first = enqueue_event_once(
                    resident,
                    event_id=event_id,
                    task="original percept",
                    kind="channel_message",
                    payload={"version": 1},
                )
                second = enqueue_event_once(
                    resident,
                    event_id=event_id,
                    task="replayed but changed text",
                    kind="channel_message",
                    payload={"version": 2},
                )

                self.assertTrue(first.created)
                self.assertFalse(second.created)
                stored = store.get_event(event_id)
                self.assertIsNotNone(stored)
                self.assertEqual(stored.task, "original percept")
                self.assertEqual(stored.payload, {"version": 1})
                self.assertEqual(
                    [item.event_id for item in store.list_events(limit=10)].count(event_id),
                    1,
                )
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
