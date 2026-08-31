from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from zn_agent.core.upstream_bug_report import ResidentUpstreamBugReportOutbox
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
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


class _IntakeClient:
    def __init__(self, intake: MaintainerBugReportIntake):
        self.intake = intake
        self.posts: list[tuple[str, dict, dict]] = []
        self.gets: list[tuple[str, dict]] = []
        self.post_error: BaseException | None = None
        self.drop_ack_after_accept = False

    def post(self, url: str, *, json, headers):
        self.posts.append((url, dict(json), dict(headers)))
        if self.post_error is not None:
            raise self.post_error
        ack = self.intake.accept(json)
        if self.drop_ack_after_accept:
            raise TimeoutError("ack lost after receiver commit")
        return _Response(202, ack)

    def get(self, url: str, *, headers):
        self.gets.append((url, dict(headers)))
        key = urlsplit(url).path.rsplit("/", 1)[-1]
        ack = self.intake.lookup(key)
        return _Response(200, ack) if ack is not None else _Response(404, None)


class _StaticClient:
    def __init__(self, *, post_response=None, get_response=None):
        self.post_response = post_response
        self.get_response = get_response

    def post(self, url: str, *, json, headers):
        return self.post_response

    def get(self, url: str, *, headers):
        return self.get_response


class UpstreamBugReportTransportTests(unittest.TestCase):
    @staticmethod
    def _task():
        return {
            "task_id": "maintenance-0123456789abcdef01234567",
            "organ": "body:command",
            "status": "open",
            "failure_class": "probable_zn_defect",
            "fingerprint": "a" * 64,
            "exception_type": "AssertionError",
            "occurrences": 3,
        }

    def _outbox(self, root: str):
        return ResidentUpstreamBugReportOutbox(
            SimpleNamespace(path=Path(root) / "kernel.db")
        )

    def test_transport_requires_bounded_https_endpoint(self):
        invalid = (
            "http://reports.example.test/v1/reports",
            "https://user:secret@reports.example.test/v1/reports",
            "https://reports.example.test/v1/reports?token=secret",
            "https:///v1/reports",
        )
        for endpoint in invalid:
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ValueError):
                    UpstreamBugReportTransport(endpoint)

        transport = UpstreamBugReportTransport(
            "https://reports.example.test/v1/reports/",
            timeout_seconds=999,
        )
        self.assertEqual(transport.endpoint, "https://reports.example.test/v1/reports")
        self.assertEqual(transport.timeout_seconds, 60.0)

    def test_bearer_token_is_sent_but_not_exposed_by_transport_repr(self):
        with tempfile.TemporaryDirectory() as tmp:
            secret = "maintainer-report-secret"
            outbox = self._outbox(tmp)
            prepared = outbox.prepare(self._task())
            intake = MaintainerBugReportIntake(Path(tmp) / "intake.db")
            client = _IntakeClient(intake)
            transport = UpstreamBugReportTransport(
                "https://reports.example.test/v1/reports",
                bearer_token=secret,
                http_client=client,
            )

            delivered = transport.dispatch(outbox, prepared["report_key"])
            self.assertEqual(delivered["state"], "delivered")
            self.assertEqual(client.posts[0][2]["Authorization"], f"Bearer {secret}")
            self.assertNotIn(secret, repr(transport))

    def test_dispatch_commits_reservation_before_receiver_and_requires_exact_ack(self):
        with tempfile.TemporaryDirectory() as tmp:
            outbox = self._outbox(tmp)
            prepared = outbox.prepare(self._task())
            intake = MaintainerBugReportIntake(Path(tmp) / "intake.db")
            client = _IntakeClient(intake)
            transport = UpstreamBugReportTransport(
                "https://reports.example.test/v1/reports",
                http_client=client,
            )

            delivered = transport.dispatch(outbox, prepared["report_key"])

            self.assertEqual(delivered["state"], "delivered")
            self.assertEqual(delivered["dispatch_attempts"], 1)
            self.assertEqual(intake.snapshot()["report_count"], 1)
            self.assertEqual(len(client.posts), 1)
            _, payload, headers = client.posts[0]
            self.assertEqual(headers["Idempotency-Key"], prepared["report_key"])
            self.assertEqual(headers["X-ZN-Report-Key"], prepared["report_key"])
            self.assertEqual(payload["report_key"], prepared["report_key"])
            with self.assertRaises(RuntimeError):
                transport.dispatch(outbox, prepared["report_key"])

    def test_lost_ack_is_uncertain_and_reconciliation_recovers_delivered_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            outbox = self._outbox(tmp)
            prepared = outbox.prepare(self._task())
            intake = MaintainerBugReportIntake(Path(tmp) / "intake.db")
            client = _IntakeClient(intake)
            client.drop_ack_after_accept = True
            transport = UpstreamBugReportTransport(
                "https://reports.example.test/v1/reports",
                http_client=client,
            )

            with self.assertRaises(UpstreamBugReportTransportError):
                transport.dispatch(outbox, prepared["report_key"])

            uncertain = outbox.snapshot()["reports"][0]
            self.assertEqual(uncertain["state"], "outcome_uncertain")
            self.assertEqual(uncertain["dispatch_attempts"], 1)
            self.assertEqual(intake.snapshot()["report_count"], 1)
            with self.assertRaises(RuntimeError):
                transport.dispatch(outbox, prepared["report_key"])

            client.drop_ack_after_accept = False
            reconciled = transport.reconcile(outbox, prepared["report_key"])
            self.assertEqual(reconciled["state"], "delivered")
            self.assertEqual(reconciled["dispatch_attempts"], 1)
            self.assertEqual(len(client.posts), 1)
            self.assertEqual(len(client.gets), 1)

    def test_authoritative_absence_unlocks_one_new_dispatch_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            outbox = self._outbox(tmp)
            prepared = outbox.prepare(self._task())
            intake = MaintainerBugReportIntake(Path(tmp) / "intake.db")
            client = _IntakeClient(intake)
            client.post_error = TimeoutError("connect outcome unknown")
            transport = UpstreamBugReportTransport(
                "https://reports.example.test/v1/reports",
                http_client=client,
            )

            with self.assertRaises(UpstreamBugReportTransportError):
                transport.dispatch(outbox, prepared["report_key"])
            unlocked = transport.reconcile(outbox, prepared["report_key"])
            self.assertEqual(unlocked["state"], "pending")
            self.assertEqual(unlocked["dispatch_attempts"], 1)

            client.post_error = None
            delivered = transport.dispatch(outbox, prepared["report_key"])
            self.assertEqual(delivered["state"], "delivered")
            self.assertEqual(delivered["dispatch_attempts"], 2)
            self.assertEqual(intake.snapshot()["report_count"], 1)

    def test_mismatched_ack_fails_closed_as_uncertain(self):
        with tempfile.TemporaryDirectory() as tmp:
            outbox = self._outbox(tmp)
            prepared = outbox.prepare(self._task())
            client = _StaticClient(
                post_response=_Response(
                    202,
                    {
                        "schema": "zn-upstream-bug-report-ack-v1",
                        "report_key": "b" * 64,
                        "accepted": True,
                    },
                )
            )
            transport = UpstreamBugReportTransport(
                "https://reports.example.test/v1/reports",
                http_client=client,
            )

            with self.assertRaises(UpstreamBugReportTransportError):
                transport.dispatch(outbox, prepared["report_key"])
            report = outbox.snapshot()["reports"][0]
            self.assertEqual(report["state"], "outcome_uncertain")
            self.assertEqual(report["dispatch_attempts"], 1)


if __name__ == "__main__":
    unittest.main()
