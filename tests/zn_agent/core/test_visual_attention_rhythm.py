from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.visual_sense import NativeVisualSense, VisualFrame


class VisualAttentionRhythmTests(unittest.TestCase):
    @staticmethod
    def _frame(token: str = "a") -> VisualFrame:
        return VisualFrame(
            frame_hash=(token * 64)[:64],
            width=320,
            height=180,
            source="test-screen",
        )

    @staticmethod
    def _healthy_disk():
        return patch(
            "zn_agent.core.life.shutil.disk_usage",
            return_value=SimpleNamespace(total=100, used=50, free=50),
        )

    @classmethod
    def _settle(cls, retina: NativeVisualSense, samples: int = 3) -> None:
        first = retina.sample()
        assert first is not None and first.changed
        for _ in range(samples):
            unchanged = retina.sample()
            assert unchanged is not None and not unchanged.changed

    def test_stable_scene_backs_off_and_rhythm_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            retina = NativeVisualSense(
                first,
                capture_fn=lambda: self._frame("a"),
                interval_seconds=2.0,
            )
            self._settle(retina, 3)

            stable = retina.rhythm()
            self.assertEqual(stable.mode, "stable")
            self.assertEqual(stable.interval_seconds, 4.0)
            stable_state = retina.status()
            self.assertEqual(stable_state.unchanged_sample_streak, 3)
            last_sampled = retina._parse_time(stable_state.last_sampled_at)
            self.assertIsNotNone(last_sampled)
            self.assertFalse(retina.due(now=last_sampled + timedelta(seconds=3.9)))
            self.assertTrue(retina.due(now=last_sampled + timedelta(seconds=4.0)))
            self.assertEqual(first.store.get_runtime_metrics().model_invocations, 0)
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            restored = NativeVisualSense(
                second,
                capture_fn=lambda: self._frame("a"),
                interval_seconds=2.0,
            )
            self.assertEqual(restored.status().unchanged_sample_streak, 3)
            self.assertEqual(restored.rhythm().interval_seconds, 4.0)

            for _ in range(5):
                observation = restored.sample()
                self.assertIsNotNone(observation)
                self.assertFalse(observation.changed)
            settled = restored.rhythm()
            self.assertEqual(settled.mode, "settled")
            self.assertEqual(settled.interval_seconds, 8.0)
            self.assertEqual(restored.status().unchanged_sample_streak, 8)
            self.assertEqual(second.store.get_runtime_metrics().model_invocations, 0)
            second.store.close()

    def test_visual_prediction_recheck_overrides_stable_backoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            retina = NativeVisualSense(
                resident,
                capture_fn=lambda: self._frame("a"),
                interval_seconds=2.0,
            )
            self._settle(retina, 8)
            self.assertEqual(retina.rhythm().mode, "settled")

            intention = resident.intend("keep a visual expectation grounded")
            resident.will.incubate_candidate(
                intention.intention_id,
                kind="situated_schema_probe",
                step="recheck whether the expected visual change is still present",
                reason="fresh visual prediction error requires another native observation",
                confidence=0.55,
                support=("test:visual",),
                payload={
                    "model_policy": "never",
                    "schema_expectation": {
                        "family": "visual_change",
                        "value": "local",
                        "recheck": True,
                    },
                    "transfer_attention": {
                        "evidence_state": "prediction_error",
                    },
                },
            )

            rhythm = retina.rhythm()
            self.assertEqual(rhythm.mode, "prediction_error")
            self.assertEqual(rhythm.interval_seconds, 1.0)
            self.assertTrue(any("prediction error" in item for item in rhythm.reasons))
            self.assertEqual(retina.status().unchanged_sample_streak, 8)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_nonvisual_conflict_does_not_hot_sample_the_screen(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            retina = NativeVisualSense(
                resident,
                capture_fn=lambda: self._frame("a"),
                interval_seconds=2.0,
            )
            self._settle(retina, 3)

            intention = resident.intend("keep a system expectation grounded")
            resident.will.incubate_candidate(
                intention.intention_id,
                kind="situated_schema_probe",
                step="recheck the system relation",
                reason="system evidence conflicts",
                confidence=0.55,
                support=("test:system",),
                payload={
                    "model_policy": "never",
                    "schema_expectation": {
                        "family": "system",
                        "value": "linux",
                        "recheck": True,
                    },
                    "transfer_attention": {
                        "evidence_state": "prediction_error",
                    },
                },
            )

            rhythm = retina.rhythm()
            self.assertEqual(rhythm.mode, "stable")
            self.assertEqual(rhythm.interval_seconds, 4.0)
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_visual_thought_attention_temporarily_tightens_sampling(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self._healthy_disk():
                resident = build_resident_runtime_from_existing_stack(
                    config={"model": {}},
                    store_path=Path(tmp) / "kernel.db",
                )
                try:
                    retina = NativeVisualSense(
                        resident,
                        capture_fn=lambda: self._frame("a"),
                        interval_seconds=2.0,
                    )
                    self._settle(retina, 3)
                    self.assertEqual(retina.rhythm().mode, "stable")

                    resident.perceive_visual(
                        "a newly salient visual thread",
                        features=("screen", "visual_change:local"),
                        source="resident-retina",
                        salience=1.0,
                        arousal=0.9,
                    )
                    pulse = resident.pulse()
                    self.assertIsNotNone(pulse.thought)
                    self.assertEqual(pulse.thought.action_kind, "observe")
                    self.assertEqual(pulse.thought.focus, "a newly salient visual thread")

                    rhythm = retina.rhythm()
                    self.assertEqual(rhythm.mode, "thought_attention")
                    self.assertEqual(rhythm.interval_seconds, 1.5)
                    self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
                finally:
                    resident.store.close()


if __name__ == "__main__":
    unittest.main()
