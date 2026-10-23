from __future__ import annotations

import unittest

from zn_agent.core.automation_element_sense import AutomationElementObservation
from zn_agent.core.foreground_window_sense import ForegroundWindowObservation
from zn_agent.core.local_perception_grounding import (
    LocalGroundingLevel,
    LocalPerceptionGrounder,
)
from zn_agent.core.models import utc_now
from zn_agent.core.visual_ocr_sense import VisualOcrObservation, VisualOcrWord


class _Foreground:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = 0

    def probe(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("no foreground")
        return ForegroundWindowObservation(
            process_id=42,
            title="App",
            process_name="app.exe",
            class_name="Window",
            captured_at=utc_now(),
        )


class _Automation:
    def __init__(self, *, fail=False, process_id=42, offscreen=False):
        self.fail = fail
        self.process_id = process_id
        self.offscreen = offscreen
        self.calls = []

    def probe_at_point(self, x, y):
        self.calls.append((x, y))
        if self.fail:
            raise RuntimeError("uia unavailable")
        return AutomationElementObservation(
            runtime_id=(1, 2, 3),
            process_id=self.process_id,
            process_name="app.exe",
            framework_id="Win32",
            control_type=50000,
            class_name="Button",
            is_enabled=True,
            is_keyboard_focusable=True,
            has_keyboard_focus=False,
            is_offscreen=self.offscreen,
            native_window_handle=1,
            captured_at=utc_now(),
        )


class _Ocr:
    def __init__(self, *, fail=False, text="Settings"):
        self.fail = fail
        self.text = text
        self.calls = []

    def probe(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.fail:
            raise RuntimeError("ocr unavailable")
        words = (
            (VisualOcrWord("Settings", 10, 10, 50, 30),)
            if self.text
            else ()
        )
        return VisualOcrObservation(
            source="windows-media-ocr",
            captured_at=utc_now(),
            language_tag="en-US",
            text=self.text,
            words=words,
            screen_width=1000,
            screen_height=800,
            left=400,
            top=300,
            right=600,
            bottom=500,
            raw_frame_persisted=False,
        )


class LocalPerceptionGroundingTests(unittest.TestCase):
    def test_uia_success_short_circuits_ocr_after_foreground_system_fact(self):
        foreground = _Foreground()
        automation = _Automation()
        ocr = _Ocr()
        grounder = LocalPerceptionGrounder(
            foreground=foreground,
            automation=automation,
            ocr=ocr,
        )
        result = grounder.ground_point(
            x=250,
            y=300,
            screen_width=1000,
            screen_height=800,
        )
        self.assertEqual(result.level, LocalGroundingLevel.UIA)
        self.assertEqual(foreground.calls, 1)
        self.assertEqual(automation.calls, [(250, 300)])
        self.assertEqual(ocr.calls, [])
        self.assertIsNotNone(result.foreground)
        self.assertIsNotNone(result.automation)

    def test_ocr_runs_only_after_uia_failure(self):
        foreground = _Foreground()
        automation = _Automation(fail=True)
        ocr = _Ocr(text="Settings")
        result = LocalPerceptionGrounder(
            foreground=foreground,
            automation=automation,
            ocr=ocr,
        ).ground_point(
            x=499,
            y=399,
            screen_width=1000,
            screen_height=800,
        )
        self.assertEqual(result.level, LocalGroundingLevel.LOCAL_OCR)
        self.assertEqual(len(ocr.calls), 1)
        self.assertAlmostEqual(ocr.calls[0]["center_x_fraction"], 0.4995)
        self.assertAlmostEqual(ocr.calls[0]["center_y_fraction"], 0.499375)
        self.assertTrue(any(reason.startswith("uia:") for reason in result.reasons))

    def test_uia_process_mismatch_falls_back_to_ocr(self):
        result = LocalPerceptionGrounder(
            foreground=_Foreground(),
            automation=_Automation(process_id=99),
            ocr=_Ocr(text="Fallback"),
        ).ground_point(
            x=20,
            y=20,
            screen_width=100,
            screen_height=100,
        )
        self.assertEqual(result.level, LocalGroundingLevel.LOCAL_OCR)
        self.assertTrue(any("does not match" in reason for reason in result.reasons))

    def test_all_local_failures_return_model_required_without_model_call(self):
        foreground = _Foreground(fail=True)
        automation = _Automation(fail=True)
        ocr = _Ocr(fail=True)
        result = LocalPerceptionGrounder(
            foreground=foreground,
            automation=automation,
            ocr=ocr,
        ).ground_point(
            x=10,
            y=10,
            screen_width=100,
            screen_height=100,
        )
        self.assertEqual(result.level, LocalGroundingLevel.MODEL_REQUIRED)
        self.assertIsNone(result.automation)
        self.assertIsNone(result.ocr)
        self.assertGreaterEqual(len(result.reasons), 3)

    def test_empty_ocr_is_not_promoted_to_grounding(self):
        result = LocalPerceptionGrounder(
            foreground=_Foreground(),
            automation=_Automation(fail=True),
            ocr=_Ocr(text=""),
        ).ground_point(
            x=10,
            y=10,
            screen_width=100,
            screen_height=100,
        )
        self.assertEqual(result.level, LocalGroundingLevel.MODEL_REQUIRED)
        self.assertTrue(any("no bounded text" in reason for reason in result.reasons))

    def test_point_must_be_inside_current_screen_before_any_probe(self):
        foreground = _Foreground()
        automation = _Automation()
        ocr = _Ocr()
        grounder = LocalPerceptionGrounder(
            foreground=foreground,
            automation=automation,
            ocr=ocr,
        )
        with self.assertRaisesRegex(ValueError, "inside"):
            grounder.ground_point(
                x=100,
                y=0,
                screen_width=100,
                screen_height=100,
            )
        self.assertEqual(foreground.calls, 0)
        self.assertEqual(automation.calls, [])
        self.assertEqual(ocr.calls, [])


if __name__ == "__main__":
    unittest.main()
