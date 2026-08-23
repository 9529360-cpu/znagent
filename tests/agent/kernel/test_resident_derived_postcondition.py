from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.kernel.action import derive_native_action_intents
from agent.kernel.models import AgentEvent, ExecutionPath
from agent.kernel.provider_bridge import build_resident_runtime


class ResidentDerivedPostconditionTests(unittest.TestCase):
    @staticmethod
    def _run_to_terminal(resident, limit: int = 64):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError("resident did not reach a terminal result")

    def test_complete_current_preview_forms_exact_append_and_replace_choices(self):
        target = "/current/notes.txt"
        event = AgentEvent(
            event_id="evt-derived-append-goal",
            task="append the requested text to the current file",
            payload={
                "path": target,
                "content": "suffix",
                "append": True,
            },
        )
        facts = {
            "paths": [{"path": target, "exists": True, "type": "file"}],
            "file_previews": [
                {
                    "path": target,
                    "preview": "prefix-",
                    "chars": 7,
                    "truncated": False,
                }
            ],
        }

        choices = derive_native_action_intents(event, facts=facts)

        self.assertEqual(len(choices), 2)
        self.assertTrue(all(item.source == "resident_choice" for item in choices))
        self.assertTrue(choices[0].args["append"])
        self.assertFalse(choices[1].args["append"])
        self.assertEqual(choices[1].args["content"], "prefix-suffix")
        self.assertEqual(
            choices[0].expected_outcome,
            {
                "kind": "text_equals",
                "path": target,
                "expected_text": "prefix-suffix",
            },
        )
        self.assertEqual(choices[1].expected_outcome, choices[0].expected_outcome)

    def test_missing_or_truncated_preview_does_not_invent_final_text(self):
        target = "/current/notes.txt"
        event = AgentEvent(
            event_id="evt-derived-append-fail-closed",
            task="append the requested text to the current file",
            payload={"path": target, "content": "suffix", "append": True},
        )
        for facts in (
            {"paths": [{"path": target, "exists": True, "type": "file"}]},
            {
                "paths": [{"path": target, "exists": True, "type": "file"}],
                "file_previews": [
                    {
                        "path": target,
                        "preview": "partial",
                        "chars": 7,
                        "truncated": True,
                    }
                ],
            },
        ):
            with self.subTest(facts=facts):
                choices = derive_native_action_intents(event, facts=facts)
                self.assertEqual(len(choices), 1)
                self.assertTrue(choices[0].args["append"])
                self.assertIsNone(choices[0].expected_outcome)

    def test_active_resident_derives_then_independently_verifies_append_goal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "append.txt"
            target.write_text("prefix-", encoding="utf-8")
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            event = resident.enqueue(
                "append the requested text to the current file",
                payload={
                    "path": str(target),
                    "content": "suffix",
                    "append": True,
                    "required_capabilities": ["filesystem"],
                    "model_policy": "never",
                },
            )

            result = self._run_to_terminal(resident)

            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.BODY)
            self.assertEqual(result.model_invocations, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), "prefix-suffix")
            experiences = resident.verified_experiences.for_event(event.event_id)
            self.assertEqual(len(experiences), 1)
            self.assertEqual(experiences[0].verdict, "verified")
            self.assertEqual(experiences[0].expected_outcome["kind"], "text_equals")
            self.assertEqual(experiences[0].expected_outcome["action_variant"], "append")
            self.assertNotIn(str(target), str(experiences[0].expected_outcome))

            movements = [
                item.kind
                for item in resident.body.recent_actions(40)
                if item.event_id == event.event_id
            ]
            self.assertIn("inspect_path", movements)
            self.assertIn("read_text", movements)
            self.assertIn("write_text", movements)
            self.assertGreaterEqual(movements.count("read_text"), 2)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
