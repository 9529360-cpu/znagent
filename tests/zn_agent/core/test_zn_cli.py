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
            finally:
                _best_effort_shutdown(endpoint_path)
                thread.join(timeout=10.0)
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
