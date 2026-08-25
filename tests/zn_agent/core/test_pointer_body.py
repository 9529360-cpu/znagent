from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core import EmbodiedResidentRuntime, ExecutionPath
from zn_agent.core.body import NativeBody
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class _FakePointerBody(NativeBody):
    def __init__(self, *, resident=None, store=None, drift_pixels: int = 0):
        super().__init__(resident=resident, store=store)
        self.pointer_x = 0
        self.pointer_y = 0
        self.screen_width = 101
        self.screen_height = 51
        self.drift_pixels = int(drift_pixels)
        self.move_calls: list[tuple[int, int]] = []

    def _read_primary_pointer_state(self):
        return {
            "coordinate_space": "primary_screen_fraction",
            "x": self.pointer_x,
            "y": self.pointer_y,
            "x_fraction": round(self.pointer_x / (self.screen_width - 1), 6),
            "y_fraction": round(self.pointer_y / (self.screen_height - 1), 6),
            "screen_width": self.screen_width,
            "screen_height": self.screen_height,
            "captured_at": "test-current-world",
        }

    def _set_primary_pointer_position(self, x: int, y: int) -> bool:
        self.move_calls.append((int(x), int(y)))
        self.pointer_x = int(x) + self.drift_pixels
        self.pointer_y = int(y)
        return True


class PointerBodyTests(unittest.TestCase):
    @staticmethod
    def _advance_until_stage(resident, stage: str, limit: int = 12) -> None:
        for _ in range(limit):
            if resident.store.get_working_state().stage == stage:
                return
            result = resident.live_once()
            if result is not None:
                raise AssertionError(
                    f"event reached terminal result before stage {stage}: {result}"
                )
        raise AssertionError(
            f"resident did not reach stage {stage}; current="
            f"{resident.store.get_working_state().stage}"
        )

    def test_pointer_move_is_bounded_normalized_body_movement(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            body = _FakePointerBody(resident=resident)

            moved = body.act(
                "pointer_move",
                event_id="evt-pointer-body",
                x_fraction=0.5,
                y_fraction=0.4,
            )
            observed = body.act("pointer_state", event_id="evt-pointer-body")
            invalid = body.act(
                "pointer_move",
                event_id="evt-pointer-invalid",
                x_fraction=1.01,
                y_fraction=0.4,
            )

            self.assertTrue(moved.success)
            self.assertEqual(body.move_calls, [(50, 20)])
            self.assertEqual(moved.data["coordinate_space"], "primary_screen_fraction")
            self.assertEqual(moved.data["target_x"], 50)
            self.assertEqual(moved.data["target_y"], 20)
            self.assertTrue(observed.success)
            self.assertEqual(observed.data["x"], 50)
            self.assertEqual(observed.data["y"], 20)
            self.assertFalse(invalid.success)
            self.assertIn("between 0 and 1", invalid.error or "")
            self.assertEqual(body.move_calls, [(50, 20)])
            resident.store.close()

    def test_structured_pointer_move_waits_for_fresh_position_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            self.assertIsInstance(resident, EmbodiedResidentRuntime)
            resident.body = _FakePointerBody(resident=resident)

            event = resident.enqueue(
                "move the pointer to the explicitly supplied screen position",
                payload={
                    "body_action": {
                        "kind": "pointer_move",
                        "args": {"x_fraction": 0.5, "y_fraction": 0.4},
                    },
                    "model_policy": "never",
                },
            )
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            verification_state = resident.store.get_working_state()
            self.assertEqual(verification_state.stage, "native_verification")
            contract = verification_state.data["native_verification"]
            self.assertEqual(contract["kind"], "pointer_position")
            self.assertEqual(contract["expected_x"], 50)
            self.assertEqual(contract["expected_y"], 20)

            result = resident.live_once()
            self.assertIsNotNone(result)
            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.BODY)
            self.assertEqual(result.model_invocations, 0)
            self.assertIn("independently verifying", result.reason)

            movements = [
                item.kind
                for item in reversed(resident.body.recent_actions(20))
                if item.event_id == event.event_id
            ]
            self.assertEqual(movements.count("pointer_move"), 1)
            self.assertEqual(movements.count("pointer_state"), 1)
            self.assertLess(movements.index("pointer_move"), movements.index("pointer_state"))
            resident.store.close()

    def test_pointer_drift_contradicts_success_and_returns_to_investigation(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            resident.body = _FakePointerBody(resident=resident, drift_pixels=4)

            event = resident.enqueue(
                "move the pointer to the explicitly supplied screen position",
                payload={
                    "body_action": {
                        "kind": "pointer_move",
                        "args": {"x_fraction": 0.5, "y_fraction": 0.4},
                    },
                    "model_policy": "never",
                },
            )
            self._advance_until_stage(resident, "native_action")
            self.assertIsNone(resident.live_once())
            self.assertEqual(resident.store.get_working_state().stage, "native_verification")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertIn("pointer postcondition verification failed", state.data["local_failure"])
            self.assertFalse(state.data["native_verification_result"]["verified"])
            self.assertEqual(
                state.data["native_verification_result"]["observed_x"],
                54,
            )

            movements = [
                item.kind
                for item in resident.body.recent_actions(20)
                if item.event_id == event.event_id
            ]
            self.assertEqual(movements.count("pointer_move"), 1)
            self.assertEqual(movements.count("pointer_state"), 1)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
