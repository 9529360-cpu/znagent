from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.resident_server import ResidentSocketService
from zn_agent.core.visual_region_sense import (
    NativeVisualRegionSense,
    VisualRegionObservation,
)
from zn_agent.core.visual_sense import VisualFrame


class VisualRegionSenseTests(unittest.TestCase):
    @staticmethod
    def _observation(
        center_x: float,
        center_y: float,
        width: float,
        height: float,
        *,
        signature: str = "local-signature",
    ) -> VisualRegionObservation:
        return VisualRegionObservation(
            signature=signature,
            source="test-region",
            captured_at="2026-08-25T00:00:00+00:00",
            screen_width=1000,
            screen_height=800,
            left=450,
            top=360,
            right=550,
            bottom=440,
            center_x_fraction=center_x,
            center_y_fraction=center_y,
            width_fraction=width,
            height_fraction=height,
            mean_luminance=0.4,
            raw_frame_persisted=False,
        )

    def test_probe_is_bounded_fresh_read_only_local_evidence(self):
        calls: list[tuple[float, float, float, float]] = []

        def probe(center_x: float, center_y: float, width: float, height: float):
            calls.append((center_x, center_y, width, height))
            return self._observation(center_x, center_y, width, height)

        sense = NativeVisualRegionSense(probe_fn=probe)
        observed = sense.probe(
            center_x_fraction=0.5,
            center_y_fraction=0.25,
            width_fraction=0.1,
            height_fraction=0.12,
        )

        self.assertEqual(calls, [(0.5, 0.25, 0.1, 0.12)])
        self.assertEqual(observed.signature, "local-signature")
        self.assertFalse(observed.raw_frame_persisted)
        self.assertEqual((observed.left, observed.top, observed.right, observed.bottom), (450, 360, 550, 440))

    def test_invalid_region_never_reaches_capture_authority(self):
        calls = 0

        def probe(center_x: float, center_y: float, width: float, height: float):
            nonlocal calls
            calls += 1
            return self._observation(center_x, center_y, width, height)

        sense = NativeVisualRegionSense(probe_fn=probe)
        invalid = (
            {"center_x_fraction": -0.01, "center_y_fraction": 0.5},
            {"center_x_fraction": 0.5, "center_y_fraction": 1.01},
            {"center_x_fraction": math.nan, "center_y_fraction": 0.5},
            {"center_x_fraction": 0.5, "center_y_fraction": 0.5, "width_fraction": 0.001},
            {"center_x_fraction": 0.5, "center_y_fraction": 0.5, "height_fraction": 0.75},
        )
        for args in invalid:
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    sense.probe(**args)
        self.assertEqual(calls, 0)

    def test_probe_rejects_raw_pixel_persistence_claim(self):
        def unsafe(center_x: float, center_y: float, width: float, height: float):
            observed = self._observation(center_x, center_y, width, height)
            return VisualRegionObservation(
                **{
                    **{
                        field: getattr(observed, field)
                        for field in observed.__dataclass_fields__
                    },
                    "raw_frame_persisted": True,
                }
            )

        sense = NativeVisualRegionSense(probe_fn=unsafe)
        with self.assertRaisesRegex(ValueError, "must not persist raw frame pixels"):
            sense.probe(center_x_fraction=0.5, center_y_fraction=0.5)

    def test_resident_service_owns_region_sense_without_writing_retina_or_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            before_traces = tuple(resident.nervous.recent_traces(100))
            calls = 0

            def visual_capture() -> VisualFrame:
                return VisualFrame(
                    frame_hash="a" * 64,
                    width=320,
                    height=180,
                    source="test-screen",
                )

            def region_probe(center_x: float, center_y: float, width: float, height: float):
                nonlocal calls
                calls += 1
                return self._observation(center_x, center_y, width, height)

            service = ResidentSocketService(
                ResidentRpcServer(resident=resident),
                visual_capture_fn=visual_capture,
                visual_region_probe_fn=region_probe,
            )
            retina_before = service.visual.status()
            observed = service.visual_region.probe(
                center_x_fraction=0.4,
                center_y_fraction=0.6,
            )
            retina_after = service.visual.status()

            self.assertIs(resident.visual_region, service.visual_region)
            self.assertEqual(calls, 1)
            self.assertEqual(observed.signature, "local-signature")
            self.assertEqual(retina_before.sample_count, retina_after.sample_count)
            self.assertEqual(retina_before.last_frame_hash, retina_after.last_frame_hash)
            self.assertEqual(tuple(resident.nervous.recent_traces(100)), before_traces)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
