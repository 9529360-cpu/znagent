from __future__ import annotations

import ctypes
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.windows_companion_body import WindowsCompanionAwareBody
from zn_agent.core.windows_wifi import (
    WindowsWifiError,
    WindowsWifiInterfaceObservation,
    WindowsWifiObservation,
    WindowsWifiUnavailable,
    _WLAN_INTERFACE_INFO,
    _WLAN_INTERFACE_INFO_LIST,
    _interface_state_name,
    _parse_interface_list,
    _raise_native_error,
    read_windows_wifi_state,
)


class WindowsWifiNativeTests(unittest.TestCase):
    def test_interface_state_names_match_native_wifi_contract(self) -> None:
        self.assertEqual(_interface_state_name(0), "not_ready")
        self.assertEqual(_interface_state_name(1), "connected")
        self.assertEqual(_interface_state_name(4), "disconnected")
        self.assertEqual(_interface_state_name(7), "authenticating")
        self.assertEqual(_interface_state_name(999), "unknown")
        self.assertEqual(_interface_state_name("bad"), "unknown")

    def test_parse_interface_list_reads_bounded_native_rows(self) -> None:
        count = 2
        size = (
            _WLAN_INTERFACE_INFO_LIST.InterfaceInfo.offset
            + count * ctypes.sizeof(_WLAN_INTERFACE_INFO)
        )
        buffer = ctypes.create_string_buffer(size)
        pointer = ctypes.cast(
            buffer,
            ctypes.POINTER(_WLAN_INTERFACE_INFO_LIST),
        )
        pointer.contents.dwNumberOfItems = count
        base = (
            ctypes.addressof(buffer)
            + _WLAN_INTERFACE_INFO_LIST.InterfaceInfo.offset
        )

        first = _WLAN_INTERFACE_INFO.from_address(base)
        first.strInterfaceDescription = "Intel Wi-Fi 7"
        first.isState = 1

        second = _WLAN_INTERFACE_INFO.from_address(
            base + ctypes.sizeof(_WLAN_INTERFACE_INFO)
        )
        second.strInterfaceDescription = "USB Wireless"
        second.isState = 4

        rows = _parse_interface_list(pointer)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].description, "Intel Wi-Fi 7")
        self.assertEqual(rows[0].state, "connected")
        self.assertTrue(rows[0].connected)
        self.assertEqual(rows[1].description, "USB Wireless")
        self.assertEqual(rows[1].state, "disconnected")
        self.assertFalse(rows[1].connected)

    @patch("zn_agent.core.windows_wifi.platform.system", return_value="Linux")
    def test_non_windows_platform_fails_closed(self, _platform) -> None:
        with self.assertRaises(WindowsWifiUnavailable):
            read_windows_wifi_state()

    def test_service_not_active_is_unavailable_not_success(self) -> None:
        with self.assertRaises(WindowsWifiUnavailable):
            _raise_native_error("WlanOpenHandle", 1062)

    def test_unexpected_native_error_is_unknown_capability_error(self) -> None:
        with self.assertRaises(WindowsWifiError):
            _raise_native_error("WlanEnumInterfaces", 87)


class WindowsWifiBodyTests(unittest.TestCase):
    @staticmethod
    def _body() -> WindowsCompanionAwareBody:
        return WindowsCompanionAwareBody(
            device_capabilities=SimpleNamespace()
        )

    @patch(
        "zn_agent.core.windows_companion_body.read_windows_wifi_state",
        return_value=WindowsWifiObservation(
            (
                WindowsWifiInterfaceObservation(
                    "Intel Wi-Fi",
                    "connected",
                    True,
                ),
                WindowsWifiInterfaceObservation(
                    "USB Wi-Fi",
                    "disconnected",
                    False,
                ),
            ),
            "2026-09-21T12:00:00Z",
        ),
    )
    def test_wifi_read_is_bounded_read_only_body_evidence(
        self,
        read_wifi,
    ) -> None:
        result = self._body().act("windows_network_wifi_read")

        self.assertTrue(result.success)
        self.assertTrue(result.data["read_only"])
        self.assertFalse(result.data["dispatch_sent"])
        self.assertTrue(result.data["connected"])
        self.assertEqual(result.data["interface_count"], 2)
        self.assertEqual(result.data["connected_interface_count"], 1)
        self.assertEqual(
            result.data["interfaces"],
            [
                {
                    "description": "Intel Wi-Fi",
                    "state": "connected",
                    "connected": True,
                },
                {
                    "description": "USB Wi-Fi",
                    "state": "disconnected",
                    "connected": False,
                },
            ],
        )
        self.assertNotIn("ssid", repr(result.data).lower())
        self.assertNotIn("bssid", repr(result.data).lower())
        read_wifi.assert_called_once_with()

    @patch("zn_agent.core.windows_companion_body.read_windows_wifi_state")
    def test_wifi_read_rejects_arguments_without_native_call(
        self,
        read_wifi,
    ) -> None:
        result = self._body().act(
            "windows_network_wifi_read",
            ssid="private-network",
        )

        self.assertFalse(result.success)
        self.assertEqual(
            result.data.get("disposition"),
            "unexpected_arguments",
        )
        self.assertFalse(result.data.get("dispatch_sent"))
        self.assertNotIn("private-network", repr(result))
        read_wifi.assert_not_called()


if __name__ == "__main__":
    unittest.main()
