"""P3-8: disband executes for real -- DisbandPlan scope is actually deleted.

Uses the real ledger + real memory (same harness as test_team_runner):
assemble -> runner creates plan items + journal + runs -> execute_disband
-> re-read every scope and assert it is gone, checklist delivered.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.evidence_bound_work import EvidenceBoundSteerableWorkLedger
from zn_agent.core.memory import StructuredMemory
from zn_agent.core.project_team import SHARED_FILES_REMINDER, assemble_team
from zn_agent.core.steerable_work import WorkItem
from zn_agent.core.store import KernelStore
from zn_agent.core.team_disband import (
    DisbandReport,
    execute_disband,
    find_team_id_in_messages,
    parse_disband_request,
)
from zn_agent.core.team_memory import (
    delete_team_memory,
    specialist_memory,
    team_shared_memory,
)
from zn_agent.core.team_runner import TeamRunner, VerificationOutcome
from zn_agent.core.team_work_owner import TEAM_SPEC_KEY
from zn_agent.core.work import WorkArtifact, WorkRun


class _StubVerifier:
    def verify(self, *, item, run):
        return VerificationOutcome(passed=True, notes="stub")


def _make_ledger_and_memory(root: Path):
    store = KernelStore(root / "kernel.db")
    resident = SimpleNamespace(store=SimpleNamespace(path=str(root / "kernel.db")))
    ledger = EvidenceBoundSteerableWorkLedger(resident)
    memory = StructuredMemory(store)
    return ledger, memory, store


class ParseDisbandTests(unittest.TestCase):
    def test_explicit_instructions_parse(self):
        for text in (
            "把团队解散",
            "把这支团队解散",
            "解散团队",
            "解散这个团队",
            "把团队删掉",
            "删除团队",
            "解散掉团队",
            "删掉团队",
            "disband the team",
            "delete the team",
        ):
            self.assertIsNotNone(parse_disband_request(text), text)

    def test_negated_disband_never_parses(self):
        for text in (
            "不要解散团队",
            "请不要解散团队",
            "别把团队解散",
            "别解散团队",
            "禁止解散团队",
        ):
            self.assertIsNone(parse_disband_request(text), text)

    def test_non_instructions_do_not_parse(self):
        for text in (
            "解散",
            "解散会议",
            "团队解散了",
            "他们团队解散了",
            "我们团队明天开会",
            "帮我写个脚本",
            "给 XX 项目组个团队",
            "",
        ):
            self.assertIsNone(parse_disband_request(text), text)


class ExecuteDisbandTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.ledger, self.memory, self.store = _make_ledger_and_memory(root)
        self.thread_id = "thread-disband-1"
        self.ledger.create_thread(thread_id=self.thread_id, title="项目 X")
        # The team event's Root + plan items (via the real runner).
        team_root = WorkItem(
            work_item_id="team-root-1",
            work_thread_id=self.thread_id,
            title="XX 项目",
            objective="把 XX 项目做完",
            status="running",
            plan_version=1,
        )
        self.ledger._save_item(team_root)
        self.team = assemble_team(
            "XX 项目",
            ["researcher", "developer"],
            team_id="td1",
            work_thread_id=self.thread_id,
        )
        runner = TeamRunner(
            team=self.team,
            ledger=self.ledger,
            memory=self.memory,
            verifier=_StubVerifier(),
            root_work_item_id="team-root-1",
        )
        runner.step()  # creates plan items, dispatches, journals handoffs
        # Specialist memory + a non-team fact (must survive). The spec is
        # what the owner writes on the first pulse (TeamWorkOwner).
        shared = team_shared_memory(self.memory, "td1")
        shared.remember(
            TEAM_SPEC_KEY,
            {"project_title": "XX 项目", "role_keys": ["researcher", "developer"]},
        )
        shared.remember("retrospective", {"entry_count": 3})
        specialist = specialist_memory(self.memory, self.team.members[0])
        specialist.remember("lesson", "always verify")
        self.memory.remember("my_own_fact", "must survive disband")
        # A non-team message + a team journal message.
        self.ledger.append_message(
            self.thread_id, role="user", text="先聊点别的", detail={}
        )
        self.ledger.append_message(
            self.thread_id,
            role="team:td1:coordinator",
            text="派活：XX 项目·调研 → 调研-01",
            detail={"kind": "handoff", "team_id": "td1", "author": "coordinator"},
        )
        # An artifact row + an old event's work_run row.
        self.ledger._save_artifact(
            WorkArtifact(
                artifact_id="artifact-1",
                thread_id=self.thread_id,
                event_id="old-event",
                kind="file",
                name="notes.md",
                content="old",
            )
        )
        self.ledger._save_run(
            WorkRun(
                event_id="old-event",
                thread_id=self.thread_id,
                message_id="msg-old",
                task="old task",
            )
        )
        # The disband event's own rows (must survive as the checklist carrier).
        disband_root = WorkItem(
            work_item_id="disband-root-1",
            work_thread_id=self.thread_id,
            title="把团队解散",
            objective="把团队解散",
            status="running",
            plan_version=1,
        )
        self.ledger._save_item(disband_root)
        disband_msg = self.ledger.append_message(
            self.thread_id, role="user", text="把团队解散", detail={}
        )
        self.ledger._save_run(
            WorkRun(
                event_id="disband-event",
                thread_id=self.thread_id,
                message_id=disband_msg.message_id,
                task="把团队解散",
            )
        )
        self.disband_message_id = disband_msg.message_id

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def _run_disband(self, **overrides):
        kwargs = {
            "team_id": "td1",
            "ledger": self.ledger,
            "memory": self.memory,
            "thread_id": self.thread_id,
            "current_event_id": "disband-event",
            "current_work_item_id": "disband-root-1",
            "current_message_id": self.disband_message_id,
        }
        kwargs.update(overrides)
        return execute_disband(**kwargs)

    def test_disband_deletes_every_scope_and_verifies(self):
        report = self._run_disband()
        self.assertTrue(report.verified)
        self.assertEqual(report.team_id, "td1")
        self.assertEqual(report.plan_items_deleted, 2)
        self.assertGreaterEqual(report.worker_runs_deleted, 1)
        self.assertGreaterEqual(report.journal_messages_deleted, 1)
        self.assertGreaterEqual(report.memory_facts_deleted, 3)
        self.assertEqual(report.work_runs_deleted, 1)
        # Only the disband event's own rows survive.
        remaining_items = self.ledger.list_work_items(self.thread_id, limit=500)
        self.assertEqual(
            [item.work_item_id for item in remaining_items],
            ["disband-root-1"],
        )
        remaining_messages = self.ledger.list_messages(self.thread_id, limit=500)
        self.assertEqual(
            [msg.message_id for msg in remaining_messages],
            [self.disband_message_id],
        )
        self.assertEqual(self.ledger.list_artifacts(self.thread_id), [])
        self.assertEqual(self.ledger.count_thread_work_runs(self.thread_id), 1)
        self.assertEqual(
            [
                f["key"]
                for f in self.memory.store.list_facts()
                if str(f["key"]).startswith("team:td1:")
            ],
            [],
        )
        # Non-team memory survives.
        self.assertIsNotNone(self.memory.recall("my_own_fact"))
        # The thread row itself survives as the checklist carrier.
        self.assertIsNotNone(self.ledger.get_thread(self.thread_id))
        # Checklist: counts + shared-files manual-cleanup reminder.
        checklist = report.checklist_text()
        self.assertIn("已解散", checklist)
        self.assertIn("逐项复核通过", checklist)
        self.assertIn(SHARED_FILES_REMINDER, checklist)
        self.assertIn("调研-01", checklist)

    def test_disband_without_current_rows_deletes_everything(self):
        report = self._run_disband(
            current_event_id=None,
            current_work_item_id=None,
            current_message_id=None,
        )
        self.assertTrue(report.verified)
        self.assertEqual(self.ledger.list_work_items(self.thread_id), [])
        self.assertEqual(self.ledger.list_messages(self.thread_id), [])
        self.assertEqual(self.ledger.count_thread_work_runs(self.thread_id), 0)

    def test_disband_unknown_team_deletes_nothing(self):
        before_messages = self.ledger.list_messages(self.thread_id, limit=500)
        before_items = self.ledger.list_work_items(self.thread_id, limit=500)
        with self.assertRaises(ValueError):
            self._run_disband(team_id="no-such-team")
        self.assertEqual(
            [m.message_id for m in self.ledger.list_messages(self.thread_id)],
            [m.message_id for m in before_messages],
        )
        self.assertEqual(
            [i.work_item_id for i in self.ledger.list_work_items(self.thread_id)],
            [i.work_item_id for i in before_items],
        )
        self.assertIsNotNone(self.memory.recall("my_own_fact"))

    def test_disband_unknown_thread_deletes_nothing(self):
        with self.assertRaises(ValueError):
            execute_disband(
                team_id="td1",
                ledger=self.ledger,
                memory=self.memory,
                thread_id="no-such-thread",
            )
        self.assertIsNotNone(self.memory.recall("my_own_fact"))

    def test_find_team_id_in_messages(self):
        messages = self.ledger.list_messages(self.thread_id, limit=500)
        self.assertEqual(find_team_id_in_messages(messages), "td1")
        self.assertIsNone(find_team_id_in_messages([]))

    def test_checklist_report_shape(self):
        report = DisbandReport(team_id="t", thread_id="th", verified=True)
        self.assertIn(SHARED_FILES_REMINDER, report.checklist_text())

    def test_delete_team_memory_prefix_sweep(self):
        self.assertGreaterEqual(delete_team_memory(self.memory, "td1"), 3)
        self.assertEqual(delete_team_memory(self.memory, "td1"), 0)
        self.assertIsNotNone(self.memory.recall("my_own_fact"))


if __name__ == "__main__":
    unittest.main()
