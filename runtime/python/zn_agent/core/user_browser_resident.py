from __future__ import annotations

"""Resident-owned authorization switch for the user's existing browser.

This layer does not add a new browser workflow. It only changes which existing
BrowserAdapter supplies fresh observations and actions after an explicit user
browser authorization. The inherited Work/authority/postcondition lifecycle is
unchanged.
"""

from typing import Any

from .browser import BrowserPlane
from .browser_goal_understanding_resident import BrowserGoalUnderstandingResidentRuntime
from .semantic_managed_browser import SemanticPlaywrightManagedBrowser
from .user_browser import AuthorizedCDPUserBrowser


class UserBrowserBridgeResidentRuntime(BrowserGoalUnderstandingResidentRuntime):
    """Allow the final Resident to adopt and revoke one authorized browser bridge."""

    def authorize_existing_user_browser(self, endpoint: str) -> dict[str, Any]:
        current = self.managed_browser
        self._require_browser_adapter_idle(current)
        replacement = AuthorizedCDPUserBrowser(endpoint=endpoint)
        if getattr(current, "plane", None) is BrowserPlane.USER:
            close = getattr(current, "close", None)
            if callable(close):
                close()
        self.managed_browser = replacement
        return {
            "authorized": True,
            "plane": BrowserPlane.USER.value,
            "provider": replacement.name,
            "profile_scope": "user_existing",
            "endpoint_scope": "loopback_local",
            "browser_ownership": "user",
        }

    def revoke_existing_user_browser(self) -> dict[str, Any]:
        current = self.managed_browser
        was_user = getattr(current, "plane", None) is BrowserPlane.USER
        if was_user:
            self._require_browser_adapter_idle(current)
            close = getattr(current, "close", None)
            if callable(close):
                close()
            self.managed_browser = SemanticPlaywrightManagedBrowser()
        return {
            "authorized": False,
            "revoked": bool(was_user),
            "plane": BrowserPlane.MANAGED.value,
            "browser_ownership": "resident",
        }

    def user_browser_authorization(self) -> dict[str, Any]:
        current = self.managed_browser
        if getattr(current, "plane", None) is BrowserPlane.USER:
            return {
                "authorized": True,
                "plane": BrowserPlane.USER.value,
                "provider": str(getattr(current, "name", "")),
                "profile_scope": "user_existing",
                "endpoint_scope": "loopback_local",
                "browser_ownership": "user",
            }
        return {
            "authorized": False,
            "plane": BrowserPlane.MANAGED.value,
            "browser_ownership": "resident",
        }

    @staticmethod
    def _require_browser_adapter_idle(adapter: Any) -> None:
        sessions = getattr(adapter, "_sessions", None)
        if isinstance(sessions, dict) and sessions:
            raise RuntimeError(
                "cannot switch browser ownership while a browser session is active"
            )
