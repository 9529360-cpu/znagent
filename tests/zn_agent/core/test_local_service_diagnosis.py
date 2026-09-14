from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.local_service_diagnosis import (
    LocalServiceDiagnoser,
    LocalServiceTarget,
)
from zn_agent.core.terminal import TerminalResult


class _Oneshot:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Process:
    def __init__(self, pid: int, *, name: str = "service.exe") -> None:
        self.pid = pid
        self._name = name

    def oneshot(self):
        return _Oneshot()

    def name(self):
        return self._name

    def exe(self):
        return rf"C:\apps\{self._name}"

    def cmdline(self):
        return [self._name, "--serve"]

    def create_time(self):
        return 1234.5


class _Response:
    def __init__(self, status: int) -> None:
        self.status = status
        self.closed = False

    def getcode(self):
        return self.status

    def close(self):
        self.closed = True


class _Terminal:
    def __init__(self, callback=None, *, success: bool = True) -> None:
        self.callback = callback
        self.success = success
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        if self.callback is not None:
            self.callback()
        return TerminalResult(
            status="completed",
            command=request.command,
            success=self.success,
            output="repair dispatched",
            exit_code=0 if self.success else 1,
            cwd=request.workdir,
        )


def _connection(port: int, pid: int, *, host: str = "127.0.0.1"):
    return SimpleNamespace(
        status="LISTEN",
        laddr=SimpleNamespace(ip=host, port=port),
        pid=pid,
    )


class LocalServiceDiagnosisTests(unittest.TestCase):
    def test_inspect_correlates_listener_process_health_and_bounded_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "service.log"
            log.write_text("old\nready=false\n", encoding="utf-8")
            response = _Response(503)
            diagnoser = LocalServiceDiagnoser(
                connection_provider=lambda: [_connection(8123, 4242)],
                urlopen=lambda url, timeout: response,
            )
            with patch(
                "zn_agent.core.local_service_diagnosis.psutil.Process",
                side_effect=lambda pid: _Process(pid, name="service.exe"),
            ):
                snapshot = diagnoser.inspect(
                    LocalServiceTarget(
                        port=8123,
                        expected_process_name="service",
                        health_url="http://127.0.0.1:8123/health",
                        log_path=str(log),
                    )
                )

            self.assertFalse(snapshot.healthy)
            self.assertEqual(snapshot.listeners[0].pid, 4242)
            self.assertEqual(snapshot.listeners[0].process_name, "service.exe")
            self.assertEqual(snapshot.health.status_code, 503)
            self.assertEqual(snapshot.log.tail, "old\nready=false")
            self.assertIn("health", snapshot.reason)
            self.assertTrue(response.closed)

    def test_explicit_repair_is_verified_by_real_postcondition(self) -> None:
        state = {"healthy": False}
        terminal = _Terminal(callback=lambda: state.__setitem__("healthy", True))
        diagnoser = LocalServiceDiagnoser(
            terminal=terminal,
            connection_provider=lambda: [_connection(8124, 4243)],
            urlopen=lambda url, timeout: _Response(200 if state["healthy"] else 503),
            sleep=lambda seconds: None,
        )
        with patch(
            "zn_agent.core.local_service_diagnosis.psutil.Process",
            side_effect=lambda pid: _Process(pid),
        ):
            result = diagnoser.diagnose_and_repair(
                LocalServiceTarget(
                    port=8124,
                    expected_process_name="service.exe",
                    health_url="http://127.0.0.1:8124/health",
                ),
                repair_command="service-repair --safe",
                workdir="C:/work",
                verification_timeout=0.1,
            )

        self.assertFalse(result.before.healthy)
        self.assertTrue(result.after.healthy)
        self.assertTrue(result.repair_attempted)
        self.assertTrue(result.restored)
        self.assertTrue(result.success)
        self.assertEqual(len(terminal.requests), 1)
        self.assertEqual(terminal.requests[0].command, "service-repair --safe")

    def test_command_success_is_not_treated_as_service_recovery(self) -> None:
        terminal = _Terminal(success=True)
        diagnoser = LocalServiceDiagnoser(
            terminal=terminal,
            connection_provider=lambda: [_connection(8125, 4244)],
            urlopen=lambda url, timeout: _Response(503),
            sleep=lambda seconds: None,
        )
        with patch(
            "zn_agent.core.local_service_diagnosis.psutil.Process",
            side_effect=lambda pid: _Process(pid),
        ):
            result = diagnoser.diagnose_and_repair(
                LocalServiceTarget(
                    port=8125,
                    health_url="http://127.0.0.1:8125/health",
                ),
                repair_command="repair-command",
                verification_timeout=0.0,
            )

        self.assertTrue(result.repair_result.success)
        self.assertFalse(result.after.healthy)
        self.assertFalse(result.success)
        self.assertFalse(result.restored)

    def test_unexpected_port_owner_blocks_repair(self) -> None:
        terminal = _Terminal()
        diagnoser = LocalServiceDiagnoser(
            terminal=terminal,
            connection_provider=lambda: [_connection(8126, 4245)],
        )
        with patch(
            "zn_agent.core.local_service_diagnosis.psutil.Process",
            side_effect=lambda pid: _Process(pid, name="other.exe"),
        ):
            result = diagnoser.diagnose_and_repair(
                LocalServiceTarget(port=8126, expected_process_name="service.exe"),
                repair_command="restart-service",
            )

        self.assertFalse(result.repair_attempted)
        self.assertIn("unexpected", result.repair_blocked_reason)
        self.assertEqual(terminal.requests, [])

    def test_multiple_port_owners_block_repair(self) -> None:
        terminal = _Terminal()
        diagnoser = LocalServiceDiagnoser(
            terminal=terminal,
            connection_provider=lambda: [
                _connection(8127, 4246, host="0.0.0.0"),
                _connection(8127, 4247, host="::"),
            ],
        )
        with patch(
            "zn_agent.core.local_service_diagnosis.psutil.Process",
            side_effect=lambda pid: _Process(pid),
        ):
            result = diagnoser.diagnose_and_repair(
                LocalServiceTarget(port=8127),
                repair_command="restart-service",
            )

        self.assertFalse(result.repair_attempted)
        self.assertIn("multiple", result.repair_blocked_reason)
        self.assertEqual(terminal.requests, [])

    def test_log_tail_is_bounded_to_recent_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "service.log"
            log.write_text("\n".join(f"line-{index}" for index in range(10)), encoding="utf-8")
            diagnoser = LocalServiceDiagnoser(
                connection_provider=lambda: [],
                max_log_lines=3,
            )
            snapshot = diagnoser.inspect(LocalServiceTarget(port=8128, log_path=str(log)))
            self.assertEqual(snapshot.log.tail, "line-7\nline-8\nline-9")
            self.assertTrue(snapshot.log.truncated)


if __name__ == "__main__":
    unittest.main()
