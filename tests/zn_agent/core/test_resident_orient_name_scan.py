"""PERF-2 second channel: name-driven orient lookup, free of BM25 rank pressure.

The first three PERF-2 fixes all lost to the same structure on zn-live:
every failed natural question writes another ``work_summary:`` run-log
fact, so BM25 rank pressure keeps sinking the true fact below any finite
hybrid window (live: true fact ``d1_acceptance_project`` at rank 6 of a
top-10 window, 0.4522, crowded out by five ``work_summary:`` keyword
magnets at 0.4717-0.4996 -- and the treadmill only gets worse).

``_orient_name_scan`` does not rank by BM25 at all: it walks the same
candidate set hybrid walks (current, unexpired, retainable facts),
skips run-log keys with the same prefix rule, and scores each fact's
name directly with ``_hybrid_entity_score``. Only strong entity
evidence (``_orient_entity_evidence`` reused verbatim) qualifies, and
exactly one fact must be strictly strongest -- a tie is ambiguity and
falls back to the model path (never guess).
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
from zn_agent.core.models import ExecutionPath

# The zn-live incident fact and question (recall() is None for it).
FACT_KEY = "d1_acceptance_project"
FACT_VALUE = "D1部署验收事实：用户的秘密项目代号是「蓝鲸」，启动日期是 2026-11-01。"
FACT_ALIASES = ("秘密项目代号", "蓝鲸计划")
QUESTION = "秘密项目的代号是什么？启动日期是哪天？"

# Sixteen keyword-magnet run-log facts. Each value repeats the question's
# distinctive bigrams (including 号是, which the true fact alone carries
# in a small corpus) with distinct tails so near-duplicate supersession
# does not merge them. In this corpus the true fact is crowded out of
# the entire top-10 hybrid window -- the live failure shape -- while the
# noise sits at the 0.50 keyword-only ceiling.
NOISE_TAILS = (
    "归档完毕收尾总结报告存档确认",
    "通知完毕",
    "复核完毕",
    "公示完毕",
    "记录完毕",
    "结算完毕",
    "核销完毕",
    "交接完毕",
    "核验完毕",
    "备案完毕",
    "闭环完毕",
    "归集完毕",
    "落盘完毕",
    "同步完毕",
    "回执完毕",
    "签收完毕",
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


class OrientNameScanTests(unittest.TestCase):
    """Second orient channel: name lookup independent of BM25 ranking."""

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

    def _remember_run_log_noise(self):
        for i, tail in enumerate(NOISE_TAILS):
            self.resident.memory.remember(
                f"{SUMMARY_KEY_PREFIX}thread-{i}:event-{i}",
                f"秘密项目代号是蓝鲸启动日期是哪天"
                f"秘密项目代号是蓝鲸启动日期{tail}"
                f"秘密项目代号是蓝鲸。",
            )

    def test_crowded_out_fact_answered_via_name_scan(self):
        # The live failure shape: >= 12 keyword-only work_summary hits
        # fill the whole top-10 hybrid window (all at the 0.50 ceiling),
        # so the first channel has nothing usable after the run-log
        # filter. The name-driven second channel must still direct-answer
        # the true fact verbatim with zero model calls.
        self.assertGreaterEqual(len(NOISE_TAILS), 12)
        self.resident.memory.remember(FACT_KEY, FACT_VALUE, aliases=FACT_ALIASES)
        self._remember_run_log_noise()
        self.assertIsNone(self.resident.memory.recall(QUESTION))

        hits = self.resident.memory.recall_hybrid(QUESTION, max_facts=10)
        self.assertEqual(len(hits), 10)
        usable = [
            h
            for h in hits
            if not str(h["key"]).startswith(SUMMARY_KEY_PREFIX)
        ]
        # The true fact is crowded out of the entire window: the first
        # channel genuinely cannot answer this question.
        self.assertEqual(usable, [])

        scanned = self.resident._orient_name_scan(QUESTION)
        self.assertIsNotNone(scanned)
        assert scanned is not None
        self.assertEqual(scanned.key, FACT_KEY)
        self.assertEqual(scanned.value, FACT_VALUE)
        self.assertEqual(scanned.matched_by, "秘密项目代号")
        self.assertNotIn("work_summary:", scanned.key)

        match, score = self.resident._orient_memory_lookup(QUESTION)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.key, FACT_KEY)
        self.assertEqual(match.value, FACT_VALUE)
        # A name-scan hit is a name lookup, not a ranked hybrid hit:
        # no fused score is reported (same convention as exact hits).
        self.assertIsNone(score)

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

    def test_strictly_strongest_name_wins_among_qualifiers(self):
        # Two facts with strong entity evidence: "蓝鲸" is mentioned
        # verbatim (entity 1.0), "秘密项目的代号" is partially mentioned
        # with name-token coverage 4/7 >= 0.50. The strictly strongest
        # (by entity, then coverage) is direct-answered -- no tie.
        self.resident.memory.remember(
            "whale_fact", "蓝鲸是最大的动物。", aliases=("蓝鲸",)
        )
        self.resident.memory.remember(
            "codename_fact",
            "代号事项已归档。",
            aliases=("秘密项目的代号",),
        )
        question = "蓝鲸的秘密项目代号是什么？"
        scanned = self.resident._orient_name_scan(question)
        self.assertIsNotNone(scanned)
        assert scanned is not None
        self.assertEqual(scanned.key, "whale_fact")
        self.assertEqual(scanned.matched_by, "蓝鲸")

    def test_tied_name_mentions_fall_back_to_model(self):
        # Both facts are named verbatim with identical evidence
        # (entity 1.0, coverage 1.0): ambiguity -- never guess.
        self.resident.memory.remember(
            "whale_a", "鲸鱼生活在海洋里。", aliases=("鲸鱼",)
        )
        self.resident.memory.remember(
            "whale_b", "蓝鲸是须鲸的一种。", aliases=("蓝鲸",)
        )
        question = "鲸鱼和蓝鲸哪个大？"
        self.assertIsNone(self.resident._orient_name_scan(question))

    def test_tied_name_mentions_fall_back_to_model_end_to_end(self):
        # End to end: the tied facts are crowded out of the hybrid
        # window by run-log noise, so the second channel is reached and
        # must decline the tie -- the question goes to the model path.
        self.resident.memory.remember(
            "whale_a", "鲸鱼生活在海洋里。", aliases=("鲸鱼",)
        )
        self.resident.memory.remember(
            "whale_b", "蓝鲸是须鲸的一种。", aliases=("蓝鲸",)
        )
        question = "鲸鱼和蓝鲸哪个大？"
        for i, tail in enumerate(NOISE_TAILS):
            self.resident.memory.remember(
                f"{SUMMARY_KEY_PREFIX}thread-{i}:event-{i}",
                f"鲸鱼和蓝鲸哪个大鲸鱼和蓝鲸{tail}鲸鱼和蓝鲸。",
            )
        hits = self.resident.memory.recall_hybrid(question, max_facts=10)
        usable = [
            h
            for h in hits
            if not str(h["key"]).startswith(SUMMARY_KEY_PREFIX)
        ]
        self.assertEqual(usable, [])

        match, _score = self.resident._orient_memory_lookup(question)
        self.assertIsNone(match)

        calls_before = self.factory.calls
        result = self.resident.submit(question)
        self.assertNotEqual(result.execution_path, ExecutionPath.MEMORY)
        self.assertEqual(result.response, "model answer")
        self.assertEqual(self.factory.calls, calls_before + 1)

    def test_non_retainable_fact_named_is_never_surfaced(self):
        # Q11: non-retainable facts never enter the hybrid candidate
        # set, so the name scan -- which walks that same set -- can
        # never surface one, however directly it is named.
        self.resident.memory.remember(
            "vault combo",
            "保险柜密码是 9981",
            aliases=("保险柜密码",),
            sensitivity="non_retainable",
        )
        question = "保险柜密码是多少？"
        self.assertIsNone(self.resident._orient_name_scan(question))

        match, _score = self.resident._orient_memory_lookup(question)
        self.assertIsNone(match)
        result = self.resident.submit(question)
        self.assertNotEqual(result.execution_path, ExecutionPath.MEMORY)
        self.assertNotIn("9981", str(result.response))

    def test_work_summary_named_is_never_direct_answered(self):
        # The run-log prefix filter applies in the second channel too:
        # a work_summary fact named verbatim via its alias must never
        # be direct-answered.
        self.resident.memory.remember(
            f"{SUMMARY_KEY_PREFIX}blue-whale:1",
            "蓝鲸计划相关事项已归档。",
            aliases=("蓝鲸计划",),
        )
        question = "蓝鲸计划的代号是什么？"
        self.assertIsNone(self.resident._orient_name_scan(question))

        match, _score = self.resident._orient_memory_lookup(question)
        self.assertIsNone(match)
        result = self.resident.submit(question)
        self.assertNotEqual(result.execution_path, ExecutionPath.MEMORY)
        self.assertEqual(result.response, "model answer")

    def test_expired_fact_named_is_never_surfaced(self):
        # Q7: expired facts are filtered out of live recall; the name
        # scan walks the same filtered candidate set.
        self.resident.memory.remember(
            "old_codename",
            "旧代号是灰鲸。",
            aliases=("灰鲸",),
            expires_at="2000-01-01T00:00:00+00:00",
        )
        question = "灰鲸是什么？"
        self.assertIsNone(self.resident._orient_name_scan(question))

        match, _score = self.resident._orient_memory_lookup(question)
        self.assertIsNone(match)
        result = self.resident.submit(question)
        self.assertNotEqual(result.execution_path, ExecutionPath.MEMORY)
        self.assertEqual(result.response, "model answer")


if __name__ == "__main__":
    unittest.main()
