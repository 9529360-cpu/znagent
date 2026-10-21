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
from zn_agent.core.completion_summary import PITFALL_KEY_PREFIX, SUMMARY_KEY_PREFIX
from zn_agent.core.models import ExecutionPath
from zn_agent.core.resident import (
    _ORIENT_HYBRID_CANDIDATES,
    _ORIENT_HYBRID_MIN_SCORE,
    _ORIENT_RUN_LOG_PREFIXES,
)

FACT_KEY = "d1_acceptance_project"
FACT_VALUE = "D1部署验收事实：用户的秘密项目代号是「蓝鲸」，启动日期是 2026-11-01。"
FACT_ALIASES = ("秘密项目代号", "蓝鲸计划")

# The zn-live incident question (PERF-2 evidence): exact recall() is
# None for it; the live kernel.db ranked four keyword-only
# ``work_summary:`` hits 0.47-0.50 above the true fact (0.4496 there).
QUESTION = "秘密项目的代号是什么？启动日期是哪天？"

# Four keyword-only run-log facts reproducing the live noise shape:
# short, keyword-dense completion summaries with no entity signal, so
# each scores 0.45 * ~1.0 (keyword) + recency -- the 0.47-0.50 band
# measured on zn-live. Values are worded differently so the memory's
# near-duplicate supersession does not merge them.
KEYWORD_NOISE = (
    "秘密项目代号是蓝鲸，启动日期是2026-11-01。代号清单已归档。",
    "秘密项目代号是蓝鲸，启动日期是2026-11-01。通知已下发各组。",
    "秘密项目代号是蓝鲸，启动日期是2026-11-01。复核无误收尾。",
    "秘密项目代号是蓝鲸，启动日期是2026-11-01。代号事项已公示。",
)

# A run-log fact engineered ABOVE the orient threshold: its value is
# keyword-dense and its alias is mentioned verbatim in the question,
# giving entity 1.0 on top of keyword -- 0.74 in the seeded DB. The
# alias simulates a summary whose recorded thread-alias text happens to
# be asked about; the filter keys off the KEY prefix either way.
ABOVE_THRESHOLD_NOISE_VALUE = (
    "秘密项目代号蓝鲸，启动日期是2026-11-01，代号事项收尾。"
)
ABOVE_THRESHOLD_NOISE_ALIAS = "启动日期"


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


class OrientRunLogFilterTests(unittest.TestCase):
    """PERF-2 follow-up (zn-live regression): the orient pre-check's
    hybrid fallback must skip system run-log facts -- ``work_summary:``
    / ``work_pitfall:`` keys written by completion_summary.py. They are
    keyword magnets for natural questions, crowd the true fact out of a
    top-1 window, and must NEVER be direct-answered even when one
    clears the 0.55 threshold."""

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

    def _remember_keyword_noise(self):
        for i, value in enumerate(KEYWORD_NOISE):
            self.resident.memory.remember(
                f"{SUMMARY_KEY_PREFIX}thread-{i}:event-{i}", value
            )

    def test_filter_constants_are_locked(self):
        # The hybrid window widened by the fix is a locked constant;
        # the run-log prefixes must be the completion_summary single
        # source of truth, never a second hand-typed literal.
        # PERF-2 second channel: the window is 10 (recall_hybrid's hard
        # max_facts cap) as mitigation; the structural cure is the
        # name-driven channel in _orient_memory_lookup, which needs no
        # BM25 window at all.
        self.assertEqual(_ORIENT_HYBRID_CANDIDATES, 10)
        self.assertEqual(
            _ORIENT_RUN_LOG_PREFIXES, (SUMMARY_KEY_PREFIX, PITFALL_KEY_PREFIX)
        )
        self.assertEqual(SUMMARY_KEY_PREFIX, "work_summary:")
        self.assertEqual(PITFALL_KEY_PREFIX, "work_pitfall:")

    def test_keyword_noise_below_threshold_is_skipped_true_fact_answered(self):
        # Reproduces the zn-live noise shape: four keyword-only
        # work_summary hits in the 0.47-0.50 band (matched_by=keyword,
        # no entity signal). The helper must skip all of them and
        # answer the true fact verbatim.
        self._remember_keyword_noise()
        self.assertIsNone(self.resident.memory.recall(QUESTION))

        hits = self.resident.memory.recall_hybrid(QUESTION, max_facts=10)
        noise_hits = [
            h
            for h in hits
            if str(h["key"]).startswith(SUMMARY_KEY_PREFIX)
        ]
        self.assertEqual(len(noise_hits), 4)
        for hit in noise_hits:
            self.assertGreaterEqual(hit["score"], 0.46)
            self.assertLess(hit["score"], _ORIENT_HYBRID_MIN_SCORE)
            self.assertEqual(hit.get("matched_by"), "keyword")

        match, score = self.resident._orient_memory_lookup(QUESTION)
        self.assertIsNotNone(match)
        assert match is not None and score is not None
        self.assertEqual(match.key, FACT_KEY)
        self.assertNotIn("work_summary:", match.key)
        self.assertGreaterEqual(score, _ORIENT_HYBRID_MIN_SCORE)

        calls_before = self.factory.calls
        result = self.resident.submit(QUESTION)
        self.assertTrue(result.success)
        self.assertEqual(result.execution_path, ExecutionPath.MEMORY)
        self.assertEqual(result.model_invocations, 0)
        self.assertEqual(self.factory.calls, calls_before)
        self.assertEqual(result.response, FACT_VALUE)
        self.assertIn("蓝鲸", result.response)
        self.assertIn(FACT_KEY, result.reason)
        self.assertIn("hybrid", result.reason)

    def test_above_threshold_run_log_hit_is_never_answered(self):
        # The sharp regression: a work_summary hit engineered above the
        # 0.55 threshold (keyword + alias entity) outranks the true
        # fact. The pre-fix code (max_facts=1) took this hit and would
        # have direct-answered the system log. The filter must skip it
        # and answer the true fact instead.
        self.resident.memory.remember(
            f"{SUMMARY_KEY_PREFIX}thread-9:event-9",
            ABOVE_THRESHOLD_NOISE_VALUE,
            aliases=(ABOVE_THRESHOLD_NOISE_ALIAS,),
        )
        self.assertIsNone(self.resident.memory.recall(QUESTION))

        old_top = self.resident.memory.recall_hybrid(QUESTION, max_facts=1)[0]
        self.assertTrue(str(old_top["key"]).startswith(SUMMARY_KEY_PREFIX))
        self.assertGreaterEqual(old_top["score"], _ORIENT_HYBRID_MIN_SCORE)

        match, score = self.resident._orient_memory_lookup(QUESTION)
        self.assertIsNotNone(match)
        assert match is not None and score is not None
        self.assertEqual(match.key, FACT_KEY)
        self.assertEqual(match.value, FACT_VALUE)
        self.assertGreaterEqual(score, _ORIENT_HYBRID_MIN_SCORE)

        result = self.resident.submit(QUESTION)
        self.assertTrue(result.success)
        self.assertEqual(result.execution_path, ExecutionPath.MEMORY)
        self.assertEqual(result.model_invocations, 0)
        self.assertEqual(result.response, FACT_VALUE)
        self.assertIn(FACT_KEY, result.reason)

    def test_work_pitfall_prefix_is_skipped_too(self):
        # Same hazard through the second run-log prefix.
        self.resident.memory.remember(
            f"{PITFALL_KEY_PREFIX}event-7:0",
            "秘密项目代号蓝鲸，启动日期是2026-11-01，代号曾误记已更正。",
            aliases=(ABOVE_THRESHOLD_NOISE_ALIAS,),
        )
        self.assertIsNone(self.resident.memory.recall(QUESTION))

        old_top = self.resident.memory.recall_hybrid(QUESTION, max_facts=1)[0]
        self.assertTrue(str(old_top["key"]).startswith(PITFALL_KEY_PREFIX))
        self.assertGreaterEqual(old_top["score"], _ORIENT_HYBRID_MIN_SCORE)

        match, score = self.resident._orient_memory_lookup(QUESTION)
        self.assertIsNotNone(match)
        assert match is not None and score is not None
        self.assertEqual(match.key, FACT_KEY)
        self.assertEqual(match.value, FACT_VALUE)

        result = self.resident.submit(QUESTION)
        self.assertEqual(result.execution_path, ExecutionPath.MEMORY)
        self.assertEqual(result.response, FACT_VALUE)

    def test_window_of_only_run_logs_falls_through_to_model(self):
        # When the hybrid window holds nothing but run-log hits, the
        # helper reports no usable hit and the task falls through to
        # the normal model path -- the log is never rendered as the
        # answer.
        self._remember_keyword_noise()
        self.resident.memory.forget(FACT_KEY)

        match, score = self.resident._orient_memory_lookup(QUESTION)
        self.assertIsNone(match)
        self.assertIsNone(score)

        result = self.resident.submit(QUESTION)
        self.assertNotEqual(result.execution_path, ExecutionPath.MEMORY)
        self.assertEqual(result.response, "model answer")
        self.assertEqual(result.model_invocations, 1)


if __name__ == "__main__":
    unittest.main()
