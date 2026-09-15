from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core import browser_desktop_record_transfer_behavior as transfer


CUSTOMER = "CUST-FRESH-14"
VALUE = "需跟进"


class _RotatingExtension:
    def __init__(self) -> None:
        self.calls = 0

    def authorized_tab(self):
        self.calls += 1
        generation = "generation-1" if self.calls == 1 else "generation-2"
        return SimpleNamespace(tab_id=91, attached_at=generation)


class _BrowserResident:
    def __init__(self) -> None:
        self.user_browser_extension = _RotatingExtension()

    def _observe_authorized_anchor(self, anchor: str):
        self.asserted_anchor = anchor
        return {
            "tab_id": 91,
            "url": "https://example.test/customers",
            "title": "客户跟进列表",
            "context": f"{CUSTOMER} {VALUE}",
            "observed_at": "2026-09-13T12:00:00Z",
            "source": "test-browser",
        }


class _BindingResident:
    def __init__(self, *, key_read_only: bool = True, value_read_only: bool = False) -> None:
        self.foreground = SimpleNamespace(
            process_id=4242,
            process_name="fixture.exe",
            window_handle=5151,
            title="客户记录编辑",
        )
        self.foreground_window = SimpleNamespace(probe=lambda: self.foreground)
        self.controls = {
            "客户编号": SimpleNamespace(
                name="客户编号",
                control_type=50004,
                runtime_id=(1, 1),
                value_is_read_only=key_read_only,
            ),
            "跟进状态": SimpleNamespace(
                name="跟进状态",
                control_type=50004,
                runtime_id=(2, 1),
                value_is_read_only=value_read_only,
            ),
        }
        self.named_automation_control = SimpleNamespace(find_unique_edit=self._find)
        self.current_app_text_content = SimpleNamespace(
            list_value_edits=self._list_value_edits,
            read_exact=self._read,
        )

    def _find(self, *, name: str, **_kwargs):
        return self.controls[name]

    def _list_value_edits(self, **_kwargs):
        return tuple(self.controls.values())

    def _read(self, *, name: str, **_kwargs):
        text = CUSTOMER if name == "客户编号" else "未跟进"
        return SimpleNamespace(text=text, audit={})


def _source():
    return {
        "tab_id": 91,
        "authorization_attached_at": "generation-1",
        "url": transfer._bounded_audit("https://example.test/customers"),
        "title": transfer._bounded_audit("客户跟进列表"),
        "row": transfer._bounded_audit(f"{CUSTOMER} {VALUE}"),
        "business_key": transfer._bounded_audit(CUSTOMER),
        "value": transfer._bounded_audit(VALUE),
        "observed_at": "2026-09-13T12:00:00Z",
        "source": "test-browser",
    }


def _meta():
    return {
        "process_id": 4242,
        "process_name": "fixture.exe",
        "source_window_handle": 5151,
        "business_key": transfer._bounded_audit(CUSTOMER),
        "destination_initial_value": transfer._bounded_audit("未跟进"),
        "source": _source(),
    }


class FreshAuthorityTests(unittest.TestCase):
    def test_browser_authorization_generation_drift_during_observation_fails_closed(self):
        resident = _BrowserResident()
        with self.assertRaisesRegex(RuntimeError, "authorization generation changed"):
            transfer._source_observation(resident)
        self.assertEqual(resident.asserted_anchor, transfer._SOURCE_ANCHOR)

    def test_fresh_business_key_must_still_be_read_only(self):
        resident = _BindingResident(key_read_only=False)
        with patch.object(
            transfer,
            "_source_observation",
            return_value=(_source(), CUSTOMER, VALUE),
        ):
            with self.assertRaisesRegex(RuntimeError, "business-key field is no longer read-only"):
                transfer._fresh_binding(
                    resident,
                    _meta(),
                    require_hwnd=True,
                    require_initial_value=True,
                )

    def test_fresh_destination_field_must_still_be_writable_before_commit(self):
        resident = _BindingResident(value_read_only=True)
        with patch.object(
            transfer,
            "_source_observation",
            return_value=(_source(), CUSTOMER, VALUE),
        ):
            with self.assertRaisesRegex(RuntimeError, "transfer field is no longer writable"):
                transfer._fresh_binding(
                    resident,
                    _meta(),
                    require_hwnd=True,
                    require_initial_value=True,
                )


if __name__ == "__main__":
    unittest.main()
