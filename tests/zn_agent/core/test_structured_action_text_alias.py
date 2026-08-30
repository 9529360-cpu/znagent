from __future__ import annotations

import unittest

from zn_agent.core.action import _explicit_action


class StructuredActionTextAliasTests(unittest.TestCase):
    def test_browser_text_action_does_not_duplicate_text_into_content(self) -> None:
        kind, args = _explicit_action(
            {
                "kind": "browser_type_named_text",
                "args": {
                    "url": "https://example.com/form",
                    "target_name": "Search",
                    "text": "private browser text",
                },
            },
            {},
        )

        self.assertEqual(kind, "browser_type_named_text")
        self.assertEqual(args["text"], "private browser text")
        self.assertNotIn("content", args)

    def test_form_text_action_does_not_duplicate_text_into_content(self) -> None:
        kind, args = _explicit_action(
            {
                "kind": "browser_fill_named_text_and_click_named_button_to_url",
                "args": {
                    "url": "https://example.com/form",
                    "textbox_name": "Search",
                    "text": "private form text",
                    "button_name": "Continue",
                    "expected_url": "https://example.com/done",
                },
            },
            {},
        )

        self.assertEqual(kind, "browser_fill_named_text_and_click_named_button_to_url")
        self.assertEqual(args["text"], "private form text")
        self.assertNotIn("content", args)

    def test_file_write_keeps_legacy_text_to_content_compatibility(self) -> None:
        for action_kind in ("write_text", "write_file"):
            with self.subTest(action_kind=action_kind):
                kind, args = _explicit_action(
                    {
                        "kind": action_kind,
                        "args": {"path": "note.txt", "text": "file contents"},
                    },
                    {},
                )
                self.assertEqual(kind, action_kind)
                self.assertEqual(args["text"], "file contents")
                self.assertEqual(args["content"], "file contents")

    def test_keyboard_text_consumes_text_without_content_alias(self) -> None:
        kind, args = _explicit_action(
            {"kind": "keyboard_text", "args": {"text": "typed text"}},
            {},
        )

        self.assertEqual(kind, "keyboard_text")
        self.assertEqual(args["text"], "typed text")
        self.assertNotIn("content", args)


if __name__ == "__main__":
    unittest.main(verbosity=2)
