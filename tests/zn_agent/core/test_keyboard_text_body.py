from __future__ import annotations

import unittest

from zn_agent.core.keyboard_text_body import KeyboardTextBody


class _KeyboardBody(KeyboardTextBody):
    def __init__(self, *, partial: bool = False):
        super().__init__()
        self.partial = bool(partial)
        self.sent: list[str] = []

    def _send_keyboard_text(self, text: str) -> tuple[int, int]:
        self.sent.append(text)
        _, units = self.validate_text(text)
        expected = len(units) * 2
        return (expected - 1, expected) if self.partial else (expected, expected)


class KeyboardTextBodyTests(unittest.TestCase):
    def test_plain_unicode_text_is_one_bounded_body_movement(self) -> None:
        body = _KeyboardBody()

        result = body.act("keyboard_text", text="ZN 文本")

        self.assertTrue(result.success, result.error)
        self.assertEqual(body.sent, ["ZN 文本"])
        self.assertEqual(result.data["text_chars"], 5)
        self.assertGreaterEqual(result.data["utf16_units"], 5)
        self.assertEqual(len(result.data["text_sha256"]), 64)
        self.assertEqual(
            result.data["input_events_sent"], result.data["input_events_expected"]
        )
        self.assertNotIn("text", result.data)
        self.assertNotIn("ZN 文本", result.output)

    def test_empty_control_and_oversized_text_fail_before_send(self) -> None:
        body = _KeyboardBody()
        cases = (
            "",
            "line\nfeed",
            "x" * (KeyboardTextBody.MAX_UTF16_UNITS + 1),
        )

        for text in cases:
            with self.subTest(text_length=len(text)):
                result = body.act("keyboard_text", text=text)
                self.assertFalse(result.success)

        self.assertEqual(body.sent, [])

    def test_partial_send_is_failure_and_never_claims_completion(self) -> None:
        body = _KeyboardBody(partial=True)

        result = body.act("keyboard_text", text="bounded")

        self.assertFalse(result.success)
        self.assertEqual(body.sent, ["bounded"])
        self.assertLess(
            result.data["input_events_sent"], result.data["input_events_expected"]
        )
        self.assertIn("must not replay blindly", result.error or "")

    def test_non_string_text_is_rejected_before_send(self) -> None:
        body = _KeyboardBody()

        result = body.act("keyboard_text", text=123)

        self.assertFalse(result.success)
        self.assertEqual(body.sent, [])
        self.assertIn("explicit string", result.error or "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
