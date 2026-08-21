from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from agent.kernel import EmbodiedInvestigator, NativeBody
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack


class NativeBodyTests(unittest.TestCase):
    def test_normal_resident_has_body_without_registering_a_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )

            self.assertIsInstance(resident.body, NativeBody)
            self.assertIsInstance(resident.investigator, EmbodiedInvestigator)
            self.assertIs(resident.investigator.resident.body, resident.body)
            self.assertEqual(resident.capabilities.names(), ())

            sensed = resident.body.act("sense", event_id="evt-sense")
            self.assertTrue(sensed.success)
            self.assertEqual(sensed.data["pid"], os.getpid())
            self.assertTrue(sensed.data["cwd"])
            self.assertGreater(sensed.data["disk_total_bytes"], 0)
            resident.store.close()

    def test_file_movement_is_body_action_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            target = root / "body" / "note.txt"

            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            written = first.body.act(
                "write_text",
                event_id="evt-body-file",
                path=str(target),
                content="ZN body evidence",
            )
            read = first.body.act(
                "read_text",
                event_id="evt-body-file",
                path=str(target),
            )

            self.assertTrue(written.success)
            self.assertTrue(read.success)
            self.assertEqual(read.output, "ZN body evidence")
            self.assertEqual(first.capabilities.names(), ())
            action_ids = {item.action_id for item in first.body.recent_actions(10)}
            self.assertIn(written.action_id, action_ids)
            self.assertIn(read.action_id, action_ids)
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            restored = second.body.recent_actions(10)
            restored_ids = {item.action_id for item in restored}

            self.assertIn(written.action_id, restored_ids)
            self.assertIn(read.action_id, restored_ids)
            self.assertEqual(second.capabilities.names(), ())
            second.store.close()

    def test_process_observation_is_a_body_movement(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )

            result = resident.body.act(
                "process_state",
                event_id="evt-process",
                pid=os.getpid(),
            )

            self.assertTrue(result.success)
            self.assertTrue(result.data["alive"])
            self.assertEqual(result.data["pid"], os.getpid())
            self.assertEqual(resident.capabilities.names(), ())
            resident.store.close()

    def test_multi_pulse_investigation_uses_body_for_evidence_and_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "evidence.txt"
            target.write_text("evidence from the world", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )

            result = resident.submit(
                f"read {target}",
                payload={"path": str(target)},
            )
            event_actions = [
                item
                for item in reversed(resident.body.recent_actions(20))
                if item.event_id == result.event.event_id
            ]

            self.assertTrue(result.success)
            self.assertEqual(result.output if hasattr(result, "output") else result.response, "evidence from the world")
            self.assertGreaterEqual(len(event_actions), 2)
            self.assertEqual(event_actions[0].kind, "inspect_path")
            self.assertEqual(event_actions[1].kind, "read_text")
            self.assertEqual(resident.capabilities.names(), ())
            self.assertEqual(result.model_invocations, 0)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
