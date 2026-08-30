from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.upstream_bug_report import ResidentUpstreamBugReportOutbox


class ResidentUpstreamBugReportOutboxTests(unittest.TestCase):
    def _task(self, *, occurrences: int = 3, fingerprint: str = "a" * 64):
        return {
            "task_id": "maintenance-0123456789abcdef01234567",
            "organ": "body:command",
            "status": "open",
            "failure_class": "probable_zn_defect",
            "fingerprint": fingerprint,
            "exception_type": "AssertionError",
            "occurrences": occurrences,
        }

    def test_outbox_owner_has_no_network_process_or_credential_dependency(self):
        source_path = (
            Path(__file__).resolve().parents[3]
            / "runtime"
            / "python"
            / "zn_agent"
            / "core"
            / "upstream_bug_report.py"
        )
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_roots: set[str] = set()
        relative_imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    relative_imports.add(str(node.module or ""))
                elif node.module:
                    imported_roots.add(node.module.split(".", 1)[0])

        self.assertTrue(
            imported_roots.isdisjoint(
                {"http", "urllib", "requests", "socket", "subprocess", "webbrowser"}
            )
        )
        self.assertNotIn("credentials", relative_imports)
        self.assertNotIn("provider_bridge", relative_imports)

    def test_prepare_is_idempotent_and_payload_contains_only_pseudonymous_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            outbox = ResidentUpstreamBugReportOutbox(SimpleNamespace(path=db))
            task = self._task()

            first = outbox.prepare(task)
            second = outbox.prepare(task)
            payload = outbox.payload(first["report_key"])

            self.assertEqual(first["report_key"], second["report_key"])
            self.assertEqual(first["state"], "pending")
            self.assertEqual(outbox.snapshot()["report_count"], 1)
            self.assertEqual(
                set(payload),
                {
                    "schema",
                    "product",
                    "report_key",
                    "component_token",
                    "failure_class",
                    "exception_type",
                    "incident_token",
                    "occurrences",
                },
            )
            self.assertEqual(payload["schema"], "zn-upstream-bug-report-v2")
            self.assertEqual(payload["product"], "ZN")
            self.assertEqual(len(payload["incident_token"]), 64)
            self.assertEqual(len(payload["component_token"]), 64)
            self.assertNotEqual(payload["incident_token"], task["fingerprint"])
            self.assertNotIn(task["fingerprint"], repr(payload))
            self.assertNotIn(task["organ"], repr(payload))
            self.assertNotIn(task["task_id"], repr(payload))
            self.assertNotIn("path", repr(payload).lower())
            self.assertNotIn("repository", repr(payload).lower())
            self.assertNotIn("credential", repr(payload).lower())
            self.assertNotIn("authorization", repr(payload).lower())
            self.assertNotIn("api_key", repr(payload).lower())

            raw = db.read_bytes()
            self.assertNotIn(b"body:command", raw)

    def test_same_incident_is_not_correlatable_across_independent_installations(self):
        with tempfile.TemporaryDirectory() as first_tmp, tempfile.TemporaryDirectory() as second_tmp:
            first = ResidentUpstreamBugReportOutbox(
                SimpleNamespace(path=Path(first_tmp) / "kernel.db")
            ).prepare(self._task())
            second = ResidentUpstreamBugReportOutbox(
                SimpleNamespace(path=Path(second_tmp) / "kernel.db")
            ).prepare(self._task())

            self.assertNotEqual(first["report_key"], second["report_key"])
            self.assertNotEqual(first["incident_token"], second["incident_token"])
            self.assertNotEqual(first["component_token"], second["component_token"])

    def test_pending_incident_updates_occurrence_count_without_duplicate_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            outbox = ResidentUpstreamBugReportOutbox(
                SimpleNamespace(path=Path(tmp) / "kernel.db")
            )
            first = outbox.prepare(self._task(occurrences=3))
            updated = outbox.prepare(self._task(occurrences=7))

            self.assertEqual(first["report_key"], updated["report_key"])
            self.assertEqual(updated["occurrences"], 7)
            self.assertEqual(outbox.snapshot()["report_count"], 1)

    def test_dispatch_is_reserved_before_delivery_and_delivered_reports_are_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            outbox = ResidentUpstreamBugReportOutbox(
                SimpleNamespace(path=Path(tmp) / "kernel.db")
            )
            prepared = outbox.prepare(self._task())
            key = prepared["report_key"]

            payload = outbox.reserve_dispatch(key)
            self.assertEqual(payload["report_key"], key)
            dispatching = outbox.snapshot()["reports"][0]
            self.assertEqual(dispatching["state"], "dispatching")
            self.assertEqual(dispatching["dispatch_attempts"], 1)

            delivered = outbox.mark_delivered(key)
            self.assertEqual(delivered["state"], "delivered")
            self.assertEqual(outbox.mark_delivered(key)["state"], "delivered")
            with self.assertRaises(RuntimeError):
                outbox.reserve_dispatch(key)

    def test_ambiguous_dispatch_is_durable_and_automatic_replay_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            outbox = ResidentUpstreamBugReportOutbox(SimpleNamespace(path=db))
            prepared = outbox.prepare(self._task())
            key = prepared["report_key"]
            outbox.reserve_dispatch(key)
            uncertain = outbox.mark_outcome_uncertain(
                key, TimeoutError("credential=never-persist-this")
            )

            self.assertEqual(uncertain["state"], "outcome_uncertain")
            self.assertEqual(uncertain["last_error_type"], "TimeoutError")
            self.assertEqual(outbox.snapshot()["outcome_uncertain_count"], 1)
            with self.assertRaises(RuntimeError):
                outbox.reserve_dispatch(key)
            self.assertNotIn(b"never-persist-this", db.read_bytes())

    def test_invalid_or_insufficient_tasks_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            outbox = ResidentUpstreamBugReportOutbox(
                SimpleNamespace(path=Path(tmp) / "kernel.db")
            )
            with self.assertRaises(ValueError):
                outbox.prepare(self._task(occurrences=2))

            closed = self._task()
            closed["status"] = "closed"
            with self.assertRaises(ValueError):
                outbox.prepare(closed)

            external = self._task()
            external["failure_class"] = "network_or_service"
            with self.assertRaises(ValueError):
                outbox.prepare(external)

            malformed = self._task(fingerprint="not-a-digest")
            with self.assertRaises(ValueError):
                outbox.prepare(malformed)

            self.assertEqual(outbox.snapshot()["report_count"], 0)


if __name__ == "__main__":
    unittest.main()
