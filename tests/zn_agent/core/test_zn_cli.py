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

    # AP-1: zn approval decide --note -------------------------------------
    def test_approval_decide_deny_with_note_sends_note(self):
        result = {
            "request": {
                "request_id": "req-1",
                "status": "denied",
                "decision": "deny",
                "decision_note": "太贵了",
            }
        }
        code, out, err = self._run(
            [
                "approval",
                "decide",
                "--request-id",
                "req-1",
                "--deny",
                "--note",
                "太贵了",
            ],
            self._handler({"approval_decide": result}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("req-1", out)
        self.assertEqual(
            self.calls,
            [
                (
                    "approval_decide",
                    {
                        "request_id": "req-1",
                        "decision": "deny",
                        "note": "太贵了",
                    },
                )
            ],
        )

    def test_approval_decide_allow_with_note_warns_and_ignores_note(self):
        result = {
            "request": {
                "request_id": "req-1",
                "status": "approved_once",
                "decision": "allow_once",
            }
        }
        code, out, err = self._run(
            [
                "approval",
                "decide",
                "--request-id",
                "req-1",
                "--allow",
                "--note",
                "看看再说",
            ],
            self._handler({"approval_decide": result}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("req-1", out)
        # The decision is recorded; the warning goes to stderr (T2-5 style).
        self.assertIn("--note", err)
        self.assertIn("只在拒绝", err)
        # The note is dropped: RPC params byte-identical to a plain allow.
        self.assertEqual(
            self.calls,
            [("approval_decide", {"request_id": "req-1", "decision": "allow_once"})],
        )

    def test_approval_decide_deny_without_note_omits_note_param(self):
        # Lock: a bare --deny sends no note key at all.
        result = {
            "request": {
                "request_id": "req-1",
                "status": "denied",
                "decision": "deny",
            }
        }
        code, out, err = self._run(
            ["approval", "decide", "--request-id", "req-1", "--deny"],
            self._handler({"approval_decide": result}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(
            self.calls,
            [("approval_decide", {"request_id": "req-1", "decision": "deny"})],
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

    def test_show_renders_decision_note_when_present(self):
        # AP-1: deny --note feedback shows in the card detail.
        card = {
            "request_id": "req-noted",
            "status": "denied",
            "action_kind": "purchase",
            "target": "example store",
            "scope": "shopping",
            "decision": "deny",
            "decided_at": "2026-10-21T18:30:00Z",
            "decision_note": "太贵了，换个方案",
            "created_at": "2026-10-21T18:00:00Z",
            "expires_at": "",
        }
        result = {"pending": [], "denied": [card], "expired": [], "applied": []}
        code, out, err = self._run(
            ["approval", "show", "req-noted"],
            self._handler({"approval_list": result}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("决定备注", out)
        self.assertIn("太贵了，换个方案", out)

    def test_show_hides_decision_note_row_when_absent(self):
        # The shared fixture has no decision_note: no row, output unchanged.
        code, out, err = self._run(
            ["approval", "show", "req-denied"],
            self._handler({"approval_list": self._approval_result()}),
        )
        self.assertEqual(code, 0, err)
        self.assertNotIn("决定备注", out)

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
            ["suggestions", "list"],
            self._handler(
                {"suggestions_list": items, "proactive_contact_recent": []}
            ),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("sug-1", out)
        self.assertIn("Finish the report", out)
        self.assertIn("sug-2", out)
        self.assertEqual(
            self.calls,
            [
                ("suggestions_list", {"limit": 8}),
                ("proactive_contact_recent", {"limit": 5}),
            ],
        )

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
            ["suggestions", "list"],
            self._handler(
                {"suggestions_list": [], "proactive_contact_recent": []}
            ),
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

    # -- PC-1: 最近主动联系（建议栏尾部顺带呈现） ----------------------------

    def test_suggestions_list_appends_recent_contacts(self):
        items = [
            {"key": "sug-1", "kind": "work", "title": "Finish the report"},
        ]
        records = [
            {
                "suggestion_key": "recurring:daily check",
                "kind": "recurring_due",
                "sent_at": "2026-10-23T06:10:00+00:00",
                "day": "2026-10-23",
            },
            {
                "suggestion_key": "recurring:standup",
                "kind": "recurring_upcoming",
                "sent_at": "2026-10-22T06:10:00+00:00",
                "day": "2026-10-22",
            },
        ]
        code, out, err = self._run(
            ["suggestions", "list"],
            self._handler(
                {"suggestions_list": items, "proactive_contact_recent": records}
            ),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("sug-1", out)
        # 顺带段落在建议行之后。
        self.assertLess(out.index("sug-1"), out.index("最近主动联系："))
        self.assertIn("2026-10-23 [recurring_due] recurring:daily check", out)
        self.assertIn("2026-10-22 [recurring_upcoming] recurring:standup", out)
        self.assertEqual(
            self.calls,
            [
                ("suggestions_list", {"limit": 8}),
                ("proactive_contact_recent", {"limit": 5}),
            ],
        )

    def test_suggestions_list_no_records_output_byte_identical(self):
        # PC-1 锁定：无主动联系记录时，human 输出与改动前逐字节一致。
        items = [
            {"key": "sug-1", "kind": "work", "title": "Finish the report"},
            {"key": "sug-2", "kind": "recurring", "title": "Check the garden"},
        ]
        code, out, err = self._run(
            ["suggestions", "list"],
            self._handler(
                {"suggestions_list": items, "proactive_contact_recent": []}
            ),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(
            out,
            f"{'sug-1':64} [work] Finish the report\n"
            f"{'sug-2':64} [recurring] Check the garden\n",
        )
        self.assertNotIn("最近主动联系", out)

    def test_suggestions_list_empty_no_records_output_byte_identical(self):
        code, out, err = self._run(
            ["suggestions", "list"],
            self._handler(
                {"suggestions_list": [], "proactive_contact_recent": []}
            ),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "no suggestions\n")

    def test_suggestions_list_tolerates_unknown_recent_rpc(self):
        # 旧 resident 不认识 proactive_contact_recent：顺带段落静默
        # 跳过，主干建议栏不受影响。
        items = [
            {"key": "sug-1", "kind": "work", "title": "Finish the report"},
        ]
        code, out, err = self._run(
            ["suggestions", "list"], self._handler({"suggestions_list": items})
        )
        self.assertEqual(code, 0, err)
        self.assertIn("sug-1", out)
        self.assertNotIn("最近主动联系", out)

    def test_suggestions_list_json_unchanged_with_records(self):
        # --json 输出不变：不调新 RPC，只返回建议栏本身。
        items = [{"key": "sug-1", "kind": "work", "title": "Finish the report"}]
        code, out, err = self._run(
            ["suggestions", "list", "--json"],
            self._handler({"suggestions_list": items}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(self.calls, [("suggestions_list", {"limit": 8})])
        self.assertEqual(json.loads(out), items)


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

    # D1: `zn approval list` empty state gets the same "what next" hint as
    # the other T3-4 lists. The RPC returns a dict of sections (not a list),
    # so these cases are dedicated rather than folded into _EMPTY_CASES.
    def _empty_approval(self):
        return {"pending": [], "denied": [], "expired": [], "applied": []}

    def test_approval_list_empty_prints_hint_on_tty(self):
        code, out, err = self._run_on_tty(
            ["approval", "list"], self._handler({"approval_list": self._empty_approval()})
        )
        self.assertEqual(code, 0, err)
        self.assertIn("(none)", out)
        self.assertIn(
            "下一步：审批卡由 ZN 在需要你确认时自动发出，"
            "先看看自动批准规则，运行 `zn approval rules list`",
            out,
        )

    def test_approval_list_empty_hint_once_for_all_status(self):
        code, out, err = self._run_on_tty(
            ["approval", "list", "--status", "all"],
            self._handler({"approval_list": self._empty_approval()}),
        )
        self.assertEqual(code, 0, err)
        # four sections, but exactly one hint line
        self.assertEqual(out.count("(none)"), 4)
        self.assertEqual(out.count("下一步"), 1)

    def test_approval_list_empty_no_hint_on_pipe(self):
        code, out, err = self._run(
            ["approval", "list"], self._handler({"approval_list": self._empty_approval()})
        )
        self.assertEqual(code, 0, err)
        self.assertIn("(none)", out)
        self.assertNotIn("下一步", out)
        self.assertNotIn("\x1b[", out)

    def test_approval_list_empty_no_hint_in_json_mode(self):
        payload = self._empty_approval()
        code, out, err = self._run_on_tty(
            ["approval", "list", "--json"], self._handler({"approval_list": payload})
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), payload)
        self.assertNotIn("下一步", out)

    # D2: when the current view shows at least one pending card, the list
    # ends with one dim "what next" hint. This deliberately inverts the
    # D1-era expectation of the test above it (same scenario, changed
    # product behavior): the recorded CONSTRAINTS §1.3 exception lives in
    # the PR body.
    def test_approval_list_pending_shows_next_hint(self):
        result = self._empty_approval()
        result["pending"] = [
            {
                "request_id": "req-1",
                "status": "pending",
                "action_kind": "send",
                "target": "t",
                "scope": "s",
                "created_at": "2026-10-21T19:00:00Z",
                "expires_at": "",
            }
        ]
        code, out, err = self._run_on_tty(
            ["approval", "list"], self._handler({"approval_list": result})
        )
        self.assertEqual(code, 0, err)
        self.assertIn("req-1", out)
        self.assertIn(
            "下一步：先用 `zn approval show <request_id>` 看一张卡的详情，"
            "再用 `zn approval decide --request-id <id> --allow` 批准"
            "（或 `--deny` 拒绝）",
            out,
        )
        # exactly one hint line, at the end, dim on a TTY
        self.assertEqual(out.count("下一步"), 1)
        self.assertIn("下一步", out.rstrip("\n").splitlines()[-1])
        self.assertIn("\x1b[2m", out)

    def test_approval_list_pending_shows_hint_once_for_all_status(self):
        result = self._empty_approval()
        result["pending"] = [{"request_id": "req-1", "status": "pending"}]
        result["denied"] = [{"request_id": "req-d"}]
        code, out, err = self._run_on_tty(
            ["approval", "list", "--status", "all"],
            self._handler({"approval_list": result}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("req-1", out)
        self.assertIn("req-d", out)
        self.assertEqual(out.count("下一步"), 1)
        self.assertIn("下一步", out.rstrip("\n").splitlines()[-1])

    def test_approval_list_pending_no_hint_on_pipe(self):
        result = self._empty_approval()
        result["pending"] = [{"request_id": "req-1", "status": "pending"}]
        code, out, err = self._run(
            ["approval", "list"], self._handler({"approval_list": result})
        )
        self.assertEqual(code, 0, err)
        self.assertIn("req-1", out)
        self.assertNotIn("下一步", out)
        self.assertNotIn("\x1b[", out)

    def test_approval_list_pending_no_hint_with_no_color_on_tty(self):
        result = self._empty_approval()
        result["pending"] = [{"request_id": "req-1", "status": "pending"}]
        code, out, err = self._run_on_tty(
            ["approval", "list"],
            self._handler({"approval_list": result}),
            no_color=True,
        )
        self.assertEqual(code, 0, err)
        self.assertIn("req-1", out)
        self.assertNotIn("下一步", out)
        self.assertNotIn("\x1b[", out)

    def test_approval_list_pending_no_hint_in_json_mode(self):
        payload = self._empty_approval()
        payload["pending"] = [{"request_id": "req-1", "status": "pending"}]
        code, out, err = self._run_on_tty(
            ["approval", "list", "--json"], self._handler({"approval_list": payload})
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), payload)
        self.assertNotIn("下一步", out)

    def test_approval_list_non_pending_views_no_hint(self):
        # denied-only, expired-only, applied-only views show cards but no
        # pending ones: no D2 hint.
        for status, card_id in (
            ("denied", "req-d"),
            ("expired", "req-e"),
            ("applied", "req-a"),
        ):
            result = self._empty_approval()
            result[status] = [{"request_id": card_id}]
            code, out, err = self._run_on_tty(
                ["approval", "list", "--status", status],
                self._handler({"approval_list": result}),
            )
            self.assertEqual(code, 0, err)
            self.assertIn(card_id, out)
            self.assertNotIn("下一步", out)

    def test_approval_list_empty_keeps_only_d1_hint(self):
        # empty view: the D1 empty-state hint only; the D2 pending hint must
        # not appear and the two must never duplicate.
        code, out, err = self._run_on_tty(
            ["approval", "list"], self._handler({"approval_list": self._empty_approval()})
        )
        self.assertEqual(code, 0, err)
        self.assertIn("(none)", out)
        self.assertIn(
            "下一步：审批卡由 ZN 在需要你确认时自动发出，"
            "先看看自动批准规则，运行 `zn approval rules list`",
            out,
        )
        self.assertNotIn("zn approval show", out)
        self.assertEqual(out.count("下一步"), 1)

    def test_approval_list_filtered_empty_section_gets_hint(self):
        # `--status pending` shows only pending; denied having cards does not
        # suppress the hint for the (empty) requested view.
        result = self._empty_approval()
        result["denied"] = [{"request_id": "req-d"}]
        code, out, err = self._run_on_tty(
            ["approval", "list", "--status", "pending"],
            self._handler({"approval_list": result}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("(none)", out)
        self.assertIn("下一步", out)

    def test_approval_list_all_status_with_items_no_hint(self):
        result = self._empty_approval()
        result["denied"] = [{"request_id": "req-d"}]
        code, out, err = self._run_on_tty(
            ["approval", "list", "--status", "all"],
            self._handler({"approval_list": result}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("req-d", out)
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


class ZnCliApprovalReconsiderT12Tests(_CliHarness):
    """T12: ``zn approval reconsider <request-id> [--note]``."""

    def _reconsider_result(self, **overrides):
        result = {
            "request": {
                "request_id": "req-fresh",
                "status": "pending",
                "action_kind": "shell",
                "target": "deploy.sh",
                "created_at": "2026-10-22T20:00:00Z",
            }
        }
        result["request"].update(overrides)
        return result

    def test_reconsider_success_opens_fresh_pending_card(self):
        code, out, err = self._run(
            ["approval", "reconsider", "req-denied"],
            self._handler({"approval_reconsider_denied": self._reconsider_result()}),
        )
        self.assertEqual(code, 0, err)
        # New card id differs from the denied one; the denied record itself
        # is never mutated (server contract, audited via deny_overridden).
        self.assertIn("已为被拒的申请发起重新考虑", out)
        self.assertIn("新审批卡 req-fresh", out)
        self.assertNotEqual("req-fresh", "req-denied")
        self.assertIn("待审批", out)
        self.assertIn("原卡片：req-denied", out)
        self.assertIn("记录保持不变", out)
        self.assertEqual(
            self.calls,
            [("approval_reconsider_denied", {"request_id": "req-denied", "note": ""})],
        )

    def test_reconsider_note_passthrough(self):
        code, out, err = self._run(
            ["approval", "reconsider", "req-denied", "--note", "请再看一次"],
            self._handler({"approval_reconsider_denied": self._reconsider_result()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("说明：请再看一次", out)
        self.assertEqual(
            self.calls,
            [
                (
                    "approval_reconsider_denied",
                    {"request_id": "req-denied", "note": "请再看一次"},
                )
            ],
        )

    def test_reconsider_unknown_id_humanized(self):
        code, out, err = self._run(
            ["approval", "reconsider", "req-nope"],
            self._handler(
                {
                    "approval_reconsider_denied": (
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
        self.assertIn("unknown approval request", err)  # english kept in parens
        self.assertIn("zn approval list --status denied", err)

    def test_reconsider_not_denied_humanized(self):
        code, out, err = self._run(
            ["approval", "reconsider", "req-1"],
            self._handler(
                {
                    "approval_reconsider_denied": (
                        False,
                        None,
                        "ValueError: only denied approval requests can be "
                        "reconsidered; request req-1 is pending",
                    )
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("无法重新考虑", err)
        self.assertIn("only denied approval requests can be reconsidered", err)
        self.assertIn("pending", err)
        self.assertIn("req-1", err)

    def test_reconsider_offline_claims_nothing(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(["approval", "reconsider", "req-denied"], refused)
        self.assertEqual(code, 0, err)
        self.assertIn("常驻服务未运行", out)
        self.assertIn("没有为被拒的申请发起重新考虑", out)
        self.assertIn("保持被拒状态", out)
        self.assertNotIn("已为被拒的申请发起重新考虑", out)

    def test_reconsider_offline_json(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(
            ["approval", "reconsider", "req-denied", "--json"], refused
        )
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertFalse(data["daemon_reachable"])
        self.assertFalse(data["reconsidered"])
        self.assertEqual(data["request_id"], "req-denied")

    def test_reconsider_json_byte_stable(self):
        payload = self._reconsider_result()
        code, out, err = self._run(
            ["approval", "reconsider", "req-denied", "--json"],
            self._handler({"approval_reconsider_denied": payload}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(
            out,
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        )


class ZnCliTeamDriveT13Tests(_CliHarness):
    """T13: ``zn team assign @specialist <instruction>`` + ``zn team handover-done``."""

    def _assign_result(self, **overrides):
        result = {
            "team_id": "team-7",
            "specialist": "设计",
            "item_id": "item-9",
            "item_title": "重做首页排版",
            "instruction": "用新版设计稿",
        }
        result.update(overrides)
        return result

    def _handover_result(self, **overrides):
        result = {
            "team_id": "team-7",
            "handover_id": "handover-abc123",
            "kind": "password",
            "status": "resolved",
        }
        result.update(overrides)
        return result

    # -- team assign --------------------------------------------------------

    def test_assign_success_reassigns_next_pending_item(self):
        code, out, err = self._run(
            ["team", "assign", "@设计", "用新版设计稿", "--thread-id", "thread-1"],
            self._handler({"team_assign": self._assign_result()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("已把团队下一项任务指派给 @设计", out)
        self.assertIn("任务：重做首页排版", out)
        self.assertIn("团队：team-7", out)
        self.assertIn("说明：用新版设计稿", out)
        # The override is journaled; the timeline is where the user sees it.
        self.assertIn("zn team timeline --thread-id thread-1", out)
        # Leading @ is a CLI spelling; the RPC takes the bare member name.
        self.assertEqual(
            self.calls,
            [
                (
                    "team_assign",
                    {
                        "thread_id": "thread-1",
                        "specialist": "设计",
                        "instruction": "用新版设计稿",
                    },
                )
            ],
        )

    def test_assign_specialist_without_at_sign(self):
        code, out, err = self._run(
            ["team", "assign", "qa", "跑一遍回归测试", "--thread-id", "thread-1"],
            self._handler(
                {
                    "team_assign": self._assign_result(
                        specialist="qa",
                        item_title="回归测试",
                        instruction="跑一遍回归测试",
                    )
                }
            ),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("已把团队下一项任务指派给 @qa", out)
        self.assertEqual(
            self.calls[0][1]["specialist"], "qa", "bare name passes through"
        )

    def test_assign_unknown_thread_humanized(self):
        code, out, err = self._run(
            ["team", "assign", "@设计", "做事", "--thread-id", "thread-nope"],
            self._handler(
                {
                    "team_assign": (
                        False,
                        None,
                        "ValueError: unknown work thread: 'thread-nope'",
                    )
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("找不到工作线程 'thread-nope'", err)
        self.assertIn("unknown work thread", err)  # english kept in parens
        self.assertIn("zn work list", err)

    def test_assign_no_running_team_passthrough(self):
        # The daemon message is already Chinese and actionable; it passes
        # through unchanged (no English fragment to keep).
        code, out, err = self._run(
            ["team", "assign", "@设计", "做事", "--thread-id", "thread-1"],
            self._handler(
                {
                    "team_assign": (
                        False,
                        None,
                        "ValueError: 该 Work 没有运行中的团队，@指派需要先组团队",
                    )
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("该 Work 没有运行中的团队", err)
        self.assertIn("@指派需要先组团队", err)

    def test_assign_unknown_specialist_passthrough(self):
        code, out, err = self._run(
            ["team", "assign", "@ghost", "做事", "--thread-id", "thread-1"],
            self._handler(
                {
                    "team_assign": (
                        False,
                        None,
                        "ValueError: 团队里没有专员 'ghost'，可选：设计, qa",
                    )
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("团队里没有专员 'ghost'", err)
        self.assertIn("可选：设计, qa", err)

    def test_assign_no_pending_item_passthrough(self):
        code, out, err = self._run(
            ["team", "assign", "@设计", "做事", "--thread-id", "thread-1"],
            self._handler(
                {
                    "team_assign": (
                        False,
                        None,
                        "ValueError: 团队已无待派发任务，@指派无下一步可派",
                    )
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("团队已无待派发任务", err)

    def test_assign_work_ledger_missing_humanized(self):
        code, out, err = self._run(
            ["team", "assign", "@设计", "做事", "--thread-id", "thread-1"],
            self._handler(
                {
                    "team_assign": (
                        False,
                        None,
                        "ValueError: resident has no work ledger",
                    )
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("缺少工作账本", err)
        self.assertIn("resident has no work ledger", err)  # english kept in parens

    def test_assign_offline_claims_nothing(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(
            ["team", "assign", "@设计", "做事", "--thread-id", "thread-1"], refused
        )
        self.assertEqual(code, 0, err)
        self.assertIn("常驻服务未运行", out)
        self.assertIn("没有为团队指派新的专员", out)
        self.assertIn("未生效", out)
        self.assertNotIn("已把团队下一项任务指派给", out)

    def test_assign_offline_json(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(
            ["team", "assign", "@设计", "做事", "--thread-id", "thread-1", "--json"],
            refused,
        )
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertFalse(data["daemon_reachable"])
        self.assertFalse(data["assigned"])
        self.assertEqual(data["thread_id"], "thread-1")
        self.assertEqual(data["specialist"], "设计")

    def test_assign_json_byte_stable(self):
        payload = self._assign_result()
        code, out, err = self._run(
            ["team", "assign", "@设计", "用新版设计稿", "--thread-id", "thread-1", "--json"],
            self._handler({"team_assign": payload}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(
            out,
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        )

    def test_assign_missing_thread_id_is_argparse_error(self):
        with self.assertRaises(SystemExit) as caught:
            self._run(
                ["team", "assign", "@设计", "做事"],
                self._handler({"team_assign": self._assign_result()}),
            )
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [], "no RPC fires before argparse rejects")

    # -- team handover-done --------------------------------------------------

    def test_handover_done_success_releases_team(self):
        code, out, err = self._run(
            ["team", "handover-done", "--thread-id", "thread-1"],
            self._handler({"team_handover_done": self._handover_result()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("敏感步骤已放行，团队继续", out)
        self.assertIn("交接：handover-abc123（password）", out)
        self.assertIn("团队：team-7", out)
        self.assertEqual(
            self.calls,
            [("team_handover_done", {"thread_id": "thread-1"})],
        )

    def test_handover_done_no_pending_refused_nonzero(self):
        code, out, err = self._run(
            ["team", "handover-done", "--thread-id", "thread-1"],
            self._handler(
                {
                    "team_handover_done": (
                        False,
                        None,
                        "ValueError: 该团队当前没有待主人完成的敏感步骤",
                    )
                }
            ),
        )
        self.assertEqual(code, 1, "spec: refusal is human, but non-zero")
        self.assertEqual(out, "")
        self.assertIn("没有待主人完成的敏感步骤", err)
        self.assertIn("no pending handover", err)  # english kept in parens
        self.assertIn("无需放行", err)

    def test_handover_done_unknown_thread_humanized(self):
        code, out, err = self._run(
            ["team", "handover-done", "--thread-id", "thread-nope"],
            self._handler(
                {
                    "team_handover_done": (
                        False,
                        None,
                        "ValueError: unknown work thread: 'thread-nope'",
                    )
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("找不到工作线程 'thread-nope'", err)
        self.assertIn("unknown work thread", err)

    def test_handover_done_offline_claims_nothing(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(
            ["team", "handover-done", "--thread-id", "thread-1"], refused
        )
        self.assertEqual(code, 0, err)
        self.assertIn("常驻服务未运行", out)
        self.assertIn("没有放行任何敏感步骤", out)
        self.assertNotIn("敏感步骤已放行", out)

    def test_handover_done_offline_json(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(
            ["team", "handover-done", "--thread-id", "thread-1", "--json"], refused
        )
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertFalse(data["daemon_reachable"])
        self.assertFalse(data["resolved"])
        self.assertEqual(data["thread_id"], "thread-1")

    def test_handover_done_json_byte_stable(self):
        payload = self._handover_result()
        code, out, err = self._run(
            ["team", "handover-done", "--thread-id", "thread-1", "--json"],
            self._handler({"team_handover_done": payload}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(
            out,
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        )


class ZnCliWorkSubmitFailureHintD3Tests(_CliHarness):
    """D3: `zn work submit` ending with ``success=False`` names the next step.

    New test class (Floor Guard: existing tests and assertions untouched).
    """

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

    def _failed_submit(self, *, response=""):
        return {
            "thread": {"id": "thread-1", "title": "T"},
            "run": {
                "event_id": "ev-1",
                "success": False,
                "cancelled": False,
                "execution_path": "direct",
                "model_invocations": 1,
                "response": response,
            },
            "recovery_required": False,
        }

    def _submit(self, argv, handler):
        return self._run(
            ["work", "submit", "--thread-id", "thread-1", "--task", "do the thing",
             *argv],
            handler,
        )

    def test_failure_shows_next_hint_on_tty(self):
        code, out, err = self._run_on_tty(
            ["work", "submit", "--thread-id", "thread-1", "--task", "do the thing"],
            self._handler({"work_submit": self._failed_submit()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("success=False", out)
        self.assertIn(
            "下一步：这次交办失败了（success=False），"
            "用 `zn work get --thread-id thread-1` 看失败原因",
            out,
        )
        # exactly one hint line, at the end, dim on a TTY
        self.assertEqual(out.count("下一步"), 1)
        self.assertIn("下一步", out.rstrip("\n").splitlines()[-1])
        self.assertIn("\x1b[2m", out)

    def test_failure_without_response_still_hints(self):
        # the walkthrough case: only the one-line summary, no reply text.
        code, out, err = self._run_on_tty(
            ["work", "submit", "--thread-id", "thread-1", "--task", "do the thing"],
            self._handler({"work_submit": self._failed_submit()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("success=False", out)
        self.assertIn("zn work get --thread-id thread-1", out)

    def test_failure_hint_sits_right_after_summary_line(self):
        code, out, err = self._run_on_tty(
            ["work", "submit", "--thread-id", "thread-1", "--task", "do the thing"],
            self._handler(
                {"work_submit": self._failed_submit(response="出了点问题")}
            ),
        )
        self.assertEqual(code, 0, err)
        lines = out.rstrip("\n").splitlines()
        summary_idx = next(
            i for i, line in enumerate(lines) if line.startswith("run event=")
        )
        self.assertIn("下一步", lines[summary_idx + 1])

    def test_success_has_no_hint(self):
        result = {
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
        code, out, err = self._run_on_tty(
            ["work", "submit", "--thread-id", "thread-1", "--task", "do the thing"],
            self._handler({"work_submit": result}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("success=True", out)
        self.assertNotIn("下一步", out)

    def test_failure_no_hint_on_pipe(self):
        code, out, err = self._submit([], self._handler({"work_submit": self._failed_submit()}))
        self.assertEqual(code, 0, err)
        self.assertIn("success=False", out)
        self.assertNotIn("下一步", out)
        self.assertNotIn("\x1b[", out)

    def test_failure_no_hint_with_no_color_on_tty(self):
        code, out, err = self._run_on_tty(
            ["work", "submit", "--thread-id", "thread-1", "--task", "do the thing"],
            self._handler({"work_submit": self._failed_submit()}),
            no_color=True,
        )
        self.assertEqual(code, 0, err)
        self.assertIn("success=False", out)
        self.assertNotIn("下一步", out)
        self.assertNotIn("\x1b[", out)

    def test_failure_no_hint_in_json_mode(self):
        result = self._failed_submit()
        code, out, err = self._run_on_tty(
            [
                "work",
                "submit",
                "--thread-id",
                "thread-1",
                "--task",
                "do the thing",
                "--json",
            ],
            self._handler({"work_submit": result}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), result)
        self.assertNotIn("下一步", out)


class ZnCliWorkCancelFinishedRunD4Tests(_CliHarness):
    """D4: `zn work cancel` on a finished run is humanized with a next step.

    New test class (Floor Guard: existing tests and assertions untouched).
    """

    _FINISHED_ERROR = "RuntimeError: work cancellation requires an active Work run"
    _GENERIC_ERROR = (
        "zn: error: 服务端返回错误（work_cancel）："
        f"{_FINISHED_ERROR}\n"
    )

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

    def _cancel(self, argv_extra=()):
        return (
            ["work", "cancel", "--thread-id", "t1", "--event-id", "e9", *argv_extra],
            self._handler({"work_cancel": (False, None, self._FINISHED_ERROR)}),
        )

    def test_finished_run_cancel_humanized_with_hint_on_tty(self):
        argv, handler = self._cancel()
        code, out, err = self._run_on_tty(argv, handler)
        self.assertEqual(code, 1, err)
        # human body + English technical snippet in parentheses (T2-5)
        self.assertIn("zn: error: 这个任务已经结束了，取消不了", err)
        self.assertIn("（work cancellation requires an active Work run）", err)
        self.assertNotIn("服务端返回错误", err)
        # dim next-step hint on stdout, exactly once
        self.assertIn(
            "下一步：活已经结束了，用 `zn work get --thread-id t1` 看结果",
            out,
        )
        self.assertEqual(out.count("下一步"), 1)
        self.assertIn("\x1b[2m", out)

    def test_finished_run_cancel_generic_on_pipe(self):
        # piped output keeps the historic generic error byte-stable
        argv, handler = self._cancel()
        code, out, err = self._run(argv, handler)
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertEqual(err, self._GENERIC_ERROR)
        self.assertNotIn("下一步", err)
        self.assertNotIn("\x1b[", out + err)

    def test_finished_run_cancel_generic_with_no_color_on_tty(self):
        argv, handler = self._cancel()
        code, out, err = self._run_on_tty(argv, handler, no_color=True)
        self.assertEqual(code, 1, err)
        # the T3-3 first-run hint may share stdout on a real TTY in a fresh
        # home; the D4 contract is only that the D4 hint line is absent.
        self.assertNotIn("下一步", out)
        self.assertEqual(err, self._GENERIC_ERROR)
        self.assertNotIn("下一步", err)

    def test_finished_run_cancel_generic_in_json_mode(self):
        argv, handler = self._cancel(["--json"])
        code, out, err = self._run_on_tty(argv, handler)
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertEqual(err, self._GENERIC_ERROR)
        self.assertNotIn("下一步", err)

    def test_other_server_error_unchanged_on_tty(self):
        # a different work_cancel rejection keeps the generic path on TTY
        handler = self._handler(
            {"work_cancel": (False, None, "RuntimeError: something else broke")}
        )
        code, out, err = self._run_on_tty(
            ["work", "cancel", "--thread-id", "t1", "--event-id", "e9"], handler
        )
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn("服务端返回错误（work_cancel）：RuntimeError: something else broke", err)
        self.assertNotIn("下一步", out)
        self.assertNotIn("下一步", err)
        self.assertNotIn("已经结束了", err)

    def test_successful_cancel_unchanged_on_tty(self):
        # the happy path is untouched: no hint, normal output
        payload = {
            "progress": {"state": "cancelled", "cancelled": True},
            "thread": {"id": "t1"},
        }
        code, out, err = self._run_on_tty(
            ["work", "cancel", "--thread-id", "t1", "--event-id", "e9"],
            self._handler({"work_cancel": payload}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("cancelled event=e9 on thread=t1", out)
        self.assertNotIn("下一步", out)


class ZnCliWorkResolveUncertainT14Tests(_CliHarness):
    """T14: ``zn work resolve-uncertain`` -- terminal entry for uncertain side-effect decisions.

    New test class (Floor Guard: existing tests and assertions untouched).
    """

    _NON_ACTIVE_ERROR = (
        "RuntimeError: work uncertain-effect resolution requires an active Work run"
    )
    _GENERIC_NON_ACTIVE_ERROR = (
        "zn: error: 服务端返回错误（work_resolve_uncertain）："
        f"{_NON_ACTIVE_ERROR}\n"
    )

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

    def _argv(self, decision="effect_happened", extra=()):
        return (
            [
                "work",
                "resolve-uncertain",
                "--thread-id",
                "t1",
                "--event-id",
                "e9",
                "--attempt-id",
                "a3",
                "--decision",
                decision,
                *extra,
            ]
        )

    def _result(self, **overrides):
        result = {"progress": {"state": "running", "status": "working"}, "thread": {"id": "t1"}}
        result.update(overrides)
        return result

    # -- happy paths ---------------------------------------------------------

    def test_effect_happened_success_renders_decision(self):
        code, out, err = self._run(
            self._argv("effect_happened"),
            self._handler({"work_resolve_uncertain": self._result()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("resolved event=e9 attempt=a3 on thread=t1", out)
        self.assertIn("裁决：effect_happened（副作用已发生，不再重发）", out)
        self.assertIn("state=running", out)
        self.assertEqual(
            self.calls,
            [
                (
                    "work_resolve_uncertain",
                    {
                        "thread_id": "t1",
                        "event_id": "e9",
                        "attempt_id": "a3",
                        "decision": "effect_happened",
                    },
                )
            ],
        )

    def test_retry_authorized_success_renders_decision(self):
        code, out, err = self._run(
            self._argv("retry_authorized"),
            self._handler({"work_resolve_uncertain": self._result()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("裁决：retry_authorized（允许 ZN 重试这一步）", out)

    def test_json_passes_rpc_result_through(self):
        payload = self._result()
        code, out, err = self._run(
            self._argv("retry_authorized", extra=["--json"]),
            self._handler({"work_resolve_uncertain": payload}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), payload)
        self.assertIn('"progress"', out)

    # -- argparse: illegal / missing values exit 2 ----------------------------

    def test_illegal_decision_exits_2(self):
        handler = self._handler({})
        with self.assertRaises(SystemExit) as caught:
            self._run(self._argv("maybe_retry"), handler)
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])

    def test_missing_attempt_id_exits_2(self):
        handler = self._handler({})
        with self.assertRaises(SystemExit) as caught:
            self._run(
                [
                    "work",
                    "resolve-uncertain",
                    "--thread-id",
                    "t1",
                    "--event-id",
                    "e9",
                    "--decision",
                    "effect_happened",
                ],
                handler,
            )
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])

    # -- T2-6: unreachable resident -> exit 0, nothing claimed ------------------

    def test_offline_claims_nothing(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(self._argv("effect_happened"), refused)
        self.assertEqual(code, 0, err)
        self.assertIn("常驻服务未运行", out)
        self.assertIn("没有裁决任何不确定的副作用", out)
        self.assertIn("未生效", out)
        self.assertNotIn("resolved event=e9", out)

    def test_offline_json(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(
            self._argv("retry_authorized", extra=["--json"]), refused
        )
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertFalse(data["daemon_reachable"])
        self.assertFalse(data["resolved"])
        self.assertEqual(data["thread_id"], "t1")
        self.assertEqual(data["event_id"], "e9")
        self.assertEqual(data["attempt_id"], "a3")

    # -- T2-5: server rejections humanized, exit 1 -------------------------------

    def _reject(self, error_text):
        return self._handler({"work_resolve_uncertain": (False, None, error_text)})

    def test_non_active_run_humanized_with_hint_on_tty(self):
        code, out, err = self._run_on_tty(
            self._argv("effect_happened"), self._reject(self._NON_ACTIVE_ERROR)
        )
        self.assertEqual(code, 1, err)
        # human body + English technical snippet in parentheses (T2-5)
        self.assertIn("zn: error: 这个任务已经结束了，裁决不了", err)
        self.assertIn(
            "（work uncertain-effect resolution requires an active Work run）", err
        )
        self.assertNotIn("服务端返回错误", err)
        # dim next-step hint on stdout, exactly once
        self.assertIn(
            "下一步：活已经结束了，用 `zn work get --thread-id t1` 看结果", out
        )
        self.assertEqual(out.count("下一步"), 1)
        self.assertIn("\x1b[2m", out)

    def test_non_active_run_generic_on_pipe(self):
        # piped output keeps the historic generic error byte-stable
        code, out, err = self._run(
            self._argv("effect_happened"), self._reject(self._NON_ACTIVE_ERROR)
        )
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertEqual(err, self._GENERIC_NON_ACTIVE_ERROR)
        self.assertNotIn("下一步", err)
        self.assertNotIn("\x1b[", out + err)

    def test_non_active_run_generic_with_no_color_on_tty(self):
        code, out, err = self._run_on_tty(
            self._argv("effect_happened"), self._reject(self._NON_ACTIVE_ERROR),
            no_color=True,
        )
        self.assertEqual(code, 1, err)
        self.assertNotIn("下一步", out)
        self.assertEqual(err, self._GENERIC_NON_ACTIVE_ERROR)

    def test_non_active_run_generic_in_json_mode(self):
        code, out, err = self._run_on_tty(
            self._argv("effect_happened", extra=["--json"]),
            self._reject(self._NON_ACTIVE_ERROR),
        )
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertEqual(err, self._GENERIC_NON_ACTIVE_ERROR)
        self.assertNotIn("下一步", err)

    def test_unknown_event_humanized(self):
        code, out, err = self._run(
            self._argv("effect_happened"),
            self._reject("ValueError: unknown work event for thread"),
        )
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn(
            "zn: error: 找不到这个工作事件（unknown work event for thread）", err
        )
        self.assertIn("zn work get --thread-id t1", err)
        self.assertNotIn("服务端返回错误", err)

    def test_attempt_checkpoint_mismatch_humanized(self):
        code, out, err = self._run(
            self._argv("retry_authorized"),
            self._reject(
                "RuntimeError: uncertain event resolution attempt does not match "
                "the active recovery checkpoint"
            ),
        )
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn("zn: error: 这次尝试现在不在等待人工裁决的状态", err)
        self.assertIn(
            "（uncertain event resolution attempt does not match "
            "the active recovery checkpoint）",
            err,
        )
        self.assertNotIn("服务端返回错误", err)

    def test_other_server_error_unchanged_on_tty(self):
        # a different rejection keeps the generic path on TTY
        code, out, err = self._run_on_tty(
            self._argv("effect_happened"),
            self._reject("RuntimeError: something else broke"),
        )
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn(
            "服务端返回错误（work_resolve_uncertain）：RuntimeError: something else broke",
            err,
        )
        self.assertNotIn("下一步", out)
        self.assertNotIn("已经结束了", err)

    # -- TTY niceties -----------------------------------------------------------

    def test_tty_prints_uncertain_meaning_note(self):
        code, out, err = self._run_on_tty(
            self._argv("effect_happened"),
            self._handler({"work_resolve_uncertain": self._result()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("说明：「副作用不确定」", out)

    def test_pipe_output_has_no_note(self):
        code, out, err = self._run(
            self._argv("effect_happened"),
            self._handler({"work_resolve_uncertain": self._result()}),
        )
        self.assertEqual(code, 0, err)
        self.assertNotIn("说明：", out)
        self.assertNotIn("\x1b[", out + err)


class ZnCliWorkRenameT16Tests(_CliHarness):
    """T16: ``zn work rename`` -- terminal entry for renaming a work thread.

    New test class (Floor Guard: existing tests and assertions untouched).
    """

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

    def _argv(self, title="新标题", extra=()):
        return ["work", "rename", "--thread-id", "t1", "--title", title, *extra]

    def _result(self, **overrides):
        result = {
            "id": "t1",
            "title": "新标题",
            "created_at": "2026-10-22T01:00:00Z",
            "updated_at": "2026-10-22T02:00:00Z",
            "active_run": None,
            "messages": [],
            "artifacts": [],
            "metadata": {},
        }
        result.update(overrides)
        return result

    # -- happy paths ---------------------------------------------------------

    def test_rename_success_prints_new_title(self):
        code, out, err = self._run(
            self._argv(), self._handler({"work_rename": self._result()})
        )
        self.assertEqual(code, 0, err)
        self.assertIn("renamed thread=t1", out)
        self.assertIn("新标题：新标题", out)
        self.assertEqual(
            self.calls, [("work_rename", {"thread_id": "t1", "title": "新标题"})]
        )

    def test_rename_sends_exact_rpc_schema(self):
        # the daemon rejects work_rename params that are not exactly
        # {"thread_id", "title"} -- the client must send nothing else.
        self._run(self._argv(), self._handler({"work_rename": self._result()}))
        method, params = self.calls[0]
        self.assertEqual(method, "work_rename")
        self.assertEqual(set(params), {"thread_id", "title"})

    def test_rename_prints_server_returned_title(self):
        # the resident normalizes titles; what the resident stored wins.
        code, out, err = self._run(
            self._argv(),
            self._handler({"work_rename": self._result(title="归一化后")}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("新标题：归一化后", out)

    def test_rename_json_passes_rpc_result_through(self):
        payload = self._result()
        code, out, err = self._run(
            self._argv(extra=["--json"]),
            self._handler({"work_rename": payload}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), payload)
        self.assertIn('"title"', out)

    def test_rename_malformed_result_humanized(self):
        code, out, err = self._run(
            self._argv(), self._handler({"work_rename": {"id": "t1"}})
        )
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn(
            "zn: error: 服务返回了无法识别的结果（unexpected work_rename result", err
        )

    # -- argparse: illegal / missing values exit 2 ----------------------------

    def test_missing_thread_id_exits_2(self):
        handler = self._handler({})
        with self.assertRaises(SystemExit) as caught:
            self._run(["work", "rename", "--title", "新标题"], handler)
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])

    def test_missing_title_exits_2(self):
        handler = self._handler({})
        with self.assertRaises(SystemExit) as caught:
            self._run(["work", "rename", "--thread-id", "t1"], handler)
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])

    def test_blank_title_exits_2(self):
        handler = self._handler({})
        with self.assertRaises(SystemExit) as caught:
            self._run(self._argv(title="   "), handler)
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])

    # -- T2-6: unreachable resident -> exit 0, nothing claimed ------------------

    def test_offline_claims_nothing(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(self._argv(), refused)
        self.assertEqual(code, 0, err)
        self.assertIn("常驻服务未运行", out)
        self.assertIn("没有给线程改名", out)
        self.assertIn("未生效", out)
        self.assertNotIn("renamed thread=t1", out)

    def test_offline_json(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(self._argv(extra=["--json"]), refused)
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertFalse(data["daemon_reachable"])
        self.assertFalse(data["renamed"])
        self.assertEqual(data["thread_id"], "t1")
        self.assertEqual(data["title"], "新标题")

    # -- T2-5: server rejections humanized, exit 1 -------------------------------

    def test_unknown_thread_humanized(self):
        handler = self._handler(
            {"work_rename": (False, None, "ValueError: unknown work thread")}
        )
        code, out, err = self._run(self._argv(), handler)
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn(
            "zn: error: 找不到这个工作线程（unknown work thread）", err
        )
        self.assertIn("zn work list", err)
        self.assertNotIn("服务端返回错误", err)

    def test_other_server_error_unchanged(self):
        handler = self._handler(
            {"work_rename": (False, None, "RuntimeError: something else broke")}
        )
        code, out, err = self._run(self._argv(), handler)
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn(
            "服务端返回错误（work_rename）：RuntimeError: something else broke", err
        )

    # -- TTY niceties -----------------------------------------------------------

    def test_tty_prints_confirm_hint(self):
        code, out, err = self._run_on_tty(
            self._argv(), self._handler({"work_rename": self._result()})
        )
        self.assertEqual(code, 0, err)
        self.assertIn("用 `zn work list` 确认新标题", out)
        self.assertIn("\x1b[2m", out)

    def test_pipe_output_has_no_hint(self):
        code, out, err = self._run(
            self._argv(), self._handler({"work_rename": self._result()})
        )
        self.assertEqual(code, 0, err)
        self.assertNotIn("用 `zn work list`", out)
        self.assertNotIn("\x1b[", out + err)


class ZnCliWorkAttachT16Tests(_CliHarness):
    """T16: ``zn work attach`` -- terminal entry for attaching a workspace.

    New test class (Floor Guard: existing tests and assertions untouched).
    """

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

    def _argv(self, path, extra=()):
        return ["work", "attach", "--thread-id", "t1", "--path", path, *extra]

    def _result(self, **overrides):
        result = {
            "id": "t1",
            "title": "Thread",
            "created_at": "2026-10-22T01:00:00Z",
            "updated_at": "2026-10-22T02:00:00Z",
            "active_run": None,
            "messages": [],
            "artifacts": [],
            "metadata": {
                "workspace": {
                    "path": str(self.tmp.name),
                    "name": os.path.basename(self.tmp.name),
                    "attached_at": "2026-10-22T02:00:00Z",
                }
            },
        }
        result.update(overrides)
        return result

    # -- happy paths ---------------------------------------------------------

    def test_attach_success_prints_workspace(self):
        code, out, err = self._run(
            self._argv(self.tmp.name),
            self._handler({"work_attach_workspace": self._result()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("attached workspace to thread=t1", out)
        self.assertIn(f"目录：{self.tmp.name}", out)
        self.assertEqual(
            self.calls,
            [
                (
                    "work_attach_workspace",
                    {"thread_id": "t1", "workspace_path": self.tmp.name},
                )
            ],
        )

    def test_attach_json_passes_rpc_result_through(self):
        payload = self._result()
        code, out, err = self._run(
            self._argv(self.tmp.name, extra=["--json"]),
            self._handler({"work_attach_workspace": payload}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), payload)
        self.assertIn('"workspace"', out)

    def test_attach_malformed_result_humanized(self):
        code, out, err = self._run(
            self._argv(self.tmp.name),
            self._handler({"work_attach_workspace": {"id": "t1", "metadata": {}}}),
        )
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn(
            "zn: error: 服务返回了无法识别的结果（unexpected work_attach_workspace result",
            err,
        )

    # -- client-side path validation: no RPC leaves the terminal ---------------

    def test_missing_directory_path_humanized(self):
        missing = os.path.join(self.tmp.name, "no-such-dir")
        handler = self._handler({})
        code, out, err = self._run(self._argv(missing), handler)
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn("zn: error: 找不到这个目录（path does not exist", err)
        self.assertIn(missing, err)
        self.assertEqual(self.calls, [])

    def test_file_instead_of_directory_humanized(self):
        file_path = os.path.join(self.tmp.name, "a-file.txt")
        Path(file_path).write_text("x", encoding="utf-8")
        handler = self._handler({})
        code, out, err = self._run(self._argv(file_path), handler)
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn("zn: error: 这不是一个目录（not a directory", err)
        self.assertEqual(self.calls, [])

    # -- argparse: illegal / missing values exit 2 ----------------------------

    def test_missing_thread_id_exits_2(self):
        handler = self._handler({})
        with self.assertRaises(SystemExit) as caught:
            self._run(["work", "attach", "--path", self.tmp.name], handler)
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])

    def test_missing_path_exits_2(self):
        handler = self._handler({})
        with self.assertRaises(SystemExit) as caught:
            self._run(["work", "attach", "--thread-id", "t1"], handler)
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])

    # -- T2-6: unreachable resident -> exit 0, nothing claimed ------------------

    def test_offline_claims_nothing(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(self._argv(self.tmp.name), refused)
        self.assertEqual(code, 0, err)
        self.assertIn("常驻服务未运行", out)
        self.assertIn("没有给线程绑定工作区", out)
        self.assertIn("未生效", out)
        self.assertNotIn("attached workspace to thread=t1", out)

    def test_offline_json(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(
            self._argv(self.tmp.name, extra=["--json"]), refused
        )
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertFalse(data["daemon_reachable"])
        self.assertFalse(data["attached"])
        self.assertEqual(data["thread_id"], "t1")
        self.assertEqual(data["workspace_path"], self.tmp.name)

    # -- T2-5: server rejections humanized, exit 1 -------------------------------

    def test_server_path_unavailable_humanized(self):
        # the local pre-check makes this a race-only path; it still has to
        # be human copy if the resident rejects after the check passed.
        handler = self._handler(
            {
                "work_attach_workspace": (
                    False,
                    None,
                    f"ValueError: workspace path is unavailable: {self.tmp.name}",
                )
            }
        )
        code, out, err = self._run(self._argv(self.tmp.name), handler)
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn("zn: error: 这个目录常驻服务够不着（workspace path is unavailable）", err)
        self.assertNotIn("服务端返回错误", err)

    def test_other_server_error_unchanged(self):
        handler = self._handler(
            {
                "work_attach_workspace": (
                    False,
                    None,
                    "RuntimeError: something else broke",
                )
            }
        )
        code, out, err = self._run(self._argv(self.tmp.name), handler)
        self.assertEqual(code, 1, err)
        self.assertIn(
            "服务端返回错误（work_attach_workspace）：RuntimeError: something else broke",
            err,
        )

    # -- TTY niceties -----------------------------------------------------------

    def test_tty_prints_get_hint(self):
        code, out, err = self._run_on_tty(
            self._argv(self.tmp.name),
            self._handler({"work_attach_workspace": self._result()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("用 `zn work get --thread-id t1` 查看绑定的工作区", out)
        self.assertIn("\x1b[2m", out)

    def test_pipe_output_has_no_hint(self):
        code, out, err = self._run(
            self._argv(self.tmp.name),
            self._handler({"work_attach_workspace": self._result()}),
        )
        self.assertEqual(code, 0, err)
        self.assertNotIn("zn work get --thread-id", out)
        self.assertNotIn("\x1b[", out + err)


class ZnCliRoutineProposeConfirmT17Tests(_CliHarness):
    """T17: ``zn routine propose`` / ``zn routine confirm``.

    Terminal face for the daemon's already-wired ``routine_propose`` /
    ``routine_confirm`` RPCs: one sentence -> draft with the six
    confirmations, then validate + create from a (possibly edited) draft.

    New test class (Floor Guard: existing tests and assertions untouched).
    """

    def _draft(self, **overrides):
        draft = {
            "text": "每天早上8点提醒我看日程",
            "task": "提醒我看日程",
            "owner": "ZN",
            "schedule_kind": "cron",
            "interval_seconds": None,
            "cron_expression": "0 8 * * *",
            "timezone": "UTC",
            "input_source": "ZN 记忆与当前工作现场",
            "expected_result": "完成：提醒我看日程",
            "approval_boundary": "只读汇总，不发送、不发布、不删除、不购买；超出范围需审批",
            "missing_data_policy": "skip",
            "auto_pause_after_days": 14,
            "missing": [],
        }
        draft.update(overrides)
        return draft

    def _snapshot(self, **overrides):
        snap = {
            "routine_id": "routine-abc123",
            "title": "提醒我看日程",
            "task": "提醒我看日程",
            "owner": "ZN",
            "schedule_kind": "cron",
            "schedule_spec": "0 8 * * *",
            "timezone": "UTC",
            "input_source": "ZN 记忆与当前工作现场",
            "expected_result": "完成：提醒我看日程",
            "approval_boundary": "只读汇总",
            "missing_data_policy": "skip",
            "status": "active",
            "schedule_description": "每天 08:00（UTC）",
            "created_at": "2026-10-23T00:00:00+00:00",
        }
        snap.update(overrides)
        return snap

    def _rejected(self, error_text):
        """An RPC ok:false server rejection, as the real daemon sends."""
        return (False, None, error_text)

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

    def _refused(self, method, params):
        raise socket.error("connection refused")

    # -- propose: happy paths --------------------------------------------------

    def test_propose_shows_six_confirmations(self):
        draft = self._draft()
        code, out, err = self._run(
            ["routine", "propose", "每天早上8点提醒我看日程"],
            self._handler({"routine_propose": draft}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(
            self.calls,
            [("routine_propose", {"text": "每天早上8点提醒我看日程"})],
        )
        for label in ("任务：", "负责人：", "计划：", "输入来源：", "期望结果：", "审批边界：", "缺失数据策略："):
            self.assertIn(label, out)
        self.assertIn("提醒我看日程", out)
        self.assertIn("0 8 * * *", out)
        self.assertNotIn("缺项", out)
        self.assertEqual(err, "")

    def test_propose_missing_schedule_hint(self):
        draft = self._draft(
            schedule_kind="",
            cron_expression=None,
            missing=["schedule"],
        )
        code, out, err = self._run(
            ["routine", "propose", "提醒我喝水"],
            self._handler({"routine_propose": draft}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("未解析出时间计划", out)
        self.assertIn("缺项：时间计划还没解析出来", out)
        self.assertIn("每天早上8点", out)

    def test_propose_json_passes_rpc_result_through(self):
        draft = self._draft()
        code, out, err = self._run(
            ["routine", "propose", "每天早上8点提醒我看日程", "--json"],
            self._handler({"routine_propose": draft}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), draft)
        self.assertEqual(err, "")

    def test_propose_unexpected_shape_fails_closed(self):
        code, out, err = self._run(
            ["routine", "propose", "每天早上8点提醒我看日程"],
            self._handler({"routine_propose": ["not", "a", "dict"]}),
        )
        self.assertEqual(code, 1, err)
        self.assertIn("无法识别的结果", err)
        self.assertEqual(out, "")

    # -- propose: input validation ---------------------------------------------

    def test_propose_empty_text_is_human_guidance(self):
        code, out, err = self._run(
            ["routine", "propose", ""],
            self._handler({}),
        )
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn("zn: error: 请用一句话描述这个例行任务", err)
        self.assertIn('zn routine propose "每天早上8点提醒我看日程"', err)
        self.assertEqual(self.calls, [])

    def test_propose_missing_text_arg_exits_2(self):
        handler = self._handler({})
        with self.assertRaises(SystemExit) as caught:
            self._run(["routine", "propose"], handler)
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])

    # -- propose: offline / server errors ---------------------------------------

    def test_propose_offline_claims_nothing(self):
        code, out, err = self._run(
            ["routine", "propose", "每天早上8点提醒我看日程"], self._refused
        )
        self.assertEqual(code, 0, err)
        self.assertIn("unreachable", out)
        self.assertIn("没能生成例行任务草稿", out)
        self.assertNotIn("草稿已生成", out)
        self.assertEqual(err, "")

    def test_propose_offline_json(self):
        code, out, err = self._run(
            ["routine", "propose", "每天早上8点提醒我看日程", "--json"],
            self._refused,
        )
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertFalse(data["daemon_reachable"])
        self.assertIsNone(data["draft"])
        self.assertEqual(err, "")

    def test_propose_server_rejection_humanized(self):
        code, out, err = self._run(
            ["routine", "propose", "每天早上8点提醒我看日程"],
            self._handler(
                {
                    "routine_propose": self._rejected(
                        "ValueError: routine_propose requires text"
                    )
                }
            ),
        )
        self.assertEqual(code, 1, err)
        self.assertIn("请用一句话描述这个例行任务", err)
        self.assertIn("routine_propose requires text", err)
        self.assertNotIn("草稿已生成", out)

    # -- propose: TTY niceties ----------------------------------------------------

    def test_propose_tty_prints_next_step_hint(self):
        code, out, err = self._run_on_tty(
            ["routine", "propose", "每天早上8点提醒我看日程"],
            self._handler({"routine_propose": self._draft()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("zn routine confirm --draft-file draft.json", out)
        self.assertIn("\x1b[2m", out)

    def test_propose_pipe_has_no_hint(self):
        code, out, err = self._run(
            ["routine", "propose", "每天早上8点提醒我看日程"],
            self._handler({"routine_propose": self._draft()}),
        )
        self.assertEqual(code, 0, err)
        self.assertNotIn("zn routine confirm --draft-file", out)
        self.assertNotIn("\x1b[", out + err)

    # -- confirm: happy paths ----------------------------------------------------

    def test_confirm_from_draft_file_creates_routine(self):
        draft = self._draft()
        draft_path = Path(self.tmp.name) / "draft.json"
        draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
        snap = self._snapshot()
        code, out, err = self._run(
            ["routine", "confirm", "--draft-file", str(draft_path)],
            self._handler({"routine_confirm": snap}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(self.calls, [("routine_confirm", {"draft": draft})])
        self.assertIn("例行任务 routine-abc123 已创建", out)
        self.assertIn("[active]", out)
        self.assertIn("每天 08:00", out)
        self.assertEqual(err, "")

    def test_confirm_from_draft_json_string(self):
        draft = self._draft()
        snap = self._snapshot()
        code, out, err = self._run(
            [
                "routine",
                "confirm",
                "--draft-json",
                json.dumps(draft, ensure_ascii=False),
            ],
            self._handler({"routine_confirm": snap}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(self.calls, [("routine_confirm", {"draft": draft})])
        self.assertIn("已创建", out)
        self.assertEqual(err, "")

    def test_confirm_json_passes_rpc_result_through(self):
        draft = self._draft()
        snap = self._snapshot()
        draft_path = Path(self.tmp.name) / "draft.json"
        draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
        code, out, err = self._run(
            ["routine", "confirm", "--draft-file", str(draft_path), "--json"],
            self._handler({"routine_confirm": snap}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), snap)
        self.assertEqual(err, "")

    def test_confirm_unexpected_shape_fails_closed(self):
        draft = self._draft()
        code, out, err = self._run(
            ["routine", "confirm", "--draft-json", json.dumps(draft)],
            self._handler({"routine_confirm": []}),
        )
        self.assertEqual(code, 1, err)
        self.assertIn("无法识别的结果", err)
        self.assertEqual(out, "")

    # -- confirm: draft source validation -----------------------------------------

    def test_confirm_missing_draft_source_exits_2(self):
        handler = self._handler({})
        with self.assertRaises(SystemExit) as caught:
            self._run(["routine", "confirm"], handler)
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])

    def test_confirm_both_draft_sources_exits_2(self):
        handler = self._handler({})
        with self.assertRaises(SystemExit) as caught:
            self._run(
                [
                    "routine",
                    "confirm",
                    "--draft-json",
                    "{}",
                    "--draft-file",
                    "draft.json",
                ],
                handler,
            )
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])

    def test_confirm_missing_draft_file_humanized(self):
        missing = str(Path(self.tmp.name) / "no-such-draft.json")
        code, out, err = self._run(
            ["routine", "confirm", "--draft-file", missing],
            self._handler({}),
        )
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn("zn: error: 找不到草稿文件", err)
        self.assertIn("file not found", err)
        self.assertEqual(self.calls, [])

    def test_confirm_bad_json_file_humanized(self):
        draft_path = Path(self.tmp.name) / "draft.json"
        draft_path.write_text("{not valid json", encoding="utf-8")
        code, out, err = self._run(
            ["routine", "confirm", "--draft-file", str(draft_path)],
            self._handler({}),
        )
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn("zn: error:", err)
        self.assertIn("不是合法 JSON", err)
        self.assertEqual(self.calls, [])

    def test_confirm_non_object_draft_humanized(self):
        code, out, err = self._run(
            ["routine", "confirm", "--draft-json", "[1, 2, 3]"],
            self._handler({}),
        )
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn("zn: error:", err)
        self.assertIn("必须是 JSON 对象", err)
        self.assertIn("draft must be an object", err)
        self.assertEqual(self.calls, [])

    def test_confirm_bad_draft_json_string_humanized(self):
        code, out, err = self._run(
            ["routine", "confirm", "--draft-json", "{oops"],
            self._handler({}),
        )
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn("不是合法 JSON", err)
        self.assertEqual(self.calls, [])

    # -- confirm: server rejections humanized, exit 1 -------------------------------

    def test_confirm_empty_task_rejection_humanized(self):
        draft = self._draft(task="")
        code, out, err = self._run(
            ["routine", "confirm", "--draft-json", json.dumps(draft)],
            self._handler(
                {
                    "routine_confirm": self._rejected(
                        "ValueError: routine task must not be empty"
                    )
                }
            ),
        )
        self.assertEqual(code, 1, err)
        self.assertIn("zn: error: 草稿里没有任务内容", err)
        self.assertIn("routine task must not be empty", err)
        self.assertNotIn("已创建", out)

    def test_confirm_missing_schedule_rejection_humanized(self):
        draft = self._draft(schedule_kind="", cron_expression=None)
        code, out, err = self._run(
            ["routine", "confirm", "--draft-json", json.dumps(draft)],
            self._handler(
                {
                    "routine_confirm": self._rejected(
                        "ValueError: routine draft has no parsed schedule"
                    )
                }
            ),
        )
        self.assertEqual(code, 1, err)
        self.assertIn("zn: error: 草稿里没有可用的时间计划", err)
        self.assertIn("routine draft has no parsed schedule", err)
        self.assertNotIn("已创建", out)

    def test_confirm_other_server_error_unchanged(self):
        draft = self._draft()
        code, out, err = self._run(
            ["routine", "confirm", "--draft-json", json.dumps(draft)],
            self._handler(
                {
                    "routine_confirm": self._rejected(
                        "RuntimeError: trigger registration failed"
                    )
                }
            ),
        )
        self.assertEqual(code, 1, err)
        self.assertIn(
            "服务端返回错误（routine_confirm）：RuntimeError: trigger registration failed",
            err,
        )
        self.assertNotIn("已创建", out)

    # -- confirm: offline -> exit 0, nothing claimed ---------------------------------

    def test_confirm_offline_claims_nothing(self):
        draft = self._draft()
        code, out, err = self._run(
            ["routine", "confirm", "--draft-json", json.dumps(draft)],
            self._refused,
        )
        self.assertEqual(code, 0, err)
        self.assertIn("unreachable", out)
        self.assertIn("没有创建任何例行任务", out)
        self.assertNotIn("已创建", out)
        self.assertEqual(err, "")

    def test_confirm_offline_json(self):
        draft = self._draft()
        code, out, err = self._run(
            ["routine", "confirm", "--draft-json", json.dumps(draft), "--json"],
            self._refused,
        )
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertFalse(data["daemon_reachable"])
        self.assertFalse(data["changed"])
        self.assertIsNone(data["routine"])
        self.assertEqual(err, "")

    # -- confirm: TTY niceties ----------------------------------------------------------

    def test_confirm_tty_prints_list_hint(self):
        draft = self._draft()
        code, out, err = self._run_on_tty(
            ["routine", "confirm", "--draft-json", json.dumps(draft)],
            self._handler({"routine_confirm": self._snapshot()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("用 `zn routine list` 查看已创建的例行任务", out)
        self.assertIn("\x1b[2m", out)


class ZnCliWorkDetachT20Tests(_CliHarness):
    """T20: ``zn work detach`` -- terminal entry for detaching a workspace.

    The inverse of T16's ``zn work attach``. New test class (Floor Guard:
    existing tests and assertions untouched).
    """

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

    def _argv(self, extra=()):
        return ["work", "detach", "--thread-id", "t1", *extra]

    def _result(self, **overrides):
        # after a detach the snapshot's metadata has no "workspace" entry
        # (daemon.py pops it before saving the thread)
        result = {
            "id": "t1",
            "title": "Thread",
            "created_at": "2026-10-22T01:00:00Z",
            "updated_at": "2026-10-22T03:00:00Z",
            "active_run": None,
            "messages": [],
            "artifacts": [],
            "metadata": {},
        }
        result.update(overrides)
        return result

    # -- happy paths ---------------------------------------------------------

    def test_detach_success_prints_human_line(self):
        code, out, err = self._run(
            self._argv(),
            self._handler({"work_detach_workspace": self._result()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("detached workspace from thread=t1", out)
        self.assertIn("该线程已不再关联工作区目录", out)
        self.assertEqual(
            self.calls,
            [
                (
                    "work_detach_workspace",
                    {"thread_id": "t1"},
                )
            ],
        )

    def test_detach_sends_exact_single_key_rpc_schema(self):
        # the daemon's work_detach_workspace RPC accepts exactly {thread_id};
        # the client must not send a path or anything else
        self._run(self._argv(), self._handler({"work_detach_workspace": self._result()}))
        self.assertEqual(self.calls, [("work_detach_workspace", {"thread_id": "t1"})])
        for _, params in self.calls:
            self.assertEqual(set(params), {"thread_id"})

    def test_detach_json_passes_rpc_result_through(self):
        payload = self._result()
        code, out, err = self._run(
            self._argv(extra=["--json"]),
            self._handler({"work_detach_workspace": payload}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), payload)
        self.assertIn('"id"', out)

    def test_detach_malformed_result_humanized(self):
        code, out, err = self._run(
            self._argv(),
            self._handler({"work_detach_workspace": {"id": 42, "metadata": {}}}),
        )
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn(
            "zn: error: 服务返回了无法识别的结果（unexpected work_detach_workspace result",
            err,
        )

    def test_detach_tty_hint_behind_use_color(self):
        code, out, err = self._run_on_tty(
            self._argv(),
            self._handler({"work_detach_workspace": self._result()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("用 `zn work get --thread-id t1` 查看线程状态", out)
        self.assertIn("\x1b[2m", out)

    def test_detach_no_hint_on_pipe(self):
        code, out, err = self._run(
            self._argv(),
            self._handler({"work_detach_workspace": self._result()}),
        )
        self.assertEqual(code, 0, err)
        self.assertNotIn("zn work get --thread-id", out)
        self.assertNotIn("\x1b[", out + err)

    def test_detach_no_hint_with_no_color(self):
        code, out, err = self._run_on_tty(
            self._argv(),
            self._handler({"work_detach_workspace": self._result()}),
            no_color=True,
        )
        self.assertEqual(code, 0, err)
        self.assertNotIn("zn work get --thread-id", out)
        self.assertNotIn("\x1b[", out + err)

    # -- argparse: missing --thread-id exits 2 --------------------------------

    def test_missing_thread_id_exits_2(self):
        handler = self._handler({})
        with self.assertRaises(SystemExit) as caught:
            self._run(["work", "detach"], handler)
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])

    def test_blank_thread_id_exits_2(self):
        handler = self._handler({})
        with self.assertRaises(SystemExit) as caught:
            self._run(["work", "detach", "--thread-id", "  "], handler)
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])

    # -- T2-6: unreachable resident -> exit 0, nothing claimed ------------------

    def test_offline_claims_nothing(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(self._argv(), refused)
        self.assertEqual(code, 0, err)
        self.assertIn("常驻服务未运行", out)
        self.assertIn("没有给线程解绑工作区", out)
        self.assertIn("未生效", out)
        self.assertNotIn("detached workspace from thread=t1", out)

    def test_offline_json(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(self._argv(extra=["--json"]), refused)
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertFalse(data["daemon_reachable"])
        self.assertFalse(data["detached"])
        self.assertEqual(data["thread_id"], "t1")

    # -- T2-5: server rejections humanized, exit 1 -------------------------------

    def test_unknown_thread_humanized(self):
        handler = self._handler(
            {
                "work_detach_workspace": (
                    False,
                    None,
                    "ValueError: unknown work thread: t9",
                )
            }
        )
        code, out, err = self._run(
            ["work", "detach", "--thread-id", "t9"], handler
        )
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn("zn: error: 找不到这个工作线程（unknown work thread）", err)
        self.assertIn("t9", err)
        self.assertIn("zn work list", err)
        self.assertNotIn("服务端返回错误", err)

    def test_other_server_error_unchanged(self):
        handler = self._handler(
            {
                "work_detach_workspace": (
                    False,
                    None,
                    "RuntimeError: something exploded",
                )
            }
        )
        code, out, err = self._run(self._argv(), handler)
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn("something exploded", err)
        self.assertNotIn("找不到这个工作线程", err)

    # -- epilog carries a real runnable example (no drift) -----------------------

    def test_detach_epilog_example_is_real_command(self):
        parser = build_parser()
        work = parser._subparsers._group_actions[0].choices["work"]
        detach = work._subparsers._group_actions[0].choices["detach"]
        self.assertIn("zn work detach --thread-id <thread-id>", detach.epilog)


class ZnCliWorkRestoreT21Tests(_CliHarness):
    """T21: ``zn work restore-prepare`` / ``restore-approve`` / ``restore-application``.

    Terminal entries for the daemon's ``work_restore_prepare``,
    ``work_restore_approve`` and ``work_restore_application`` RPCs -- the
    three-step missing-file restore flow. New test class (Floor Guard:
    existing tests and assertions untouched).
    """

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

    def _application(self, **overrides):
        # mirrors work_restore_application_resident._application_public
        result = {
            "application_id": "restore-app-1",
            "restore_point_id": "rp-1",
            "thread_id": "t1",
            "event_id": "ev-1",
            "target_path": "C:\\work\\notes.txt",
            "status": "approval_required",
            "requires_user_approval": True,
            "fresh_revalidation_required": True,
            "automatic_authority": False,
            "error": None,
            "created_at": "2026-10-23T05:00:00Z",
            "updated_at": "2026-10-23T05:00:00Z",
            "completed_at": None,
        }
        result.update(overrides)
        return result

    def _prepare_argv(self, extra=()):
        return ["work", "restore-prepare", "--thread-id", "t1",
                "--restore-point-id", "rp-1", *extra]

    def _approve_argv(self, extra=()):
        return ["work", "restore-approve", "--thread-id", "t1",
                "--application-id", "restore-app-1", *extra]

    def _application_argv(self, extra=()):
        return ["work", "restore-application",
                "--application-id", "restore-app-1", *extra]

    # -- restore-prepare: happy paths -----------------------------------------

    def test_prepare_success_prints_human_line(self):
        code, out, err = self._run(
            self._prepare_argv(),
            self._handler({"work_restore_prepare": self._application()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("restore prepare: 缺文件恢复申请已创建", out)
        self.assertIn("application=restore-app-1", out)
        self.assertIn("目标文件：C:\\work\\notes.txt", out)
        self.assertIn("状态：等待审批（approval_required）", out)
        self.assertEqual(
            self.calls,
            [
                (
                    "work_restore_prepare",
                    {"thread_id": "t1", "restore_point_id": "rp-1"},
                )
            ],
        )

    def test_prepare_sends_exact_two_key_rpc_schema(self):
        # the daemon's work_restore_prepare RPC accepts exactly
        # {thread_id, restore_point_id}; the client must not send extras
        self._run(self._prepare_argv(), self._handler({"work_restore_prepare": self._application()}))
        self.assertEqual(
            self.calls,
            [("work_restore_prepare", {"thread_id": "t1", "restore_point_id": "rp-1"})],
        )
        for _, params in self.calls:
            self.assertEqual(set(params), {"thread_id", "restore_point_id"})

    def test_prepare_json_passes_rpc_result_through(self):
        payload = self._application()
        code, out, err = self._run(
            self._prepare_argv(extra=["--json"]),
            self._handler({"work_restore_prepare": payload}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), payload)
        self.assertIn('"application_id"', out)

    def test_prepare_malformed_result_humanized(self):
        code, out, err = self._run(
            self._prepare_argv(),
            self._handler({"work_restore_prepare": {"application_id": 42}}),
        )
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn(
            "zn: error: 服务返回了无法识别的结果（unexpected work_restore_prepare result",
            err,
        )

    def test_prepare_tty_hint_behind_use_color(self):
        code, out, err = self._run_on_tty(
            self._prepare_argv(),
            self._handler({"work_restore_prepare": self._application()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn(
            "zn work restore-approve --thread-id t1 --application-id restore-app-1",
            out,
        )
        self.assertIn("\x1b[2m", out)

    def test_prepare_no_hint_on_pipe(self):
        code, out, err = self._run(
            self._prepare_argv(),
            self._handler({"work_restore_prepare": self._application()}),
        )
        self.assertEqual(code, 0, err)
        self.assertNotIn("zn work restore-approve", out)
        self.assertNotIn("\x1b[", out + err)

    def test_prepare_no_hint_with_no_color(self):
        code, out, err = self._run_on_tty(
            self._prepare_argv(),
            self._handler({"work_restore_prepare": self._application()}),
            no_color=True,
        )
        self.assertEqual(code, 0, err)
        self.assertNotIn("zn work restore-approve", out)
        self.assertNotIn("\x1b[", out + err)

    # -- restore-prepare: argparse: missing args exit 2 ------------------------

    def test_prepare_missing_args_exit_2(self):
        handler = self._handler({})
        for argv in (
            ["work", "restore-prepare"],
            ["work", "restore-prepare", "--thread-id", "t1"],
            ["work", "restore-prepare", "--restore-point-id", "rp-1"],
        ):
            with self.assertRaises(SystemExit) as caught:
                self._run(argv, handler)
            self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])

    def test_prepare_blank_args_exit_2(self):
        handler = self._handler({})
        with self.assertRaises(SystemExit) as caught:
            self._run(
                ["work", "restore-prepare", "--thread-id", "t1",
                 "--restore-point-id", "  "],
                handler,
            )
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])

    # -- restore-prepare: T2-6 offline ----------------------------------------

    def test_offline_prepare_claims_nothing(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(self._prepare_argv(), refused)
        self.assertEqual(code, 0, err)
        self.assertIn("常驻服务未运行", out)
        self.assertIn("没有创建缺文件恢复申请", out)
        self.assertIn("未发出", out)
        self.assertNotIn("缺文件恢复申请已创建", out)

    def test_offline_prepare_json(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(self._prepare_argv(extra=["--json"]), refused)
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertFalse(data["daemon_reachable"])
        self.assertFalse(data["prepared"])
        self.assertEqual(data["thread_id"], "t1")
        self.assertEqual(data["restore_point_id"], "rp-1")

    # -- restore-prepare: T2-5 server rejections --------------------------------

    def test_prepare_unknown_thread_humanized(self):
        handler = self._handler(
            {
                "work_restore_prepare": (
                    False,
                    None,
                    "ValueError: unknown work thread: t9",
                )
            }
        )
        code, out, err = self._run(
            ["work", "restore-prepare", "--thread-id", "t9",
             "--restore-point-id", "rp-1"],
            handler,
        )
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn("zn: error: 找不到这个工作线程（unknown work thread）", err)
        self.assertIn("t9", err)
        self.assertIn("zn work list", err)
        self.assertNotIn("服务端返回错误", err)

    def test_prepare_unknown_restore_point_humanized(self):
        handler = self._handler(
            {
                "work_restore_prepare": (
                    False,
                    None,
                    "ValueError: unknown Work restore point for thread",
                )
            }
        )
        code, out, err = self._run(self._prepare_argv(), handler)
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn("zn: error: 找不到这个恢复点（unknown Work restore point）", err)
        self.assertIn("rp-1", err)
        self.assertIn("zn work get --thread-id", err)
        self.assertNotIn("服务端返回错误", err)

    def test_prepare_windows_only_humanized_no_traceback(self):
        handler = self._handler(
            {
                "work_restore_prepare": (
                    False,
                    None,
                    "RuntimeError: missing-file Work restore application "
                    "currently requires Windows",
                )
            }
        )
        code, out, err = self._run(self._prepare_argv(), handler)
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn("缺文件恢复目前只支持 Windows", err)
        self.assertIn("currently requires Windows", err)
        self.assertIn("这台机器用不了这条路", err)
        self.assertNotIn("Traceback", err)
        self.assertNotIn("Traceback", out)

    def test_prepare_other_server_error_unchanged(self):
        handler = self._handler(
            {
                "work_restore_prepare": (
                    False,
                    None,
                    "RuntimeError: something exploded",
                )
            }
        )
        code, out, err = self._run(self._prepare_argv(), handler)
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn("something exploded", err)
        self.assertNotIn("找不到这个工作线程", err)
        self.assertNotIn("缺文件恢复目前只支持 Windows", err)

    # -- restore-approve: happy paths -------------------------------------------

    def test_approve_success_prints_human_line(self):
        code, out, err = self._run(
            self._approve_argv(),
            self._handler({"work_restore_approve": self._application()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("restore approve: 恢复申请已审批", out)
        self.assertIn("application=restore-app-1", out)
        self.assertIn("状态：approval_required", out)
        self.assertEqual(
            self.calls,
            [
                (
                    "work_restore_approve",
                    {"thread_id": "t1", "application_id": "restore-app-1"},
                )
            ],
        )

    def test_approve_sends_exact_two_key_rpc_schema(self):
        self._run(self._approve_argv(), self._handler({"work_restore_approve": self._application()}))
        for _, params in self.calls:
            self.assertEqual(set(params), {"thread_id", "application_id"})

    def test_approve_json_passes_rpc_result_through(self):
        payload = self._application()
        code, out, err = self._run(
            self._approve_argv(extra=["--json"]),
            self._handler({"work_restore_approve": payload}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), payload)

    def test_approve_malformed_result_humanized(self):
        code, out, err = self._run(
            self._approve_argv(),
            self._handler({"work_restore_approve": {"status": "completed"}}),
        )
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn(
            "zn: error: 服务返回了无法识别的结果（unexpected work_restore_approve result",
            err,
        )

    def test_approve_tty_hint_points_to_application(self):
        code, out, err = self._run_on_tty(
            self._approve_argv(),
            self._handler({"work_restore_approve": self._application()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn(
            "zn work restore-application --application-id restore-app-1", out
        )
        self.assertIn("\x1b[2m", out)

    def test_approve_no_hint_on_pipe(self):
        code, out, err = self._run(
            self._approve_argv(),
            self._handler({"work_restore_approve": self._application()}),
        )
        self.assertEqual(code, 0, err)
        self.assertNotIn("zn work restore-application", out)
        self.assertNotIn("\x1b[", out + err)

    # -- restore-approve: argparse / offline / rejections ------------------------

    def test_approve_missing_args_exit_2(self):
        handler = self._handler({})
        for argv in (
            ["work", "restore-approve"],
            ["work", "restore-approve", "--thread-id", "t1"],
            ["work", "restore-approve", "--application-id", "restore-app-1"],
        ):
            with self.assertRaises(SystemExit) as caught:
                self._run(argv, handler)
            self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])

    def test_offline_approve_claims_nothing(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(self._approve_argv(), refused)
        self.assertEqual(code, 0, err)
        self.assertIn("常驻服务未运行", out)
        self.assertIn("没有审批这个恢复申请", out)
        self.assertIn("未生效", out)
        self.assertNotIn("恢复申请已审批", out)

    def test_offline_approve_json(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(self._approve_argv(extra=["--json"]), refused)
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertFalse(data["daemon_reachable"])
        self.assertFalse(data["approved"])
        self.assertEqual(data["application_id"], "restore-app-1")

    def test_approve_unknown_application_humanized(self):
        handler = self._handler(
            {
                "work_restore_approve": (
                    False,
                    None,
                    "ValueError: unknown Work restore application for thread",
                )
            }
        )
        code, out, err = self._run(self._approve_argv(), handler)
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn(
            "zn: error: 找不到这个恢复申请（unknown Work restore application）", err
        )
        self.assertIn("restore-app-1", err)
        self.assertNotIn("服务端返回错误", err)

    def test_approve_windows_only_humanized_no_traceback(self):
        handler = self._handler(
            {
                "work_restore_approve": (
                    False,
                    None,
                    "RuntimeError: missing-file Work restore application "
                    "currently requires Windows",
                )
            }
        )
        code, out, err = self._run(self._approve_argv(), handler)
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn("缺文件恢复目前只支持 Windows", err)
        self.assertIn("currently requires Windows", err)
        self.assertIn("这台机器用不了这条路", err)
        self.assertNotIn("Traceback", err)

    def test_approve_other_server_error_unchanged(self):
        handler = self._handler(
            {
                "work_restore_approve": (
                    False,
                    None,
                    "RuntimeError: something exploded",
                )
            }
        )
        code, out, err = self._run(self._approve_argv(), handler)
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn("something exploded", err)
        self.assertNotIn("找不到这个恢复申请", err)

    # -- restore-application: status reporting -------------------------------------

    def test_application_completed_reports_done(self):
        payload = self._application(
            status="completed",
            requires_user_approval=False,
            fresh_revalidation_required=False,
            completed_at="2026-10-23T05:01:00Z",
        )
        code, out, err = self._run(
            self._application_argv(),
            self._handler({"work_restore_application": payload}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("restore application: application=restore-app-1", out)
        self.assertIn("目标文件：C:\\work\\notes.txt", out)
        self.assertIn("状态：已完成（completed）", out)
        self.assertIn("目标文件已恢复", out)
        self.assertEqual(
            self.calls,
            [("work_restore_application", {"application_id": "restore-app-1"})],
        )

    def test_application_sends_exact_single_key_rpc_schema(self):
        self._run(
            self._application_argv(),
            self._handler({"work_restore_application": self._application()}),
        )
        for _, params in self.calls:
            self.assertEqual(set(params), {"application_id"})

    def test_application_json_passes_rpc_result_through(self):
        payload = self._application(status="completed", requires_user_approval=False)
        code, out, err = self._run(
            self._application_argv(extra=["--json"]),
            self._handler({"work_restore_application": payload}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), payload)

    def test_application_pending_points_back_to_approve_on_tty(self):
        code, out, err = self._run_on_tty(
            self._application_argv(),
            self._handler({"work_restore_application": self._application()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("状态：等待审批（approval_required）", out)
        self.assertIn(
            "zn work restore-approve --thread-id t1 --application-id restore-app-1",
            out,
        )
        self.assertIn("\x1b[2m", out)

    def test_application_pending_no_hint_on_pipe(self):
        code, out, err = self._run(
            self._application_argv(),
            self._handler({"work_restore_application": self._application()}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("状态：等待审批（approval_required）", out)
        self.assertNotIn("zn work restore-approve", out)
        self.assertNotIn("\x1b[", out + err)

    def test_application_error_reports_human_reason(self):
        payload = self._application(
            status="blocked",
            requires_user_approval=False,
            fresh_revalidation_required=False,
            error="durable restore bytes failed integrity verification",
        )
        code, out, err = self._run(
            self._application_argv(),
            self._handler({"work_restore_application": payload}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("状态：blocked", out)
        self.assertIn(
            "失败原因：durable restore bytes failed integrity verification", out
        )
        self.assertNotIn("zn work restore-approve", out)

    def test_application_malformed_result_humanized(self):
        code, out, err = self._run(
            self._application_argv(),
            self._handler({"work_restore_application": {"application_id": 42}}),
        )
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn(
            "zn: error: 服务返回了无法识别的结果（unexpected work_restore_application result",
            err,
        )

    def test_application_unknown_application_humanized(self):
        handler = self._handler(
            {
                "work_restore_application": (
                    False,
                    None,
                    "ValueError: unknown Work restore application",
                )
            }
        )
        code, out, err = self._run(self._application_argv(), handler)
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn(
            "zn: error: 找不到这个恢复申请（unknown Work restore application）", err
        )
        self.assertNotIn("服务端返回错误", err)

    def test_application_missing_args_exit_2(self):
        handler = self._handler({})
        with self.assertRaises(SystemExit) as caught:
            self._run(["work", "restore-application"], handler)
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])

    def test_offline_application_claims_nothing(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(self._application_argv(), refused)
        self.assertEqual(code, 0, err)
        self.assertIn("常驻服务未运行", out)
        self.assertIn("没有查到恢复申请的状态", out)
        self.assertIn("未完成", out)

    def test_offline_application_json(self):
        def refused(method, params):
            raise socket.error("connection refused")

        code, out, err = self._run(self._application_argv(extra=["--json"]), refused)
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertFalse(data["daemon_reachable"])
        self.assertEqual(data["application_id"], "restore-app-1")

    # -- epilog carries real runnable examples (no drift) --------------------------

    def _epilog_choices(self):
        parser = build_parser()
        work = parser._subparsers._group_actions[0].choices["work"]
        return work._subparsers._group_actions[0].choices

    def test_prepare_epilog_example_is_real_command(self):
        self.assertIn(
            "zn work restore-prepare --thread-id <thread-id> "
            "--restore-point-id <restore-point-id>",
            self._epilog_choices()["restore-prepare"].epilog,
        )

    def test_approve_epilog_example_is_real_command(self):
        self.assertIn(
            "zn work restore-approve --thread-id <thread-id> "
            "--application-id <application-id>",
            self._epilog_choices()["restore-approve"].epilog,
        )

    def test_application_epilog_example_is_real_command(self):
        self.assertIn(
            "zn work restore-application --application-id <application-id>",
            self._epilog_choices()["restore-application"].epilog,
        )
