from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.kernel.provider_bridge import build_resident_runtime
from agent.kernel.procedural_resident import ProcedurallyInfluencedResidentRuntime


class ResidentStructuredChoiceLearningTests(unittest.TestCase):
    @staticmethod
    def _run_to_terminal(resident, limit: int = 96):
        for _ in range(limit):
            result = resident.live_once()
            if result is not None:
                return result
        raise AssertionError(
            "resident did not reach a terminal result; current="
            f"{resident.store.get_working_state().stage}"
        )

    @staticmethod
    def _advance_until_stage(resident, stage: str, limit: int = 80) -> None:
        for _ in range(limit):
            if resident.store.get_working_state().stage == stage:
                return
            result = resident.live_once()
            if result is not None:
                raise AssertionError(
                    f"event reached terminal result before stage {stage}: {result}"
                )
        raise AssertionError(
            f"resident did not reach stage {stage}; current="
            f"{resident.store.get_working_state().stage}"
        )

    @staticmethod
    def _append_event(resident, target: Path, prefix: str, suffix: str):
        return resident.enqueue(
            "append requested text to the current file and satisfy its exact text state",
            payload={
                "path": str(target),
                "content": suffix,
                "append": True,
                "required_capabilities": ["filesystem"],
                "model_policy": "never",
                "expected_outcome": {
                    "kind": "text_equals",
                    "path": str(target),
                    "expected_text": prefix + suffix,
                },
            },
        )

    def test_failed_append_teaches_verified_replace_tendency_that_biases_later_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "stable.txt"
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            self.assertIsInstance(resident, ProcedurallyInfluencedResidentRuntime)

            original_write = resident.body._write_text

            def reject_append(action, started):
                if bool(action.args.get("append", False)):
                    raise OSError("append route unavailable in this observed environment")
                return original_write(action, started)

            trained_contents: list[str] = []
            with patch.object(resident.body, "_write_text", side_effect=reject_append):
                for index in range(3):
                    prefix = f"base-{index}"
                    suffix = f"-tail-{index}"
                    expected = prefix + suffix
                    target.write_text(prefix, encoding="utf-8")
                    event = self._append_event(resident, target, prefix, suffix)

                    result = self._run_to_terminal(resident)

                    self.assertTrue(result.success)
                    self.assertEqual(result.model_invocations, 0)
                    self.assertEqual(target.read_text(encoding="utf-8"), expected)
                    experiences = resident.verified_experiences.for_event(event.event_id)
                    self.assertEqual(len(experiences), 1)
                    self.assertEqual(experiences[0].verdict, "verified")
                    self.assertEqual(experiences[0].action_kind, "write_text")
                    trained_contents.append(expected)

                    actions = [
                        item
                        for item in resident.body.recent_actions(80)
                        if item.event_id == event.event_id and item.kind == "write_text"
                    ]
                    self.assertEqual(len(actions), 2)
                    failed = [item for item in actions if not item.success]
                    succeeded = [item for item in actions if item.success]
                    self.assertEqual(len(failed), 1)
                    self.assertEqual(len(succeeded), 1)
                    self.assertIn("append route unavailable", failed[0].error or "")
                    self.assertFalse(succeeded[0].data.get("append"))

            candidates = resident.verified_experiences.candidate_tendencies()
            supported = [
                item
                for item in candidates
                if item.action_kind == "write_text"
                and item.expected_kind == "text_equals"
                and item.maturity_state == "supported"
            ]
            self.assertEqual(len(supported), 1)
            candidate = supported[0]
            self.assertEqual(candidate.support_count, 3)
            serialized = json.dumps(candidate.to_dict(), sort_keys=True)
            for raw in trained_contents:
                self.assertNotIn(raw, serialized)
            self.assertNotIn(str(target), serialized)

            # In a later comparable reality, current event data and current file
            # evidence form the same two choices again. The learned tendency may
            # now bias the current direct-replace shape, but still supplies no
            # path/content arguments and verification remains mandatory.
            prefix = "later-base"
            suffix = "-later-tail"
            expected = prefix + suffix
            target.write_text(prefix, encoding="utf-8")
            event = self._append_event(resident, target, prefix, suffix)
            self._advance_until_stage(resident, "native_action")

            state = resident.store.get_working_state()
            selected = state.data["native_action_intent"]
            self.assertEqual(selected["source"], "resident_choice")
            self.assertEqual(selected["kind"], "write_text")
            self.assertFalse(selected["args"]["append"])
            self.assertEqual(selected["args"]["path"], str(target))
            self.assertEqual(selected["args"]["content"], expected)
            influence = state.data.get("procedural_action_influence")
            self.assertIsInstance(influence, dict)
            self.assertEqual(influence["tendency_id"], candidate.tendency_id)
            self.assertFalse(influence["revoked"])

            result = self._run_to_terminal(resident)
            self.assertTrue(result.success)
            self.assertEqual(result.model_invocations, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), expected)
            actions = [
                item
                for item in resident.body.recent_actions(80)
                if item.event_id == event.event_id and item.kind == "write_text"
            ]
            self.assertEqual(len(actions), 1)
            self.assertFalse(actions[0].data.get("append"))
            verification = [
                item
                for item in resident.body.recent_actions(80)
                if item.event_id == event.event_id and item.kind == "read_text"
            ]
            self.assertTrue(verification)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
