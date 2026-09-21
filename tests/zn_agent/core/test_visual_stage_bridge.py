from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.desktop_scene import (
    DesktopScene,
    DesktopSceneForeground,
    DesktopSceneRect,
    DesktopSceneScreenshot,
)
from zn_agent.core.action import NativeActionIntent
from zn_agent.core.pointer_click_resident import VerifiedPointerClickResidentRuntime
from zn_agent.core.research_information_product_resident import (
    ProductResearchInformationResidentRuntime,
)
from zn_agent.core.visual_action_reasoner import VisualActionDecision, VisualActionInference
from zn_agent.core.visual_stage_bridge import (
    DesktopVisualStageBridge,
    VisualStageBridgeResult,
    build_current_visual_stage_bridge,
)


class _Runtime:
    def __init__(self):
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return SimpleNamespace(
            success=True,
            error=None,
            verification=SimpleNamespace(reason="ok"),
        )


class _Reasoner:
    def __init__(self, action="TAP", x=0.5, y=0.5):
        self.action = action
        self.x = x
        self.y = y

    def infer(self, **kwargs):
        decision = VisualActionDecision(
            self.action,
            self.x if self.action == "TAP" else None,
            self.y if self.action == "TAP" else None,
        )
        return VisualActionInference(
            decision=decision,
            provider="fake",
            model="fake",
        )


def _scene(path: str, *, scene_id: str, identity: str = "a" * 64) -> DesktopScene:
    return DesktopScene(
        scene_id=scene_id,
        captured_at="2026-09-21T00:00:00Z",
        foreground=DesktopSceneForeground(
            application_id="app.test",
            process_name="test.exe",
            class_name="Test",
            identity_sha256=identity,
            window_rect=DesktopSceneRect(10, 10, 90, 90),
        ),
        screenshot=DesktopSceneScreenshot(
            local_path=path,
            width=100,
            height=100,
            size_bytes=3,
            sha256="b" * 64,
            source="test",
        ),
        targets=(),
        grounding_mode="screenshot_only",
        providers=("windows_uia",),
    )


def _token(decision_id: str) -> str:
    return hashlib.sha256(decision_id.encode("utf-8")).hexdigest()[:16]


class VisualStageBridgeTests(unittest.TestCase):
    def test_tap_regrounds_and_builds_pointer_lifecycle_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "screen.png"
            image.write_bytes(b"png")
            token = _token("cycle-1")
            scenes = {
                f"evt:visual-stage:{token}:see": _scene(
                    str(image), scene_id="desktop-scene-before"
                ),
                f"evt:visual-stage:{token}:reground": _scene(
                    str(image), scene_id="desktop-scene-after"
                ),
            }
            runtime = _Runtime()
            bridge = DesktopVisualStageBridge(
                action_runtime=runtime,
                reasoner=_Reasoner(),
                scene_loader=lambda event_id: scenes[event_id],
            )
            result = bridge.evaluate(
                event_id="evt",
                decision_id="cycle-1",
                application_id="app.test",
                instruction="click the visible button",
            )
            self.assertEqual(len(runtime.requests), 2)
            self.assertEqual(result.pointer_intent.kind, "pointer_click")
            self.assertEqual(result.pointer_intent.args["x_fraction"], 0.5)
            self.assertEqual(
                result.event_payload["desktop_scene_precondition"]["scene_id"],
                "desktop-scene-after",
            )
            resident = object.__new__(VerifiedPointerClickResidentRuntime)
            contract, error = resident._pointer_click_contract(
                SimpleNamespace(payload={}),
                result.pointer_intent,
            )
            self.assertIsNone(error)
            self.assertEqual(
                contract["desktop_scene_precondition"]["scene_id"],
                "desktop-scene-after",
            )

    def test_same_decision_id_replays_same_intent_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "screen.png"
            image.write_bytes(b"png")
            token = _token("cycle-1")
            scenes = {
                f"evt:visual-stage:{token}:see": _scene(
                    str(image), scene_id="desktop-scene-before"
                ),
                f"evt:visual-stage:{token}:reground": _scene(
                    str(image), scene_id="desktop-scene-after"
                ),
            }
            bridge = DesktopVisualStageBridge(
                action_runtime=_Runtime(),
                reasoner=_Reasoner(),
                scene_loader=lambda event_id: scenes[event_id],
            )
            first = bridge.evaluate(
                event_id="evt",
                decision_id="cycle-1",
                application_id="app.test",
                instruction="click the visible button",
            )
            second = bridge.evaluate(
                event_id="evt",
                decision_id="cycle-1",
                application_id="app.test",
                instruction="click the visible button",
            )
            self.assertEqual(first.pointer_intent.intent_id, second.pointer_intent.intent_id)

    def test_wait_never_creates_pointer_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "screen.png"
            image.write_bytes(b"png")
            token = _token("cycle-wait")
            bridge = DesktopVisualStageBridge(
                action_runtime=_Runtime(),
                reasoner=_Reasoner("WAIT", None, None),
                scene_loader=lambda event_id: _scene(
                    str(image), scene_id=f"desktop-scene-{token}"
                ),
            )
            result = bridge.evaluate(
                event_id="evt",
                decision_id="cycle-wait",
                application_id="app.test",
                instruction="wait for loading",
            )
            self.assertIsNone(result.pointer_intent)
            self.assertFalse(result.requires_completion_verification)

    def test_finish_never_creates_pointer_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "screen.png"
            image.write_bytes(b"png")
            bridge = DesktopVisualStageBridge(
                action_runtime=_Runtime(),
                reasoner=_Reasoner("FINISH", None, None),
                scene_loader=lambda event_id: _scene(
                    str(image), scene_id="desktop-scene-finish"
                ),
            )
            result = bridge.evaluate(
                event_id="evt",
                decision_id="cycle-finish",
                application_id="app.test",
                instruction="confirm done",
            )
            self.assertIsNone(result.pointer_intent)
            self.assertTrue(result.requires_completion_verification)

    def test_current_bridge_uses_router_order_and_existing_image_resource(self):
        image_resource = SimpleNamespace(invoke_image=lambda **kwargs: None)
        text_resource = SimpleNamespace()
        routes = (
            SimpleNamespace(route_id="text"),
            SimpleNamespace(route_id="image"),
        )

        class Router:
            def __init__(self):
                self.routes = routes
                self.calls = []

            def select(self, goal, excluded=None):
                excluded = set(excluded or ())
                self.calls.append((goal, excluded))
                return next(route for route in self.routes if route.route_id not in excluded)

        class Factory:
            def create(self, route):
                resource = image_resource if route.route_id == "image" else text_resource
                return SimpleNamespace(resource=resource)

        router = Router()
        kernel = SimpleNamespace(router=router, worker_factory=Factory())
        runtime = _Runtime()
        bridge = build_current_visual_stage_bridge(
            action_runtime=runtime,
            kernel=kernel,
            route_policy={"allowed_providers": ["gemini"]},
            data_classification="private",
        )
        self.assertIs(bridge.action_runtime, runtime)
        self.assertIs(bridge.reasoner.resource, image_resource)
        self.assertEqual(len(router.calls), 2)
        self.assertEqual(router.calls[1][1], {"text"})
        self.assertEqual(
            router.calls[0][0].metadata["route_policy"]["data_classification"],
            "private",
        )
        self.assertEqual(
            router.calls[0][0].metadata["route_policy"]["allowed_providers"],
            ["gemini"],
        )

    def test_product_resident_admits_only_tap_into_native_action_cycle(self):
        pointer_intent = NativeActionIntent(
            intent_id="visual-tap-test",
            event_id="evt",
            kind="pointer_click",
            args={"x_fraction": 0.5, "y_fraction": 0.5, "button": "left"},
            expected_outcome={"kind": "visual_region_changed"},
            source="visual_stage_bridge",
        )
        tap = VisualStageBridgeResult(
            inference=VisualActionInference(
                decision=VisualActionDecision("TAP", 0.5, 0.5),
                provider="fake",
                model="fake",
            ),
            scene_id="desktop-scene-before",
            regrounded_scene_id="desktop-scene-after",
            pointer_intent=pointer_intent,
        )
        resident = object.__new__(ProductResearchInformationResidentRuntime)
        resident._current_visual_stage_bridge = lambda event: SimpleNamespace(
            evaluate=lambda **kwargs: tap
        )
        resident.budget = SimpleNamespace(
            decide=lambda *args, **kwargs: SimpleNamespace(
                use_model=True,
                max_calls=1,
                reason="visual stage admitted",
            )
        )
        admitted = []
        resident._begin_native_action_cycle = lambda event, state, intent: admitted.append(intent)
        saved = []
        resident.store = SimpleNamespace(save_working_state=lambda state: saved.append(state))
        resident._sync_execution_context = lambda event, state: None
        state = SimpleNamespace(data={})
        event = SimpleNamespace(event_id="evt", payload={})

        result = ProductResearchInformationResidentRuntime.evaluate_visual_stage(
            resident,
            event=event,
            state=state,
            application_id="app.test",
            instruction="click target",
            decision_id="cycle-1",
        )
        self.assertIs(result, tap)
        self.assertEqual(admitted, [pointer_intent])
        self.assertEqual(saved, [state])
        self.assertEqual(state.data["visual_stage_decision"]["decision"]["action"], "TAP")

        finish = VisualStageBridgeResult(
            inference=VisualActionInference(
                decision=VisualActionDecision("FINISH"),
                provider="fake",
                model="fake",
            ),
            scene_id="desktop-scene-finish",
            requires_completion_verification=True,
        )
        resident._current_visual_stage_bridge = lambda event: SimpleNamespace(
            evaluate=lambda **kwargs: finish
        )
        admitted.clear()
        saved.clear()
        result = ProductResearchInformationResidentRuntime.evaluate_visual_stage(
            resident,
            event=event,
            state=state,
            application_id="app.test",
            instruction="confirm done",
            decision_id="cycle-2",
        )
        self.assertIs(result, finish)
        self.assertEqual(admitted, [])
        self.assertEqual(saved, [state])
        self.assertTrue(state.data["visual_stage_decision"]["requires_completion_verification"])

    def test_product_resident_visual_stage_respects_model_policy_gate(self):
        resident = object.__new__(ProductResearchInformationResidentRuntime)
        resident.budget = SimpleNamespace(
            decide=lambda event, **kwargs: SimpleNamespace(
                use_model=False,
                max_calls=0,
                reason="model use disabled by policy 'never'",
            )
        )
        resident._current_visual_stage_bridge = lambda event: self.fail(
            "visual bridge must not be constructed when model policy denies cognition"
        )
        with self.assertRaisesRegex(RuntimeError, "does not permit"):
            ProductResearchInformationResidentRuntime.evaluate_visual_stage(
                resident,
                event=SimpleNamespace(event_id="evt", payload={"model_policy": "never"}),
                state=SimpleNamespace(data={}),
                application_id="app.test",
                instruction="click target",
                decision_id="cycle-policy",
            )

    def test_product_resident_rejects_visual_model_when_budget_blocks_it(self):
        resident = object.__new__(ProductResearchInformationResidentRuntime)
        resident.budget = SimpleNamespace(
            decide=lambda *args, **kwargs: SimpleNamespace(
                use_model=False,
                max_calls=0,
                reason="budget blocked",
            )
        )
        resident._current_visual_stage_bridge = lambda event: self.fail(
            "bridge must not be built when model policy blocks visual cognition"
        )
        with self.assertRaisesRegex(RuntimeError, "does not permit it"):
            ProductResearchInformationResidentRuntime.evaluate_visual_stage(
                resident,
                event=SimpleNamespace(event_id="evt", payload={}),
                state=SimpleNamespace(data={}),
                application_id="app.test",
                instruction="click target",
                decision_id="cycle-budget-blocked",
            )

    def test_product_resident_rejects_malformed_visual_route_policy(self):
        resident = object.__new__(ProductResearchInformationResidentRuntime)
        with self.assertRaisesRegex(RuntimeError, "route_policy is malformed"):
            ProductResearchInformationResidentRuntime._current_visual_stage_bridge(
                resident,
                SimpleNamespace(payload={"route_policy": "not-an-object"}),
            )

    @staticmethod
    def _scene_precondition(**overrides):
        value = {
            "kind": "desktop_scene_foreground_matches",
            "application_id": "app.test",
            "identity_sha256": "a" * 64,
            "scene_id": "desktop-scene-current",
            "window_rect": {"left": 10.0, "top": 10.0, "right": 90.0, "bottom": 90.0},
            "screen_width": 100,
            "screen_height": 100,
        }
        value.update(overrides)
        return value

    @staticmethod
    def _guard_body(*, identity="a" * 64, rect=None, width=100, height=100):
        current_rect = rect or {"left": 10.0, "top": 10.0, "right": 90.0, "bottom": 90.0}

        class Body:
            def observe_desktop_scene_foreground(self, **kwargs):
                return {
                    "application_id": "app.test",
                    "identity_sha256": identity,
                    "window_rect": dict(current_rect),
                }

            def act(self, kind, *, event_id=None, **kwargs):
                assert kind == "pointer_state"
                return SimpleNamespace(
                    success=True,
                    data={"screen_width": width, "screen_height": height},
                )

        return Body()

    def test_pointer_scene_guard_accepts_fresh_matching_geometry(self):
        resident = object.__new__(VerifiedPointerClickResidentRuntime)
        resident.body = self._guard_body()
        self.assertIsNone(
            resident._desktop_scene_precondition_error(self._scene_precondition())
        )

    def test_pointer_scene_guard_rejects_identity_drift(self):
        resident = object.__new__(VerifiedPointerClickResidentRuntime)
        resident.body = self._guard_body(identity="c" * 64)
        error = resident._desktop_scene_precondition_error(self._scene_precondition())
        self.assertIn("identity drifted", error)

    def test_pointer_scene_guard_rejects_window_geometry_drift(self):
        resident = object.__new__(VerifiedPointerClickResidentRuntime)
        resident.body = self._guard_body(
            rect={"left": 20.0, "top": 10.0, "right": 100.0, "bottom": 90.0}
        )
        error = resident._desktop_scene_precondition_error(self._scene_precondition())
        self.assertIn("geometry drifted", error)

    def test_pointer_scene_guard_rejects_screen_geometry_drift(self):
        resident = object.__new__(VerifiedPointerClickResidentRuntime)
        resident.body = self._guard_body(width=120)
        error = resident._desktop_scene_precondition_error(self._scene_precondition())
        self.assertIn("primary-screen geometry drifted", error)


if __name__ == "__main__":
    unittest.main()
