from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.side_effect_body import SideEffectAwareBody
from zn_agent.core.store import KernelStore


class _GenericInputBody(SideEffectAwareBody):
    def __init__(self, *, store=None):
        super().__init__(store=store)
        self.pointer_x = 50
        self.pointer_y = 20
        self.screen_width = 101
        self.screen_height = 51
        self.clicks: list[str] = []
        self.scrolls: list[tuple[str, int]] = []
        self.drags: list[tuple[str, float, float]] = []
        self.key_sequences: list[tuple[str, ...]] = []
        self.partial_keys = False

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

    def _send_primary_pointer_click(self, button: str) -> bool:
        self.clicks.append(str(button))
        return True

    def _send_primary_pointer_scroll(self, axis: str, steps: int) -> bool:
        self.scrolls.append((str(axis), int(steps)))
        return True

    def _send_primary_pointer_drag(
        self,
        *,
        button: str,
        end_x_fraction: float,
        end_y_fraction: float,
    ) -> bool:
        self.drags.append((str(button), float(end_x_fraction), float(end_y_fraction)))
        self.pointer_x = int(round(float(end_x_fraction) * (self.screen_width - 1)))
        self.pointer_y = int(round(float(end_y_fraction) * (self.screen_height - 1)))
        return True

    def _send_keyboard_keys(self, keys: tuple[str, ...]) -> tuple[int, int]:
        self.key_sequences.append(tuple(keys))
        expected = len(keys) * 2
        if self.partial_keys:
            return expected - 1, expected
        return expected, expected


class GenericInputBodyTests(unittest.TestCase):
    def test_pointer_click_supports_right_and_middle_without_implicit_move(self) -> None:
        body = _GenericInputBody()

        right = body.act(
            "pointer_click",
            x_fraction=0.5,
            y_fraction=0.4,
            button="right",
        )
        middle = body.act(
            "pointer_click",
            x_fraction=0.5,
            y_fraction=0.4,
            button="middle",
        )

        self.assertTrue(right.success, right.error)
        self.assertTrue(middle.success, middle.error)
        self.assertEqual(body.clicks, ["right", "middle"])
        self.assertEqual((body.pointer_x, body.pointer_y), (50, 20))

    def test_right_click_with_event_id_uses_generic_replay_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            try:
                body = _GenericInputBody(store=store)
                first = body.act(
                    "pointer_click",
                    event_id="evt-right-click",
                    x_fraction=0.5,
                    y_fraction=0.4,
                    button="right",
                )
                second = body.act(
                    "pointer_click",
                    event_id="evt-right-click",
                    x_fraction=0.5,
                    y_fraction=0.4,
                    button="right",
                )

                self.assertTrue(first.success, first.error)
                self.assertEqual(body.clicks, ["right"])
                self.assertFalse(second.success)
                self.assertTrue(second.data["replay_blocked"])
                self.assertEqual(body.clicks, ["right"])
            finally:
                store.close()

    def test_scroll_requires_explicit_current_target_and_replay_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            try:
                body = _GenericInputBody(store=store)
                first = body.act(
                    "pointer_scroll",
                    event_id="evt-scroll",
                    x_fraction=0.5,
                    y_fraction=0.4,
                    axis="vertical",
                    steps=-3,
                )
                second = body.act(
                    "pointer_scroll",
                    event_id="evt-scroll",
                    x_fraction=0.5,
                    y_fraction=0.4,
                    axis="vertical",
                    steps=-3,
                )

                self.assertTrue(first.success, first.error)
                self.assertEqual(first.data["wheel_delta"], -360)
                self.assertEqual(body.scrolls, [("vertical", -3)])
                self.assertFalse(second.success)
                self.assertTrue(second.data["replay_blocked"])
                self.assertEqual(body.scrolls, [("vertical", -3)])
            finally:
                store.close()

    def test_scroll_refuses_stale_pointer_and_fractional_steps(self) -> None:
        body = _GenericInputBody()
        body.pointer_x = 0

        stale = body.act(
            "pointer_scroll",
            x_fraction=0.5,
            y_fraction=0.4,
            axis="vertical",
            steps=1,
        )
        fractional = body.act(
            "pointer_scroll",
            x_fraction=0.0,
            y_fraction=0.4,
            axis="vertical",
            steps=1.5,
        )

        self.assertFalse(stale.success)
        self.assertIn("current cursor position", stale.error or "")
        self.assertFalse(fractional.success)
        self.assertIn("must be an integer", fractional.error or "")
        self.assertEqual(body.scrolls, [])

    def test_drag_requires_start_and_confirms_end_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            try:
                body = _GenericInputBody(store=store)
                result = body.act(
                    "pointer_drag",
                    event_id="evt-drag",
                    start_x_fraction=0.5,
                    start_y_fraction=0.4,
                    end_x_fraction=0.8,
                    end_y_fraction=0.6,
                    button="left",
                )

                self.assertTrue(result.success, result.error)
                self.assertEqual(body.drags, [("left", 0.8, 0.6)])
                self.assertTrue(result.data["end_position_verified"])
                self.assertEqual(
                    (result.data["observed_end_x"], result.data["observed_end_y"]),
                    (80, 30),
                )
            finally:
                store.close()

    def test_drag_never_repositions_stale_start(self) -> None:
        body = _GenericInputBody()
        body.pointer_x = 10

        result = body.act(
            "pointer_drag",
            start_x_fraction=0.5,
            start_y_fraction=0.4,
            end_x_fraction=0.8,
            end_y_fraction=0.6,
        )

        self.assertFalse(result.success)
        self.assertIn("explicit drag start", result.error or "")
        self.assertEqual(body.drags, [])

    def test_keyboard_chord_is_structured_normalized_and_replay_guarded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            try:
                body = _GenericInputBody(store=store)
                first = body.act(
                    "keyboard_chord",
                    event_id="evt-chord",
                    keys=["control", "shift", "s"],
                )
                second = body.act(
                    "keyboard_chord",
                    event_id="evt-chord",
                    keys=["control", "shift", "s"],
                )

                self.assertTrue(first.success, first.error)
                self.assertEqual(first.data["keys"], ["ctrl", "shift", "s"])
                self.assertEqual(body.key_sequences, [("ctrl", "shift", "s")])
                self.assertFalse(second.success)
                self.assertTrue(second.data["replay_blocked"])
                self.assertEqual(body.key_sequences, [("ctrl", "shift", "s")])
            finally:
                store.close()

    def test_keyboard_key_supports_navigation_and_rejects_freeform_key_names(self) -> None:
        body = _GenericInputBody()

        result = body.act("keyboard_key", key="PgDn")
        invalid = body.act("keyboard_key", key="save_document")

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.data["keys"], ["page_down"])
        self.assertEqual(body.key_sequences, [("page_down",)])
        self.assertFalse(invalid.success)
        self.assertIn("unsupported keyboard key", invalid.error or "")

    def test_keyboard_chord_requires_modifiers_before_final_key(self) -> None:
        body = _GenericInputBody()
        cases = (
            ["s", "ctrl"],
            ["ctrl", "alt"],
            ["ctrl", "ctrl", "s"],
            ["ctrl", "shift", "alt", "win", "s"],
        )

        for keys in cases:
            with self.subTest(keys=keys):
                result = body.act("keyboard_chord", keys=keys)
                self.assertFalse(result.success)

        self.assertEqual(body.key_sequences, [])

    def test_partial_keyboard_send_is_uncertain_and_not_replayed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            try:
                body = _GenericInputBody(store=store)
                body.partial_keys = True
                first = body.act(
                    "keyboard_chord",
                    event_id="evt-partial",
                    keys=["ctrl", "s"],
                )
                second = body.act(
                    "keyboard_chord",
                    event_id="evt-partial",
                    keys=["ctrl", "s"],
                )

                self.assertFalse(first.success)
                self.assertTrue(first.data["side_effect_uncertain"])
                self.assertEqual(body.key_sequences, [("ctrl", "s")])
                self.assertFalse(second.success)
                self.assertTrue(second.data["replay_blocked"])
                self.assertEqual(body.key_sequences, [("ctrl", "s")])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
