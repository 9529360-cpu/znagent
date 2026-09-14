from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.long_running_terminal_behavior import (
    _ACCEPTANCE,
    _INSTALL_MARKER,
    _request,
)
from zn_agent.core.provider_bridge import build_resident_runtime


TASK = "请在这个项目里运行 `python -c \"print('done')\"`，等它跑完后把结果告诉我。"


class LongRunningTerminalAdmissionTests(unittest.TestCase):
    @staticmethod
    def _event(task: str, **payload):
        return SimpleNamespace(
            kind="desktop_user_event",
            task=task,
            payload={"workspace_path": "/authorized/workspace", **payload},
        )

    def test_request_requires_one_explicit_inline_command_and_wait_intent(self) -> None:
        admitted = _request(self._event(TASK))
        self.assertIsNotNone(admitted)
        assert admitted is not None
        self.assertEqual(admitted["command"], "python -c \"print('done')\"")

        rejected = (
            "请运行 `python -V`。",
            "等它跑完后告诉我结果。",
            "运行 `python -V` 和 `git status`，等它们跑完。",
            "运行 ```python -V```，等它跑完。",
        )
        for task in rejected:
            with self.subTest(task=task):
                self.assertIsNone(_request(self._event(task)))

        self.assertIsNone(_request(self._event(TASK, body_action="command")))
        self.assertIsNone(
            _request(SimpleNamespace(kind="desktop_user_event", task=TASK, payload={}))
        )


class LongRunningTerminalProductTests(unittest.TestCase):
    @staticmethod
    def _result(*, status: str, session_id: str = "term-e2e22", pid: int = 4242,
                success: bool = True, output: str = "", exit_code=None, error=None,
                dispatch_observed: bool = False):
        data = {
            "status": status,
            "session_id": session_id,
            "pid": pid,
            "truncated": False,
        }
        if exit_code is not None:
            data["exit_code"] = exit_code
        if dispatch_observed:
            data["side_effect_attempt_id"] = "sidefx-e2e22"
            data["side_effect_dispatch_observed"] = True
        return SimpleNamespace(
            success=success,
            output=output,
            data=data,
            error=error,
        )

    @staticmethod
    def _child(ledger, thread_id: str):
        return next(
            item
            for item in ledger.list_work_items(thread_id, limit=64)
            if _ACCEPTANCE in item.acceptance_criteria
        )

    def _runtime(self, root: Path):
        workspace = root / "workspace"
        workspace.mkdir()
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=root / "kernel.db",
        )
        ledger = resident.work_ledger
        ledger.create_thread(thread_id="e2e22", title="Long command")
        ledger.attach_workspace("e2e22", workspace)
        return resident, ledger, workspace

    def test_product_runtime_installs_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, _, _ = self._runtime(Path(tmp))
            try:
                self.assertTrue(getattr(resident, _INSTALL_MARKER, False))
            finally:
                resident.store.close()

    def test_real_background_process_is_polled_to_exit_zero_without_model_wait(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, workspace = self._runtime(Path(tmp))
            executable = str(Path(sys.executable).resolve()).replace("\\", "/")
            release = workspace / "e2e22-release.flag"
            command = (
                f'"{executable}" -c "import time,pathlib; '
                "p=pathlib.Path('e2e22-release.flag'); "
                "exec('while not p.exists():\\n    time.sleep(0.05)'); "
                "print('e2e22-real-done')\""
            )
            task = f"请在这个项目里运行 `{command}`，等它跑完后把结果告诉我。"
            original_act = resident.body.act
            running_polls = 0

            def observed_act(kind, *, event_id=None, **kwargs):
                nonlocal running_polls
                result = original_act(kind, event_id=event_id, **kwargs)
                data = result.data if isinstance(result.data, dict) else {}
                if kind == "terminal_poll" and str(data.get("status") or "").lower() == "running":
                    running_polls += 1
                    if not release.exists():
                        release.write_text("release", encoding="utf-8")
                return result

            try:
                with patch.object(resident.body, "act", side_effect=observed_act):
                    _, run = ledger.submit("e2e22", task)

                self.assertTrue(run.success, run.reason)
                self.assertEqual(run.model_invocations, 0)
                self.assertGreaterEqual(running_polls, 1)
                self.assertIn("e2e22-real-done", run.response)
                child = self._child(ledger, "e2e22")
                self.assertEqual(child.status, "completed")
                evidence = json.loads(child.result)
                self.assertEqual(evidence["status"], "completed")
                self.assertEqual(evidence["exit_code"], 0)
                self.assertGreaterEqual(evidence["poll_count"], 2)
                self.assertEqual(Path(evidence["workspace"]), workspace.resolve())
                self.assertTrue(str(evidence["side_effect_attempt_id"]).startswith("sidefx-"))
                self.assertNotIn("e2e22-real-done", child.result)
                self.assertNotIn(executable, child.result)
            finally:
                resident.store.close()

    def test_command_dispatches_once_then_only_polls_same_session_until_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, workspace = self._runtime(Path(tmp))
            original_act = resident.body.act
            calls: list[tuple[str, dict]] = []
            polls = iter(
                (
                    self._result(status="running", output="half"),
                    self._result(status="completed", output="done\n", exit_code=0),
                )
            )

            def fake_act(kind, *, event_id=None, **kwargs):
                if kind == "command":
                    calls.append((kind, dict(kwargs)))
                    return self._result(status="running", dispatch_observed=True)
                if kind == "terminal_poll":
                    calls.append((kind, dict(kwargs)))
                    return next(polls)
                return original_act(kind, event_id=event_id, **kwargs)

            try:
                with (
                    patch.object(resident.body, "act", side_effect=fake_act),
                    patch("zn_agent.core.long_running_terminal_behavior.time.sleep", return_value=None),
                ):
                    _, run = ledger.submit("e2e22", TASK)

                self.assertTrue(run.success, run.reason)
                self.assertEqual(run.model_invocations, 0)
                self.assertIn("done", run.response)
                command_calls = [item for item in calls if item[0] == "command"]
                poll_calls = [item for item in calls if item[0] == "terminal_poll"]
                self.assertEqual(len(command_calls), 1)
                self.assertEqual(len(poll_calls), 2)
                self.assertTrue(command_calls[0][1]["background"])
                self.assertEqual(Path(command_calls[0][1]["workdir"]), workspace.resolve())
                self.assertEqual(
                    [item[1]["session_id"] for item in poll_calls],
                    ["term-e2e22", "term-e2e22"],
                )

                child = self._child(ledger, "e2e22")
                self.assertEqual(child.status, "completed")
                evidence = json.loads(child.result)
                self.assertEqual(evidence["status"], "completed")
                self.assertEqual(evidence["exit_code"], 0)
                self.assertEqual(evidence["poll_count"], 2)
                self.assertEqual(evidence["pid"], 4242)
                self.assertEqual(evidence["side_effect_attempt_id"], "sidefx-e2e22")
                self.assertNotIn("python -c", child.result)
                self.assertNotIn("done", child.result)
                self.assertEqual(len(evidence["command_sha256"]), 64)
                self.assertEqual(len(evidence["output_sha256"]), 64)
            finally:
                resident.store.close()

    def test_wait_has_no_hidden_wall_clock_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, _ = self._runtime(Path(tmp))
            original_act = resident.body.act
            command_calls = 0
            poll_calls = 0

            def fake_act(kind, *, event_id=None, **kwargs):
                nonlocal command_calls, poll_calls
                if kind == "command":
                    command_calls += 1
                    return self._result(status="running", dispatch_observed=True)
                if kind == "terminal_poll":
                    poll_calls += 1
                    return self._result(status="completed", output="done\n", exit_code=0)
                return original_act(kind, event_id=event_id, **kwargs)

            try:
                with (
                    patch.object(resident.body, "act", side_effect=fake_act),
                    patch("zn_agent.core.long_running_terminal_behavior.time.sleep", return_value=None),
                    patch(
                        "zn_agent.core.long_running_terminal_behavior.utc_now",
                        return_value="2000-01-01T00:00:00+00:00",
                    ),
                ):
                    _, run = ledger.submit("e2e22", TASK)

                self.assertTrue(run.success, run.reason)
                self.assertEqual(run.model_invocations, 0)
                self.assertEqual(command_calls, 1)
                self.assertEqual(poll_calls, 1)
            finally:
                resident.store.close()

    def test_running_session_without_durable_dispatch_receipt_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, _ = self._runtime(Path(tmp))
            original_act = resident.body.act
            command_calls = 0
            poll_calls = 0

            def fake_act(kind, *, event_id=None, **kwargs):
                nonlocal command_calls, poll_calls
                if kind == "command":
                    command_calls += 1
                    return self._result(status="running", dispatch_observed=False)
                if kind == "terminal_poll":
                    poll_calls += 1
                    raise AssertionError("unconfirmed side effect must never enter polling")
                return original_act(kind, event_id=event_id, **kwargs)

            try:
                with patch.object(resident.body, "act", side_effect=fake_act):
                    _, run = ledger.submit("e2e22", TASK)

                self.assertFalse(run.success)
                self.assertIn("side_effect_guard_unconfirmed", run.reason)
                self.assertEqual(run.model_invocations, 0)
                self.assertEqual(command_calls, 1)
                self.assertEqual(poll_calls, 0)
                child = self._child(ledger, "e2e22")
                self.assertEqual(child.status, "blocked")
            finally:
                resident.store.close()

    def test_uncertain_dispatch_preserves_attempt_and_never_polls_or_replays(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, _ = self._runtime(Path(tmp))
            original_act = resident.body.act
            command_calls = 0
            poll_calls = 0

            def fake_act(kind, *, event_id=None, **kwargs):
                nonlocal command_calls, poll_calls
                if kind == "command":
                    command_calls += 1
                    return SimpleNamespace(
                        success=False,
                        output="",
                        data={
                            "side_effect_uncertain": True,
                            "replay_blocked": True,
                            "side_effect_attempt_id": "sidefx-uncertain-e2e22",
                            "side_effect_signature": "abcdef0123456789",
                        },
                        error="command dispatch may already have happened; refusing blind replay",
                    )
                if kind == "terminal_poll":
                    poll_calls += 1
                    raise AssertionError("uncertain dispatch must never enter polling")
                return original_act(kind, event_id=event_id, **kwargs)

            try:
                with patch.object(resident.body, "act", side_effect=fake_act):
                    _, run = ledger.submit("e2e22", TASK)

                self.assertFalse(run.success)
                self.assertIn("command_dispatch_uncertain", run.reason)
                self.assertEqual(run.model_invocations, 0)
                self.assertEqual(command_calls, 1)
                self.assertEqual(poll_calls, 0)
                child = self._child(ledger, "e2e22")
                self.assertEqual(child.status, "blocked")
                evidence = json.loads(child.result)
                self.assertEqual(evidence["side_effect_attempt_id"], "sidefx-uncertain-e2e22")
                self.assertNotIn("python -c", child.result)
            finally:
                resident.store.close()

    def test_nonzero_completion_fails_without_replaying_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, _ = self._runtime(Path(tmp))
            original_act = resident.body.act
            command_calls = 0
            poll_calls = 0

            def fake_act(kind, *, event_id=None, **kwargs):
                nonlocal command_calls, poll_calls
                if kind == "command":
                    command_calls += 1
                    return self._result(status="running", dispatch_observed=True)
                if kind == "terminal_poll":
                    poll_calls += 1
                    return self._result(
                        status="completed",
                        success=False,
                        output="failed\n",
                        exit_code=7,
                        error="command exited with code 7",
                    )
                return original_act(kind, event_id=event_id, **kwargs)

            try:
                with (
                    patch.object(resident.body, "act", side_effect=fake_act),
                    patch("zn_agent.core.long_running_terminal_behavior.time.sleep", return_value=None),
                ):
                    _, run = ledger.submit("e2e22", TASK)

                self.assertFalse(run.success)
                self.assertIn("command_completed_nonzero", run.reason)
                self.assertEqual(run.model_invocations, 0)
                self.assertEqual(command_calls, 1)
                self.assertEqual(poll_calls, 1)
                child = self._child(ledger, "e2e22")
                self.assertEqual(child.status, "blocked")
            finally:
                resident.store.close()

    def test_lost_session_fails_closed_without_command_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident, ledger, _ = self._runtime(Path(tmp))
            original_act = resident.body.act
            command_calls = 0
            poll_calls = 0

            def fake_act(kind, *, event_id=None, **kwargs):
                nonlocal command_calls, poll_calls
                if kind == "command":
                    command_calls += 1
                    return self._result(status="running", dispatch_observed=True)
                if kind == "terminal_poll":
                    poll_calls += 1
                    return SimpleNamespace(
                        success=False,
                        output="",
                        data={},
                        error="KeyError: unknown ZN terminal session",
                    )
                return original_act(kind, event_id=event_id, **kwargs)

            try:
                with (
                    patch.object(resident.body, "act", side_effect=fake_act),
                    patch("zn_agent.core.long_running_terminal_behavior.time.sleep", return_value=None),
                ):
                    _, run = ledger.submit("e2e22", TASK)

                self.assertFalse(run.success)
                self.assertIn("terminal_session_lost", run.reason)
                self.assertEqual(run.model_invocations, 0)
                self.assertEqual(command_calls, 1)
                self.assertEqual(poll_calls, 1)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
