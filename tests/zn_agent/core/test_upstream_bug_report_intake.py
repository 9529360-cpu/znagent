from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.upstream_bug_report_intake import MaintainerBugReportIntake


class MaintainerBugReportIntakeTests(unittest.TestCase):
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

    def test_accept_is_deduplicated_and_lookup_returns_exact_ack(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "intake.db"
            intake = MaintainerBugReportIntake(db)

            first = intake.accept(self._payload(occurrences=3))
            second = intake.accept(self._payload(occurrences=7))
            found = intake.lookup("a" * 64)
            snapshot = intake.snapshot()

            expected_ack = {
                "schema": "zn-upstream-bug-report-ack-v1",
                "report_key": "a" * 64,
                "accepted": True,
            }
            self.assertEqual(first, expected_ack)
            self.assertEqual(second, expected_ack)
            self.assertEqual(found, expected_ack)
            self.assertEqual(snapshot["report_count"], 1)
            self.assertEqual(snapshot["reports"][0]["occurrences"], 7)

    def test_intake_rejects_raw_or_unbounded_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            intake = MaintainerBugReportIntake(Path(tmp) / "intake.db")
            payload = self._payload()
            payload["error_text"] = "credential=must-not-cross-boundary"
            with self.assertRaises(ValueError):
                intake.accept(payload)

            malformed = self._payload()
            malformed["incident_token"] = "not-a-digest"
            with self.assertRaises(ValueError):
                intake.accept(malformed)

            wrong_class = self._payload()
            wrong_class["failure_class"] = "network_or_service"
            with self.assertRaises(ValueError):
                intake.accept(wrong_class)

            self.assertEqual(intake.snapshot()["report_count"], 0)

    def test_report_key_reuse_with_different_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            intake = MaintainerBugReportIntake(Path(tmp) / "intake.db")
            intake.accept(self._payload())
            drifted = self._payload()
            drifted["incident_token"] = "d" * 64

            with self.assertRaises(RuntimeError):
                intake.accept(drifted)
            self.assertEqual(intake.snapshot()["report_count"], 1)

    def test_storage_contains_only_bounded_payload_not_raw_incident_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "intake.db"
            intake = MaintainerBugReportIntake(db)
            intake.accept(self._payload())

            raw = db.read_bytes()
            self.assertNotIn(b"body:command", raw)
            self.assertNotIn(b"maintenance-", raw)
            self.assertNotIn(b"credential=", raw)
            self.assertNotIn(b"repository", raw.lower())


if __name__ == "__main__":
    unittest.main()
