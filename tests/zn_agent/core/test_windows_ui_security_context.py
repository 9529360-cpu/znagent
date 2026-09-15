from __future__ import annotations

import unittest

from zn_agent.core.device_capability_graph import DeviceCapabilityGraph
from zn_agent.core.foreground_window_sense import (
    ForegroundWindowObservation,
    NativeForegroundWindowSense,
)
from zn_agent.core.windows_foreground_companion import NativeWindowsForegroundCompanionSense
from zn_agent.core.windows_ui_security_context import NativeWindowsUiSecurityContextSense


class WindowsUiSecurityContextTests(unittest.TestCase):
    @staticmethod
    def _sense(*, resident_rid: int | None, foreground_rid: int | None):
        rows = {
            100: {
                "observable": resident_rid is not None,
                "integrity_rid": resident_rid,
                "elevated": False,
                "ui_access": False,
            },
            200: {
                "observable": foreground_rid is not None,
                "integrity_rid": foreground_rid,
                "elevated": foreground_rid is not None and foreground_rid >= 0x3000,
                "ui_access": False,
            },
        }
        return NativeWindowsUiSecurityContextSense(
            token_probe=lambda pid: rows.get(pid, {"observable": False}),
            current_process_id=lambda: 100,
        )

    def test_equal_integrity_is_sendinput_compatible(self) -> None:
        context = self._sense(resident_rid=0x2000, foreground_rid=0x2000).probe(
            foreground_process_id=200
        )
        self.assertTrue(context.platform_supported)
        self.assertEqual(context.resident.integrity_label, "medium")
        self.assertEqual(context.foreground.integrity_label, "medium")
        self.assertTrue(context.input_integrity_compatible)
        self.assertEqual(context.disposition, "compatible")

    def test_higher_integrity_foreground_is_explicit_uipi_mismatch(self) -> None:
        context = self._sense(resident_rid=0x2000, foreground_rid=0x3000).probe(
            foreground_process_id=200
        )
        self.assertFalse(context.input_integrity_compatible)
        self.assertEqual(context.disposition, "foreground_higher_integrity")
        self.assertEqual(context.resident.integrity_label, "medium")
        self.assertEqual(context.foreground.integrity_label, "high")
        self.assertTrue(context.foreground.elevated)

    def test_higher_resident_integrity_can_reach_lower_integrity_target_under_uipi_order(self) -> None:
        context = self._sense(resident_rid=0x3000, foreground_rid=0x2000).probe(
            foreground_process_id=200
        )
        self.assertTrue(context.input_integrity_compatible)
        self.assertEqual(context.disposition, "compatible")

    def test_unknown_target_integrity_remains_unknown_instead_of_guessing_compatible(self) -> None:
        context = self._sense(resident_rid=0x2000, foreground_rid=None).probe(
            foreground_process_id=200
        )
        self.assertIsNone(context.input_integrity_compatible)
        self.assertEqual(context.disposition, "foreground_integrity_unknown")
        self.assertFalse(context.foreground.observable)

    def test_missing_foreground_process_is_distinct_from_token_query_failure(self) -> None:
        context = self._sense(resident_rid=0x2000, foreground_rid=0x2000).probe(
            foreground_process_id=None
        )
        self.assertIsNone(context.foreground)
        self.assertIsNone(context.input_integrity_compatible)
        self.assertEqual(context.disposition, "foreground_process_unavailable")

    def test_integrity_labels_preserve_windows_mandatory_level_order(self) -> None:
        cases = (
            (0x0000, "untrusted"),
            (0x1000, "low"),
            (0x2000, "medium"),
            (0x2100, "medium_plus"),
            (0x3000, "high"),
            (0x4000, "system"),
            (0x5000, "protected"),
        )
        for rid, label in cases:
            with self.subTest(rid=rid):
                context = self._sense(resident_rid=rid, foreground_rid=rid).probe(
                    foreground_process_id=200
                )
                self.assertEqual(context.resident.integrity_label, label)

    def test_device_graph_binds_security_comparison_to_privacy_safe_foreground_pid(self) -> None:
        foreground = NativeWindowsForegroundCompanionSense(
            foreground_sense=NativeForegroundWindowSense(
                probe_fn=lambda: ForegroundWindowObservation(
                    process_id=200,
                    title="Sensitive title never enters security context",
                    process_name="target.exe",
                    class_name="TargetWindow",
                    captured_at="2026-09-15T00:00:00Z",
                    window_handle=300,
                )
            ),
            monitor_probe=lambda hwnd: {},
        )
        security = self._sense(resident_rid=0x2000, foreground_rid=0x3000)
        graph = DeviceCapabilityGraph(
            inventory_provider=lambda: [],
            process_provider=lambda: [],
            window_provider=lambda: [],
            cache_path=None,
            inventory_ttl_seconds=0,
            foreground_companion_sense=foreground,
            ui_security_context_sense=security,
        )
        context = graph.ui_security_context()
        self.assertEqual(context.foreground.process_id, 200)
        self.assertEqual(context.disposition, "foreground_higher_integrity")
        self.assertNotIn("Sensitive title", repr(context))
        self.assertFalse(hasattr(context, "window_title"))


if __name__ == "__main__":
    unittest.main()
