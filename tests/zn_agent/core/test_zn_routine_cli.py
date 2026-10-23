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
- edit: --time / --content / both / --json passthrough / unknown id /
  unparseable --time / neither flag / server rejection / engaged -> exit 1
  with zero mutation RPCs / missing --routine-id -> exit 2
- delete: success / --json passthrough / unknown id / server rejection /
  engaged -> exit 1 with zero mutation RPCs / missing --routine-id -> exit 2
- test-run: real execution (status running) / awaiting_approval held run /
  denied boundary -> human error / engaged -> exit 1 with zero mutation RPCs /
  --json passthrough / unknown id / server rejection / missing --routine-id
  -> exit 2
- acknowledge: success resets auto-pause clock / --json passthrough /
  unknown id / missing --routine-id -> exit 2
- offline (resident unreachable): every command exits 0 with an honest
  "unreachable" note and the start hint -- pause/resume/edit/delete never
  print success
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


class RoutineEditTests(_RoutineCliHarness):
    """T18: ``zn routine edit`` -- change a routine's time and/or content.

    ``--time`` reuses the propose schedule parser; ``--content`` maps to the
    ``task`` field. Every test asserts the exact RPC methods/params: the
    read-only ``routine_get`` pre-flight first, then exactly one
    ``routine_edit`` -- and zero mutation RPCs when the routine is engaged.
    """

    def test_edit_time(self):
        snapshot = _routine_snapshot()
        edited = _routine_snapshot(
            schedule_description="每天 09:00（Europe/Berlin）",
        )
        code, out, err = self._run(
            [
                "routine",
                "edit",
                "--routine-id",
                "routine-abc123",
                "--time",
                "每天早上9点",
            ],
            self._handler({"routine_get": snapshot, "routine_edit": edited}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("已更新", out)
        self.assertIn("[active]", out)
        self.assertIn("时间：每天 09:00", out)
        self.assertEqual(
            self.calls,
            [
                ("routine_get", {"routine_id": "routine-abc123"}),
                (
                    "routine_edit",
                    {
                        "routine_id": "routine-abc123",
                        "fields": {
                            "schedule_kind": "cron",
                            "cron_expression": "0 9 * * *",
                        },
                    },
                ),
            ],
        )
        self.assertEqual(err, "")

    def test_edit_content(self):
        snapshot = _routine_snapshot()
        edited = _routine_snapshot(task="提醒我看今天的日程")
        code, out, err = self._run(
            [
                "routine",
                "edit",
                "--routine-id",
                "routine-abc123",
                "--content",
                "提醒我看今天的日程",
            ],
            self._handler({"routine_get": snapshot, "routine_edit": edited}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("已更新", out)
        self.assertIn("内容：提醒我看今天的日程", out)
        self.assertEqual(
            self.calls[1],
            (
                "routine_edit",
                {
                    "routine_id": "routine-abc123",
                    "fields": {"task": "提醒我看今天的日程"},
                },
            ),
        )
        self.assertEqual(err, "")

    def test_edit_time_and_content(self):
        snapshot = _routine_snapshot()
        edited = _routine_snapshot(
            task="看一次日历",
            schedule_description="每 30 分钟",
        )
        code, out, err = self._run(
            [
                "routine",
                "edit",
                "--routine-id",
                "routine-abc123",
                "--time",
                "每30分钟",
                "--content",
                "看一次日历",
            ],
            self._handler({"routine_get": snapshot, "routine_edit": edited}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("已更新", out)
        self.assertIn("时间：每 30 分钟", out)
        self.assertIn("内容：看一次日历", out)
        self.assertEqual(
            self.calls[1][1]["fields"],
            {
                "schedule_kind": "interval",
                "interval_seconds": 1800,
                "task": "看一次日历",
            },
        )

    def test_edit_json_passthrough(self):
        edited = _routine_snapshot(
            schedule_description="每天 09:00（Europe/Berlin）",
        )
        code, out, err = self._run(
            [
                "routine",
                "edit",
                "--routine-id",
                "routine-abc123",
                "--time",
                "每天早上9点",
                "--json",
            ],
            self._handler(
                {"routine_get": _routine_snapshot(), "routine_edit": edited}
            ),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), edited)
        self.assertEqual(err, "")

    def test_edit_engaged_refuses_without_mutation_rpc(self):
        engaged = _routine_snapshot(
            recent_runs=[_run_row(status="running", finished_at=None)]
        )
        code, out, err = self._run(
            [
                "routine",
                "edit",
                "--routine-id",
                "routine-abc123",
                "--time",
                "每天早上9点",
            ],
            self._handler({"routine_get": engaged}),
        )
        self.assertEqual(code, 1)
        self.assertIn("正在执行中", err)
        self.assertIn("run in flight", err)
        self.assertIn("不能修改", err)
        self.assertIn("zn routine runs routine-abc123", err)
        self.assertNotIn("已更新", out)
        # Only the read-only pre-flight went out; no routine_edit was sent.
        self.assertEqual(
            self.calls, [("routine_get", {"routine_id": "routine-abc123"})]
        )

    def test_edit_unknown_id_is_human_error(self):
        code, out, err = self._run(
            [
                "routine",
                "edit",
                "--routine-id",
                "routine-nope",
                "--content",
                "提醒我看日程",
            ],
            self._handler(
                {
                    "routine_get": _rejected(
                        "KeyError: unknown routine: routine-nope"
                    )
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("找不到例行任务 'routine-nope'", err)
        self.assertNotIn("已更新", out)
        self.assertEqual(
            self.calls, [("routine_get", {"routine_id": "routine-nope"})]
        )

    def test_edit_unparseable_time_is_human_error(self):
        code, out, err = self._run(
            [
                "routine",
                "edit",
                "--routine-id",
                "routine-abc123",
                "--time",
                "下辈子",
            ],
            self._handler({"routine_get": _routine_snapshot()}),
        )
        self.assertEqual(code, 1)
        self.assertIn("没听懂这个时间", err)
        self.assertIn("could not parse schedule", err)
        self.assertNotIn("已更新", out)
        self.assertEqual(self.calls, [])

    def test_edit_without_time_or_content_is_human_error(self):
        code, out, err = self._run(
            ["routine", "edit", "--routine-id", "routine-abc123"],
            self._handler({"routine_get": _routine_snapshot()}),
        )
        self.assertEqual(code, 1)
        self.assertIn("至少改一项", err)
        self.assertIn("nothing to change", err)
        self.assertNotIn("已更新", out)
        self.assertEqual(self.calls, [])

    def test_edit_server_rejection_surfaces(self):
        code, out, err = self._run(
            [
                "routine",
                "edit",
                "--routine-id",
                "routine-abc123",
                "--content",
                "提醒我看日程",
            ],
            self._handler(
                {
                    "routine_get": _routine_snapshot(),
                    "routine_edit": _rejected(
                        "ValueError: routine schedule failed to validate"
                    ),
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("服务端返回错误（routine_edit）", err)
        self.assertIn("routine schedule failed to validate", err)
        self.assertNotIn("已更新", out)

    def test_edit_missing_routine_id_exits_2_without_rpc(self):
        with self.assertRaises(SystemExit) as caught:
            run(
                [
                    "--endpoint",
                    str(self.endpoint_path),
                    "routine",
                    "edit",
                    "--time",
                    "每天早上9点",
                ]
            )
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])


class RoutineDeleteTests(_RoutineCliHarness):
    """T18: ``zn routine delete`` -- remove one routine."""

    def test_delete(self):
        code, out, err = self._run(
            ["routine", "delete", "--routine-id", "routine-abc123"],
            self._handler(
                {
                    "routine_get": _routine_snapshot(),
                    "routine_delete": {
                        "routine_id": "routine-abc123",
                        "deleted": True,
                    },
                }
            ),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("例行任务 routine-abc123 已删除", out)
        self.assertEqual(
            self.calls,
            [
                ("routine_get", {"routine_id": "routine-abc123"}),
                ("routine_delete", {"routine_id": "routine-abc123"}),
            ],
        )
        self.assertEqual(err, "")

    def test_delete_json_passthrough(self):
        result = {"routine_id": "routine-abc123", "deleted": True}
        code, out, err = self._run(
            ["routine", "delete", "--routine-id", "routine-abc123", "--json"],
            self._handler(
                {"routine_get": _routine_snapshot(), "routine_delete": result}
            ),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), result)
        self.assertEqual(err, "")

    def test_delete_engaged_refuses_without_mutation_rpc(self):
        engaged = _routine_snapshot(
            recent_runs=[_run_row(status="running", finished_at=None)]
        )
        code, out, err = self._run(
            ["routine", "delete", "--routine-id", "routine-abc123"],
            self._handler({"routine_get": engaged}),
        )
        self.assertEqual(code, 1)
        self.assertIn("正在执行中", err)
        self.assertIn("run in flight", err)
        self.assertIn("不能删除", err)
        self.assertNotIn("已删除", out)
        # Only the read-only pre-flight went out; no routine_delete was sent.
        self.assertEqual(
            self.calls, [("routine_get", {"routine_id": "routine-abc123"})]
        )

    def test_delete_unknown_id_is_human_error(self):
        code, out, err = self._run(
            ["routine", "delete", "--routine-id", "routine-nope"],
            self._handler(
                {
                    "routine_get": _rejected(
                        "KeyError: unknown routine: routine-nope"
                    )
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("找不到例行任务 'routine-nope'", err)
        self.assertNotIn("已删除", out)

    def test_delete_server_rejection_surfaces(self):
        code, out, err = self._run(
            ["routine", "delete", "--routine-id", "routine-abc123"],
            self._handler(
                {
                    "routine_get": _routine_snapshot(),
                    "routine_delete": _rejected(
                        "ValueError: routine has a run in flight; "
                        "wait for it to finish before delete"
                    ),
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("服务端返回错误（routine_delete）", err)
        self.assertIn("run in flight", err)
        self.assertNotIn("已删除", out)

    def test_delete_missing_routine_id_exits_2_without_rpc(self):
        with self.assertRaises(SystemExit) as caught:
            run(
                [
                    "--endpoint",
                    str(self.endpoint_path),
                    "routine",
                    "delete",
                ]
            )
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])


def _test_run_row(run_id="run-tr1", status="running", **overrides):
    row = _run_row(
        run_id=run_id,
        status=status,
        trigger_kind="test_run",
        scheduled_at=None,
        finished_at=None,
    )
    row.update(overrides)
    return row


class RoutineTestRunTests(_RoutineCliHarness):
    """T19: ``zn routine test-run`` -- real execution, not a dry run.

    Every test asserts the exact RPC methods/params: the read-only
    ``routine_get`` pre-flight first, then exactly one ``routine_test_run`` --
    and zero mutation RPCs when the routine is engaged.
    """

    def test_run_executes_now(self):
        snapshot = _routine_snapshot(approval_boundary="")
        started = _test_run_row(status="running")
        code, out, err = self._run(
            ["routine", "test-run", "--routine-id", "routine-abc123"],
            self._handler(
                {"routine_get": snapshot, "routine_test_run": started}
            ),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("试运行已启动", out)
        self.assertIn("真执行，不是 dry-run", out)
        self.assertIn("run-tr1", out)
        self.assertEqual(
            self.calls,
            [
                ("routine_get", {"routine_id": "routine-abc123"}),
                ("routine_test_run", {"routine_id": "routine-abc123"}),
            ],
        )
        self.assertEqual(err, "")

    def test_run_awaiting_approval_holds_without_executing(self):
        snapshot = _routine_snapshot(
            approval_boundary="只读汇总，不发送、不发布、不删除、不购买"
        )
        held = _test_run_row(status="awaiting_approval")
        code, out, err = self._run(
            ["routine", "test-run", "--routine-id", "routine-abc123"],
            self._handler(
                {"routine_get": snapshot, "routine_test_run": held}
            ),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("审批等待", out)
        self.assertIn("awaiting_approval", out)
        self.assertIn("暂不执行", out)
        self.assertNotIn("已启动", out)
        self.assertEqual(err, "")

    def test_run_json_passthrough(self):
        snapshot = _routine_snapshot(approval_boundary="")
        started = _test_run_row(status="running")
        code, out, err = self._run(
            [
                "routine",
                "test-run",
                "--routine-id",
                "routine-abc123",
                "--json",
            ],
            self._handler(
                {"routine_get": snapshot, "routine_test_run": started}
            ),
        )
        self.assertEqual(code, 0, err)
        parsed = json.loads(out)
        self.assertEqual(parsed["run_id"], "run-tr1")
        self.assertEqual(parsed["trigger_kind"], "test_run")
        self.assertEqual(parsed["status"], "running")
        self.assertEqual(err, "")

    def test_run_engaged_refuses_without_mutation_rpc(self):
        snapshot = _routine_snapshot(
            recent_runs=[_run_row(status="running")]
        )
        code, out, err = self._run(
            ["routine", "test-run", "--routine-id", "routine-abc123"],
            self._handler({"routine_get": snapshot}),
        )
        self.assertEqual(code, 1)
        self.assertIn("正在执行中", err)
        self.assertIn("不能试运行", err)
        self.assertIn("等这次运行结束后再试", err)
        self.assertEqual(self.calls, [("routine_get", {"routine_id": "routine-abc123"})])
        self.assertNotIn("已启动", out)

    def test_run_denied_boundary_is_human_error(self):
        code, out, err = self._run(
            ["routine", "test-run", "--routine-id", "routine-abc123"],
            self._handler(
                {
                    "routine_get": _routine_snapshot(
                        approval_boundary="只读汇总，不发送"
                    ),
                    "routine_test_run": _rejected(
                        "ValueError: routine test run blocked by its approval "
                        "boundary: approval card denied"
                    ),
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("这次试运行被审批边界拦下了", err)
        self.assertIn(
            "（routine test run blocked by its approval boundary）", err
        )
        self.assertIn("approval card denied", err)
        self.assertNotIn("已启动", out)

    def test_run_unknown_id_is_human_error(self):
        code, out, err = self._run(
            ["routine", "test-run", "--routine-id", "routine-nope"],
            self._handler(
                {
                    "routine_get": _rejected(
                        "KeyError: unknown routine: routine-nope"
                    )
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("找不到例行任务 'routine-nope'", err)
        self.assertNotIn("已启动", out)

    def test_run_server_rejection_surfaces(self):
        code, out, err = self._run(
            ["routine", "test-run", "--routine-id", "routine-abc123"],
            self._handler(
                {
                    "routine_get": _routine_snapshot(approval_boundary=""),
                    "routine_test_run": _rejected(
                        "RuntimeError: boom"
                    ),
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("服务端返回错误（routine_test_run）", err)
        self.assertIn("boom", err)
        self.assertNotIn("已启动", out)

    def test_run_malformed_payload_fails_closed(self):
        code, out, err = self._run(
            ["routine", "test-run", "--routine-id", "routine-abc123"],
            self._handler(
                {
                    "routine_get": _routine_snapshot(approval_boundary=""),
                    "routine_test_run": {"status": "running"},
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertNotIn("已启动", out)
        self.assertEqual(err.strip() != "", True)

    def test_run_missing_routine_id_exits_2_without_rpc(self):
        with self.assertRaises(SystemExit) as caught:
            run(
                [
                    "--endpoint",
                    str(self.endpoint_path),
                    "routine",
                    "test-run",
                ]
            )
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])


class RoutineAcknowledgeTests(_RoutineCliHarness):
    """T19: ``zn routine acknowledge`` -- "I looked at it", resets the
    auto-pause clock.
    """

    def test_acknowledge(self):
        snapshot = _routine_snapshot()
        confirmed = _routine_snapshot(
            last_confirmed_at="2026-10-23T05:30:00+00:00"
        )
        code, out, err = self._run(
            ["routine", "acknowledge", "--routine-id", "routine-abc123"],
            self._handler(
                {"routine_get": snapshot, "routine_acknowledge": confirmed}
            ),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("已确认例行任务 routine-abc123", out)
        self.assertIn("自动暂停计时器已重置", out)
        self.assertEqual(
            self.calls,
            [
                ("routine_get", {"routine_id": "routine-abc123"}),
                ("routine_acknowledge", {"routine_id": "routine-abc123"}),
            ],
        )
        self.assertEqual(err, "")

    def test_acknowledge_json_passthrough(self):
        confirmed = _routine_snapshot()
        code, out, err = self._run(
            [
                "routine",
                "acknowledge",
                "--routine-id",
                "routine-abc123",
                "--json",
            ],
            self._handler(
                {"routine_get": _routine_snapshot(), "routine_acknowledge": confirmed}
            ),
        )
        self.assertEqual(code, 0, err)
        parsed = json.loads(out)
        self.assertEqual(parsed["routine_id"], "routine-abc123")
        self.assertEqual(err, "")

    def test_acknowledge_unknown_id_is_human_error(self):
        code, out, err = self._run(
            ["routine", "acknowledge", "--routine-id", "routine-nope"],
            self._handler(
                {
                    "routine_get": _rejected(
                        "KeyError: unknown routine: routine-nope"
                    )
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("找不到例行任务 'routine-nope'", err)
        self.assertNotIn("已确认", out)

    def test_acknowledge_missing_routine_id_exits_2_without_rpc(self):
        with self.assertRaises(SystemExit) as caught:
            run(
                [
                    "--endpoint",
                    str(self.endpoint_path),
                    "routine",
                    "acknowledge",
                ]
            )
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])


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

    def test_edit_offline_reports_no_change(self):
        code, out, err = self._run_offline(
            [
                "routine",
                "edit",
                "--routine-id",
                "routine-abc123",
                "--time",
                "每天早上9点",
            ]
        )
        self.assertEqual(code, 0)
        self.assertIn("unreachable", out)
        self.assertIn("zn-resident", out)
        self.assertIn("没有修改任何例行任务", out)
        self.assertNotIn("已更新", out)
        self.assertEqual(err, "")

    def test_edit_offline_json(self):
        code, out, err = self._run_offline(
            [
                "routine",
                "edit",
                "--routine-id",
                "routine-abc123",
                "--content",
                "提醒我看日程",
                "--json",
            ]
        )
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertFalse(parsed["daemon_reachable"])
        self.assertFalse(parsed["changed"])
        self.assertEqual(err, "")

    def test_delete_offline_reports_no_change(self):
        code, out, err = self._run_offline(
            ["routine", "delete", "--routine-id", "routine-abc123"]
        )
        self.assertEqual(code, 0)
        self.assertIn("unreachable", out)
        self.assertIn("没有删除任何例行任务", out)
        self.assertNotIn("已删除", out)
        self.assertEqual(err, "")

    def test_test_run_offline_reports_no_change(self):
        code, out, err = self._run_offline(
            ["routine", "test-run", "--routine-id", "routine-abc123"]
        )
        self.assertEqual(code, 0)
        self.assertIn("unreachable", out)
        self.assertIn("zn-resident", out)
        self.assertIn("没有试运行任何例行任务", out)
        self.assertNotIn("已启动", out)
        self.assertEqual(err, "")

    def test_test_run_offline_json(self):
        code, out, err = self._run_offline(
            ["routine", "test-run", "--routine-id", "routine-abc123", "--json"]
        )
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertFalse(parsed["daemon_reachable"])
        self.assertFalse(parsed["changed"])
        self.assertEqual(err, "")

    def test_acknowledge_offline_reports_no_change(self):
        code, out, err = self._run_offline(
            ["routine", "acknowledge", "--routine-id", "routine-abc123"]
        )
        self.assertEqual(code, 0)
        self.assertIn("unreachable", out)
        self.assertIn("zn-resident", out)
        self.assertIn("没有确认任何例行任务", out)
        self.assertNotIn("已确认", out)
        self.assertEqual(err, "")

    def test_acknowledge_offline_json(self):
        code, out, err = self._run_offline(
            ["routine", "acknowledge", "--routine-id", "routine-abc123", "--json"]
        )
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertFalse(parsed["daemon_reachable"])
        self.assertFalse(parsed["changed"])
        self.assertIsNone(parsed["routine"])
        self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()
