from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.machine_capability import _wmi_property_text


class _BrokenDirectRow:
    def __init__(self) -> None:
        self.Properties_ = (
            SimpleNamespace(Name="Name", Value="Intel Arc"),
            SimpleNamespace(Name="PNPDeviceID", Value=r"PCI\VEN_8086"),
        )

    @property
    def Name(self):
        raise NameError("dynamic property binding unavailable")

    @property
    def PNPDeviceID(self):
        raise NameError("dynamic property binding unavailable")


class MachineGpuProbeTests(unittest.TestCase):
    def test_wmi_property_falls_back_to_properties_collection(self) -> None:
        row = _BrokenDirectRow()

        self.assertEqual(_wmi_property_text(row, "Name"), "Intel Arc")
        self.assertEqual(
            _wmi_property_text(row, "PNPDeviceID"),
            r"PCI\VEN_8086",
        )

    def test_wmi_property_prefers_direct_attribute_when_available(self) -> None:
        row = SimpleNamespace(Name="Direct GPU")

        self.assertEqual(_wmi_property_text(row, "Name"), "Direct GPU")

    def test_missing_wmi_property_fails_closed_to_empty_text(self) -> None:
        row = SimpleNamespace(Properties_=())

        self.assertEqual(_wmi_property_text(row, "Name"), "")


if __name__ == "__main__":
    unittest.main()
