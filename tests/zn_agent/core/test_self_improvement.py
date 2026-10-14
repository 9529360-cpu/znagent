from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.self_improvement import (
    SELF_IMPROVEMENT_TASK,
    SelfImprovementHistory,
    audit_memory_facts,
    audit_skills,
    collect_recent_routine_runs,
    ensure_self_improvement_routine,
    run_self_improvement,
    summarize_recent_tasks,
    trigger_self_improvement,
)
from zn_agent.core.skills import Skill, SkillStore


class MemoryAuditTests(unittest.TestCase):
    def test_alias_collision_and_duplicate_value_detected_without_mutation(self):
        facts = [
            {"key": "reply language", "value": "Chinese", "aliases": ("回答语言",)},
            {"key": "回答语言", "value": "Chinese", "aliases": ()},
            {"key": "timezone", "value": "UTC", "aliases": ()},
            {"key": "tz", "value": "UTC", "aliases": ()},
            {"key": "empty note", "value": "", "aliases": ()},
        ]
        before = copy.deepcopy(facts)
        report = audit_memory_facts(facts)
        # Same input object, untouched: the audit is read-only.
        self.assertEqual(facts, before)
        self.assertEqual(report["fact_count"], 5)
        aliases = {item["alias"] for item in report["alias_collisions"]}
        self.assertIn("回答语言", aliases)
        self.assertEqual(len(report["duplicate_values"]), 2)
        dup_key_sets = {tuple(item["keys"]) for item in report["duplicate_values"]}
        self.assertIn(("timezone", "tz"), dup_key_sets)
        self.assertIn(("reply language", "回答语言"), dup_key_sets)
        self.assertEqual(report["empty_facts"], ["empty note"])
        self.assertGreater(report["finding_count"], 0)

    def test_clean_memory_reports_no_findings(self):
        report = audit_memory_facts(
            [
                {"key": "reply language", "value": "Chinese", "aliases": ()},
                {"key": "timezone", "value": "UTC", "aliases": ()},
            ]
        )
        self.assertEqual(report["finding_count"], 0)


class SkillAuditTests(unittest.TestCase):
    def _skill(self, name, description, **kwargs):
        base = {
            "name": name,
            "description": description,
            "version": "1.0.0",
            "path": Path(f"/skills/{name}/skill.md"),
            "body": "Do the thing.",
        }
        base.update(kwargs)
        return Skill(**base)

    def test_duplicates_conflicts_expired_detected_without_mutation(self):
        skills = [
            self._skill("deploy", "Deploy the app when asked"),
            self._skill("deploy", "Ship the app when asked"),
            self._skill("ship", "Deploy the app when asked"),
            self._skill("old", "Ancient workflow", body="DEPRECATED: use deploy"),
        ]
        # Dict-form skills (as the auditor also accepts) carry meta.
        dict_skills = [
            {
                "name": skill.name,
                "description": skill.description,
                "version": skill.version,
                "path": str(skill.path),
                "body": skill.body,
            }
            for skill in skills
        ]
        dict_skills.append(
            {
                "name": "legacy",
                "description": "Old workflow",
                "version": "1.0.0",
                "path": "/skills/legacy/skill.md",
                "body": "Old workflow.",
                "meta": {"status": "deprecated"},
            }
        )
        before = copy.deepcopy(dict_skills)
        report = audit_skills(dict_skills)
        self.assertEqual(dict_skills, before)
        self.assertEqual(len(report["duplicates"]), 1)
        self.assertEqual(report["duplicates"][0]["name"], "deploy")
        self.assertEqual(len(report["conflicts"]), 1)
        self.assertEqual(report["conflicts"][0]["name"], "deploy")
        self.assertEqual(len(report["near_duplicates"]), 1)
        self.assertEqual(
            report["near_duplicates"][0]["names"], ["deploy", "ship"]
        )
        expired_names = {item["name"] for item in report["expired"]}
        self.assertEqual(expired_names, {"legacy", "old"})
        self.assertTrue(report["recommendations"])

    def test_expired_by_past_date_and_clean_skills(self):
        report = audit_skills(
            [
                {
                    "name": "dated",
                    "description": "Dated skill",
                    "version": "1.0.0",
                    "path": "/skills/dated/skill.md",
                    "body": "Still here.",
                    "meta": {"expires_at": "2020-01-01T00:00:00Z"},
                },
                {
                    "name": "fresh",
                    "description": "Fresh skill",
                    "version": "1.0.0",
                    "path": "/skills/fresh/skill.md",
                    "body": "Still here.",
                    "meta": {"expires_at": "2999-01-01T00:00:00Z"},
                },
            ]
        )
        self.assertEqual([item["name"] for item in report["expired"]], ["dated"])
        self.assertEqual(report["finding_count"], 1)


class RetrospectiveTests(unittest.TestCase):
    def test_mixed_tasks_counted_and_failures_become_entries(self):
        review = summarize_recent_tasks(
            [
                {"task": "check inbox", "status": "succeeded"},
                {"task": "send report", "status": "failed", "failure_reason": "timeout"},
                {"task": "sync files", "status": "failed", "failure_reason": "timeout"},
                {"task": "backup", "status": "failed", "failure_reason": "disk full"},
            ]
        )
        self.assertEqual(review["total"], 4)
        self.assertEqual(review["succeeded"], 1)
        self.assertEqual(review["failed"], 3)
        self.assertEqual(
            review["failure_reasons"],
            [
                {"reason": "timeout", "count": 2},
                {"reason": "disk full", "count": 1},
            ],
        )
        self.assertEqual(review["entries"][0]["kind"], "summary")
        failures = [e for e in review["entries"] if e["kind"] == "failure"]
        self.assertEqual(len(failures), 3)
        self.assertEqual(failures[0]["reason"], "timeout")

    def test_empty_tasks_yield_zero_summary(self):
        review = summarize_recent_tasks([])
        self.assertEqual(review["total"], 0)
        self.assertEqual(review["entries"][0]["kind"], "summary")

    def test_collector_skips_running_and_normalizes_runs(self):
        class FakeManager:
            def list_routines(self, limit=100):
                return [
                    {
                        "routine_id": "routine-1",
                        "title": "check inbox",
                        "task": "check inbox",
                    }
                ]

            def runs(self, routine_id, limit=20):
                return [
                    {
                        "run_id": "run-1",
                        "status": "succeeded",
                        "started_at": "2026-10-14T08:00:00Z",
                    },
                    {
                        "run_id": "run-2",
                        "status": "failed",
                        "failure_reason": "timeout",
                        "started_at": "2026-10-14T09:00:00Z",
                    },
                    {"run_id": "run-3", "status": "running"},
                ]

        tasks, in_flight = collect_recent_routine_runs(FakeManager())
        self.assertEqual(in_flight, 1)
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]["status"], "failed")
        self.assertEqual(tasks[0]["failure_reason"], "timeout")


class RegistrationAndTriggerTests(unittest.TestCase):
    @staticmethod
    def _resident(db: Path):
        return build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=db,
        )

    def test_registration_is_idempotent_and_manual_trigger_records_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            resident = self._resident(tmp_path / "kernel.db")
            first = ensure_self_improvement_routine(resident.routines)
            self.assertEqual(first["task"], SELF_IMPROVEMENT_TASK)
            self.assertEqual(first["status"], "active")
            second = ensure_self_improvement_routine(resident.routines)
            self.assertEqual(second["routine_id"], first["routine_id"])
            matches = [
                item
                for item in resident.routines.list_routines(limit=500)
                if item["task"] == SELF_IMPROVEMENT_TASK
            ]
            self.assertEqual(len(matches), 1)
            # The trigger organ owns the cadence.
            trigger = resident.recurring_will.get(first["intention_id"])
            self.assertIsNotNone(trigger)
            assert trigger is not None
            self.assertEqual(trigger.interval_seconds, 7 * 24 * 3600)

            # Seed one memory fact, one skill bundle, then trigger manually.
            resident.store.put_fact("reply language", "Chinese")
            skills_root = tmp_path / "skills" / "deploy"
            skills_root.mkdir(parents=True)
            (skills_root / "skill.md").write_text(
                "---\nname: deploy\ndescription: Deploy the app when asked\n"
                "version: 1.0.0\n---\nDeploy the app.\n",
                encoding="utf-8",
            )
            result = trigger_self_improvement(
                resident, skill_store=SkillStore(root=tmp_path / "skills")
            )
            report = result["report"]
            self.assertEqual(report["memory"]["fact_count"], 1)
            self.assertEqual(report["skills"]["skill_count"], 1)
            self.assertEqual(report["review"]["total"], 0)
            self.assertEqual(result["run"]["status"], "succeeded")
            self.assertEqual(result["run"]["routine_id"], first["routine_id"])

            history = SelfImprovementHistory(resident.store)
            recent = history.recent(limit=20)
            self.assertEqual(len(recent), 1)
            self.assertEqual(recent[0]["run_id"], result["run"]["run_id"])
            resident.store.close()

    def test_run_self_improvement_is_pure_report(self):
        report = run_self_improvement(
            memory_facts=[
                {"key": "a", "value": "1", "aliases": ()},
                {"key": "b", "value": "1", "aliases": ()},
            ],
            skills=[
                {
                    "name": "deploy",
                    "description": "Deploy",
                    "version": "1.0.0",
                    "path": "/x",
                    "body": "x",
                }
            ],
            tasks=[{"task": "t", "status": "failed", "failure_reason": "boom"}],
        )
        self.assertEqual(report["memory"]["finding_count"], 1)
        self.assertEqual(report["skills"]["skill_count"], 1)
        self.assertEqual(report["review"]["failed"], 1)
        self.assertIn("只读", report["note"])


if __name__ == "__main__":
    unittest.main()
