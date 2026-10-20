"""M-11: opt-in 真实模型端到端证据收集 harness（判断力）。

背景：仓库现有测试的 provider 响应全是受控测试边界，
``docs/ZN-IMPLEMENTATION-STATUS.md`` 明确写了"不是真实模型质量证据"。
这个 harness 提供可重复的证据收集机制：在真实模型下跑一组跨域代表
任务，用 CP-3 判定器（``completion_verdict``，M-5 已推广到单人 Work 的
同一判定器）对每条任务打 verdict，并按确定性规则做失败分类，
产出格式稳定的证据报告，供后续切片当回归基线。

设计边界（M-11 范围）：
- 只读模型调用层（``cognitive_factory`` / ``cognitive_resource``），
  **不改任何产品代码路径**，不触达内核/团队/审批运行时。
- opt-in 闸门：默认不触网。``ZN_E2E_LIVE=1`` 且模型路由能解析出凭证
  时才走真实模型；否则只校验任务集合法性并产出 dry-run 报告，
  跳过的任务明确记录跳过原因，而不是假跑。
- 凭证只走环境变量/现有安全存储引用，永不写入代码、日志与报告。

任务集：声明式 JSON（``evidence/live_model_taskset.json``），覆盖研究 /
浏览器 / 文件 / 编码 / 跨面 五个域。每个任务自带 expected_output
（CP-3 终报逐项举证的验收口径）与一组确定性检查：
- ``fact_markers``: 模型输出原文必须命中的事实标记（研究类）。全命中时
  登记一条 objective 为「事实标记核查」的证据条目，供终报引用；缺标记
  时不登记，引用落空、判定保持 partial。
- ``file_content``: 模型产物（终报 evidence 条目可选携带 ``artifact``
  字段）由 harness 写到隔离 scratch 目录后做存在性 / 内容命中 /
  JSON 或 Python 解析检查。
- ``python_run``: 编码类任务，harness 用**仓库自带**的测试片段在子进程
  里执行模型产物（隔离 scratch，超时熔断），记录真实运行证据。
- ``http_observation``: 浏览器类任务，harness 自己独立抓取同一 URL
  （仅 live 模式），把独立观测与模型报告做交叉比对。

CP-3 复用：终报形状与 ``adjudicate_completion`` 完全一致；harness
记录的 evidence 条目（``relative_path`` / ``objective`` / ``result``）
扮演"Body 验证证据"角色，模型终报必须逐条引用真实证据。

失败分类（确定性、可测试）：
- ``tool_environment``: 调用/抓取/检查执行本身抛异常（超时、断连、
  凭证缺失、HTTP 错误……）。
- ``model_capability``: 终报被 rejected（结构坏、引用越界、自相矛盾），
  或产物确定性检查失败（模型输出对不上）。
- ``verification_gap``: 终报结构成立但有验收项缺匹配证据（partial）。
- ``other``: 兜底；``none``: verified 或被闸门跳过。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .completion_verdict import adjudicate_completion

HARNESS_VERSION = "0.1.0"
REPORT_SCHEMA = "zn-live-model-evidence/v1"
TASKSET_SCHEMA = "zn-live-model-taskset/v1"

LIVE_ENV = "ZN_E2E_LIVE"
MODEL_ENV = "ZN_E2E_MODEL"
DEFAULT_MODEL = "deepseek-chat"

DOMAINS = ("research", "browser", "file", "coding", "cross_domain")

# 失败分类（报告里写英文常量，中文含义见模块 docstring）。
FAILURE_NONE = "none"
FAILURE_MODEL_CAPABILITY = "model_capability"
FAILURE_TOOL_ENVIRONMENT = "tool_environment"
FAILURE_VERIFICATION_GAP = "verification_gap"
FAILURE_OTHER = "other"

CHECK_KINDS = ("fact_markers", "file_content", "python_run", "http_observation")


# ---------------------------------------------------------------------------
# 任务集 schema 校验
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    domain: str
    title: str
    system_guidance: str
    user_prompt: str
    expected_output: tuple[str, ...]
    checks: tuple[dict[str, Any], ...] = ()
    timeout_s: int = 120


def _check_spec(check: Mapping[str, Any], *, task_id: str, index: int) -> dict[str, Any]:
    if not isinstance(check, Mapping):
        raise ValueError(f"任务 {task_id} 的第 {index} 个检查不是对象")
    kind = str(check.get("kind") or "").strip()
    if kind not in CHECK_KINDS:
        raise ValueError(f"任务 {task_id} 的第 {index} 个检查 kind 非法：{kind!r}")
    normalized = dict(check)
    if kind in ("fact_markers",):
        markers = check.get("markers")
        if not isinstance(markers, list) or not markers or not all(
            str(m).strip() for m in markers
        ):
            raise ValueError(f"任务 {task_id} 的 fact_markers 检查需要非空 markers")
    elif kind == "file_content":
        if not str(check.get("ref") or "").strip():
            raise ValueError(f"任务 {task_id} 的 file_content 检查需要 ref（证据引用路径）")
    elif kind == "python_run":
        if not str(check.get("test_snippet") or "").strip():
            raise ValueError(f"任务 {task_id} 的 python_run 检查需要 test_snippet")
    elif kind == "http_observation":
        if not str(check.get("url") or "").strip():
            raise ValueError(f"任务 {task_id} 的 http_observation 检查需要 url")
    return normalized


def _task_spec(data: Mapping[str, Any], *, index: int) -> TaskSpec:
    where = f"第 {index} 个任务"
    if not isinstance(data, Mapping):
        raise ValueError(f"{where}不是对象")
    task_id = str(data.get("id") or "").strip()
    if not task_id:
        raise ValueError(f"{where}缺 id")
    domain = str(data.get("domain") or "").strip()
    if domain not in DOMAINS:
        raise ValueError(f"任务 {task_id} 的 domain 非法：{domain!r}")
    title = str(data.get("title") or "").strip()
    system_guidance = str(data.get("system_guidance") or "")
    user_prompt = str(data.get("user_prompt") or "").strip()
    if not user_prompt:
        raise ValueError(f"任务 {task_id} 缺 user_prompt")
    expected = data.get("expected_output")
    if not isinstance(expected, list) or not [
        str(x).strip() for x in expected if str(x).strip()
    ]:
        raise ValueError(f"任务 {task_id} 的 expected_output 必须是非空列表")
    checks_raw = data.get("checks", [])
    if not isinstance(checks_raw, list):
        raise ValueError(f"任务 {task_id} 的 checks 必须是列表")
    checks = tuple(
        _check_spec(item, task_id=task_id, index=i)
        for i, item in enumerate(checks_raw)
    )
    timeout = data.get("timeout_s", 120)
    try:
        timeout_s = max(10, int(timeout))
    except (TypeError, ValueError):
        raise ValueError(f"任务 {task_id} 的 timeout_s 非法：{timeout!r}")
    return TaskSpec(
        task_id=task_id,
        domain=domain,
        title=title,
        system_guidance=system_guidance,
        user_prompt=user_prompt,
        expected_output=tuple(str(x).strip() for x in expected if str(x).strip()),
        checks=checks,
        timeout_s=timeout_s,
    )


def load_task_set(path: str | Path) -> list[TaskSpec]:
    """加载并严格校验任务集；非法即抛 ValueError，错误信息带任务定位。"""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"任务集文件不存在：{path}")
    except (OSError, ValueError) as exc:
        raise ValueError(f"任务集文件解析失败：{path}：{exc}")
    if not isinstance(raw, Mapping):
        raise ValueError(f"任务集顶层必须是对象：{path}")
    if str(raw.get("schema") or "").strip() != TASKSET_SCHEMA:
        raise ValueError(
            f"任务集 schema 必须是 {TASKSET_SCHEMA!r}：{path}"
        )
    tasks_raw = raw.get("tasks")
    if not isinstance(tasks_raw, list) or not tasks_raw:
        raise ValueError(f"任务集 tasks 必须是非空列表：{path}")
    specs = [_task_spec(item, index=i) for i, item in enumerate(tasks_raw)]
    seen: dict[str, int] = {}
    for spec in specs:
        seen[spec.task_id] = seen.get(spec.task_id, 0) + 1
    dupes = sorted(task_id for task_id, count in seen.items() if count > 1)
    if dupes:
        raise ValueError(f"任务集 id 重复：{', '.join(dupes)}")
    domains = {spec.domain for spec in specs}
    missing = [domain for domain in DOMAINS if domain not in domains]
    if missing:
        raise ValueError(f"任务集缺域：{', '.join(missing)}（至少每域一个）")
    return specs


# ---------------------------------------------------------------------------
# opt-in 闸门
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LiveGate:
    enabled: bool
    reason: str
    model: str = ""


def resolve_live_gate(*, environ: Mapping[str, str] | None = None) -> LiveGate:
    """解析 opt-in 闸门。纯逻辑：不触网、不打印凭证。"""
    env = environ if environ is not None else os.environ
    if str(env.get(LIVE_ENV) or "").strip() != "1":
        return LiveGate(
            enabled=False,
            reason=f"未设置 {LIVE_ENV}=1：opt-in 闸门关闭，真实模型调用被跳过",
        )
    model = str(env.get(MODEL_ENV) or "").strip() or DEFAULT_MODEL
    try:
        # 延迟导入：CI/单测环境不装模型依赖时，闸门关闭路径不受影响。
        # 注意 resolve_zn_cognitive_route 固定读 os.environ（它不接受
        # environ 参数）；带自定义 environ 的单测用 mock.patch.dict(os.environ)。
        from .cognitive_factory import resolve_zn_cognitive_route
        from .models import ModelRoute

        resolve_zn_cognitive_route(
            ModelRoute(route_id="m11-live-gate-probe", provider="auto", model=model)
        )
    except Exception as exc:  # 缺凭证 / 路由非法都算闸门关闭
        return LiveGate(
            enabled=False,
            reason=f"模型路由解析失败（通常缺凭证）：{type(exc).__name__}",
            model=model,
        )
    return LiveGate(
        enabled=True,
        reason="闸门开启：模型路由已就绪（凭证存在性已确认，值不记录）",
        model=model,
    )


def build_live_invoke(model: str) -> Callable[[str, str], str]:
    """构造真实模型调用（仅闸门开启后调用）。异常向上传，由 runner 归类。"""

    def _invoke(question: str, context: str) -> str:
        from .cognitive_factory import resolve_zn_cognitive_route
        from .cognitive_resource import OpenAICompatibleCognitiveResource
        from .models import ModelRoute

        route = resolve_zn_cognitive_route(
            ModelRoute(route_id="m11-live-run", provider="auto", model=model)
        )
        resource = OpenAICompatibleCognitiveResource(route)
        increment = resource.invoke(question=question, context=context)
        return str(increment.text or "")

    return _invoke


# ---------------------------------------------------------------------------
# 终报提取与确定性检查
# ---------------------------------------------------------------------------


def extract_completion_report(text: str) -> dict[str, Any] | None:
    """从模型输出中提取终报 JSON。提取失败返回 None（判 rejected 的输入）。"""
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        parsed = None
    if not isinstance(parsed, dict) or "completion_report" not in parsed:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(raw[start : end + 1])
            except ValueError:
                return None
        else:
            return None
    if not isinstance(parsed, dict) or "completion_report" not in parsed:
        return None
    return parsed


@dataclass
class CheckOutcome:
    name: str
    passed: bool
    detail: str


@dataclass
class TaskOutcome:
    task_id: str
    domain: str
    title: str
    verdict: str  # verified | partial | rejected | skipped
    failure_class: str
    missing_items: list[str] = field(default_factory=list)
    evidence_excerpts: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    notes: str = ""


def classify(
    *,
    skipped: bool,
    error_kind: str | None,
    verdict: str,
    report_parse_failed: bool,
    deterministic_failed: bool,
) -> str:
    """失败分类：确定性规则，纯函数，可单测。"""
    if skipped:
        return FAILURE_NONE
    if error_kind is not None:
        return FAILURE_TOOL_ENVIRONMENT
    if verdict == "rejected" or report_parse_failed:
        return FAILURE_MODEL_CAPABILITY
    if deterministic_failed:
        return FAILURE_MODEL_CAPABILITY
    if verdict == "partial":
        return FAILURE_VERIFICATION_GAP
    if verdict == "verified":
        return FAILURE_NONE
    return FAILURE_OTHER


def _run_fact_markers(
    check: Mapping[str, Any],
    model_text: str,
    evidence: list[dict[str, Any]],
) -> CheckOutcome:
    markers = [str(m) for m in check.get("markers", [])]
    missing = [m for m in markers if m not in model_text]
    if missing:
        return CheckOutcome(
            name="fact_markers",
            passed=False,
            detail=f"缺事实标记 {len(missing)}/{len(markers)}：{', '.join(missing[:5])}",
        )
    # 全命中才登记证据条目：该条目即"Body 已验证"的核查记录，
    # 终报以 objective「事实标记核查」引用它。缺标记时不登记，
    # 引用落空，判定保持 partial，不让未核查的回答借引用过关。
    evidence.append(
        {
            "relative_path": "",
            "objective": "事实标记核查",
            "result": (
                f"模型终报命中全部 {len(markers)} 个事实标记："
                f"{'、'.join(markers)}"
            ),
        }
    )
    return CheckOutcome(
        name="fact_markers", passed=True, detail=f"事实标记 {len(markers)} 个全命中"
    )


def _run_file_content(
    check: Mapping[str, Any],
    artifacts: dict[str, str],
    scratch: Path,
    evidence: list[dict[str, Any]],
) -> CheckOutcome:
    ref = str(check.get("ref") or "").strip()
    content = artifacts.get(ref)
    if content is None:
        return CheckOutcome(
            name="file_content", passed=False, detail=f"终报未给出证据 {ref!r} 的产物"
        )
    target = scratch / ref
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    evidence.append(
        {
            "relative_path": str(target.relative_to(scratch)),
            "objective": f"文件产物写出：{ref}",
            "result": f"写出 {target.stat().st_size} 字节到隔离 scratch",
        }
    )
    must_contain = [str(x) for x in (check.get("must_contain") or [])]
    missing = [x for x in must_contain if x not in content]
    if missing:
        return CheckOutcome(
            name="file_content",
            passed=False,
            detail=f"{ref} 缺必需内容：{', '.join(missing[:5])}",
        )
    must_parse = str(check.get("must_parse") or "").strip().lower()
    if must_parse == "json":
        try:
            json.loads(content)
        except ValueError as exc:
            return CheckOutcome(
                name="file_content", passed=False, detail=f"{ref} JSON 解析失败：{exc}"
            )
    elif must_parse == "python":
        try:
            compile(content, ref, "exec")
        except SyntaxError as exc:
            return CheckOutcome(
                name="file_content", passed=False, detail=f"{ref} Python 编译失败：{exc}"
            )
    return CheckOutcome(
        name="file_content",
        passed=True,
        detail=f"{ref} 内容命中 {len(must_contain)} 项"
        + (f"，{must_parse} 解析通过" if must_parse else ""),
    )


def _run_python_run(
    check: Mapping[str, Any],
    artifacts: dict[str, str],
    scratch: Path,
    evidence: list[dict[str, Any]],
    timeout_s: int,
) -> CheckOutcome:
    module_path = str(check.get("module_path") or "solution.py").strip()
    snippet = str(check.get("test_snippet") or "")
    solution = artifacts.get(module_path)
    if solution is None:
        return CheckOutcome(
            name="python_run",
            passed=False,
            detail=f"终报未给出证据 {module_path!r} 的产物",
        )
    (scratch / module_path).parent.mkdir(parents=True, exist_ok=True)
    (scratch / module_path).write_text(solution, encoding="utf-8")
    test_file = scratch / "_harness_test.py"
    # python -I 会忽略 PYTHONPATH，这里在文件头部注入隔离 scratch 的导入路径。
    bootstrap = (
        "import sys\n"
        f"sys.path.insert(0, {str(scratch)!r})\n"
    )
    test_file.write_text(bootstrap + snippet, encoding="utf-8")
    evidence.append(
        {
            "relative_path": str(Path(module_path)),
            "objective": "编码产物落盘",
            "result": f"模型产物写入隔离 scratch/{module_path}",
        }
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-I", str(test_file)],
            cwd=str(scratch),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        evidence.append(
            {
                "relative_path": str(test_file.relative_to(scratch)),
                "objective": "运行时测试执行",
                "result": f"子进程执行超时（{timeout_s}s）",
            }
        )
        return CheckOutcome(
            name="python_run", passed=False, detail=f"测试执行超时（{timeout_s}s）"
        )
    tail = (proc.stdout + proc.stderr)[-500:]
    evidence.append(
        {
            "relative_path": str(test_file.relative_to(scratch)),
            "objective": "运行时测试执行",
            "action_kind": "run_python" if proc.returncode == 0 else "run_failed",
            "result": f"退出码 {proc.returncode}；输出尾：{tail.strip()[:200]}",
        }
    )
    if proc.returncode != 0:
        return CheckOutcome(
            name="python_run",
            passed=False,
            detail=f"测试退出码 {proc.returncode}：{tail.strip()[:200]}",
        )
    return CheckOutcome(name="python_run", passed=True, detail="测试子进程退出码 0")


def _run_http_observation(
    check: Mapping[str, Any],
    model_text: str,
    evidence: list[dict[str, Any]],
    timeout_s: int,
) -> CheckOutcome:
    url = str(check.get("url") or "").strip()
    markers = [str(m) for m in check.get("markers", [])]
    request = urllib.request.Request(url, headers={"User-Agent": "ZN-live-model-harness/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = response.read(200_000).decode("utf-8", errors="replace")
            status = getattr(response, "status", 200)
    except Exception as exc:
        raise RuntimeError(f"独立抓取 {url} 失败：{type(exc).__name__}：{exc}")
    text_only = re.sub(r"<[^>]+>", " ", body)
    text_only = re.sub(r"\s+", " ", text_only)
    missing_page = [m for m in markers if m not in text_only]
    evidence.append(
        {
            "relative_path": "",
            "objective": f"独立抓取 {url}",
            "result": (
                f"HTTP {status}，抓取 {len(text_only)} 字符，"
                f"页面标记命中 {len(markers) - len(missing_page)}/{len(markers)}"
            ),
        }
    )
    if missing_page:
        return CheckOutcome(
            name="http_observation",
            passed=False,
            detail=f"独立抓取的页面缺标记：{', '.join(missing_page[:5])}（页面本身变化，属环境漂移）",
        )
    missing_model = [m for m in markers if m not in model_text]
    if missing_model:
        return CheckOutcome(
            name="http_observation",
            passed=False,
            detail=f"模型报告未提及页面标记：{', '.join(missing_model[:5])}",
        )
    return CheckOutcome(
        name="http_observation",
        passed=True,
        detail=f"独立抓取与模型报告交叉命中 {len(markers)} 个标记",
    )


def run_task(
    task: TaskSpec,
    *,
    model_invoke: Callable[[str, str], str],
    scratch_root: Path,
    live: bool,
) -> TaskOutcome:
    """跑单个任务：调模型 → 终报提取 → 确定性检查 → CP-3 判定 → 分类。"""
    started = time.monotonic()
    evidence: list[dict[str, Any]] = []
    notes: list[str] = []
    error_kind: str | None = None

    http_checks = [c for c in task.checks if c.get("kind") == "http_observation"]
    if http_checks and not live:
        return TaskOutcome(
            task_id=task.task_id,
            domain=task.domain,
            title=task.title,
            verdict="skipped",
            failure_class=FAILURE_NONE,
            duration_s=time.monotonic() - started,
            notes="http_observation 检查需要 live 模式（真实抓取），闸门关闭时跳过",
        )

    scratch = scratch_root / task.task_id
    scratch.mkdir(parents=True, exist_ok=True)

    try:
        model_text = model_invoke(task.user_prompt, task.system_guidance)
    except Exception as exc:
        error_kind = type(exc).__name__
        notes.append(f"模型调用抛异常：{error_kind}：{str(exc)[:200]}")
        return TaskOutcome(
            task_id=task.task_id,
            domain=task.domain,
            title=task.title,
            verdict="rejected",
            failure_class=classify(
                skipped=False,
                error_kind=error_kind,
                verdict="rejected",
                report_parse_failed=True,
                deterministic_failed=True,
            ),
            duration_s=time.monotonic() - started,
            notes="；".join(notes),
        )

    report = extract_completion_report(model_text)
    report_parse_failed = report is None
    artifacts: dict[str, str] = {}
    if report is not None:
        for entry in (report.get("completion_report") or {}).get("evidence", []):
            if isinstance(entry, dict):
                ref = str(entry.get("evidence_ref") or "").strip()
                artifact = entry.get("artifact")
                if ref and isinstance(artifact, str):
                    artifacts[ref] = artifact

    check_outcomes: list[CheckOutcome] = []
    check_error: str | None = None
    for check in task.checks:
        kind = check.get("kind")
        try:
            if kind == "fact_markers":
                check_outcomes.append(_run_fact_markers(check, model_text, evidence))
            elif kind == "file_content":
                check_outcomes.append(
                    _run_file_content(check, artifacts, scratch, evidence)
                )
            elif kind == "python_run":
                check_outcomes.append(
                    _run_python_run(
                        check, artifacts, scratch, evidence, timeout_s=task.timeout_s
                    )
                )
            elif kind == "http_observation":
                check_outcomes.append(
                    _run_http_observation(
                        check, model_text, evidence, timeout_s=task.timeout_s
                    )
                )
        except Exception as exc:
            check_error = f"{kind} 检查执行失败：{type(exc).__name__}：{str(exc)[:200]}"
            notes.append(check_error)
            error_kind = type(exc).__name__
            break

    deterministic_failed = any(not outcome.passed for outcome in check_outcomes)
    for outcome in check_outcomes:
        notes.append(f"[{outcome.name}] {'通过' if outcome.passed else '失败'}：{outcome.detail}")

    evidence.append(
        {
            "relative_path": "",
            "objective": "模型终报原文",
            "result": f"收到 {len(model_text)} 字符；终报提取{'成功' if report else '失败'}",
        }
    )

    if report is None:
        verdict_obj = adjudicate_completion(
            expected_output=list(task.expected_output),
            evidence=evidence,
            summary="",
        )
    else:
        verdict_obj = adjudicate_completion(
            expected_output=list(task.expected_output),
            evidence=evidence,
            summary=json.dumps(report, ensure_ascii=False),
        )

    failure_class = classify(
        skipped=False,
        error_kind=error_kind,
        verdict=verdict_obj.verdict,
        report_parse_failed=report_parse_failed,
        deterministic_failed=deterministic_failed,
    )
    excerpts = [
        (entry.get("objective") or "") + " | " + str(entry.get("result") or "")[:160]
        for entry in evidence
    ]
    return TaskOutcome(
        task_id=task.task_id,
        domain=task.domain,
        title=task.title,
        verdict=verdict_obj.verdict,
        failure_class=failure_class,
        missing_items=list(verdict_obj.missing_items or []),
        evidence_excerpts=excerpts,
        duration_s=time.monotonic() - started,
        notes="；".join(notes),
    )


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------


@dataclass
class EvidenceReport:
    run_id: str
    started_at: str
    finished_at: str
    mode: str  # live | dry
    model: str
    gate_reason: str
    outcomes: list[TaskOutcome] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        verdicts: dict[str, int] = {}
        for outcome in self.outcomes:
            counts[outcome.failure_class] = counts.get(outcome.failure_class, 0) + 1
            verdicts[outcome.verdict] = verdicts.get(outcome.verdict, 0) + 1
        return {
            "total": len(self.outcomes),
            "by_verdict": verdicts,
            "by_failure_class": counts,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": REPORT_SCHEMA,
            "harness_version": HARNESS_VERSION,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "mode": self.mode,
            "model": self.model,
            "gate": {"reason": self.gate_reason},
            "tasks": [
                {
                    "task_id": outcome.task_id,
                    "domain": outcome.domain,
                    "title": outcome.title,
                    "verdict": outcome.verdict,
                    "failure_class": outcome.failure_class,
                    "missing_items": outcome.missing_items,
                    "duration_s": round(outcome.duration_s, 2),
                    "evidence_excerpts": outcome.evidence_excerpts,
                    "notes": outcome.notes,
                }
                for outcome in self.outcomes
            ],
            "summary": self.summary(),
        }

    def to_markdown(self) -> str:
        summary = self.summary()
        lines = [
            f"# ZN 真实模型端到端证据报告（{self.run_id}）",
            "",
            f"- 模式：{self.mode}（模型：{self.model}）",
            f"- 闸门：{self.gate_reason}",
            f"- 时间：{self.started_at} → {self.finished_at}",
            f"- schema：{REPORT_SCHEMA} / harness v{HARNESS_VERSION}",
            f"- 汇总：共 {summary['total']} 项，"
            + "、".join(f"{k}={v}" for k, v in sorted(summary["by_verdict"].items())),
            f"- 失败分类：" + "、".join(
                f"{k}={v}" for k, v in sorted(summary["by_failure_class"].items())
            ),
            "",
            "| 任务 | 域 | verdict | 失败类 | 耗时(s) | 缺失项 |",
            "|---|---|---|---|---|---|",
        ]
        for outcome in self.outcomes:
            missing = "；".join(outcome.missing_items) or "-"
            lines.append(
                f"| {outcome.task_id} | {outcome.domain} | {outcome.verdict} | "
                f"{outcome.failure_class} | {outcome.duration_s:.1f} | {missing} |"
            )
        lines += ["", "## 任务明细", ""]
        for outcome in self.outcomes:
            lines += [
                f"### {outcome.task_id}（{outcome.domain}）{outcome.title}",
                "",
                f"- verdict：{outcome.verdict}；失败类：{outcome.failure_class}",
                f"- 备注：{outcome.notes or '-'}",
                "- 证据摘录：",
            ]
            for excerpt in outcome.evidence_excerpts:
                lines.append(f"  - {excerpt}")
            lines.append("")
        return "\n".join(lines)


def run_all(
    tasks: Sequence[TaskSpec],
    *,
    model_invoke: Callable[[str, str], str] | None,
    scratch_root: Path,
    live: bool,
    model_name: str,
    gate_reason: str,
) -> EvidenceReport:
    """跑全量任务集并产出报告。dry 模式用注入的 mock invoke。"""
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    run_id = time.strftime("%Y%m%d-%H%M%S")
    invoke = model_invoke
    if invoke is None:

        def _missing_invoke(question: str, context: str) -> str:
            raise RuntimeError("dry 模式未注入模型实现：只做任务集校验，不应走到这里")

        invoke = _missing_invoke

    outcomes: list[TaskOutcome] = []
    for task in tasks:
        outcomes.append(
            run_task(task, model_invoke=invoke, scratch_root=scratch_root, live=live)
        )
    finished_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    return EvidenceReport(
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        mode="live" if live else "dry",
        model=model_name,
        gate_reason=gate_reason,
        outcomes=outcomes,
    )


def write_report(report: EvidenceReport, out_dir: str | Path) -> tuple[Path, Path]:
    """写出 JSON + Markdown 报告（固定 schema，跨次可对比）。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = report.to_dict()
    json_path = out_dir / f"{report.run_id}.json"
    md_path = out_dir / f"{report.run_id}.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(report.to_markdown() + "\n", encoding="utf-8")
    return json_path, md_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="M-11 opt-in 真实模型端到端证据收集 harness"
    )
    parser.add_argument("--taskset", required=True, help="任务集 JSON 路径")
    parser.add_argument("--out", required=True, help="报告输出目录")
    parser.add_argument(
        "--scratch",
        default="",
        help="隔离 scratch 目录（默认在输出目录下建 _scratch）",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="请求真实模型调用（仍需 ZN_E2E_LIVE=1 闸门；无凭证则任务跳过）",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.live:
        os.environ[LIVE_ENV] = "1"

    try:
        tasks = load_task_set(args.taskset)
    except ValueError as exc:
        print(f"任务集非法：{exc}", file=sys.stderr)
        return 2
    print(f"任务集合法：{len(tasks)} 个任务，域：{sorted({t.domain for t in tasks})}")

    gate = resolve_live_gate()
    print(f"闸门：{'开启' if gate.enabled else '关闭'}：{gate.reason}")
    model_name = gate.model or DEFAULT_MODEL

    out_dir = Path(args.out)
    scratch_root = Path(args.scratch) if args.scratch else out_dir / "_scratch"

    if gate.enabled:
        invoke: Callable[[str, str], str] | None = build_live_invoke(model_name)
    else:
        # dry 模式：无真实调用。任务集已校验；浏览器类（需真实抓取）
        # 任务按跳过记录，其余任务走确定性"无模型"路径也会如实记录失败。
        # 为避免 dry 报告里出现误导性的模型失败，dry 下统一注入
        # 一个明确标记的占位实现：只跑闸门/结构，不伪造模型证据。
        def _dry_invoke(question: str, context: str) -> str:
            raise RuntimeError(
                "dry-run：opt-in 闸门关闭，未做真实模型调用"
            )

        invoke = _dry_invoke

    report = run_all(
        tasks,
        model_invoke=invoke,
        scratch_root=scratch_root,
        live=gate.enabled,
        model_name=model_name,
        gate_reason=gate.reason,
    )
    json_path, md_path = write_report(report, out_dir)
    print(f"报告已写出：\n  {json_path}\n  {md_path}")
    print(f"汇总：{json.dumps(report.summary(), ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
