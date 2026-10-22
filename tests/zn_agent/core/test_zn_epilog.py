"""Tests for T3-2: every leaf subcommand of `zn` carries runnable examples.

The ``build_parser()`` tree is walked recursively. For every leaf subcommand
the test asserts:

1. ``epilog`` is non-empty.
2. ``epilog`` contains at least one example line (a line starting with
   ``zn ``); every non-empty, non-header line of the epilog must be such an
   example line, so copy text stays copy-pasteable.
3. Every example line is genuinely runnable: it must parse against a fresh
   ``build_parser()`` and resolve back to the very leaf subcommand that
   carries it. Angle-bracket placeholders (``<thread-id>`` etc.) are allowed
   as ordinary argument values; command names and flags are not guessed.

Adding a new leaf subcommand without an epilog fails test 1 automatically,
which is the drift guard for this task.
"""
from __future__ import annotations

import argparse
import shlex
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime" / "python"))

from zn_agent.core.zn_cli import build_parser


def _leaf_parsers(
    parser: argparse.ArgumentParser,
) -> list[tuple[str, argparse.ArgumentParser]]:
    """Collect ``(command path, parser)`` for every leaf subcommand."""
    leaves: list[tuple[str, argparse.ArgumentParser]] = []

    def visit(node: argparse.ArgumentParser, prefix: str) -> None:
        for action in node._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, sub in action.choices.items():
                    path = f"{prefix} {name}".strip()
                    before = len(leaves)
                    visit(sub, path)
                    if len(leaves) == before:
                        leaves.append((path, sub))

    visit(parser, "")
    return leaves


def _resolve_leaf_path(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> str:
    """Walk a parsed namespace back to its leaf command path."""
    node = parser
    parts: list[str] = []
    while True:
        for action in node._actions:
            if isinstance(action, argparse._SubParsersAction):
                chosen = getattr(args, action.dest, None)
                if chosen is None:
                    raise AssertionError(
                        f"parsed args have no selection for subparser "
                        f"{action.dest!r}"
                    )
                parts.append(chosen)
                node = action.choices[chosen]
                break
        else:
            return " ".join(parts)


def _example_lines(epilog: str) -> list[str]:
    """Example lines: stripped lines that start with ``zn ``."""
    return [
        line.strip()
        for line in epilog.splitlines()
        if line.strip().startswith("zn ")
    ]


class TestEpilogCoverage(unittest.TestCase):
    def test_every_leaf_subcommand_has_non_empty_epilog(self):
        missing = [
            path
            for path, leaf in _leaf_parsers(build_parser())
            if not (leaf.epilog or "").strip()
        ]
        self.assertEqual(
            missing,
            [],
            f"leaf subcommands without epilog: {missing}",
        )

    def test_every_epilog_has_at_least_one_example_line(self):
        for path, leaf in _leaf_parsers(build_parser()):
            self.assertGreaterEqual(
                len(_example_lines(leaf.epilog or "")),
                1,
                f"epilog of {path!r} has no 'zn ...' example line",
            )

    def test_epilog_contains_only_example_lines(self):
        # Any non-empty, non-example line would be prose that breaks the
        # copy-paste contract; keep the epilog a header plus example lines.
        for path, leaf in _leaf_parsers(build_parser()):
            for line in (leaf.epilog or "").splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                self.assertTrue(
                    stripped.startswith("zn ") or stripped == "示例：",
                    f"epilog of {path!r} has a non-example line: {line!r}",
                )

    def test_every_example_is_runnable_and_targets_its_own_command(self):
        for path, leaf in _leaf_parsers(build_parser()):
            for example in _example_lines(leaf.epilog or ""):
                tokens = shlex.split(example)
                self.assertEqual(
                    tokens[0],
                    "zn",
                    f"example of {path!r} does not start with 'zn': {example!r}",
                )
                parsed = build_parser().parse_args(tokens[1:])
                resolved = _resolve_leaf_path(build_parser(), parsed)
                self.assertEqual(
                    resolved,
                    path,
                    f"example {example!r} parses to {resolved!r}, "
                    f"not the leaf that carries it ({path!r})",
                )


if __name__ == "__main__":
    unittest.main()
