from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.store import KernelStore
from zn_agent.core.windows_audio import validate_volume_percent
from zn_agent.core.windows_companion_body import WindowsCompanionAwareBody


class WindowsAudioValidationTests(unittest.TestCase):
    def test_volume_percent_accepts_explicit_numeric_range(self) -> None:
        self.assertEqual(validate_volume_percent(0), 0.0)
        self.assertEqual(validate_volume_percent(42.5), 42.5)
        self.assertEqual(validate_volume_percent("100"), 100.0)

    def test_volume_percent_rejects_clamping_and_non_finite_values(self) -> None:
        for value in (-1, 101, float("nan"), float("inf"), True, None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_volume_percent(value)


class WindowsAudioBodyTests(unittest.TestCase):
    @staticmethod
    def _body() -> WindowsCompanionAwareBody:
        return WindowsCompanionAwareBody(device_capabilities=SimpleNamespace())

    @patch(
        "zn_agent.core.windows_companion_body.read_default_render_volume_percent",
        return_value=42.25,
    )
    def test_read_volume_is_bounded_read_only_body_evidence(self, read_volume) -> None:
        result = self._body().act("windows_audio_volume_read")

        self.assertTrue(result.success)
        self.assertEqual(result.data["level_percent"], 42.25)
        self.assertTrue(result.data["read_only"])
        self.assertFalse(result.data["dispatch_sent"])
        read_volume.assert_called_once_with()

    def test_read_volume_rejects_arguments_before_native_call(self) -> None:
        with patch(
            "zn_agent.core.windows_companion_body.read_default_render_volume_percent"
        ) as read_volume:
            result = self._body().act(
                "windows_audio_volume_read",
                unexpected=True,
            )

        self.assertFalse(result.success)
        self.assertEqual(result.data["disposition"], "unexpected_arguments")
        self.assertFalse(result.data["dispatch_sent"])
        read_volume.assert_not_called()

    @patch(
        "zn_agent.core.windows_companion_body.set_default_render_volume_percent",
        return_value=67.0,
    )
    @patch(
        "zn_agent.core.windows_companion_body.read_default_render_volume_percent",
        return_value=31.0,
    )
    def test_event_bound_volume_set_reuses_existing_durable_replay_guard(
        self,
        read_volume,
        set_volume,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            body = WindowsCompanionAwareBody(
                store=store,
                device_capabilities=SimpleNamespace(),
            )
            try:
                first = body.act(
                    "windows_audio_volume_set",
                    event_id="evt-volume-guard",
                    level_percent=67,
                )
                second = body.act(
                    "windows_audio_volume_set",
                    event_id="evt-volume-guard",
                    level_percent=67,
                )
            finally:
                store.close()

        self.assertTrue(first.success)
        self.assertTrue(first.data["side_effect_dispatch_observed"])
        self.assertTrue(first.data["side_effect_attempt_id"])
        self.assertFalse(second.success)
        self.assertTrue(second.data["side_effect_uncertain"])
        self.assertTrue(second.data["replay_blocked"])
        set_volume.assert_called_once_with(67.0)
        read_volume.assert_called_once_with()

    @patch(
        "zn_agent.core.windows_companion_body.set_default_render_volume_percent",
        return_value=67.0,
    )
    @patch(
        "zn_agent.core.windows_companion_body.read_default_render_volume_percent",
        return_value=31.0,
    )
    def test_set_volume_reads_before_write_and_verifies_fresh_readback(
        self,
        read_volume,
        set_volume,
    ) -> None:
        result = self._body().act(
            "windows_audio_volume_set",
            level_percent=67,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.data["previous_level_percent"], 31.0)
        self.assertEqual(result.data["requested_level_percent"], 67.0)
        self.assertEqual(result.data["observed_level_percent"], 67.0)
        self.assertTrue(result.data["verified"])
        self.assertTrue(result.data["dispatch_sent"])
        read_volume.assert_called_once_with()
        set_volume.assert_called_once_with(67.0)

    @patch(
        "zn_agent.core.windows_companion_body.set_default_render_volume_percent",
        return_value=61.0,
    )
    @patch(
        "zn_agent.core.windows_companion_body.read_default_render_volume_percent",
        return_value=31.0,
    )
    def test_set_volume_fails_when_postcondition_is_not_observed(
        self,
        _read_volume,
        _set_volume,
    ) -> None:
        result = self._body().act(
            "windows_audio_volume_set",
            level_percent=60,
        )

        self.assertFalse(result.success)
        self.assertTrue(result.data["dispatch_sent"])
        self.assertFalse(result.data["verified"])
        self.assertIn("readback", result.error)

    def test_set_volume_rejects_extra_arguments_without_dispatch(self) -> None:
        with patch(
            "zn_agent.core.windows_companion_body.set_default_render_volume_percent"
        ) as set_volume:
            result = self._body().act(
                "windows_audio_volume_set",
                level_percent=50,
                unexpected=True,
            )

        self.assertFalse(result.success)
        self.assertFalse(result.data["dispatch_sent"])
        set_volume.assert_not_called()


if __name__ == "__main__":
    unittest.main()
