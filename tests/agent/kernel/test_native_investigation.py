from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from agent.kernel import EventStatus, ExecutionPath
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack


class NativeInvestigationTests(unittest.TestCase):
    def test_resident_answers_its_current_working_directory_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )

            result = resident.submit("what is my current working directory?")
            investigations = resident.investigator.recent(1)

            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.INVESTIGATION)
            self.assertEqual(result.response, os.getcwd())
            self.assertEqual(result.model_invocations, 0)
            self.assertIsNone(resident.life.snapshot().current_impasse)
            self.assertEqual(len(investigations), 1)
            self.assertEqual(investigations[0].status, "resolved")
            self.assertEqual(investigations[0].rounds, 1)
            self.assertIn("body", investigations[0].probe_keys)
            resident.store.close()

    def test_resident_checks_a_referenced_path_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "evidence.txt"
            target.write_text("zn", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )

            result = resident.submit(
                f"does {target} exist?",
                payload={"path": str(target)},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.INVESTIGATION)
            self.assertIn("exists", result.response)
            latest = resident.investigator.recent(1)[0]
            self.assertEqual(latest.facts["paths"][0]["exists"], True)
            self.assertEqual(latest.probe_keys, ("paths",))
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_resident_checks_process_state_without_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )

            result = resident.submit(
                f"is pid {os.getpid()} running?",
                payload={"pid": os.getpid()},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.INVESTIGATION)
            self.assertIn("alive", result.response)
            self.assertEqual(result.model_invocations, 0)
            resident.store.close()

    def test_one_live_cycle_advances_only_one_investigation_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            event = resident.enqueue(
                "debug the current project state and explain what is unusual",
                payload={"model_policy": "never"},
            )

            # Pulse 1 only orients and decides that local investigation is next.
            self.assertIsNone(resident.live_once())
            working = resident.store.get_working_state()
            self.assertEqual(working.current_event_id, event.event_id)
            self.assertEqual(working.stage, "native_investigation")
            self.assertIsNone(resident.investigator.current(event.event_id))
            self.assertEqual(resident.store.get_event(event.event_id).status, EventStatus.PROCESSING)

            # Pulse 2 executes exactly one probe and keeps the same active event.
            self.assertIsNone(resident.live_once())
            first_round = resident.investigator.current(event.event_id)
            self.assertIsNotNone(first_round)
            self.assertEqual(first_round.rounds, 1)
            self.assertEqual(len(first_round.probe_keys), 1)
            self.assertEqual(resident.store.peek_next_event().event_id, event.event_id)
            thought = resident.life.recent_thoughts(1)[0]
            self.assertEqual(thought.action_kind, "investigate")

            # Pulse 3 uses the updated evidence and advances another native round.
            self.assertIsNone(resident.live_once())
            second_round = resident.investigator.current(event.event_id)
            self.assertEqual(second_round.rounds, 2)
            self.assertEqual(len(second_round.probe_keys), 2)
            self.assertEqual(resident.store.get_working_state().stage, "native_deliberation")

            # Only after the native probe set is exhausted can policy/model handling occur.
            terminal = resident.live_once()
            self.assertIsNotNone(terminal)
            self.assertFalse(terminal.success)
            self.assertEqual(terminal.execution_path, ExecutionPath.BUDGET_BLOCKED)
            resident.store.close()

    def test_evidence_from_one_round_creates_the_next_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "note.txt"
            target.write_text("evidence becomes the next action", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            event = resident.enqueue(
                f"read the content of {target}",
                payload={"path": str(target), "model_policy": "never"},
            )

            self.assertIsNone(resident.live_once())  # orient
            self.assertIsNone(resident.live_once())  # inspect path metadata
            after_path = resident.investigator.current(event.event_id)
            self.assertEqual(after_path.probe_keys, ("paths",))
            self.assertEqual(after_path.next_probe, "file_preview")

            result = resident.live_once()  # Thought chooses the evidence-derived file probe
            self.assertIsNotNone(result)
            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.INVESTIGATION)
            self.assertEqual(result.response, "evidence becomes the next action")
            final = resident.investigator.current(event.event_id)
            self.assertEqual(final.probe_keys, ("paths", "file_preview"))
            self.assertEqual(final.rounds, 2)
            resident.store.close()

    def test_in_progress_investigation_resumes_next_probe_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            target = root / "resume.txt"
            target.write_text("continue from evidence", encoding="utf-8")

            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            event = first.enqueue(
                f"read the content of {target}",
                payload={"path": str(target), "model_policy": "never"},
            )
            self.assertIsNone(first.live_once())
            self.assertIsNone(first.live_once())
            before = first.investigator.current(event.event_id)
            self.assertEqual(before.probe_keys, ("paths",))
            self.assertEqual(before.next_probe, "file_preview")
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            result = second.live_once()
            self.assertIsNotNone(result)
            self.assertTrue(result.success)
            self.assertEqual(result.response, "continue from evidence")
            restored = second.investigator.current(event.event_id)
            self.assertEqual(restored.investigation_id, before.investigation_id)
            self.assertEqual(restored.probe_keys, ("paths", "file_preview"))
            self.assertEqual(restored.rounds, 2)
            second.store.close()

    def test_unresolved_investigation_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            result = first.submit(
                "diagnose an unfamiliar failure that has no local evidence yet",
                payload={"model_policy": "never"},
            )
            first_investigation = first.investigator.recent(1)[0]

            self.assertFalse(result.success)
            self.assertEqual(first_investigation.status, "open")
            self.assertTrue(first_investigation.unresolved)
            self.assertGreaterEqual(first_investigation.rounds, 1)
            investigation_id = first_investigation.investigation_id
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            restored = second.investigator.recent(1)[0]
            self.assertEqual(restored.investigation_id, investigation_id)
            self.assertEqual(restored.status, "open")
            self.assertTrue(restored.evidence)
            self.assertIsNotNone(second.life.snapshot().current_impasse)
            second.store.close()


if __name__ == "__main__":
    unittest.main()
