"""T5: M-11 基线报告回归对比工具的单测。

全部纯函数测试，不触网、不调模型、不写报告：
- 按 task id 对齐 verdict + 失败分类（对齐 / 退化 / 修复 / 无变化）；
- 分类漂移（verdict 同、failure_class 变）；
- 新增 / 移除 / skipped / 未知 verdict；
- schema 校验失败路径；
- 文本渲染（红绿黄、--no-color、无变化收拢一行）；
- CLI 退出码：退化→1，无退化→0，报告坏→2。
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from zn_agent.core.live_model_evidence_diff import (
    STATUS_CLASS_DRIFT,
    STATUS_IMPROVEMENT,
    STATUS_NEW,
    STATUS_REGRESSION,
    STATUS_REMOVED,
    STATUS_SKIPPED_CHANGE,
    STATUS_UNCHANGED,
    STATUS_UNKNOWN,
    diff_reports,
    load_report,
    render_text,
    to_json,
    main,
)

TASK_IDS = ["research-01", "browser-01", "file-01", "file-02", "coding-01", "cross-01"]


def _task(task_id, verdict, failure_class, notes=""):
    return {
        "task_id": task_id,
        "title": task_id,
        "domain": "research" if task_id.startswith("research") else "file",
        "verdict": verdict,
        "failure_class": failure_class,
        "duration_s": 1.0,
        "missing_items": [],
        "evidence_excerpts": [],
        "notes": notes,
    }


def _report(run_id, specs):
    return {
        "schema": "zn-live-model-evidence/v1",
        "run_id": run_id,
        "model": "deepseek-flash",
        "mode": "live",
        "gate": {},
        "harness_version": "0.1.0",
        "started_at": "t0",
        "finished_at": "t1",
        "summary": {"total": len(specs)},
        "tasks": [_task(tid, v, fc) for tid, v, fc in specs],
    }


class DiffAlignTest(unittest.TestCase):
    """对齐 / 退化 / 修复 / 无变化 四条路。"""

    def test_all_unchanged(self):
        before = _report("r1", [(t, "verified", "none") for t in TASK_IDS])
        after = _report("r2", [(t, "verified", "none") for t in TASK_IDS])
        diff = diff_reports(before, after)
        self.assertEqual(len(diff.entries), 6)
        self.assertTrue(all(e.status == STATUS_UNCHANGED for e in diff.entries))
        self.assertFalse(diff.has_regression)
        self.assertEqual(diff.summary[STATUS_UNCHANGED], 6)

    def test_regression_verified_to_rejected(self):
        before = _report("r1", [("research-01", "verified", "none")])
        after = _report("r2", [("research-01", "rejected", "model_capability")])
        diff = diff_reports(before, after)
        (entry,) = diff.entries
        self.assertEqual(entry.status, STATUS_REGRESSION)
        self.assertEqual(entry.before_verdict, "verified")
        self.assertEqual(entry.after_verdict, "rejected")
        self.assertTrue(diff.has_regression)

    def test_regression_partial_to_rejected(self):
        before = _report("r1", [("research-01", "partial", "verification_gap")])
        after = _report("r2", [("research-01", "rejected", "model_capability")])
        (entry,) = diff_reports(before, after).entries
        self.assertEqual(entry.status, STATUS_REGRESSION)

    def test_improvement_rejected_to_verified(self):
        before = _report("r1", [("coding-01", "rejected", "model_capability")])
        after = _report("r2", [("coding-01", "verified", "none")])
        (entry,) = diff_reports(before, after).entries
        self.assertEqual(entry.status, STATUS_IMPROVEMENT)
        self.assertFalse(diff_reports(before, after).has_regression)


class ClassDriftTest(unittest.TestCase):
    """verdict 相同但失败分类变了——漂移，不是退化也不是修复。"""

    def test_class_drift_flagged(self):
        before = _report("r1", [("browser-01", "rejected", "model_capability")])
        after = _report("r2", [("browser-01", "rejected", "tool_environment")])
        (entry,) = diff_reports(before, after).entries
        self.assertEqual(entry.status, STATUS_CLASS_DRIFT)
        self.assertEqual(entry.before_class, "model_capability")
        self.assertEqual(entry.after_class, "tool_environment")
        self.assertFalse(diff_reports(before, after).has_regression)

    def test_same_verdict_same_class_is_unchanged(self):
        before = _report("r1", [("browser-01", "partial", "verification_gap")])
        after = _report("r2", [("browser-01", "partial", "verification_gap")])
        (entry,) = diff_reports(before, after).entries
        self.assertEqual(entry.status, STATUS_UNCHANGED)


class EdgeCasesTest(unittest.TestCase):
    def test_new_and_removed_tasks(self):
        before = _report("r1", [("a", "verified", "none"), ("b", "verified", "none")])
        after = _report("r2", [("b", "verified", "none"), ("c", "verified", "none")])
        by_id = {e.task_id: e for e in diff_reports(before, after).entries}
        self.assertEqual(by_id["a"].status, STATUS_REMOVED)
        self.assertEqual(by_id["b"].status, STATUS_UNCHANGED)
        self.assertEqual(by_id["c"].status, STATUS_NEW)

    def test_skipped_change_is_neutral(self):
        before = _report("r1", [("research-01", "skipped", "none")])
        after = _report("r2", [("research-01", "verified", "none")])
        (entry,) = diff_reports(before, after).entries
        self.assertEqual(entry.status, STATUS_SKIPPED_CHANGE)
        self.assertFalse(diff_reports(before, after).has_regression)

    def test_unknown_verdict_is_neutral(self):
        before = _report("r1", [("research-01", "weird", "none")])
        after = _report("r2", [("research-01", "verified", "none")])
        (entry,) = diff_reports(before, after).entries
        self.assertEqual(entry.status, STATUS_UNKNOWN)
        self.assertFalse(diff_reports(before, after).has_regression)


class LoadReportTest(unittest.TestCase):
    def test_schema_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            data = _report("r1", [])
            data["schema"] = "something-else/v9"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                load_report(path)
            self.assertIn("schema", str(ctx.exception))

    def test_malformed_json_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_report(path)

    def test_missing_task_id_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            data = _report("r1", [])
            data["tasks"] = [{"verdict": "verified"}]
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_report(path)


class RenderTest(unittest.TestCase):
    def _diff(self):
        before = _report(
            "r1",
            [
                ("research-01", "verified", "none"),
                ("browser-01", "rejected", "model_capability"),
                ("file-01", "rejected", "model_capability"),
                ("file-02", "verified", "none"),
                ("coding-01", "partial", "verification_gap"),
                ("cross-01", "verified", "none"),
            ],
        )
        after = _report(
            "r2",
            [
                ("research-01", "rejected", "model_capability"),  # 退化
                ("browser-01", "verified", "none"),  # 修复
                ("file-01", "rejected", "tool_environment"),  # 分类漂移
                ("file-02", "verified", "none"),
                ("coding-01", "partial", "verification_gap"),
                ("cross-01", "verified", "none"),
            ],
        )
        return diff_reports(before, after)

    def test_regression_red_improvement_green_drift_yellow(self):
        text = render_text(self._diff(), color=True)
        self.assertIn("\033[31m", text)  # 红
        self.assertIn("\033[32m", text)  # 绿
        self.assertIn("\033[33m", text)  # 黄
        self.assertIn("research-01", text)
        self.assertIn("browser-01", text)

    def test_no_color(self):
        text = render_text(self._diff(), color=False)
        self.assertNotIn("\033[", text)
        self.assertIn("[退化]", text)
        self.assertIn("[修复]", text)

    def test_unchanged_collapsed_to_one_line(self):
        text = render_text(self._diff(), color=False)
        collapsed = [
            line for line in text.splitlines() if line.startswith("无变化")
        ]
        self.assertEqual(len(collapsed), 1)
        self.assertIn("3 项", collapsed[0])


class JsonOutputTest(unittest.TestCase):
    def test_to_json_machine_readable(self):
        diff = self._make_simple()
        payload = to_json(diff)
        self.assertEqual(payload["schema"], "zn-live-model-evidence-diff/v1")
        self.assertTrue(payload["has_regression"])
        by_id = {e["task_id"]: e for e in payload["entries"]}
        self.assertEqual(by_id["research-01"]["status"], STATUS_REGRESSION)

    def _make_simple(self):
        before = _report("r1", [("research-01", "verified", "none")])
        after = _report("r2", [("research-01", "rejected", "model_capability")])
        return diff_reports(before, after)


class CliExitCodeTest(unittest.TestCase):
    def _write(self, tmp, name, specs):
        path = Path(tmp) / name
        path.write_text(
            json.dumps(_report(name, specs), ensure_ascii=False), encoding="utf-8"
        )
        return str(path)

    def test_exit_1_on_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            before = self._write(tmp, "b.json", [("a", "verified", "none")])
            after = self._write(tmp, "a.json", [("a", "rejected", "model_capability")])
            with redirect_stdout(io.StringIO()):
                rc = main([before, after, "--no-color"])
            self.assertEqual(rc, 1)

    def test_exit_0_when_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            before = self._write(tmp, "b.json", [("a", "rejected", "model_capability")])
            after = self._write(tmp, "a.json", [("a", "verified", "none")])
            with redirect_stdout(io.StringIO()):
                rc = main([before, after, "--no-color"])
            self.assertEqual(rc, 0)

    def test_exit_2_on_bad_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{}", encoding="utf-8")
            good = self._write(tmp, "g.json", [])
            with redirect_stdout(io.StringIO()):
                rc = main([str(bad), good, "--no-color"])
            self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
