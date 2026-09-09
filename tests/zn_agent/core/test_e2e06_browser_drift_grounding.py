from __future__ import annotations

import unittest
from typing import Any

from zn_agent.core.user_browser_extension_relay import UserBrowserExtensionRelayError
from zn_agent.core.user_browser_managed_research_resident import (
    UserBrowserManagedResearchResidentRuntime,
)


_PAGE_URL = "https://shop.test/orders/alice"
_POST_URL = "https://shop.test/orders/alice?saved=1"


def _textbox(
    *,
    name: str = "Customer follow-up",
    query_parameter: str = "case_update",
    signature: str = "drift-signature",
    action: str = _POST_URL,
    text_length: int = 0,
    sensitive: bool = False,
) -> dict[str, Any]:
    return {
        "role": "textbox",
        "name": name,
        "enabled": True,
        "visible": True,
        "editable": True,
        "sensitive": sensitive,
        "text_length": text_length,
        "form_method": "post",
        "form_action": action,
        "form_signature": signature,
        "query_parameter": query_parameter,
    }


def _button(
    *,
    name: str = "Commit change",
    signature: str = "drift-signature",
    action: str = _POST_URL,
    sensitive: bool = False,
) -> dict[str, Any]:
    return {
        "role": "button",
        "name": name,
        "enabled": True,
        "visible": True,
        "clickable": True,
        "sensitive": sensitive,
        "form_method": "post",
        "form_action": action,
        "form_signature": signature,
    }


def _sense(*candidates: dict[str, Any], truncated: bool = False) -> dict[str, Any]:
    return {
        "url": _PAGE_URL,
        "truncated": truncated,
        "candidates": list(candidates),
    }


class E2E06BrowserDriftGroundingTests(unittest.TestCase):
    def test_unique_safe_post_form_regrounds_after_accessible_and_control_names_drift(self) -> None:
        grounded = UserBrowserManagedResearchResidentRuntime._note_update_form_from_sense(
            _sense(_textbox(), _button())
        )

        self.assertEqual(grounded["textbox_name"], "Customer follow-up")
        self.assertEqual(grounded["textbox_query_parameter"], "case_update")
        self.assertEqual(grounded["button_name"], "Commit change")
        self.assertEqual(grounded["form_signature"], "drift-signature")
        self.assertEqual(grounded["expected_url"], _POST_URL)

    def test_explicit_note_cue_beats_structural_fallback_when_multiple_post_inputs_exist(self) -> None:
        grounded = UserBrowserManagedResearchResidentRuntime._note_update_form_from_sense(
            _sense(
                _textbox(
                    name="Customer follow-up",
                    query_parameter="case_update",
                    signature="generic-signature",
                ),
                _button(signature="generic-signature"),
                _textbox(
                    name="Customer details",
                    query_parameter="note",
                    signature="note-signature",
                ),
                _button(name="Save note", signature="note-signature"),
            )
        )

        self.assertEqual(grounded["textbox_name"], "Customer details")
        self.assertEqual(grounded["textbox_query_parameter"], "note")
        self.assertEqual(grounded["button_name"], "Save note")
        self.assertEqual(grounded["form_signature"], "note-signature")

    def test_two_uncued_safe_post_textboxes_fail_closed(self) -> None:
        with self.assertRaises(UserBrowserExtensionRelayError):
            UserBrowserManagedResearchResidentRuntime._note_update_form_from_sense(
                _sense(
                    _textbox(signature="first-signature"),
                    _button(signature="first-signature"),
                    _textbox(
                        name="Case detail",
                        query_parameter="case_detail",
                        signature="second-signature",
                    ),
                    _button(name="Commit second", signature="second-signature"),
                )
            )

    def test_two_uncued_same_form_buttons_fail_closed(self) -> None:
        with self.assertRaises(UserBrowserExtensionRelayError):
            UserBrowserManagedResearchResidentRuntime._note_update_form_from_sense(
                _sense(
                    _textbox(),
                    _button(name="Commit change"),
                    _button(name="Send update"),
                )
            )

    def test_explicit_save_cue_breaks_same_form_button_ambiguity(self) -> None:
        grounded = UserBrowserManagedResearchResidentRuntime._note_update_form_from_sense(
            _sense(
                _textbox(),
                _button(name="Commit change"),
                _button(name="Save note"),
            )
        )

        self.assertEqual(grounded["textbox_name"], "Customer follow-up")
        self.assertEqual(grounded["button_name"], "Save note")

    def test_cross_origin_post_is_rejected_even_when_it_is_unique(self) -> None:
        with self.assertRaises(UserBrowserExtensionRelayError):
            UserBrowserManagedResearchResidentRuntime._note_update_form_from_sense(
                _sense(
                    _textbox(action="https://other.test/save"),
                    _button(action="https://other.test/save"),
                )
            )

    def test_sensitive_textbox_is_rejected_even_when_it_is_unique(self) -> None:
        with self.assertRaises(UserBrowserExtensionRelayError):
            UserBrowserManagedResearchResidentRuntime._note_update_form_from_sense(
                _sense(_textbox(sensitive=True), _button())
            )

    def test_truncated_sense_is_rejected_before_structural_fallback(self) -> None:
        with self.assertRaises(UserBrowserExtensionRelayError):
            UserBrowserManagedResearchResidentRuntime._note_update_form_from_sense(
                _sense(_textbox(), _button(), truncated=True)
            )

    def test_nonempty_textbox_is_not_overwritten_by_structural_fallback(self) -> None:
        with self.assertRaises(UserBrowserExtensionRelayError):
            UserBrowserManagedResearchResidentRuntime._note_update_form_from_sense(
                _sense(_textbox(text_length=18), _button())
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
