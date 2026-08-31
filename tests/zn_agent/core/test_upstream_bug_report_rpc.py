from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.upstream_bug_report_intake import MaintainerBugReportIntake
from zn_agent.core.upstream_bug_report_transport import (
    UpstreamBugReportTransport,
    UpstreamBugReportTransportError,
)


class _Response:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _IntakeClient:
    def __init__(self, intake: MaintainerBugReportIntake):
        self.intake = intake
        self.posts: list[tuple[str, dict, dict]] = []
        self.gets: list[tuple[str, dict]] = []
        self.drop_ack_after_accept = False

    def post(self, url: str, *, json, headers):
        self.posts.append((url, dict(json), dict(headers)))
        ack = self.intake.accept(json)
        if self.drop_ack_after_accept:
            raise TimeoutError("ack lost after receiver commit")
        return _Response(202, ack)

    def get(self, url: str, *, headers):
        self.gets.append((url, dict(headers)))
        key = urlsplit(url).path.rsplit("/", 1)[-1]
        return _Response(200, self.intake.reconciliation(key))


class UpstreamBugReportRpcTests(unittest.TestCase):
    @staticmethod
    def _close(resident) -> None:
        try:
            resident.managed_browser.close()
        finally:
            resident.store.close()

    @staticmethod
    def _prepare_report(resident) -> dict:
        for _ in range(3):
            resident.health.record_failure(
                "body:command",
                AssertionError("rpc report control regression"),
            )
        status = resident.status()["upstream_bug_reports"]
        return status["reports"][0]

    def test_rpc_dispatches_pending_report_only_through_explicit_operator_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                prepared = self._prepare_report(resident)
                intake = MaintainerBugReportIntake(Path(tmp) / "intake.db")
                client = _IntakeClient(intake)
                resident.upstream_bug_report_transport = UpstreamBugReportTransport(
                    "https://reports.example.test/v1/reports",
                    http_client=client,
                )
                rpc = ResidentRpcServer(resident=resident)

                response = rpc.handle(
                    {
                        "id": "send-report",
                        "method": "upstream_bug_report_dispatch",
                        "params": {"report_key": prepared["report_key"]},
                    }
                )

                self.assertTrue(response["ok"])
                self.assertEqual(response["result"]["state"], "delivered")
                self.assertEqual(response["result"]["dispatch_attempts"], 1)
                self.assertEqual(len(client.posts), 1)
                self.assertEqual(intake.snapshot()["report_count"], 1)
            finally:
                self._close(resident)

    def test_rpc_reconciles_uncertain_report_without_replaying_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                prepared = self._prepare_report(resident)
                intake = MaintainerBugReportIntake(Path(tmp) / "intake.db")
                client = _IntakeClient(intake)
                client.drop_ack_after_accept = True
                resident.upstream_bug_report_transport = UpstreamBugReportTransport(
                    "https://reports.example.test/v1/reports",
                    http_client=client,
                )
                rpc = ResidentRpcServer(resident=resident)

                with self.assertRaises(UpstreamBugReportTransportError):
                    rpc.handle(
                        {
                            "id": "uncertain-send",
                            "method": "upstream_bug_report_dispatch",
                            "params": {"report_key": prepared["report_key"]},
                        }
                    )

                uncertain = resident.status()["upstream_bug_reports"]["reports"][0]
                self.assertEqual(uncertain["state"], "outcome_uncertain")
                self.assertEqual(uncertain["dispatch_attempts"], 1)
                self.assertEqual(len(client.posts), 1)

                client.drop_ack_after_accept = False
                response = rpc.handle(
                    {
                        "id": "reconcile-report",
                        "method": "upstream_bug_report_reconcile",
                        "params": {"report_key": prepared["report_key"]},
                    }
                )

                self.assertTrue(response["ok"])
                self.assertEqual(response["result"]["state"], "delivered")
                self.assertEqual(response["result"]["dispatch_attempts"], 1)
                self.assertEqual(len(client.posts), 1)
                self.assertEqual(len(client.gets), 1)
            finally:
                self._close(resident)

    def test_rpc_report_actions_require_explicit_report_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                rpc = ResidentRpcServer(resident=resident)
                for method in (
                    "upstream_bug_report_dispatch",
                    "upstream_bug_report_reconcile",
                ):
                    with self.subTest(method=method):
                        with self.assertRaises(ValueError):
                            rpc.handle({"id": method, "method": method, "params": {}})
            finally:
                self._close(resident)


if __name__ == "__main__":
    unittest.main()