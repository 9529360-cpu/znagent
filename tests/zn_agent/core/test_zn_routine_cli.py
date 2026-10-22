"""T9: `zn routine list|get|runs|pause|resume` CLI.

The daemon side is already wired (daemon.py ``_routine_result`` dispatches
``routine_list`` / ``routine_get`` / ``routine_runs`` / ``routine_pause`` /
``routine_resume`` to ``RoutineManager``); this file covers the terminal
face only, against a scripted fake resident socket:

- list: empty / non-empty / --limit passthrough / --json
- get: detail card / --json / unknown id -> human "not found" error
- runs: history rows (succeeded / failed / still running) / empty / --json /
  unknown id -> human "not found" error
- pause / resume: success copy / --reason passthrough / --json / unknown id
- pause while a run is in flight: server rejection surfaces, exit 1
- offline (resident unreachable): every command exits 0 with an honest
  "unreachable" note and the start hint -- pause/resume never print success
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

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime" / "python"))

from zn_agent.core.zn_cli import run

_SECRET = "t9-routine-cli-test-secret-32-chars!"


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


def _run_row(run_id="run-1", status="succeeded", **overrides):
    row = {
        "run_id": run_id,
        "routine_id": "routine-abc123",
        "trigger_kind": "scheduled",
        "scheduled_at": "2026-10-22T06:00:00+00:00",
        "started_at": "2026-10-22T06:00:01+00:00",
        "finished_at": "2026-10-22T06:00:20+00:00",
        "status": status,
        "failure_reason": None,
        "summary": "提醒已发送",
    }
    row.update(overrides)
    return row


def _routine_snapshot(routine_id="routine-abc123", status="active", **overrides):
    snap = {
        "routine_id": routine_id,
        "intention_id": "int-1",
        "title": "每天早上 8 点提醒我看日程",
        "task": "每天早上 8 点提醒我看日程",
        "owner": "user",
        "schedule_kind": "daily",
        "schedule_spec": "08:00",
        "timezone": "Europe/Berlin",
        "input_source": "日历",
        "expected_result": "收到提醒",
        "approval_boundary": "",
        "missing_data_policy": "跳过并告知",
        "auto_pause_after_days": 14,
        "status": status,
        "paused_reason": None,
        "last_confirmed_at": "2026-10-22T10:00:00+00:00",
        "last_run_at": "2026-10-22T06:00:00+00:00",
        "created_at": "2026-10-20T10:00:00+00:00",
        "updated_at": "2026-10-22T10:00:00+00:00",
        "schedule_description": "每天 08:00（Europe/Berlin）",
        "recent_runs": [_run_row()],
    }
    snap.update(overrides)
    return snap


def _rejected(error_text):
    """An RPC ok:false server rejection, as the real daemon would send."""
    return (False, None, error_text)


class _RoutineCliHarness(unittest.TestCase):
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


class RoutineListTests(_RoutineCliHarness):
    def test_list_empty(self):
        code, out, err = self._run(
            ["routine", "list"], self._handler({"routine_list": []})
        )
        self.assertEqual(code, 0)
        self.assertIn("no routines", out)
        self.assertEqual(err, "")

    def test_list_nonempty(self):
        routines = [
            _routine_snapshot(),
            _routine_snapshot(
                "routine-paused1", status="paused", paused_reason="出差一周"
            ),
        ]
        code, out, err = self._run(
            ["routine", "list"], self._handler({"routine_list": routines})
        )
        self.assertEqual(code, 0)
        self.assertIn("--- routines (2) ---", out)
        self.assertIn("routine-abc123", out)
        self.assertIn("[active]", out)
        self.assertIn("每天 08:00", out)
        self.assertIn("routine-paused1", out)
        self.assertIn("[paused]", out)
        self.assertIn("出差一周", out)
        self.assertEqual(err, "")

    def test_list_json(self):
        routines = [_routine_snapshot()]
        code, out, err = self._run(
            ["routine", "list", "--json"], self._handler({"routine_list": routines})
        )
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertEqual(parsed[0]["routine_id"], "routine-abc123")
        self.assertEqual(err, "")

    def test_list_passes_limit(self):
        self._run(
            ["routine", "list", "--limit", "7"],
            self._handler({"routine_list": []}),
        )
        self.assertEqual(
            self.calls, [("routine_list", {"limit": 7})]
        )

    def test_list_unexpected_shape_fails_closed(self):
        code, out, err = self._run(
            ["routine", "list"],
            self._handler({"routine_list": {"not": "a list"}}),
        )
        self.assertEqual(code, 1)
        self.assertIn("无法识别的结果", err)
        self.assertEqual(out, "")


class RoutineGetTests(_RoutineCliHarness):
    def test_get_detail(self):
        code, out, err = self._run(
            ["routine", "get", "routine-abc123"],
            self._handler({"routine_get": _routine_snapshot()}),
        )
        self.assertEqual(code, 0)
        self.assertIn("例行任务 routine-abc123", out)
        self.assertIn("[active]", out)
        self.assertIn("任务：", out)
        self.assertIn("负责人：", out)
        self.assertIn("时区：", out)
        self.assertIn("最近运行", out)
        self.assertIn("run-1", out)
        self.assertEqual(
            self.calls, [("routine_get", {"routine_id": "routine-abc123"})]
        )
        self.assertEqual(err, "")

    def test_get_json(self):
        code, out, err = self._run(
            ["routine", "get", "routine-abc123", "--json"],
            self._handler({"routine_get": _routine_snapshot()}),
        )
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertEqual(parsed["routine_id"], "routine-abc123")
        self.assertEqual(err, "")

    def test_get_unknown_id_is_human_error(self):
        code, out, err = self._run(
            ["routine", "get", "routine-nope"],
            self._handler(
                {"routine_get": _rejected("KeyError: unknown routine: routine-nope")}
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("找不到例行任务 'routine-nope'", err)
        self.assertIn("zn routine list", err)
        self.assertNotIn("已", out)

    def test_get_unexpected_shape_fails_closed(self):
        code, out, err = self._run(
            ["routine", "get", "routine-abc123"],
            self._handler({"routine_get": []}),
        )
        self.assertEqual(code, 1)
        self.assertIn("无法识别的结果", err)


class RoutineRunsTests(_RoutineCliHarness):
    def test_runs_history(self):
        runs = [
            _run_row("run-3", "succeeded"),
            _run_row(
                "run-2",
                "failed",
                failure_reason="日历接口超时",
                summary=None,
                finished_at="2026-10-21T06:00:30+00:00",
            ),
            _run_row("run-1", "running", finished_at=None, summary=None),
        ]
        code, out, err = self._run(
            ["routine", "runs", "routine-abc123"],
            self._handler({"routine_runs": runs}),
        )
        self.assertEqual(code, 0)
        self.assertIn("--- routine runs (3) ---", out)
        self.assertIn("run-3", out)
        self.assertIn("[succeeded]", out)
        self.assertIn("[failed]", out)
        self.assertIn("日历接口超时", out)
        self.assertIn("进行中", out)
        self.assertEqual(err, "")

    def test_runs_empty(self):
        code, out, err = self._run(
            ["routine", "runs", "routine-abc123"],
            self._handler({"routine_runs": []}),
        )
        self.assertEqual(code, 0)
        self.assertIn("(none)", out)
        self.assertEqual(err, "")

    def test_runs_json(self):
        runs = [_run_row()]
        code, out, err = self._run(
            ["routine", "runs", "routine-abc123", "--json"],
            self._handler({"routine_runs": runs}),
        )
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertEqual(parsed[0]["run_id"], "run-1")
        self.assertEqual(err, "")

    def test_runs_unknown_id_is_human_error(self):
        code, out, err = self._run(
            ["routine", "runs", "routine-nope"],
            self._handler(
                {"routine_runs": _rejected("KeyError: unknown routine: routine-nope")}
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("找不到例行任务 'routine-nope'", err)


class RoutinePauseTests(_RoutineCliHarness):
    def test_pause(self):
        paused = _routine_snapshot(status="paused", paused_reason="paused by user")
        code, out, err = self._run(
            ["routine", "pause", "routine-abc123"],
            self._handler({"routine_pause": paused}),
        )
        self.assertEqual(code, 0)
        self.assertIn("已暂停", out)
        self.assertIn("[paused]", out)
        self.assertIn("paused by user", out)
        # no --reason given -> params carry no reason key
        self.assertEqual(self.calls, [("routine_pause", {"routine_id": "routine-abc123"})])
        self.assertEqual(err, "")

    def test_pause_with_reason(self):
        paused = _routine_snapshot(status="paused", paused_reason="出差一周")
        code, out, err = self._run(
            ["routine", "pause", "routine-abc123", "--reason", "出差一周"],
            self._handler({"routine_pause": paused}),
        )
        self.assertEqual(code, 0)
        self.assertIn("出差一周", out)
        self.assertEqual(
            self.calls,
            [("routine_pause", {"routine_id": "routine-abc123", "reason": "出差一周"})],
        )
        self.assertEqual(err, "")

    def test_pause_json(self):
        paused = _routine_snapshot(status="paused", paused_reason="paused by user")
        code, out, err = self._run(
            ["routine", "pause", "routine-abc123", "--json"],
            self._handler({"routine_pause": paused}),
        )
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertEqual(parsed["status"], "paused")
        self.assertEqual(err, "")

    def test_pause_unknown_id_is_human_error(self):
        code, out, err = self._run(
            ["routine", "pause", "routine-nope"],
            self._handler(
                {"routine_pause": _rejected("KeyError: unknown routine: routine-nope")}
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("找不到例行任务 'routine-nope'", err)
        self.assertNotIn("已暂停", out)

    def test_pause_run_in_flight_surfaces_server_rejection(self):
        code, out, err = self._run(
            ["routine", "pause", "routine-abc123"],
            self._handler(
                {
                    "routine_pause": _rejected(
                        "ValueError: routine has a run in flight; "
                        "wait for it to finish before pause"
                    )
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("服务端返回错误（routine_pause）", err)
        self.assertIn("run in flight", err)
        self.assertNotIn("已暂停", out)


class RoutineResumeTests(_RoutineCliHarness):
    def test_resume(self):
        active = _routine_snapshot(status="active", paused_reason=None)
        code, out, err = self._run(
            ["routine", "resume", "routine-abc123"],
            self._handler({"routine_resume": active}),
        )
        self.assertEqual(code, 0)
        self.assertIn("已恢复", out)
        self.assertIn("[active]", out)
        self.assertEqual(
            self.calls, [("routine_resume", {"routine_id": "routine-abc123"})]
        )
        self.assertEqual(err, "")

    def test_resume_json(self):
        active = _routine_snapshot(status="active", paused_reason=None)
        code, out, err = self._run(
            ["routine", "resume", "routine-abc123", "--json"],
            self._handler({"routine_resume": active}),
        )
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertEqual(parsed["status"], "active")
        self.assertEqual(err, "")

    def test_resume_unknown_id_is_human_error(self):
        code, out, err = self._run(
            ["routine", "resume", "routine-nope"],
            self._handler(
                {"routine_resume": _rejected("KeyError: unknown routine: routine-nope")}
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("找不到例行任务 'routine-nope'", err)
        self.assertNotIn("已恢复", out)


class RoutineOfflineTests(_RoutineCliHarness):
    """Resident unreachable: exit 0 with an honest note; no false success."""

    def test_list_offline(self):
        code, out, err = self._run_offline(["routine", "list"])
        self.assertEqual(code, 0)
        self.assertIn("unreachable", out)
        self.assertIn("zn-resident", out)
        self.assertEqual(err, "")

    def test_list_offline_json(self):
        code, out, err = self._run_offline(["routine", "list", "--json"])
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertFalse(parsed["daemon_reachable"])
        self.assertEqual(parsed["routines"], [])
        self.assertEqual(err, "")

    def test_get_offline(self):
        code, out, err = self._run_offline(["routine", "get", "routine-abc123"])
        self.assertEqual(code, 0)
        self.assertIn("unreachable", out)
        self.assertIn("zn-resident", out)

    def test_runs_offline(self):
        code, out, err = self._run_offline(["routine", "runs", "routine-abc123"])
        self.assertEqual(code, 0)
        self.assertIn("unreachable", out)

    def test_pause_offline_reports_no_change(self):
        code, out, err = self._run_offline(["routine", "pause", "routine-abc123"])
        self.assertEqual(code, 0)
        self.assertIn("unreachable", out)
        self.assertIn("没有暂停任何例行任务", out)
        self.assertNotIn("已暂停", out)
        self.assertEqual(err, "")

    def test_resume_offline_reports_no_change(self):
        code, out, err = self._run_offline(["routine", "resume", "routine-abc123"])
        self.assertEqual(code, 0)
        self.assertIn("unreachable", out)
        self.assertIn("没有恢复任何例行任务", out)
        self.assertNotIn("已恢复", out)
        self.assertEqual(err, "")

    def test_pause_offline_json(self):
        code, out, err = self._run_offline(
            ["routine", "pause", "routine-abc123", "--json"]
        )
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertFalse(parsed["daemon_reachable"])
        self.assertFalse(parsed["changed"])
        self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()
