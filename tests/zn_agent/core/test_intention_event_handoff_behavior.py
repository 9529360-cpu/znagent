from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.models import AgentEvent
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class IntentionEventHandoffBehaviorTests(unittest.TestCase):
    @staticmethod
    def _resident(db: Path):
        return build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=db,
        )

    def test_same_active_will_step_reuses_one_event_after_crash_before_engage(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = self._resident(db)
            intention = first.intend(
                "keep one durable objective moving",
                priority=7,
                next_task="inspect the current objective state",
                next_payload={"fresh_revalidation_required": True},
            )

            original_engage = first.will.engage

            def crash_after_event_persistence(*args, **kwargs):
                raise RuntimeError("simulated crash before Will engage")

            first.will.engage = crash_after_event_persistence
            try:
                with self.assertRaisesRegex(RuntimeError, "before Will engage"):
                    first._advance_intention(intention.intention_id)
            finally:
                first.will.engage = original_engage

            events = first.store.list_events(limit=20)
            self.assertEqual(len(events), 1)
            first_event = events[0]
            self.assertTrue(first_event.event_id.startswith("evt-will-"))
            self.assertEqual(first_event.priority, 7)
            self.assertEqual(first_event.payload["intention_id"], intention.intention_id)

            still_active = first.will.get(intention.intention_id)
            self.assertIsNotNone(still_active)
            assert still_active is not None
            self.assertEqual(still_active.status, "active")
            self.assertEqual(still_active.next_task, "inspect the current objective state")
            self.assertIsNone(still_active.related_event_id)
            first.store.close()

            restored = self._resident(db)
            restored._advance_intention(intention.intention_id)

            after = restored.store.list_events(limit=20)
            self.assertEqual(len(after), 1)
            self.assertEqual(after[0].event_id, first_event.event_id)
            self.assertEqual(after[0].priority, 7)
            engaged = restored.will.get(intention.intention_id)
            self.assertIsNotNone(engaged)
            assert engaged is not None
            self.assertEqual(engaged.status, "engaged")
            self.assertEqual(engaged.related_event_id, first_event.event_id)
            restored.store.close()

    def test_later_same_text_step_gets_a_new_event_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._resident(db)
            intention = resident.intend(
                "repeat a durable observation when justified",
                next_task="inspect current state",
            )

            resident._advance_intention(intention.intention_id)
            first = resident.will.get(intention.intention_id)
            self.assertIsNotNone(first)
            assert first is not None
            first_event_id = first.related_event_id
            self.assertIsNotNone(first_event_id)

            resident.will.observe_event_outcome(
                intention.intention_id,
                event_id=first_event_id,
                success=True,
                summary="first step completed",
            )
            resident.will.set_next_step(
                intention.intention_id,
                "inspect current state",
            )
            resident._advance_intention(intention.intention_id)

            second = resident.will.get(intention.intention_id)
            self.assertIsNotNone(second)
            assert second is not None
            second_event_id = second.related_event_id
            self.assertIsNotNone(second_event_id)
            self.assertNotEqual(second_event_id, first_event_id)
            self.assertEqual(len(resident.store.list_events(limit=20)), 2)
            resident.store.close()

    def test_existing_same_identity_with_different_contract_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._resident(db)
            intention = resident.intend(
                "preserve the exact Will event contract",
                next_task="inspect exact state",
            )

            original_engage = resident.will.engage
            resident.will.engage = lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("stop after first enqueue")
            )
            try:
                with self.assertRaises(RuntimeError):
                    resident._advance_intention(intention.intention_id)
            finally:
                resident.will.engage = original_engage

            existing = resident.store.list_events(limit=20)[0]
            resident.store.enqueue_event(
                AgentEvent(
                    event_id=existing.event_id,
                    task="different task under the same durable id",
                    kind=existing.kind,
                    priority=existing.priority,
                    payload=dict(existing.payload),
                )
            )

            with self.assertRaisesRegex(RuntimeError, "different contract"):
                resident._advance_intention(intention.intention_id)
            self.assertEqual(len(resident.store.list_events(limit=20)), 1)
            self.assertEqual(
                resident.store.get_event(existing.event_id).task,
                "different task under the same durable id",
            )
            resident.store.close()

    def test_non_will_enqueue_keeps_existing_random_event_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            first = resident.enqueue("ordinary user event", payload={"marker": 1})
            second = resident.enqueue("ordinary user event", payload={"marker": 1})
            self.assertNotEqual(first.event_id, second.event_id)
            self.assertTrue(first.event_id.startswith("evt-"))
            self.assertFalse(first.event_id.startswith("evt-will-"))
            resident.store.close()

    def test_caller_supplied_intention_id_cannot_claim_will_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            intention = resident.intend(
                "real resident intention",
                next_task="real next step",
                source="self",
            )
            forged = resident.enqueue(
                "different caller task",
                kind="user_task",
                payload={
                    "intention_id": intention.intention_id,
                    "intention_description": intention.description,
                    "intention_source": intention.source,
                },
            )
            self.assertFalse(forged.event_id.startswith("evt-will-"))
            self.assertEqual(
                resident.will.get(intention.intention_id).next_task,
                "real next step",
            )
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
