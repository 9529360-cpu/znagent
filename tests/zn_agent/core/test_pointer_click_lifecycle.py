from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core import ExecutionPath
from zn_agent.core.body import NativeBody
from zn_agent.core.models import utc_now
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.visual_region_sense import VisualRegionObservation


class _ClickBody(NativeBody):
    def __init__(self, *, resident=None):
        super().__init__(resident=resident)
        self.pointer_x = 0
        self.pointer_y = 0
        self.screen_width = 101
        self.screen_height = 51
        self.move_calls: list[tuple[int, int]] = []
        self.click_calls = 0

    def _read_primary_pointer_state(self):
        return {
            "coordinate_space": "primary_screen_fraction",
            "x": self.pointer_x,
            "y": self.pointer_y,
            "x_fraction": round(self.pointer_x / (self.screen_width - 1), 6),
            "y_fraction": round(self.pointer_y / (self.screen_height - 1), 6),
            "screen_width": self.screen_width,
            "screen_height": self.screen_height,
            "captured_at": utc_now(),
        }

    def _set_primary_pointer_position(self, x: int, y: int) -> bool:
        self.move_calls.append((int(x), int(y)))
        self.pointer_x = int(x)
        self.pointer_y = int(y)
        return True

    def _send_primary_pointer_click(self, button: str) -> bool:
        self.assertable_button = button
        self.click_calls += 1
        return True


class _ClickVisualRegion:
    def __init__(self, body: _ClickBody, *, change_after_click: bool = True):
        self.body = body
        self.change_after_click = bool(change_after_click)
        self.calls: list[tuple[float, float, float, float]] = []

    def probe(
        self,
        *,
        center_x_fraction: float,
        center_y_fraction: float,
        width_fraction: float,
        height_fraction: float,
    ) -> VisualRegionObservation:
        self.calls.append(
            (
                float(center_x_fraction),
                float(center_y_fraction),
                float(width_fraction),
                float(height_fraction),
            )
        )
        changed = self.change_after_click and self.body.click_calls > 0
        signature = "after-click-signature" if changed else "before-click-signature"
        return VisualRegionObservation(
            signature=signature,
            source="test-region",
            captured_at=utc_now(),
            screen_width=101,
            screen_height=51,
            left=45,
            top=18,
            right=55,
            bottom=23,
            center_x_fraction=float(center_x_fraction),
            center_y_fraction=float(center_y_fraction),
            width_fraction=float(width_fraction),
            height_fraction=float(height_fraction),
            mean_luminance=0.5,
            raw_frame_persisted=False,
        )


class PointerClickLifecycleTests(unittest.TestCase):
    @staticmethod
    def _advance_until_stage(resident, stage: str, limit: int = 16) -> None:
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

    @staticmethod
    def _event(
        resident,
        *,
        task: str = "perform the explicitly supplied bounded click",
        kind: str = "effect_probe",
        completion_scope: bool | dict[str, str] = True,
    ):
        payload = {
            "body_action": {
                "kind": "pointer_click",
                "args": {
                    "x_fraction": 0.5,
                    "y_fraction": 0.4,
                    "button": "left",
                },
            },
            "expected_outcome": {
                "kind": "visual_region_changed",
                "width_fraction": 0.08,
                "height_fraction": 0.08,
            },
            "model_policy": "never",
        }
        if completion_scope is True:
            payload["completion_scope"] = {
                "kind": "verified_effect",
                "effect_kind": "visual_region_changed",
            }
        elif isinstance(completion_scope, dict):
            payload["completion_scope"] = dict(completion_scope)
        return resident.enqueue(task, kind=kind, payload=payload)

    def test_pointer_click_body_never_moves_implicitly(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            body = _ClickBody(resident=resident)
            body.pointer_x = 50
            body.pointer_y = 20

            clicked = body.act(
                "pointer_click",
                event_id="evt-click-body",
                x_fraction=0.5,
                y_fraction=0.4,
                button="left",
            )
            body.pointer_x = 0
            refused = body.act(
                "pointer_click",
                event_id="evt-click-refused",
                x_fraction=0.5,
                y_fraction=0.4,
                button="left",
            )

            self.assertTrue(clicked.success)
            self.assertEqual(body.click_calls, 1)
            self.assertEqual(body.move_calls, [])
            self.assertFalse(refused.success)
            self.assertIn("no longer matches", refused.error or "")
            self.assertEqual(body.click_calls, 1)
            self.assertEqual(body.move_calls, [])
            resident.store.close()

    def test_click_waits_for_position_baseline_and_fresh_effect_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            body = _ClickBody(resident=resident)
            visual = _ClickVisualRegion(body)
            resident.body = body
            resident.visual_region = visual
            self._event(resident)
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            prepared = resident.store.get_working_state()
            self.assertEqual(prepared.stage, "native_action")
            self.assertEqual(body.move_calls, [(50, 20)])
            self.assertEqual(body.click_calls, 0)
            self.assertEqual(len(visual.calls), 0)
            self.assertTrue(
                prepared.data[resident._POINTER_CLICK_PRECONDITION_KEY]["position_verified"]
            )

            self.assertIsNone(resident.live_once())
            clicked = resident.store.get_working_state()
            self.assertEqual(clicked.stage, "native_verification")
            self.assertEqual(body.click_calls, 1)
            self.assertEqual(len(visual.calls), 1)
            self.assertEqual(
                clicked.data[resident._POINTER_CLICK_EXECUTION_KEY]["status"],
                "completed",
            )
            self.assertEqual(
                clicked.data[resident._POINTER_CLICK_PRECONDITION_KEY]["baseline"]["signature"],
                "before-click-signature",
            )

            result = resident.live_once()
            self.assertIsNotNone(result)
            self.assertTrue(result.success)
            self.assertEqual(result.execution_path, ExecutionPath.BODY)
            self.assertEqual(result.model_invocations, 0)
            self.assertIn("effect_probe", result.reason)
            self.assertIn("visual_region_changed", result.reason)
            self.assertEqual(body.click_calls, 1)
            self.assertEqual(len(visual.calls), 2)
            resident.store.close()

    def test_interrupted_started_click_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            body = _ClickBody(resident=resident)
            resident.body = body
            resident.visual_region = _ClickVisualRegion(body)
            self._event(resident)
            self._advance_until_stage(resident, "native_action")
            self.assertIsNone(resident.live_once())

            state = resident.store.get_working_state()
            intent_id = state.data["native_action_intent"]["intent_id"]
            state.data[resident._POINTER_CLICK_EXECUTION_KEY] = {
                "intent_id": intent_id,
                "status": "started",
                "baseline_signature": "unknown-delivery",
                "started_at": utc_now(),
                "action_id": None,
            }
            resident.store.save_working_state(state)

            self.assertIsNone(resident.live_once())
            recovered = resident.store.get_working_state()
            self.assertEqual(recovered.stage, "native_investigation")
            self.assertEqual(body.click_calls, 0)
            self.assertIn("refusing blind replay", recovered.data["local_failure"])
            resident.store.close()

    def test_unchanged_local_region_contradicts_click_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            body = _ClickBody(resident=resident)
            resident.body = body
            resident.visual_region = _ClickVisualRegion(body, change_after_click=False)
            self._event(resident)
            self._advance_until_stage(resident, "native_action")
            self.assertIsNone(resident.live_once())
            self.assertIsNone(resident.live_once())
            self.assertEqual(body.click_calls, 1)
            self.assertEqual(resident.store.get_working_state().stage, "native_verification")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.click_calls, 1)
            self.assertFalse(state.data["native_verification_result"]["verified"])
            self.assertIn("did not differ", state.data["local_failure"])
            resident.store.close()

    def test_click_without_narrow_visual_postcondition_fails_before_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            body = _ClickBody(resident=resident)
            resident.body = body
            resident.visual_region = _ClickVisualRegion(body)
            resident.enqueue(
                "perform the explicitly supplied bounded click",
                kind="effect_probe",
                payload={
                    "body_action": {
                        "kind": "pointer_click",
                        "args": {"x_fraction": 0.5, "y_fraction": 0.4},
                    },
                    "completion_scope": {
                        "kind": "verified_effect",
                        "effect_kind": "visual_region_changed",
                    },
                    "model_policy": "never",
                },
            )
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.click_calls, 0)
            self.assertEqual(body.move_calls, [])
            self.assertIn("visual_region_changed", state.data["local_failure"])
            resident.store.close()

    def test_user_task_click_is_rejected_before_pointer_movement(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            body = _ClickBody(resident=resident)
            visual = _ClickVisualRegion(body)
            resident.body = body
            resident.visual_region = visual
            self._event(resident, kind="user_task")
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.move_calls, [])
            self.assertEqual(body.click_calls, 0)
            self.assertEqual(visual.calls, [])
            self.assertIn("effect_probe", state.data["local_failure"])
            self.assertIn("broader user task", state.data["local_failure"])
            resident.store.close()

    def test_effect_probe_without_exact_completion_scope_fails_before_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            body = _ClickBody(resident=resident)
            visual = _ClickVisualRegion(body)
            resident.body = body
            resident.visual_region = visual
            self._event(resident, completion_scope=False)
            self._advance_until_stage(resident, "native_action")

            self.assertIsNone(resident.live_once())
            state = resident.store.get_working_state()
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(body.move_calls, [])
            self.assertEqual(body.click_calls, 0)
            self.assertEqual(visual.calls, [])
            self.assertIn("completion_scope", state.data["local_failure"])
            self.assertIn("verified_effect", state.data["local_failure"])
            resident.store.close()

    def test_effect_probe_completion_does_not_credit_task_prose_as_native_ability(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            body = _ClickBody(resident=resident)
            resident.body = body
            resident.visual_region = _ClickVisualRegion(body)
            before = resident.kernel.self_model.get("communication/writing")
            self.assertEqual(before.evidence_count, 0)

            self._event(
                resident,
                task="write the quarterly report",
            )
            self._advance_until_stage(resident, "native_action")
            self.assertIsNone(resident.live_once())
            self.assertIsNone(resident.live_once())
            result = resident.live_once()

            self.assertIsNotNone(result)
            self.assertTrue(result.success)
            after = resident.kernel.self_model.get("communication/writing")
            self.assertEqual(after.evidence_count, 0)
            self.assertEqual(body.click_calls, 1)
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
