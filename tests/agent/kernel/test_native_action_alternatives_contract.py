from __future__ import annotations

import unittest

from agent.kernel.action import derive_native_action_intent, derive_native_action_intents
from agent.kernel.models import AgentEvent


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


if __name__ == "__main__":
    unittest.main()
