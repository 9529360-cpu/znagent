from __future__ import annotations

import unittest

from zn_agent.core.action import derive_native_action_intent, derive_native_action_intents
from zn_agent.core.models import AgentEvent


class NativeActionAlternativesContractTests(unittest.TestCase):
    def test_invalid_explicit_action_keeps_historical_native_fallback(self):
        event = AgentEvent(
            event_id="evt-invalid-explicit-fallback",
            task="ensure the target contains requested content",
            payload={
                "body_action": {"reason": "invalid because no kind"},
                "path": "/tmp/zn-fallback.txt",
                "content": "current event content",
            },
        )

        intents = derive_native_action_intents(event, facts={})
        default = derive_native_action_intent(event, facts={})

        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].kind, "write_text")
        self.assertIsNotNone(default)
        self.assertEqual(default.kind, "write_text")
        self.assertEqual(default.source, "native_deliberation")

    def test_incompatible_write_target_does_not_become_a_write_alternative(self):
        target = "/tmp/zn-directory-target"
        event = AgentEvent(
            event_id="evt-incompatible-write-alternative",
            task="run the current command and ensure the target contains requested content",
            payload={
                "command": "python -c \"print('safe')\"",
                "path": target,
                "content": "not a directory write",
            },
        )
        facts = {
            "paths": [
                {
                    "path": target,
                    "exists": True,
                    "type": "directory",
                }
            ]
        }

        intents = derive_native_action_intents(event, facts=facts)

        self.assertEqual([item.kind for item in intents], ["command"])
        self.assertEqual(derive_native_action_intent(event, facts=facts).kind, "command")

    def test_resident_forms_exact_text_alternatives_only_with_current_semantic_proof(self):
        target = "/tmp/zn-resident-choice.txt"
        event = AgentEvent(
            event_id="evt-resident-exact-text-choice",
            task="append requested text to the current file",
            payload={
                "path": target,
                "content": "-tail",
                "append": True,
                "expected_outcome": {
                    "kind": "text_equals",
                    "path": target,
                    "expected_text": "base-tail",
                },
            },
        )
        facts = {
            "paths": [{"path": target, "exists": True, "type": "file"}],
            "file_previews": [
                {
                    "path": target,
                    "preview": "base",
                    "chars": 4,
                    "truncated": False,
                }
            ],
        }

        intents = derive_native_action_intents(event, facts=facts)

        self.assertEqual(len(intents), 2)
        self.assertEqual(tuple(item.source for item in intents), ("resident_choice",) * 2)
        self.assertTrue(intents[0].args["append"])
        self.assertEqual(intents[0].args["content"], "-tail")
        self.assertFalse(intents[1].args["append"])
        self.assertEqual(intents[1].args["content"], "base-tail")
        self.assertEqual(intents[0].args["path"], intents[1].args["path"])

    def test_resident_does_not_invent_choice_without_complete_matching_preview(self):
        target = "/tmp/zn-resident-choice-proof.txt"
        event = AgentEvent(
            event_id="evt-resident-choice-no-proof",
            task="append requested text to the current file",
            payload={
                "path": target,
                "content": "-tail",
                "append": True,
                "expected_outcome": {
                    "kind": "text_equals",
                    "path": target,
                    "expected_text": "base-tail",
                },
            },
        )
        base_path_fact = [{"path": target, "exists": True, "type": "file"}]

        for preview in (
            None,
            {"path": target, "preview": "base", "chars": 4, "truncated": True},
            {"path": target, "preview": "different", "chars": 9, "truncated": False},
        ):
            facts = {"paths": base_path_fact}
            if preview is not None:
                facts["file_previews"] = [preview]
            with self.subTest(preview=preview):
                intents = derive_native_action_intents(event, facts=facts)
                self.assertEqual(len(intents), 1)
                self.assertTrue(intents[0].args["append"])
                self.assertNotEqual(intents[0].source, "resident_choice")


if __name__ == "__main__":
    unittest.main()
