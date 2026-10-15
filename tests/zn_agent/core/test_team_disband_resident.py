"""P3-8 end-to-end through the real resident loop + daemon RPCs.

1. Disband: seed a team (spec + plan items + journal + runs) on a thread,
   send "把团队解散" via daemon work_start, drive the resident, and
   assert the cleanup checklist is the event's final response, the team
   state is gone, and the thread holds only the disband request +
   the checklist (+ the finalize activity note).
2. Sensitive handover: a specialist proposes a password step -> the
   resident records a handover and blocks WITHOUT executing it ->
   team_handover_done resolves it -> the driver continues and the
   specialist's real step lands.
3. Daemon guards: disband with no team, handover_done with no pending.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.cognitive_resource import CognitiveIncrement, CognitiveResourceWorkerFactory
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.models import ModelRoute
from zn_agent.core.project_team import SHARED_FILES_REMINDER
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.sensitive_handover import pending_handover
from zn_agent.core.steerable_work import WorkItem
from zn_agent.core.team_disband import find_team_id_in_messages
from zn_agent.core.team_memory import team_shared_memory
from zn_agent.core.team_runner import TeamRunner, VerificationOutcome
from zn_agent.core.team_work_owner import TEAM_SPEC_KEY


class _StubVerifier:
    def verify(self, *, item, run):
        return VerificationOutcome(passed=True, notes="stub verified")


def _configure_cognition(resident, cognition) -> None:
    resident.kernel.reconfigure_resources(
        routes=[
            ModelRoute(
                route_id="p3-8-cognition",
                provider="fixture",
                model="p3-8-fixture",
                capabilities={
                    "general": 1.0,
                    "reasoning": 1.0,
                    "coding": 1.0,
                    "research": 1.0,
                    "language_understanding": 1.0,
                },
            )
        ],
        worker_factory=CognitiveResourceWorkerFactory(
            resource_builder=lambda _route: cognition,
        ),
        max_attempts=1,
        resource_status={"available": True, "error": None},
    )


def _cognition_increment(text: str) -> CognitiveIncrement:
    return CognitiveIncrement(
        text=text, provider="fixture-cognition", model="p3-8-fixture"
    )


class _SensitiveThenRealCognition:
    """First specialist call: a password step. Then a real step, then a claim."""

    def __init__(self) -> None:
        self.calls = 0
        self.sent_sensitive = False
        self.sent_step = False

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        self.calls += 1
        if "调研-01" not in question:
            return _cognition_increment("继续按现有证据推进。")
        if not self.sent_sensitive:
            self.sent_sensitive = True
            return _cognition_increment(
                json.dumps(
                    {
                        "zn_work_step": {
                            "objective": "输入密码后继续",
                            "action": {
                                "kind": "write_file",
                                "path": "secret-step.md",
                                "content": "must never execute",
                            },
                            "acceptance": {
                                "kind": "text_equals",
                                "path": "secret-step.md",
                                "expected_text": "must never execute",
                            },
                        }
                    },
                    ensure_ascii=False,
                )
            )
        if not self.sent_step:
            self.sent_step = True
            return _cognition_increment(
                json.dumps(
                    {
                        "zn_work_step": {
                            "objective": "调研-01 写一份可验证的工作产物",
                            "action": {
                                "kind": "write_file",
                                "path": "research-notes.md",
                                "content": "调研-01 verified step\n",
                            },
                            "acceptance": {
                                "kind": "text_equals",
                                "path": "research-notes.md",
                                "expected_text": "调研-01 verified step\n",
                            },
                        }
                    },
                    ensure_ascii=False,
                )
            )
        return _cognition_increment(
            json.dumps(
                {
                    "completion_report": {
                        "conclusion": "调研完成：调研结论有明确选型建议，风险清单覆盖主要未知项。",
                        "evidence": [
                            {
                                "criterion": "调研结论有明确选型建议",
                                "evidence_ref": "research-notes.md",
                            },
                            {
                                "criterion": "风险清单覆盖主要未知项",
                                "evidence_ref": "research-notes.md",
                            },
                        ],
                        "files": ["research-notes.md"],
                        "unfinished": [],
                        # AS-3: the owner requires both tracks; attest DoD.
                        "standing_dod": {
                            "no_regression": {
                                "status": "not_applicable",
                                "detail": "纯调研任务，无代码变更，无回归面。",
                            },
                            "runtime_verified": {
                                "status": "not_applicable",
                                "detail": "纯调研任务，无需运行时验证。",
                            },
                            "docs": {
                                "status": "satisfied",
                                "detail": "结论已写入 research-notes.md。",
                                "evidence_ref": "research-notes.md",
                            },
                            "rollback": {
                                "status": "satisfied",
                                "detail": "删除 research-notes.md 即可回退。",
                            },
                            "approval": {
                                "status": "satisfied",
                                "detail": "无破坏性/外部动作，无需审批。",
                            },
                        },
                    }
                },
                ensure_ascii=False,
            )
        )


class DisbandResidentTests(unittest.TestCase):
    def _seed_team(self, server, thread_id, team_id):
        ledger = server.resident.work_ledger
        ledger.create_thread(thread_id=thread_id, title="XX 项目")
        root = WorkItem(
            work_item_id=f"{team_id}-root",
            work_thread_id=thread_id,
            title="XX 项目",
            objective="把 XX 项目做完",
            status="running",
            plan_version=1,
        )
        ledger._save_item(root)
        from zn_agent.core.project_team import assemble_team

        team = assemble_team(
            "XX 项目",
            ["researcher"],
            team_id=team_id,
            work_thread_id=thread_id,
        )
        shared = team_shared_memory(server.resident.memory, team_id)
        shared.remember(
            TEAM_SPEC_KEY,
            {"project_title": "XX 项目", "role_keys": ["researcher"]},
        )
        runner = TeamRunner(
            team=team,
            ledger=ledger,
            memory=server.resident.memory,
            verifier=_StubVerifier(),
            root_work_item_id=f"{team_id}-root",
        )
        runner.step()
        return team

    def test_disband_sentence_drives_resident_to_checklist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident = build_resident_runtime(
                config={"model": {}}, store_path=root / "kernel.db"
            )
            server = ResidentRpcServer(resident=resident)
            try:
                self._seed_team(server, "disband-e2e", "tde")
                response = server.handle(
                    {
                        "id": "disband-1",
                        "method": "work_start",
                        "params": {
                            "thread_id": "disband-e2e",
                            "task": "把团队解散",
                        },
                    }
                )
                self.assertTrue(response["ok"], response)
                event_id = response["result"]["progress"]["event_id"]
                event = resident.store.get_event(event_id)
                assert event is not None
                self.assertEqual(
                    event.payload.get("disband_request"), {"team_id": "tde"}
                )
                completed = None
                for _ in range(60):
                    resident.live_once()
                    completed = resident.result_for(event_id)
                    if completed is not None:
                        break
                self.assertIsNotNone(completed, "disband event never completed")
                assert completed is not None
                self.assertTrue(completed.success, completed.reason)
                self.assertIn("清理清单", completed.response or "")
                self.assertIn(SHARED_FILES_REMINDER, completed.response or "")
                self.assertIn("已解散", completed.response or "")
                # Delivery: the checklist lands in the thread via finalize.
                progress = None
                for _ in range(10):
                    progress = server.handle(
                        {
                            "id": "disband-progress",
                            "method": "work_progress",
                            "params": {
                                "thread_id": "disband-e2e",
                                "event_id": event_id,
                            },
                        }
                    )
                    self.assertTrue(progress["ok"], progress)
                    if progress["result"]["progress"].get("finalized"):
                        break
                thread = progress["result"].get("thread")
                assert thread is not None
                roles = [msg["role"] for msg in thread["messages"]]
                self.assertFalse(
                    [role for role in roles if role.startswith("team:tde:")],
                    f"team journal survived disband: {roles}",
                )
                zn_texts = [
                    msg["text"] for msg in thread["messages"] if msg["role"] == "zn"
                ]
                self.assertTrue(
                    any("清理清单" in text for text in zn_texts),
                    f"checklist missing from thread: {zn_texts}",
                )
                # Every DisbandPlan scope is gone; only the disband Root left.
                ledger = server.resident.work_ledger
                remaining = ledger.list_work_items("disband-e2e", limit=500)
                self.assertEqual(len(remaining), 1)
                self.assertEqual(
                    remaining[0].work_item_id,
                    ledger.work_item_for_event(event_id).work_item_id,
                )
                self.assertEqual(
                    [
                        f["key"]
                        for f in resident.memory.store.list_facts()
                        if str(f["key"]).startswith("team:tde:")
                    ],
                    [],
                )
            finally:
                resident.store.close()

    def test_disband_without_team_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}}, store_path=Path(tmp) / "kernel.db"
            )
            server = ResidentRpcServer(resident=resident)
            try:
                with self.assertRaises(ValueError):
                    server.handle(
                        {
                            "id": "disband-none",
                            "method": "work_start",
                            "params": {
                                "thread_id": "plain-thread",
                                "task": "把团队解散",
                            },
                        }
                    )
            finally:
                resident.store.close()

    def test_team_handover_done_without_pending_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}}, store_path=Path(tmp) / "kernel.db"
            )
            server = ResidentRpcServer(resident=resident)
            try:
                self._seed_team(server, "handover-none", "thn")
                with self.assertRaises(ValueError):
                    server.handle(
                        {
                            "id": "handover-none-1",
                            "method": "team_handover_done",
                            "params": {"thread_id": "handover-none"},
                        }
                    )
            finally:
                resident.store.close()

    def test_sensitive_step_blocks_then_resumes_after_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "handover-workspace"
            workspace.mkdir()
            resident = build_resident_runtime(
                config={"model": {}}, store_path=root / "kernel.db"
            )
            try:
                cognition = _SensitiveThenRealCognition()
                _configure_cognition(resident, cognition)
                server = ResidentRpcServer(resident=resident)
                ledger = server.resident.work_ledger
                ledger.create_thread(thread_id="handover-e2e", title="XX 项目")
                ledger.attach_workspace(
                    "handover-e2e", workspace, name="Handover Workspace"
                )
                response = server.handle(
                    {
                        "id": "team-start",
                        "method": "work_start",
                        "params": {
                            "thread_id": "handover-e2e",
                            # One researcher only: the fixture covers exactly
                            # this specialist; the other roles would spin
                            # on generic prose and hit the no-progress guard.
                            "task": "给 XX 项目组个团队，带一个调研",
                        },
                    }
                )
                self.assertTrue(response["ok"], response)
                event_id = response["result"]["progress"]["event_id"]
                # Drive until the sensitive step hands over. The team id
                # only exists once the first pulse journals a handoff, so
                # resolve it fresh every pulse.
                handed_over = False
                for _ in range(60):
                    resident.live_once()
                    team_id = find_team_id_in_messages(
                        ledger.list_messages("handover-e2e", limit=500)
                    )
                    if pending_handover(resident.memory, team_id or "") is not None:
                        handed_over = True
                        break
                    if resident.result_for(event_id) is not None:
                        break
                self.assertTrue(handed_over, "sensitive step never handed over")
                # Nothing executed: no Body step, no secret file, event alive.
                self.assertFalse((workspace / "secret-step.md").exists())
                self.assertIsNone(resident.result_for(event_id))
                # A few more pulses stay blocked (no cognition burn).
                calls_at_block = cognition.calls
                for _ in range(3):
                    resident.live_once()
                self.assertEqual(cognition.calls, calls_at_block)
                # The owner does the step by hand and says "做完了".
                done = server.handle(
                    {
                        "id": "handover-done",
                        "method": "team_handover_done",
                        "params": {"thread_id": "handover-e2e"},
                    }
                )
                self.assertTrue(done["ok"], done)
                self.assertEqual(done["result"]["status"], "resolved")
                self.assertIsNone(pending_handover(resident.memory, team_id or ""))
                # Drive to item completion: the real step lands, then the claim.
                completed_item = False
                for _ in range(120):
                    resident.live_once()
                    children = [
                        item
                        for item in ledger.list_work_items("handover-e2e")
                        if item.parent_work_item_id
                        == ledger.work_item_for_event(event_id).work_item_id
                    ]
                    if children and all(
                        item.status == "completed" for item in children
                    ):
                        completed_item = True
                        break
                self.assertTrue(
                    completed_item, "team did not resume after handover"
                )
                self.assertTrue((workspace / "research-notes.md").is_file())
                self.assertFalse((workspace / "secret-step.md").exists())
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
