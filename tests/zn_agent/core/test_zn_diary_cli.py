"""T10: `zn diary list` / `zn diary get [--date YYYY-MM-DD]` CLI.

The daemon side is already wired (daemon.py dispatches ``diary_list`` /
``diary_get`` to ``DiaryEngine``); this file covers the terminal face only,
against a scripted fake resident socket:

- list: empty / non-empty / --limit passthrough / --json
- get: detail card / --json / missing date (daemon answers null) -> human
  "not found" error / server rejection surfaces, exit 1
- DIARY-TODAY: omitting --date defaults to today -- the RPC goes out with
  today's date, the TTY headline carries the "（默认今天）" hint, --json
  is unchanged passthrough; explicit --date behavior is unchanged
- --date validation: strict YYYY-MM-DD, usage error (exit 2) otherwise
- offline (resident unreachable): both commands exit 0 with an honest
  "unreachable" note and the start hint
- malformed server payloads fail closed (exit 1, humanized error)
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime" / "python"))

from zn_agent.core.zn_cli import build_parser, run

_SECRET="t10-diary-cli-test-secret-32-chars!"


def _endpoint_payload(**overrides):
    payload = {
        "version": 2,
        "transport": "tcp",
        "host": "127.0.0.1",
        "port": 59999,
        "authentication": {"scheme": "session-secret-v1", "secret": _SECRET},
    }
    payload.update(overrides)
    return payload


class _FakeStream:
    def __init__(self) -> None:
        self.lines: list[bytes] = []

    def readline(self) -> bytes:
        if not self.lines:
            return b""
        return self.lines.pop(0)


class _FakeSocket:
    """Speaks the resident newline-JSON protocol against a scripted handler."""

    def __init__(self, handler) -> None:
        self.handler = handler
        self.stream = _FakeStream()
        self.closed = False

    def settimeout(self, _timeout) -> None:
        pass

    def makefile(self, _mode):
        return self.stream

    def sendall(self, data: bytes) -> None:
        for line in data.decode("utf-8").splitlines():
            if not line.strip():
                continue
            request = json.loads(line)
            if request.get("method") == "authenticate":
                ok = request.get("params", {}).get("secret") == _SECRET
                self.stream.lines.append(
                    json.dumps(
                        {
                            "id": request.get("id"),
                            "ok": ok,
                            "error": None if ok else "authentication failed",
                            "result": {"authenticated": ok},
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                continue
            outcome = self.handler(request.get("method"), request.get("params") or {})
            if isinstance(outcome, Exception):
                raise outcome
            if isinstance(outcome, tuple):
                ok, result, error = outcome
            else:
                ok, result, error = True, outcome, None
            self.stream.lines.append(
                json.dumps(
                    {"id": request.get("id"), "ok": ok, "result": result, "error": error}
                ).encode("utf-8")
                + b"\n"
            )

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False


def _diary_entry(entry_date="2026-10-22", **overrides):
    entry = {
        "date": entry_date,
        "key": entry_date,
        "text": "今日事项：\n- 交办了两件事\n- 记了一条长期记忆",
        "item_count": 5,
        "persona_fingerprint": "fp-1",
        "created_at": "2026-10-22T23:00:00+02:00",
    }
    entry.update(overrides)
    return entry


def _rejected(error_text):
    """An RPC ok:false server rejection, as the real daemon would send."""
    return (False, None, error_text)


class _DiaryCliHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.endpoint_path = Path(self.tmp.name) / "resident-endpoint.json"
        self.endpoint_path.write_text(
            json.dumps(_endpoint_payload()), encoding="utf-8"
        )
        self.calls: list[tuple] = []

    def _handler(self, mapping):
        def handle(method, params):
            self.calls.append((method, params))
            if method not in mapping:
                raise AssertionError(f"unexpected RPC method {method!r}")
            return mapping[method]

        return handle

    def _run_with_connect(self, argv, connect_fn):
        with (
            mock.patch("socket.create_connection", side_effect=connect_fn),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            code = run(["--endpoint", str(self.endpoint_path), *argv])
        return code, stdout.getvalue(), stderr.getvalue()

    def _run(self, argv, handler):
        def connect(address, timeout=None):
            return _FakeSocket(handler)

        return self._run_with_connect(argv, connect)

    def _run_offline(self, argv):
        def connect(address, timeout=None):
            raise ConnectionRefusedError("connection refused")

        return self._run_with_connect(argv, connect)


class DiaryListTests(_DiaryCliHarness):
    def test_list_empty(self):
        code, out, err = self._run(
            ["diary", "list"], self._handler({"diary_list": []})
        )
        self.assertEqual(code, 0)
        self.assertIn("no diary entries", out)
        self.assertEqual(err, "")

    def test_list_nonempty(self):
        entries = [_diary_entry("2026-10-22"), _diary_entry("2026-10-21")]
        code, out, err = self._run(
            ["diary", "list"], self._handler({"diary_list": entries})
        )
        self.assertEqual(code, 0)
        self.assertIn("--- diary entries (2) ---", out)
        self.assertIn("2026-10-22", out)
        self.assertIn("2026-10-21", out)
        self.assertIn("5 条素材", out)
        self.assertIn("今日事项", out)
        self.assertEqual(err, "")

    def test_list_json(self):
        entries = [_diary_entry("2026-10-22")]
        code, out, err = self._run(
            ["diary", "list", "--json"], self._handler({"diary_list": entries})
        )
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertEqual(parsed[0]["date"], "2026-10-22")
        self.assertEqual(parsed[0]["item_count"], 5)
        self.assertEqual(err, "")

    def test_list_passes_limit(self):
        self._run(
            ["diary", "list", "--limit", "7"],
            self._handler({"diary_list": []}),
        )
        self.assertEqual(self.calls, [("diary_list", {"limit": 7})])

    def test_list_unexpected_shape_fails_closed(self):
        code, out, err = self._run(
            ["diary", "list"],
            self._handler({"diary_list": {"not": "a list"}}),
        )
        self.assertEqual(code, 1)
        self.assertIn("无法识别的结果", err)
        self.assertEqual(out, "")


class DiaryGetTests(_DiaryCliHarness):
    def test_get_detail(self):
        code, out, err = self._run(
            ["diary", "get", "--date", "2026-10-22"],
            self._handler({"diary_get": _diary_entry()}),
        )
        self.assertEqual(code, 0)
        self.assertIn("日记 2026-10-22", out)
        self.assertIn("素材数：5", out)
        self.assertIn("写于：", out)
        self.assertIn("正文：", out)
        # T2-4: the body keeps its line structure, not pressed to one line.
        self.assertIn("- 交办了两件事", out)
        self.assertEqual(
            self.calls, [("diary_get", {"date": "2026-10-22"})]
        )
        self.assertEqual(err, "")

    def test_get_json(self):
        code, out, err = self._run(
            ["diary", "get", "--date", "2026-10-22", "--json"],
            self._handler({"diary_get": _diary_entry()}),
        )
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertEqual(parsed["date"], "2026-10-22")
        self.assertIn("交办了两件事", parsed["text"])
        self.assertEqual(err, "")

    def test_get_missing_date_is_human_error(self):
        # The daemon answers null (not a rejection) for a date with no
        # entry: the CLI must say so in plain words, exit 1, and keep the
        # server contract greppable via the English fragment.
        code, out, err = self._run(
            ["diary", "get", "--date", "2026-10-20"],
            self._handler({"diary_get": None}),
        )
        self.assertEqual(code, 1)
        self.assertIn("找不到 2026-10-20 的日记", err)
        self.assertIn("no diary entry for that date", err)
        self.assertIn("zn diary list", err)
        self.assertEqual(out, "")

    def test_get_server_rejection_surfaces(self):
        code, out, err = self._run(
            ["diary", "get", "--date", "2026-10-22"],
            self._handler(
                {"diary_get": _rejected("ValueError: diary_get requires date")}
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("服务端返回错误（diary_get）", err)
        self.assertEqual(out, "")

    def test_get_unexpected_shape_fails_closed(self):
        code, out, err = self._run(
            ["diary", "get", "--date", "2026-10-22"],
            self._handler({"diary_get": ["not", "a", "dict"]}),
        )
        self.assertEqual(code, 1)
        self.assertIn("无法识别的结果", err)
        self.assertEqual(out, "")


class DiaryGetDefaultDateTests(_DiaryCliHarness):
    """DIARY-TODAY: ``zn diary get`` with no --date resolves to today."""

    def test_get_defaults_to_today_with_hint(self):
        today = date.today().isoformat()
        code, out, err = self._run(
            ["diary", "get"],
            self._handler({"diary_get": _diary_entry(today)}),
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, [("diary_get", {"date": today})])
        # The TTY headline names the resolved date and says it defaulted.
        first_line = out.splitlines()[0]
        self.assertIn(today, first_line)
        self.assertIn("（默认今天）", first_line)
        self.assertIn("素材数：5", out)
        self.assertEqual(err, "")

    def test_get_explicit_date_carries_no_hint(self):
        code, out, err = self._run(
            ["diary", "get", "--date", "2026-10-22"],
            self._handler({"diary_get": _diary_entry("2026-10-22")}),
        )
        self.assertEqual(code, 0)
        self.assertNotIn("（默认今天）", out)
        self.assertEqual(err, "")

    def test_get_default_json_passthrough(self):
        # --json output is raw: the date field is the resolved today, and
        # no hint text leaks into the JSON.
        today = date.today().isoformat()
        code, out, err = self._run(
            ["diary", "get", "--json"],
            self._handler({"diary_get": _diary_entry(today)}),
        )
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertEqual(parsed["date"], today)
        self.assertNotIn("默认今天", out)
        self.assertEqual(err, "")

    def test_get_default_missing_entry_is_human_error(self):
        # No entry for today: same humanized "not found" error, naming
        # today's date, exit 1.
        today = date.today().isoformat()
        code, out, err = self._run(
            ["diary", "get"], self._handler({"diary_get": None})
        )
        self.assertEqual(code, 1)
        self.assertIn(f"找不到 {today} 的日记", err)
        self.assertIn("no diary entry for that date", err)
        self.assertEqual(out, "")

    def test_get_default_offline(self):
        today = date.today().isoformat()
        code, out, err = self._run_offline(["diary", "get"])
        self.assertEqual(code, 0)
        self.assertIn("unreachable", out)
        self.assertIn(f"看不到 {today} 的日记", out)
        self.assertEqual(err, "")

    def test_get_default_offline_json(self):
        today = date.today().isoformat()
        code, out, err = self._run_offline(["diary", "get", "--json"])
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertFalse(parsed["daemon_reachable"])
        self.assertEqual(parsed["date"], today)
        self.assertIsNone(parsed["entry"])
        self.assertEqual(err, "")


class DiaryOfflineTests(_DiaryCliHarness):
    """Resident unreachable: exit 0 with an honest note; no false success."""

    def test_list_offline(self):
        code, out, err = self._run_offline(["diary", "list"])
        self.assertEqual(code, 0)
        self.assertIn("unreachable", out)
        self.assertIn("看不到日记列表", out)
        self.assertIn("zn-resident", out)
        self.assertEqual(err, "")

    def test_list_offline_json(self):
        code, out, err = self._run_offline(["diary", "list", "--json"])
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertFalse(parsed["daemon_reachable"])
        self.assertEqual(parsed["entries"], [])
        self.assertEqual(err, "")

    def test_get_offline(self):
        code, out, err = self._run_offline(
            ["diary", "get", "--date", "2026-10-22"]
        )
        self.assertEqual(code, 0)
        self.assertIn("unreachable", out)
        self.assertIn("看不到 2026-10-22 的日记", out)
        self.assertIn("zn-resident", out)
        self.assertEqual(err, "")

    def test_get_offline_json(self):
        code, out, err = self._run_offline(
            ["diary", "get", "--date", "2026-10-22", "--json"]
        )
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertFalse(parsed["daemon_reachable"])
        self.assertEqual(parsed["date"], "2026-10-22")
        self.assertIsNone(parsed["entry"])
        self.assertEqual(err, "")


class DiaryDateArgTests(unittest.TestCase):
    """--date must be strict YYYY-MM-DD; argparse usage error (exit 2)."""

    def test_valid_date_accepted(self):
        namespace = build_parser().parse_args(
            ["diary", "get", "--date", "2026-10-22"]
        )
        self.assertEqual(namespace.date, "2026-10-22")

    def test_date_arg_is_optional_and_defaults_none(self):
        # DIARY-TODAY: --date is no longer required; the CLI resolves
        # today at command time, so argparse must leave it unset.
        namespace = build_parser().parse_args(["diary", "get"])
        self.assertIsNone(namespace.date)

    def test_invalid_dates_rejected_with_usage_error(self):
        for bad in (
            "20261022",
            "2026-1-1",
            "2026/10/22",
            "2026-13-01",
            "2026-02-30",
            "not-a-date",
            "",
        ):
            with (
                self.subTest(bad=bad),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as ctx,
            ):
                build_parser().parse_args(["diary", "get", "--date", bad])
            self.assertEqual(
                ctx.exception.code, 2, f"date {bad!r} should be a usage error"
            )


if __name__ == "__main__":
    unittest.main()
