from __future__ import annotations

import unittest

from zn_agent.core.automation_named_control_sense import (
    NamedAutomationControlObservation,
    NativeNamedAutomationControlSense,
)


class NamedAutomationControlSenseTests(unittest.TestCase):
    def test_exact_button_probe_is_structurally_bounded(self) -> None:
        calls: list[tuple[int, str, str]] = []

        def probe(process_id: int, process_name: str, name: str):
            calls.append((process_id, process_name, name))
            return NamedAutomationControlObservation(
                runtime_id=(42, process_id, 7),
                process_id=process_id,
                process_name=process_name,
                name=name,
                control_type=50000,
                class_name="Button",
                is_enabled=True,
                is_offscreen=False,
                left=400,
                top=300,
                right=520,
                bottom=340,
                center_x_fraction=0.46,
                center_y_fraction=0.40,
                captured_at="2026-09-01T00:00:00+00:00",
                source="test-exact-name",
            )

        sense = NativeNamedAutomationControlSense(probe_fn=probe)
        observed = sense.find_unique_button(
            process_id=330,
            process_name="customerapp.exe",
            name="查询",
        )

        self.assertEqual(calls, [(330, "customerapp.exe", "查询")])
        self.assertEqual(observed.runtime_id, (42, 330, 7))
        self.assertEqual(observed.name, "查询")
        self.assertEqual(observed.control_type, 50000)

    def test_probe_cannot_return_a_different_or_unsafe_control(self) -> None:
        def wrong_name(process_id: int, process_name: str, name: str):
            return NamedAutomationControlObservation(
                runtime_id=(1, 2, 3),
                process_id=process_id,
                process_name=process_name,
                name="删除",
                control_type=50000,
                class_name="Button",
                is_enabled=True,
                is_offscreen=False,
                left=10,
                top=10,
                right=40,
                bottom=30,
                center_x_fraction=0.02,
                center_y_fraction=0.02,
                captured_at="2026-09-01T00:00:00+00:00",
            )

        sense = NativeNamedAutomationControlSense(probe_fn=wrong_name)
        with self.assertRaisesRegex(ValueError, "did not match"):
            sense.find_unique_button(
                process_id=330,
                process_name="customerapp.exe",
                name="查询",
            )

        with self.assertRaisesRegex(ValueError, "1..160"):
            sense.find_unique_button(
                process_id=330,
                process_name="customerapp.exe",
                name="x" * 161,
            )

    def test_exact_named_safe_edit_can_be_discovered_without_reading_its_value(self) -> None:
        calls: list[tuple[int, str, str]] = []

        def edit_probe(process_id: int, process_name: str, name: str):
            calls.append((process_id, process_name, name))
            return NamedAutomationControlObservation(
                runtime_id=(42, process_id, 11),
                process_id=process_id,
                process_name=process_name,
                name=name,
                control_type=50004,
                class_name="TextBox",
                is_enabled=True,
                is_offscreen=False,
                left=220,
                top=180,
                right=520,
                bottom=220,
                center_x_fraction=0.37,
                center_y_fraction=0.25,
                captured_at="2026-09-01T00:00:00+00:00",
                is_keyboard_focusable=True,
                has_keyboard_focus=False,
                is_password=False,
                is_value_pattern_available=True,
                value_is_read_only=False,
                source="test-exact-name-edit",
            )

        sense = NativeNamedAutomationControlSense(edit_probe_fn=edit_probe)
        observed = sense.find_unique_edit(
            process_id=330,
            process_name="customerapp.exe",
            name="账号",
        )

        self.assertEqual(calls, [(330, "customerapp.exe", "账号")])
        self.assertEqual(observed.runtime_id, (42, 330, 11))
        self.assertEqual(observed.control_type, 50004)
        self.assertTrue(observed.is_keyboard_focusable)
        self.assertFalse(observed.is_password)
        self.assertFalse(observed.value_is_read_only)
        self.assertFalse(hasattr(observed, "value"))
        self.assertFalse(hasattr(observed, "text"))

    def test_password_read_only_or_nonfocusable_named_edit_is_rejected(self) -> None:
        def unsafe(*, password: bool = False, read_only: bool = False, focusable: bool = True):
            def probe(process_id: int, process_name: str, name: str):
                return NamedAutomationControlObservation(
                    runtime_id=(42, process_id, 12),
                    process_id=process_id,
                    process_name=process_name,
                    name=name,
                    control_type=50004,
                    class_name="TextBox",
                    is_enabled=True,
                    is_offscreen=False,
                    left=220,
                    top=180,
                    right=520,
                    bottom=220,
                    center_x_fraction=0.37,
                    center_y_fraction=0.25,
                    captured_at="2026-09-01T00:00:00+00:00",
                    is_keyboard_focusable=focusable,
                    has_keyboard_focus=False,
                    is_password=password,
                    is_value_pattern_available=True,
                    value_is_read_only=read_only,
                )
            return probe

        for probe in (
            unsafe(password=True),
            unsafe(read_only=True),
            unsafe(focusable=False),
        ):
            sense = NativeNamedAutomationControlSense(edit_probe_fn=probe)
            with self.assertRaisesRegex(ValueError, "requested Edit"):
                sense.find_unique_edit(
                    process_id=330,
                    process_name="customerapp.exe",
                    name="账号",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
