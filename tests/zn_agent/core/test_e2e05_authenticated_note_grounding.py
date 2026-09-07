from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.user_browser_extension_relay import UserBrowserExtensionRelayError
from zn_agent.core.user_browser_managed_research_resident import (
    UserBrowserManagedResearchResidentRuntime,
)


_TASK = "查一下 Alice 最近的订单，再去官网核对退货规则，然后回来把备注更新成官网写的退货时限。"


class E2E05AuthenticatedNoteGroundingTests(unittest.TestCase):
    def test_normal_language_task_is_recognized_without_urls_or_engineering_targets(self) -> None:
        event = SimpleNamespace(task=_TASK, payload={"model_policy": "never"})
        self.assertTrue(
            UserBrowserManagedResearchResidentRuntime._natural_authenticated_return_note_update(event)
        )
        self.assertEqual(
            UserBrowserManagedResearchResidentRuntime._order_subject(_TASK),
            "Alice",
        )
        self.assertFalse(
            UserBrowserManagedResearchResidentRuntime._natural_authenticated_return_note_update(
                SimpleNamespace(task="查一下 Alice 最近的订单。", payload={})
            )
        )

    def test_official_return_policy_reference_must_be_unambiguous(self) -> None:
        ranked = UserBrowserManagedResearchResidentRuntime._rank_return_policy_candidates(
            [
                {"href": "https://shop.test/help", "text": "Help"},
                {
                    "href": "https://shop.test/official-return-policy",
                    "text": "Official return policy",
                },
            ]
        )
        self.assertEqual(
            ranked,
            [
                {
                    "href": "https://shop.test/official-return-policy",
                    "text": "Official return policy",
                }
            ],
        )

    def test_policy_extraction_is_label_grounded_and_rejects_conflicting_values(self) -> None:
        self.assertEqual(
            UserBrowserManagedResearchResidentRuntime._return_policy(
                "Official return policy: Returns accepted within 30 days of delivery."
            ),
            "Returns accepted within 30 days of delivery.",
        )
        self.assertIsNone(
            UserBrowserManagedResearchResidentRuntime._return_policy(
                "Return policy: 30 days\nReturn policy: 60 days"
            )
        )

    def test_note_form_requires_one_empty_safe_post_textbox_and_same_form_save_button(self) -> None:
        sense = {
            "url": "https://shop.test/orders/alice",
            "truncated": False,
            "candidates": [
                {
                    "role": "textbox",
                    "name": "Order search",
                    "enabled": True,
                    "visible": True,
                    "editable": True,
                    "sensitive": False,
                    "text_length": 0,
                    "form_method": "get",
                    "form_action": "https://shop.test/orders/alice",
                    "form_signature": "search-signature",
                },
                {
                    "role": "textbox",
                    "name": "Order note",
                    "enabled": True,
                    "visible": True,
                    "editable": True,
                    "sensitive": False,
                    "text_length": 0,
                    "form_method": "post",
                    "form_action": "https://shop.test/orders/alice?saved=1",
                    "form_signature": "note-signature",
                },
                {
                    "role": "button",
                    "name": "Save note",
                    "enabled": True,
                    "visible": True,
                    "clickable": True,
                    "sensitive": False,
                    "form_method": "post",
                    "form_action": "https://shop.test/orders/alice?saved=1",
                    "form_signature": "note-signature",
                },
            ],
        }
        grounded = UserBrowserManagedResearchResidentRuntime._note_update_form_from_sense(sense)
        self.assertEqual(grounded["textbox_name"], "Order note")
        self.assertEqual(grounded["button_name"], "Save note")
        self.assertEqual(
            grounded["expected_url"],
            "https://shop.test/orders/alice?saved=1",
        )

        ambiguous = dict(sense)
        ambiguous["candidates"] = list(sense["candidates"]) + [
            {
                "role": "textbox",
                "name": "Internal note",
                "enabled": True,
                "visible": True,
                "editable": True,
                "sensitive": False,
                "text_length": 0,
                "form_method": "post",
                "form_action": "https://shop.test/orders/alice?saved=1",
                "form_signature": "other-note-signature",
            }
        ]
        with self.assertRaises(UserBrowserExtensionRelayError):
            UserBrowserManagedResearchResidentRuntime._note_update_form_from_sense(ambiguous)

    def test_cross_origin_note_post_is_rejected(self) -> None:
        sense = {
            "url": "https://shop.test/orders/alice",
            "truncated": False,
            "candidates": [
                {
                    "role": "textbox",
                    "name": "Order note",
                    "enabled": True,
                    "visible": True,
                    "editable": True,
                    "sensitive": False,
                    "text_length": 0,
                    "form_method": "post",
                    "form_action": "https://other.test/save",
                    "form_signature": "note-signature",
                },
                {
                    "role": "button",
                    "name": "Save note",
                    "enabled": True,
                    "visible": True,
                    "clickable": True,
                    "sensitive": False,
                    "form_method": "post",
                    "form_action": "https://other.test/save",
                    "form_signature": "note-signature",
                },
            ],
        }
        with self.assertRaises(UserBrowserExtensionRelayError):
            UserBrowserManagedResearchResidentRuntime._note_update_form_from_sense(sense)


if __name__ == "__main__":
    unittest.main(verbosity=2)
