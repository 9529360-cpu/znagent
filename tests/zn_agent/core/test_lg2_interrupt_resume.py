"""LG-2: interrupt + Command(resume) with a value.

P2b ``gap_report`` stops the team when the specialist hits a missing
design/scope gap; LG-2 is the other half -- how the team comes back:

- interrupt: the pending decision is persisted into the team's durable
  shared memory AND into the AF-2 checkpoint (``checkpoint.state``,
  ``pending_interrupt``), and the event stays alive + blocked instead of
  failing terminally, so a crash/restart loses nothing;
- resume: ``TeamWorkOwner.resume_interrupt`` is the ``Command(resume)``
  shape -- a caller supplies the decision value, the interrupted node
  re-runs with that value in its next cognition call, completed steps are
  never replayed, and the interrupt record is consumed exactly once.

No daemon RPC yet (daemon.py is out of this slice's scope): the resume
entry point is the owner API, for a later PR to wire to the daemon.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.cognitive_resource import (
    CognitiveIncrement,
    CognitiveResourceWorkerFactory,
)
from zn_agent.core.completion_verdict import render_completion_report
from zn_agent.core.evidence_bound_work import EvidenceBoundSteerableWorkLedger
from zn_agent.core.memory import StructuredMemory
from zn_agent.core.models import ModelRoute
from zn_agent.core.project_team import assemble_team
from zn_agent.core.provider_bridge import (
    build_resident_runtime,
    build_resident_runtime_from_existing_stack,
)
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.steerable_work import WorkItem
from zn_agent.core.store import KernelStore
from zn_agent.core.team_memory import team_shared_memory
from zn_agent.core.team_runner import (
    InMemoryCheckpointStorage,
    TeamRunner,
    pending_steps,
)
from zn_agent.core.team_work_owner import TeamWorkOwner
from zn_agent.core.work_restore_control import RestoreAwareWorkControl

CRITERIA = ["调研结论有明确选型建议", "风险清单覆盖主要未知项"]
GAP = {
    "missing": "没有设计文档",
    "needed": "架构专员的设计文档",
    "impact": "无法确定接口范围",
}
RESUME_VALUE = "用现有接口文档继续，接口按 v1 草案。"


def _dod(*, ref: str = "research/notes.md") -> dict[str, dict[str, str]]:
    return {
        "no_regression": {
            "status": "satisfied",
            "detail": "相关测试集已运行并通过。",
            "evidence_ref": ref,
        },
        "runtime_verified": {
            "status": "satisfied",
            "detail": "关键行为已在真实运行时验证过。",
            "evidence_ref": ref,
        },
        "docs": {
            "status": "satisfied",
            "detail": "结论与风险已写入 research/notes.md。",
        },
        "rollback": {
            "status": "satisfied",
            "detail": "删除 research/notes.md 即可回退。",
        },
        "approval": {
            "status": "satisfied",
            "detail": "无破坏性/外部动作，无需审批。",
        },
    }


def _full_report(*, ref: str = "research/notes.md") -> str:
    return render_completion_report(
        conclusion="调研完成，结论已写好。",
        evidence=[(criterion, ref) for criterion in CRITERIA],
        files=[ref],
        unfinished=[],
        standing_dod=_dod(ref=ref),
    )


def _gap_json() -> str:
    return json.dumps({"gap_report": dict(GAP)}, ensure_ascii=False)


class OwnerInterruptTests(unittest.TestCase):
    """Owner-level interrupt record + resume + checkpoint persistence."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zn-lg2-owner-"))
        self.store = KernelStore(self.root / "kernel.db")
        resident = SimpleNamespace(
            store=SimpleNamespace(path=str(self.root / "kernel.db"))
        )
        self.ledger = EvidenceBoundSteerableWorkLedger(resident)
        self.ledger.create_thread(thread_id="thread-lg2", title="XX 项目")
        self.memory = StructuredMemory(self.store)
        self.storage = InMemoryCheckpointStorage()
        self.owner = TeamWorkOwner(
            ledger=self.ledger,
            memory=self.memory,
            checkpoint_storage=self.storage,
        )
        self.team = assemble_team(
            "XX 项目",
            ["researcher", "developer"],
            team_id="team-lg2",
            work_thread_id="thread-lg2",
        )

    def tearDown(self):
        self.store.close()

    def _record(self, **overrides):
        kwargs = {
            "team_id": "team-lg2",
            "run_id": "run-1",
            "work_item_id": "item-1",
            "kind": "gap",
            "missing": GAP["missing"],
            "needed": GAP["needed"],
            "impact": GAP["impact"],
        }
        kwargs.update(overrides)
        return self.owner.record_interrupt(**kwargs)

    def test_interrupt_record_round_trip_and_restart(self):
        record = self._record()
        self.assertEqual(record["status"], "pending")
        self.assertEqual(record["missing"], GAP["missing"])
        self.assertTrue(str(record.get("interrupt_id") or "").strip())
        # A fresh owner over the same memory sees it: crash/restart
        # loses nothing.
        fresh = TeamWorkOwner(ledger=self.ledger, memory=self.memory)
        pending = fresh.pending_interrupt(team_id="team-lg2")
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertEqual(pending["interrupt_id"], record["interrupt_id"])
        self.assertEqual(pending["status"], "pending")

    def test_resume_requires_pending_and_nonempty_value(self):
        with self.assertRaises(ValueError):
            self.owner.resume_interrupt(team_id="team-lg2", resume_value="x")
        self._record()
        with self.assertRaises(ValueError):
            self.owner.resume_interrupt(team_id="team-lg2", resume_value="   ")
        resumed = self.owner.resume_interrupt(
            team_id="team-lg2", resume_value=RESUME_VALUE
        )
        self.assertEqual(resumed["status"], "resumed")
        self.assertEqual(resumed["resume_value"], RESUME_VALUE)
        self.assertTrue(str(resumed.get("resumed_at") or "").strip())

    def test_resume_same_value_is_idempotent_replay(self):
        self._record()
        first = self.owner.resume_interrupt(
            team_id="team-lg2", resume_value=RESUME_VALUE
        )
        # Crash between resume and consumption: replaying the same
        # resume value must not raise or duplicate.
        second = self.owner.resume_interrupt(
            team_id="team-lg2", resume_value=RESUME_VALUE
        )
        self.assertEqual(second["interrupt_id"], first["interrupt_id"])
        self.assertEqual(second["status"], "resumed")
        # A different value while resumed is ambiguous: refuse.
        with self.assertRaises(ValueError):
            self.owner.resume_interrupt(
                team_id="team-lg2", resume_value="另一个决定"
            )

    def test_record_is_idempotent_for_same_node_and_guards_other_node(self):
        first = self._record()
        second = self._record()
        self.assertEqual(second["interrupt_id"], first["interrupt_id"])
        with self.assertRaises(ValueError):
            self._record(run_id="run-2", work_item_id="item-2")

    def test_clear_consumes_exactly_once(self):
        self._record()
        self.owner.resume_interrupt(team_id="team-lg2", resume_value=RESUME_VALUE)
        self.owner.clear_interrupt(team_id="team-lg2")
        self.assertIsNone(self.owner.pending_interrupt(team_id="team-lg2"))
        # Clearing again is a no-op, never an error.
        self.owner.clear_interrupt(team_id="team-lg2")

    def test_interrupt_checkpoint_carries_pending_decision(self):
        self._record()
        saved = self.owner.save_interrupt_checkpoint(
            team=self.team, root_work_item_id="root-lg2"
        )
        self.assertIsNotNone(saved)
        assert saved is not None
        pending = saved.state.get("pending_interrupt")
        self.assertIsInstance(pending, dict)
        assert isinstance(pending, dict)
        self.assertEqual(pending["status"], "pending")
        self.assertEqual(pending["missing"], GAP["missing"])
        self.assertEqual(pending["needed"], GAP["needed"])
        self.assertEqual(pending["impact"], GAP["impact"])
        # The checkpoint round-trips through its serialized shape.
        restored = type(saved).from_dict(saved.to_dict())
        restored_pending = restored.state.get("pending_interrupt")
        self.assertIsInstance(restored_pending, dict)
        assert isinstance(restored_pending, dict)
        self.assertEqual(restored_pending["missing"], GAP["missing"])
        # No storage wired: no checkpoint, no crash.
        owner_no_store = TeamWorkOwner(ledger=self.ledger, memory=self.memory)
        self.assertIsNone(
            owner_no_store.save_interrupt_checkpoint(
                team=self.team, root_work_item_id="root-lg2"
            )
        )

    def test_checkpoint_does_not_replay_completed_steps(self):
        """Completed steps stay completed across interrupt + resume."""
        first_item, second_item = (
            item.item_id for item in self.team.plan
        )
        self.ledger._save_item(
            WorkItem(
                work_item_id="wi-first",
                work_thread_id="thread-lg2",
                title="第一项",
                objective="做第一项",
                status="completed",
                plan_version=1,
            )
        )
        self.ledger._save_item(
            WorkItem(
                work_item_id="wi-second",
                work_thread_id="thread-lg2",
                title="第二项",
                objective="做第二项",
                status="running",
                plan_version=1,
            )
        )
        shared = team_shared_memory(self.memory, "team-lg2")
        shared.remember(
            TeamRunner.PLAN_MAP_KEY,
            {first_item: "wi-first", second_item: "wi-second"},
        )
        self._record(work_item_id="wi-second")
        saved = self.owner.save_interrupt_checkpoint(
            team=self.team, root_work_item_id="root-lg2"
        )
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved.completed_step_ids, (first_item,))
        self.assertEqual(saved.pending_step_ids, (second_item,))
        self.assertEqual(
            pending_steps(saved, [first_item, second_item]), [second_item]
        )


# -- resident end-to-end -------------------------------------------------


class _ScriptedSpecialist:
    """Fixture cognition: scripted replies per live-specialist call."""

    def __init__(self, *, script: list[str]) -> None:
        self._script = list(script)
        self.specialist_calls = 0
        self.questions: list[str] = []

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        if "调研-01" not in question:
            return CognitiveIncrement(
                text="继续按现有证据推进。",
                provider="fixture-cognition",
                model="team-lg2-fixture",
            )
        self.specialist_calls += 1
        self.questions.append(question)
        index = min(self.specialist_calls - 1, len(self._script) - 1)
        return CognitiveIncrement(
            text=self._script[index],
            provider="fixture-cognition",
            model="team-lg2-fixture",
        )


class ResidentInterruptResumeTests(unittest.TestCase):
    @staticmethod
    def _configure_cognition(resident, cognition) -> None:
        resident.kernel.reconfigure_resources(
            routes=[
                ModelRoute(
                    route_id="team-lg2-cognition",
                    provider="fixture",
                    model="team-lg2-fixture",
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

    def _start(self, root: Path, cognition):
        workspace = root / "team-workspace"
        workspace.mkdir(exist_ok=True)
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=root / "kernel.db",
        )
        self._configure_cognition(resident, cognition)
        control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
        ledger = control.ledger
        ledger.create_thread(thread_id="team-lg2-e2e", title="XX 项目")
        ledger.attach_workspace("team-lg2-e2e", workspace, name="Team Workspace")
        _, event = control.start(
            "team-lg2-e2e",
            "给 XX 项目组个团队",
            payload={
                "model_policy": "on_demand",
                "team_request": {
                    "project_title": "XX 项目",
                    "role_keys": ["researcher"],
                },
            },
        )
        return resident, ledger, event, workspace

    @staticmethod
    def _child(ledger, event):
        root = ledger.work_item_for_event(event.event_id)
        children = [
            item
            for item in ledger.list_work_items("team-lg2-e2e")
            if root is not None
            and item.parent_work_item_id == root.work_item_id
        ]
        return children[0] if children else None

    @staticmethod
    def _proposal(*, path: str, content: str) -> str:
        return json.dumps(
            {
                "zn_work_step": {
                    "objective": "调研员写一份可验证的工作产物",
                    "action": {
                        "kind": "write_file",
                        "path": path,
                        "content": content,
                    },
                    "acceptance": {
                        "kind": "text_equals",
                        "path": path,
                        "expected_text": content,
                    },
                }
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _team_id(resident) -> str:
        state = resident.store.get_working_state()
        team_id = str((state.data or {}).get("team_id") or "").strip()
        assert team_id, "working state lost the team id"
        return team_id

    def _drive_until_gap_consumed(self, resident, cognition):
        for _ in range(60):
            terminal = resident.live_once()
            self.assertIsNone(terminal, "gap must interrupt, not fail terminally")
            if cognition.specialist_calls >= 1:
                return
        self.fail("gap report was never consumed by the resident")

    def test_gap_interrupts_blocks_alive_and_resumes_to_completion(self):
        """gap -> interrupt (blocked, nothing invented) -> resume with a
        value -> the interrupted node re-runs with the value -> completes."""
        valid = self._proposal(
            path="research/notes.md", content="调研-01 verified step\n"
        )
        cognition = _ScriptedSpecialist(
            script=[_gap_json(), valid, _full_report()]
        )
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, event, workspace = self._start(
                Path(tmp), cognition
            )
            try:
                self._drive_until_gap_consumed(resident, cognition)
                # Blocked, not dead: more pulses ask nothing and fail
                # nothing, and no scope was invented.
                for _ in range(5):
                    terminal = resident.live_once()
                    self.assertIsNone(terminal)
                self.assertEqual(cognition.specialist_calls, 1)
                self.assertEqual(
                    sorted(p.name for p in workspace.iterdir()),
                    ["agents"],
                )
                # The pending decision is durable in team shared memory.
                owner = TeamWorkOwner(ledger=ledger, memory=resident.memory)
                team_id = self._team_id(resident)
                pending = owner.pending_interrupt(team_id=team_id)
                self.assertIsNotNone(pending)
                assert pending is not None
                self.assertEqual(pending["status"], "pending")
                self.assertEqual(pending["missing"], GAP["missing"])
                # Command(resume): supply the user's decision value.
                owner.resume_interrupt(
                    team_id=team_id, resume_value=RESUME_VALUE
                )
                # The interrupted node re-runs with the value and the
                # team continues to completion -- no restart from scratch.
                completed = False
                for _ in range(120):
                    terminal = resident.live_once()
                    self.assertIsNone(
                        terminal, "team must not fail after resume"
                    )
                    child = self._child(ledger, event)
                    if child is not None and child.status == "completed":
                        completed = True
                        break
                self.assertTrue(completed, "team item did not complete after resume")
                self.assertEqual(cognition.specialist_calls, 3)
                # The resume value reached the interrupted node's
                # re-run: it is in the second cognition question.
                self.assertGreaterEqual(len(cognition.questions), 2)
                self.assertIn(RESUME_VALUE, cognition.questions[1])
                # The interrupt record was consumed exactly once.
                self.assertIsNone(owner.pending_interrupt(team_id=team_id))
                # The verified step landed; the item completed on it.
                notes = workspace / "research" / "notes.md"
                self.assertTrue(notes.exists())
                self.assertEqual(
                    notes.read_text(encoding="utf-8"),
                    "调研-01 verified step\n",
                )
            finally:
                resident.store.close()

    def test_gap_interrupt_survives_restart_then_resumes(self):
        """Crash/restart between interrupt and resume loses nothing:
        the rebuilt resident still blocks on the same pending decision,
        and resume after restart still carries the value forward."""
        valid = self._proposal(
            path="research/notes.md", content="调研-01 verified step\n"
        )
        cognition = _ScriptedSpecialist(script=[_gap_json()])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident, ledger, event, workspace = self._start(root, cognition)
            try:
                self._drive_until_gap_consumed(resident, cognition)
                team_id = self._team_id(resident)
                resident.store.close()
            except Exception:
                resident.store.close()
                raise
            # Rebuild over the same store: the pending decision is
            # still there, and the rebuilt resident still blocks.
            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            cognition2 = _ScriptedSpecialist(script=[valid, _full_report()])
            try:
                self._configure_cognition(restored, cognition2)
                control = RestoreAwareWorkControl(
                    RecoveryBoundedWorkLedger(restored)
                )
                restored_ledger = control.ledger
                restored_ledger.attach_workspace(
                    "team-lg2-e2e", workspace, name="Team Workspace"
                )
                for _ in range(5):
                    terminal = restored.live_once()
                    self.assertIsNone(
                        terminal, "restart must not turn an interrupt into failure"
                    )
                self.assertEqual(
                    cognition2.specialist_calls,
                    0,
                    "rebuilt resident must still block on the pending decision",
                )
                owner = TeamWorkOwner(
                    ledger=restored_ledger, memory=restored.memory
                )
                pending = owner.pending_interrupt(team_id=team_id)
                self.assertIsNotNone(pending)
                assert pending is not None
                self.assertEqual(pending["missing"], GAP["missing"])
                owner.resume_interrupt(
                    team_id=team_id, resume_value=RESUME_VALUE
                )
                completed = False
                for _ in range(120):
                    terminal = restored.live_once()
                    self.assertIsNone(
                        terminal, "team must not fail after resume"
                    )
                    child = self._child(restored_ledger, event)
                    if child is not None and child.status == "completed":
                        completed = True
                        break
                self.assertTrue(
                    completed, "team item did not complete after restart + resume"
                )
                self.assertGreaterEqual(len(cognition2.questions), 1)
                self.assertIn(RESUME_VALUE, cognition2.questions[0])
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main()
