from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.foreground_window_sense import ForegroundWindowObservation
from zn_agent.core.models import utc_now
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class _FailingForegroundWindow:
    def probe(self):
        raise AssertionError("test foreground probe invariant failed")


class _HealthyForegroundWindow:
    def probe(self):
        return ForegroundWindowObservation(
            process_id=42,
            title="Desktop",
            process_name="explorer.exe",
            class_name="Progman",
            captured_at=utc_now(),
            source="test-foreground-window",
        )


class ForegroundWindowHealthTests(unittest.TestCase):
    @staticmethod
    def _resident(tmp: str):
        return build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=Path(tmp) / "kernel.db",
        )

    def test_actual_probe_failures_enter_health_once_per_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            resident.foreground_window = _FailingForegroundWindow()

            for expected in range(1, 4):
                observed, error = resident._probe_foreground_window()
                self.assertIsNone(observed)
                self.assertIn("AssertionError", error or "")
                health = resident.health.get(resident._FOREGROUND_WINDOW_HEALTH_ORGAN)
                self.assertIsNotNone(health)
                self.assertEqual(health["total_failures"], expected)
                self.assertEqual(health["consecutive_failures"], expected)
                self.assertEqual(health["repeat_fingerprint_failures"], expected)

            health = resident.health.get(resident._FOREGROUND_WINDOW_HEALTH_ORGAN)
            self.assertTrue(health["maintenance_candidate"])
            self.assertEqual(health["last_failure_class"], "probable_zn_defect")
            resident.store.close()

    def test_real_probe_success_closes_the_same_health_streak(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            resident.foreground_window = _FailingForegroundWindow()
            resident._probe_foreground_window()
            resident._probe_foreground_window()

            resident.foreground_window = _HealthyForegroundWindow()
            observed, error = resident._probe_foreground_window()

            self.assertIsNone(error)
            self.assertIsNotNone(observed)
            self.assertEqual(observed.process_name, "explorer.exe")
            health = resident.health.get(resident._FOREGROUND_WINDOW_HEALTH_ORGAN)
            self.assertIsNotNone(health)
            self.assertTrue(health["healthy"])
            self.assertEqual(health["consecutive_failures"], 0)
            self.assertEqual(health["repeat_fingerprint_failures"], 0)
            self.assertIsNotNone(health["last_success_at"])
            resident.store.close()

    def test_health_journal_failure_does_not_replace_probe_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            resident.foreground_window = _HealthyForegroundWindow()

            original = resident.health.record_success
            resident.health.record_success = lambda organ: (_ for _ in ()).throw(
                RuntimeError("health unavailable")
            )
            try:
                observed, error = resident._probe_foreground_window()
            finally:
                resident.health.record_success = original

            self.assertIsNone(error)
            self.assertIsNotNone(observed)
            self.assertEqual(observed.title, "Desktop")
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
