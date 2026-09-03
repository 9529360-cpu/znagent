from __future__ import annotations

import unittest

from zn_agent.core.automation_named_control_sense import (
    NamedAutomationControlObservation,
    NativeNamedAutomationControlSense,
)


def _control(
    *,
    process_id: int,
    process_name: str,
    name: str,
    control_type: int,
    runtime_tail: int,
    focusable: bool = False,
    password: bool = False,
    read_only: bool | None = None,
) -> NamedAutomationControlObservation:
    return NamedAutomationControlObservation(
        runtime_id=(42, process_id, runtime_tail),
        process_id=process_id,
        process_name=process_name,
        name=name,
        control_type=control_type,
        class_name="TextBox" if control_type == 50004 else "Button",
        is_enabled=True,
        is_offscreen=False,
        left=100 + runtime_tail,
        top=100,
        right=300 + runtime_tail,
        bottom=140,
        center_x_fraction=0.30,
        center_y_fraction=0.20,
        captured_at="2026-09-01T00:00:00+00:00",
        is_keyboard_focusable=focusable,
        has_keyboard_focus=False,
        is_password=password,
        is_value_pattern_available=control_type == 50004,
        value_is_read_only=read_only,
        source="test-foreground-candidate",
    )


class NamedAutomationControlSenseTests(unittest.TestCase):
    def test_exact_button_probe_is_structurally_bounded(self) -> None:
        calls: list[tuple[int, str, str]] = []

        def probe(process_id: int, process_name: str, name: str):
            calls.append((process_id, process_name, name))
            return _control(
                process_id=process_id,
                process_name=process_name,
                name=name,
                control_type=50000,
                runtime_tail=7,
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
            return _control(
                process_id=process_id,
                process_name=process_name,
                name="删除",
                control_type=50000,
                runtime_tail=3,
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
            return _control(
                process_id=process_id,
                process_name=process_name,
                name=name,
                control_type=50004,
                runtime_tail=11,
                focusable=True,
                read_only=False,
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
                return _control(
                    process_id=process_id,
                    process_name=process_name,
                    name=name,
                    control_type=50004,
                    runtime_tail=12,
                    focusable=focusable,
                    password=password,
                    read_only=read_only,
                )
            return probe

        for probe in (
            unsafe(password=True),
            unsafe(read_only=True),
            unsafe(focusable=False),
        ):
            sense = NativeNamedAutomationControlSense(edit_probe_fn=probe)
            with self.assertRaisesRegex(ValueError, "safe Edit"):
                sense.find_unique_edit(
                    process_id=330,
                    process_name="customerapp.exe",
                    name="账号",
                )

    def test_fresh_candidate_sense_exposes_bounded_safe_names_from_current_process(self) -> None:
        calls: list[tuple[int, str, int]] = []

        def candidates(process_id: int, process_name: str, control_type: int):
            calls.append((process_id, process_name, control_type))
            names = (
                ("客户名称", 1),
                ("订单编号", 2),
                ("备注", 3),
            ) if control_type == 50004 else (("查找", 4), ("取消", 5))
            return tuple(
                _control(
                    process_id=process_id,
                    process_name=process_name,
                    name=name,
                    control_type=control_type,
                    runtime_tail=tail,
                    focusable=control_type == 50004,
                    read_only=False if control_type == 50004 else None,
                )
                for name, tail in names
            )

        sense = NativeNamedAutomationControlSense(candidate_probe_fn=candidates)
        edits = sense.list_safe_edits(process_id=330, process_name="customerapp.exe")
        buttons = sense.list_buttons(process_id=330, process_name="customerapp.exe")

        self.assertEqual([item.name for item in edits], ["客户名称", "订单编号", "备注"])
        self.assertEqual([item.name for item in buttons], ["查找", "取消"])
        self.assertEqual(calls, [(330, "customerapp.exe", 50004), (330, "customerapp.exe", 50000)])
        self.assertTrue(all(item.runtime_id for item in edits + buttons))
        self.assertTrue(all(not hasattr(item, "text") for item in edits))

    def test_candidate_probe_cannot_smuggle_unsafe_edit_into_grounding_set(self) -> None:
        def candidates(process_id: int, process_name: str, control_type: int):
            return (
                _control(
                    process_id=process_id,
                    process_name=process_name,
                    name="密码",
                    control_type=50004,
                    runtime_tail=9,
                    focusable=True,
                    password=True,
                    read_only=False,
                ),
            )

        sense = NativeNamedAutomationControlSense(candidate_probe_fn=candidates)
        with self.assertRaisesRegex(ValueError, "bounded safe Edit"):
            sense.list_safe_edits(process_id=330, process_name="customerapp.exe")

    def test_candidate_collection_is_hard_bounded_before_semantic_grounding(self) -> None:
        def candidates(process_id: int, process_name: str, control_type: int):
            return tuple(
                _control(
                    process_id=process_id,
                    process_name=process_name,
                    name=f"字段 {index}",
                    control_type=50004,
                    runtime_tail=index + 1,
                    focusable=True,
                    read_only=False,
                )
                for index in range(25)
            )

        sense = NativeNamedAutomationControlSense(candidate_probe_fn=candidates)
        with self.assertRaisesRegex(ValueError, "bounded collection"):
            sense.list_safe_edits(process_id=330, process_name="customerapp.exe")


if __name__ == "__main__":
    unittest.main(verbosity=2)
