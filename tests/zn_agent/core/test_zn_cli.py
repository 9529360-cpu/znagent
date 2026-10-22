from __future__ import annotations

import argparse
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
from zn_agent.core import zn_cli as _zn_cli_module
from zn_agent.core.provider_bridge import (
    build_resident_runtime_from_existing_stack,
)
from zn_agent.core.resident_server import ResidentSocketService
from zn_agent.core.zn_cli import (
    ResidentClient,
    _cli_error,
    _format_approval_card,
    _long_text,
    _pid_is_dead,
    _set_error_details,
    _unexpected_result,
    build_parser,
    load_endpoint,
    run,
)

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

    def test_pid_is_dead_windows_snapshot_overrides_spurious_87(self):
        # Windows false positive seen on CI: OpenProcess reports a LIVE pid
        # as dead (OSError winerror 87). The Toolhelp snapshot is the second
        # opinion: pid listed -> alive even when os.kill said dead.
        dead_windows = OSError(87, "invalid parameter")
        dead_windows.winerror = 87
        with (
            mock.patch("os.kill", side_effect=dead_windows),
            mock.patch.object(
                _zn_cli_module,
                "_windows_pid_in_process_snapshot",
                return_value=True,
            ),
        ):
            self.assertFalse(_pid_is_dead(424242))
        with (
            mock.patch("os.kill", side_effect=dead_windows),
            mock.patch.object(
                _zn_cli_module,
                "_windows_pid_in_process_snapshot",
                return_value=False,
            ),
        ):
            self.assertTrue(_pid_is_dead(424242))
        with (
            mock.patch("os.kill", side_effect=dead_windows),
            mock.patch.object(
                _zn_cli_module,
                "_windows_pid_in_process_snapshot",
                return_value=None,
            ),
        ):
            # Snapshot unavailable: fall back to the os.kill verdict.
            self.assertTrue(_pid_is_dead(424242))

    def test_windows_process_snapshot_lists_live_pids(self):
        # Validates the ctypes Toolhelp plumbing itself. On non-Windows the
        # helper is defined to stay out of the way (None).
        probe = _zn_cli_module._windows_pid_in_process_snapshot
        if os.name != "nt":
            self.assertIsNone(probe(os.getpid()))
            return
        self.assertTrue(probe(os.getpid()))
        self.assertFalse(probe(2147483646))

    def test_work_list_child_reaches_inprocess_resident(self):
        # Regression shape of the CI paradox: the resident lives in THIS
        # process (endpoint pid == our own pid) while a spawned `zn work
        # list` child checks that pid. The child must reach the resident
        # instead of misreporting the live parent as a stale endpoint.
        import subprocess

        with tempfile.TemporaryDirectory(prefix="win-pid-e2e-") as tmp:
            root = Path(tmp)
            home = root / "home"
            home.mkdir(parents=True, exist_ok=True)
            db = home / "kernel.db"
            endpoint_path = home / "kernel" / "resident-endpoint.json"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            rpc = ResidentRpcServer(resident=resident, life_interval=0.1)
            service = ResidentSocketService(rpc, endpoint_path=endpoint_path)
            thread = threading.Thread(
                target=service.serve_forever,
                name="test-win-pid-e2e-resident",
                daemon=True,
            )
            thread.start()
            try:
                deadline = time.monotonic() + 15.0
                while not endpoint_path.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(endpoint_path.exists(), "resident endpoint not published")

                repo_root = Path(__file__).resolve().parents[3]
                child_env = dict(os.environ)
                child_env.update(
                    {
                        "ZN_HOME": str(home),
                        "ZN_AGENT_HOME": str(home),
                        "PYTHONPATH": str(repo_root / "runtime" / "python"),
                        "PYTHONIOENCODING": "utf-8",
                    }
                )
                popen_kwargs: dict = {
                    "env": child_env,
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.PIPE,
                    "text": True,
                }
                if os.name == "nt":
                    popen_kwargs["stdin"] = subprocess.DEVNULL
                    popen_kwargs["creationflags"] = (
                        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    )
                proc = subprocess.Popen(
                    [sys.executable, "-m", "zn_agent.core.zn_cli", "work", "list"],
                    **popen_kwargs,
                )
                try:
                    out, err = proc.communicate(timeout=60)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    out, err = proc.communicate()
                    self.fail("zn work list child did not exit within 60s")
                self.assertEqual(proc.returncode, 0, err)
                self.assertNotIn("stale", err)
                self.assertNotIn("已过期", err)
                self.assertIn("no work threads", out)
            finally:
                _best_effort_shutdown(endpoint_path)
                thread.join(timeout=10.0)
                resident.store.close()

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


class ZnCliLongTextT24Tests(_CliHarness):
    """T2-4: replies keep their line structure; long text paginates on TTY only.

    Non-TTY / NO_COLOR output always carries the full text (script-safe, no
    silent drops); only a real human terminal truncates to 60 lines, with an
    overflow note pointing at the full source.
    """

    def _submit_result(self, response):
        return {
            "thread": {"id": "thread-1", "title": "T"},
            "run": {
                "event_id": "ev-1",
                "success": True,
                "cancelled": False,
                "execution_path": "direct",
                "model_invocations": 2,
                "response": response,
            },
            "recovery_required": False,
        }

    def _run_on_tty(self, argv, handler, no_color=False):
        self._patch_connect(handler)

        class _Tty(io.StringIO):
            def isatty(self):
                return True

        tty, stderr = _Tty(), io.StringIO()
        env = {key: value for key, value in os.environ.items() if key != "NO_COLOR"}
        if no_color:
            env["NO_COLOR"] = "1"
        env["TERM"] = "xterm-256color"
        with mock.patch.dict(os.environ, env, clear=True):
            with contextlib.redirect_stdout(tty), contextlib.redirect_stderr(stderr):
                code = run(["--endpoint", str(self.endpoint_path), *argv])
        return code, tty.getvalue(), stderr.getvalue()

    def test_long_text_unit_keeps_structure_and_sanitizes(self):
        with mock.patch("zn_agent.core.zn_cli.use_color", return_value=False):
            self.assertEqual(_long_text("a\nb\nc"), "a\nb\nc")
            self.assertEqual(_long_text("a\tb"), "a\tb")  # tabs survive
            # control characters are neutralized, newlines are not
            self.assertEqual(_long_text("a\x00b\nc\x07d"), "a b\nc d")
            # a trailing newline does not inflate the line count
            self.assertEqual(_long_text("x\ny\n"), "x\ny")
            self.assertEqual(_long_text(""), "")
            # non-TTY: over-long text is complete, never silently dropped
            long_text = "\n".join(f"LN{i:03d}" for i in range(100))
            self.assertEqual(_long_text(long_text), long_text)

    def test_long_text_unit_paginates_on_tty(self):
        with mock.patch("zn_agent.core.zn_cli.use_color", return_value=True):
            long_text = "\n".join(f"LN{i:03d}" for i in range(100))
            rendered = _long_text(long_text)
            self.assertIn("LN059", rendered)
            self.assertNotIn("LN060", rendered)
            self.assertIn("全文共 100 行，仅显示前 60 行", rendered)
            # exactly 60 lines: no truncation even on TTY
            sixty = "\n".join(f"LN{i:03d}" for i in range(60))
            self.assertEqual(_long_text(sixty), sixty)
            noted = _long_text(
                long_text, overflow_suffix="；全文见 `zn work get --thread-id t`"
            )
            self.assertIn("全文见 `zn work get --thread-id t`", noted)

    def test_submit_response_keeps_multiline(self):
        response = "第一行\n第二行\n第三行"
        code, out, err = self._run(
            ["work", "submit", "--thread-id", "thread-1", "--task", "do it"],
            self._handler({"work_submit": self._submit_result(response)}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("第一行\n第二行\n第三行", out)

    def test_submit_long_response_truncates_on_tty_with_pointer(self):
        response = "\n".join(f"LN{i:03d}" for i in range(100))
        code, out, err = self._run_on_tty(
            ["work", "submit", "--thread-id", "thread-1", "--task", "do it"],
            self._handler({"work_submit": self._submit_result(response)}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("LN059", out)
        self.assertNotIn("LN060", out)
        self.assertIn("全文见 `zn work get --thread-id thread-1`", out)

    def test_submit_long_response_full_on_non_tty(self):
        response = "\n".join(f"LN{i:03d}" for i in range(100))
        code, out, err = self._run(
            ["work", "submit", "--thread-id", "thread-1", "--task", "do it"],
            self._handler({"work_submit": self._submit_result(response)}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("LN099", out)
        self.assertNotIn("全文见", out)

    def test_submit_long_response_full_with_no_color(self):
        response = "\n".join(f"LN{i:03d}" for i in range(100))
        code, out, err = self._run_on_tty(
            ["work", "submit", "--thread-id", "thread-1", "--task", "do it"],
            self._handler({"work_submit": self._submit_result(response)}),
            no_color=True,
        )
        self.assertEqual(code, 0, err)
        self.assertIn("LN099", out)
        self.assertNotIn("全文见", out)

    def test_work_get_message_keeps_multiline(self):
        snapshot = {
            "id": "thread-1",
            "title": "T",
            "created_at": "2026-10-19T05:00:00Z",
            "updated_at": "2026-10-19T06:00:00Z",
            "messages": [
                {
                    "created_at": "2026-10-19T05:02:00Z",
                    "role": "assistant",
                    "text": "第一段\n\n第二段\n- 列表项",
                },
            ],
        }
        code, out, err = self._run(
            ["work", "get", "--thread-id", "thread-1"],
            self._handler({"work_get": snapshot}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("  第一段\n  \n  第二段\n  - 列表项", out)

    def test_timeline_long_text_full_on_non_tty(self):
        entry = {
            "at": "2026-10-21T10:00:00Z",
            "kind": "message",
            "from_author": "agent-a",
            "text": "\n".join(f"TL{i:03d}" for i in range(70)),
        }
        code, out, err = self._run(
            ["team", "timeline", "--thread-id", "thread-1"],
            self._handler(
                {
                    "team_timeline": {
                        "team_id": "team-1",
                        "members": [],
                        "entries": [entry],
                    }
                }
            ),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("TL069", out)
        self.assertNotIn("仅显示前", out)

    def test_timeline_long_text_truncates_on_tty(self):
        entry = {
            "at": "2026-10-21T10:00:00Z",
            "kind": "message",
            "from_author": "agent-a",
            "text": "\n".join(f"TL{i:03d}" for i in range(70)),
        }
        code, out, err = self._run_on_tty(
            ["team", "timeline", "--thread-id", "thread-1"],
            self._handler(
                {
                    "team_timeline": {
                        "team_id": "team-1",
                        "members": [],
                        "entries": [entry],
                    }
                }
            ),
        )
        self.assertEqual(code, 0, err)
        self.assertNotIn("TL060", out)
        self.assertIn("仅显示前 60 行", out)


class ZnCliApprovalUxT23Tests(_CliHarness):
    """T2-3: two-line approval cards, ``approval show``, human errors."""

    def _approval_result(self):
        return {
            "pending": [
                {
                    "request_id": "req-pending",
                    "status": "pending",
                    "action_kind": "send",
                    "target": "someone",
                    "scope": "chat",
                    "source": "resident",
                    "value_text": "Send the weekly report to the team channel.",
                    "created_at": "2026-10-21T19:00:00Z",
                    "expires_at": "2026-10-21T20:00:00Z",
                }
            ],
            "denied": [
                {
                    "request_id": "req-denied",
                    "status": "denied",
                    "action_kind": "purchase",
                    "target": "example store",
                    "scope": "shopping",
                    "decision": "deny",
                    "decided_at": "2026-10-21T18:30:00Z",
                    "created_at": "2026-10-21T18:00:00Z",
                    "expires_at": "",
                }
            ],
            "expired": [],
            "applied": [
                {
                    "request_id": "req-applied",
                    "status": "applied",
                    "action_kind": "send",
                    "target": "someone",
                    "scope": "chat",
                    "decision": "allow_once",
                    "decided_at": "2026-10-21T17:00:00Z",
                    "created_at": "2026-10-21T16:00:00Z",
                    "expires_at": "",
                }
            ],
        }

    def test_list_two_line_cards_three_states(self):
        code, out, err = self._run(
            ["approval", "list", "--status", "all"],
            self._handler({"approval_list": self._approval_result()}),
        )
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        heads = {
            "req-pending": "send",
            "req-denied": "purchase",
            "req-applied": "send",
        }
        for request_id, kind in heads.items():
            head = next(
                i
                for i, line in enumerate(lines)
                if line.startswith(f"{request_id}  [")
            )
            self.assertIn(kind, lines[head])
            detail = lines[head + 1]
            self.assertTrue(detail.startswith("  "), detail)
            self.assertIn("target=", detail)
            self.assertIn("scope=", detail)
            self.assertIn("expires=", detail)
        # only the pending card carries the waited= duration
        pending_head = next(
            i for i, line in enumerate(lines) if line.startswith("req-pending  [")
        )
        self.assertIn("waited=", lines[pending_head + 1])
        for request_id in ("req-denied", "req-applied"):
            head = next(
                i for i, line in enumerate(lines) if line.startswith(f"{request_id}  [")
            )
            self.assertNotIn("waited=", lines[head + 1])
        # piped (non-TTY) output carries no escape codes
        self.assertNotIn("\x1b[", out)

    def test_list_waited_exact_duration(self):
        now = datetime(2026, 10, 21, 21, 15, 0, tzinfo=timezone.utc)
        card = _format_approval_card(
            {
                "request_id": "req-1",
                "status": "pending",
                "action_kind": "send",
                "target": "t",
                "scope": "s",
                "created_at": "2026-10-21T19:00:00Z",
                "expires_at": "",
            },
            now=now,
        )
        self.assertIn("waited=2h 15m", card)

    def test_list_waited_absent_without_created_at(self):
        card = _format_approval_card(
            {
                "request_id": "req-1",
                "status": "pending",
                "action_kind": "send",
                "target": "t",
                "scope": "s",
                "expires_at": "",
            }
        )
        self.assertNotIn("waited=", card)

    def test_list_waited_absent_for_garbled_created_at(self):
        card = _format_approval_card(
            {
                "request_id": "req-1",
                "status": "pending",
                "action_kind": "send",
                "target": "t",
                "scope": "s",
                "created_at": "not-a-time",
                "expires_at": "",
            }
        )
        self.assertNotIn("waited=", card)

    def test_list_card_color_modes(self):
        from zn_agent.core import cli_format

        item = {
            "request_id": "req-1",
            "status": "pending",
            "action_kind": "send",
            "target": "t",
            "scope": "s",
            "created_at": "2026-10-21T19:00:00Z",
            "expires_at": "",
        }
        now = datetime(2026, 10, 21, 19, 30, 0, tzinfo=timezone.utc)
        env = dict(os.environ)
        env.pop("NO_COLOR", None)
        env["TERM"] = "xterm-256color"
        with mock.patch.object(cli_format, "is_tty", return_value=True), mock.patch.dict(
            "os.environ", env, clear=True
        ):
            colored = _format_approval_card(item, now=now)
        self.assertIn("\x1b[33mpending\x1b[0m", colored)
        self.assertIn("waited=30m", colored)
        env["NO_COLOR"] = "1"
        with mock.patch.object(cli_format, "is_tty", return_value=True), mock.patch.dict(
            "os.environ", env, clear=True
        ):
            plain = _format_approval_card(item, now=now)
        self.assertNotIn("\x1b[", plain)
        self.assertIn("pending", plain)
        self.assertIn("waited=30m", plain)

    def test_show_full_detail(self):
        code, out, err = self._run(
            ["approval", "show", "req-pending"],
            self._handler({"approval_list": self._approval_result()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("审批卡 req-pending", out)
        self.assertIn("send", out)
        self.assertIn("someone", out)
        self.assertIn("内容摘要", out)
        self.assertIn("weekly report", out)
        self.assertIn("已等待", out)
        self.assertIn("zn approval decide --request-id req-pending", out)
        self.assertEqual(self.calls, [("approval_list", {})])

    def test_show_denied_card_shows_decision(self):
        code, out, err = self._run(
            ["approval", "show", "req-denied"],
            self._handler({"approval_list": self._approval_result()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("决定", out)
        self.assertIn("deny", out)
        self.assertIn("决定时间", out)

    def test_show_missing_id_human_error(self):
        code, out, err = self._run(
            ["approval", "show", "req-nope"],
            self._handler({"approval_list": self._approval_result()}),
        )
        self.assertEqual(code, 1)
        self.assertIn("zn: error:", err)
        self.assertIn("找不到审批卡", err)
        self.assertIn("req-nope", err)
        self.assertIn("zn approval list --status all", err)

    def test_show_empty_request_id_rejected(self):
        with self.assertRaises(SystemExit) as caught:
            run(
                [
                    "--endpoint",
                    str(self.endpoint_path),
                    "approval",
                    "show",
                    "",
                ]
            )
        self.assertEqual(caught.exception.code, 2)
        self.assertFalse(hasattr(self, "calls"))  # argparse rejected before any RPC

    def test_show_json_byte_exact(self):
        result = self._approval_result()
        card = result["pending"][0]
        code, out, _ = self._run(
            ["approval", "show", "req-pending", "--json"],
            self._handler({"approval_list": result}),
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            out, json.dumps(card, ensure_ascii=False, indent=2, default=str) + "\n"
        )

    def test_list_json_unchanged(self):
        result = self._approval_result()
        code, out, _ = self._run(
            ["approval", "list", "--json"],
            self._handler({"approval_list": result}),
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), result)


class ZnCliWorkSubmitProgressTests(_CliHarness):
    """T2-2: `zn work submit` streams work_progress while the submit RPC runs.

    The blocking work_submit RPC keeps its historic semantics (it stays the
    source of truth for the final result); the CLI only *observes* via the
    read-only work_get (active_run discovery) + work_progress RPCs.
    """

    _FINAL_RESULT = {
        "thread": {"id": "thread-1", "title": "T"},
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

    def _progress(self, stage, **overrides):
        payload = {
            "event_id": "ev-1",
            "thread_id": "thread-1",
            "stage": stage,
            "status": "active",
            "terminal": False,
            "finalized": False,
            "next_action": "thinking hard",
            "model_invocations": 1,
        }
        payload.update(overrides)
        return payload

    def _scripted_handler(self, release, progress_scripts, interrupt_on_progress=False):
        calls_lock = threading.Lock()
        state = {"progress_calls": 0}

        def handle(method, params):
            with calls_lock:
                self.calls.append((method, params))
            if method == "work_submit":
                assert release.wait(timeout=15), "work_submit was not released"
                return dict(self._FINAL_RESULT)
            if method == "work_get":
                return {
                    "id": "thread-1",
                    "title": "T",
                    "active_run": {"thread_id": "thread-1", "event_id": "ev-1"},
                    "messages": [],
                }
            if method == "work_progress":
                if interrupt_on_progress:
                    raise KeyboardInterrupt("simulated ctrl-c")
                with calls_lock:
                    state["progress_calls"] += 1
                    n = state["progress_calls"]
                if n < len(progress_scripts):
                    return {"progress": dict(progress_scripts[n - 1])}
                release.set()
                return {"progress": dict(progress_scripts[-1])}
            raise AssertionError(f"unexpected RPC method {method!r}")

        self.calls = []
        return handle

    def _patch_timings(self):
        for name, value in (
            ("_WORK_SUBMIT_GRACE_SECONDS", 0.02),
            ("_WORK_POLL_INTERVAL_SECONDS", 0.02),
            ("_WORK_NONTTY_HEARTBEAT_SECONDS", 0.02),
        ):
            patcher = mock.patch(f"zn_agent.core.zn_cli.{name}", value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _run_submit(self, handler):
        self._patch_connect(handler)
        self._patch_timings()
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = run(
                [
                    "--endpoint", str(self.endpoint_path),
                    "work", "submit",
                    "--thread-id", "thread-1",
                    "--task", "do the thing",
                ]
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_slow_submit_streams_progress_then_final(self):
        release = threading.Event()
        self.addCleanup(release.set)
        scripts = [
            self._progress("planning"),
            self._progress("executing"),
            self._progress(
                "complete",
                status="completed",
                terminal=True,
                finalized=True,
                execution_path="direct",
                model_invocations=2,
                next_action="",
            ),
        ]
        code, out, err = self._run_submit(self._scripted_handler(release, scripts))
        self.assertEqual(code, 0, err)
        self.assertIn("submitted to thread thread-1  (T)", out)
        # non-TTY: plain interval status lines, no spinner escape codes
        self.assertNotIn("\x1b[", out)
        self.assertIn("progress thread=thread-1 event=ev-1", out)
        self.assertIn("stage=planning", out)
        self.assertIn("stage=executing", out)
        # final summary keeps the pre-T2-2 format
        self.assertIn(
            "run event=ev-1  success=True  cancelled=False  path=direct  "
            "model_invocations=2",
            out,
        )
        self.assertIn("finished", out)
        methods = [method for method, _ in self.calls]
        self.assertIn("work_submit", methods)
        self.assertIn("work_get", methods)
        self.assertIn("work_progress", methods)
        self.assertLess(methods.index("work_get"), methods.index("work_progress"))
        for method, params in self.calls:
            if method == "work_progress":
                self.assertEqual(params["thread_id"], "thread-1")
                self.assertEqual(params["event_id"], "ev-1")

    def test_tty_shows_stage_transitions_and_spinner(self):
        release = threading.Event()
        self.addCleanup(release.set)
        scripts = [
            self._progress("planning"),
            self._progress("executing"),
            self._progress(
                "complete",
                status="completed",
                terminal=True,
                finalized=True,
                execution_path="direct",
                model_invocations=2,
                next_action="",
            ),
        ]
        self._patch_connect(self._scripted_handler(release, scripts))
        self._patch_timings()

        class _Tty(io.StringIO):
            def isatty(self):
                return True

        tty, stderr = _Tty(), io.StringIO()
        env = {key: value for key, value in os.environ.items() if key != "NO_COLOR"}
        env["TERM"] = "xterm-256color"
        with mock.patch.dict(os.environ, env, clear=True):
            with contextlib.redirect_stdout(tty), contextlib.redirect_stderr(stderr):
                code = run(
                    [
                        "--endpoint", str(self.endpoint_path),
                        "work", "submit",
                        "--thread-id", "thread-1",
                        "--task", "do the thing",
                    ]
                )
        out = tty.getvalue()
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertIn("\x1b[", out)  # colors on in TTY mode
        self.assertIn("\u2026", out)  # pending spinner symbol
        self.assertIn("stage:", out)  # stage transition line
        self.assertIn("submitted to thread thread-1  (T)", out)
        self.assertIn("run event=ev-1  success=True", out)

    def test_interrupt_stops_watching_without_cancelling(self):
        release = threading.Event()
        self.addCleanup(release.set)
        handler = self._scripted_handler(
            release, [self._progress("planning")], interrupt_on_progress=True
        )
        code, out, err = self._run_submit(handler)
        self.assertEqual(code, 1)
        self.assertIn("zn: error: interrupted:", err)
        self.assertIn("keeps running", err)
        self.assertIn("zn work cancel --thread-id thread-1 --event-id ev-1", err)
        # the CLI never cancels on Ctrl-C: no work_cancel call went out
        self.assertNotIn("work_cancel", [method for method, _ in self.calls])

    def test_submit_rpc_error_surfaces_unchanged(self):
        def handle(method, params):
            self.calls.append((method, params))
            if method == "work_submit":
                return (False, None, "kaput")
            raise AssertionError(f"unexpected RPC method {method!r}")

        self.calls = []
        code, out, err = self._run_submit(handle)
        self.assertEqual(code, 1)
        self.assertIn("zn: error:", err)
        self.assertIn("kaput", err)
        # the RPC failed before any polling could start
        self.assertNotIn("work_progress", [method for method, _ in self.calls])


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


class ZnCliAutonomySuggestionsTests(_CliHarness):
    def test_autonomy_list_prints_levels(self):
        levels = [
            {
                "domain": "connector.weather",
                "level": "suggest",
                "updated_at": "2026-10-21T10:00:00Z",
            },
            {
                "domain": "recurring.interval",
                "level": "observe_only",
                "updated_at": "2026-10-21T09:00:00Z",
            },
        ]
        code, out, err = self._run(
            ["autonomy", "list"], self._handler({"autonomy_list": levels})
        )
        self.assertEqual(code, 0, err)
        self.assertIn("connector.weather", out)
        self.assertIn("suggest", out)
        self.assertIn("observe_only", out)
        self.assertEqual(self.calls, [("autonomy_list", {})])

    def test_autonomy_list_empty_and_json(self):
        code, out, err = self._run(
            ["autonomy", "list"], self._handler({"autonomy_list": []})
        )
        self.assertEqual(code, 0, err)
        self.assertIn("require_approval", out)

        code, out, err = self._run(
            ["autonomy", "list", "--json"], self._handler({"autonomy_list": []})
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), [])

    def test_autonomy_get_prints_level(self):
        code, out, err = self._run(
            ["autonomy", "get", "connector.weather"],
            self._handler(
                {
                    "autonomy_get": {
                        "domain": "connector.weather",
                        "level": "observe_only",
                    }
                }
            ),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("connector.weather", out)
        self.assertIn("observe_only", out)
        self.assertEqual(
            self.calls, [("autonomy_get", {"domain": "connector.weather"})]
        )

    def test_autonomy_get_requires_domain_without_rpc(self):
        with self.assertRaises(SystemExit) as caught:
            run(["--endpoint", str(self.endpoint_path), "autonomy", "get"])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.connect_calls, [])

    def test_autonomy_set_sends_domain_and_level(self):
        result = {
            "domain": "connector.weather",
            "level": "suggest",
            "old_level": "require_approval",
            "updated_at": "2026-10-21T10:00:00Z",
        }
        code, out, err = self._run(
            ["autonomy", "set", "connector.weather", "suggest"],
            self._handler({"autonomy_set": result}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("connector.weather", out)
        self.assertIn("suggest", out)
        self.assertIn("require_approval", out)
        self.assertEqual(
            self.calls,
            [("autonomy_set", {"domain": "connector.weather", "level": "suggest"})],
        )

    def test_autonomy_set_json(self):
        result = {
            "domain": "connector.weather",
            "level": "suggest",
            "old_level": "require_approval",
            "updated_at": "2026-10-21T10:00:00Z",
        }
        code, out, err = self._run(
            ["autonomy", "set", "connector.weather", "suggest", "--json"],
            self._handler({"autonomy_set": result}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), result)

    def test_autonomy_set_illegal_level_surfaces_resident_rejection(self):
        code, _, err = self._run(
            ["autonomy", "set", "connector.weather", "yolo"],
            self._handler(
                {"autonomy_set": (False, None, "unknown autonomy level: 'yolo'")}
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("unknown autonomy level", err)

    def test_suggestions_list_prints_suggestions(self):
        items = [
            {"key": "sug-1", "kind": "work", "title": "Finish the report"},
            {"key": "sug-2", "kind": "recurring", "title": "Check the garden"},
        ]
        code, out, err = self._run(
            ["suggestions", "list"], self._handler({"suggestions_list": items})
        )
        self.assertEqual(code, 0, err)
        self.assertIn("sug-1", out)
        self.assertIn("Finish the report", out)
        self.assertIn("sug-2", out)
        self.assertEqual(self.calls, [("suggestions_list", {"limit": 8})])

    def test_suggestions_list_limit_flag_and_json(self):
        items = [{"key": "sug-1", "kind": "work", "title": "Finish the report"}]
        code, out, err = self._run(
            ["suggestions", "list", "--limit", "3", "--json"],
            self._handler({"suggestions_list": items}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(self.calls, [("suggestions_list", {"limit": 3})])
        self.assertEqual(json.loads(out), items)

    def test_suggestions_list_empty(self):
        code, out, err = self._run(
            ["suggestions", "list"], self._handler({"suggestions_list": []})
        )
        self.assertEqual(code, 0, err)
        self.assertIn("no suggestions", out)

    def test_suggestions_dismiss_calls_rpc(self):
        result = {
            "dismissed": True,
            "key": "sug-1",
            "dismissed_at": "2026-10-21T10:00:00Z",
            "expires_at": "2026-10-28T10:00:00Z",
        }
        code, out, err = self._run(
            ["suggestions", "dismiss", "--key", "sug-1"],
            self._handler({"suggestions_dismiss": result}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("sug-1", out)
        self.assertEqual(self.calls, [("suggestions_dismiss", {"key": "sug-1"})])

    def test_suggestions_dismiss_requires_key_without_rpc(self):
        with self.assertRaises(SystemExit) as caught:
            run(["--endpoint", str(self.endpoint_path), "suggestions", "dismiss"])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.connect_calls, [])


class ZnCliHumanizedErrorsT25Tests(_CliHarness):
    """T2-5: every error mapping renders the new humanized copy.

    Copy-change trace (CONSTRAINTS.md §3): T2-5 intentionally replaces the
    CLI's raw English error strings with humanized copy ("what happened +
    what to do next"). The seven pre-existing assertions on the old copy
    are kept verbatim (no test modification): the new copy retains the
    original English fragments as technical details in parentheses, so the
    old assertions still pin the same behavior. The new humanized copy is
    additionally pinned by the tests in this class.
    """

    def _run_stderr(self, argv):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = run(["--endpoint", str(self.endpoint_path), *argv])
        return code, stderr.getvalue()

    def test_endpoint_missing_humanized(self):
        missing = Path(self.tmp.name) / "no-such-endpoint.json"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = run(["--endpoint", str(missing), "work", "list"])
        err = stderr.getvalue()
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("zn: error:"))
        self.assertIn("ZN 常驻服务没在运行", err)
        self.assertIn("找不到 endpoint 文件", err)
        self.assertIn("下一步", err)
        self.assertIn("ZN_HOME", err)

    def test_endpoint_malformed_humanized(self):
        self.endpoint_path.write_text("{not json", encoding="utf-8")
        code, err = self._run_stderr(["work", "list"])
        self.assertEqual(code, 1)
        self.assertIn("ZN 常驻服务没在运行", err)
        self.assertIn("无法解析为 JSON", err)
        self.assertIn("下一步", err)

    def test_endpoint_not_object_humanized(self):
        self.endpoint_path.write_text("[1, 2]", encoding="utf-8")
        code, err = self._run_stderr(["work", "list"])
        self.assertEqual(code, 1)
        self.assertIn("ZN 常驻服务没在运行", err)
        self.assertIn("不是 JSON 对象", err)

    def test_endpoint_bad_port_humanized(self):
        for bad_port in (99999, "abc", 0):
            with self.subTest(bad_port=bad_port):
                self.endpoint_path.write_text(
                    json.dumps(_endpoint_payload(port=bad_port)), encoding="utf-8"
                )
                code, err = self._run_stderr(["work", "list"])
                self.assertEqual(code, 1)
                self.assertIn("ZN 常驻服务没在运行", err)
                self.assertIn("端口非法", err)
                self.assertIn("下一步", err)

    def test_endpoint_stale_humanized_next_step(self):
        self.endpoint_path.write_text(
            json.dumps(_endpoint_payload(pid=424242)), encoding="utf-8"
        )
        with (
            mock.patch("os.kill", side_effect=ProcessLookupError("no such process")),
            mock.patch("socket.create_connection") as connect,
        ):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = run(["--endpoint", str(self.endpoint_path), "work", "list"])
        err = stderr.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("已过期", err)
        self.assertIn("424242", err)
        self.assertIn("下一步", err)
        connect.assert_not_called()

    def test_endpoint_bad_version_humanized(self):
        self.endpoint_path.write_text(
            json.dumps(_endpoint_payload(version=1)), encoding="utf-8"
        )
        code, err = self._run_stderr(["work", "list"])
        self.assertEqual(code, 1)
        self.assertIn("版本不一致", err)
        self.assertIn("下一步", err)

    def test_endpoint_bad_transport_humanized(self):
        self.endpoint_path.write_text(
            json.dumps(_endpoint_payload(transport="udp")), encoding="utf-8"
        )
        code, err = self._run_stderr(["work", "list"])
        self.assertEqual(code, 1)
        self.assertIn("传输方式不受支持", err)

    def test_endpoint_bad_auth_scheme_humanized(self):
        self.endpoint_path.write_text(
            json.dumps(
                _endpoint_payload(
                    authentication={"scheme": "none", "secret": "x" * 64}
                )
            ),
            encoding="utf-8",
        )
        code, err = self._run_stderr(["work", "list"])
        self.assertEqual(code, 1)
        self.assertIn("认证方式不受支持", err)

    def test_endpoint_bad_secret_humanized(self):
        self.endpoint_path.write_text(
            json.dumps(
                _endpoint_payload(
                    authentication={"scheme": "session-secret-v1", "secret": "short"}
                )
            ),
            encoding="utf-8",
        )
        code, err = self._run_stderr(["work", "list"])
        self.assertEqual(code, 1)
        self.assertIn("会话密钥缺失或过短", err)

    def test_endpoint_non_loopback_humanized_next_step(self):
        self.endpoint_path.write_text(
            json.dumps(_endpoint_payload(host="192.168.1.10")), encoding="utf-8"
        )
        with mock.patch("socket.create_connection") as connect:
            code, err = self._run_stderr(["work", "list"])
        self.assertEqual(code, 1)
        self.assertIn("只允许本机", err)
        self.assertIn("下一步", err)
        connect.assert_not_called()

    def test_connect_timeout_humanized(self):
        with mock.patch(
            "socket.create_connection", side_effect=TimeoutError("timed out")
        ):
            code, err = self._run_stderr(["work", "list"])
        self.assertEqual(code, 1)
        self.assertIn("连不上 ZN 常驻服务", err)
        self.assertIn("稍后重试", err)
        self.assertIn("下一步", err)

    def test_connect_refused_humanized_next_step(self):
        with mock.patch(
            "socket.create_connection",
            side_effect=ConnectionRefusedError("refused"),
        ):
            code, err = self._run_stderr(["work", "list"])
        self.assertEqual(code, 1)
        self.assertIn("连不上 ZN 常驻服务", err)
        self.assertIn("稍后重试", err)
        self.assertIn("下一步", err)
        self.assertIn("refused", err)  # raw OS error is preserved

    def test_connection_lost_mid_rpc_humanized(self):
        def handler(method, params):
            raise OSError("broken pipe")

        code, _, err = self._run(["work", "list"], handler)
        self.assertEqual(code, 1)
        self.assertIn("请求中途断开", err)
        self.assertIn("work_list", err)
        self.assertIn("下一步", err)

    def test_auth_failed_humanized(self):
        def handler(method, params):
            return {"authenticated": False}

        def connect(address, timeout=None):
            fake = _FakeSocket(handler)
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
            code, err = self._run_stderr(["work", "list"])
        self.assertEqual(code, 1)
        self.assertIn("认证失败", err)
        self.assertIn("authentication failed", err)  # server reason passes through
        self.assertIn("下一步", err)

    def test_rpc_rejected_gets_category_prefix(self):
        code, _, err = self._run(
            ["work", "list"],
            self._handler({"work_list": (False, None, "thread not found")}),
        )
        self.assertEqual(code, 1)
        self.assertIn("服务端返回错误", err)
        self.assertIn("thread not found", err)  # server message passes through

    def test_response_closed_humanized(self):
        def connect(address, timeout=None):
            fake = _FakeSocket(lambda method, params: {})
            original = fake.sendall

            def sendall(data):
                original(data)
                fake.stream.lines.clear()

            fake.sendall = sendall
            return fake

        with mock.patch("socket.create_connection", side_effect=connect):
            code, err = self._run_stderr(["work", "list"])
        self.assertEqual(code, 1)
        self.assertIn("关闭了连接", err)
        self.assertIn("下一步", err)

    def test_response_bad_json_humanized(self):
        def connect(address, timeout=None):
            fake = _FakeSocket(lambda method, params: {})
            original = fake.sendall

            def sendall(data):
                original(data)
                request = json.loads(data.decode("utf-8").splitlines()[-1])
                if request.get("method") != "authenticate":
                    fake.stream.lines = [b"not json{{{\n"]

            fake.sendall = sendall
            return fake

        with mock.patch("socket.create_connection", side_effect=connect):
            code, err = self._run_stderr(["work", "list"])
        self.assertEqual(code, 1)
        self.assertIn("不是合法 JSON", err)

    def test_unexpected_result_humanized_hides_raw_by_default(self):
        code, _, err = self._run(
            ["work", "list"],
            self._handler({"work_list": {"wrong": "shape", "marker": "RAW42"}}),
        )
        self.assertEqual(code, 1)
        self.assertIn("无法识别的结果", err)
        self.assertIn("版本可能不一致", err)
        self.assertIn("下一步", err)
        self.assertNotIn("RAW42", err)

    def test_unexpected_result_verbose_shows_raw(self):
        code, _, err = self._run(
            ["--verbose", "work", "list"],
            self._handler({"work_list": {"wrong": "shape", "marker": "RAW42"}}),
        )
        self.assertEqual(code, 1)
        self.assertIn("无法识别的结果", err)
        self.assertIn("原始内容", err)
        self.assertIn("RAW42", err)

    def test_unexpected_result_zn_debug_env_shows_raw(self):
        with mock.patch.dict(os.environ, {"ZN_DEBUG": "1"}):
            code, _, err = self._run(
                ["work", "list"],
                self._handler({"work_list": {"wrong": "shape", "marker": "RAW42"}}),
            )
        self.assertEqual(code, 1)
        self.assertIn("原始内容", err)
        self.assertIn("RAW42", err)

    def test_verbose_flag_does_not_leak_into_next_run(self):
        handler = self._handler({"work_list": {"wrong": "shape"}})
        self._run(["--verbose", "work", "list"], handler)
        _, _, err = self._run(["work", "list"], handler)
        self.assertNotIn("原始内容", err)

    def test_unexpected_result_unit_gating(self):
        _set_error_details(False)
        try:
            err = _unexpected_result("work_list", {"a": 1})
            self.assertNotIn("{'a': 1}", str(err))
            self.assertIn("无法识别的结果", str(err))
            _set_error_details(True)
            err = _unexpected_result("work_list", {"a": 1})
            self.assertIn("原始内容", str(err))
        finally:
            _set_error_details(False)

    def test_verbose_flag_parses(self):
        args = build_parser().parse_args(["--verbose", "work", "list"])
        self.assertTrue(args.verbose)
        args = build_parser().parse_args(["work", "list"])
        self.assertFalse(args.verbose)

    def test_error_copy_table_renders(self):
        import string

        from zn_agent.core import zn_cli

        for key, (lead, next_step) in zn_cli._ERROR_COPY.items():
            with self.subTest(key=key):
                fields = {
                    fname: "X"
                    for _, fname, _, _ in string.Formatter().parse(lead)
                    if fname
                }
                err = _cli_error(key, **fields)
                text = str(err)
                self.assertTrue(text)
                if next_step:
                    self.assertIn("下一步", text)

    def test_exit_code_contract_unchanged(self):
        # exit 1 on business failure (resident down), exit 2 on bad args.
        missing = Path(self.tmp.name) / "no-such-endpoint.json"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = run(["--endpoint", str(missing), "work", "list"])
        self.assertEqual(code, 1)
        with self.assertRaises(SystemExit) as caught:
            run(["--endpoint", str(self.endpoint_path), "work", "list", "--limit", "0"])
        self.assertEqual(caught.exception.code, 2)


class ZnCliStatusT26Tests(_CliHarness):
    """T2-6: ``zn status`` aggregate command.

    Six rows (resident / summary / model / connectors / approvals /
    autonomy), red highlighting + subcommand hints for abnormal rows,
    offline degradation with unreachable markers, and ``--json`` output.
    """

    def _route_report(self, **overrides):
        from zn_agent.core.model_check import ModelCheckReport, RouteCheckResult

        results = overrides.pop(
            "results",
            (
                RouteCheckResult("r1", "deepseek", "deepseek-chat", True, 0.10, ""),
                RouteCheckResult("r2", "deepseek", "deepseek-reasoner", True, 0.20, ""),
            ),
        )
        return ModelCheckReport(
            configured=overrides.pop("configured", True),
            config_error=None,
            results=results,
        )

    def _stub_probe(self, report):
        patcher = mock.patch(
            "zn_agent.core.zn_cli.check_model_routes", return_value=report
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _stub_connector_eval(self, items):
        patcher = mock.patch(
            "zn_agent.core.connector_autoattach.evaluate_connector_status",
            return_value=items,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _mapping(self):
        return {
            "ping": {"alive": True, "pulse_count": 7},
            "status": {
                "identity": {"name": "ZN", "version": "0.1.0"},
                "model_dependency": {"model_invocations": 12},
            },
            "connector_status": {
                "generated_at": "2026-10-21T23:00:00Z",
                "mounted": 2,
                "approved": 3,
                "connectors": [
                    {"name": "search", "r_series": "R1", "mounted": True,
                     "approved": True, "reason": ""},
                    {"name": "rss", "r_series": "R2", "mounted": True,
                     "approved": True, "reason": ""},
                    {"name": "mail", "r_series": "R9", "mounted": False,
                     "approved": True, "reason": "needs auth"},
                ],
            },
            "approval_list": {
                "pending": [{"request_id": "a1"}, {"request_id": "a2"}],
                "denied": [],
                "expired": [],
                "applied": [],
            },
            "autonomy_list": [
                {"domain": "connector.mail", "level": "require_approval"},
                {"domain": "recurring.interval", "level": "execute_reversible"},
            ],
        }

    def _run_on_tty(self, argv, handler):
        self._patch_connect(handler)

        class _Tty(io.StringIO):
            def isatty(self):
                return True

        tty, stderr = _Tty(), io.StringIO()
        env = {key: value for key, value in os.environ.items() if key != "NO_COLOR"}
        env["TERM"] = "xterm-256color"
        with mock.patch.dict(os.environ, env, clear=True):
            with contextlib.redirect_stdout(tty), contextlib.redirect_stderr(stderr):
                code = run(["--endpoint", str(self.endpoint_path), *argv])
        return code, tty.getvalue(), stderr.getvalue()

    def test_status_rows_all_present(self):
        self._stub_probe(self._route_report())
        code, out, _ = self._run(["status"], self._handler(self._mapping()))
        self.assertEqual(code, 0)
        for label in (
            "resident",
            "summary",
            "model",
            "connectors",
            "approvals",
            "autonomy",
        ):
            self.assertIn(label, out)
        self.assertIn("pulse_count=7", out)
        self.assertIn("model_invocations=12", out)
        self.assertIn("2 of 2 route(s) reachable", out)
        self.assertIn("2 of 3 mounted, 1 failed", out)
        self.assertIn("zn connector status", out)
        self.assertIn("2 pending", out)
        self.assertIn("zn approval list", out)
        self.assertIn("2 explicit domain(s)", out)
        self.assertIn("zn autonomy list", out)

    def test_status_tty_highlights_abnormal_rows_and_hints(self):
        # failed connector -> red; pending approvals -> warning yellow.
        self._stub_probe(self._route_report())
        code, out, _ = self._run_on_tty(
            ["status"], self._handler(self._mapping())
        )
        self.assertEqual(code, 0)
        self.assertIn("\033[31m", out)  # err red on the connector row
        self.assertIn("\033[33m", out)  # warn yellow on the approvals row
        self.assertIn("zn connector status", out)
        self.assertIn("zn approval list", out)

    def test_status_tty_model_unreachable_is_red_with_hint(self):
        from zn_agent.core.model_check import RouteCheckResult

        self._stub_probe(
            self._route_report(
                results=(
                    RouteCheckResult("r1", "deepseek", "deepseek-chat", False, None,
                                     "dial timeout"),
                )
            )
        )
        code, out, _ = self._run_on_tty(
            ["status"], self._handler(self._mapping())
        )
        self.assertEqual(code, 0)
        self.assertIn("0 of 1 route(s) reachable", out)
        self.assertIn("\033[31m", out)
        self.assertIn("zn model check", out)

    def test_status_offline_marks_unreachable_and_still_reports(self):
        def refused(method, params):
            raise socket.error("connection refused")

        self._stub_probe(self._route_report())
        self._stub_connector_eval(
            [
                {
                    "approved": True,
                    "name": "mail",
                    "r_series": "R9",
                    "last_mount": {"mounted": False, "reason": "needs auth"},
                    "readiness": "will mount on next daemon start",
                },
                {
                    "approved": True,
                    "name": "search",
                    "r_series": "R1",
                    "last_mount": {"mounted": True, "reason": ""},
                    "readiness": "ok",
                },
            ]
        )
        code, out, _ = self._run(["status"], refused)
        self.assertEqual(code, 0)
        self.assertIn("unreachable", out)
        # local rows still report without a running resident
        self.assertIn("2 of 2 route(s) reachable", out)
        self.assertIn("local config evaluation", out)
        self.assertIn("1 failed", out)
        self.assertIn("zn connector status", out)

    def test_status_json_structure(self):
        self._stub_probe(self._route_report())
        code, out, _ = self._run(
            ["status", "--json"], self._handler(self._mapping())
        )
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["daemon_reachable"])
        self.assertNotIn("daemon_error", data)
        self.assertEqual(data["resident"]["pulse_count"], 7)
        self.assertEqual(data["summary"]["model_invocations"], 12)
        self.assertEqual(data["model"]["reachable_count"], 2)
        self.assertEqual(data["connectors"]["mounted"], 2)
        self.assertEqual(data["connectors"]["failed"], 1)
        self.assertFalse(data["connectors"]["local_evaluation"])
        self.assertEqual(data["approvals"]["pending"], 2)
        self.assertEqual(data["autonomy"]["explicit_domains"], 2)


    def test_status_offline_json(self):
        def refused(method, params):
            raise socket.error("connection refused")

        self._stub_probe(self._route_report())
        self._stub_connector_eval([])
        code, out, _ = self._run(["status", "--json"], refused)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertFalse(data["daemon_reachable"])
        self.assertIn("daemon_error", data)
        self.assertIsNone(data["resident"])
        self.assertIsNone(data["summary"])
        self.assertEqual(data["model"]["reachable_count"], 2)
        self.assertTrue(data["connectors"]["local_evaluation"])
        self.assertIsNone(data["approvals"]["pending"])
        self.assertIsNone(data["autonomy"]["explicit_domains"])


class ZnCliFirstRunHintT33Tests(unittest.TestCase):
    """T3-3: three-line onboarding hint appended at the end of ``run()``.

    The hint fires only when the ZN home is fresh (no
    ``kernel/resident-endpoint.json`` and no ``kernel`` data dir), the call
    is interactive (stdout is a TTY and ``--json`` was not passed), and only
    once per process. ``_cmd_*`` handlers stay unaware of it.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "fresh-home"
        self.home.mkdir()
        env = mock.patch.dict(os.environ, {"ZN_AGENT_HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        flag = mock.patch.object(_zn_cli_module, "_FIRST_RUN_HINT_SHOWN", False)
        flag.start()
        self.addCleanup(flag.stop)

    def _run_help(self, tty: bool):
        class _Tty(io.StringIO):
            def isatty(self):
                return True

        stdout, stderr = (_Tty() if tty else io.StringIO()), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = run(["help"])
        return code, stdout.getvalue()

    def test_fresh_home_tty_shows_hint_at_tail(self):
        code, out = self._run_help(tty=True)
        self.assertEqual(code, 0)
        self.assertEqual(
            out.splitlines()[-3:], list(_zn_cli_module._FIRST_RUN_HINT_LINES)
        )

    def test_fresh_home_pipe_no_hint(self):
        code, out = self._run_help(tty=False)
        self.assertEqual(code, 0)
        self.assertNotIn("①", out)

    def test_home_with_endpoint_and_kernel_dir_no_hint(self):
        kernel = self.home / "kernel"
        kernel.mkdir()
        (kernel / "resident-endpoint.json").write_text("{}", encoding="utf-8")
        code, out = self._run_help(tty=True)
        self.assertEqual(code, 0)
        self.assertNotIn("①", out)

    def test_home_with_kernel_dir_only_no_hint(self):
        # kernel dir alone already means the home is not fresh.
        (self.home / "kernel").mkdir()
        code, out = self._run_help(tty=True)
        self.assertEqual(code, 0)
        self.assertNotIn("①", out)

    def test_shown_only_once_per_process(self):
        _, first = self._run_help(tty=True)
        _, second = self._run_help(tty=True)
        self.assertEqual(first.count("①"), 1)
        self.assertEqual(second.count("①"), 0)

    def test_json_flag_suppresses_hint(self):
        class _Tty(io.StringIO):
            def isatty(self):
                return True

        stdout = _Tty()
        with contextlib.redirect_stdout(stdout):
            _zn_cli_module._maybe_print_first_run_hint(argparse.Namespace(json=True))
        self.assertEqual(stdout.getvalue(), "")

    def test_fresh_probe_is_read_only(self):
        # no kernel dir is created by the probe or the hint itself.
        self._run_help(tty=True)
        self.assertFalse((self.home / "kernel").exists())


class ZnCliNextHintT34Tests(_CliHarness):
    """T3-4: empty listings get one dim "what next" line on human terminals.

    Only when stdout is a real TTY with color allowed: ``--json`` mode,
    piped output, and ``NO_COLOR`` keep the historic single "no ..." line,
    byte for byte. Non-empty listings never get the hint.
    """

    def setUp(self) -> None:
        super().setUp()
        # T3-4 asserts byte-exact "no ..." lines, so the T3-3 first-run
        # probe must not leak into this output: point the home at a temp
        # dir that already holds kernel data (deterministically non-fresh).
        # No assertion is touched; this only removes ambient-home flakiness.
        t34_home = Path(self.tmp.name) / "zn-home"
        (t34_home / "kernel").mkdir(parents=True)
        home_env = mock.patch.dict(os.environ, {"ZN_AGENT_HOME": str(t34_home)})
        home_env.start()
        self.addCleanup(home_env.stop)

    _EMPTY_CASES = [
        (
            ["work", "list"],
            "work_list",
            "no work threads",
            "下一步：交办第一件事，运行 `zn work submit --task \"…\"`",
        ),
        (
            ["memory", "list"],
            "memory_list",
            "no remembered facts",
            "下一步：记住一件关于你的事，"
            "运行 `zn memory remember --key \"…\" --value \"…\"`",
        ),
        (
            ["team", "list"],
            "team_list",
            "no active teams",
            "下一步：交办一件事，团队会在任务里自动组建，"
            "运行 `zn work submit --task \"…\"`",
        ),
        (
            ["suggestions", "list"],
            "suggestions_list",
            "no suggestions",
            "下一步：看看 ZN 都会什么，运行 `zn help`",
        ),
    ]

    def _run_on_tty(self, argv, handler, no_color=False):
        self._patch_connect(handler)

        class _Tty(io.StringIO):
            def isatty(self):
                return True

        tty, stderr = _Tty(), io.StringIO()
        env = {key: value for key, value in os.environ.items() if key != "NO_COLOR"}
        if no_color:
            env["NO_COLOR"] = "1"
        env["TERM"] = "xterm-256color"
        with mock.patch.dict(os.environ, env, clear=True):
            with contextlib.redirect_stdout(tty), contextlib.redirect_stderr(stderr):
                code = run(["--endpoint", str(self.endpoint_path), *argv])
        return code, tty.getvalue(), stderr.getvalue()

    def test_empty_lists_print_hint_on_tty(self):
        for argv, method, empty_line, hint in self._EMPTY_CASES:
            with self.subTest(command=" ".join(argv)):
                code, out, err = self._run_on_tty(
                    argv, self._handler({method: []})
                )
                self.assertEqual(code, 0, err)
                self.assertIn(empty_line, out)
                self.assertIn(hint, out)

    def test_empty_lists_no_hint_on_pipe(self):
        for argv, method, empty_line, _hint in self._EMPTY_CASES:
            with self.subTest(command=" ".join(argv)):
                code, out, err = self._run(argv, self._handler({method: []}))
                self.assertEqual(code, 0, err)
                self.assertEqual(out, empty_line + "\n")
                self.assertNotIn("下一步", out)

    def test_empty_lists_no_hint_with_no_color_on_tty(self):
        code, out, err = self._run_on_tty(
            ["work", "list"], self._handler({"work_list": []}), no_color=True
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "no work threads\n")

    def test_empty_lists_no_hint_in_json_mode(self):
        for argv, method, _empty_line, _hint in self._EMPTY_CASES:
            with self.subTest(command=" ".join(argv)):
                code, out, err = self._run_on_tty(
                    [*argv, "--json"], self._handler({method: []})
                )
                self.assertEqual(code, 0, err)
                self.assertEqual(json.loads(out), [])
                self.assertNotIn("下一步", out)

    def test_non_empty_lists_never_get_hint(self):
        thread = {
            "id": "t-1",
            "title": "T",
            "updated_at": "2026-10-22",
            "messages": [],
            "active_run": None,
        }
        code, out, err = self._run_on_tty(
            ["work", "list"], self._handler({"work_list": [thread]})
        )
        self.assertEqual(code, 0, err)
        self.assertIn("t-1", out)
        self.assertNotIn("下一步", out)


class ZnCliApprovalRulesUndoT11Tests(_CliHarness):
    """T11: ``zn approval rules list|delete`` + ``zn approval undo``."""

    def _rules_result(self):
        return {
            "pending": [],
            "denied": [],
            "expired": [],
            "applied": [],
            "rules": [
                {
                    "rule_id": "rule-abc123",
                    "action_kind": "send",
                    "scope": "chat",
                    "effect": "auto_allow",
                    "created_at": "2026-10-20T08:00:00Z",
                    "enabled": True,
                },
                {
                    "rule_id": "rule-def456",
                    "action_kind": "publish",
                    "scope": "rss",
                    "effect": "ask_first",
                    "created_at": "2026-10-21T08:00:00Z",
                    "enabled": True,
                },
            ],
            "audit": [],
        }

    # -- rules list -----------------------------------------------------

    def test_rules_list_prints_rules(self):
        code, out, err = self._run(
            ["approval", "rules", "list"],
            self._handler({"approval_list": self._rules_result()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("--- approval rules (2) ---", out)
        self.assertIn("rule-abc123", out)
        self.assertIn("rule-def456", out)
        self.assertIn("always allow", out)  # auto_allow -> T2-7 word
        self.assertIn("ask_first", out)  # unknown effect passes through
        self.assertIn("scope=chat", out)
        self.assertEqual(self.calls, [("approval_list", {})])

    def test_rules_list_empty(self):
        result = self._rules_result()
        result["rules"] = []
        code, out, err = self._run(
            ["approval", "rules", "list"], self._handler({"approval_list": result})
        )
        self.assertEqual(code, 0, err)
        self.assertIn("no approval rules", out)

    def test_rules_list_json(self):
        code, out, err = self._run(
            ["approval", "rules", "list", "--json"],
            self._handler({"approval_list": self._rules_result()}),
        )
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["rule_id"], "rule-abc123")

    def test_rules_list_malformed_payload(self):
        result = self._rules_result()
        result["rules"] = "not-a-list"
        code, _, err = self._run(
            ["approval", "rules", "list"], self._handler({"approval_list": result})
        )
        self.assertEqual(code, 1)
        self.assertIn("无法识别", err)

    def test_rules_list_offline(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(["approval", "rules", "list"], refused)
        self.assertEqual(code, 0, err)
        self.assertIn("常驻服务未运行", out)
        self.assertIn("看不到审批规则列表", out)
        self.assertIn("下一步", out)

    def test_rules_list_offline_json(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(["approval", "rules", "list", "--json"], refused)
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertFalse(data["daemon_reachable"])
        self.assertEqual(data["rules"], [])

    # -- rules delete ---------------------------------------------------

    def test_rules_delete_success(self):
        code, out, err = self._run(
            ["approval", "rules", "delete", "rule-abc123"],
            self._handler({"approval_rule_delete": {"deleted": True}}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("已删除审批规则 rule-abc123", out)
        self.assertIn("不再生效", out)
        self.assertEqual(
            self.calls, [("approval_rule_delete", {"rule_id": "rule-abc123"})]
        )

    def test_rules_delete_json(self):
        code, out, err = self._run(
            ["approval", "rules", "delete", "rule-abc123", "--json"],
            self._handler({"approval_rule_delete": {"deleted": True}}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(
            json.loads(out), {"deleted": True, "rule_id": "rule-abc123"}
        )

    def test_rules_delete_unknown_rule_humanized(self):
        code, out, err = self._run(
            ["approval", "rules", "delete", "rule-nope"],
            self._handler(
                {
                    "approval_rule_delete": (
                        False,
                        None,
                        "ValueError: unknown approval rule",
                    )
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("找不到审批规则 'rule-nope'", err)
        self.assertIn("unknown approval rule", err)  # english kept in parens
        self.assertIn("zn approval rules list", err)

    def test_rules_delete_offline_claims_nothing(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(
            ["approval", "rules", "delete", "rule-abc123"], refused
        )
        self.assertEqual(code, 0, err)
        self.assertIn("常驻服务未运行", out)
        self.assertIn("没有删除任何审批规则", out)
        self.assertNotIn("已删除", out)

    # -- undo -----------------------------------------------------------

    def _undo_result(self, **overrides):
        result = {
            "request_id": "req-1",
            "path": "/home/user/workspace/report.md",
            "restored": True,
            "note": "file restored to pre-change snapshot",
            "pre_undo_checkpoint_id": "ckpt-9",
        }
        result.update(overrides)
        return result

    def test_undo_success_restored(self):
        code, out, err = self._run(
            ["approval", "undo", "req-1"],
            self._handler({"approval_undo": self._undo_result()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("req-1", out)
        self.assertIn("已撤销", out)
        self.assertIn("恢复到变更前", out)
        self.assertIn("/home/user/workspace/report.md", out)
        self.assertIn("ckpt-9", out)
        self.assertEqual(self.calls, [("approval_undo", {"request_id": "req-1"})])

    def test_undo_already_at_pre_change_state(self):
        code, out, err = self._run(
            ["approval", "undo", "req-1"],
            self._handler(
                {
                    "approval_undo": self._undo_result(
                        restored=False,
                        note="file was already at its pre-change state",
                    )
                }
            ),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("无需改动", out)
        self.assertIn("already at pre-change state", out)

    def test_undo_json(self):
        code, out, err = self._run(
            ["approval", "undo", "req-1", "--json"],
            self._handler({"approval_undo": self._undo_result()}),
        )
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["request_id"], "req-1")
        self.assertTrue(data["restored"])
        self.assertEqual(data["pre_undo_checkpoint_id"], "ckpt-9")

    def test_undo_unknown_request_humanized(self):
        code, out, err = self._run(
            ["approval", "undo", "req-nope"],
            self._handler(
                {
                    "approval_undo": (
                        False,
                        None,
                        "ValueError: unknown approval request: req-nope",
                    )
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("找不到审批卡 'req-nope'", err)
        self.assertIn("unknown approval request", err)
        self.assertIn("zn approval list --status applied", err)

    def test_undo_not_consumed_humanized(self):
        code, out, err = self._run(
            ["approval", "undo", "req-1"],
            self._handler(
                {
                    "approval_undo": (
                        False,
                        None,
                        "ValueError: only an applied (consumed) approval can be "
                        "undone; request req-1 is pending",
                    )
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("还不能撤销", err)
        self.assertIn("only consumed approvals can be undone", err)

    def test_undo_already_undone_humanized(self):
        code, out, err = self._run(
            ["approval", "undo", "req-1"],
            self._handler(
                {
                    "approval_undo": (
                        False,
                        None,
                        "ValueError: this approved change was already undone",
                    )
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("已经撤销过了", err)
        self.assertIn("already undone", err)

    def test_undo_offline_claims_nothing(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(["approval", "undo", "req-1"], refused)
        self.assertEqual(code, 0, err)
        self.assertIn("常驻服务未运行", out)
        self.assertIn("没有撤销任何变更", out)
        self.assertNotIn("已撤销", out)
