from __future__ import annotations

import unittest
from dataclasses import replace

from zn_agent.core.focused_text_sense import (
    FocusedTextObservation,
    NativeFocusedTextSense,
)
from zn_agent.core.models import utc_now


def _observation(**changes) -> FocusedTextObservation:
    base = FocusedTextObservation(
        native_window_handle=9003,
        process_id=200,
        process_name="notepad.exe",
        foreground_title="Untitled - Notepad",
        control_class_name="Edit",
        control_id=1003,
        enabled=True,
        visible=True,
        text_length=0,
        text_sha256=NativeFocusedTextSense.digest_text(""),
        is_password=False,
        is_read_only=False,
        captured_at=utc_now(),
        source="test-focused-edit",
    )
    return replace(base, **changes)


class FocusedTextSenseTests(unittest.TestCase):
    def test_digest_evidence_never_exposes_dynamic_text(self) -> None:
        sense = NativeFocusedTextSense(probe_fn=lambda: _observation())

        observed = sense.probe()

        self.assertEqual(observed.text_length, 0)
        self.assertEqual(observed.text_sha256, NativeFocusedTextSense.digest_text(""))
        self.assertFalse(hasattr(observed, "text"))
        self.assertEqual(observed.control_class_name, "Edit")
        self.assertEqual(observed.control_id, 1003)

    def test_password_read_only_and_non_edit_controls_fail_closed(self) -> None:
        for observed in (
            _observation(is_password=True),
            _observation(is_read_only=True),
            _observation(control_class_name="RichEditD2DPT"),
        ):
            with self.subTest(observed=observed):
                sense = NativeFocusedTextSense(probe_fn=lambda item=observed: item)
                with self.assertRaises(ValueError):
                    sense.probe()

    def test_invalid_length_and_digest_are_rejected(self) -> None:
        for observed in (
            _observation(text_length=4097),
            _observation(text_sha256="not-a-digest"),
        ):
            with self.subTest(observed=observed):
                sense = NativeFocusedTextSense(probe_fn=lambda item=observed: item)
                with self.assertRaises(ValueError):
                    sense.probe()

    def test_disabled_or_hidden_edit_is_not_text_entry_evidence(self) -> None:
        for observed in (
            _observation(enabled=False),
            _observation(visible=False),
        ):
            with self.subTest(observed=observed):
                sense = NativeFocusedTextSense(probe_fn=lambda item=observed: item)
                with self.assertRaises(ValueError):
                    sense.probe()


if __name__ == "__main__":
    unittest.main(verbosity=2)
