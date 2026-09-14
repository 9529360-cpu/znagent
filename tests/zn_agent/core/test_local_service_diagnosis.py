from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.current_app_text_body import CurrentAppTextAwareBody
from zn_agent.core.local_service_diagnosis import LocalServiceDiagnoser, LocalServiceTarget


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
            self.assertIsNone(snapshot.repair_blocked_reason)
            self.assertTrue(response.closed)

    def test_wait_until_healthy_requires_fresh_observed_postcondition(self) -> None:
        state = {"probes": 0}

        def open_health(url, timeout):
            state["probes"] += 1
            return _Response(200 if state["probes"] >= 2 else 503)

        diagnoser = LocalServiceDiagnoser(
            connection_provider=lambda: [_connection(8124, 4243)],
            urlopen=open_health,
            sleep=lambda seconds: None,
        )
        with patch(
            "zn_agent.core.local_service_diagnosis.psutil.Process",
            side_effect=lambda pid: _Process(pid),
        ):
            snapshot = diagnoser.wait_until_healthy(
                LocalServiceTarget(
                    port=8124,
                    expected_process_name="service.exe",
                    health_url="http://127.0.0.1:8124/health",
                ),
                timeout=0.1,
                interval=0.01,
            )

        self.assertTrue(snapshot.healthy)
        self.assertGreaterEqual(state["probes"], 2)

    def test_unexpected_port_owner_is_visible_as_repair_blocker(self) -> None:
        diagnoser = LocalServiceDiagnoser(
            connection_provider=lambda: [_connection(8126, 4245)],
        )
        with patch(
            "zn_agent.core.local_service_diagnosis.psutil.Process",
            side_effect=lambda pid: _Process(pid, name="other.exe"),
        ):
            snapshot = diagnoser.inspect(
                LocalServiceTarget(port=8126, expected_process_name="service.exe")
            )

        self.assertFalse(snapshot.healthy)
        self.assertIn("unexpected", snapshot.repair_blocked_reason)

    def test_multiple_port_owners_are_visible_as_repair_blocker(self) -> None:
        diagnoser = LocalServiceDiagnoser(
            connection_provider=lambda: [
                _connection(8127, 4246, host="0.0.0.0"),
                _connection(8127, 4247, host="::"),
            ],
        )
        with patch(
            "zn_agent.core.local_service_diagnosis.psutil.Process",
            side_effect=lambda pid: _Process(pid),
        ):
            snapshot = diagnoser.inspect(LocalServiceTarget(port=8127))

        self.assertIn("multiple", snapshot.repair_blocked_reason)

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

    def test_final_product_body_exposes_read_only_local_service_state(self) -> None:
        body = CurrentAppTextAwareBody()
        body._local_service_diagnoser = LocalServiceDiagnoser(
            connection_provider=lambda: [_connection(8129, 4248)],
            urlopen=lambda url, timeout: _Response(200),
        )
        with patch(
            "zn_agent.core.local_service_diagnosis.psutil.Process",
            side_effect=lambda pid: _Process(pid),
        ):
            result = body.act(
                "local_service_state",
                port=8129,
                expected_process_name="service.exe",
                health_url="http://127.0.0.1:8129/health",
            )

        self.assertTrue(result.success)
        self.assertTrue(result.data["healthy"])
        self.assertEqual(result.data["listeners"][0]["pid"], 4248)
        self.assertTrue(body._requires_guard("command", {"command": "repair"}))
        self.assertFalse(body._requires_guard("local_service_state", {"port": 8129}))


if __name__ == "__main__":
    unittest.main()
