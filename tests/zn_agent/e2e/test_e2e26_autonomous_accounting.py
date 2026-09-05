from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.broad_goal_autonomous_resident import BroadGoalAutonomousResidentRuntime
from zn_agent.core.config import load_zn_config
from zn_agent.core.provider_bridge import (
    build_resident_runtime,
    build_zn_cognitive_resource_plan,
)
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


BROAD_GOAL = (
    "帮我开发一个本地个人记账小产品。先调研一下同类产品最核心的功能，然后自己推进，"
    "做出一个能真正运行的第一版。第一版不要做登录，不要做复杂设计，先把核心记账跑起来。"
)
STEERING = "登录先不要做，界面保持简单，先确保新增收支和本地保存能用。"


class E2E26AutonomousAccountingTests(unittest.TestCase):
    """Real-provider acceptance: the harness supplies goals, never the product solution."""

    def test_broad_goal_reaches_evidence_bound_runnable_mvp_without_solution_fixture(self) -> None:
        config = load_zn_config()
        plan = build_zn_cognitive_resource_plan(config)
        if not plan.available or all(route.provider == "none" for route in plan.routes):
            self.skipTest(
                "E2E-26 real autonomous acceptance requires a configured real cognitive resource; "
                "fixture cognition must not stand in for the product-development model"
            )
        if os.environ.get("ZN_E2E26_REAL_MODEL", "").strip().lower() not in {"1", "true", "yes"}:
            self.skipTest(
                "set ZN_E2E26_REAL_MODEL=1 only on a runner intended to spend a real model call budget"
            )

        with tempfile.TemporaryDirectory(prefix="zn-e2e26-autonomous-accounting-") as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            subprocess.run(
                ["git", "init", "-q", str(workspace)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            resident = build_resident_runtime(config=config, store_path=root / "kernel.db")
            self.assertIsInstance(resident, BroadGoalAutonomousResidentRuntime)
            control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
            ledger = control.ledger
            ledger.create_thread(thread_id="e2e-26-real", title="Autonomous local accounting MVP")
            ledger.attach_workspace("e2e-26-real", workspace, name="Autonomous Accounting Workspace")

            _, event = control.start(
                "e2e-26-real",
                BROAD_GOAL,
                payload={"model_policy": "on_demand"},
            )
            original_event_id = event.event_id
            original_root = ledger.work_item_for_event(original_event_id)
            self.assertIsNotNone(original_root)
            assert original_root is not None
            self.assertEqual(
                original_root.acceptance_criteria,
                [],
                "the harness must not pre-author the accounting product acceptance contract",
            )
            self.assertEqual(
                [path for path in workspace.rglob("*") if path.is_file() and ".git" not in path.parts],
                [],
                "the workspace must not contain a hidden accounting implementation fixture",
            )

            criteria_formed_before_child = False
            research_seen = False
            steering_applied = False
            steered_event_id: str | None = None
            terminal = None

            try:
                for _ in range(900):
                    candidate = resident.live_once()
                    if candidate is not None:
                        terminal = candidate
                        if steering_applied and candidate.event.event_id == steered_event_id:
                            break
                        if not steering_applied and candidate.event.event_id == original_event_id:
                            self.fail(
                                "the original broad Root terminalized before the required mid-flight steering"
                            )

                    current_items = ledger.list_work_items("e2e-26-real", limit=256)
                    current_version = ledger.plan_version("e2e-26-real")
                    active_roots = [
                        item
                        for item in current_items
                        if item.parent_work_item_id is None
                        and item.plan_version == current_version
                        and item.status in {"running", "blocked", "completed"}
                    ]
                    if active_roots:
                        active_root = active_roots[-1]
                        current_children = [
                            item
                            for item in current_items
                            if item.parent_work_item_id == active_root.work_item_id
                            and item.plan_version == current_version
                        ]
                        if active_root.acceptance_criteria and not current_children:
                            criteria_formed_before_child = True
                        if any(
                            item.status == "completed"
                            and any(
                                criterion.startswith("page_read:")
                                for criterion in item.acceptance_criteria
                            )
                            for item in current_children
                        ):
                            research_seen = True

                    if research_seen and not steering_applied:
                        _, steered_event = ledger.steer_active(
                            "e2e-26-real",
                            original_event_id,
                            STEERING,
                            objective=STEERING,
                            reference="current",
                            payload={"model_policy": "on_demand"},
                        )
                        steering_applied = True
                        steered_event_id = steered_event.event_id

                self.assertTrue(
                    criteria_formed_before_child,
                    "ZN must form and persist its own Root acceptance criteria before materializing execution WorkItems",
                )
                self.assertTrue(
                    research_seen,
                    "the user's explicit research request must produce real managed-browser evidence",
                )
                self.assertTrue(steering_applied, "the fixed E2E-27 steering was never applied mid-flight")
                self.assertIsNotNone(steered_event_id)
                self.assertIsNotNone(terminal, "the steered autonomous Root never reached terminal evidence")
                assert terminal is not None and steered_event_id is not None
                self.assertEqual(terminal.event.event_id, steered_event_id)
                self.assertTrue(terminal.success, terminal.reason)
                self.assertEqual(terminal.execution_path.value, "body")

                items = ledger.list_work_items("e2e-26-real", limit=256)
                current_version = ledger.plan_version("e2e-26-real")
                self.assertGreaterEqual(current_version, 2)
                current_root = ledger.work_item_for_event(steered_event_id)
                self.assertIsNotNone(current_root)
                assert current_root is not None
                self.assertEqual(current_root.status, "completed")
                self.assertTrue(current_root.acceptance_criteria)
                self.assertIn("zn_independent_acceptance", current_root.result or "")

                current_children = [
                    item
                    for item in items
                    if item.parent_work_item_id == current_root.work_item_id
                    and item.plan_version == current_version
                ]
                self.assertTrue(
                    any(
                        item.status == "completed"
                        and any(c.startswith("text_equals:") for c in item.acceptance_criteria)
                        for item in current_children
                    ),
                    "current plan has no verified File/code movement",
                )
                command_children = [
                    item
                    for item in current_children
                    if item.status == "completed"
                    and any(c.startswith("command_exit:") for c in item.acceptance_criteria)
                ]
                self.assertTrue(command_children, "current plan has no verified real Terminal execution")
                verifiers = [
                    item
                    for item in current_children
                    if item.status == "completed"
                    and any(
                        c.startswith("independent_python_verification:")
                        for c in item.acceptance_criteria
                    )
                ]
                self.assertEqual(
                    len(verifiers),
                    1,
                    "Root acceptance must come from exactly one dedicated current-plan verifier WorkItem",
                )
                self.assertTrue(str(verifiers[0].result or "").strip())

                progress = ledger.progress("e2e-26-real", steered_event_id)
                self.assertTrue(progress.get("accepted"))
                old_progress = ledger.progress("e2e-26-real", original_event_id)
                self.assertTrue(old_progress.get("stale"))
                self.assertFalse(old_progress.get("accepted"))

                product_files = [
                    path
                    for path in workspace.rglob("*")
                    if path.is_file() and ".git" not in path.parts
                ]
                self.assertTrue(product_files, "autonomous Work produced no real workspace artifact")
                git_status = subprocess.run(
                    ["git", "-C", str(workspace), "status", "--porcelain"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                ).stdout.strip()
                self.assertTrue(git_status, "Git sees no actual product workspace changes")

                acceptance = json.loads(current_root.result or "{}").get("zn_independent_acceptance")
                self.assertIsInstance(acceptance, dict)
                self.assertEqual(int(acceptance["plan_version"]), current_version)
                self.assertEqual(acceptance["verifier_work_item_id"], verifiers[0].work_item_id)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
