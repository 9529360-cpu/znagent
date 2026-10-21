from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core import (
    KernelStore,
    ModelRoute,
    WorkerResult,
    ZNKernelRuntime,
    ZNResidentRuntime,
)
from zn_agent.core.models import ExecutionPath
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.resident import _ORIENT_HYBRID_MIN_SCORE

FACT_KEY = "d1_acceptance_project"
FACT_VALUE = "D1部署验收事实：用户的秘密项目代号是「蓝鲸」，启动日期是 2026-11-01。"
FACT_ALIASES = ("秘密项目代号", "蓝鲸计划")

# Natural phrasings of the seeded fact. Exact recall() returns None for
# every one of them (asserted in the tests); recall_hybrid() scores
# them 0.57-0.85. These are the zn-live reproduction questions from the
# PERF-2 evidence, plus close variants.
NATURAL_QUESTIONS = (
    "秘密项目的代号是什么？启动日期是哪天？",
    "秘密项目代号是什么",
    "蓝鲸计划什么时候启动？",
    "我的秘密项目叫什么来着，几号开始？",
)

UNRELATED_QUESTIONS = (
    "今天天气怎么样？",
    "帮我写一封道歉邮件",
    "量子计算机的基本原理是什么？",
)


class FakeWorker:
    def __init__(self, result):
        self.result = result

    def run(self, goal, kernel_context):
        return self.result


class FakeFactory:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def create(self, route):
        result = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        return FakeWorker(result)


def _model_factory() -> FakeFactory:
    return FakeFactory(
        [
            WorkerResult(
                success=True,
                response="model answer",
                verification_passed=True,
                metrics={"model_invoked": True},
            )
        ]
    )


class HybridRecallFallbackTests(unittest.TestCase):
    """PERF-2: orient pre-check falls back to recall_hybrid when the
    exact recall misses, but only for a high fused score."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.factory = _model_factory()
        kernel = ZNKernelRuntime(
            store=KernelStore(self.root / "kernel.db"),
            routes=[ModelRoute("primary", "test", "model", {"general": 0.8})],
            worker_factory=self.factory,
        )
        self.resident = ZNResidentRuntime(kernel=kernel)
        self.addCleanup(self.resident.store.close)
        self.resident.memory.remember(FACT_KEY, FACT_VALUE, aliases=FACT_ALIASES)

    def test_exact_recall_still_short_circuits_without_hybrid(self):
        match, score = self.resident._orient_memory_lookup("秘密项目代号")
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.key, FACT_KEY)
        # Exact hit: no hybrid score is attached.
        self.assertIsNone(score)

        result = self.resident.submit("秘密项目代号")
        self.assertTrue(result.success)
        self.assertEqual(result.execution_path, ExecutionPath.MEMORY)
        self.assertEqual(result.response, FACT_VALUE)
        self.assertNotIn("hybrid", result.reason)
        self.assertEqual(self.factory.calls, 0)

    def test_natural_questions_hit_via_hybrid_and_quote_the_fact(self):
        for question in NATURAL_QUESTIONS:
            with self.subTest(question=question):
                # Preconditions: the exact path really misses and the
                # hybrid path really clears the orient threshold.
                self.assertIsNone(self.resident.memory.recall(question))
                match, score = self.resident._orient_memory_lookup(question)
                self.assertIsNotNone(match)
                assert match is not None and score is not None
                self.assertEqual(match.key, FACT_KEY)
                self.assertGreaterEqual(score, _ORIENT_HYBRID_MIN_SCORE)

                calls_before = self.factory.calls
                result = self.resident.submit(question)
                self.assertTrue(result.success)
                self.assertEqual(result.execution_path, ExecutionPath.MEMORY)
                self.assertEqual(result.model_invocations, 0)
                self.assertEqual(self.factory.calls, calls_before)
                # The answer is the fact value verbatim, and the reason
                # cites the fact key plus the hybrid evidence.
                self.assertEqual(result.response, FACT_VALUE)
                self.assertIn("蓝鲸", result.response)
                self.assertIn(FACT_KEY, result.reason)
                self.assertIn("hybrid", result.reason)

    def test_unrelated_questions_do_not_misrecall(self):
        for question in UNRELATED_QUESTIONS:
            with self.subTest(question=question):
                match, _score = self.resident._orient_memory_lookup(question)
                self.assertIsNone(match)
                result = self.resident.submit(question)
                self.assertNotEqual(result.execution_path, ExecutionPath.MEMORY)
                self.assertNotEqual(result.response, FACT_VALUE)
                self.assertEqual(result.response, "model answer")
                self.assertEqual(result.model_invocations, 1)

    def test_keyword_only_hit_stays_below_the_threshold(self):
        # A value-text keyword overlap alone caps at 0.50 fused score
        # (0.45 keyword + at most 0.05 recency): never enough to answer
        # directly from memory at orient time.
        self.resident.memory.remember(
            "server config", "the backup window is 2am daily"
        )
        self.assertIsNone(self.resident.memory.recall("backup window"))
        hits = self.resident.memory.recall_hybrid("backup window")
        self.assertTrue(hits)
        self.assertAlmostEqual(hits[0]["score"], 0.50, places=2)
        self.assertLess(hits[0]["score"], _ORIENT_HYBRID_MIN_SCORE)

        match, score = self.resident._orient_memory_lookup("backup window")
        self.assertIsNone(match)
        self.assertIsNotNone(score)
        assert score is not None
        self.assertLess(score, _ORIENT_HYBRID_MIN_SCORE)

        result = self.resident.submit("backup window")
        self.assertNotEqual(result.execution_path, ExecutionPath.MEMORY)
        self.assertEqual(result.response, "model answer")

    def test_instruction_mentioning_a_fact_is_not_short_circuited(self):
        # An instruction that mentions a fact is not a memory question:
        # even though recall_hybrid scores it above the threshold, the
        # task belongs on the cognition path (where the fact is bound
        # as context), not answered by parroting the fact value back.
        self.resident.memory.remember(
            "project",
            {"name": "Artemis", "decision": "offline first"},
            aliases=("active project",),
        )
        task = "Explain the active project approach"
        self.assertIsNone(self.resident.memory.recall(task))
        hits = self.resident.memory.recall_hybrid(task)
        self.assertTrue(hits)
        self.assertGreaterEqual(hits[0]["score"], _ORIENT_HYBRID_MIN_SCORE)

        match, _score = self.resident._orient_memory_lookup(task)
        self.assertIsNone(match)
        result = self.resident.submit(task)
        self.assertNotEqual(result.execution_path, ExecutionPath.MEMORY)
        self.assertEqual(result.response, "model answer")
        self.assertEqual(result.model_invocations, 1)

    def test_allow_memory_false_skips_the_hybrid_fallback(self):
        result = self.resident.submit(
            NATURAL_QUESTIONS[0], payload={"allow_memory": False}
        )
        self.assertNotEqual(result.execution_path, ExecutionPath.MEMORY)
        self.assertEqual(result.response, "model answer")
        self.assertEqual(result.model_invocations, 1)

    def test_non_retainable_fact_never_surfaces_via_hybrid(self):
        self.resident.memory.remember(
            "vault combo",
            "保险柜密码是 9981",
            aliases=("保险柜密码",),
            sensitivity="non_retainable",
        )
        question = "保险柜密码是多少？"
        self.assertIsNone(self.resident.memory.recall(question))
        match, _score = self.resident._orient_memory_lookup(question)
        self.assertIsNone(match)
        result = self.resident.submit(question)
        self.assertNotEqual(result.execution_path, ExecutionPath.MEMORY)
        self.assertNotIn("9981", str(result.response))


class HybridRecallFallbackProductRuntimeTests(unittest.TestCase):
    """PERF-2 on the production runtime chain (CapabilityRecovery
    _orient_step override): the same fallback answers there."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.resident = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=self.root / "kernel.db",
        )
        self.addCleanup(self.resident.store.close)
        self.resident.memory.remember(FACT_KEY, FACT_VALUE, aliases=FACT_ALIASES)

    def test_natural_question_answered_from_memory_without_a_model(self):
        result = self.resident.submit(NATURAL_QUESTIONS[0])
        self.assertTrue(result.success)
        self.assertEqual(result.execution_path, ExecutionPath.MEMORY)
        self.assertEqual(result.model_invocations, 0)
        self.assertEqual(result.response, FACT_VALUE)
        self.assertIn(FACT_KEY, result.reason)
        self.assertIn("hybrid", result.reason)

    def test_unrelated_question_is_not_answered_from_memory(self):
        result = self.resident.submit(UNRELATED_QUESTIONS[0])
        self.assertNotEqual(result.execution_path, ExecutionPath.MEMORY)
        self.assertNotEqual(result.response, FACT_VALUE)


if __name__ == "__main__":
    unittest.main()
