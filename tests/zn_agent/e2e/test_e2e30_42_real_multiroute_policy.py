from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.models import ModelRoute
from zn_agent.core.provider_bridge import build_resident_runtime, build_zn_cognitive_resource_plan
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


GOAL = (
    "帮我开发一个本地个人记账小产品。先调研一个权威的当前资料来确认核心功能，"
    "然后开发一个可运行的最小版本，实际运行测试，再做一次独立 review/test。"
    "不要做登录，不要发布，不要发消息；最终必须用当前工作区和持久化数据的真实证据验收。"
)
_MAX_PULSES = 560


def _copy_route(route: ModelRoute, *, capabilities: dict[str, float], reliability: float) -> ModelRoute:
    return ModelRoute(
        route_id=route.route_id,
        provider=route.provider,
        model=route.model,
        capabilities=dict(capabilities),
        reliability=reliability,
        cost_weight=route.cost_weight,
        latency_weight=route.latency_weight,
        metadata=dict(route.metadata),
    )


def _two_distinct_provider_routes(routes: list[ModelRoute]) -> tuple[ModelRoute, ModelRoute] | None:
    usable = [
        route
        for route in routes
        if route.provider != "none" and str(route.provider).strip() and str(route.model).strip()
    ]
    for index, first in enumerate(usable):
        for second in usable[index + 1 :]:
            if first.provider.strip().lower() != second.provider.strip().lower():
                return first, second
    return None


def _kernel_route_snapshot(resident, model_goal_id: str) -> dict:
    goal = resident.store.get_goal(model_goal_id)
    if goal is None or not isinstance(goal.metadata, dict):
        return {}
    durable = goal.metadata.get("_durable_external_run")
    if not isinstance(durable, dict):
        return {}
    attempts = durable.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        return {}
    last = attempts[-1]
    route = last.get("route") if isinstance(last, dict) else None
    return dict(route) if isinstance(route, dict) else {}


class E2E30And42RealMultiRoutePolicyTests(unittest.TestCase):
    def test_real_delegated_work_uses_two_providers_by_capability_and_keeps_durable_provenance(self) -> None:
        if os.environ.get("ZN_E2E30_42_REAL_MODELS", "").strip().lower() not in {"1", "true", "yes"}:
            self.skipTest("set ZN_E2E30_42_REAL_MODELS=1 only on the guarded real-model runner")

        config = __import__("zn_agent.core.config", fromlist=["load_zn_config"]).load_zn_config()
        plan = build_zn_cognitive_resource_plan(config)
        pair = _two_distinct_provider_routes(plan.routes)
        self.assertTrue(plan.available, plan.error)
        self.assertIsNotNone(
            pair,
            "E2E-30/42 requires at least two actually configured routes from distinct real providers",
        )
        assert pair is not None
        research_base, coding_base = pair
        research_route = _copy_route(
            research_base,
            capabilities={"general": 0.70, "reasoning": 1.0, "research": 1.0},
            reliability=0.95,
        )
        coding_route = _copy_route(
            coding_base,
            capabilities={"general": 0.75, "reasoning": 1.0, "coding": 1.0},
            reliability=0.95,
        )

        with tempfile.TemporaryDirectory(prefix="zn-e2e30-42-multiroute-") as tmp:
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
            resident.kernel.reconfigure_resources(
                routes=[research_route, coding_route],
                worker_factory=plan.worker_factory,
                max_attempts=1,
                resource_status={"available": True, "error": None},
            )
            control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
            ingress = control.ledger
            work = resident.work_ledger
            ingress.create_thread(thread_id="e2e-30-42-real", title="Real multi-provider Work")
            ingress.attach_workspace("e2e-30-42-real", workspace, name="E2E30/42 workspace")
            _, event = control.start(
                "e2e-30-42-real",
                GOAL,
                payload={"model_policy": "on_demand"},
            )

            terminal = None
            try:
                for pulse in range(1, _MAX_PULSES + 1):
                    candidate = resident.live_once()
                    if candidate is not None and candidate.event.event_id == event.event_id:
                        terminal = candidate
                        break
                    if pulse % 50 == 0:
                        runs = work.list_worker_runs(thread_id="e2e-30-42-real", limit=96)
                        print(
                            "ZN_E2E30_42_HEARTBEAT="
                            + json.dumps(
                                {
                                    "pulse": pulse,
                                    "workers": [
                                        {
                                            "id": run.worker_run_id,
                                            "kind": run.executor_kind,
                                            "state": run.state,
                                            "route": run.model_route_id,
                                            "verification": run.verification_status,
                                        }
                                        for run in runs[-12:]
                                    ],
                                },
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )

                self.assertIsNotNone(terminal, "real multi-provider Work did not reach Root verification")
                assert terminal is not None
                self.assertTrue(terminal.success, terminal.reason)
                version = work.plan_version("e2e-30-42-real")
                root = work.work_item_for_event(event.event_id)
                self.assertIsNotNone(root)
                assert root is not None
                self.assertEqual(root.plan_version, version)
                self.assertEqual(root.status, "completed")
                self.assertIn("zn_independent_acceptance", root.result or "")

                runs = [
                    run
                    for run in work.list_worker_runs(thread_id="e2e-30-42-real", limit=96)
                    if run.plan_version == version and run.verification_status == "accepted"
                ]
                research = next(run for run in runs if run.executor_kind == "research")
                coding = next(run for run in runs if run.executor_kind == "coding")
                review = next(run for run in runs if run.executor_kind == "review")
                self.assertEqual(research.model_route_id, research_route.route_id)
                self.assertEqual(coding.model_route_id, coding_route.route_id)
                self.assertEqual(review.model_route_id, coding_route.route_id)
                self.assertNotEqual(research.model_route_id, coding.model_route_id)

                provenance = []
                for run in (research, coding, review):
                    route = _kernel_route_snapshot(resident, run.model_goal_id)
                    self.assertEqual(route.get("route_id"), run.model_route_id)
                    self.assertTrue(str(route.get("provider") or "").strip())
                    self.assertTrue(str(route.get("model") or "").strip())
                    provenance.append(
                        {
                            "worker_run_id": run.worker_run_id,
                            "work_item_id": run.work_item_id,
                            "plan_version": run.plan_version,
                            "model_route_id": run.model_route_id,
                            "provider": route.get("provider"),
                            "model": route.get("model"),
                            "executor_kind": run.executor_kind,
                        }
                    )
                self.assertEqual(provenance[0]["provider"], research_route.provider)
                self.assertEqual(provenance[1]["provider"], coding_route.provider)
                self.assertEqual(provenance[2]["provider"], coding_route.provider)
                print(
                    "ZN_E2E30_42_ROUTES="
                    + json.dumps(
                        {
                            "research": {
                                "route_id": research_route.route_id,
                                "provider": research_route.provider,
                                "model": research_route.model,
                            },
                            "coding": {
                                "route_id": coding_route.route_id,
                                "provider": coding_route.provider,
                                "model": coding_route.model,
                            },
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                print("ZN_E2E30_42_WORKERS=" + json.dumps(provenance, ensure_ascii=False), flush=True)
                print("ZN_E2E30_42_ROOT_ACCEPTANCE=" + str(root.result or ""), flush=True)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
