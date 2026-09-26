from __future__ import annotations

import unittest

from zn_agent.core.error_safety import public_error_text, public_exception_text


class PublicErrorSafetyTests(unittest.TestCase):
    def test_common_secret_forms_are_redacted_and_useful_context_remains(self) -> None:
        raw = (
            "provider rejected request; "
            "Authorization: Bearer bearer-secret-value "
            "api_key=plain-secret-value "
            "password='password-secret-value' "
            "url=https://user:pass-secret@example.test/v1"
            "?access_token=query-secret-value "
            "key sk-abcdefghijklmnopqrstuvwxyz"
        )

        safe = public_error_text(raw)

        for secret in (
            "bearer-secret-value",
            "plain-secret-value",
            "password-secret-value",
            "pass-secret",
            "query-secret-value",
            "sk-abcdefghijklmnopqrstuvwxyz",
        ):
            self.assertNotIn(secret, safe)
        self.assertIn("provider rejected request", safe)
        self.assertIn("<redacted", safe)

    def test_exception_projection_keeps_class_but_is_bounded(self) -> None:
        safe = public_exception_text(
            RuntimeError("token=" + ("s" * 2000)),
            limit=120,
        )

        self.assertTrue(safe.startswith("RuntimeError: "))
        self.assertLessEqual(len(safe), 120)
        self.assertNotIn("s" * 100, safe)
        self.assertIn("<redacted>", safe)

    def test_non_secret_validation_message_remains_actionable(self) -> None:
        safe = public_exception_text(ValueError("threadId is required"))

        self.assertEqual(safe, "ValueError: threadId is required")


if __name__ == "__main__":
    unittest.main()
