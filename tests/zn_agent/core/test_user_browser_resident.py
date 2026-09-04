from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.browser import BrowserPlane
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.semantic_managed_browser import SemanticPlaywrightManagedBrowser
from zn_agent.core.user_browser import AuthorizedCDPUserBrowser


class UserBrowserBridgeResidentTests(unittest.TestCase):
    def test_final_resident_can_authorize_and_revoke_existing_browser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertEqual(
                    resident.user_browser_authorization(),
                    {
                        "authorized": False,
                        "plane": BrowserPlane.MANAGED.value,
                        "browser_ownership": "resident",
                    },
                )

                authorized = resident.authorize_existing_user_browser(
                    "http://127.0.0.1:9222"
                )
                self.assertTrue(authorized["authorized"])
                self.assertEqual(authorized["plane"], BrowserPlane.USER.value)
                self.assertEqual(authorized["profile_scope"], "user_existing")
                self.assertIsInstance(resident.managed_browser, AuthorizedCDPUserBrowser)
                self.assertTrue(resident.user_browser_authorization()["authorized"])

                revoked = resident.revoke_existing_user_browser()
                self.assertTrue(revoked["revoked"])
                self.assertFalse(revoked["authorized"])
                self.assertIsInstance(
                    resident.managed_browser,
                    SemanticPlaywrightManagedBrowser,
                )
            finally:
                resident.store.close()

    def test_provider_switch_is_refused_while_browser_session_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                resident.managed_browser._sessions["busy"] = object()
                with self.assertRaisesRegex(RuntimeError, "session is active"):
                    resident.authorize_existing_user_browser(
                        "http://127.0.0.1:9222"
                    )
                self.assertIs(
                    resident.managed_browser.plane,
                    BrowserPlane.MANAGED,
                )
            finally:
                resident.managed_browser._sessions.clear()
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
