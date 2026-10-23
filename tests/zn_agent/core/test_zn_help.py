"""Tests for the T3-1 scenario-organized `zn help` overview.

Two layers:

1. Snapshot: ``render_help_text()`` must equal an explicit expected string,
   locking the five-section structure. New commands/sections require a
   conscious snapshot update here, never a silent pass.
2. Drift guard: every command path mentioned in ``_HELP_SECTIONS`` must be a
   real registered name in ``build_parser()`` (walked recursively), so the
   copy can never name a command that does not exist.
"""
from __future__ import annotations

import argparse
import contextlib
import io
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime" / "python"))

from zn_agent.core.zn_cli import (
    _HELP_SECTIONS,
    _cmd_help,
    build_parser,
    render_help_text,
    run,
)


def _registered_command_paths(parser: argparse.ArgumentParser) -> set[str]:
    """Collect every leaf command path, e.g. ``"work submit"``."""
    paths: set[str] = set()

    def visit(node: argparse.ArgumentParser, prefix: str) -> None:
        for action in node._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, sub in action.choices.items():
                    path = f"{prefix} {name}".strip()
                    before = len(paths)
                    visit(sub, path)
                    if len(paths) == before:
                        paths.add(path)

    visit(parser, "")
    return paths


def _row_commands() -> list[str]:
    return [command for _, rows in _HELP_SECTIONS for command, _, _ in rows]


# Snapshot: non-TTY stream so output is plain and deterministic (no color,
# no glyphs); any copy edit must update this string deliberately.
_EXPECTED_SNAPSHOT = """ZN 能帮你干的事（按场景）

--- 交办 (5) ---
  work submit
    交办一件事给 ZN，常驻服务去执行
    例：zn work submit --task "把 downloads 里昨天的发票整理成一张表"
  work list
    看看 ZN 手上正在干的活
    例：zn work list
  work get
    看某件事的进展和结果
    例：zn work get --thread-id <id>
  work cancel
    停掉一件正在干的活
    例：zn work cancel --thread-id <id> --event-id <id>
  chat
    直接跟 ZN 对话交办（交互模式）
    例：zn chat

--- 审批 (3) ---
  approval list
    看等你拍板的申请卡
    例：zn approval list
  approval show
    先看清一张卡的内容再拍板
    例：zn approval show <id>
  approval decide
    批准或拒绝一张卡
    例：zn approval decide --request-id <id> --allow

--- 审批规则与撤销 (3) ---
  approval rules list
    看有哪些自动放行规则
    例：zn approval rules list
  approval rules delete
    收回一条自动放行规则
    例：zn approval rules delete <rule-id>
  approval undo
    撤销一次已执行的批准变更（文件回滚）
    例：zn approval undo <request-id>

--- 记忆 (5) ---
  memory list
    看看 ZN 都记着哪些事
    例：zn memory list
  memory remember
    让 ZN 记住一件事
    例：zn memory remember --key "公司 wifi 密码" --value "xxxx"
  memory forget
    让 ZN 忘掉一件事（默认要手动确认）
    例：zn memory forget --key "公司 wifi 密码" --yes
  memory export
    把记忆备份成文件
    例：zn memory export --out ~/memory-backup.json
  memory import
    从备份文件恢复记忆
    例：zn memory import --in ~/memory-backup.json

--- 团队与自驱 (4) ---
  team list
    看有哪些项目团队在干活
    例：zn team list
  team timeline
    看某件事的团队进展时间线
    例：zn team timeline --thread-id <id>
  goal list
    看 ZN 的自驱目标清单
    例：zn goal list
  goal status
    看 ZN 自驱的当前状态
    例：zn goal status

--- 例行任务 (5) ---
  routine list
    看有哪些例行任务在跑
    例：zn routine list
  routine get
    看某条例行任务的详情
    例：zn routine get <id>
  routine runs
    看某条例行任务的运行历史
    例：zn routine runs <id>
  routine pause
    暂停一条例行任务
    例：zn routine pause <id>
  routine resume
    恢复一条被暂停的例行任务
    例：zn routine resume <id>

--- 日记 (3) ---
  diary list
    看 ZN 写过哪些日记（最新在前）
    例：zn diary list
  diary get
    看今天的日记（默认今天）
    例：zn diary get
  diary get
    看某天的日记
    例：zn diary get --date 2026-10-22

--- 日常 (5) ---
  suggestions list
    看 ZN 给你的建议
    例：zn suggestions list
  autonomy list
    看 ZN 在各领域的自主权设置
    例：zn autonomy list
  connector status
    看连接器挂载得正不正常
    例：zn connector status
  model check
    检查模型通道通不通
    例：zn model check
  status
    一屏看 ZN 的整体状态（服务/模型/审批/连接器）
    例：zn status

细看某条命令：zn <命令> --help，例如 zn work submit --help"""


class TestHelpSnapshot(unittest.TestCase):
    def test_snapshot_matches_expected(self):
        self.assertEqual(
            render_help_text(stream=io.StringIO()),
            _EXPECTED_SNAPSHOT,
        )

    def test_snapshot_has_exactly_eight_sections(self):
        titles = [title for title, _ in _HELP_SECTIONS]
        self.assertEqual(titles, ["交办", "审批", "审批规则与撤销", "记忆", "团队与自驱", "例行任务", "日记", "日常"])

    def test_each_section_has_three_to_five_rows(self):
        for title, rows in _HELP_SECTIONS:
            self.assertGreaterEqual(
                len(rows), 3, f"section {title!r} has fewer than 3 rows"
            )
            self.assertLessEqual(
                len(rows), 5, f"section {title!r} has more than 5 rows"
            )

    def test_every_example_is_copy_pasteable(self):
        for command, _, example in (
            (command, blurb, example)
            for _, rows in _HELP_SECTIONS
            for command, blurb, example in rows
        ):
            self.assertTrue(
                example.startswith(f"zn {command}"),
                f"example {example!r} does not start with the command itself",
            )


class TestHelpDrift(unittest.TestCase):
    def test_every_copy_command_is_registered_in_parser(self):
        registered = _registered_command_paths(build_parser())
        for command in _row_commands():
            self.assertIn(
                command,
                registered,
                f"help copy names command {command!r} "
                "but build_parser() does not register it",
            )

    def test_help_subcommand_is_wired_to_cmd_help(self):
        args = build_parser().parse_args(["help"])
        self.assertEqual(args.func, _cmd_help)

    def test_zn_help_runs_offline(self):
        # No resident, no endpoint, no network: `zn help` must still print
        # the overview and exit 0.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = run(["help"])
        self.assertEqual(code, 0)
        output = buf.getvalue()
        for title in ["交办", "审批", "记忆", "团队与自驱", "日常"]:
            self.assertIn(title, output)


if __name__ == "__main__":
    unittest.main()
