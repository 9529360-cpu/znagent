"""Tests for the zn CLI terminal formatter contract (T2-1).

The formatter is the presentation layer behind every TTY-only nicety:
semantic colors, symbols, section headers, aligned tables, and the
status-word vocabulary. The hard contract under test:

- NO_COLOR (any value), TERM=dumb, or a non-TTY stream -> plain text that
  is byte-identical to the historic output. Scripts that parse ``zn``
  output must not see any escape codes or glyphs.
- Color mode (real TTY, no NO_COLOR, sane TERM) -> ANSI-wrapped words.
"""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime" / "python"))

from zn_agent.core.cli_format import (
    _detect_stdout_encoding,
    colorize,
    is_tty,
    kv,
    section,
    status_word,
    symbol,
    table,
    use_color,
)
from zn_agent.core.zn_cli import _format_approval_card


class _Tty:
    """Minimal TTY stand-in: isatty() True, otherwise a sink."""

    def __init__(self) -> None:
        self.buf = io.StringIO()

    def isatty(self) -> bool:
        return True

    def write(self, text: str) -> int:
        return self.buf.write(text)


_COLOR_ENV = {"TERM": "xterm-256color"}
_NO_COLOR_ENV = {"TERM": "xterm-256color", "NO_COLOR": "1"}
_DUMB_ENV = {"TERM": "dumb"}


class TtyDetectionTests(unittest.TestCase):
    def test_stringio_is_not_tty(self):
        self.assertFalse(is_tty(io.StringIO()))

    def test_fake_tty_is_tty(self):
        self.assertTrue(is_tty(_Tty()))

    def test_object_without_isatty_is_not_tty(self):
        self.assertFalse(is_tty(object()))

    def test_use_color_needs_tty_clean_env_and_sane_term(self):
        self.assertTrue(use_color(stream=_Tty(), environ=_COLOR_ENV))

    def test_use_color_rejects_non_tty(self):
        self.assertFalse(use_color(stream=io.StringIO(), environ=_COLOR_ENV))

    def test_use_color_no_color_any_value_disables(self):
        for value in ("", "0", "1", "true"):
            with self.subTest(value=value):
                env = dict(_COLOR_ENV)
                env["NO_COLOR"] = value
                self.assertFalse(use_color(stream=_Tty(), environ=env))

    def test_use_color_dumb_terminal_disables(self):
        self.assertFalse(use_color(stream=_Tty(), environ=_DUMB_ENV))

    def test_detect_stdout_encoding_returns_string(self):
        self.assertIsInstance(_detect_stdout_encoding(), str)


class ColorizeTests(unittest.TestCase):
    def test_colorize_wraps_in_color_mode(self):
        self.assertEqual(
            colorize("ok", "ok", stream=_Tty(), environ=_COLOR_ENV),
            "\x1b[32mok\x1b[0m",
        )

    def test_colorize_plain_in_non_color_mode(self):
        for stream, env in (
            (io.StringIO(), _COLOR_ENV),
            (_Tty(), _NO_COLOR_ENV),
            (_Tty(), _DUMB_ENV),
        ):
            with self.subTest(env=env):
                self.assertEqual(
                    colorize("oops", "err", stream=stream, environ=env), "oops"
                )

    def test_colorize_unknown_kind_is_plain(self):
        self.assertEqual(
            colorize("x", "sparkle", stream=_Tty(), environ=_COLOR_ENV), "x"
        )


class SectionTests(unittest.TestCase):
    def test_section_with_count(self):
        self.assertEqual(
            section("pending", 2, stream=io.StringIO(), environ=_COLOR_ENV),
            "--- pending (2) ---",
        )

    def test_section_without_count(self):
        self.assertEqual(
            section("labels", stream=io.StringIO(), environ=_COLOR_ENV),
            "--- labels ---",
        )

    def test_section_is_colored_in_color_mode(self):
        out = section("pending", 1, stream=_Tty(), environ=_COLOR_ENV)
        self.assertEqual(out, "\x1b[2m--- pending (1) ---\x1b[0m")


class KvTests(unittest.TestCase):
    def test_kv_is_plain_key_equals_value(self):
        self.assertEqual(kv("tier", "hot"), "tier=hot")
        self.assertEqual(kv("updated", ""), "updated=")


class TableTests(unittest.TestCase):
    def test_table_aligns_columns(self):
        out = table([["req-1", "pending"], ["req-22", "denied"]])
        self.assertEqual(out, "req-1   pending\nreq-22  denied")

    def test_table_with_headers(self):
        out = table([["a", "b"]], headers=["id", "status"])
        self.assertEqual(out, "id  status\n--  ------\na   b")

    def test_table_empty(self):
        self.assertEqual(table([]), "")


class StatusWordTests(unittest.TestCase):
    def test_booleans_map_to_ok_and_failed(self):
        self.assertEqual(
            status_word(True, stream=io.StringIO(), environ=_COLOR_ENV), "ok"
        )
        self.assertEqual(
            status_word(False, stream=io.StringIO(), environ=_COLOR_ENV), "failed"
        )

    def test_status_enums_map_to_canonical_words(self):
        cases = {
            "pending": "pending",
            "allowed": "allowed",
            "allow_once": "allowed",
            "always_allow": "always allow",
            "denied": "denied",
            "expired": "expired",
            "applied": "applied",
            "active": "active",
            "finalized": "finalized",
        }
        for raw, word in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(
                    status_word(raw, stream=io.StringIO(), environ=_COLOR_ENV),
                    word,
                )

    def test_unknown_values_pass_through_unchanged(self):
        self.assertEqual(
            status_word("weird-state", stream=_Tty(), environ=_COLOR_ENV),
            "weird-state",
        )
        self.assertEqual(
            status_word(None, stream=io.StringIO(), environ=_COLOR_ENV), "None"
        )

    def test_color_mode_wraps_in_ansi(self):
        self.assertEqual(
            status_word("pending", stream=_Tty(), environ=_COLOR_ENV),
            "\x1b[33mpending\x1b[0m",
        )
        self.assertEqual(
            status_word("denied", stream=_Tty(), environ=_COLOR_ENV),
            "\x1b[31mdenied\x1b[0m",
        )


class SymbolTests(unittest.TestCase):
    def test_symbol_in_color_mode(self):
        self.assertEqual(symbol("ok", stream=_Tty(), environ=_COLOR_ENV), "✓")
        self.assertEqual(symbol("fail", stream=_Tty(), environ=_COLOR_ENV), "✗")
        self.assertEqual(symbol("pending", stream=_Tty(), environ=_COLOR_ENV), "…")

    def test_symbol_empty_in_non_color_mode(self):
        for stream, env in (
            (io.StringIO(), _COLOR_ENV),
            (_Tty(), _NO_COLOR_ENV),
        ):
            with self.subTest(env=env):
                self.assertEqual(symbol("ok", stream=stream, environ=env), "")

    def test_symbol_unknown_name_is_empty(self):
        self.assertEqual(symbol("nope", stream=_Tty(), environ=_COLOR_ENV), "")


class ZnCliWiringTests(unittest.TestCase):
    """The two representative rewired commands: byte-stable in non-TTY."""

    def test_approval_card_byte_identical_non_tty(self):
        item = {
            "request_id": "req-pending",
            "status": "pending",
            "action_kind": "send",
            "target": "someone",
            "scope": "chat",
            "expires_at": "2026-10-19T07:00:00Z",
        }
        import contextlib

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            card = _format_approval_card(item)
        self.assertEqual(
            card,
            "req-pending  [pending]  send  target=someone  "
            "scope=chat  expires=2026-10-19T07:00:00Z",
        )

    def test_approval_card_colors_status_in_color_mode(self):
        item = {
            "request_id": "req-1",
            "status": "denied",
            "action_kind": "send",
            "target": "x",
            "scope": "chat",
            "expires_at": "",
        }
        import contextlib
        from unittest import mock

        tty = _Tty()
        with contextlib.redirect_stdout(tty), mock.patch.dict(
            "os.environ", _COLOR_ENV, clear=True
        ):
            card = _format_approval_card(item)
        self.assertIn("\x1b[31mdenied\x1b[0m", card)


if __name__ == "__main__":
    unittest.main()
