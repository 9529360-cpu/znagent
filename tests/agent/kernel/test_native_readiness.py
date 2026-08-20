from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.kernel import KernelStore, ModelRoute, WorkerResult, ZNKernelRuntime, ZNResidentRuntime


class _RecordingWorker:
    def __init__(self, calls):
        self.calls = calls

    def run(self, goal, kernel_context):
        self.calls.append((goal.task, kernel_context))
        return WorkerResult(
            success=True,
            response="bounded cognition result",
            verification_passed=True,
            metrics={"model_invoked": True},
        )


class _Factory:
    def __init__(self, calls):
        self.calls = calls

    def create(self, route):
        return _RecordingWorker(self.calls)


class NativeReadinessTests(unittest.TestCase):
    def _resident(self, db: Path, calls: list[tuple[str, str]]):
        kernel = ZNKernelRuntime(
            store=KernelStore(db),
            routes=[ModelRoute("primary", "test", "model", {"programming": 0.9})],
            worker_factory=_Factory(calls),
        )
        return ZNResidentRuntime(kernel=kernel)

    @staticmethod
    def _teach_python_knowledge(resident: ZNResidentRuntime) -> None:
        for _ in range(2):
            resident.kernel.self_model.integrate_external_learning(
                "debug Python code",
                ("python",),
                quality=0.9,
                confidence=1.0,
            )

    def test_familiar_knowledge_does_not_claim_independent_ability(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[tuple[str, str]] = []
            resident = self._resident(Path(tmp) / "kernel.db", calls)
            self._teach_python_knowledge(resident)

            readiness = resident.kernel.self_model.assess_task(
                "debug Python code",
                ("python",),
            )

            self.assertEqual(readiness.posture, "familiar")
            self.assertGreaterEqual(readiness.knowledge_score, 0.7)
            self.assertEqual(readiness.ability_score, 0.0)
            self.assertEqual(resident.kernel.self_model.get("python").evidence_count, 0)
            resident.store.close()

    def test_thought_uses_self_readiness_before_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[tuple[str, str]] = []
            resident = self._resident(Path(tmp) / "kernel.db", calls)
            self._teach_python_knowledge(resident)

            result = resident.submit(
                "debug Python code",
                payload={
                    "required_capabilities": ["python"],
                    "model_policy": "never",
                },
            )
            thought = resident.life.recent_thoughts(1)[0]
            impasse = resident.life.snapshot().current_impasse

            self.assertFalse(result.success)
            self.assertEqual(calls, [])
            self.assertTrue(any("posture=familiar" in item for item in thought.known))
            self.assertTrue(
                any("better than I can execute" in item for item in thought.unknown)
            )
            self.assertIsNotNone(impasse)
            self.assertIn("verified native procedure", impasse.reason)
            resident.store.close()

    def test_external_brain_receives_deliberated_gap_not_self_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[tuple[str, str]] = []
            resident = self._resident(Path(tmp) / "kernel.db", calls)
            self._teach_python_knowledge(resident)

            result = resident.submit(
                "debug Python code in the current project",
                payload={"required_capabilities": ["python"]},
            )

            self.assertTrue(result.success)
            self.assertEqual(len(calls), 1)
            task, context = calls[0]
            self.assertNotEqual(task, "debug Python code in the current project")
            self.assertIn("smallest missing step", task)
            self.assertNotIn("self_model", context)
            self.assertNotIn("knowledge_score", context)
            self.assertNotIn("independent ability", context)
            self.assertEqual(resident.kernel.self_model.get("python").evidence_count, 0)
            self.assertGreater(
                resident.kernel.self_model.knowledge("python").evidence_count,
                2,
            )
            resident.store.close()

    def test_related_learning_is_recalled_inside_zn_but_not_exported(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls: list[tuple[str, str]] = []
            resident = self._resident(Path(tmp) / "kernel.db", calls)

            first = resident.submit(
                "debug Python sqlite transaction timeout",
                payload={"required_capabilities": ["python"]},
            )
            self.assertTrue(first.success)
            candidates = resident.life.recent_learning_candidates(5)
            self.assertEqual(len(candidates), 1)
            self.assertIn("bounded cognition result", candidates[0].resolution_summary)

            second = resident.submit(
                "debug Python sqlite transaction lock",
                payload={"required_capabilities": ["python"]},
            )
            thought = resident.life.recent_thoughts(1)[0]

            self.assertTrue(second.success)
            self.assertEqual(len(calls), 2)
            self.assertTrue(
                any("related prior learning record" in item for item in thought.known)
            )
            second_task, second_context = calls[1]
            self.assertIn("related prior resolutions", second_task)
            self.assertNotIn("bounded cognition result", second_context)
            self.assertNotIn(candidates[0].candidate_id, second_context)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
