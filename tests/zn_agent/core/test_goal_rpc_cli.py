"""M16: goal_list / goal_status daemon RPCs + `zn goal list|status` CLI.

Covers both ends:
- daemon.py dispatches goal_list/goal_status to the M-14 SelfDriveDriver
  (resident.self_drive), honestly reporting {"enabled": False, ...} when
  self-drive was never installed instead of an empty list;
- zn_cli.py renders `zn goal list [--limit] [--json]` and
  `zn goal status [--json]`; --json prints the raw RPC payload.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime" / "python"))

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.self_drive import install_self_drive_behavior
from zn_agent.core.zn_cli import _EMPTY_RESULT_HINTS, run

_SECRET = "0f2e9a4c6b1d8f3e5a7c9d0b2e4f6a8c1d3e5f7a9b0c2d4e6f8a0b1c3d5e7f9"


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


class _GoalCliHarness(unittest.TestCase):
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

    def _run(self, argv, handler):
        def connect(address, timeout=None):
            return _FakeSocket(handler)

        with (
            mock.patch("socket.create_connection", side_effect=connect),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            code = run(["--endpoint", str(self.endpoint_path), *argv])
        return code, stdout.getvalue(), stderr.getvalue()


class GoalRpcTests(unittest.TestCase):
    """M16: daemon goal_list/goal_status wired to the M-14 driver."""

    @staticmethod
    def _server(tmp: str):
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=Path(tmp) / "kernel.db",
        )
        server = ResidentRpcServer(
            resident=resident,
            input_stream=io.StringIO(),
            output_stream=io.StringIO(),
        )
        return resident, server

    def _ok(self, server, method, params):
        response = server.handle({"id": "1", "method": method, "params": params})
        self.assertTrue(response["ok"], response)
        return response["result"]

    def test_goal_list_empty_when_installed_but_no_goals(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, server = self._server(tmp)
            try:
                install_self_drive_behavior(resident)
                result = self._ok(server, "goal_list", {})
                self.assertEqual(
                    result, {"enabled": True, "goals": []}
                )
            finally:
                resident.store.close()

    def test_goal_list_reports_submitted_goal(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, server = self._server(tmp)
            try:
                driver = install_self_drive_behavior(resident)
                intention = driver.submit_goal("整理书架", acceptance=["书架整齐"])
                result = self._ok(server, "goal_list", {})
                self.assertTrue(result["enabled"])
                self.assertEqual(len(result["goals"]), 1)
                goal = result["goals"][0]
                self.assertEqual(goal["intention_id"], intention.intention_id)
                self.assertEqual(goal["status"], "active")
                self.assertEqual(goal["objective"], "整理书架")
                # Limit clamps to a minimum of 1 server-side; a larger limit
                # passes through to the driver.
                limited = self._ok(server, "goal_list", {"limit": 1})
                self.assertEqual(len(limited["goals"]), 1)
            finally:
                resident.store.close()

    def test_goal_status_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, server = self._server(tmp)
            try:
                driver = install_self_drive_behavior(resident)
                driver.submit_goal("整理书架", acceptance=["书架整齐"])
                result = self._ok(server, "goal_status", {})
                self.assertTrue(result["enabled"])
                self.assertEqual(len(result["goals"]), 1)
                self.assertIn("recent_errors", result)
                self.assertIn("recent_notes", result)
            finally:
                resident.store.close()

    def test_goal_list_not_installed_reports_disabled_not_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, server = self._server(tmp)
            try:
                # The product resident installs self-drive at construction;
                # removing the attribute reproduces a resident that never
                # installed it -- the RPC must report disabled, not [].
                delattr(resident, "self_drive")
                self.assertIsNone(getattr(resident, "self_drive", None))
                result = self._ok(server, "goal_list", {})
                self.assertFalse(result["enabled"])
                self.assertIn("not installed", result["reason"])
                self.assertNotIn("goals", result)
            finally:
                resident.store.close()

    def test_goal_status_not_installed_reports_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, server = self._server(tmp)
            try:
                delattr(resident, "self_drive")
                result = self._ok(server, "goal_status", {})
                self.assertFalse(result["enabled"])
                self.assertIn("not installed", result["reason"])
            finally:
                resident.store.close()

    def test_goal_list_rejects_unknown_params(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, server = self._server(tmp)
            try:
                install_self_drive_behavior(resident)
                with self.assertRaises(ValueError):
                    server.handle(
                        {"id": "1", "method": "goal_list", "params": {"bogus": 1}}
                    )
            finally:
                resident.store.close()

    def test_goal_status_rejects_params(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, server = self._server(tmp)
            try:
                install_self_drive_behavior(resident)
                with self.assertRaises(ValueError):
                    server.handle(
                        {"id": "1", "method": "goal_status", "params": {"limit": 5}}
                    )
            finally:
                resident.store.close()


class ZnCliGoalTests(_GoalCliHarness):
    """M16: `zn goal list|status` CLI rendering and --json passthrough."""

    def test_goal_list_prints_goal_line(self):
        goals = [
            {
                "intention_id": "goal-1",
                "status": "active",
                "objective": "整理书架",
                "origin": "user",
                "generation": 2,
                "blocked_reason": None,
                "steps": 3,
            }
        ]
        code, out, err = self._run(
            ["goal", "list"],
            self._handler({"goal_list": {"enabled": True, "goals": goals}}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("goal-1", out)
        self.assertIn("active", out)
        self.assertIn("整理书架", out)
        self.assertEqual(self.calls, [("goal_list", {"limit": 50})])

    def test_goal_list_respects_limit_and_json(self):
        goals = [{"intention_id": "g", "status": "active"}]
        code, out, err = self._run(
            ["goal", "list", "--limit", "10"],
            self._handler({"goal_list": {"enabled": True, "goals": goals}}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(self.calls, [("goal_list", {"limit": 10})])

        code, out, err = self._run(
            ["goal", "list", "--json"],
            self._handler({"goal_list": {"enabled": True, "goals": goals}}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), goals)

    def test_goal_list_empty(self):
        code, out, err = self._run(
            ["goal", "list"],
            self._handler({"goal_list": {"enabled": True, "goals": []}}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("no self-drive goals", out)

    def test_goal_list_not_installed_is_honest_error(self):
        code, out, err = self._run(
            ["goal", "list"],
            self._handler(
                {
                    "goal_list": {
                        "enabled": False,
                        "reason": "self-drive is not installed on this resident",
                    }
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("not installed", err)

    def test_goal_status_prints_counts_and_active_goal(self):
        payload = {
            "enabled": True,
            "goals": [
                {
                    "intention_id": "goal-1",
                    "status": "active",
                    "objective": "整理书架",
                    "origin": "user",
                    "generation": 2,
                    "blocked_reason": None,
                    "steps": 3,
                },
                {
                    "intention_id": "goal-0",
                    "status": "completed",
                    "objective": "旧目标",
                    "origin": "resident",
                    "generation": 1,
                    "blocked_reason": None,
                    "steps": 5,
                },
            ],
            "recent_errors": ["drive exploded once"],
            "recent_notes": ["note one", "note two"],
        }
        code, out, err = self._run(
            ["goal", "status"], self._handler({"goal_status": payload})
        )
        self.assertEqual(code, 0, err)
        self.assertIn("2 goal(s), 1 active", out)
        self.assertIn("整理书架", out)
        self.assertIn("recent errors: 1", out)
        self.assertIn("recent notes: 2", out)
        self.assertEqual(self.calls, [("goal_status", {})])

    def test_goal_status_json(self):
        payload = {
            "enabled": True,
            "goals": [],
            "recent_errors": [],
            "recent_notes": ["hello"],
        }
        code, out, err = self._run(
            ["goal", "status", "--json"], self._handler({"goal_status": payload})
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), payload)

    def test_goal_status_not_installed_is_honest_error(self):
        code, out, err = self._run(
            ["goal", "status"],
            self._handler(
                {
                    "goal_status": {
                        "enabled": False,
                        "reason": "self-drive is not installed on this resident",
                    }
                }
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("not installed", err)

    def test_goal_list_unexpected_result_surfaces(self):
        code, out, err = self._run(
            ["goal", "list"], self._handler({"goal_list": ["not-a-dict"]})
        )
        self.assertEqual(code, 1)
        self.assertIn("unexpected goal_list result", err)


class ZnCliGoalEmptyHintTests(_GoalCliHarness):
    """GOAL-HINT: empty `zn goal list` gets the T3-4 "what next" tail.

    The goal group is read-only (goals are created through chat by the
    engine itself), so the hint names a spoken sentence, not a command.
    ``--json`` and piped output stay byte-identical to before.
    """

    def setUp(self) -> None:
        super().setUp()
        # T3-4 asserts byte-exact "no ..." lines, so the T3-3 first-run
        # probe must not leak into this output: point the home at a temp
        # dir that already holds kernel data (deterministically non-fresh).
        # Mirrors ZnCliNextHintT34Tests in test_zn_cli.py.
        hint_home = Path(self.tmp.name) / "zn-home"
        (hint_home / "kernel").mkdir(parents=True)
        home_env = mock.patch.dict(os.environ, {"ZN_AGENT_HOME": str(hint_home)})
        home_env.start()
        self.addCleanup(home_env.stop)

    def _run_on_tty(self, argv, handler):
        class _Tty(io.StringIO):
            def isatty(self):
                return True

        def connect(address, timeout=None):
            return _FakeSocket(handler)

        tty, stderr = _Tty(), io.StringIO()
        env = {key: value for key, value in os.environ.items() if key != "NO_COLOR"}
        env["TERM"] = "xterm-256color"
        with (
            mock.patch("socket.create_connection", side_effect=connect),
            mock.patch("zn_agent.core.zn_cli.use_color", return_value=True),
            mock.patch(
                "zn_agent.core.zn_cli.colorize",
                side_effect=lambda s, *a, **k: s,
            ),
            mock.patch.dict(os.environ, env, clear=True),
            contextlib.redirect_stdout(tty),
            contextlib.redirect_stderr(stderr),
        ):
            code = run(["--endpoint", str(self.endpoint_path), *argv])
        return code, tty.getvalue(), stderr.getvalue()

    def test_empty_goal_list_prints_next_hint_on_tty(self):
        code, out, err = self._run_on_tty(
            ["goal", "list"],
            self._handler({"goal_list": {"enabled": True, "goals": []}}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("no self-drive goals", out)
        self.assertIn(_EMPTY_RESULT_HINTS["goal_list"], out)

    def test_empty_goal_list_json_is_byte_identical(self):
        code, out, err = self._run(
            ["goal", "list", "--json"],
            self._handler({"goal_list": {"enabled": True, "goals": []}}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "[]\n")
        self.assertNotIn("下一步", out)

    def test_empty_goal_list_pipe_has_no_hint(self):
        code, out, err = self._run(
            ["goal", "list"],
            self._handler({"goal_list": {"enabled": True, "goals": []}}),
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "no self-drive goals\n")
        self.assertNotIn("下一步", out)

    def test_non_empty_goal_list_never_gets_hint_on_tty(self):
        goals = [
            {
                "intention_id": "goal-1",
                "status": "active",
                "objective": "整理书架",
                "origin": "user",
            }
        ]
        code, out, err = self._run_on_tty(
            ["goal", "list"],
            self._handler({"goal_list": {"enabled": True, "goals": goals}}),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("goal-1", out)
        self.assertNotIn("下一步", out)


if __name__ == "__main__":
    unittest.main()
