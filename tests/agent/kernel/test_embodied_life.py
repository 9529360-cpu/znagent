from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.kernel import CognitiveSituation, EmbodiedLifeCore
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack


class EmbodiedLifeTests(unittest.TestCase):
    def test_situation_forms_investigation_thought_before_resident_enrichment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "evidence.txt"
            target.write_text("world evidence", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            event = resident.enqueue(
                f"read {target}",
                payload={"path": str(target)},
            )

            initial = resident.pulse()
            self.assertIsInstance(resident.life, EmbodiedLifeCore)
            self.assertIsInstance(resident.life.snapshot().current_situation, CognitiveSituation)
            self.assertEqual(initial.thought.action_kind, "event")
            self.assertEqual(initial.thought.action_target, event.event_id)

            # First live cycle only orients the event; it does not run the whole
            # investigation in one hidden loop.
            self.assertIsNone(resident.live_once())
            oriented = resident.pulse()
            situation = resident.life.snapshot().current_situation

            self.assertIsInstance(situation, CognitiveSituation)
            self.assertEqual(situation.working_stage, "native_investigation")
            self.assertEqual(situation.working_event_id, event.event_id)
            self.assertEqual(oriented.thought.action_kind, "investigate")
            self.assertEqual(oriented.thought.action_target, event.event_id)
            self.assertTrue(
                any("current cognition stage" in item for item in oriented.thought.known)
            )

            # One more live cycle performs exactly one body probe (path
            # observation). The next raw pulse must then see that evidence and
            # choose the file-content probe by itself.
            self.assertIsNone(resident.live_once())
            after_probe = resident.pulse()
            situation = resident.life.snapshot().current_situation

            self.assertEqual(situation.investigation_round, 1)
            self.assertGreaterEqual(situation.investigation_evidence_count, 1)
            self.assertEqual(situation.investigation_next_probe, "file_preview")
            self.assertEqual(after_probe.thought.action_kind, "investigate")
            self.assertIn("file_preview", after_probe.thought.chosen_action)
            resident.store.close()

    def test_cognitive_situation_resumes_same_investigation_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            target = root / "resume.txt"
            target.write_text("resume evidence", encoding="utf-8")

            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            event = first.enqueue(
                f"read {target}",
                payload={"path": str(target)},
            )
            self.assertIsNone(first.live_once())  # orient
            self.assertIsNone(first.live_once())  # inspect path
            investigation = first.investigator.current(event.event_id)
            self.assertIsNotNone(investigation)
            investigation_id = investigation.investigation_id
            self.assertEqual(investigation.rounds, 1)
            self.assertEqual(investigation.next_probe, "file_preview")
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            pulse = second.pulse()
            situation = second.life.snapshot().current_situation

            self.assertIsInstance(situation, CognitiveSituation)
            self.assertEqual(situation.active_event_id, event.event_id)
            self.assertEqual(situation.investigation_id, investigation_id)
            self.assertEqual(situation.investigation_round, 1)
            self.assertEqual(situation.investigation_next_probe, "file_preview")
            self.assertEqual(pulse.thought.action_kind, "investigate")
            self.assertIn("file_preview", pulse.thought.chosen_action)

            # Continue the exact unfinished event. Reopening the runtime is not
            # a new conversation/task; the same resident subject resumes the
            # same investigation and reaches its original outcome.
            result = second.live_once()
            self.assertIsNotNone(result)
            self.assertEqual(result.event.event_id, event.event_id)
            self.assertTrue(result.success)
            self.assertEqual(result.response, "resume evidence")
            self.assertEqual(result.model_invocations, 0)

            restored = second.investigator.current(event.event_id)
            self.assertIsNotNone(restored)
            self.assertEqual(restored.investigation_id, investigation_id)
            self.assertEqual(restored.status, "resolved")
            second.store.close()


if __name__ == "__main__":
    unittest.main()
