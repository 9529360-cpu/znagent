from __future__ import annotations

"""Resident composition for explicit current-tab browser-extension authorization."""

from typing import Any

from .browser import BrowserPlane
from .semantic_managed_browser import SemanticPlaywrightManagedBrowser
from .user_browser_extension_adapter import AuthorizedExtensionUserBrowser
from .user_browser_extension_relay import ResidentUserBrowserExtensionRelay
from .user_browser_resident import UserBrowserBridgeResidentRuntime


class _ResidentBoundExtensionRelay(ResidentUserBrowserExtensionRelay):
    """Translate explicit relay authorization into the Resident's browser resource."""

    def __init__(self, owner: "UserBrowserExtensionResidentRuntime"):
        super().__init__()
        self.owner = owner

    def authorize(self, *, tab_id: Any, url: Any, title: Any) -> dict[str, Any]:
        result = super().authorize(tab_id=tab_id, url=url, title=title)
        try:
            self.owner._activate_extension_browser()
        except Exception:
            try:
                super().revoke(tab_id=tab_id)
            finally:
                self.owner._deactivate_extension_browser()
            raise
        return result

    def revoke(self, *, tab_id: Any = None) -> dict[str, Any]:
        result = super().revoke(tab_id=tab_id)
        self.owner._deactivate_extension_browser()
        return result

    def close(self) -> None:
        super().close()
        self.owner._deactivate_extension_browser()


class UserBrowserExtensionResidentRuntime(UserBrowserBridgeResidentRuntime):
    """Own the loopback authorization surface used by the ZN browser extension."""

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        # ResidentService starts/stops this resource only while this runtime owns
        # the single-instance resident lease. Merely constructing a runtime must
        # never seize the fixed browser-extension port.
        self.user_browser_extension = _ResidentBoundExtensionRelay(self)
        self.extension_user_browser = AuthorizedExtensionUserBrowser(
            self.user_browser_extension
        )

    def status(self) -> dict[str, Any]:
        data = super().status()
        data["user_browser_extension"] = self.user_browser_extension.status()
        return data

    def user_browser_extension_status(self) -> dict[str, Any]:
        return self.user_browser_extension.status()

    def revoke_user_browser_extension_tab(self, tab_id: int | None = None) -> dict[str, Any]:
        return self.user_browser_extension.revoke(tab_id=tab_id)

    def authorize_existing_user_browser(self, endpoint: str) -> dict[str, Any]:
        if self.user_browser_extension.authorized_tab() is not None:
            raise RuntimeError(
                "revoke the extension-authorized browser tab before switching browser transports"
            )
        return super().authorize_existing_user_browser(endpoint)

    def revoke_existing_user_browser(self) -> dict[str, Any]:
        tab = self.user_browser_extension.authorized_tab()
        if tab is not None:
            result = self.user_browser_extension.revoke(tab_id=tab.tab_id)
            return {
                "authorized": False,
                "revoked": True,
                "plane": BrowserPlane.MANAGED.value,
                "browser_ownership": "resident",
                "extension": result,
            }
        return super().revoke_existing_user_browser()

    def user_browser_authorization(self) -> dict[str, Any]:
        if self.managed_browser is self.extension_user_browser:
            tab = self.user_browser_extension.authorized_tab()
            return {
                "authorized": tab is not None,
                "plane": BrowserPlane.USER.value,
                "provider": self.extension_user_browser.name,
                "profile_scope": "user_existing",
                "endpoint_scope": "loopback_extension",
                "browser_ownership": "user",
                "tab_id": tab.tab_id if tab is not None else None,
            }
        return super().user_browser_authorization()

    def _activate_extension_browser(self) -> None:
        current = self.managed_browser
        if current is self.extension_user_browser:
            return
        self._require_browser_adapter_idle(current)
        if getattr(current, "plane", None) is BrowserPlane.USER:
            close = getattr(current, "close", None)
            if callable(close):
                close()
        self.managed_browser = self.extension_user_browser

    def _deactivate_extension_browser(self) -> None:
        if getattr(self, "extension_user_browser", None) is None:
            return
        if self.managed_browser is not self.extension_user_browser:
            return
        self.extension_user_browser.close()
        self.managed_browser = SemanticPlaywrightManagedBrowser()
