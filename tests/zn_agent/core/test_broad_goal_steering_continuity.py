from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.broad_goal_research_resident import BroadGoalResearchResidentRuntime
from zn_agent.core.budget import CognitiveBudgetManager
from zn_agent.core.cognitive_resource import CognitiveIncrement, CognitiveResourceWorkerFactory
from zn_agent.core.models import ModelRoute, utc_now
from zn_agent.core.provider_bridge import build_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.steerable_work import WorkItem
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


STEERING = "登录先不要做，界面保持简单，先确保新增收支和本地保存能用。"
CRITERIA = [
    "新增收入和支出能通过真实运行路径写入本地数据",
    "重启后的新进程能读回已保存记录",
]


class _CaptureBroadCognition:
    _BROAD_MARKER = "You are a bounded coding/reasoning resource assisting one durable ZN Work."

    def __init__(self) -> None:
        self.step_questions: list[str] = []

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        if self._BROAD_MARKER in question:
            self.step_questions.append(question)
            text = "not-a-structured-step"
        else:
            text = "Continue the user's current durable objective."
        return CognitiveIncrement(text=text, provider="fixture", model="steering-fixture")


def _resident(db: Path):
    kernel = build_runtime(config={"model": {}}, store_path=db)
    return BroadGoalResearchResidentRuntime(kernel=kernel, budget=CognitiveBudgetManager())


def _configure(resident, cognition) -> None:
    resident.kernel.reconfigure_resources(
        routes=[
            ModelRoute(
                route_id="steering-fixture",
                provider="fixture",
                model="steering-fixture",
                capabilities={
                    "general": 1.0,
                    "reasoning": 1.0,
                    "coding": 1.0,
                    "language_understanding": 1.0,
                },
            )
        ],
        worker_factory=CognitiveResourceWorkerFactory(resource_builder=lambda _route: cognition),
        max_attempts=1,
        resource_status={"available": True, "error": None},
    )


class BroadGoalSteeringContinuityTests(unittest.TestCase):
    def test_restart_after_steering_recovers_root_criteria_and_historical_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            workspace = root / "workspace"
            workspace.mkdir()

            first = _resident(db)
            first_control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(first))
            ledger = first_control.ledger
            ledger.create_thread(thread_id="product", title="Local product")
            ledger.attach_workspace("product", workspace, name="Product Workspace")
            _, old_event = ledger.start(
                "product",
                "开发一个本地小产品，先推进当前计划。",
                payload={"model_policy": "on_demand"},
                acceptance_criteria=CRITERIA,
            )
            old_root = ledger.work_item_for_event(old_event.event_id)
            self.assertIsNotNone(old_root)
            assert old_root is not None
            historical = WorkItem(
                work_item_id="item-historical-research",
                work_thread_id="product",
                parent_work_item_id=old_root.work_item_id,
                title="Historical research",
                objective="先调研本地优先产品的核心行为",
                status="completed",
                plan_version=old_root.plan_version,
                acceptance_criteria=["page_read: https://example.test/local-first"],
                result="LOCAL-FIRST-HISTORICAL-EVIDENCE",
                completed_at=utc_now(),
            )
            historical.updated_at = historical.completed_at or historical.updated_at
            ledger._save_item(historical)

            _, new_event = ledger.steer_active(
                "product",
                old_event.event_id,
                STEERING,
                objective=STEERING,
                reference="current",
                payload={"model_policy": "on_demand"},
            )
            new_event_id = new_event.event_id
            new_item_before = ledger.work_item_for_event(new_event_id)
            self.assertIsNotNone(new_item_before)
            assert new_item_before is not None
            self.assertEqual(new_item_before.plan_version, 2)
            self.assertEqual(new_item_before.acceptance_criteria, [])
            self.assertEqual(ledger.work_item_for_event(old_event.event_id).status, "superseded")
            self.assertEqual(historical.status, "completed")
            first.store.close()

            restored = _resident(db)
            cognition = _CaptureBroadCognition()
            _configure(restored, cognition)
            try:
                restored_ledger = RestoreAwareWorkControl(
                    RecoveryBoundedWorkLedger(restored)
                ).ledger
                restored_event = restored.store.get_event(new_event_id)
                self.assertIsNotNone(restored_event)
                assert restored_event is not None

                recovered_root = restored._criterion_bound_root(restored_event)
                self.assertIsNotNone(recovered_root)
                assert recovered_root is not None
                self.assertEqual(recovered_root.plan_version, 2)
                self.assertEqual(recovered_root.acceptance_criteria, CRITERIA)
                persisted = restored_ledger.work_item_for_event(new_event_id)
                self.assertEqual(persisted.acceptance_criteria, CRITERIA)

                for _ in range(96):
                    restored.live_once()
                    if cognition.step_questions:
                        break
                self.assertTrue(cognition.step_questions)
                question = cognition.step_questions[-1]
                self.assertIn(STEERING, question)
                self.assertIn("LOCAL-FIRST-HISTORICAL-EVIDENCE", question)
                self.assertIn("Historical completed evidence from superseded plans is context only", question)
                self.assertIn("NEVER counts as acceptance for the current plan", question)

                old_child = next(
                    item
                    for item in restored_ledger.list_work_items("product")
                    if item.work_item_id == "item-historical-research"
                )
                self.assertEqual(old_child.status, "completed")
                self.assertEqual(old_child.plan_version, 1)
                self.assertNotEqual(old_child.parent_work_item_id, recovered_root.work_item_id)
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
