from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.broad_goal_autonomous_resident import BroadGoalAutonomousResidentRuntime
from zn_agent.core.config import load_zn_config
from zn_agent.core.provider_bridge import build_resident_runtime, build_zn_cognitive_resource_plan
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


GOAL = (
    "帮我开发一个本地个人记账小产品。先调研一个权威的当前资料来确认核心功能，"
    "然后开发一个可运行的最小版本，实际运行测试，再做一次独立 review/test。"
    "不要做登录，不要发布，不要发消息；最终必须用当前工作区和持久化数据的真实证据验收。"
)
_MAX_PULSES = 520


class E2E29OneModelMultiWorkerTests(unittest.TestCase):
    def test_one_real_model_route_serves_distinct_research_coding_review_workers(self) -> None:
        config = load_zn_config()
        plan = build_zn_cognitive_resource_plan(config)
        real_routes = [route for route in plan.routes if route.provider != "none" and str(route.model).strip()]
        if not plan.available or not real_routes:
            self.skipTest("E2E-29 real acceptance requires one configured external cognitive resource")
        if os.environ.get("ZN_E2E29_REAL_MODEL", "").strip().lower() not in {"1", "true", "yes"}:
            self.skipTest("set ZN_E2E29_REAL_MODEL=1 only on the guarded real-model runner")

        only_route = real_routes[0]
        with tempfile.TemporaryDirectory(prefix="zn-e2e29-one-model-workers-") as tmp:
            root_dir = Path(tmp)
            workspace = root_dir / "workspace"
            workspace.mkdir()
            subprocess.run(
                ["git", "init", "-q", str(workspace)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            resident = build_resident_runtime(config=config, store_path=root_dir / "kernel.db")
            self.assertIsInstance(resident, BroadGoalAutonomousResidentRuntime)
            resident.kernel.reconfigure_resources(
                routes=[only_route],
                worker_factory=plan.worker_factory,
                max_attempts=1,
                resource_status={"available": True, "error": None},
            )
            control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
            ledger = control.ledger
            ledger.create_thread(thread_id="e2e-29-real", title="One model multi worker")
            ledger.attach_workspace("e2e-29-real", workspace, name="E2E29 workspace")
            _, event = control.start("e2e-29-real", GOAL, payload={"model_policy": "on_demand"})

            terminal = None
            try:
                for pulse in range(1, _MAX_PULSES + 1):
                    candidate = resident.live_once()
                    if candidate is not None and candidate.event.event_id == event.event_id:
                        terminal = candidate
                        break
                    if pulse % 40 == 0:
                        runs = ledger.list_worker_runs(thread_id="e2e-29-real", limit=64)
                        print(
                            "ZN_E2E29_HEARTBEAT="
                            + json.dumps(
                                {
                                    "pulse": pulse,
                                    "stage": resident.store.get_working_state().stage,
                                    "workers": [
                                        {
                                            "id": run.worker_run_id,
                                            "kind": run.executor_kind,
                                            "state": run.state,
                                            "route": run.model_route_id,
                                            "verification": run.verification_status,
                                        }
                                        for run in runs
                                    ],
                                },
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )

                self.assertIsNotNone(terminal, "E2E-29 did not reach evidence-bound Root completion")
                assert terminal is not None
                self.assertTrue(terminal.success, terminal.reason)

                current_version = ledger.plan_version("e2e-29-real")
                root = ledger.work_item_for_event(event.event_id)
                self.assertIsNotNone(root)
                assert root is not None
                self.assertEqual(root.plan_version, current_version)
                self.assertEqual(root.status, "completed")
                self.assertIn("zn_independent_acceptance", root.result or "")

                runs = ledger.list_worker_runs(thread_id="e2e-29-real", limit=64)
                current_runs = [run for run in runs if run.plan_version == current_version]
                self.assertGreaterEqual(len(current_runs), 3)
                self.assertGreaterEqual(len({run.worker_run_id for run in current_runs}), 3)
                self.assertTrue({"research", "coding", "review"}.issubset({run.executor_kind for run in current_runs}))
                route_ids = {run.model_route_id for run in current_runs if run.model_route_id}
                self.assertEqual(route_ids, {only_route.route_id})
                self.assertGreater(len({run.worker_run_id for run in current_runs}), len(route_ids))
                self.assertTrue(all(run.work_item_id for run in current_runs))
                self.assertTrue(all(run.verification_status == "accepted" for run in current_runs))

                research = next(run for run in current_runs if run.executor_kind == "research")
                coding = next(run for run in current_runs if run.executor_kind == "coding")
                review = next(run for run in current_runs if run.executor_kind == "review")
                self.assertNotEqual(research.tool_scope, coding.tool_scope)
                self.assertNotEqual(coding.authority_scope, review.authority_scope)
                self.assertNotIn("workspace.write", research.tool_scope)
                self.assertNotIn("workspace.write", review.tool_scope)
                self.assertIn("workspace.write", coding.tool_scope)

                goals = [resident.store.get_goal(run.model_goal_id) for run in current_runs]
                self.assertTrue(all(goal is not None for goal in goals))
                packs = []
                for goal, run in zip(goals, current_runs):
                    assert goal is not None
                    raw = goal.metadata.get("cognition_request") if isinstance(goal.metadata, dict) else None
                    context = raw.get("context") if isinstance(raw, dict) else None
                    pack = context.get("worker_context_pack") if isinstance(context, dict) else None
                    self.assertIsInstance(pack, dict)
                    assert isinstance(pack, dict)
                    self.assertEqual(pack["plan_version"], current_version)
                    self.assertEqual(pack["tool_scope"], list(run.tool_scope))
                    self.assertNotIn("transcript", pack)
                    self.assertNotIn("memory", pack)
                    self.assertNotIn("self_model", pack)
                    packs.append(json.dumps(pack, ensure_ascii=False, sort_keys=True))
                self.assertGreaterEqual(len(set(packs)), 3, "delegated context packs must be isolated per WorkItem")

                items = ledger.list_work_items("e2e-29-real", limit=256)
                current_children = [
                    item for item in items
                    if item.parent_work_item_id == root.work_item_id and item.plan_version == current_version
                ]
                self.assertTrue(any(any(c.startswith("page_read:") for c in item.acceptance_criteria) and item.status == "completed" for item in current_children))
                self.assertTrue(any(any(c.startswith("text_equals:") for c in item.acceptance_criteria) and item.status == "completed" for item in current_children))
                self.assertTrue(any(any(c.startswith("command_exit:") for c in item.acceptance_criteria) and item.status == "completed" for item in current_children))
                verifiers = [item for item in current_children if item.status == "completed" and any(c.startswith("independent_python_verification:") for c in item.acceptance_criteria)]
                self.assertEqual(len(verifiers), 1)
                self.assertNotEqual(review.work_item_id, verifiers[0].work_item_id, "review Worker must not own Root acceptance")

                product_files = [path for path in workspace.rglob("*") if path.is_file() and ".git" not in path.parts]
                self.assertTrue(product_files)
                git_status = subprocess.run(
                    ["git", "-C", str(workspace), "status", "--porcelain"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                ).stdout.strip()
                self.assertTrue(git_status)

                print(
                    "ZN_E2E29_WORKERS="
                    + json.dumps(
                        [
                            {
                                "worker_run_id": run.worker_run_id,
                                "work_item_id": run.work_item_id,
                                "executor_kind": run.executor_kind,
                                "model_goal_id": run.model_goal_id,
                                "model_route_id": run.model_route_id,
                                "tool_scope": list(run.tool_scope),
                                "authority_scope": list(run.authority_scope),
                                "claimed_completion": run.claimed_completion,
                                "verification_status": run.verification_status,
                            }
                            for run in current_runs
                        ],
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                print("ZN_E2E29_ROOT_ACCEPTANCE=" + str(root.result or ""), flush=True)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
