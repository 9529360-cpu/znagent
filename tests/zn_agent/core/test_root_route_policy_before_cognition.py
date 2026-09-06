from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.cognitive_resource import CognitiveIncrement, CognitiveResourceWorkerFactory
from zn_agent.core.models import ModelRoute
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.router import NoRouteAvailable
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


CRITERIA = [
    "The requested local product has a runnable core path.",
    "The requested result can be independently verified from the attached workspace.",
]


class _PolicyProbeResource:
    def __init__(self, route, calls):
        self.route = route
        self.calls = calls

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        self.calls.append(
            {
                "route_id": self.route.route_id,
                "provider": self.route.provider,
                "question": question,
                "context": context,
            }
        )
        return CognitiveIncrement(
            text=json.dumps({"zn_root_acceptance": {"criteria": CRITERIA}}),
            provider=self.route.provider,
            model=self.route.model,
        )


class RootRoutePolicyBeforeCognitionTests(unittest.TestCase):
    @staticmethod
    def _attach_root(resident, root: Path, *, thread_id: str, task: str, payload: dict):
        workspace = root / f"{thread_id}-workspace"
        workspace.mkdir()
        control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
        ledger = control.ledger
        ledger.create_thread(thread_id=thread_id, title=thread_id)
        ledger.attach_workspace(thread_id, workspace, name=f"{thread_id} workspace")
        _, event = control.start(
            thread_id,
            task,
            payload={"model_policy": "on_demand", **payload},
        )
        return ledger, event

    def test_initial_root_cognition_filters_forbidden_provider_before_factory_or_context_delivery(self) -> None:
        calls: list[dict[str, str]] = []
        created_routes: list[str] = []

        def build_resource(route):
            created_routes.append(route.route_id)
            return _PolicyProbeResource(route, calls)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident = build_resident_runtime(config={"model": {}}, store_path=root / "kernel.db")
            try:
                resident.kernel.reconfigure_resources(
                    routes=[
                        ModelRoute(
                            route_id="anthropic-preferred",
                            provider="anthropic",
                            model="claude-policy-probe",
                            capabilities={"general": 1.0, "reasoning": 1.0},
                            reliability=1.0,
                        ),
                        ModelRoute(
                            route_id="openai-allowed",
                            provider="openai",
                            model="gpt-policy-probe",
                            capabilities={"general": 0.7, "reasoning": 0.7},
                            reliability=0.7,
                        ),
                    ],
                    worker_factory=CognitiveResourceWorkerFactory(resource_builder=build_resource),
                    max_attempts=1,
                    resource_status={"available": True, "error": None},
                )
                ledger, event = self._attach_root(
                    resident,
                    root,
                    thread_id="root-policy",
                    task="不要让 Claude 接触这个项目。开发一个可运行的本地小工具。",
                    payload={},
                )

                accepted = None
                for _ in range(96):
                    terminal = resident.live_once()
                    self.assertIsNone(terminal)
                    item = ledger.work_item_for_event(event.event_id)
                    if item is not None and item.acceptance_criteria:
                        accepted = item
                        break

                self.assertIsNotNone(accepted)
                self.assertEqual(created_routes, ["openai-allowed"])
                self.assertEqual([call["provider"] for call in calls], ["openai"])
                self.assertFalse(any(call["provider"] == "anthropic" for call in calls))

                thread = ledger.get_thread("root-policy")
                self.assertIsNotNone(thread)
                assert thread is not None
                self.assertEqual(
                    thread.metadata.get("route_policy"),
                    {"denied_providers": ["anthropic"]},
                )
                self.assertIn('"denied_providers": [', calls[0]["context"])
                self.assertIn('"anthropic"', calls[0]["context"])
            finally:
                resident.store.close()

    def test_explicit_allowlist_is_durable_and_filters_before_first_provider_construction(self) -> None:
        calls: list[dict[str, str]] = []
        created_routes: list[str] = []

        def build_resource(route):
            created_routes.append(route.route_id)
            return _PolicyProbeResource(route, calls)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            resident = build_resident_runtime(config={"model": {}}, store_path=db)
            try:
                resident.kernel.reconfigure_resources(
                    routes=[
                        ModelRoute(
                            route_id="anthropic-preferred",
                            provider="anthropic",
                            model="claude-policy-probe",
                            capabilities={"general": 1.0, "reasoning": 1.0},
                            reliability=1.0,
                        ),
                        ModelRoute(
                            route_id="openai-allowed",
                            provider="openai",
                            model="gpt-policy-probe",
                            capabilities={"general": 0.8, "reasoning": 0.8},
                            reliability=0.8,
                        ),
                    ],
                    worker_factory=CognitiveResourceWorkerFactory(resource_builder=build_resource),
                    max_attempts=1,
                    resource_status={"available": True, "error": None},
                )
                ledger, event = self._attach_root(
                    resident,
                    root,
                    thread_id="explicit-policy",
                    task="开发一个可运行的本地小工具。",
                    payload={"route_policy": {"allowed_providers": ["openai"]}},
                )

                accepted = None
                for _ in range(96):
                    terminal = resident.live_once()
                    self.assertIsNone(terminal)
                    item = ledger.work_item_for_event(event.event_id)
                    if item is not None and item.acceptance_criteria:
                        accepted = item
                        break

                self.assertIsNotNone(accepted)
                self.assertEqual(created_routes, ["openai-allowed"])
                self.assertEqual([call["provider"] for call in calls], ["openai"])
                thread = ledger.get_thread("explicit-policy")
                self.assertIsNotNone(thread)
                assert thread is not None
                self.assertEqual(
                    thread.metadata.get("route_policy"),
                    {"allowed_providers": ["openai"]},
                )
            finally:
                resident.store.close()

            restarted = build_resident_runtime(config={"model": {}}, store_path=db)
            try:
                thread = restarted.work_ledger.get_thread("explicit-policy")
                self.assertIsNotNone(thread)
                assert thread is not None
                self.assertEqual(
                    thread.metadata.get("route_policy"),
                    {"allowed_providers": ["openai"]},
                )
            finally:
                restarted.store.close()

    def test_initial_local_only_root_fails_closed_without_constructing_cloud_provider(self) -> None:
        created_routes: list[str] = []

        def build_resource(route):
            created_routes.append(route.route_id)
            raise AssertionError("cloud provider factory must not be reached for local-only Work")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident = build_resident_runtime(config={"model": {}}, store_path=root / "kernel.db")
            try:
                resident.kernel.reconfigure_resources(
                    routes=[
                        ModelRoute(
                            route_id="openai-cloud",
                            provider="openai",
                            model="gpt-cloud",
                            capabilities={"general": 1.0, "reasoning": 1.0},
                            reliability=1.0,
                            metadata={"local": False},
                        )
                    ],
                    worker_factory=CognitiveResourceWorkerFactory(resource_builder=build_resource),
                    max_attempts=1,
                    resource_status={"available": True, "error": None},
                )
                ledger, _ = self._attach_root(
                    resident,
                    root,
                    thread_id="local-root",
                    task="这个项目只允许本地模型处理。开发一个可运行的小工具。",
                    payload={},
                )

                for _ in range(96):
                    try:
                        result = resident.live_once()
                    except NoRouteAvailable:
                        break
                    if result is not None and not result.success:
                        break
                    state = resident.store.get_working_state()
                    if "no eligible model route" in str(state.data.get("local_failure") or "").lower():
                        break

                self.assertEqual(created_routes, [])
                thread = ledger.get_thread("local-root")
                self.assertIsNotNone(thread)
                assert thread is not None
                self.assertEqual(
                    thread.metadata.get("route_policy"),
                    {"data_classification": "local_only"},
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
