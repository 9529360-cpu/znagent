from __future__ import annotations

import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack
from agent.kernel.world_closed_loop import AdaptiveWorldSense


class WorldAttentionRhythmTests(unittest.TestCase):
    @staticmethod
    def _payload() -> str:
        return json.dumps(
            {
                "results": [
                    {
                        "title": "Grid storage report",
                        "snippet": "Deployment remained unchanged in the current report.",
                        "url": "https://grid.test/report",
                    }
                ]
            }
        )

    @classmethod
    def _settle(cls, world: AdaptiveWorldSense, focus_id: str, samples: int) -> None:
        payload = cls._payload()
        first = world.observe(
            focus_id,
            search_fn=lambda query, limit: payload,
        )
        assert first.changed
        for _ in range(samples):
            stable = world.observe(
                focus_id,
                search_fn=lambda query, limit: payload,
            )
            assert not stable.changed

    def test_stable_world_focus_backs_off_and_rhythm_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            self.assertIsInstance(first.world, AdaptiveWorldSense)
            focus = first.follow_world(
                "grid storage research",
                interval_seconds=600,
            )
            self._settle(first.world, focus.focus_id, 3)

            stable = first.world.rhythm(focus.focus_id)
            self.assertEqual(stable.mode, "stable")
            self.assertEqual(stable.interval_seconds, 1200.0)
            state = first.world.rhythm_state(focus.focus_id)
            self.assertEqual(state.unchanged_observation_streak, 3)
            restored_focus = first.world.focuses(enabled_only=True, limit=10)[0]
            last = first.world._parse_time(restored_focus.last_observed_at)
            self.assertIsNotNone(last)
            self.assertIsNone(first.world.due_focus(now=last + timedelta(seconds=1199)))
            self.assertEqual(
                first.world.due_focus(now=last + timedelta(seconds=1200)).focus_id,
                focus.focus_id,
            )
            self.assertEqual(first.store.get_runtime_metrics().model_invocations, 0)
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            self.assertEqual(
                second.world.rhythm_state(focus.focus_id).unchanged_observation_streak,
                3,
            )
            self.assertEqual(second.world.rhythm(focus.focus_id).interval_seconds, 1200.0)
            payload = self._payload()
            for _ in range(5):
                stable_observation = second.world.observe(
                    focus.focus_id,
                    search_fn=lambda query, limit: payload,
                )
                self.assertFalse(stable_observation.changed)
            settled = second.world.rhythm(focus.focus_id)
            self.assertEqual(settled.mode, "settled")
            self.assertEqual(settled.interval_seconds, 2400.0)
            self.assertEqual(
                second.world.rhythm_state(focus.focus_id).unchanged_observation_streak,
                8,
            )
            self.assertEqual(second.store.get_runtime_metrics().model_invocations, 0)
            second.store.close()

    def test_world_prediction_recheck_overrides_stable_backoff_for_target_focus(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            focus = resident.follow_world(
                "battery research",
                interval_seconds=600,
            )
            self._settle(resident.world, focus.focus_id, 8)
            self.assertEqual(resident.world.rhythm(focus.focus_id).mode, "settled")

            intention = resident.intend("keep battery research grounded")
            resident.will.incubate_candidate(
                intention.intention_id,
                kind="situated_schema_probe",
                step="recheck the current battery research world relation",
                reason="fresh world prediction error needs one later observation",
                confidence=0.55,
                support=("test:world",),
                payload={
                    "model_policy": "never",
                    "world_focus_id": focus.focus_id,
                    "world_topic": focus.topic,
                    "schema_expectation": {
                        "family": "world_change",
                        "value": "changed",
                        "recheck": True,
                    },
                    "transfer_attention": {
                        "evidence_state": "prediction_error",
                    },
                },
            )

            rhythm = resident.world.rhythm(focus.focus_id)
            self.assertEqual(rhythm.mode, "prediction_error")
            self.assertEqual(rhythm.interval_seconds, 150.0)
            self.assertTrue(any("prediction error" in item for item in rhythm.reasons))
            self.assertEqual(
                resident.world.rhythm_state(focus.focus_id).unchanged_observation_streak,
                8,
            )
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
