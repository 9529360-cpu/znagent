from __future__ import annotations

"""Resident composition for explicit current-tab browser-extension authorization."""

from typing import Any

from .user_browser_extension_relay import ResidentUserBrowserExtensionRelay
from .user_browser_resident import UserBrowserBridgeResidentRuntime


class UserBrowserExtensionResidentRuntime(UserBrowserBridgeResidentRuntime):
    """Own the loopback authorization surface used by the ZN browser extension."""

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        # ResidentService starts/stops this resource only while this runtime owns
        # the single-instance resident lease. Merely constructing a runtime must
        # never seize the fixed browser-extension port.
        self.user_browser_extension = ResidentUserBrowserExtensionRelay()

    def status(self) -> dict[str, Any]:
        data = super().status()
        data["user_browser_extension"] = self.user_browser_extension.status()
        return data

    def user_browser_extension_status(self) -> dict[str, Any]:
        return self.user_browser_extension.status()

    def revoke_user_browser_extension_tab(self, tab_id: int | None = None) -> dict[str, Any]:
        return self.user_browser_extension.revoke(tab_id=tab_id)
