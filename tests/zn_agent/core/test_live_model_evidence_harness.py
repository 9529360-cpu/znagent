"""M-11: opt-in 真实模型端到端证据收集 harness 的单测。

全部用 mock 覆盖（CI 内可跑，不触网）：
- 任务集 schema 校验；
- 失败分类确定性逻辑；
- 终报提取；
- opt-in 闸门（默认关闭、无凭证关闭、有凭证开启——只做纯路由解析，不触网）；
- runner 四条路径（verified / rejected / partial / 调用异常）+ 干闸门跳过；
- 报告 JSON/Markdown 往返与写出。

真实模型调用只出现在 opt-in 路径，由 ZN_E2E_LIVE=1 闸门保护，
默认测试环境永远走不到。
"""

import json
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from zn_agent.core.live_model_evidence_harness import (
    DOMAINS,
    FAILURE_MODEL_CAPABILITY,
    FAILURE_NONE,
    FAILURE_OTHER,
    FAILURE_TOOL_ENVIRONMENT,
    FAILURE_VERIFICATION_GAP,
    EvidenceReport,
    TaskOutcome,
    TaskSpec,
    classify,
    extract_completion_report,
    load_task_set,
    resolve_live_gate,
    run_all,
    run_task,
    write_report,
)

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[3]  # tests/zn_agent/core/test_x.py -> 仓库根
TASKSET = REPO_ROOT / "evidence" / "live_model_taskset.json"


def _good_report(task):
    """构造一条结构合法、引用全匹配的终报 JSON（供 mock 模型用）。

    evidence_ref 引用 harness 记录的"模型终报原文"证据条目，
    ``_ref_matches`` 按子串双向匹配，可命中。
    """
    claims = []
    for criterion in task.expected_output:
        claims.append({"criterion": criterion, "evidence_ref": "模型终报原文"})
    report = {
        "completion_report": {
            "conclusion": "任务完成，证据齐备。",
            "evidence": claims,
            "files": [],
            "unfinished": [],
        }
    }
    return json.dumps(report, ensure_ascii=False)


class TestTaskSetSchema(unittest.TestCase):
    def test_repo_taskset_loads_and_covers_all_domains(self):
        tasks = load_task_set(TASKSET)
        self.assertGreaterEqual(len(tasks), 5)
        domains = {task.domain for task in tasks}
        for domain in DOMAINS:
            self.assertIn(domain, domains, f"任务集缺域：{domain}")
        ids = [task.task_id for task in tasks]
        self.assertEqual(len(ids), len(set(ids)))

    def test_repo_taskset_prompts_carry_shape_hint_and_criteria(self):
        # Q6 公平性：CP-3 契约要求 criterion 逐字引用验收项、终报为固定
        # JSON 形状——被测模型必须在任务内拿到这两样信息，否则 2026-10-20
        # 基线实测的"提取失败 / 引用越界"会重演（不是模型能力问题）。
        tasks = load_task_set(TASKSET)
        for task in tasks:
            self.assertIn(
                "<exact acceptance criterion>",
                task.system_guidance,
                f"{task.task_id} 的 system_guidance 缺终报结构说明",
            )
            self.assertIn("completion_report", task.system_guidance)
            for item in task.expected_output:
                self.assertIn(
                    item,
                    task.user_prompt,
                    f"{task.task_id} 的 user_prompt 缺验收项原文：{item}",
                )

    def _write(self, payload):
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(payload, tmp, ensure_ascii=False)
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        return tmp.name

    def _base_task(self):
        return {
            "id": "research-01",
            "domain": "research",
            "title": "t",
            "user_prompt": "p",
            "expected_output": ["验收一"],
            "checks": [],
        }

    def _base_set(self, tasks):
        return {"schema": "zn-live-model-taskset/v1", "tasks": tasks}

    def test_rejects_wrong_schema(self):
        path = self._write({"schema": "nope", "tasks": [self._base_task()]})
        with self.assertRaisesRegex(ValueError, "schema"):
            load_task_set(path)

    def test_rejects_unknown_domain(self):
        task = self._base_task()
        task["domain"] = "desktop"
        with self.assertRaisesRegex(ValueError, "domain"):
            load_task_set(self._write(self._base_set([task])))

    def test_rejects_missing_domain_coverage(self):
        with self.assertRaisesRegex(ValueError, "缺域"):
            load_task_set(self._write(self._base_set([self._base_task()])))

    def test_rejects_duplicate_ids(self):
        task = self._base_task()
        task["domain"] = "research"
        other = dict(task)
        other["domain"] = "browser"
        with self.assertRaisesRegex(ValueError, "重复"):
            load_task_set(self._write(self._base_set([task, other])))

    def test_rejects_empty_expected_output(self):
        task = self._base_task()
        task["expected_output"] = []
        with self.assertRaisesRegex(ValueError, "expected_output"):
            load_task_set(self._write(self._base_set([task])))

    def test_rejects_unknown_check_kind(self):
        task = self._base_task()
        task["checks"] = [{"kind": "teleport"}]
        with self.assertRaisesRegex(ValueError, "kind"):
            load_task_set(self._write(self._base_set([task])))

    def test_rejects_missing_file(self):
        with self.assertRaisesRegex(ValueError, "不存在"):
            load_task_set("/tmp/zn-m11-does-not-exist.json")


class TestClassify(unittest.TestCase):
    def test_skipped_is_none(self):
        self.assertEqual(
            classify(
                skipped=True,
                error_kind="TimeoutError",
                verdict="rejected",
                report_parse_failed=True,
                deterministic_failed=True,
            ),
            FAILURE_NONE,
        )

    def test_invoke_error_is_tool_environment(self):
        self.assertEqual(
            classify(
                skipped=False,
                error_kind="TimeoutError",
                verdict="rejected",
                report_parse_failed=True,
                deterministic_failed=True,
            ),
            FAILURE_TOOL_ENVIRONMENT,
        )

    def test_rejected_report_is_model_capability(self):
        self.assertEqual(
            classify(
                skipped=False,
                error_kind=None,
                verdict="rejected",
                report_parse_failed=False,
                deterministic_failed=False,
            ),
            FAILURE_MODEL_CAPABILITY,
        )

    def test_unparsable_report_is_model_capability(self):
        self.assertEqual(
            classify(
                skipped=False,
                error_kind=None,
                verdict="partial",
                report_parse_failed=True,
                deterministic_failed=False,
            ),
            FAILURE_MODEL_CAPABILITY,
        )

    def test_failed_deterministic_check_is_model_capability(self):
        self.assertEqual(
            classify(
                skipped=False,
                error_kind=None,
                verdict="partial",
                report_parse_failed=False,
                deterministic_failed=True,
            ),
            FAILURE_MODEL_CAPABILITY,
        )

    def test_partial_with_clean_checks_is_verification_gap(self):
        self.assertEqual(
            classify(
                skipped=False,
                error_kind=None,
                verdict="partial",
                report_parse_failed=False,
                deterministic_failed=False,
            ),
            FAILURE_VERIFICATION_GAP,
        )

    def test_verified_is_none(self):
        self.assertEqual(
            classify(
                skipped=False,
                error_kind=None,
                verdict="verified",
                report_parse_failed=False,
                deterministic_failed=False,
            ),
            FAILURE_NONE,
        )

    def test_unknown_verdict_is_other(self):
        self.assertEqual(
            classify(
                skipped=False,
                error_kind=None,
                verdict="mystery",
                report_parse_failed=False,
                deterministic_failed=False,
            ),
            FAILURE_OTHER,
        )


class TestExtractReport(unittest.TestCase):
    def test_pure_json(self):
        text = json.dumps({"completion_report": {"conclusion": "ok"}})
        self.assertEqual(
            extract_completion_report(text)["completion_report"]["conclusion"], "ok"
        )

    def test_prose_wrapped_json(self):
        text = "以下是终报：\n" + json.dumps(
            {"completion_report": {"conclusion": "ok"}}
        ) + "\n完毕。"
        parsed = extract_completion_report(text)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["completion_report"]["conclusion"], "ok")

    def test_garbage_returns_none(self):
        self.assertIsNone(extract_completion_report("就是搞定了，没有 JSON"))
        self.assertIsNone(extract_completion_report(""))
        self.assertIsNone(extract_completion_report('{"no_report": true}'))


class TestLiveGate(unittest.TestCase):
    def test_gate_closed_by_default(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            gate = resolve_live_gate()
        self.assertFalse(gate.enabled)
        self.assertIn("ZN_E2E_LIVE", gate.reason)

    def test_gate_closed_without_credential(self):
        with unittest.mock.patch.dict(os.environ, {"ZN_E2E_LIVE": "1"}, clear=True):
            gate = resolve_live_gate()
        self.assertFalse(gate.enabled)
        self.assertIn("凭证", gate.reason)

    def test_gate_open_with_deepseek_key(self):
        # 只做纯路由解析（provider=deepseek + 默认 base_url），不触网。
        fake_env = {"ZN_E2E_LIVE": "1", "DEEPSEEK_API_KEY": "test-only-not-real"}
        with unittest.mock.patch.dict(os.environ, fake_env, clear=True):
            gate = resolve_live_gate()
        self.assertTrue(gate.enabled)
        self.assertEqual(gate.model, "deepseek-chat")


class TestRunner(unittest.TestCase):
    def setUp(self):
        self.tasks = {task.task_id: task for task in load_task_set(TASKSET)}
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.scratch = Path(self.tmp.name) / "scratch"

    def _run(self, task_id, invoke, live=False):
        return run_task(
            self.tasks[task_id],
            model_invoke=invoke,
            scratch_root=self.scratch,
            live=live,
        )

    def test_research_verified_path(self):
        task = self.tasks["research-01"]
        markers = task.checks[0]["markers"]

        def fake(question, context):
            body = " ".join(markers)
            report = json.loads(_good_report(task))
            return body + "\n" + json.dumps(report, ensure_ascii=False)

        outcome = self._run("research-01", fake)
        self.assertEqual(outcome.verdict, "verified", outcome.notes)
        self.assertEqual(outcome.failure_class, FAILURE_NONE)
        self.assertEqual(outcome.missing_items, [])

    def test_file_verified_path(self):
        task = self.tasks["file-01"]
        artifact = json.dumps(
            {"name": "nightly", "schedule": "0 3 * * *", "enabled": True}
        )

        def fake(question, context):
            report = {
                "completion_report": {
                    "conclusion": "配置文件已生成。",
                    "evidence": [
                        {
                            "criterion": criterion,
                            "evidence_ref": "routine.json",
                            "artifact": artifact,
                        }
                        for criterion in task.expected_output
                    ],
                    "files": ["routine.json"],
                    "unfinished": [],
                }
            }
            return json.dumps(report, ensure_ascii=False)

        outcome = self._run("file-01", fake)
        self.assertEqual(outcome.verdict, "verified", outcome.notes)
        self.assertEqual(outcome.failure_class, FAILURE_NONE)
        written = self.scratch / "file-01" / "routine.json"
        self.assertTrue(written.exists())
        self.assertEqual(json.loads(written.read_text(encoding="utf-8"))["name"], "nightly")

    def test_coding_verified_path_runs_real_subprocess(self):
        task = self.tasks["coding-01"]
        fixed = "def total(prices):\n    s = 0\n    for p in prices:\n        s = s + p\n    return s\n"

        def fake(question, context):
            report = {
                "completion_report": {
                    "conclusion": "bug 已修复并通过运行测试。",
                    "evidence": [
                        {
                            "criterion": criterion,
                            "evidence_ref": "solution.py",
                            "artifact": fixed,
                        }
                        for criterion in task.expected_output
                    ],
                    "files": ["solution.py"],
                    "unfinished": [],
                }
            }
            return json.dumps(report, ensure_ascii=False)

        outcome = self._run("coding-01", fake)
        self.assertEqual(outcome.verdict, "verified", outcome.notes)
        self.assertEqual(outcome.failure_class, FAILURE_NONE)

    def test_coding_wrong_fix_is_model_capability(self):
        task = self.tasks["coding-01"]
        broken = "def total(prices):\n    return 0\n"

        def fake(question, context):
            report = {
                "completion_report": {
                    "conclusion": "修完了。",
                    "evidence": [
                        {
                            "criterion": criterion,
                            "evidence_ref": "solution.py",
                            "artifact": broken,
                        }
                        for criterion in task.expected_output
                    ],
                    "files": ["solution.py"],
                    "unfinished": [],
                }
            }
            return json.dumps(report, ensure_ascii=False)

        outcome = self._run("coding-01", fake)
        self.assertEqual(outcome.failure_class, FAILURE_MODEL_CAPABILITY)
        self.assertNotEqual(outcome.verdict, "verified")

    def test_research_fact_check_ref_docks_to_registered_evidence(self):
        # Q6 对接：fact_markers 全命中后登记 objective=「事实标记核查」的
        # 证据条目；按任务集指引引用它的终报应 verified（修复前账本只有
        # 「模型终报原文」一条，这类引用必然落空 → partial）。
        task = self.tasks["research-01"]
        markers = task.checks[0]["markers"]

        def fake(question, context):
            body = " ".join(markers)
            report = {
                "completion_report": {
                    "conclusion": "已按资料作答，事实齐备。",
                    "evidence": [
                        {"criterion": criterion, "evidence_ref": "事实标记核查"}
                        for criterion in task.expected_output
                    ],
                    "files": [],
                    "unfinished": [],
                }
            }
            return body + "\n" + json.dumps(report, ensure_ascii=False)

        outcome = self._run("research-01", fake)
        self.assertEqual(outcome.verdict, "verified", outcome.notes)
        self.assertEqual(outcome.failure_class, FAILURE_NONE)
        self.assertTrue(
            any("事实标记核查" in excerpt for excerpt in outcome.evidence_excerpts),
            outcome.evidence_excerpts,
        )

    def test_research_fact_check_not_registered_when_markers_missing(self):
        # 缺标记时不登记核查条目：同样的引用落空，判定保持 partial，
        # 且内容检查失败归类 model_capability，不借引用蒙混过关。
        # 用合成任务：标记词不出现在验收项里，缺标记才可真实复现
        # （仓库 research-01 的标记本身是验收项子串，引用即命中）。
        task = TaskSpec(
            task_id="research-synth",
            domain="research",
            title="合成研究任务",
            system_guidance="",
            user_prompt="作答",
            expected_output=("验收项甲", "验收项乙"),
            checks=({"kind": "fact_markers", "markers": ["标记X", "标记Y"]},),
        )

        def fake(question, context):
            report = {
                "completion_report": {
                    "conclusion": "已作答。",
                    "evidence": [
                        {"criterion": criterion, "evidence_ref": "事实标记核查"}
                        for criterion in task.expected_output
                    ],
                    "files": [],
                    "unfinished": [],
                }
            }
            return json.dumps(report, ensure_ascii=False)

        outcome = run_task(
            task,
            model_invoke=fake,
            scratch_root=self.scratch,
            live=False,
        )
        self.assertEqual(outcome.verdict, "partial", outcome.notes)
        self.assertEqual(outcome.failure_class, FAILURE_MODEL_CAPABILITY)
        self.assertEqual(
            sorted(outcome.missing_items), sorted(task.expected_output)
        )
        self.assertFalse(
            any("事实标记核查" in excerpt for excerpt in outcome.evidence_excerpts),
            outcome.evidence_excerpts,
        )

    def test_malformed_report_is_rejected_model_capability(self):
        outcome = self._run("research-01", lambda q, c: "搞定了，相信我")
        self.assertEqual(outcome.verdict, "rejected")
        self.assertEqual(outcome.failure_class, FAILURE_MODEL_CAPABILITY)

    def test_dangling_evidence_ref_is_partial_verification_gap(self):
        task = self.tasks["research-01"]

        def fake(question, context):
            report = {
                "completion_report": {
                    "conclusion": "完成了。",
                    "evidence": [
                        {
                            "criterion": criterion,
                            "evidence_ref": "不存在的证据-xyz-123",
                        }
                        for criterion in task.expected_output
                    ],
                    "files": [],
                    "unfinished": [],
                }
            }
            return json.dumps(report, ensure_ascii=False)

        outcome = self._run("research-01", fake)
        self.assertEqual(outcome.verdict, "partial", outcome.notes)
        self.assertEqual(outcome.failure_class, FAILURE_VERIFICATION_GAP)
        self.assertTrue(outcome.missing_items)

    def test_invoke_timeout_is_tool_environment(self):
        def fake(question, context):
            raise TimeoutError("model call timed out")

        outcome = self._run("research-01", fake)
        self.assertEqual(outcome.failure_class, FAILURE_TOOL_ENVIRONMENT)
        self.assertIn("TimeoutError", outcome.notes)

    def test_browser_task_skipped_when_gate_closed(self):
        outcome = self._run("browser-01", lambda q, c: "{}", live=False)
        self.assertEqual(outcome.verdict, "skipped")
        self.assertEqual(outcome.failure_class, FAILURE_NONE)
        self.assertIn("闸门", outcome.notes)


class TestReport(unittest.TestCase):
    def test_roundtrip_and_write(self):
        outcomes = [
            TaskOutcome(
                task_id="research-01",
                domain="research",
                title="t",
                verdict="verified",
                failure_class=FAILURE_NONE,
                duration_s=1.5,
                notes="ok",
            ),
            TaskOutcome(
                task_id="browser-01",
                domain="browser",
                title="t",
                verdict="skipped",
                failure_class=FAILURE_NONE,
                notes="闸门关闭",
            ),
        ]
        report = EvidenceReport(
            run_id="20990101-000000",
            started_at="2099-01-01T00:00:00+0000",
            finished_at="2099-01-01T00:01:00+0000",
            mode="dry",
            model="deepseek-chat",
            gate_reason="未设置 ZN_E2E_LIVE=1",
            outcomes=outcomes,
        )
        payload = report.to_dict()
        self.assertEqual(payload["schema"], "zn-live-model-evidence/v1")
        json.dumps(payload, ensure_ascii=False)  # 必须可序列化
        self.assertEqual(payload["summary"]["total"], 2)
        self.assertEqual(payload["summary"]["by_verdict"]["verified"], 1)
        md = report.to_markdown()
        self.assertIn("research-01", md)
        self.assertIn("browser-01", md)
        self.assertIn("zn-live-model-evidence/v1", md)

        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = write_report(report, tmp)
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            reloaded = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(reloaded["run_id"], "20990101-000000")
            # 稳定字段集：跨次对比只依赖这些键
            self.assertEqual(
                set(reloaded["tasks"][0].keys()),
                {
                    "task_id",
                    "domain",
                    "title",
                    "verdict",
                    "failure_class",
                    "missing_items",
                    "duration_s",
                    "evidence_excerpts",
                    "notes",
                },
            )

    def test_run_all_builds_report(self):
        tasks = load_task_set(TASKSET)
        with tempfile.TemporaryDirectory() as tmp:
            report = run_all(
                tasks,
                model_invoke=lambda q, c: (_ for _ in ()).throw(
                    RuntimeError("dry-run：opt-in 闸门关闭，未做真实模型调用")
                ),
                scratch_root=Path(tmp) / "scratch",
                live=False,
                model_name="deepseek-chat",
                gate_reason="测试闸门",
            )
        self.assertEqual(report.mode, "dry")
        self.assertEqual(len(report.outcomes), len(tasks))
        browser = next(o for o in report.outcomes if o.task_id == "browser-01")
        self.assertEqual(browser.verdict, "skipped")


if __name__ == "__main__":
    unittest.main()
