from __future__ import annotations

import unittest

from zn_agent.core.user_browser_extension_resident import UserBrowserExtensionResidentRuntime


class UserBrowserUserPresenceBlockerTests(unittest.TestCase):
    def test_visible_enabled_one_time_code_is_deterministic_blocker(self) -> None:
        sense = {
            "candidates": [
                {
                    "role": "textbox",
                    "name": "安全代码",
                    "visible": True,
                    "enabled": True,
                    "editable": False,
                    "sensitive": True,
                    "sensitive_kind": "one_time_code",
                }
            ]
        }
        self.assertTrue(
            UserBrowserExtensionResidentRuntime._user_presence_blocker_from_sense(sense)
        )

    def test_password_is_not_upgraded_to_otp_handoff(self) -> None:
        sense = {
            "candidates": [
                {
                    "role": "textbox",
                    "name": "密码",
                    "visible": True,
                    "enabled": True,
                    "editable": False,
                    "sensitive": True,
                    "sensitive_kind": "password",
                }
            ]
        }
        self.assertFalse(
            UserBrowserExtensionResidentRuntime._user_presence_blocker_from_sense(sense)
        )

    def test_resume_discards_pre_mfa_grounded_target_identity(self) -> None:
        semantic = {
            "phase": "input_grounded",
            "regrounds": 2,
            "input_name": "客户邮箱",
            "input_target_id": "backend:stale",
            "button_name": "搜索订单",
            "button_target_id": "backend:also-stale",
        }

        resumed = UserBrowserExtensionResidentRuntime._resume_phase_after_user_presence(
            semantic,
            "ground_input",
        )

        self.assertEqual(resumed, {"phase": "ground_input", "regrounds": 2})
        self.assertNotIn("input_target_id", resumed)
        self.assertNotIn("button_target_id", resumed)

    def test_verify_resume_preserves_only_expected_url_not_stale_targets(self) -> None:
        semantic = {
            "phase": "verify_result",
            "regrounds": 1,
            "expected_url": "https://example.test/results?customer=alice",
            "input_target_id": "backend:stale",
            "button_target_id": "backend:stale-button",
        }

        resumed = UserBrowserExtensionResidentRuntime._resume_phase_after_user_presence(
            semantic,
            "verify_result",
        )

        self.assertEqual(
            resumed,
            {
                "phase": "verify_result",
                "regrounds": 1,
                "expected_url": "https://example.test/results?customer=alice",
            },
        )


if __name__ == "__main__":
    unittest.main()
