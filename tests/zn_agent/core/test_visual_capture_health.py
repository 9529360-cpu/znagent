from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.resident_server import ResidentSocketService
from zn_agent.core.visual_sense import VisualFrame


class VisualCaptureHealthTests(unittest.TestCase):
    @staticmethod
    def _resident(tmp: str):
        return build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=Path(tmp) / "kernel.db",
        )

    def test_each_real_capture_failure_enters_health_once_and_success_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            failing = True
            calls = 0

            def capture():
                nonlocal calls
                calls += 1
                if failing:
                    raise AssertionError("test visual capture invariant failed")
                return VisualFrame(frame_hash="frame-ok", width=100, height=80)

            service = ResidentSocketService(
                ResidentRpcServer(resident=resident),
                visual_capture_fn=capture,
            )

            for expected in range(1, 4):
                self.assertIsNone(service.visual.sample())
                health = resident.health.get(service._VISUAL_CAPTURE_HEALTH_ORGAN)
                self.assertIsNotNone(health)
                self.assertEqual(health["total_failures"], expected)
                self.assertEqual(health["consecutive_failures"], expected)
                self.assertEqual(health["repeat_fingerprint_failures"], expected)

            health = resident.health.get(service._VISUAL_CAPTURE_HEALTH_ORGAN)
            self.assertTrue(health["maintenance_candidate"])
            self.assertEqual(health["last_failure_class"], "probable_zn_defect")
            self.assertEqual(calls, 3)

            failing = False
            observed = service.visual.sample()
            self.assertIsNotNone(observed)
            self.assertEqual(calls, 4)
            health = resident.health.get(service._VISUAL_CAPTURE_HEALTH_ORGAN)
            self.assertTrue(health["healthy"])
            self.assertEqual(health["consecutive_failures"], 0)
            self.assertEqual(health["repeat_fingerprint_failures"], 0)
            self.assertIsNotNone(health["last_success_at"])
            resident.store.close()

    def test_capture_failure_is_not_replaced_when_health_persistence_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)

            def capture():
                raise AssertionError("original visual failure")

            service = ResidentSocketService(
                ResidentRpcServer(resident=resident),
                visual_capture_fn=capture,
            )
            original = resident.health.record_failure
            resident.health.record_failure = lambda organ, error: (_ for _ in ()).throw(
                RuntimeError("health unavailable")
            )
            try:
                self.assertIsNone(service.visual.sample())
            finally:
                resident.health.record_failure = original

            state = service.visual.status()
            self.assertIn("AssertionError: original visual failure", state.last_error or "")
            resident.store.close()

    def test_successful_capture_survives_health_success_write_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(tmp)
            service = ResidentSocketService(
                ResidentRpcServer(resident=resident),
                visual_capture_fn=lambda: VisualFrame(
                    frame_hash="healthy-frame",
                    width=120,
                    height=90,
                ),
            )
            original = resident.health.record_success
            resident.health.record_success = lambda organ: (_ for _ in ()).throw(
                RuntimeError("health unavailable")
            )
            try:
                observed = service.visual.sample()
            finally:
                resident.health.record_success = original

            self.assertIsNotNone(observed)
            self.assertEqual(observed.frame_hash, "healthy-frame")
            self.assertIsNone(service.visual.status().last_error)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
