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
from zn_agent.core.pointer_click_resident import VerifiedPointerClickResidentRuntime
from zn_agent.core.visual_action_reasoner import VisualActionDecision, VisualActionInference
from zn_agent.core.visual_stage_bridge import DesktopVisualStageBridge


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

    def test_pointer_scene_guard_rejects_identity_drift(self):
        resident = object.__new__(VerifiedPointerClickResidentRuntime)
        resident.body = SimpleNamespace(
            observe_desktop_scene_foreground=lambda **kwargs: {
                "application_id": "app.test",
                "identity_sha256": "c" * 64,
            }
        )
        error = resident._desktop_scene_precondition_error(
            {
                "kind": "desktop_scene_foreground_matches",
                "application_id": "app.test",
                "identity_sha256": "a" * 64,
                "scene_id": "desktop-scene-current",
            }
        )
        self.assertIn("drifted", error)


if __name__ == "__main__":
    unittest.main()
