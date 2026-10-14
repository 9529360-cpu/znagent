from __future__ import annotations

"""P2-5 team group-chat timeline: derivation, @assign, and daemon RPCs.

The timeline is derived from the Work log, never a second source of truth:
every entry maps 1:1 to a journal message (same id/text/timestamp).
"""

import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.evidence_bound_work import EvidenceBoundSteerableWorkLedger
from zn_agent.core.memory import StructuredMemory
from zn_agent.core.project_team import assemble_team
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.steerable_work import WorkItem
from zn_agent.core.store import KernelStore
from zn_agent.core.team_coordinator import TeamCoordinator
from zn_agent.core.team_memory import team_shared_memory
from zn_agent.core.team_runner import TeamRunner, VerificationOutcome
from zn_agent.core.team_timeline import (
    apply_assignee_overrides,
    build_team_timeline,
    parse_mention,
    record_assignee_override,
)
from zn_agent.core.team_work_owner import (
    TEAM_SPEC_KEY,
    TeamWorkOwner,
)


def _msg(message_id, role, text, detail=None, created_at="2026-10-14T00:00:00+00:00"):
    return {
        "message_id": message_id,
        "role": role,
        "text": text,
        "detail": detail or {},
        "created_at": created_at,
    }


class TeamTimelineBuilderTests(unittest.TestCase):
    def test_handoff_entry_shows_from_to_what_and_evidence(self):
        entries = build_team_timeline(
            [
                _msg(
                    "m1",
                    "team:t1:coordinator",
                    "派活：XX 项目·调研 → 调研-01",
                    {
                        "kind": "handoff",
                        "team_id": "t1",
                        "author": "coordinator",
                        "from_author": "coordinator",
                        "to_author": "调研-01",
                        "item_title": "XX 项目·调研",
                        "objective": "完成调研",
                    },
                ),
                _msg(
                    "m2",
                    "team:t1:coordinator",
                    "验收通过：XX 项目·调研——1 verified specialist step(s)",
                    {
                        "kind": "decision",
                        "team_id": "t1",
                        "author": "coordinator",
                        "item_title": "XX 项目·调研",
                        "evidence": [{"label": "notes.md", "ref": "notes.md"}],
                    },
                ),
            ],
            artifacts=[
                {"artifact_id": "a1", "path": "notes.md", "name": "notes.md"}
            ],
        )
        self.assertEqual(len(entries), 2)
        handoff, decision = entries
        self.assertEqual(handoff["kind"], "handoff")
        self.assertEqual(handoff["from_author"], "coordinator")
        self.assertEqual(handoff["to_author"], "调研-01")
        self.assertEqual(handoff["item_title"], "XX 项目·调研")
        self.assertEqual(handoff["objective"], "完成调研")
        # Evidence links to the thread artifact, not to invented content.
        self.assertEqual(decision["evidence"], [
            {"label": "notes.md", "ref": "notes.md", "artifact_id": "a1"}
        ])

    def test_handoff_falls_back_to_parsing_legacy_text(self):
        entries = build_team_timeline([
            _msg("m1", "team:t1:coordinator", "派活：XX 项目·调研 → 调研-01",
                 {"kind": "handoff"}),
        ])
        self.assertEqual(entries[0]["to_author"], "调研-01")
        self.assertEqual(entries[0]["item_title"], "XX 项目·调研")

    def test_specialist_message_keeps_author_and_assignment_entry(self):
        entries = build_team_timeline([
            _msg("m1", "team:t1:调研-01", "调研结论：用方案 A",
                 {"kind": "note", "team_id": "t1", "author": "调研-01"}),
            _msg("m2", "user", "@开发-02 先把登录做了",
                 {"kind": "assignment", "team_id": "t1", "from_author": "user",
                  "to_author": "开发-02", "item_title": "XX 项目·开发",
                  "instruction": "先把登录做了"}),
        ])
        self.assertEqual(
            [(e["kind"], e["author"]) for e in entries],
            [("message", "调研-01"), ("assignment", "user")],
        )
        self.assertEqual(entries[1]["to_author"], "开发-02")
        self.assertEqual(entries[1]["instruction"], "先把登录做了")

    def test_non_team_messages_are_excluded_and_ids_match_log(self):
        messages = [
            _msg("m0", "user", "组个团队做 XX 项目"),
            _msg("m1", "team:t1:coordinator", "派活：X → 调研-01",
                 {"kind": "handoff"}),
            _msg("m2", "zn", "收到，正在处理"),
            _msg("m3", "activity", "thinking"),
        ]
        entries = build_team_timeline(messages)
        # Timeline entries are a subset of the Work log, same ids.
        self.assertEqual([e["id"] for e in entries], ["m1"])
        self.assertEqual(entries[0]["text"], "派活：X → 调研-01")
        self.assertEqual(entries[0]["at"], "2026-10-14T00:00:00+00:00")


class MentionParsingTests(unittest.TestCase):
    def test_mention_with_instruction(self):
        self.assertEqual(
            parse_mention("@调研-01 先把登录做了"), ("调研-01", "先把登录做了")
        )

    def test_mention_without_instruction(self):
        self.assertEqual(parse_mention("@开发-02"), ("开发-02", ""))

    def test_full_width_at_sign(self):
        self.assertEqual(parse_mention("＠调研-01 做调研"), ("调研-01", "做调研"))

    def test_plain_text_is_not_a_mention(self):
        self.assertIsNone(parse_mention("调研-01 做调研"))
        self.assertIsNone(parse_mention("hello @调研-01"))
        self.assertIsNone(parse_mention("@"))
        self.assertIsNone(parse_mention(""))


class AssigneeOverrideTests(unittest.TestCase):
    def test_record_and_apply_override_without_mutating_team(self):
        team = assemble_team(
            "XX 项目", ["researcher", "developer"],
            team_id="t1", work_thread_id="thread-1",
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            try:
                memory = StructuredMemory(store)
                overrides = record_assignee_override(
                    memory, "t1", team.plan[0].item_id, "开发-02"
                )
                self.assertEqual(overrides, {team.plan[0].item_id: "开发-02"})
                updated = apply_assignee_overrides(team, overrides)
                self.assertEqual(updated.plan[0].assignee, "开发-02")
                # The original team is untouched (overrides are a copy).
                self.assertEqual(team.plan[0].assignee, "调研-01")
                # Unknown members / plan items are ignored, never corrupt.
                self.assertIs(
                    apply_assignee_overrides(team, {"nope": "开发-02"}), team
                )
                self.assertIs(
                    apply_assignee_overrides(
                        team, {team.plan[0].item_id: "不存在的专员"}
                    ),
                    team,
                )
            finally:
                store.close()


class CoordinatorJournalTests(unittest.TestCase):
    def test_dispatch_journal_carries_structured_handoff_fields(self):
        team = assemble_team(
            "XX 项目", ["researcher", "developer"],
            team_id="t1", work_thread_id="thread-1",
        )

        class FakeItem:
            work_item_id = "w1"
            title = "XX 项目·调研"
            status = "proposed"

        class FakeLedger:
            def list_work_items(self, thread_id):
                return [FakeItem()]

            def dependency_readiness(self, work_item_id):
                return SimpleNamespace(ready=True, waiting_on=[])

        decisions = TeamCoordinator(team=team, root_work_item_id="root").step(
            FakeLedger(), runs={}, id_map={team.plan[0].item_id: "w1"}
        )
        dispatch = [d for d in decisions if d.action == "dispatch"]
        self.assertEqual(len(dispatch), 1)
        detail = dispatch[0].journal["detail"]
        self.assertEqual(detail["kind"], "handoff")
        self.assertEqual(detail["from_author"], "coordinator")
        self.assertEqual(detail["to_author"], "调研-01")
        self.assertEqual(detail["item_title"], "XX 项目·调研")


class RunnerEvidenceJournalTests(unittest.TestCase):
    def test_verify_journal_carries_evidence_links(self):
        root = Path(tempfile.mkdtemp(prefix="zn-team-timeline-"))
        store = KernelStore(root / "kernel.db")
        try:
            resident = SimpleNamespace(
                store=SimpleNamespace(path=str(root / "kernel.db"))
            )
            ledger = EvidenceBoundSteerableWorkLedger(resident)
            memory = StructuredMemory(store)
            thread_id = "thread-team-1"
            ledger.create_thread(thread_id=thread_id, title="项目 X")
            ledger._save_item(WorkItem(
                work_item_id="root-1", work_thread_id=thread_id,
                title="XX 项目", objective="做完", status="running",
                plan_version=1,
            ))
            team = assemble_team(
                "XX 项目", ["researcher"],
                team_id="tx", work_thread_id=thread_id,
            )

            class Verifier:
                def verify(self, *, item, run):
                    return VerificationOutcome(
                        passed=True, notes="ok",
                        artifact_refs=({"path": "notes.md"},),
                    )

            runner = TeamRunner(
                team=team, ledger=ledger, memory=memory,
                verifier=Verifier(), root_work_item_id="root-1",
            )
            runner.step()  # dispatch
            wid = team_shared_memory(memory, "tx").recall("plan_item_map").value[
                team.plan[0].item_id
            ]
            run = ledger.list_worker_runs(work_item_id=wid)[-1]
            ledger.complete_worker_run(
                run.worker_run_id, result_summary="做完了",
                claimed_completion=True, verification_status="pending",
            )
            runner.step()  # verify (evidence journal) + complete
            decisions = [
                m for m in ledger.list_messages(thread_id, limit=500)
                if m.detail.get("kind") == "decision"
            ]
            self.assertEqual(len(decisions), 1)
            self.assertEqual(
                decisions[0].detail["evidence"],
                [{"label": "notes.md", "ref": "notes.md"}],
            )
        finally:
            store.close()


class OwnerOverrideTests(unittest.TestCase):
    def test_resolve_team_applies_stored_override(self):
        root = Path(tempfile.mkdtemp(prefix="zn-team-owner-"))
        store = KernelStore(root / "kernel.db")
        try:
            memory = StructuredMemory(store)
            owner = TeamWorkOwner(ledger=SimpleNamespace(), memory=memory)
            event = SimpleNamespace(payload={
                "team_request": {
                    "project_title": "XX 项目",
                    "role_keys": ["researcher", "developer"],
                },
                "work_thread_id": "thread-1",
            })
            state = SimpleNamespace(data={})
            team = owner.resolve_team(event=event, state=state, thread_id="thread-1")
            self.assertEqual(team.plan[0].assignee, "调研-01")
            record_assignee_override(
                memory, team.team_id, team.plan[0].item_id, "开发-02"
            )
            again = owner.resolve_team(event=event, state=state, thread_id="thread-1")
            self.assertEqual(again.plan[0].assignee, "开发-02")
        finally:
            store.close()


class DaemonTeamRpcTests(unittest.TestCase):
    def _server(self, tmp):
        with patch(
            "zn_agent.core.life.shutil.disk_usage",
            return_value=SimpleNamespace(total=100, used=50, free=50),
        ):
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=Path(tmp) / "kernel.db",
            )
        return ResidentRpcServer(
            resident=resident,
            input_stream=io.StringIO(),
            output_stream=io.StringIO(),
        )

    def test_timeline_and_assign_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = self._server(tmp)
            try:
                created = server.handle({
                    "id": "c", "method": "work_create",
                    "params": {"thread_id": "t-thread", "title": "XX 项目"},
                })
                self.assertTrue(created["ok"])
                # A team journal entry without a spec: timeline reads it,
                # assign refuses (no roster to validate against).
                server.work.append_message(
                    "t-thread", role="team:t1:coordinator",
                    text="派活：XX 项目·调研 → 调研-01",
                    detail={"kind": "handoff", "team_id": "t1",
                            "from_author": "coordinator",
                            "to_author": "调研-01",
                            "item_title": "XX 项目·调研"},
                )
                timeline = server.handle({
                    "id": "tl", "method": "team_timeline",
                    "params": {"thread_id": "t-thread"},
                })
                self.assertTrue(timeline["ok"])
                self.assertEqual(timeline["result"]["team_id"], "t1")
                self.assertEqual(len(timeline["result"]["entries"]), 1)
                self.assertEqual(
                    timeline["result"]["entries"][0]["to_author"], "调研-01"
                )
                with self.assertRaises(ValueError):
                    server.handle({
                        "id": "a", "method": "team_assign",
                        "params": {"thread_id": "t-thread",
                                   "specialist": "调研-01",
                                   "instruction": "做调研"},
                    })
                # Seed the team spec, then @assign works.
                team_shared_memory(server.resident.memory, "t1").remember(
                    TEAM_SPEC_KEY,
                    {"project_title": "XX 项目",
                     "role_keys": ["researcher", "developer"]},
                )
                assigned = server.handle({
                    "id": "a", "method": "team_assign",
                    "params": {"thread_id": "t-thread",
                               "specialist": "开发-02",
                               "instruction": "先把登录做了"},
                })
                self.assertTrue(assigned["ok"])
                self.assertEqual(assigned["result"]["specialist"], "开发-02")
                self.assertEqual(
                    assigned["result"]["item_title"], "XX 项目·调研"
                )
                # The assignment is journaled, so the timeline shows it and
                # stays consistent with the Work log.
                after = server.handle({
                    "id": "tl2", "method": "team_timeline",
                    "params": {"thread_id": "t-thread"},
                })
                kinds = [e["kind"] for e in after["result"]["entries"]]
                self.assertEqual(kinds, ["handoff", "assignment"])
                assignment = after["result"]["entries"][1]
                self.assertEqual(assignment["to_author"], "开发-02")
                self.assertEqual(assignment["instruction"], "先把登录做了")
                log_ids = {
                    m.message_id
                    for m in server.work.list_messages("t-thread", limit=500)
                }
                self.assertTrue(
                    {e["id"] for e in after["result"]["entries"]} <= log_ids
                )
                # Unknown specialist is rejected, not journaled.
                with self.assertRaises(ValueError):
                    server.handle({
                        "id": "a2", "method": "team_assign",
                        "params": {"thread_id": "t-thread",
                                   "specialist": "不存在-99",
                                   "instruction": ""},
                    })
            finally:
                server.resident.store.close()

    def test_assign_without_team_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = self._server(tmp)
            try:
                server.handle({
                    "id": "c", "method": "work_create",
                    "params": {"thread_id": "plain", "title": "普通任务"},
                })
                with self.assertRaises(ValueError):
                    server.handle({
                        "id": "a", "method": "team_assign",
                        "params": {"thread_id": "plain",
                                   "specialist": "调研-01",
                                   "instruction": ""},
                    })
                with self.assertRaises(ValueError):
                    server.handle({
                        "id": "x", "method": "team_assign",
                        "params": {"thread_id": "missing",
                                   "specialist": "调研-01",
                                   "instruction": ""},
                    })
            finally:
                server.resident.store.close()


if __name__ == "__main__":
    unittest.main()
