"""CM-1: structured observation records on StructuredMemory."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.memory import Observation, StructuredMemory
from zn_agent.core.store import KernelStore


def _observation(**overrides):
    data = {
        "kind": "fixed",
        "title": "Windows short-path mismatch",
        "facts": ["production side resolves to the long path", "test side did not"],
        "narrative": "Test expectation compared an unresolved temp path.",
        "concepts": ["path-normalization", "windows"],
        "files_read": ["tests/zn_agent/core/test_memory.py"],
        "files_modified": ["runtime/python/zn_agent/core/memory.py"],
    }
    data.update(overrides)
    return data


class RecordObservationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(self.root / "memory.db")
        self.addCleanup(self.store.close)
        self.memory = StructuredMemory(self.store)

    def test_structured_write_reads_back_identical(self):
        obs = Observation(**_observation())
        key = self.memory.record_observation(obs)
        self.assertEqual(key, "observation:Windows short-path mismatch")
        read_back = self.memory.recall_observation("Windows short-path mismatch")
        self.assertEqual(read_back, obs)
        self.assertEqual(read_back.kind, "fixed")
        self.assertEqual(
            read_back.facts,
            ("production side resolves to the long path", "test side did not"),
        )
        self.assertEqual(read_back.concepts, ("path-normalization", "windows"))
        self.assertEqual(read_back.files_read, ("tests/zn_agent/core/test_memory.py",))
        self.assertEqual(
            read_back.files_modified, ("runtime/python/zn_agent/core/memory.py",)
        )
        self.assertEqual(self.memory.list_observations(), [obs])

    def test_dict_input_is_accepted_and_normalized(self):
        key = self.memory.record_observation(_observation())
        self.assertEqual(key, "observation:Windows short-path mismatch")
        read_back = self.memory.recall_observation("Windows short-path mismatch")
        self.assertIsInstance(read_back, Observation)
        self.assertEqual(read_back.title, "Windows short-path mismatch")

    def test_optional_fields_default_to_empty(self):
        self.memory.record_observation({"kind": "learned", "title": "T", "facts": ["f1"]})
        read_back = self.memory.recall_observation("T")
        self.assertEqual(read_back.narrative, "")
        self.assertEqual(read_back.concepts, ())
        self.assertEqual(read_back.files_read, ())
        self.assertEqual(read_back.files_modified, ())

    def test_re_recording_same_title_replaces(self):
        self.memory.record_observation(_observation())
        self.memory.record_observation(_observation(facts=["new fact"]))
        self.assertEqual(len(self.memory.list_observations()), 1)
        self.assertEqual(
            self.memory.recall_observation("Windows short-path mismatch").facts,
            ("new fact",),
        )

    def test_forget_observation(self):
        self.memory.record_observation(_observation())
        self.assertTrue(self.memory.forget_observation("Windows short-path mismatch"))
        self.assertIsNone(self.memory.recall_observation("Windows short-path mismatch"))
        self.assertFalse(self.memory.forget_observation("Windows short-path mismatch"))
        self.assertIsNone(self.memory.recall_observation("no such title"))

    def test_old_format_facts_still_readable_and_not_listed(self):
        self.memory.remember("project", "znagent")
        self.memory.remember("reply language", "zh-CN")
        self.memory.record_observation(_observation())
        self.assertEqual(self.memory.recall("project").value, "znagent")
        self.assertEqual(len(self.memory.list_observations()), 1)
        self.assertEqual(
            self.memory.relevant_context("project"),
            [{"key": "project", "value": "znagent"}],
        )

    def test_malformed_row_is_skipped_not_fatal(self):
        self.memory.record_observation(_observation())
        # A hand-written row with the marker but missing required fields.
        self.store.put_fact(
            "observation:broken",
            {"record_kind": "observation", "kind": "learned"},
        )
        self.assertEqual(len(self.memory.list_observations()), 1)
        self.assertIsNone(self.memory.recall_observation("broken"))


class ObservationValidationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = KernelStore(self.root / "memory.db")
        self.addCleanup(self.store.close)
        self.memory = StructuredMemory(self.store)

    def test_missing_kind_rejected_with_reason(self):
        data = _observation()
        del data["kind"]
        with self.assertRaisesRegex(ValueError, "kind"):
            self.memory.record_observation(data)
        self.assertEqual(self.memory.list_observations(), [])

    def test_missing_title_rejected_with_reason(self):
        data = _observation()
        del data["title"]
        with self.assertRaisesRegex(ValueError, "title"):
            self.memory.record_observation(data)

    def test_missing_facts_rejected_with_reason(self):
        data = _observation()
        del data["facts"]
        with self.assertRaisesRegex(ValueError, "facts"):
            self.memory.record_observation(data)

    def test_empty_kind_title_and_facts_rejected(self):
        for field, bad in (
            ("kind", "   "),
            ("title", ""),
            ("facts", []),
            ("facts", ["  "]),
        ):
            with self.subTest(field=field, bad=bad):
                with self.assertRaisesRegex(ValueError, field):
                    self.memory.record_observation(_observation(**{field: bad}))

    def test_bare_string_facts_rejected(self):
        with self.assertRaisesRegex(ValueError, "facts"):
            self.memory.record_observation(_observation(facts="not a list"))

    def test_unknown_field_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown field 'typo'"):
            self.memory.record_observation(_observation(typo="oops"))

    def test_wrong_types_rejected(self):
        with self.assertRaisesRegex(ValueError, "narrative"):
            self.memory.record_observation(_observation(narrative=42))
        with self.assertRaisesRegex(ValueError, "concepts"):
            self.memory.record_observation(_observation(concepts="one-string"))
        with self.assertRaisesRegex(ValueError, "files_modified"):
            self.memory.record_observation(_observation(files_modified=[7]))

    def test_dataclass_instance_with_bad_values_rejected(self):
        with self.assertRaisesRegex(ValueError, "kind"):
            self.memory.record_observation(
                Observation(kind="", title="T", facts=("f1",))
            )


if __name__ == "__main__":
    unittest.main()
