from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.channel import ChannelDelivery, ChannelEvent
from zn_agent.core.channel_runtime import (
    ResidentChannelSupervisor,
    build_zn_channel_adapters,
)
from zn_agent.core.event_ingress import stable_external_event_id
from zn_agent.core.store import KernelStore


class _Resident:
    def __init__(self, store_path: Path, *, auto_complete: bool = True):
        self.store = KernelStore(store_path)
        self.outcomes = {}
        self.auto_complete = auto_complete

    def result_for(self, event_id):
        if event_id in self.outcomes:
            return self.outcomes[event_id]
        if self.auto_complete and self.store.get_event(event_id) is not None:
            return SimpleNamespace(success=True, response="reply", reason="")
        return None


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


class _RollbackAdapter:
    name = "telegram"

    def __init__(self):
        self.offset = 0
        self.polls = 0
        self.restored = []
        self.sent = []
        self.delivered = threading.Event()
        self.closed = False

    def checkpoint(self):
        return {"offset": self.offset}

    def restore_checkpoint(self, checkpoint):
        payload = dict(checkpoint)
        self.restored.append(payload)
        self.offset = int(payload.get("offset") or 0)

    def poll(self, *, timeout=0.0):
        self.polls += 1
        if self.offset < 43:
            self.offset = 43
            return [_FlakyAdapter.event()]
        time.sleep(min(0.01, timeout))
        return []

    def send(self, message):
        self.sent.append(message)
        self.delivered.set()
        return ChannelDelivery(True, "telegram", message.conversation_id, ("rollback-out",))

    def close(self):
        self.closed = True


class ResidentChannelSupervisorTests(unittest.TestCase):
    def test_failure_isolated_then_same_resident_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = _Resident(Path(tmp) / "kernel.db")
            try:
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

                event_id = stable_external_event_id("channel", "telegram:update:42")
                event = resident.store.get_event(event_id)
                self.assertIsNotNone(event)
                self.assertEqual(event.task, "hello")
                self.assertEqual(event.payload["channel"], "telegram")
                self.assertEqual(adapter.sent[0].text, "reply")
                state = supervisor.status()[0]
                self.assertGreaterEqual(state["total_failures"], 1)
                self.assertEqual(state["enqueued"], 1)
                self.assertGreaterEqual(state["deliveries"], 1)
                self.assertTrue(adapter.closed)
                self.assertFalse(state["running"])
            finally:
                resident.store.close()

    def test_ingress_failure_restores_poll_cursor_and_replays_without_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = _Resident(Path(tmp) / "kernel.db")
            try:
                adapter = _RollbackAdapter()
                supervisor = ResidentChannelSupervisor(
                    resident,
                    [adapter],
                    poll_timeout=0.01,
                    min_backoff=0.01,
                    max_backoff=0.02,
                )
                original = supervisor.work.start_external
                attempts = 0

                def fail_once(*args, **kwargs):
                    nonlocal attempts
                    attempts += 1
                    if attempts == 1:
                        raise RuntimeError("synthetic Work ingress failure")
                    return original(*args, **kwargs)

                supervisor.work.start_external = fail_once
                supervisor.start()
                self.assertTrue(adapter.delivered.wait(1.0))
                supervisor.stop()

                self.assertGreaterEqual(adapter.polls, 2)
                self.assertIn({"offset": 0}, adapter.restored)
                self.assertEqual(
                    supervisor.ledger.load_checkpoint("telegram"),
                    {"offset": 43},
                )
                event_id = stable_external_event_id(
                    "channel", "telegram:update:42"
                )
                events = resident.store.list_events(limit=20)
                self.assertEqual(
                    [item.event_id for item in events].count(event_id),
                    1,
                )
                self.assertEqual(len(adapter.sent), 1)
            finally:
                resident.store.close()

    def test_restart_restores_checkpoint_delivers_outcome_and_deduplicates_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            resident = _Resident(store_path, auto_complete=False)
            try:
                first = _ReplayAdapter(replay=True)
                first_supervisor = ResidentChannelSupervisor(
                    resident,
                    [first],
                    poll_timeout=0.01,
                    min_backoff=0.01,
                )
                first_supervisor.start()

                event_id = stable_external_event_id("channel", "telegram:update:42")
                deadline = time.monotonic() + 1.0
                while resident.store.get_event(event_id) is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertIsNotNone(resident.store.get_event(event_id))
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
                self.assertEqual(second.sent[0].text, "completed after restart")
                route = second_supervisor.ledger.route_for_event(event_id)
                self.assertIsNotNone(route)
                self.assertEqual(route.status, "delivered")
                self.assertGreaterEqual(
                    second_supervisor.status()[0]["duplicate_percepts"],
                    1,
                )
                events = resident.store.list_events(limit=10)
                self.assertEqual([item.event_id for item in events].count(event_id), 1)
            finally:
                resident.store.close()

    def test_duplicate_adapter_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = _Resident(Path(tmp) / "kernel.db")
            try:
                with self.assertRaises(ValueError):
                    ResidentChannelSupervisor(
                        resident,
                        [_FlakyAdapter(), _FlakyAdapter()],
                    )
            finally:
                resident.store.close()

    def test_resident_media_nomination_survives_restart_and_reaches_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "kernel.db"
            media_path = Path(tmp) / "artifact.txt"
            media_path.write_text("resident output", encoding="utf-8")
            resident = _Resident(store_path, auto_complete=False)
            try:
                first = _ReplayAdapter(replay=True)
                first_supervisor = ResidentChannelSupervisor(
                    resident,
                    [first],
                    poll_timeout=0.01,
                    min_backoff=0.01,
                )
                first_supervisor.start()
                event_id = stable_external_event_id("channel", "telegram:update:42")
                deadline = time.monotonic() + 1.0
                while resident.store.get_event(event_id) is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertIsNotNone(resident.store.get_event(event_id))
                while (
                    first_supervisor.ledger.route_for_event(event_id) is None
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.01)
                self.assertIsNotNone(first_supervisor.ledger.route_for_event(event_id))
                nomination = first_supervisor.nominate_outbound_media(
                    event_id,
                    str(media_path.resolve()),
                    file_name="answer.txt",
                    mime_type="text/plain",
                    metadata={"resident_reason": "deliver verified result"},
                )
                first_supervisor.stop()

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
                second_supervisor.stop()

                self.assertEqual(len(second.sent[0].attachments), 1)
                restored = second.sent[0].attachments[0]
                self.assertEqual(restored.nomination_id, nomination.nomination_id)
                self.assertEqual(restored.local_path, str(media_path.resolve()))
                self.assertEqual(restored.file_name, "answer.txt")
                self.assertEqual(restored.metadata["resident_reason"], "deliver verified result")
                self.assertEqual(
                    second_supervisor.ledger.route_for_event(event_id).status,
                    "delivered",
                )
            finally:
                resident.store.close()

    def test_media_nomination_rejects_non_channel_and_delivered_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = _Resident(Path(tmp) / "kernel.db")
            try:
                supervisor = ResidentChannelSupervisor(resident, [])
                ordinary = resident.store.get_event("missing")
                self.assertIsNone(ordinary)
                with self.assertRaisesRegex(ValueError, "resident channel event"):
                    supervisor.nominate_outbound_media("missing", str(Path(tmp) / "x"))

                event = _FlakyAdapter.event()
                supervisor._ingest_events([event])
                event_id = stable_external_event_id("channel", "telegram:update:42")
                supervisor.ledger.mark_delivered(event_id)
                with self.assertRaisesRegex(ValueError, "pending channel route"):
                    supervisor.nominate_outbound_media(event_id, str(Path(tmp) / "x"))
            finally:
                resident.store.close()

    def test_response_text_that_mentions_a_path_never_becomes_upload_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = _Resident(Path(tmp) / "kernel.db", auto_complete=False)
            try:
                adapter = _ReplayAdapter(replay=True)
                supervisor = ResidentChannelSupervisor(
                    resident,
                    [adapter],
                    poll_timeout=0.01,
                    min_backoff=0.01,
                )
                supervisor.start()
                event_id = stable_external_event_id("channel", "telegram:update:42")
                deadline = time.monotonic() + 1.0
                while (
                    supervisor.ledger.route_for_event(event_id) is None
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.01)
                resident.outcomes[event_id] = SimpleNamespace(
                    success=True,
                    response=f"result is at {Path(tmp) / 'private.txt'}",
                    reason="",
                )
                self.assertTrue(adapter.delivered.wait(1.0))
                supervisor.stop()

                self.assertEqual(adapter.sent[0].attachments, ())
            finally:
                resident.store.close()

    def test_media_nominations_are_bounded_and_metadata_must_be_json_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = _Resident(Path(tmp) / "kernel.db")
            try:
                supervisor = ResidentChannelSupervisor(resident, [])
                supervisor._ingest_events([_FlakyAdapter.event()])
                event_id = stable_external_event_id("channel", "telegram:update:42")
                for index in range(8):
                    supervisor.nominate_outbound_media(
                        event_id,
                        str(Path(tmp) / f"artifact-{index}.bin"),
                    )
                with self.assertRaisesRegex(ValueError, "nomination limit"):
                    supervisor.nominate_outbound_media(
                        event_id,
                        str(Path(tmp) / "artifact-9.bin"),
                    )
                with self.assertRaisesRegex(ValueError, "JSON-safe"):
                    supervisor.ledger.nominate_media(
                        event_id,
                        str(Path(tmp) / "artifact-0.bin"),
                        kind="replacement-kind",
                        metadata={"not_json": object()},
                    )
            finally:
                resident.store.close()

    def test_channel_requires_explicit_enable(self):
        self.assertEqual(
            build_zn_channel_adapters(
                {"channels": {"telegram": {}}},
                environ={},
            ),
            (),
        )

        with patch(
            "zn_agent.core.telegram_resident_channel.ResidentTelegramBotApiChannel.from_zn_config"
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
