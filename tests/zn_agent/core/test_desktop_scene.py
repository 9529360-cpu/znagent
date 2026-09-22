from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from zn_agent.core.automation_control_action import control_type_id
from zn_agent.core.automation_named_control_sense import NamedAutomationControlObservation
from zn_agent.core.desktop_scene import (
    DesktopSceneError,
    DesktopSceneForegroundBinding,
    DesktopSceneRect,
    DesktopSceneTarget,
    DesktopVisualGroundingCandidate,
    NativeDesktopSceneBuilder,
    UnavailableDesktopVisualGroundingProvider,
    desktop_scene_artifact_path,
    desktop_scene_capture_event_id,
    desktop_scene_iou,
    load_desktop_scene_artifact,
    merge_desktop_scene_targets,
)
from zn_agent.core.windows_screen_capture import capture_primary_screen_artifact


class _Sense:
    def __init__(self, rows=None, *, fail=False):
        self.rows = dict(rows or {})
        self.fail = fail
        self.calls = []

    def list_controls(self, *, process_id, process_name, control_type):
        self.calls.append((process_id, process_name, control_type))
        if self.fail:
            raise RuntimeError("UIA unavailable")
        return tuple(self.rows.get(control_type, ()))


class _Visual:
    provider_id = "test-visual"

    def __init__(self, candidates=(), *, available=True):
        self.candidates = tuple(candidates)
        self.available = available
        self.calls = []

    def availability(self):
        return self.available, "" if self.available else "disabled for test"

    def detect(self, screenshot, *, window_rect, max_targets):
        self.calls.append((screenshot, window_rect, max_targets))
        return self.candidates


def _uia(
    *,
    name="Save",
    automation_id="save",
    control_type="button",
    left=100.0,
    top=100.0,
    right=200.0,
    bottom=150.0,
):
    return NamedAutomationControlObservation(
        runtime_id=(1, 2, 3),
        process_id=321,
        process_name="demo.exe",
        name=name,
        control_type=control_type_id(control_type),
        class_name="Button",
        is_enabled=True,
        is_offscreen=False,
        left=left,
        top=top,
        right=right,
        bottom=bottom,
        center_x_fraction=((left + right) / 2.0) / 1000.0,
        center_y_fraction=((top + bottom) / 2.0) / 800.0,
        captured_at="2026-09-21T00:00:00+00:00",
        automation_id=automation_id,
        is_keyboard_focusable=True,
        has_keyboard_focus=False,
        is_password=False,
        is_value_pattern_available=control_type == "edit",
        value_is_read_only=False if control_type == "edit" else None,
        is_toggle_pattern_available=control_type == "checkbox",
        is_expand_collapse_pattern_available=control_type == "combo_box",
        is_selection_item_pattern_available=control_type in {
            "list_item",
            "menu_item",
            "radio_button",
            "tab_item",
            "tree_item",
            "data_item",
        },
    )


def _scene_target(*, source, rect, role="button", name="Save", visual_confidence=None):
    return DesktopSceneTarget(
        target_id="",
        source=source,
        role=role,
        accessible_name=name,
        automation_id="save" if source == "uia" else "",
        rect=rect,
        center_x_fraction=rect.center_x / 1000.0,
        center_y_fraction=rect.center_y / 800.0,
        enabled=True if source == "uia" else None,
        editable=False if source == "uia" else None,
        focused=False if source == "uia" else None,
        supported_patterns=("toggle",) if source == "uia" else (),
        visual_confidence=visual_confidence,
        provenance=("windows_uia",) if source == "uia" else ("visual:test-visual",),
    )


class DesktopSceneTests(unittest.TestCase):
    def test_iou_and_merge_prefer_uia_semantics(self):
        semantic = _scene_target(
            source="uia",
            rect=DesktopSceneRect(100, 100, 200, 150),
        )
        visual = _scene_target(
            source="visual",
            rect=DesktopSceneRect(105, 102, 198, 151),
            role="icon_button",
            name="floppy disk",
            visual_confidence=0.91,
        )

        self.assertGreater(desktop_scene_iou(semantic.rect, visual.rect), 0.8)
        merged, truncated = merge_desktop_scene_targets(
            (semantic,),
            (visual,),
        )

        self.assertFalse(truncated)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].source, "hybrid")
        self.assertEqual(merged[0].role, "button")
        self.assertEqual(merged[0].accessible_name, "Save")
        self.assertEqual(merged[0].automation_id, "save")
        self.assertEqual(merged[0].visual_confidence, 0.91)
        self.assertEqual(
            merged[0].provenance,
            ("windows_uia", "visual:test-visual"),
        )

    def test_non_overlapping_visual_target_is_preserved(self):
        semantic = _scene_target(
            source="uia",
            rect=DesktopSceneRect(100, 100, 200, 150),
        )
        visual = _scene_target(
            source="visual",
            rect=DesktopSceneRect(500, 400, 560, 460),
            name="Canvas icon",
            visual_confidence=0.8,
        )
        merged, truncated = merge_desktop_scene_targets((semantic,), (visual,))
        self.assertFalse(truncated)
        self.assertEqual([row.source for row in merged], ["uia", "visual"])

    def test_builder_creates_hybrid_scene_and_recoverable_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            sense = _Sense({"button": (_uia(),)})
            visual = _Visual(
                (
                    DesktopVisualGroundingCandidate(
                        role="icon_button",
                        name="save icon",
                        rect=DesktopSceneRect(102, 101, 198, 151),
                        confidence=0.94,
                        provider_id="test-visual",
                    ),
                    DesktopVisualGroundingCandidate(
                        role="canvas_control",
                        name="custom knob",
                        rect=DesktopSceneRect(500, 300, 560, 360),
                        confidence=0.81,
                        provider_id="test-visual",
                    ),
                )
            )

            def capture(event_id):
                return capture_primary_screen_artifact(
                    desktop_scene_capture_event_id(event_id),
                    home=home,
                    capture_fn=lambda: Image.new("RGB", (1000, 800), "white"),
                )

            binding = DesktopSceneForegroundBinding(
                application_id="demo.app",
                process_id=321,
                process_name="demo.exe",
                window_handle=12345,
                class_name="DemoWindow",
            )
            builder = NativeDesktopSceneBuilder(
                automation_sense=sense,
                visual_provider=visual,
                capture_fn=capture,
                window_rect_fn=lambda hwnd, pid: DesktopSceneRect(50, 50, 900, 700),
                home=home,
            )

            scene, scene_path = builder.capture(
                event_id="evt-scene",
                foreground=binding,
                foreground_probe=lambda: binding,
            )

            self.assertEqual(scene.grounding_mode, "hybrid")
            self.assertEqual(scene.providers, ("windows_uia", "test-visual"))
            self.assertEqual(scene.uia_target_count, 1)
            self.assertEqual(scene.visual_target_count, 2)
            self.assertEqual([row.source for row in scene.targets], ["hybrid", "visual"])
            self.assertTrue(all(row.target_id.startswith("desktop-target-") for row in scene.targets))
            self.assertEqual(
                Path(scene_path),
                desktop_scene_artifact_path("evt-scene", home=home).resolve(strict=True),
            )

            recovered = load_desktop_scene_artifact("evt-scene", home=home)
            self.assertEqual(recovered, scene)

            raw = Path(scene_path).read_text(encoding="utf-8")
            payload = json.loads(raw)
            serialized_scene = payload["scene"]
            self.assertNotIn("process_id", serialized_scene["foreground"])
            self.assertNotIn("window_handle", serialized_scene["foreground"])
            for target in serialized_scene["targets"]:
                self.assertNotIn("runtime_id", target)

    def test_scene_artifact_path_is_canonical_for_noncanonical_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            alias_parent = Path(tmp) / "scene-home"
            alias_parent.mkdir()
            home = alias_parent / ".."

            def capture(event_id):
                return capture_primary_screen_artifact(
                    desktop_scene_capture_event_id(event_id),
                    home=home,
                    capture_fn=lambda: Image.new("RGB", (320, 200), "white"),
                )

            binding = DesktopSceneForegroundBinding(
                "demo.app",
                321,
                "demo.exe",
                12345,
                "DemoWindow",
            )
            builder = NativeDesktopSceneBuilder(
                automation_sense=_Sense(),
                capture_fn=capture,
                window_rect_fn=lambda hwnd, pid: DesktopSceneRect(10, 10, 300, 180),
                home=home,
            )

            _scene, scene_path = builder.capture(
                event_id="evt-canonical-scene",
                foreground=binding,
                foreground_probe=lambda: binding,
            )

            self.assertEqual(
                Path(scene_path),
                desktop_scene_artifact_path(
                    "evt-canonical-scene",
                    home=home,
                ).resolve(strict=True),
            )
    def test_missing_visual_provider_is_explicit_uia_only_degradation(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            sense = _Sense({"button": (_uia(),)})

            def capture(event_id):
                return capture_primary_screen_artifact(
                    desktop_scene_capture_event_id(event_id),
                    home=home,
                    capture_fn=lambda: Image.new("RGB", (1000, 800), "white"),
                )

            binding = DesktopSceneForegroundBinding(
                "demo.app",
                321,
                "demo.exe",
                12345,
            )
            scene, _ = NativeDesktopSceneBuilder(
                automation_sense=sense,
                visual_provider=UnavailableDesktopVisualGroundingProvider(),
                capture_fn=capture,
                window_rect_fn=lambda hwnd, pid: DesktopSceneRect(0, 0, 900, 700),
                home=home,
            ).capture(
                event_id="evt-uia",
                foreground=binding,
                foreground_probe=lambda: binding,
            )

            self.assertEqual(scene.grounding_mode, "uia_only")
            self.assertEqual(scene.providers, ("windows_uia",))
            self.assertTrue(
                any("no desktop visual-grounding provider" in reason for reason in scene.degraded_reasons)
            )

    def test_uia_failure_can_degrade_to_visual_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            sense = _Sense(fail=True)
            visual = _Visual(
                (
                    DesktopVisualGroundingCandidate(
                        role="canvas_control",
                        name="custom control",
                        rect=DesktopSceneRect(200, 200, 300, 260),
                        confidence=0.88,
                        provider_id="test-visual",
                    ),
                )
            )

            def capture(event_id):
                return capture_primary_screen_artifact(
                    desktop_scene_capture_event_id(event_id),
                    home=home,
                    capture_fn=lambda: Image.new("RGB", (1000, 800), "white"),
                )

            binding = DesktopSceneForegroundBinding("demo.app", 321, "demo.exe", 12345)
            scene, _ = NativeDesktopSceneBuilder(
                automation_sense=sense,
                visual_provider=visual,
                capture_fn=capture,
                window_rect_fn=lambda hwnd, pid: DesktopSceneRect(0, 0, 900, 700),
                home=home,
            ).capture(
                event_id="evt-visual",
                foreground=binding,
                foreground_probe=lambda: binding,
            )

            self.assertEqual(scene.grounding_mode, "visual_only")
            self.assertEqual(len(scene.targets), 1)
            self.assertTrue(any(reason.startswith("uia:") for reason in scene.degraded_reasons))

    def test_visual_candidate_outside_foreground_window_is_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            visual = _Visual(
                (
                    DesktopVisualGroundingCandidate(
                        role="button",
                        name="other window",
                        rect=DesktopSceneRect(700, 600, 780, 680),
                        confidence=0.9,
                        provider_id="test-visual",
                    ),
                )
            )

            def capture(event_id):
                return capture_primary_screen_artifact(
                    desktop_scene_capture_event_id(event_id),
                    home=home,
                    capture_fn=lambda: Image.new("RGB", (1000, 800), "white"),
                )

            binding = DesktopSceneForegroundBinding("demo.app", 321, "demo.exe", 12345)
            scene, _ = NativeDesktopSceneBuilder(
                automation_sense=_Sense(),
                visual_provider=visual,
                capture_fn=capture,
                window_rect_fn=lambda hwnd, pid: DesktopSceneRect(0, 0, 600, 500),
                home=home,
            ).capture(
                event_id="evt-outside",
                foreground=binding,
                foreground_probe=lambda: binding,
            )

            self.assertEqual(scene.grounding_mode, "screenshot_only")
            self.assertEqual(scene.targets, ())

    def test_foreground_identity_drift_fails_before_scene_artifact_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)

            def capture(event_id):
                return capture_primary_screen_artifact(
                    desktop_scene_capture_event_id(event_id),
                    home=home,
                    capture_fn=lambda: Image.new("RGB", (1000, 800), "white"),
                )

            before = DesktopSceneForegroundBinding("demo.app", 321, "demo.exe", 12345)
            after = DesktopSceneForegroundBinding("demo.app", 322, "demo.exe", 12346)
            builder = NativeDesktopSceneBuilder(
                automation_sense=_Sense(),
                capture_fn=capture,
                window_rect_fn=lambda hwnd, pid: DesktopSceneRect(0, 0, 600, 500),
                home=home,
            )

            with self.assertRaisesRegex(DesktopSceneError, "identity changed"):
                builder.capture(
                    event_id="evt-drift",
                    foreground=before,
                    foreground_probe=lambda: after,
                )
            self.assertFalse(desktop_scene_artifact_path("evt-drift", home=home).exists())

    def test_tampered_scene_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)

            def capture(event_id):
                return capture_primary_screen_artifact(
                    desktop_scene_capture_event_id(event_id),
                    home=home,
                    capture_fn=lambda: Image.new("RGB", (1000, 800), "white"),
                )

            binding = DesktopSceneForegroundBinding("demo.app", 321, "demo.exe", 12345)
            builder = NativeDesktopSceneBuilder(
                automation_sense=_Sense(),
                capture_fn=capture,
                window_rect_fn=lambda hwnd, pid: DesktopSceneRect(0, 0, 600, 500),
                home=home,
            )
            builder.capture(
                event_id="evt-tamper",
                foreground=binding,
                foreground_probe=lambda: binding,
            )
            path = desktop_scene_artifact_path("evt-tamper", home=home)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["scene"]["foreground"]["application_id"] = "other.app"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(DesktopSceneError, "metadata digest mismatch"):
                load_desktop_scene_artifact("evt-tamper", home=home)


if __name__ == "__main__":
    unittest.main()
