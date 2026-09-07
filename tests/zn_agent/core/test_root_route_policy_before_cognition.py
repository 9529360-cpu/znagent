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

    @staticmethod
    def _caps(score: float) -> dict[str, float]:
        return {
            "general": score,
            "reasoning": score,
            "language_understanding": score,
        }

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
                            capabilities=self._caps(1.0),
                            reliability=1.0,
                        ),
                        ModelRoute(
                            route_id="openai-allowed",
                            provider="openai",
                            model="gpt-policy-probe",
                            capabilities=self._caps(0.7),
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

                # Policy is durable before the Resident can reach the earlier
                # desktop semantic-understanding cognition path.
                thread = ledger.get_thread("root-policy")
                self.assertIsNotNone(thread)
                assert thread is not None
                self.assertEqual(
                    thread.metadata.get("route_policy"),
                    {"denied_providers": ["anthropic"]},
                )
                persisted_event = resident.store.get_event(event.event_id)
                self.assertIsNotNone(persisted_event)
                assert persisted_event is not None
                self.assertEqual(
                    persisted_event.payload.get("route_policy"),
                    {"denied_providers": ["anthropic"]},
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
                self.assertTrue(created_routes)
                self.assertEqual(set(created_routes), {"openai-allowed"})
                self.assertTrue(calls)
                self.assertEqual({call["provider"] for call in calls}, {"openai"})
                self.assertFalse(any(call["provider"] == "anthropic" for call in calls))

                # The first direct semantic cognition Goal itself inherited the
                # event policy even though it bypasses CognitionRequest.context.
                semantic_goal = resident.store.get_goal(
                    f"goal-desktop-understanding-{event.event_id}"
                )
                self.assertIsNotNone(semantic_goal)
                assert semantic_goal is not None
                self.assertEqual(
                    semantic_goal.metadata.get("route_policy"),
                    {"denied_providers": ["anthropic"]},
                )
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
                            capabilities=self._caps(1.0),
                            reliability=1.0,
                        ),
                        ModelRoute(
                            route_id="openai-allowed",
                            provider="openai",
                            model="gpt-policy-probe",
                            capabilities=self._caps(0.8),
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
                self.assertTrue(created_routes)
                self.assertEqual(set(created_routes), {"openai-allowed"})
                self.assertEqual({call["provider"] for call in calls}, {"openai"})
                thread = ledger.get_thread("explicit-policy")
                self.assertIsNotNone(thread)
                assert thread is not None
                self.assertEqual(
                    thread.metadata.get("route_policy"),
                    {"allowed_providers": ["openai"]},
                )
                persisted_event = resident.store.get_event(event.event_id)
                self.assertIsNotNone(persisted_event)
                assert persisted_event is not None
                self.assertEqual(
                    persisted_event.payload.get("route_policy"),
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

    def test_steered_event_inherits_allowlist_before_restart_and_earliest_cognition(self) -> None:
        calls: list[dict[str, str]] = []
        created_routes: list[str] = []

        def build_resource(route):
            created_routes.append(route.route_id)
            return _PolicyProbeResource(route, calls)

        routes = [
            ModelRoute(
                route_id="anthropic-preferred",
                provider="anthropic",
                model="claude-policy-probe",
                capabilities=self._caps(1.0),
                reliability=1.0,
            ),
            ModelRoute(
                route_id="openai-allowed",
                provider="openai",
                model="gpt-policy-probe",
                capabilities=self._caps(0.7),
                reliability=0.7,
            ),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            workspace = root / "steer-policy-workspace"
            workspace.mkdir()
            resident = build_resident_runtime(config={"model": {}}, store_path=db)
            control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
            ledger = control.ledger
            ledger.create_thread(thread_id="steer-policy", title="steer-policy")
            ledger.attach_workspace("steer-policy", workspace, name="steer-policy workspace")
            try:
                resident.kernel.reconfigure_resources(
                    routes=routes,
                    worker_factory=CognitiveResourceWorkerFactory(resource_builder=build_resource),
                    max_attempts=1,
                    resource_status={"available": True, "error": None},
                )
                _, original = control.start(
                    "steer-policy",
                    "开发一个可运行的本地小工具。",
                    payload={
                        "model_policy": "on_demand",
                        "route_policy": {"allowed_providers": ["openai"]},
                    },
                )
                _, steered = control.start(
                    "ui-ingress",
                    "继续刚才，先把核心记账跑起来。",
                    payload={"model_policy": "on_demand"},
                )
                self.assertNotEqual(steered.event_id, original.event_id)

                thread = ledger.get_thread("steer-policy")
                self.assertIsNotNone(thread)
                assert thread is not None
                self.assertEqual(
                    thread.metadata.get("route_policy"),
                    {"allowed_providers": ["openai"]},
                )
                persisted = resident.store.get_event(steered.event_id)
                self.assertIsNotNone(persisted)
                assert persisted is not None
                self.assertEqual(
                    persisted.payload.get("route_policy"),
                    {"allowed_providers": ["openai"]},
                )
                self.assertEqual(created_routes, [])
            finally:
                resident.store.close()

            restarted = build_resident_runtime(config={"model": {}}, store_path=db)
            try:
                restarted.kernel.reconfigure_resources(
                    routes=routes,
                    worker_factory=CognitiveResourceWorkerFactory(resource_builder=build_resource),
                    max_attempts=1,
                    resource_status={"available": True, "error": None},
                )
                persisted = restarted.store.get_event(steered.event_id)
                self.assertIsNotNone(persisted)
                assert persisted is not None
                self.assertEqual(
                    persisted.payload.get("route_policy"),
                    {"allowed_providers": ["openai"]},
                )

                semantic_goal = None
                for _ in range(32):
                    restarted.live_once()
                    semantic_goal = restarted.store.get_goal(
                        f"goal-desktop-understanding-{steered.event_id}"
                    )
                    if semantic_goal is not None:
                        break

                self.assertIsNotNone(semantic_goal)
                assert semantic_goal is not None
                self.assertEqual(
                    semantic_goal.metadata.get("route_policy"),
                    {"allowed_providers": ["openai"]},
                )
                self.assertTrue(created_routes)
                self.assertEqual(set(created_routes), {"openai-allowed"})
                self.assertTrue(calls)
                self.assertEqual({call["provider"] for call in calls}, {"openai"})
            finally:
                restarted.store.close()

    def test_initial_local_only_root_fails_closed_before_earliest_semantic_cognition(self) -> None:
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
                            capabilities=self._caps(1.0),
                            reliability=1.0,
                            metadata={"local": False},
                        )
                    ],
                    worker_factory=CognitiveResourceWorkerFactory(resource_builder=build_resource),
                    max_attempts=1,
                    resource_status={"available": True, "error": None},
                )
                ledger, event = self._attach_root(
                    resident,
                    root,
                    thread_id="local-root",
                    task="这个项目只允许本地模型处理。开发一个可运行的小工具。",
                    payload={},
                )

                thread = ledger.get_thread("local-root")
                self.assertIsNotNone(thread)
                assert thread is not None
                self.assertEqual(
                    thread.metadata.get("route_policy"),
                    {"data_classification": "local_only"},
                )
                persisted_event = resident.store.get_event(event.event_id)
                self.assertIsNotNone(persisted_event)
                assert persisted_event is not None
                self.assertEqual(
                    persisted_event.payload.get("route_policy"),
                    {"data_classification": "local_only"},
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
                semantic_goal = resident.store.get_goal(
                    f"goal-desktop-understanding-{event.event_id}"
                )
                self.assertIsNotNone(semantic_goal)
                assert semantic_goal is not None
                self.assertEqual(
                    semantic_goal.metadata.get("route_policy"),
                    {"data_classification": "local_only"},
                )
                durable = semantic_goal.metadata.get("_durable_external_run")
                self.assertIsInstance(durable, dict)
                self.assertEqual(durable.get("attempts"), [])
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
