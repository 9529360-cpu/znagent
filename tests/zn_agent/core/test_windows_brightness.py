from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.store import KernelStore
import zn_agent.core.windows_brightness as windows_brightness
from zn_agent.core.windows_brightness import (
    WindowsBrightnessDispatchUncertain,
    WindowsBrightnessObservation,
    WindowsBrightnessUnavailable,
    read_active_brightness,
    set_active_brightness,
    validate_brightness_percent,
)
from zn_agent.core.windows_companion_body import WindowsCompanionAwareBody


class _Property:
    def __init__(self, name: str, value=None) -> None:
        self.Name = name
        self.Value = value


class _Properties:
    def __init__(self, values: dict[str, object]) -> None:
        self._items = {name: _Property(name, value) for name, value in values.items()}

    def __iter__(self):
        return iter(self._items.values())

    def Item(self, name: str):
        return self._items[name]


class _Parameters:
    def __init__(self) -> None:
        self.Properties_ = _Properties({"Timeout": None, "Brightness": None})


class _InParameters:
    def __init__(self) -> None:
        self.last = None

    def SpawnInstance_(self):
        self.last = _Parameters()
        return self.last


class _Method:
    def __init__(self) -> None:
        self.InParameters = _InParameters()


class _Methods:
    def __init__(self) -> None:
        self.method = _Method()

    def Item(self, name: str):
        if name != "WmiSetBrightness":
            raise KeyError(name)
        return self.method


class _BrightnessRow:
    def __init__(self, *, active: bool, level: float, instance: str) -> None:
        self.Properties_ = _Properties(
            {
                "Active": active,
                "CurrentBrightness": level,
                "InstanceName": instance,
            }
        )


class _MethodRow:
    def __init__(self, instance: str) -> None:
        self.Properties_ = _Properties({"InstanceName": instance})
        self.SystemProperties_ = _Properties(
            {"__RELPATH": f'WmiMonitorBrightnessMethods.InstanceName="{instance}"'}
        )
        self.Methods_ = _Methods()


class _BrightnessService:
    def __init__(
        self,
        *,
        active_rows: list[tuple[str, float]] | None = None,
    ) -> None:
        self.active_rows = list(active_rows or [("DISPLAY\\PANEL_0", 40.0)])
        self.exec_method_calls = []

    def ExecQuery(self, query: str):
        if "WmiMonitorBrightnessMethods" in query:
            return [_MethodRow(instance) for instance, _level in self.active_rows]
        if "WmiMonitorBrightness" in query:
            return [
                _BrightnessRow(active=True, level=level, instance=instance)
                for instance, level in self.active_rows
            ]
        raise AssertionError(query)

    def ExecMethod(self, relpath: str, method: str, parameters) -> None:
        brightness = int(parameters.Properties_.Item("Brightness").Value)
        timeout = int(parameters.Properties_.Item("Timeout").Value)
        self.exec_method_calls.append((relpath, method, brightness, timeout))
        instance = relpath.split('"', 1)[1].rsplit('"', 1)[0]
        self.active_rows = [
            (name, float(brightness) if name == instance else level)
            for name, level in self.active_rows
        ]


class WindowsBrightnessValidationTests(unittest.TestCase):
    def test_brightness_percent_accepts_explicit_numeric_range(self) -> None:
        self.assertEqual(validate_brightness_percent(0), 0.0)
        self.assertEqual(validate_brightness_percent(42), 42.0)
        self.assertEqual(validate_brightness_percent("100"), 100.0)

    def test_brightness_percent_rejects_clamping_fractional_and_non_finite_values(self) -> None:
        for value in (-1, 42.5, 101, float("nan"), float("inf"), True, None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_brightness_percent(value)

    @patch("zn_agent.core.windows_brightness._brightness_service")
    def test_read_requires_one_unique_active_wmi_target(self, service_factory) -> None:
        service_factory.return_value = _BrightnessService(
            active_rows=[("DISPLAY\\ONE", 33.0), ("DISPLAY\\TWO", 44.0)]
        )

        with self.assertRaises(WindowsBrightnessUnavailable):
            read_active_brightness()

    @patch("zn_agent.core.windows_brightness._brightness_service")
    @patch(
        "zn_agent.core.windows_brightness.read_active_brightness",
        return_value=WindowsBrightnessObservation("DISPLAY\\NEW", 40.0),
    )
    def test_expected_monitor_identity_drift_fails_before_dispatch(
        self,
        _read_brightness,
        service_factory,
    ) -> None:
        with self.assertRaisesRegex(
            WindowsBrightnessUnavailable,
            "changed before dispatch",
        ):
            set_active_brightness(
                61,
                expected_instance_name="DISPLAY\\OLD",
            )

        service_factory.assert_not_called()

    @patch("zn_agent.core.windows_brightness._brightness_service")
    def test_set_uses_matching_wmi_method_and_fresh_readback(self, service_factory) -> None:
        service = _BrightnessService(active_rows=[("DISPLAY\\ONE", 40.0)])
        service_factory.return_value = service

        observed = set_active_brightness(61)

        self.assertEqual(observed.instance_name, "DISPLAY\\ONE")
        self.assertEqual(observed.level_percent, 61.0)
        self.assertEqual(len(service.exec_method_calls), 1)
        relpath, method, brightness, timeout = service.exec_method_calls[0]
        self.assertIn("DISPLAY\\ONE", relpath)
        self.assertEqual(method, "WmiSetBrightness")
        self.assertEqual(brightness, 61)
        self.assertEqual(timeout, 0)

    @patch("zn_agent.core.windows_brightness.time.sleep", return_value=None)
    @patch(
        "zn_agent.core.windows_brightness.time.monotonic",
        side_effect=[0.0, 0.0, 0.30, 1.60],
    )
    @patch(
        "zn_agent.core.windows_brightness.read_active_brightness",
        side_effect=[
            WindowsBrightnessObservation("DISPLAY\\ONE", 61.0),
            WindowsBrightnessObservation("DISPLAY\\ONE", 40.0),
            WindowsBrightnessObservation("DISPLAY\\ONE", 40.0),
        ],
    )
    def test_stabilization_rejects_transient_target_match(
        self,
        _read_brightness,
        _monotonic,
        _sleep,
    ) -> None:
        observed = windows_brightness._wait_for_stable_brightness(
            "DISPLAY\\ONE",
            61.0,
        )

        self.assertEqual(observed.level_percent, 40.0)

    @patch("zn_agent.core.windows_brightness.time.sleep", return_value=None)
    @patch(
        "zn_agent.core.windows_brightness.time.monotonic",
        side_effect=[0.0, 1.40, 1.50],
    )
    @patch(
        "zn_agent.core.windows_brightness.read_active_brightness",
        side_effect=[
            WindowsBrightnessObservation("DISPLAY\\ONE", 40.0),
            WindowsBrightnessObservation("DISPLAY\\ONE", 61.0),
        ],
    )
    def test_target_seen_only_at_deadline_is_still_uncertain(
        self,
        _read_brightness,
        _monotonic,
        _sleep,
    ) -> None:
        with self.assertRaisesRegex(
            WindowsBrightnessDispatchUncertain,
            "did not remain stable",
        ):
            windows_brightness._wait_for_stable_brightness(
                "DISPLAY\\ONE",
                61.0,
            )


class WindowsBrightnessBodyTests(unittest.TestCase):
    @staticmethod
    def _body() -> WindowsCompanionAwareBody:
        return WindowsCompanionAwareBody(device_capabilities=SimpleNamespace())

    @patch(
        "zn_agent.core.windows_companion_body.read_active_brightness",
        return_value=WindowsBrightnessObservation("DISPLAY\\ONE", 42.0),
    )
    def test_read_brightness_is_bounded_read_only_body_evidence(self, read_brightness) -> None:
        result = self._body().act("windows_display_brightness_read")

        self.assertTrue(result.success)
        self.assertEqual(result.data["level_percent"], 42.0)
        self.assertEqual(result.data["instance_name"], "DISPLAY\\ONE")
        self.assertTrue(result.data["read_only"])
        self.assertFalse(result.data["dispatch_sent"])
        read_brightness.assert_called_once_with()

    @patch(
        "zn_agent.core.windows_companion_body.set_active_brightness",
        return_value=WindowsBrightnessObservation("DISPLAY\\ONE", 67.0),
    )
    @patch(
        "zn_agent.core.windows_companion_body.read_active_brightness",
        return_value=WindowsBrightnessObservation("DISPLAY\\ONE", 31.0),
    )
    def test_set_brightness_reads_before_write_and_verifies(
        self,
        read_brightness,
        set_brightness,
    ) -> None:
        result = self._body().act(
            "windows_display_brightness_set",
            level_percent=67,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.data["previous_level_percent"], 31.0)
        self.assertEqual(result.data["observed_level_percent"], 67.0)
        self.assertTrue(result.data["verified"])
        self.assertTrue(result.data["dispatch_sent"])
        read_brightness.assert_called_once_with()
        set_brightness.assert_called_once_with(
            67.0,
            expected_instance_name="DISPLAY\\ONE",
        )

    @patch(
        "zn_agent.core.windows_companion_body.set_active_brightness",
        side_effect=WindowsBrightnessDispatchUncertain("post-dispatch readback unavailable"),
    )
    @patch(
        "zn_agent.core.windows_companion_body.read_active_brightness",
        return_value=WindowsBrightnessObservation("DISPLAY\\ONE", 31.0),
    )
    def test_post_dispatch_uncertainty_preserves_side_effect_evidence(
        self,
        _read_brightness,
        _set_brightness,
    ) -> None:
        result = self._body().act(
            "windows_display_brightness_set",
            level_percent=67,
        )

        self.assertFalse(result.success)
        self.assertTrue(result.data["dispatch_sent"])
        self.assertTrue(result.data["side_effect_uncertain"])
        self.assertFalse(result.data["verified"])
        self.assertIn("post-dispatch", result.error or "")

    @patch("zn_agent.core.windows_companion_body.set_active_brightness")
    @patch("zn_agent.core.windows_companion_body.read_active_brightness")
    def test_fractional_brightness_is_rejected_without_read_or_dispatch(
        self,
        read_brightness,
        set_brightness,
    ) -> None:
        result = self._body().act(
            "windows_display_brightness_set",
            level_percent=42.5,
        )

        self.assertFalse(result.success)
        self.assertIn("integer from 0 to 100", result.error or "")
        read_brightness.assert_not_called()
        set_brightness.assert_not_called()

    @patch(
        "zn_agent.core.windows_companion_body.set_active_brightness",
        return_value=WindowsBrightnessObservation("DISPLAY\\ONE", 67.0),
    )
    @patch(
        "zn_agent.core.windows_companion_body.read_active_brightness",
        return_value=WindowsBrightnessObservation("DISPLAY\\ONE", 31.0),
    )
    def test_event_bound_brightness_set_reuses_durable_replay_guard(
        self,
        read_brightness,
        set_brightness,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            body = WindowsCompanionAwareBody(
                store=store,
                device_capabilities=SimpleNamespace(),
            )
            try:
                first = body.act(
                    "windows_display_brightness_set",
                    event_id="evt-brightness-guard",
                    level_percent=67,
                )
                second = body.act(
                    "windows_display_brightness_set",
                    event_id="evt-brightness-guard",
                    level_percent=67,
                )
            finally:
                store.close()

        self.assertTrue(first.success)
        self.assertTrue(first.data["side_effect_dispatch_observed"])
        self.assertFalse(second.success)
        self.assertTrue(second.data["side_effect_uncertain"])
        self.assertTrue(second.data["replay_blocked"])
        set_brightness.assert_called_once_with(
            67.0,
            expected_instance_name="DISPLAY\\ONE",
        )
        read_brightness.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
