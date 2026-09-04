from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class NativeBodyHealthTests(unittest.TestCase):
    @staticmethod
    def _resident(tmp: str):
        return build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=Path(tmp) / "kernel.db",
        )

    def test_real_dispatch_failures_enter_health_once_per_attempt_and_recover(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            target = Path(tmp) / "private-directory-name" / "missing.txt"

            for expected in range(1, 4):
                result = resident.body.act("read_text", path=str(target))
                self.assertFalse(result.success)
                self.assertIn("FileNotFoundError", result.error or "")
                health = resident.health.get("body:read_text")
                self.assertIsNotNone(health)
                self.assertEqual(health["total_failures"], expected)
                self.assertEqual(health["consecutive_failures"], expected)
                self.assertEqual(health["repeat_fingerprint_failures"], expected)
                self.assertEqual(health["last_exception_type"], "FileNotFoundError")
                self.assertEqual(
                    health["last_failure_class"], "configuration_or_environment"
                )

            self.assertNotIn("private-directory-name", repr(resident.status()))

            target.parent.mkdir(parents=True)
            target.write_text("body recovered", encoding="utf-8")
            recovered = resident.body.act("read_text", path=str(target))
            self.assertTrue(recovered.success)
            self.assertEqual(recovered.output, "body recovered")
            health = resident.health.get("body:read_text")
            self.assertIsNotNone(health)
            self.assertTrue(health["healthy"])
            self.assertEqual(health["consecutive_failures"], 0)
            self.assertEqual(health["repeat_fingerprint_failures"], 0)
            self.assertIsNotNone(health["last_success_at"])
            resident.store.close()

    def test_arbitrary_action_kind_is_hashed_in_health_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            secret_kind = "customer-secret-action-name"

            result = resident.body.act(secret_kind)

            self.assertFalse(result.success)
            snapshot = resident.health.snapshot()
            body_organs = [
                item for item in snapshot["organs"] if item["organ"].startswith("body:")
            ]
            self.assertEqual(len(body_organs), 1)
            self.assertTrue(body_organs[0]["organ"].startswith("body:action-"))
            self.assertNotIn(secret_kind, repr(resident.status()))
            resident.store.close()

    def test_health_journal_failure_cannot_replace_body_result_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            missing = Path(tmp) / "missing.txt"

            original_failure = resident.health.record_failure
            resident.health.record_failure = lambda organ, error: (_ for _ in ()).throw(
                RuntimeError("health unavailable")
            )
            try:
                failed = resident.body.act("read_text", path=str(missing))
            finally:
                resident.health.record_failure = original_failure
            self.assertFalse(failed.success)
            self.assertIn("FileNotFoundError", failed.error or "")

            missing.write_text("still works", encoding="utf-8")
            original_success = resident.health.record_success
            resident.health.record_success = lambda organ: (_ for _ in ()).throw(
                RuntimeError("health unavailable")
            )
            try:
                succeeded = resident.body.act("read_text", path=str(missing))
            finally:
                resident.health.record_success = original_success
            self.assertTrue(succeeded.success)
            self.assertEqual(succeeded.output, "still works")
            resident.store.close()

    def test_existing_final_body_object_is_observed_in_place_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            body = resident.body
            dispatch = body._dispatch

            resident._install_body_dispatch_health_observer()

            self.assertIs(resident.body, body)
            self.assertIs(resident.body._dispatch, dispatch)
            self.assertTrue(body._zn_health_dispatch_observer_installed)
            sensed = body.act("sense")
            self.assertTrue(sensed.success)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
