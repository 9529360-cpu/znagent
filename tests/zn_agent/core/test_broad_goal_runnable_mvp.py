from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.cognitive_resource import CognitiveIncrement, CognitiveResourceWorkerFactory
from zn_agent.core.models import ModelRoute
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
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


class BroadGoalRunnableMvpTests(unittest.TestCase):
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
                resident.kernel.reconfigure_resources(
                    routes=[
                        ModelRoute(
                            route_id="e2e-26-broad-goal-cognition",
                            provider="fixture",
                            model="bounded-planning-fixture",
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

                print(
                    "ZN_E2E_26_CURRENT_FAILURE="
                    f"model_calls={cognition.calls};"
                    f"resident_success={getattr(result, 'success', None)};"
                    f"work_item_status={progress.get('work_item_status')};"
                    f"workspace_files={len(after_files)}"
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
