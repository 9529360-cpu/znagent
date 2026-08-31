from __future__ import annotations

"""Resident composition for explicit current-tab browser-extension authorization."""

from typing import Any
from urllib.parse import urlsplit

from .user_browser_extension_relay import (
    ResidentUserBrowserExtensionRelay,
    UserBrowserExtensionRelayError,
)
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

    def probe_user_browser_extension_tab(self) -> dict[str, Any]:
        """Ask the installed extension for fresh identity of the exact authorized tab."""

        authorized = self.user_browser_extension.authorized_tab()
        if authorized is None:
            raise UserBrowserExtensionRelayError("no user browser tab is currently authorized")
        command = self.user_browser_extension.request_command(
            "probe_current_tab",
            timeout_seconds=5.0,
        )
        if command.get("success") is not True:
            raise UserBrowserExtensionRelayError(
                str(command.get("error") or "authorized browser tab probe failed")
            )
        result = command.get("result")
        if not isinstance(result, dict):
            raise UserBrowserExtensionRelayError(
                "authorized browser tab probe did not return structured evidence"
            )
        try:
            tab_id = int(result.get("tab_id"))
        except (TypeError, ValueError) as exc:
            raise UserBrowserExtensionRelayError(
                "authorized browser tab probe returned invalid tab identity"
            ) from exc
        if tab_id != authorized.tab_id:
            raise UserBrowserExtensionRelayError(
                "authorized browser tab probe returned evidence for a different tab"
            )
        url = str(result.get("url") or "").strip()
        try:
            parsed = urlsplit(url)
        except ValueError as exc:
            raise UserBrowserExtensionRelayError(
                "authorized browser tab probe returned an invalid URL"
            ) from exc
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise UserBrowserExtensionRelayError(
                "authorized browser tab probe left the permitted HTTP(S) page boundary"
            )
        title = str(result.get("title") or "").strip()
        if len(title) > 512:
            raise UserBrowserExtensionRelayError(
                "authorized browser tab probe returned an oversized title"
            )
        return {
            "authorized": True,
            "tab_id": tab_id,
            "url": url,
            "title": title,
            "observed_at": str(command.get("completed_at") or ""),
            "source": "zn_browser_extension",
        }

    def revoke_user_browser_extension_tab(self, tab_id: int | None = None) -> dict[str, Any]:
        return self.user_browser_extension.revoke(tab_id=tab_id)
