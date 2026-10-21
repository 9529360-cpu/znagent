"""PERF-2 entity tier: strong-entity-evidence discriminator for orient direct answers.

Second follow-up on the zn-live regression (see
``test_resident_orient_runlog_filter.py`` for the run-log filter): the true
fact scored 0.4496 on the live box -- below the plain 0.55 hybrid floor --
but the question mentioned the fact's alias (``entity=0.235``), i.e. the
user said the fact's name out loud. The orient pre-check now tiers the
floor: 0.40 when the hit carries *strong entity evidence* (verbatim
key/alias mention, exact match, or >= half of the matched name's tokens
covered by the question), 0.55 otherwise. A literal
``matched_by != "keyword"`` rule was measured to regress the natural-chat
contract (an instruction mentioning a fact with a trace entity signal
would be direct-answered); the name-token coverage gate below is the
regression-tested discriminator instead.
"""

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
from zn_agent.core.completion_summary import SUMMARY_KEY_PREFIX
from zn_agent.core.memory import _hybrid_tokens
from zn_agent.core.models import ExecutionPath
from zn_agent.core.resident import (
    _ORIENT_ENTITY_NAME_COVERAGE_MIN,
    _ORIENT_HYBRID_MIN_SCORE,
    _ORIENT_HYBRID_MIN_SCORE_ENTITY,
    _ORIENT_SCORE_EPS,
    _orient_entity_evidence,
)

FACT_KEY = "d1_acceptance_project"
FACT_VALUE = "D1部署验收事实：用户的秘密项目代号是「蓝鲸」，启动日期是 2026-11-01。"
FACT_ALIASES = ("秘密项目代号", "蓝鲸计划")

# The zn-live incident question: exact recall() is None for it.
QUESTION = "秘密项目的代号是什么？启动日期是哪天？"

# Four keyword-only run-log facts reproducing the live noise shape: the
# summaries are keyword magnets for the question, so they outrank the
# true fact on raw BM25 (top noise 0.50, three of four in the 0.46-0.50
# band measured on zn-live) while the true fact's keyword share is
# diluted into the 0.40-0.55 band. Values are worded differently so the
# memory's near-duplicate supersession does not merge them. A 5-document
# seed corpus cannot reproduce the live thousand-document IDF exactly;
# the asserted invariant is the regime, not the digits: keyword-only
# noise crowding above the true fact, true fact with partial alias
# mention below the 0.55 floor but at/above the 0.40 entity tier.
KEYWORD_NOISE = (
    "秘密项目代号蓝鲸启动日期是什么时候事项代号清单归档完毕收尾总结报告存档确认。",
    "秘密项目代号蓝鲸启动日期是哪天事项代号代号通知完毕。",
    "秘密项目代号蓝鲸启动日期是什么事项代号代号复核完毕。",
    "秘密项目代号蓝鲸启动日期是哪天事项代号代号公示完毕。",
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


class OrientEntityTierTests(unittest.TestCase):
    """Tiered orient floor: 0.40 with strong entity evidence, 0.55 else."""

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

    def _name_coverage(self, name: str, question: str) -> float:
        name_tokens = set(_hybrid_tokens(name))
        query_tokens = set(_hybrid_tokens(question))
        return len(name_tokens & query_tokens) / len(name_tokens)

    def test_partial_alias_mention_direct_answers_below_plain_floor(self):
        # Live shape: four keyword-only work_summary hits crowd above the
        # true fact; the true fact is a partial alias mention
        # (entity ~= 0.235, matched_by is the alias). The old 0.55 floor
        # would miss it; the 0.40 entity tier must direct-answer it
        # verbatim with zero model calls.
        self.resident.memory.remember(FACT_KEY, FACT_VALUE, aliases=FACT_ALIASES)
        for i, value in enumerate(KEYWORD_NOISE):
            self.resident.memory.remember(
                f"{SUMMARY_KEY_PREFIX}thread-{i}:event-{i}", value
            )
        self.assertIsNone(self.resident.memory.recall(QUESTION))

        hits = self.resident.memory.recall_hybrid(QUESTION, max_facts=10)
        noise_hits = [
            h for h in hits if str(h["key"]).startswith(SUMMARY_KEY_PREFIX)
        ]
        self.assertEqual(len(noise_hits), 4)
        for hit in noise_hits:
            self.assertEqual(hit.get("matched_by"), "keyword")
            self.assertEqual(hit["signals"]["entity"], 0.0)
        # Three of the four noise hits sit in the live 0.46-0.50 band.
        in_band = [h for h in noise_hits if 0.46 <= h["score"] <= 0.50]
        self.assertGreaterEqual(len(in_band), 3)

        fact_hit = next(h for h in hits if h["key"] == FACT_KEY)
        self.assertEqual(fact_hit.get("matched_by"), "秘密项目代号")
        self.assertAlmostEqual(fact_hit["signals"]["entity"], 0.235, places=2)
        self.assertGreaterEqual(
            self._name_coverage("秘密项目代号", QUESTION),
            _ORIENT_ENTITY_NAME_COVERAGE_MIN,
        )
        self.assertTrue(_orient_entity_evidence(fact_hit, QUESTION))
        # Below the plain floor, at/above the entity tier: this is the
        # regime the old code missed on zn-live (0.4496 there).
        self.assertLess(fact_hit["score"], _ORIENT_HYBRID_MIN_SCORE)
        self.assertGreaterEqual(
            fact_hit["score"], _ORIENT_HYBRID_MIN_SCORE_ENTITY - _ORIENT_SCORE_EPS
        )

        match, score = self.resident._orient_memory_lookup(QUESTION)
        self.assertIsNotNone(match)
        assert match is not None and score is not None
        self.assertEqual(match.key, FACT_KEY)
        self.assertEqual(match.value, FACT_VALUE)
        self.assertNotIn("work_summary:", match.key)

        calls_before = self.factory.calls
        result = self.resident.submit(QUESTION)
        self.assertTrue(result.success)
        self.assertEqual(result.execution_path, ExecutionPath.MEMORY)
        self.assertEqual(result.model_invocations, 0)
        self.assertEqual(self.factory.calls, calls_before)
        self.assertEqual(result.response, FACT_VALUE)
        self.assertIn("蓝鲸", result.response)
        self.assertIn("2026-11-01", result.response)
        self.assertIn(FACT_KEY, result.reason)
        self.assertIn("hybrid", result.reason)

    def test_single_char_alias_boundary_uses_epsilon(self):
        # A single-char CJK alias mentioned verbatim in the question:
        # entity=1.0, keyword=0, fused score lands strictly below 0.40
        # (measured 0.39999999992). The epsilon tolerance must still let
        # the entity tier through -- mathematically the evidence is
        # exactly at the tier line.
        self.resident.memory.remember(
            "whale_fact", "蓝鲸是秘密项目的代号。", aliases=("鲸",)
        )
        question = "鲸在哪里？"
        self.assertIsNone(self.resident.memory.recall(question))
        hits = self.resident.memory.recall_hybrid(question, max_facts=5)
        hit = next(h for h in hits if h["key"] == "whale_fact")
        self.assertEqual(hit.get("matched_by"), "鲸")
        self.assertEqual(hit["signals"]["entity"], 1.0)
        self.assertEqual(hit["signals"]["keyword"], 0.0)
        self.assertLess(hit["score"], _ORIENT_HYBRID_MIN_SCORE_ENTITY)
        self.assertGreaterEqual(
            hit["score"], _ORIENT_HYBRID_MIN_SCORE_ENTITY - _ORIENT_SCORE_EPS
        )
        self.assertTrue(_orient_entity_evidence(hit, question))

        match, _score = self.resident._orient_memory_lookup(question)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.key, "whale_fact")

        result = self.resident.submit(question)
        self.assertEqual(result.execution_path, ExecutionPath.MEMORY)
        self.assertEqual(result.model_invocations, 0)
        self.assertIn("蓝鲸", result.response)

    def test_trace_entity_evidence_does_not_direct_answer(self):
        # Regression guard from the natural-chat contract
        # (test_natural_chat_memory_recovery_contract): the instruction
        # "请记住，以后回答请简洁一些。然后告诉我你已经准备好了。" hits
        # the "response verbosity" fact with entity=0.0417 / kw=1.0 /
        # score=0.5146, matched_by an alias -- but the name-token coverage
        # is only 0.167 < 0.50, i.e. trace entity evidence. A literal
        # ``matched_by != "keyword"`` tier rule would direct-answer this
        # instruction; the coverage discriminator must let it fall through
        # to the model path.
        self.resident.memory.remember(
            "response verbosity",
            "concise",
            aliases=("reply verbosity", "回答详细程度", "回复详细程度"),
        )
        instruction = "请记住，以后回答请简洁一些。然后告诉我你已经准备好了。"
        hits = self.resident.memory.recall_hybrid(instruction, max_facts=5)
        hit = next(h for h in hits if h["key"] == "response verbosity")
        self.assertAlmostEqual(hit["score"], 0.5146, places=3)
        self.assertAlmostEqual(hit["signals"]["entity"], 0.0417, places=3)
        self.assertEqual(hit["signals"]["keyword"], 1.0)
        self.assertNotEqual(hit.get("matched_by"), "keyword")
        coverage = self._name_coverage(str(hit["matched_by"]), instruction)
        self.assertLess(coverage, _ORIENT_ENTITY_NAME_COVERAGE_MIN)
        self.assertFalse(_orient_entity_evidence(hit, instruction))

        match, score = self.resident._orient_memory_lookup(instruction)
        self.assertIsNone(match)
        assert score is not None
        self.assertAlmostEqual(score, 0.5146, places=3)

        calls_before = self.factory.calls
        result = self.resident.submit(instruction)
        self.assertNotEqual(result.execution_path, ExecutionPath.MEMORY)
        self.assertEqual(result.response, "model answer")
        self.assertEqual(result.model_invocations, 1)
        self.assertEqual(self.factory.calls, calls_before + 1)

    def test_keyword_only_ceiling_still_blocked(self):
        # #625 semantics, unchanged by the entity tier: a pure value-text
        # keyword hit caps at 0.50 fused (0.45 keyword + 0.05 recency) and
        # must never be direct-answered -- it names no fact, so it stays
        # on the 0.55 tier by construction.
        self.resident.memory.remember(
            "server config", "the backup window is 2am daily"
        )
        self.assertIsNone(self.resident.memory.recall("backup window"))
        hits = self.resident.memory.recall_hybrid("backup window")
        self.assertTrue(hits)
        self.assertAlmostEqual(hits[0]["score"], 0.50, places=2)
        self.assertLess(hits[0]["score"], _ORIENT_HYBRID_MIN_SCORE)
        self.assertEqual(hits[0].get("matched_by"), "keyword")
        self.assertFalse(_orient_entity_evidence(hits[0], "backup window"))

        match, score = self.resident._orient_memory_lookup("backup window")
        self.assertIsNone(match)
        self.assertIsNotNone(score)
        assert score is not None
        self.assertLess(score, _ORIENT_HYBRID_MIN_SCORE)

        result = self.resident.submit("backup window")
        self.assertNotEqual(result.execution_path, ExecutionPath.MEMORY)
        self.assertEqual(result.response, "model answer")

    def test_semantic_rescue_never_qualifies_for_entity_tier(self):
        # Q8 semantic rescues (matched_by="semantic") name no fact; they
        # must stay on the 0.55 tier no matter the coverage arithmetic.
        hit = {
            "key": "some fact",
            "matched_by": "semantic",
            "signals": {"keyword": 0.0, "entity": 0.0, "exact": 0.0,
                        "recency": 1.0, "semantic": 0.9},
        }
        self.assertFalse(_orient_entity_evidence(hit, "some fact"))


if __name__ == "__main__":
    unittest.main()
