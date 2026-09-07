from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.cognitive_resource import CognitiveResourceWorkerFactory
from zn_agent.core.models import ModelRoute
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.router import NoRouteAvailable
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


class RoutePolicyPersistenceValidationTests(unittest.TestCase):
    def test_invalid_mapping_fails_before_provider_construction_and_is_not_persisted(self) -> None:
        created_routes: list[str] = []

        def build_resource(route):
            created_routes.append(route.route_id)
            raise AssertionError("provider construction must not happen for invalid Work route policy")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            db = root / "kernel.db"
            resident = build_resident_runtime(config={"model": {}}, store_path=db)
            try:
                resident.kernel.reconfigure_resources(
                    routes=[
                        ModelRoute(
                            route_id="openai-cloud",
                            provider="openai",
                            model="gpt-policy-probe",
                            capabilities={"general": 1.0, "reasoning": 1.0},
                            reliability=1.0,
                        )
                    ],
                    worker_factory=CognitiveResourceWorkerFactory(resource_builder=build_resource),
                    max_attempts=1,
                    resource_status={"available": True, "error": None},
                )
                control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
                ledger = control.ledger
                ledger.create_thread(thread_id="invalid-policy", title="Invalid policy")
                ledger.attach_workspace("invalid-policy", workspace, name="workspace")
                control.start(
                    "invalid-policy",
                    "开发一个可运行的小工具。",
                    payload={
                        "model_policy": "on_demand",
                        "route_policy": {"allowed_providers": 123},
                    },
                )

                with self.assertRaises(NoRouteAvailable):
                    for _ in range(96):
                        resident.live_once()

                self.assertEqual(created_routes, [])
                thread = ledger.get_thread("invalid-policy")
                self.assertIsNotNone(thread)
                assert thread is not None
                self.assertNotIn("route_policy", thread.metadata)
            finally:
                resident.store.close()

            restarted = build_resident_runtime(config={"model": {}}, store_path=db)
            try:
                thread = restarted.work_ledger.get_thread("invalid-policy")
                self.assertIsNotNone(thread)
                assert thread is not None
                self.assertNotIn("route_policy", thread.metadata)
            finally:
                restarted.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
