from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core import (
    CapabilityResult,
    ExactTaskCapability,
    Goal,
    KernelStore,
    ModelRoute,
    ModelRouter,
    SelfModel,
    WorkerResult,
    ZNKernelRuntime,
    ZNResidentRuntime,
)


class _Worker:
    def run(self, goal, kernel_context):
        return WorkerResult(
            success=True,
            response="external cognition resolved the gap",
            verification_passed=True,
            metrics={"model_invoked": True},
        )


class _Factory:
    def create(self, route):
        return _Worker()


def _resident(db: Path) -> ZNResidentRuntime:
    kernel = ZNKernelRuntime(
        store=KernelStore(db),
        routes=[
            ModelRoute(
                "primary",
                "test",
                "model",
                {
                    "general": 0.8,
                    "programming": 0.8,
                    "security": 0.8,
                },
            )
        ],
        worker_factory=_Factory(),
    )
    return ZNResidentRuntime(kernel=kernel)


class LearningConsolidationTests(unittest.TestCase):
    def test_external_solution_builds_knowledge_not_tiny_capability(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = _resident(Path(tmp) / "kernel.db")
            before = resident.capabilities.names()

            result = resident.submit(
                "debug a Python service",
                payload={"required_capabilities": ["python"]},
            )
            learning = resident.life.recent_learning_candidates(5)
            profile = resident.kernel.self_model.profile()

            self.assertTrue(result.success)
            self.assertEqual(len(learning), 1)
            self.assertEqual(resident.capabilities.names(), before)

            knowledge = {item.name: item for item in profile["knowledge"]}
            ability = {item.name: item for item in profile["ability"]}
            self.assertIn("it", knowledge)
            self.assertIn("it/programming", knowledge)
            self.assertIn("it/programming/python", knowledge)
            self.assertGreater(knowledge["it/programming/python"].evidence_count, 0)
            self.assertNotIn("it", ability)
            self.assertNotIn("it/programming/python", ability)
            resident.store.close()

    def test_programming_and_security_share_the_it_parent_domain(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = _resident(Path(tmp) / "kernel.db")

            resident.submit(
                "debug this Python program",
                payload={"required_capabilities": ["programming"]},
            )
            resident.submit(
                "analyze a penetration testing result",
                payload={"required_capabilities": ["security"]},
            )

            knowledge = {
                item.name: item for item in resident.kernel.self_model.profile()["knowledge"]
            }
            self.assertIn("it", knowledge)
            self.assertIn("it/programming", knowledge)
            self.assertIn("it/security", knowledge)
            self.assertGreaterEqual(knowledge["it"].evidence_count, 2)
            self.assertEqual(resident.capabilities.names(), ())
            resident.store.close()

    def test_native_success_is_evidence_of_independent_ability(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = _resident(Path(tmp) / "kernel.db")
            resident.capabilities.register(
                ExactTaskCapability(
                    name="python-local",
                    triggers=("run python check",),
                    handler=lambda event, state: CapabilityResult(
                        success=True,
                        response="local result",
                    ),
                )
            )

            result = resident.submit(
                "run python check",
                payload={"required_capabilities": ["python"]},
            )
            profile = resident.kernel.self_model.profile()
            ability = {item.name: item for item in profile["ability"]}

            self.assertTrue(result.success)
            self.assertEqual(result.model_invocations, 0)
            self.assertIn("it", ability)
            self.assertIn("it/programming", ability)
            self.assertIn("it/programming/python", ability)
            self.assertGreater(ability["it/programming/python"].score, 0.0)
            resident.store.close()

    def test_external_route_learning_does_not_credit_self_ability(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = _resident(Path(tmp) / "kernel.db")

            resident.submit(
                "investigate a network security question",
                payload={"required_capabilities": ["security"]},
            )

            route_key = resident.kernel.self_model.route_capability_key(
                "primary", "it/security"
            )
            route_estimate = resident.store.get_capability(route_key)
            self_estimate = resident.kernel.self_model.get("it/security")
            knowledge_estimate = resident.kernel.self_model.knowledge("it/security")

            self.assertIsNotNone(route_estimate)
            self.assertGreater(route_estimate.evidence_count, 0)
            self.assertEqual(self_estimate.evidence_count, 0)
            self.assertGreater(knowledge_estimate.evidence_count, 0)
            resident.store.close()

    def test_python_requirement_can_use_programming_route_prior(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            router = ModelRouter(
                [
                    ModelRoute(
                        "generic",
                        "test",
                        "generic-model",
                        {"general": 0.65},
                        reliability=0.8,
                    ),
                    ModelRoute(
                        "coder",
                        "test",
                        "coder-model",
                        {"programming": 0.95, "general": 0.2},
                        reliability=0.8,
                    ),
                ],
                SelfModel(store),
            )
            goal = Goal(
                goal_id="goal-route-test",
                task="debug python",
                required_capabilities=("python",),
            )

            selected = router.select(goal)

            self.assertEqual(selected.route_id, "coder")
            store.close()


if __name__ == "__main__":
    unittest.main()
