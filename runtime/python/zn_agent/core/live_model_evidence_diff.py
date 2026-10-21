"""T5: M-11 基线报告回归对比工具（判断力）。

背景：M-11 harness + Q6 修复后已有 6/6 verified 正式基线，但两次基线跑完
没有"对比 verdict 漂移"的工具，回归靠人眼——基线不守护就白跑。

这个工具是**纯只读的本地对比**：输入两份 schema 为
``zn-live-model-evidence/v1`` 的基线报告（``evidence/runs/<run_id>.json``），
按 task id 对齐 verdict 与失败分类，输出漂移清单。

漂移语义（按 verdict 严重等级排：verified > partial > rejected；
skipped 不计等级，单独列为"对照变化"）：
- ``regression``（退化，标红）：after 的 verdict 等级低于 before，
  如 verified → partial/rejected；
- ``improvement``（修复，标绿）：after 的 verdict 等级高于 before，
  如 rejected → verified；
- ``class_drift``（分类漂移）：verdict 相同但失败分类变了
  （如 rejected 的 failure_class 从 model_capability 变成 tool_environment，
  verdict 没变但原因换了，值得看一眼）；
- ``unchanged``（无变化）：verdict 与失败分类都相同，渲染时只收拢成一行；
- ``new`` / ``removed``：某侧报告多出/缺少的任务；
- ``skipped_change``：任一侧为 skipped（闸门跳过，无证据）——中性展示，
  既不红也不绿。

退出码（方便脚本/hook 调用）：
- 0：无退化、无错误；
- 1：至少一项退化；
- 2：用法或报告加载错误。

不进 CI 必需项：对比本身不需要模型、不触网、无需凭证，只读报告。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .live_model_evidence_harness import REPORT_SCHEMA

# verdict 严重等级：数值越大越好。skipped 无证据，不计等级。
VERDICT_RANK: dict[str, int] = {
    "verified": 3,
    "partial": 2,
    "rejected": 1,
}

# 状态常量（报告里写英文常量，中文含义见模块 docstring）。
STATUS_REGRESSION = "regression"
STATUS_IMPROVEMENT = "improvement"
STATUS_CLASS_DRIFT = "class_drift"
STATUS_UNCHANGED = "unchanged"
STATUS_SKIPPED_CHANGE = "skipped_change"
STATUS_NEW = "new"
STATUS_REMOVED = "removed"
STATUS_UNKNOWN = "unknown"


@dataclass(frozen=True)
class TaskEntry:
    """一条任务在两侧报告里的对照结果。"""

    task_id: str
    status: str
    before_verdict: str | None
    after_verdict: str | None
    before_class: str | None
    after_class: str | None
    domain: str = ""
    notes: str = ""


@dataclass
class BaselineDiff:
    """两份报告的完整对比结果。"""

    before_run_id: str
    after_run_id: str
    before_model: str
    after_model: str
    before_mode: str
    after_mode: str
    entries: list[TaskEntry] = field(default_factory=list)

    def by_status(self, status: str) -> list[TaskEntry]:
        return [e for e in self.entries if e.status == status]

    @property
    def has_regression(self) -> bool:
        return any(e.status == STATUS_REGRESSION for e in self.entries)

    @property
    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.entries:
            counts[e.status] = counts.get(e.status, 0) + 1
        return counts


# ---------------------------------------------------------------------------
# 报告加载与对齐
# ---------------------------------------------------------------------------


def load_report(path: str | Path) -> dict[str, Any]:
    """加载一份基线报告并做最小 schema 校验。

    只读，不写回。schema 不匹配或结构缺失时抛 ValueError。
    """
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"报告读不出来：{path}（{exc}）") from exc
    schema = data.get("schema")
    if schema != REPORT_SCHEMA:
        raise ValueError(
            f"schema 不匹配：{path} 是 {schema!r}，期望 {REPORT_SCHEMA!r}"
        )
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError(f"报告缺 tasks 列表：{path}")
    for index, task in enumerate(tasks):
        if not isinstance(task, dict) or not task.get("task_id"):
            raise ValueError(
                f"报告第 {index} 条任务缺 task_id：{path}"
            )
    return data


def _compare_entry(
    task_id: str,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
) -> TaskEntry:
    """按 verdict + 失败分类判定单任务状态（纯函数，可单测）。"""
    before_verdict = before.get("verdict") if before else None
    after_verdict = after.get("verdict") if after else None
    before_class = before.get("failure_class") if before else None
    after_class = after.get("failure_class") if after else None

    if before is None:
        return TaskEntry(
            task_id, STATUS_NEW, None, after_verdict, None, after_class,
            domain=str(after.get("domain", "")), notes=str(after.get("notes", "")),
        )
    if after is None:
        return TaskEntry(
            task_id, STATUS_REMOVED, before_verdict, None, before_class, None,
            domain=str(before.get("domain", "")), notes=str(before.get("notes", "")),
        )

    before_v = str(before_verdict)
    after_v = str(after_verdict)
    if before_v == "skipped" or after_v == "skipped":
        return TaskEntry(
            task_id, STATUS_SKIPPED_CHANGE, before_v, after_v,
            str(before_class), str(after_class),
            domain=str(after.get("domain", "")), notes=str(after.get("notes", "")),
        )

    rank_before = VERDICT_RANK.get(before_v)
    rank_after = VERDICT_RANK.get(after_v)
    if rank_before is None or rank_after is None:
        return TaskEntry(
            task_id, STATUS_UNKNOWN, before_v, after_v,
            str(before_class), str(after_class),
            domain=str(after.get("domain", "")), notes=str(after.get("notes", "")),
        )

    if rank_after > rank_before:
        status = STATUS_IMPROVEMENT
    elif rank_after < rank_before:
        status = STATUS_REGRESSION
    elif str(before_class) != str(after_class):
        status = STATUS_CLASS_DRIFT
    else:
        status = STATUS_UNCHANGED
    return TaskEntry(
        task_id, status, before_v, after_v, str(before_class), str(after_class),
        domain=str(after.get("domain", "")), notes=str(after.get("notes", "")),
    )


def diff_reports(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> BaselineDiff:
    """对比两份已加载的报告（before → after），返回结构化漂移清单。"""
    before_tasks = {t["task_id"]: t for t in before["tasks"]}
    after_tasks = {t["task_id"]: t for t in after["tasks"]}
    entries = [
        _compare_entry(task_id, before_tasks.get(task_id), after_tasks.get(task_id))
        for task_id in sorted(set(before_tasks) | set(after_tasks))
    ]
    return BaselineDiff(
        before_run_id=str(before.get("run_id", "?")),
        after_run_id=str(after.get("run_id", "?")),
        before_model=str(before.get("model", "?")),
        after_model=str(after.get("model", "?")),
        before_mode=str(before.get("mode", "?")),
        after_mode=str(after.get("mode", "?")),
        entries=entries,
    )


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------

_COLORS = {
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "reset": "\033[0m",
}

# 输出顺序：退化优先，其次修复；无变化最后只收拢一行。
_STATUS_ORDER = (
    STATUS_REGRESSION,
    STATUS_IMPROVEMENT,
    STATUS_CLASS_DRIFT,
    STATUS_SKIPPED_CHANGE,
    STATUS_NEW,
    STATUS_REMOVED,
    STATUS_UNKNOWN,
    STATUS_UNCHANGED,
)

_STATUS_CN = {
    STATUS_REGRESSION: "退化",
    STATUS_IMPROVEMENT: "修复",
    STATUS_CLASS_DRIFT: "分类漂移",
    STATUS_UNCHANGED: "无变化",
    STATUS_SKIPPED_CHANGE: "对照变化（skipped）",
    STATUS_NEW: "新增任务",
    STATUS_REMOVED: "移除任务",
    STATUS_UNKNOWN: "未知 verdict",
}


def _color(text: str, name: str, color: bool) -> str:
    if not color:
        return text
    return f"{_COLORS[name]}{text}{_COLORS['reset']}"


def render_text(diff: BaselineDiff, *, color: bool = True) -> str:
    """把对比结果渲染成人类可读文本。退化红、修复绿、分类漂移黄。"""
    lines: list[str] = []
    lines.append(
        f"基线对比：{diff.before_run_id}（{diff.before_model}/{diff.before_mode}）"
        f" → {diff.after_run_id}（{diff.after_model}/{diff.after_mode}）"
    )
    summary_parts = [
        f"{_STATUS_CN[s]} {diff.summary.get(s, 0)}" for s in _STATUS_ORDER
        if diff.summary.get(s)
    ]
    lines.append("摘要：" + ("，".join(summary_parts) or "无任务"))
    lines.append("")

    for status in _STATUS_ORDER:
        entries = diff.by_status(status)
        if not entries:
            continue
        if status == STATUS_UNCHANGED:
            # 无变化的保持简洁：只收拢一行，不逐项列。
            ids = ", ".join(e.task_id for e in entries)
            lines.append(f"无变化 {len(entries)} 项：{ids}")
            continue
        if status == STATUS_REGRESSION:
            paint = "red"
        elif status == STATUS_IMPROVEMENT:
            paint = "green"
        elif status == STATUS_CLASS_DRIFT:
            paint = "yellow"
        else:
            paint = ""
        for entry in entries:
            line = (
                f"[{_STATUS_CN[status]}] {entry.task_id}"
                f"（{entry.domain}）：{entry.before_verdict}"
                f"（{entry.before_class}）→ {entry.after_verdict}"
                f"（{entry.after_class}）"
            )
            lines.append(_color(line, paint, color) if paint else line)
            if status in (
                STATUS_REGRESSION,
                STATUS_CLASS_DRIFT,
                STATUS_UNKNOWN,
            ) and entry.notes:
                note = entry.notes.replace("\n", " ")[:120]
                lines.append(f"    说明：{note}")
    return "\n".join(lines)


def to_json(diff: BaselineDiff) -> dict[str, Any]:
    """机器可读的对比结果（供脚本/hook 消费）。"""
    return {
        "schema": "zn-live-model-evidence-diff/v1",
        "before_run_id": diff.before_run_id,
        "after_run_id": diff.after_run_id,
        "summary": diff.summary,
        "has_regression": diff.has_regression,
        "entries": [
            {
                "task_id": e.task_id,
                "status": e.status,
                "status_cn": _STATUS_CN.get(e.status, e.status),
                "domain": e.domain,
                "before": {
                    "verdict": e.before_verdict,
                    "failure_class": e.before_class,
                },
                "after": {
                    "verdict": e.after_verdict,
                    "failure_class": e.after_class,
                },
            }
            for e in diff.entries
        ],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="T5：对比两份 M-11 基线报告，检出 verdict/失败分类漂移"
    )
    parser.add_argument("before", help="对比基准报告 JSON（旧）")
    parser.add_argument("after", help="对比目标报告 JSON（新）")
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出机器可读 JSON 而不是文本",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="禁用颜色（退化不再标红、修复不再标绿）",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        before = load_report(args.before)
        after = load_report(args.after)
    except ValueError as exc:
        print(f"报告加载失败：{exc}", file=sys.stderr)
        return 2

    diff = diff_reports(before, after)
    if args.json:
        print(json.dumps(to_json(diff), ensure_ascii=False, indent=2))
    else:
        print(render_text(diff, color=not args.no_color))

    return 1 if diff.has_regression else 0


if __name__ == "__main__":
    sys.exit(main())
