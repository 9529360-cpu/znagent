from __future__ import annotations

import contextlib
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime" / "python"))

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import (
    build_resident_runtime_from_existing_stack,
)
from zn_agent.core.resident_server import ResidentSocketService
from zn_agent.core.zn_cli import ResidentClient, _pid_is_dead, load_endpoint, run

_SECRET = "s" * 64


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
        self.sent: list[dict] = []
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
            self.sent.append(request)
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


class _CliHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.endpoint_path = Path(self.tmp.name) / "resident-endpoint.json"
        self.endpoint_path.write_text(
            json.dumps(_endpoint_payload()), encoding="utf-8"
        )
        self.sockets: list[_FakeSocket] = []
        self.connect_calls: list[tuple] = []

    def _handler(self, mapping):
        def handle(method, params):
            self.calls.append((method, params))
            if method not in mapping:
                raise AssertionError(f"unexpected RPC method {method!r}")
            return mapping[method]

        self.calls: list[tuple] = []
        return handle

    def _patch_connect(self, handler):
        def connect(address, timeout=None):
            self.connect_calls.append((address, timeout))
            fake = _FakeSocket(handler)
            self.sockets.append(fake)
            return fake

        patcher = mock.patch("socket.create_connection", side_effect=connect)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, argv, handler):
        self._patch_connect(handler)
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = run(["--endpoint", str(self.endpoint_path), *argv])
        return code, stdout.getvalue(), stderr.getvalue()


class ZnCliUnitTests(_CliHarness):
    def test_work_list_prints_threads(self):
        threads = [
            {
                "id": "thread-1",
                "title": "Write the report",
                "updated_at": "2026-10-19T06:00:00Z",
                "messages": [{"id": "m1"}],
                "active_run": None,
            },
            {
                "id": "thread-2",
                "title": "Second thread",
                "updated_at": "2026-10-19T06:01:00Z",
                "messages": [],
                "active_run": {"event_id": "ev-9"},
            },
        ]
        code, out, err = self._run(
            ["work", "list"], self._handler({"work_list": threads})
        )
        self.assertEqual(code, 0, err)
        self.assertIn("thread-1", out)
        self.assertIn("Write the report", out)
        self.assertIn("active=yes:ev-9", out)
        self.assertEqual(self.calls, [("work_list", {"limit": 24})])

    def test_work_list_json_and_empty(self):
        code, out, _ = self._run(["work", "list", "--json"], self._handler({"work_list": []}))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), [])
        code, out, _ = self._run(["work", "list"], self._handler({"work_list": []}))
        self.assertEqual(code, 0)
        self.assertIn("no work threads", out)

    def test_work_get_prints_messages(self):
        snapshot = {
            "id": "thread-1",
            "title": "Thread",
            "created_at": "2026-10-19T05:00:00Z",
            "updated_at": "2026-10-19T06:00:00Z",
            "messages": [
                {"created_at": "2026-10-19T05:01:00Z", "role": "user", "text": "hello"},
                {"created_at": "2026-10-19T05:02:00Z", "role": "assistant", "text": "done"},
            ],
        }
        code, out, err = self._run(
            ["work", "get", "--thread-id", "thread-1"],
            self._handler({"work_get": snapshot}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("hello", out)
        self.assertIn("done", out)
        self.assertEqual(
            self.calls, [("work_get", {"thread_id": "thread-1", "message_limit": 120})]
        )

    def test_work_submit_uses_existing_thread(self):
        result = {
            "thread": {"id": "thread-1", "title": "Thread"},
            "run": {
                "event_id": "ev-1",
                "success": True,
                "cancelled": False,
                "execution_path": "direct",
                "model_invocations": 2,
                "response": "finished",
            },
            "recovery_required": False,
        }
        code, out, err = self._run(
            ["work", "submit", "--thread-id", "thread-1", "--task", "do the thing"],
            self._handler({"work_submit": result}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("submitted to thread thread-1", out)
        self.assertEqual(
            self.calls,
            [("work_submit", {"thread_id": "thread-1", "task": "do the thing"})],
        )

    def test_work_submit_without_thread_creates_one_first(self):
        result = {
            "thread": {"id": "thread-new", "title": "do the thing"},
            "run": {},
            "recovery_required": False,
        }
        code, out, err = self._run(
            ["work", "submit", "--task", "do the thing"],
            self._handler(
                {
                    "work_create": {"id": "thread-new", "title": "do the thing"},
                    "work_submit": result,
                }
            ),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("submitted to thread thread-new", out)
        self.assertEqual(
            [method for method, _ in self.calls], ["work_create", "work_submit"]
        )
        self.assertEqual(self.calls[1][1]["thread_id"], "thread-new")

    def test_approval_list_defaults_to_pending(self):
        result = {
            "pending": [
                {
                    "request_id": "req-pending",
                    "status": "pending",
                    "action_kind": "send",
                    "target": "someone",
                    "scope": "chat",
                    "expires_at": "2026-10-19T07:00:00Z",
                }
            ],
            "denied": [
                {
                    "request_id": "req-denied",
                    "status": "denied",
                    "action_kind": "send",
                    "target": "someone",
                    "scope": "chat",
                    "expires_at": "",
                }
            ],
            "expired": [],
            "applied": [],
        }
        code, out, err = self._run(
            ["approval", "list"], self._handler({"approval_list": result})
        )
        self.assertEqual(code, 0, err)
        self.assertIn("req-pending", out)
        self.assertNotIn("req-denied", out)

        code, out, _ = self._run(
            ["approval", "list", "--status", "all"],
            self._handler({"approval_list": result}),
        )
        self.assertEqual(code, 0)
        self.assertIn("req-denied", out)

    def test_approval_decide_maps_flags_to_rpc_decisions(self):
        for flag, decision in [
            ("--allow", "allow_once"),
            ("--deny", "deny"),
            ("--always-allow", "always_allow"),
        ]:
            with self.subTest(flag=flag):
                self.calls = []
                result = {
                    "request": {
                        "request_id": "req-1",
                        "status": "approved_once" if decision != "deny" else "denied",
                        "decision": decision,
                    }
                }
                code, out, err = self._run(
                    ["approval", "decide", "--request-id", "req-1", flag],
                    self._handler({"approval_decide": result}),
                )
                self.assertEqual(code, 0, err)
                self.assertIn("req-1", out)
                self.assertEqual(
                    self.calls,
                    [("approval_decide", {"request_id": "req-1", "decision": decision})],
                )

    def test_memory_list_prints_facts_without_values(self):
        facts = [
            {
                "key": "project",
                "aliases": ["active project"],
                "updated_at": "2026-10-20T06:00:00Z",
                "tier": "hot",
            },
            {
                "key": "old-note",
                "aliases": [],
                "updated_at": "2026-10-19T06:00:00Z",
                "tier": "deep",
            },
        ]
        code, out, err = self._run(
            ["memory", "list"], self._handler({"memory_list": facts})
        )
        self.assertEqual(code, 0, err)
        self.assertIn("project", out)
        self.assertIn("tier=hot", out)
        self.assertIn("active project", out)
        self.assertIn("tier=deep", out)
        self.assertNotIn("value", out)
        self.assertEqual(self.calls, [("memory_list", {"limit": 20})])

    def test_memory_list_limit_flag_and_json(self):
        facts = [
            {
                "key": "k",
                "aliases": [],
                "updated_at": "2026-10-20T06:00:00Z",
                "tier": "hot",
            }
        ]
        code, out, err = self._run(
            ["memory", "list", "--limit", "5"],
            self._handler({"memory_list": facts}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(self.calls, [("memory_list", {"limit": 5})])
        code, out, _ = self._run(
            ["memory", "list", "--json"], self._handler({"memory_list": facts})
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), facts)

    def test_memory_list_empty(self):
        code, out, err = self._run(
            ["memory", "list"], self._handler({"memory_list": []})
        )
        self.assertEqual(code, 0, err)
        self.assertIn("no remembered facts", out)

    def test_team_list_prints_teams(self):
        teams = [
            {
                "team_id": "team-7f3a9c1e",
                "project_title": "公司官网改版",
                "roster": ["调研-01", "开发-02"],
                "status": "active",
            },
            {
                "team_id": "team-aa11bb22",
                "project_title": "仓库物流系统",
                "roster": ["架构-01"],
                "status": "active",
            },
        ]
        code, out, err = self._run(
            ["team", "list"], self._handler({"team_list": teams})
        )
        self.assertEqual(code, 0, err)
        self.assertIn("team-7f3a9c1e", out)
        self.assertIn("status=active", out)
        self.assertIn("调研-01", out)
        self.assertIn("开发-02", out)
        self.assertIn("公司官网改版", out)
        self.assertIn("team-aa11bb22", out)
        self.assertEqual(self.calls, [("team_list", {"limit": 20})])

    def test_team_list_limit_flag_and_json(self):
        teams = [
            {
                "team_id": "team-7f3a9c1e",
                "project_title": "公司官网改版",
                "roster": ["调研-01"],
                "status": "active",
            }
        ]
        code, out, err = self._run(
            ["team", "list", "--limit", "5"],
            self._handler({"team_list": teams}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(self.calls, [("team_list", {"limit": 5})])
        code, out, _ = self._run(
            ["team", "list", "--json"], self._handler({"team_list": teams})
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), teams)

    def test_team_list_empty(self):
        code, out, err = self._run(
            ["team", "list"], self._handler({"team_list": []})
        )
        self.assertEqual(code, 0, err)
        self.assertIn("no active teams", out)

    def test_unknown_command_and_conflicting_flags_exit_2_without_rpc(self):
        with self.assertRaises(SystemExit) as caught:
            run(["bogus"])
        self.assertEqual(caught.exception.code, 2)
        with self.assertRaises(SystemExit) as caught:
            run(
                [
                    "--endpoint",
                    str(self.endpoint_path),
                    "approval",
                    "decide",
                    "--request-id",
                    "req-1",
                    "--allow",
                    "--deny",
                ]
            )
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.connect_calls, [])

    def test_missing_and_empty_arguments_exit_2_without_rpc(self):
        cases = [
            ["work", "submit", "--thread-id", "t1"],
            ["work", "submit", "--thread-id", "t1", "--task", ""],
            ["work", "submit", "--thread-id", "t1", "--task", "   "],
            ["work", "list", "--limit", "0"],
            ["work", "list", "--limit", "101"],
            ["work", "get"],
            ["approval", "decide", "--request-id", "req-1"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit) as caught:
                    run(["--endpoint", str(self.endpoint_path), *argv])
                self.assertEqual(caught.exception.code, 2)
                self.assertEqual(self.connect_calls, [])

    def test_connection_refused_is_exit_1_with_readable_reason(self):
        with mock.patch(
            "socket.create_connection", side_effect=ConnectionRefusedError("refused")
        ):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = run(
                    ["--endpoint", str(self.endpoint_path), "work", "list"]
                )
        self.assertEqual(code, 1)
        self.assertIn("could not reach", stderr.getvalue())
        self.assertIn("refused", stderr.getvalue())

    def test_rpc_error_is_exit_1_with_server_reason(self):
        code, _, err = self._run(
            ["work", "list"],
            self._handler({"work_list": (False, None, "thread not found")}),
        )
        self.assertEqual(code, 1)
        self.assertIn("thread not found", err)

    def test_authentication_failure_is_exit_1(self):
        def handler(method, params):
            return {"authenticated": False}

        def connect(address, timeout=None):
            fake = _FakeSocket(handler)
            # Override: every response is an auth failure.
            original = fake.sendall

            def sendall(data):
                original(data)
                fake.stream.lines = [
                    json.dumps(
                        {"id": "x", "ok": False, "error": "authentication failed"}
                    ).encode("utf-8")
                    + b"\n"
                ]

            fake.sendall = sendall
            return fake

        with mock.patch("socket.create_connection", side_effect=connect):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = run(
                    ["--endpoint", str(self.endpoint_path), "work", "list"]
                )
        self.assertEqual(code, 1)
        self.assertIn("authentication failed", stderr.getvalue())

    def test_missing_endpoint_file_is_exit_1(self):
        missing = Path(self.tmp.name) / "no-such-endpoint.json"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = run(["--endpoint", str(missing), "work", "list"])
        self.assertEqual(code, 1)
        self.assertIn("endpoint not found", stderr.getvalue())

    def test_malformed_endpoint_is_exit_1(self):
        self.endpoint_path.write_text("{not json", encoding="utf-8")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = run(
                ["--endpoint", str(self.endpoint_path), "work", "list"]
            )
        self.assertEqual(code, 1)
        self.assertIn("not readable as JSON", stderr.getvalue())

    def test_non_loopback_endpoint_is_refused_without_connecting(self):
        self.endpoint_path.write_text(
            json.dumps(_endpoint_payload(host="192.168.1.10")), encoding="utf-8"
        )
        with mock.patch("socket.create_connection") as connect:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = run(
                    ["--endpoint", str(self.endpoint_path), "work", "list"]
                )
        self.assertEqual(code, 1)
        self.assertIn("non-loopback", stderr.getvalue())
        connect.assert_not_called()

    def test_stale_pid_endpoint_is_refused_without_connecting(self):
        # Deterministic across platforms: a real dead-pid probe depends on
        # OS kill() semantics (POSIX ESRCH vs Windows winerror 87) and on
        # pid reuse, so simulate the OS reporting the pid dead.
        self.endpoint_path.write_text(
            json.dumps(_endpoint_payload(pid=424242)), encoding="utf-8"
        )
        with (
            mock.patch("os.kill", side_effect=ProcessLookupError("no such process")),
            mock.patch("socket.create_connection") as connect,
        ):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = run(
                    ["--endpoint", str(self.endpoint_path), "work", "list"]
                )
        self.assertEqual(code, 1)
        self.assertIn("stale", stderr.getvalue())
        connect.assert_not_called()

    def test_pid_is_dead_maps_os_errors(self):
        with mock.patch("os.kill", side_effect=ProcessLookupError("gone")):
            self.assertTrue(_pid_is_dead(424242))
        with mock.patch("os.kill", side_effect=PermissionError("denied")):
            self.assertFalse(_pid_is_dead(424242))
        dead_windows = OSError(87, "invalid parameter")
        dead_windows.winerror = 87
        with mock.patch("os.kill", side_effect=dead_windows):
            self.assertTrue(_pid_is_dead(424242))
        live_windows = OSError(5, "access denied")
        live_windows.winerror = 5
        with mock.patch("os.kill", side_effect=live_windows):
            self.assertFalse(_pid_is_dead(424242))
        with mock.patch("os.kill", return_value=None):
            self.assertFalse(_pid_is_dead(424242))

    def test_load_endpoint_rejects_short_secret(self):
        self.endpoint_path.write_text(
            json.dumps(
                _endpoint_payload(
                    authentication={"scheme": "session-secret-v1", "secret": "short"}
                )
            ),
            encoding="utf-8",
        )
        with self.assertRaises(Exception) as caught:
            load_endpoint(str(self.endpoint_path))
        self.assertIn("secret", str(caught.exception))


class ZnCliT7BatchTests(_CliHarness):
    """T7: memory remember/forget, team timeline, work cancel CLI commands."""

    def test_memory_remember_sends_key_and_value(self):
        handler = self._handler({"remember": {"saved": True, "key": "k1"}})
        code, out, err = self._run(
            ["memory", "remember", "--key", "k1", "--value", "v1"], handler
        )
        self.assertEqual(code, 0, err)
        self.assertIn("k1", out)
        self.assertEqual(self.calls, [("remember", {"key": "k1", "value": "v1"})])

    def test_memory_remember_forwards_sensitivity_only_when_given(self):
        handler = self._handler({"remember": {"saved": True, "key": "k1"}})
        code, out, err = self._run(
            [
                "memory", "remember", "--key", "k1", "--value", "v1",
                "--sensitivity", "sensitive",
            ],
            handler,
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(
            self.calls,
            [("remember", {"key": "k1", "value": "v1", "sensitivity": "sensitive"})],
        )

    def test_memory_remember_requires_key_and_value(self):
        handler = self._handler({})
        for argv in (
            ["memory", "remember", "--value", "v1"],
            ["memory", "remember", "--key", "k1"],
            ["memory", "remember", "--key", "  ", "--value", "v1"],
        ):
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit) as caught:
                    self._run(argv, handler)
                self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])

    def test_memory_forget_yes_skips_prompt_and_calls_rpc(self):
        handler = self._handler({"forget": {"forgotten": True, "key": "k1"}})
        with mock.patch(
            "builtins.input",
            side_effect=AssertionError("prompt must not appear with --yes"),
        ):
            code, out, err = self._run(
                ["memory", "forget", "--key", "k1", "--yes"], handler
            )
        self.assertEqual(code, 0, err)
        self.assertIn("k1", out)
        self.assertEqual(self.calls, [("forget", {"key": "k1"})])

    def test_memory_forget_confirmed_typing_yes_executes(self):
        handler = self._handler({"forget": {"forgotten": True, "key": "k1"}})
        with mock.patch("builtins.input", return_value="y"):
            code, out, err = self._run(["memory", "forget", "--key", "k1"], handler)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.calls, [("forget", {"key": "k1"})])

    def test_memory_forget_without_confirmation_aborts_without_rpc(self):
        handler = self._handler({"forget": {"forgotten": True, "key": "k1"}})
        for answer in ("", "n", "no", "yess"):
            with self.subTest(answer=answer):
                self.calls = []
                with mock.patch("builtins.input", return_value=answer):
                    code, out, err = self._run(
                        ["memory", "forget", "--key", "k1"], handler
                    )
                self.assertEqual(code, 1, err)
                self.assertIn("aborted", out)
                self.assertIn("NOT forgotten", out)
                self.assertEqual(self.calls, [])

    def test_memory_forget_eof_aborts_without_rpc(self):
        handler = self._handler({"forget": {"forgotten": True, "key": "k1"}})
        with mock.patch("builtins.input", side_effect=EOFError):
            code, out, err = self._run(["memory", "forget", "--key", "k1"], handler)
        self.assertEqual(code, 1, err)
        self.assertEqual(self.calls, [])

    def test_team_timeline_renders_entries(self):
        payload = {
            "team_id": "team-abc123",
            "members": ["researcher"],
            "entries": [
                {
                    "id": "m1",
                    "kind": "assignment",
                    "author": "user",
                    "from_author": "user",
                    "to_author": "researcher",
                    "item_title": "调研 X",
                    "text": "开始调研",
                    "at": "2026-10-21T10:00:00",
                    "team_id": "team-abc123",
                },
            ],
        }
        handler = self._handler({"team_timeline": payload})
        code, out, err = self._run(
            ["team", "timeline", "--thread-id", "t1"], handler
        )
        self.assertEqual(code, 0, err)
        self.assertIn("team-abc123", out)
        self.assertIn("researcher", out)
        self.assertIn("调研 X", out)
        self.assertEqual(self.calls, [("team_timeline", {"thread_id": "t1"})])

    def test_team_timeline_json_passthrough(self):
        payload = {"team_id": None, "members": [], "entries": []}
        handler = self._handler({"team_timeline": payload})
        code, out, err = self._run(
            ["team", "timeline", "--thread-id", "t1", "--json"], handler
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), payload)

    def test_work_cancel_sends_thread_and_event(self):
        payload = {
            "progress": {"state": "cancelled", "cancelled": True},
            "thread": {"id": "t1"},
        }
        handler = self._handler({"work_cancel": payload})
        code, out, err = self._run(
            ["work", "cancel", "--thread-id", "t1", "--event-id", "e9"], handler
        )
        self.assertEqual(code, 0, err)
        self.assertIn("e9", out)
        self.assertIn("t1", out)
        self.assertEqual(
            self.calls, [("work_cancel", {"thread_id": "t1", "event_id": "e9"})]
        )

    def test_new_commands_surface_rpc_errors_as_exit_1(self):
        handler = self._handler({"remember": (False, None, "boom")})
        code, out, err = self._run(
            ["memory", "remember", "--key", "k1", "--value", "v1"], handler
        )
        self.assertEqual(code, 1)
        self.assertIn("boom", err)


def _best_effort_shutdown(endpoint_path) -> bool:
    """Ask a test resident to shut down; False when it is already gone."""

    try:
        ResidentClient(load_endpoint(str(endpoint_path))).call("shutdown", {})
    except Exception:
        return False
    return True


class ZnCliResidentIntegrationTests(unittest.TestCase):
    """End-to-end: CLI -> real ResidentSocketService -> real approval store."""

    def test_cli_against_real_resident(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            endpoint_path = root / "resident-endpoint.json"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            rpc = ResidentRpcServer(resident=resident, life_interval=0.1)
            service = ResidentSocketService(rpc, endpoint_path=endpoint_path)
            thread = threading.Thread(
                target=service.serve_forever, name="test-zn-cli-resident", daemon=True
            )
            thread.start()
            try:
                deadline = time.monotonic() + 10.0
                while not endpoint_path.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(endpoint_path.exists(), "resident endpoint not published")

                client = ResidentClient(load_endpoint(str(endpoint_path)))
                created = client.call(
                    "work_create", {"title": "CLI integration thread"}
                )
                thread_id = created["id"]
                created_card = client.call(
                    "approval_request",
                    {
                        "action_kind": "send",
                        "target": "integration-target",
                        "scope": "integration-scope",
                        "value_text": "",
                        "source": "resident",
                    },
                )
                request_id = created_card["request"]["request_id"]

                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = run(
                        [
                            "--endpoint",
                            str(endpoint_path),
                            "work",
                            "list",
                        ]
                    )
                self.assertEqual(code, 0, stderr.getvalue())
                self.assertIn(thread_id, stdout.getvalue())

                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = run(
                        [
                            "--endpoint",
                            str(endpoint_path),
                            "approval",
                            "list",
                        ]
                    )
                self.assertEqual(code, 0, stderr.getvalue())
                self.assertIn(request_id, stdout.getvalue())

                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = run(
                        [
                            "--endpoint",
                            str(endpoint_path),
                            "approval",
                            "decide",
                            "--request-id",
                            request_id,
                            "--allow",
                        ]
                    )
                self.assertEqual(code, 0, stderr.getvalue())
                self.assertIn("approved_once", stdout.getvalue())

                # The decided card is no longer pending.
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = run(
                        [
                            "--endpoint",
                            str(endpoint_path),
                            "approval",
                            "list",
                        ]
                    )
                self.assertEqual(code, 0, stderr.getvalue())
                self.assertNotIn(request_id, stdout.getvalue())

                # memory list against the real resident: key listed, value not leaked.
                client.call(
                    "remember",
                    {"key": "cli-memory-key", "value": "cli-secret-value", "aliases": ["k"]},
                )
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = run(
                        [
                            "--endpoint",
                            str(endpoint_path),
                            "memory",
                            "list",
                        ]
                    )
                self.assertEqual(code, 0, stderr.getvalue())
                self.assertIn("cli-memory-key", stdout.getvalue())
                self.assertIn("tier=hot", stdout.getvalue())
                self.assertNotIn("cli-secret-value", stdout.getvalue())

                # team list against the real resident: team listed via its
                # persisted spec, roster derived from the spec.
                client.call(
                    "remember",
                    {
                        "key": "team:team-cli9f2a:shared:team_spec",
                        "value": {
                            "project_title": "集成测试项目",
                            "role_keys": ["researcher"],
                        },
                    },
                )
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = run(
                        [
                            "--endpoint",
                            str(endpoint_path),
                            "team",
                            "list",
                        ]
                    )
                self.assertEqual(code, 0, stderr.getvalue())
                self.assertIn("team-cli9f2a", stdout.getvalue())
                self.assertIn("status=active", stdout.getvalue())
                self.assertIn("调研-01", stdout.getvalue())
                self.assertIn("集成测试项目", stdout.getvalue())
            finally:
                _best_effort_shutdown(endpoint_path)
                thread.join(timeout=10.0)
                resident.store.close()

    def test_cli_t7_batch_against_real_resident(self):
        """End-to-end: remember/forget/timeline/cancel through a real daemon."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "kernel.db"
            endpoint_path = root / "resident-endpoint.json"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            rpc = ResidentRpcServer(resident=resident, life_interval=0.1)
            service = ResidentSocketService(rpc, endpoint_path=endpoint_path)
            thread = threading.Thread(
                target=service.serve_forever, name="test-zn-cli-t7", daemon=True
            )
            thread.start()
            try:
                deadline = time.monotonic() + 10.0
                while not endpoint_path.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(endpoint_path.exists(), "resident endpoint not published")

                def cli(*argv):
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
                        stderr
                    ):
                        code = run(["--endpoint", str(endpoint_path), *argv])
                    return code, stdout.getvalue(), stderr.getvalue()

                # remember -> list shows the key (value stays hidden) ->
                # forget --yes -> key is gone.
                code, out, err = cli(
                    "memory", "remember", "--key", "t7-fact", "--value", "t7-value"
                )
                self.assertEqual(code, 0, err)
                self.assertIn("t7-fact", out)
                code, out, err = cli("memory", "list")
                self.assertEqual(code, 0, err)
                self.assertIn("t7-fact", out)
                self.assertNotIn("t7-value", out)
                code, out, err = cli("memory", "forget", "--key", "t7-fact", "--yes")
                self.assertEqual(code, 0, err)
                self.assertIn("t7-fact", out)
                code, out, err = cli("memory", "list")
                self.assertEqual(code, 0, err)
                self.assertNotIn("t7-fact", out)

                # team timeline on a real thread with no team journal:
                # empty but still exit 0.
                client = ResidentClient(load_endpoint(str(endpoint_path)))
                thread_id = client.call("work_create", {"title": "CLI t7 thread"})["id"]
                code, out, err = cli("team", "timeline", "--thread-id", thread_id)
                self.assertEqual(code, 0, err)
                self.assertIn("no timeline entries", out)

                # work cancel round-trips the real RPC shape: an unknown
                # event is rejected by the daemon with a readable reason.
                code, out, err = cli(
                    "work", "cancel", "--thread-id", thread_id, "--event-id", "nope"
                )
                self.assertEqual(code, 1)
                self.assertIn("unknown work event", err)
            finally:
                _best_effort_shutdown(endpoint_path)
                thread.join(timeout=10.0)
                resident.store.close()


if __name__ == "__main__":
    unittest.main()


class ZnCliSkillUsageTests(unittest.TestCase):
    """``zn skill usage`` / ``zn skill prune`` against the real T2 query surface."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = datetime.now(timezone.utc)
        self.skills_root = self._make_skills_root(
            {
                "alpha": (5, (self.now - timedelta(hours=2)).isoformat()),
                "beta": (2, (self.now - timedelta(days=60)).isoformat()),
                "gamma": (0, None),
            }
        )

    def _make_skills_root(self, entries: dict[str, tuple[int, str | None]]) -> Path:
        root = Path(self.tmp.name) / "skills"
        for name in entries:
            bundle = root / name
            bundle.mkdir(parents=True, exist_ok=True)
            (bundle / "skill.md").write_text(
                f"---\nname: {name}\ndescription: test skill {name}\n"
                f"version: 0.1.0\n---\n\nBody for {name}.\n",
                encoding="utf-8",
            )
        payload = {
            "version": 1,
            "skills": {
                name: {"usage_count": count, "last_used": last_used or ""}
                for name, (count, last_used) in entries.items()
            },
        }
        (root / "skills.usage.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        return root

    def _patch_store(self):
        from zn_agent.core import zn_cli
        from zn_agent.core.skills import SkillStore

        patcher = mock.patch.object(
            zn_cli, "_skill_store", lambda: SkillStore(root=self.skills_root)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run_local(self, argv: list[str]) -> tuple[int, str, str]:
        from zn_agent.core.zn_cli import run

        self._patch_store()
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = run(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def _line_for(self, out: str, name: str) -> str:
        for line in out.splitlines():
            if name in line:
                return line
        self.fail(f"no output line mentions {name!r}:\n{out}")

    def _snapshot(self) -> set[str]:
        return {
            str(path.relative_to(self.skills_root))
            for path in self.skills_root.rglob("*")
        }

    def test_skill_usage_queries_real_query_surface(self):
        code, out, err = self._run_local(
            ["skill", "usage", "--dormant-days", "30"]
        )
        self.assertEqual(code, 0, err)
        self.assertIn("uses=5", self._line_for(out, "alpha"))
        self.assertNotIn("dormant", self._line_for(out, "alpha"))
        self.assertIn("uses=2", self._line_for(out, "beta"))
        self.assertIn("dormant", self._line_for(out, "beta"))
        gamma_line = self._line_for(out, "gamma")
        self.assertIn("uses=0", gamma_line)
        self.assertIn("never", gamma_line)
        self.assertIn("dormant", gamma_line)

    def test_skill_usage_json_and_dormant_days_threshold(self):
        code, out, err = self._run_local(
            ["skill", "usage", "--dormant-days", "90", "--json"]
        )
        self.assertEqual(code, 0, err)
        parsed = json.loads(out)
        self.assertEqual(parsed["dormant_days"], 90)
        rows = {row["name"]: row for row in parsed["skills"]}
        self.assertEqual(
            [rows[name]["usage_count"] for name in ("alpha", "beta", "gamma")],
            [5, 2, 0],
        )
        self.assertFalse(rows["alpha"]["dormant"])
        # 60 days old is under the 90-day threshold, so only the zero-hit
        # skill counts as dormant.
        self.assertFalse(rows["beta"]["dormant"])
        self.assertTrue(rows["beta"]["never_used"] is False)
        self.assertTrue(rows["gamma"]["never_used"])
        self.assertTrue(rows["gamma"]["dormant"])

    def test_skill_prune_dry_run_deletes_nothing(self):
        before = self._snapshot()
        code, out, err = self._run_local(
            ["skill", "prune", "--dormant-days", "30"]
        )
        self.assertEqual(code, 0, err)
        self.assertIn("dry-run", out)
        self.assertIn("nothing deleted", out)
        self.assertIn("beta", out)
        self.assertIn("gamma", out)
        self.assertNotIn("alpha", out)
        self.assertEqual(self._snapshot(), before)

    def test_skill_prune_no_dry_run_refused_with_readable_reason(self):
        before = self._snapshot()
        code, out, err = self._run_local(["skill", "prune", "--no-dry-run"])
        self.assertEqual(code, 1)
        self.assertIn("human confirmation", err)
        self.assertEqual(self._snapshot(), before)

    def test_skill_usage_invalid_dormant_days_exit_2(self):
        from zn_agent.core.zn_cli import run

        for argv in (["skill", "usage", "--dormant-days", "0"],
                     ["skill", "prune", "--dormant-days", "99999"]):
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit) as caught:
                    run(argv)
                self.assertEqual(caught.exception.code, 2)

    def test_skill_usage_no_skills_discovered(self):
        empty_root = Path(self.tmp.name) / "empty-skills"
        from zn_agent.core import zn_cli
        from zn_agent.core.skills import SkillStore

        with mock.patch.object(
            zn_cli, "_skill_store", lambda: SkillStore(root=empty_root)
        ):
            stdout, stderr = io.StringIO(), io.StringIO()
            from zn_agent.core.zn_cli import run

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
                stderr
            ):
                code = run(["skill", "usage"])
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertIn("no skills discovered", stdout.getvalue())
