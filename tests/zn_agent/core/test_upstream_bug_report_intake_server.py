from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from zn_agent.core.upstream_bug_report_intake_server import build_server


class MaintainerReportHTTPServerTests(unittest.TestCase):
    @staticmethod
    def _payload(*, occurrences: int = 3):
        return {
            "schema": "zn-upstream-bug-report-v2",
            "product": "ZN",
            "report_key": "a" * 64,
            "component_token": "b" * 64,
            "failure_class": "probable_zn_defect",
            "exception_type": "AssertionError",
            "incident_token": "c" * 64,
            "occurrences": occurrences,
        }

    @contextmanager
    def _server(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "intake.db"
            server = build_server(
                database_path=database,
                bearer_token="test-receiver-secret",
                host="127.0.0.1",
                port=0,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                yield server, database, f"http://127.0.0.1:{server.server_address[1]}"
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    @staticmethod
    def _request(
        url: str,
        *,
        method: str = "GET",
        payload=None,
        token: str | None = "test-receiver-secret",
        report_key: str | None = None,
    ):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        if report_key is None:
            if isinstance(payload, dict):
                report_key = str(payload.get("report_key") or "")
            else:
                report_key = urlsplit(url).path.rsplit("/", 1)[-1]
        headers = {"X-ZN-Report-Key": report_key}
        if data is not None:
            headers["Content-Type"] = "application/json"
            headers["Idempotency-Key"] = report_key
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_authenticated_post_and_reconciliation_close_client_protocol_loop(self):
        with self._server() as (server, _database, base_url):
            status, accepted = self._request(
                f"{base_url}/reports",
                method="POST",
                payload=self._payload(occurrences=3),
            )
            self.assertEqual(status, 200)
            self.assertEqual(
                accepted,
                {
                    "schema": "zn-upstream-bug-report-ack-v1",
                    "report_key": "a" * 64,
                    "accepted": True,
                },
            )

            status, accepted_again = self._request(
                f"{base_url}/reports",
                method="POST",
                payload=self._payload(occurrences=7),
            )
            self.assertEqual(status, 200)
            self.assertEqual(accepted_again, accepted)
            self.assertEqual(server.intake.snapshot()["report_count"], 1)
            self.assertEqual(server.intake.snapshot()["reports"][0]["occurrences"], 7)

            status, present = self._request(f"{base_url}/reports/{'a' * 64}")
            self.assertEqual(status, 200)
            self.assertEqual(
                present,
                {
                    "schema": "zn-upstream-bug-report-reconciliation-v1",
                    "report_key": "a" * 64,
                    "present": True,
                },
            )

            status, absent = self._request(f"{base_url}/reports/{'d' * 64}")
            self.assertEqual(status, 200)
            self.assertFalse(absent["present"])

    def test_missing_or_wrong_bearer_token_never_reaches_intake(self):
        with self._server() as (server, _database, base_url):
            for token in (None, "wrong-secret"):
                status, response = self._request(
                    f"{base_url}/reports",
                    method="POST",
                    payload=self._payload(),
                    token=token,
                )
                self.assertEqual(status, 401)
                self.assertEqual(response, {"error": "unauthorized"})
            self.assertEqual(server.intake.snapshot()["report_count"], 0)

    def test_transport_identity_headers_must_match_payload_and_path(self):
        with self._server() as (server, _database, base_url):
            status, response = self._request(
                f"{base_url}/reports",
                method="POST",
                payload=self._payload(),
                report_key="d" * 64,
            )
            self.assertEqual(status, 400)
            self.assertEqual(response, {"error": "invalid_report"})
            self.assertEqual(server.intake.snapshot()["report_count"], 0)

            status, response = self._request(
                f"{base_url}/reports/{'a' * 64}",
                report_key="d" * 64,
            )
            self.assertEqual(status, 400)
            self.assertEqual(response, {"error": "invalid_report_key"})

    def test_unbounded_fields_fail_closed_without_storage(self):
        with self._server() as (server, _database, base_url):
            payload = self._payload()
            payload["error_text"] = "credential=must-not-cross-boundary"
            status, response = self._request(
                f"{base_url}/reports",
                method="POST",
                payload=payload,
            )
            self.assertEqual(status, 400)
            self.assertEqual(response, {"error": "invalid_report"})
            self.assertEqual(server.intake.snapshot()["report_count"], 0)

    def test_oversized_body_is_rejected_before_json_or_intake_processing(self):
        with self._server() as (server, _database, base_url):
            request = urllib.request.Request(
                f"{base_url}/reports",
                data=b"{" + (b"x" * 5000) + b"}",
                headers={
                    "Authorization": "Bearer test-receiver-secret",
                    "Content-Type": "application/json",
                    "X-ZN-Report-Key": "a" * 64,
                    "Idempotency-Key": "a" * 64,
                },
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=5)
            self.assertEqual(caught.exception.code, 413)
            self.assertEqual(server.intake.snapshot()["report_count"], 0)

    def test_invalid_report_key_is_not_misreported_as_absent(self):
        with self._server() as (_server, _database, base_url):
            status, response = self._request(f"{base_url}/reports/not-a-digest")
            self.assertEqual(status, 400)
            self.assertEqual(response, {"error": "invalid_report_key"})


if __name__ == "__main__":
    unittest.main()
