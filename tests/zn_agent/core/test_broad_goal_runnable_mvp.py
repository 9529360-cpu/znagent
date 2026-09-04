from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.cognitive_resource import CognitiveIncrement, CognitiveResourceWorkerFactory
from zn_agent.core.models import ModelRoute, WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.steerable_work import WorkItem
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


BROAD_GOAL = (
    "帮我开发一个本地个人记账小产品。先调研一下同类产品最核心的功能，然后自己推进，"
    "做出一个能真正运行的第一版。第一版不要做登录，不要做复杂设计，先把核心记账跑起来。"
)


class _PlanOnlyCognition:
    """A bounded cognition result: useful thinking, but no world-side evidence."""

    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        self.calls += 1
        return CognitiveIncrement(
            text=(
                "先调研个人记账产品的核心能力，再实现新增收入/支出、金额、描述和本地持久化；"
                "实现后应启动程序并验证重启后数据仍在。"
            ),
            provider="e2e-cognition",
            model="bounded-planning-fixture",
        )


class _OneStepCognition:
    """Propose one bounded workspace movement; ZN must own and verify execution."""

    def __init__(self) -> None:
        self.calls = 0
        self.questions: list[str] = []

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        self.calls += 1
        self.questions.append(question)
        proposal = {
            "zn_work_step": {
                "objective": "create one bounded probe artifact in the attached workspace",
                "action": {
                    "kind": "write_file",
                    "path": "rolling-probe.txt",
                    "content": "resident-owned rolling step\n",
                },
                "acceptance": {
                    "kind": "text_equals",
                    "path": "rolling-probe.txt",
                    "expected_text": "resident-owned rolling step\n",
                },
            }
        }
        return CognitiveIncrement(
            text=json.dumps(proposal, ensure_ascii=False),
            provider="e2e-cognition",
            model="bounded-step-fixture",
        )


class BroadGoalRunnableMvpTests(unittest.TestCase):
    @staticmethod
    def _configure_cognition(resident, cognition, *, model: str) -> None:
        resident.kernel.reconfigure_resources(
            routes=[
                ModelRoute(
                    route_id="e2e-26-broad-goal-cognition",
                    provider="fixture",
                    model=model,
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

    def test_model_plan_alone_cannot_accept_broad_goal_work_item(self) -> None:
        """E2E-26 probe: cognition is not acceptance without runnable-world evidence."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "ledger-mvp"
            workspace.mkdir()
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            try:
                cognition = _PlanOnlyCognition()
                self._configure_cognition(
                    resident,
                    cognition,
                    model="bounded-planning-fixture",
                )

                control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
                ledger = control.ledger
                ledger.create_thread(thread_id="e2e-26", title="Broad goal MVP")
                ledger.attach_workspace("e2e-26", workspace, name="Ledger MVP")
                before_files = sorted(
                    str(path.relative_to(workspace))
                    for path in workspace.rglob("*")
                    if path.is_file()
                )

                _, event = control.start(
                    "e2e-26",
                    BROAD_GOAL,
                    payload={"model_policy": "on_demand"},
                    acceptance_criteria=[
                        "current product has been started successfully",
                        "a real income or expense can be added and observed",
                        "the added record survives a product restart",
                    ],
                )

                result = None
                for _ in range(16):
                    candidate = resident.live_once()
                    if candidate is not None and candidate.event.event_id == event.event_id:
                        result = candidate
                        break

                self.assertIsNotNone(result, "broad goal did not reach the current Resident result")
                self.assertGreaterEqual(cognition.calls, 1, "broad goal never used model cognition")
                after_files = sorted(
                    str(path.relative_to(workspace))
                    for path in workspace.rglob("*")
                    if path.is_file()
                )
                self.assertEqual(
                    after_files,
                    before_files,
                    "plan-only cognition fixture must not fabricate product files",
                )

                progress = control.progress("e2e-26", event.event_id)
                item = ledger.work_item_for_event(event.event_id)
                self.assertIsNotNone(item)
                self.assertEqual(item.acceptance_criteria, [
                    "current product has been started successfully",
                    "a real income or expense can be added and observed",
                    "the added record survives a product restart",
                ])
                self.assertNotEqual(
                    progress.get("work_item_status"),
                    "completed",
                    "model text was accepted as WorkItem completion without any runnable-world evidence",
                )
            finally:
                resident.store.close()

    def test_structured_cognition_step_becomes_durable_verified_body_work(self) -> None:
        """Second E2E-26 probe: proposal -> WorkItem -> Body -> fresh verification."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "rolling-workspace"
            workspace.mkdir()
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            try:
                cognition = _OneStepCognition()
                self._configure_cognition(
                    resident,
                    cognition,
                    model="bounded-step-fixture",
                )
                control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
                ledger = control.ledger
                ledger.create_thread(thread_id="rolling-step", title="Rolling broad Work")
                ledger.attach_workspace(
                    "rolling-step",
                    workspace,
                    name="Rolling Workspace",
                )

                _, event = control.start(
                    "rolling-step",
                    "Build a small local artifact from this broad workspace goal and keep advancing from evidence.",
                    payload={"model_policy": "on_demand"},
                    acceptance_criteria=[
                        "the final broad goal still requires later independent verification",
                    ],
                )
                root_item = ledger.work_item_for_event(event.event_id)
                self.assertIsNotNone(root_item)
                assert root_item is not None

                terminal = None
                verified_child = None
                for _ in range(32):
                    candidate = resident.live_once()
                    if candidate is not None and candidate.event.event_id == event.event_id:
                        terminal = candidate
                        break
                    children = [
                        item
                        for item in ledger.list_work_items("rolling-step")
                        if item.parent_work_item_id == root_item.work_item_id
                    ]
                    completed = [item for item in children if item.status == "completed"]
                    if completed:
                        verified_child = completed[0]
                        break

                target = workspace / "rolling-probe.txt"
                self.assertGreaterEqual(cognition.calls, 1)
                self.assertTrue(
                    target.is_file(),
                    "structured model proposal was never converted into a resident-owned File movement",
                )
                self.assertEqual(
                    target.read_text(encoding="utf-8"),
                    "resident-owned rolling step\n",
                    "ZN must fresh-read and preserve the exact proposed postcondition",
                )

                items = ledger.list_work_items("rolling-step")
                children = [
                    item
                    for item in items
                    if item.parent_work_item_id == root_item.work_item_id
                ]
                self.assertEqual(
                    len(children),
                    1,
                    "one bounded cognition proposal should materialize as one durable child WorkItem",
                )
                self.assertIsNotNone(verified_child)
                self.assertEqual(children[0].status, "completed")
                self.assertEqual(
                    children[0].acceptance_criteria,
                    ["text_equals: rolling-probe.txt"],
                )
                self.assertIn("rolling-probe.txt", children[0].result or "")

                root_after = ledger.work_item_for_event(event.event_id)
                self.assertIsNotNone(root_after)
                assert root_after is not None
                self.assertNotEqual(
                    root_after.status,
                    "completed",
                    "one verified child step cannot accept the still-broad Root Work",
                )
                self.assertIsNone(
                    terminal,
                    "Resident must keep the Root Work live after one rolling child step",
                )
                self.assertEqual(
                    resident.store.get_working_state().stage,
                    "native_deliberation",
                )
            finally:
                resident.store.close()

    def test_restart_rolls_verified_child_forward_without_terminal_root(self) -> None:
        """Crash after native_completion must not turn one child into Root completion."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            workspace = root / "restart-workspace"
            workspace.mkdir()
            first = build_resident_runtime(config={"model": {}}, store_path=db)
            control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(first))
            ledger = control.ledger
            ledger.create_thread(thread_id="restart-roll", title="Restart rolling Work")
            ledger.attach_workspace("restart-roll", workspace, name="Restart Workspace")
            _, event = control.start(
                "restart-roll",
                "Keep a broad local Work alive across a verified child checkpoint.",
                acceptance_criteria=["Root still needs later independent verification"],
            )
            root_item = ledger.work_item_for_event(event.event_id)
            self.assertIsNotNone(root_item)
            assert root_item is not None
            child = WorkItem(
                work_item_id="item-restart-verified-child",
                work_thread_id="restart-roll",
                parent_work_item_id=root_item.work_item_id,
                title="Verified child",
                objective="write one verified child artifact",
                status="running",
                plan_version=root_item.plan_version,
                acceptance_criteria=["text_equals: restart-probe.txt"],
            )
            ledger._save_item(child)
            first.store.save_working_state(
                WorkingState(
                    current_event_id=event.event_id,
                    stage="native_completion",
                    next_action="publish terminal EventOutcome",
                    data={
                        "broad_goal_rolling_step": {
                            "work_item_id": child.work_item_id,
                            "root_work_item_id": root_item.work_item_id,
                            "work_thread_id": "restart-roll",
                            "plan_version": root_item.plan_version,
                            "relative_path": "restart-probe.txt",
                            "objective": child.objective,
                            "increment_id": "inc-restart-probe",
                        },
                        "native_completion": {
                            "execution_path": "body",
                            "success": True,
                            "response": str(workspace / "restart-probe.txt"),
                            "model_invocations": 0,
                            "reason": "verified child body result",
                        },
                    },
                )
            )
            first.store.close()

            restored = build_resident_runtime(config={"model": {}}, store_path=db)
            try:
                restored_event = restored.store.get_event(event.event_id)
                self.assertIsNotNone(restored_event)
                assert restored_event is not None
                result = restored._resume_native_completion(
                    restored_event,
                    restored.store.get_working_state(),
                )
                self.assertIsNone(result)
                recovered_child = next(
                    item
                    for item in restored.work_ledger.list_work_items("restart-roll")
                    if item.work_item_id == child.work_item_id
                )
                self.assertEqual(recovered_child.status, "completed")
                self.assertEqual(
                    restored.store.get_working_state().stage,
                    "native_deliberation",
                )
                self.assertIsNone(restored.store.get_event_outcome(event.event_id))
                recovered_root = restored.work_ledger.work_item_for_event(event.event_id)
                self.assertIsNotNone(recovered_root)
                assert recovered_root is not None
                self.assertNotEqual(recovered_root.status, "completed")
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
