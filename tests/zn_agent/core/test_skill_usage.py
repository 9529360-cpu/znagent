from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from zn_agent.core.models import AgentEvent, CognitionRequest
from zn_agent.core.skill_usage import (
    USAGE_FILE_NAME,
    SkillUsageStore,
)
from zn_agent.core.skills import SkillStore


def _write_skill(
    root: Path,
    name: str,
    *,
    description: str = "",
    body: str = "Body.",
    version: str = "1.0.0",
) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    front = f"---\nname: {name}\ndescription: {description}\nversion: {version}\n---\n\n"
    path = directory / "skill.md"
    path.write_text(front + body, encoding="utf-8")
    return path


def _old_timestamp(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class UsageStoreTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.usage = SkillUsageStore(self.root)

    def test_record_use_increments_and_stamps(self):
        first = self.usage.record_use("notes")
        self.assertEqual(first.usage_count, 1)
        self.assertTrue(first.last_used)
        second = self.usage.record_use("notes")
        self.assertEqual(second.usage_count, 2)
        self.assertTrue(second.last_used)

    def test_record_use_rejects_empty_name(self):
        with self.assertRaises(ValueError):
            self.usage.record_use("   ")

    def test_persists_across_instances(self):
        # Restart simulation: a fresh store on the same root keeps stats.
        self.usage.record_use("notes")
        self.usage.record_use("notes")
        reopened = SkillUsageStore(self.root)
        entry = reopened.stats_for("notes")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.usage_count, 2)
        self.assertTrue(entry.last_used)

    def test_usage_file_is_json_sidecar(self):
        self.usage.record_use("notes")
        path = self.root / USAGE_FILE_NAME
        self.assertTrue(path.is_file())
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(raw["skills"]["notes"]["usage_count"], 1)

    def test_malformed_file_is_tolerated(self):
        (self.root / USAGE_FILE_NAME).write_text("{not json", encoding="utf-8")
        reopened = SkillUsageStore(self.root)  # must not raise
        self.assertEqual(reopened.all_stats(), [])
        # Recording still works afterwards.
        reopened.record_use("notes")
        entry = reopened.stats_for("notes")
        assert entry is not None
        self.assertEqual(entry.usage_count, 1)

    def test_corrupt_entries_are_tolerated(self):
        (self.root / USAGE_FILE_NAME).write_text(
            json.dumps({"version": 1, "skills": {"a": "not-a-dict", "b": {"usage_count": "x"}}}),
            encoding="utf-8",
        )
        reopened = SkillUsageStore(self.root)  # must not raise
        entry_a = reopened.stats_for("a")
        entry_b = reopened.stats_for("b")
        assert entry_a is not None
        assert entry_b is not None
        self.assertEqual(entry_a.usage_count, 0)
        self.assertEqual(entry_b.usage_count, 0)

    def test_unknown_version_is_tolerated(self):
        (self.root / USAGE_FILE_NAME).write_text(
            json.dumps({"version": 999, "skills": {"a": {"usage_count": 5}}}),
            encoding="utf-8",
        )
        reopened = SkillUsageStore(self.root)  # must not raise
        self.assertIsNone(reopened.stats_for("a"))

    def test_dormant_since(self):
        self.assertTrue(self.usage.dormant_since("ghost", dormant_days=30))
        self.usage.record_use("fresh")
        self.assertFalse(self.usage.dormant_since("fresh", dormant_days=30))
        self.usage.record_use("old", used_at=_old_timestamp(60))
        self.assertTrue(self.usage.dormant_since("old", dormant_days=30))
        self.assertFalse(self.usage.dormant_since("old", dormant_days=90))
        self.usage.record_use("recent", used_at=_old_timestamp(10))
        self.assertFalse(self.usage.dormant_since("recent", dormant_days=30))


class ActivationRecordingTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = SkillStore(self.root)
        _write_skill(
            self.root,
            "task-management",
            description="Simple task management using a shared TASKS.md file",
            body="Read TASKS.md first.",
        )

    def test_activate_skill_records_one_load(self):
        skill = self.store.activate_skill("task-management")
        self.assertIsNotNone(skill)
        entry = self.store.skill_usage("task-management")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.usage_count, 1)
        self.assertTrue(entry.last_used)

    def test_activate_twice_counts_twice(self):
        self.store.activate_skill("task-management")
        self.store.activate_skill("task-management")
        entry = self.store.skill_usage("task-management")
        assert entry is not None
        self.assertEqual(entry.usage_count, 2)

    def test_activate_unknown_records_nothing(self):
        self.assertIsNone(self.store.activate_skill("no-such-skill"))
        self.assertIsNone(self.store.skill_usage("no-such-skill"))

    def test_recording_failure_does_not_break_activation(self):
        class BrokenStore:
            def record_uses(self, names):
                raise OSError("disk gone")

        self.store.usage_store = BrokenStore()
        skill = self.store.activate_skill("task-management")
        self.assertIsNotNone(skill)
        assert skill is not None
        self.assertEqual(skill.name, "task-management")


class BindRecordingTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = SkillStore(self.root)
        _write_skill(
            self.root,
            "task-management",
            description="Simple task management using a shared TASKS.md file",
            body="Read TASKS.md first.",
        )

    def bind(self, task, **kwargs):
        event = AgentEvent("event", task, payload=kwargs.get("payload", {}))
        request = CognitionRequest("request", "impasse", event.event_id, task)
        return self.store.bind_cognition_context(
            event, request, include_bodies=kwargs.get("include_bodies", True)
        )

    def test_bind_with_bodies_records_load(self):
        request = self.bind("help me with task management")
        bundle = request.context.get("resident_skills")
        self.assertIsNotNone(bundle)
        entry = self.store.skill_usage("task-management")
        assert entry is not None
        self.assertEqual(entry.usage_count, 1)
        self.assertTrue(entry.last_used)

    def test_bind_resident_mode_records_nothing(self):
        # Resident summaries match, but no body reaches cognition: not a use.
        request = self.bind("help me with task management", include_bodies=False)
        bundle = request.context.get("resident_skills")
        self.assertIsNotNone(bundle)
        self.assertIsNone(self.store.skill_usage("task-management"))

    def test_bind_no_match_records_nothing(self):
        request = self.bind("what is the weather today")
        self.assertIsNone(request.context.get("resident_skills"))
        self.assertIsNone(self.store.skill_usage("task-management"))


class DormantQueryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = SkillStore(self.root)
        _write_skill(
            self.root,
            "task-management",
            description="Simple task management using a shared TASKS.md file",
            body="Read TASKS.md first.",
        )
        _write_skill(
            self.root,
            "deep-research",
            description="Multi-source web research with evidence comparison",
            body="Search at least three sources.",
        )

    def test_never_used_lists_zero_hit(self):
        self.store.activate_skill("task-management")
        names = [item.name for item in self.store.never_used_skills()]
        self.assertEqual(names, ["deep-research"])

    def test_list_skill_usage_covers_all_discovered(self):
        self.store.activate_skill("task-management")
        stats = {item.name: item for item in self.store.list_skill_usage()}
        self.assertEqual(set(stats), {"task-management", "deep-research"})
        self.assertEqual(stats["task-management"].usage_count, 1)
        self.assertTrue(stats["deep-research"].never_used)

    def test_dormant_skills_threshold(self):
        self.store.usage_store.record_use("task-management", used_at=_old_timestamp(60))
        self.store.activate_skill("deep-research")
        dormant = [item.name for item in self.store.dormant_skills(dormant_days=30)]
        self.assertEqual(dormant, ["task-management"])
        # A wider window keeps the old one out of the dormant list.
        self.assertEqual(self.store.dormant_skills(dormant_days=90), [])

    def test_dormant_queries_are_read_only(self):
        self.store.activate_skill("task-management")
        before = self.root / USAGE_FILE_NAME
        mtime_before = before.stat().st_mtime_ns
        self.store.never_used_skills()
        self.store.dormant_skills()
        self.store.list_skill_usage()
        self.assertEqual(before.stat().st_mtime_ns, mtime_before)
        entry = self.store.skill_usage("task-management")
        assert entry is not None
        self.assertEqual(entry.usage_count, 1)

    def test_selection_scoring_untouched(self):
        # Usage recording must not change which skills match: same query,
        # same ranking, before and after recording loads.
        query = "help me with task management today"
        before = [s.name for s in self.store.relevant_skills(query)]
        self.store.activate_skill("deep-research")
        self.store.activate_skill("deep-research")
        after = [s.name for s in self.store.relevant_skills(query)]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
