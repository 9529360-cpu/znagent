from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.channel import ChannelDelivery
from zn_agent.core.channel_runtime import ResidentChannelSupervisor
from zn_agent.core.health_observation import ResidentHealthJournal
from zn_agent.core.store import KernelStore


class _Resident:
    def __init__(self, store: KernelStore):
        self.store = store

    def result_for(self, event_id: str):  # noqa: ARG002
        return None


class _FailThenRecoverChannel:
    name = "test"

    def __init__(self):
        self.polls = 0
        self.supervisor: ResidentChannelSupervisor | None = None

    def poll(self, *, timeout: float = 0.0):  # noqa: ARG002
        self.polls += 1
        if self.polls == 1:
            raise RuntimeError("credential=super-secret-value")
        if self.polls >= 3 and self.supervisor is not None:
            self.supervisor._stop.set()
        return []

    def send(self, message):
        return ChannelDelivery(
            ok=True,
            channel=self.name,
            conversation_id=message.conversation_id,
        )

    def close(self) -> None:
        return None


class ResidentHealthObservationTests(unittest.TestCase):
    def test_health_journal_survives_restart_without_persisting_raw_error(self):
        with tempfile.TemporaryDirectory() as root:
            database = Path(root) / "kernel.db"
            store = KernelStore(database)
            journal = ResidentHealthJournal(store)

            first = journal.record_failure(
                "channel:telegram",
                RuntimeError("token=super-secret-value"),
            )
            second = ResidentHealthJournal(store).record_failure(
                "channel:telegram",
                RuntimeError("token=super-secret-value"),
            )

            self.assertFalse(first["healthy"])
            self.assertEqual(second["total_failures"], 2)
            self.assertEqual(second["consecutive_failures"], 2)
            self.assertEqual(second["last_exception_type"], "RuntimeError")
            self.assertEqual(len(second["last_fingerprint"]), 64)
            self.assertNotIn("super-secret-value", repr(journal.snapshot()))

            recovered = ResidentHealthJournal(store).record_success("channel:telegram")
            self.assertIsNotNone(recovered)
            self.assertTrue(recovered["healthy"])
            self.assertEqual(recovered["total_failures"], 2)
            self.assertEqual(recovered["consecutive_failures"], 0)
            store.close()
            self.assertNotIn(b"super-secret-value", database.read_bytes())

    def test_channel_runtime_records_failure_and_recovery_in_durable_health(self):
        with tempfile.TemporaryDirectory() as root:
            store = KernelStore(Path(root) / "kernel.db")
            adapter = _FailThenRecoverChannel()
            supervisor = ResidentChannelSupervisor(
                _Resident(store),
                (adapter,),
                poll_timeout=0.0,
                min_backoff=0.05,
                max_backoff=0.05,
            )
            adapter.supervisor = supervisor

            supervisor._run_channel(adapter.name, adapter)

            state = ResidentHealthJournal(store).get("channel:test")
            self.assertIsNotNone(state)
            self.assertTrue(state["healthy"])
            self.assertEqual(state["total_failures"], 1)
            self.assertEqual(state["consecutive_failures"], 0)
            self.assertEqual(state["last_exception_type"], "RuntimeError")
            self.assertNotIn("super-secret-value", repr(state))
            store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
