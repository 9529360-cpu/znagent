from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.memory import StructuredMemory
from zn_agent.core.store import KernelStore


class ExplicitPreferenceWritebackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.store = KernelStore(Path(self.tmp) / "kernel.db")
        self.addCleanup(self.store.close)
        self.memory = StructuredMemory(self.store)

    def _facts(self):
        return {item["key"]: item for item in self.store.list_facts()}

    def test_explicit_presentation_preference_is_normalized_not_raw_chat(self):
        writes = self.memory.capture_explicit_user_preferences(
            "请记住，以后回答请简洁一些，不要保存这整句话。"
        )
        self.assertEqual(
            writes,
            ({
                "dimension": "verbosity",
                "key": "response verbosity",
                "value": "concise",
                "action": "saved",
            },),
        )
        facts = self._facts()
        self.assertEqual(facts["response verbosity"]["value"], "concise")
        self.assertNotIn("不要保存这整句话", repr(facts))

    def test_ordinary_chat_and_sensitive_content_are_not_auto_saved(self):
        self.assertEqual(
            self.memory.capture_explicit_user_preferences("这次请简洁回答。"),
            (),
        )
        self.assertEqual(
            self.memory.capture_explicit_user_preferences(
                "请记住，我的密码是 hunter2，以后不要忘。"
            ),
            (),
        )
        self.assertEqual(self.store.list_facts(), [])

    def test_ambiguous_conflict_is_ignored_but_explicit_correction_updates(self):
        self.memory.capture_explicit_user_preferences(
            "请记住，以后回答请简洁一些。"
        )
        self.assertEqual(
            self.memory.capture_explicit_user_preferences(
                "以后回答既要简洁又要详细。"
            ),
            (),
        )
        self.assertEqual(
            self.memory.recall("response verbosity").value,
            "concise",
        )
        writes = self.memory.capture_explicit_user_preferences(
            "以后回答不要简洁，请详细一点。"
        )
        self.assertEqual(writes[0]["action"], "updated")
        self.assertEqual(
            self.memory.recall("response verbosity").value,
            "detailed",
        )
        writes = self.memory.capture_explicit_user_preferences(
            "回复风格改成简洁一点。"
        )
        self.assertEqual(writes[0]["action"], "updated")
        self.assertEqual(
            self.memory.recall("response verbosity").value,
            "detailed",
        )

    def test_repeat_does_not_rewrite_or_duplicate_memory(self):
        self.memory.capture_explicit_user_preferences(
            "Remember: from now on, keep your replies concise."
        )
        before = self._facts()["response verbosity"]
        writes = self.memory.capture_explicit_user_preferences(
            "Remember: from now on, keep your replies concise."
        )
        after = self._facts()["response verbosity"]
        self.assertEqual(writes, ())
        self.assertEqual(before["updated_at"], after["updated_at"])
        self.assertEqual(
            [item["key"] for item in self.store.list_facts()].count(
                "response verbosity"
            ),
            1,
        )

    def test_correction_collapses_conflicting_alias_keys(self):
        self.memory.remember("回复详细程度", "concise")
        writes = self.memory.capture_explicit_user_preferences(
            "改成详细一点回答。"
        )
        facts = self._facts()
        self.assertEqual(writes[0]["value"], "detailed")
        self.assertEqual(facts["response verbosity"]["value"], "detailed")
        self.assertNotIn("回复详细程度", facts)


if __name__ == "__main__":
    unittest.main()
