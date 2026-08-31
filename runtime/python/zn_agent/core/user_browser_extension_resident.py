from __future__ import annotations

"""Resident composition for explicit current-tab browser-extension authorization."""

from typing import Any
from urllib.parse import urlsplit

from .browser import BrowserPlane
from .user_browser_extension_adapter import AuthorizedExtensionUserBrowser
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
        self._extension_user_browser = AuthorizedExtensionUserBrowser(
            self.user_browser_extension
        )
        self._browser_before_extension = None

    def status(self) -> dict[str, Any]:
        data = super().status()
        data["user_browser_extension"] = self.user_browser_extension.status()
        return data

    def user_browser_extension_status(self) -> dict[str, Any]:
        return self.user_browser_extension.status()

    def user_browser_authorization(self) -> dict[str, Any]:
        authorized = self.user_browser_extension.authorized_tab()
        if authorized is not None:
            return {
                "authorized": True,
                "plane": BrowserPlane.USER.value,
                "provider": self._extension_user_browser.name,
                "profile_scope": "user_existing",
                "endpoint_scope": "loopback_extension_relay",
                "browser_ownership": "user",
                "authorization_scope": "explicit_current_tab",
                "tab_id": authorized.tab_id,
            }
        return super().user_browser_authorization()

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
        result = self.user_browser_extension.revoke(tab_id=tab_id)
        self._restore_browser_after_extension()
        return result

    def _browser_named_goal_investigation(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        if self.user_browser_extension.authorized_tab() is not None:
            self._adopt_authorized_extension_browser()
        elif self.managed_browser is self._extension_user_browser:
            self._restore_browser_after_extension()
        return super()._browser_named_goal_investigation(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    def _deliberation_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        # Explicit form-submit Work is already resident-owned and guarded. When the
        # user has authorized one current extension tab, run that same mature Body
        # movement against the USER adapter rather than silently falling back to a
        # managed browser. The USER Body path will freshly require the current URL
        # to equal the supplied start URL and will not navigate to it.
        if self._natural_form_submit_request(event) is not None:
            if self.user_browser_extension.authorized_tab() is not None:
                self._adopt_authorized_extension_browser()
            elif self.managed_browser is self._extension_user_browser:
                self._restore_browser_after_extension()
        return super()._deliberation_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    def _adopt_authorized_extension_browser(self) -> None:
        if self.managed_browser is self._extension_user_browser:
            return
        self._require_browser_adapter_idle(self.managed_browser)
        self._browser_before_extension = self.managed_browser
        self.managed_browser = self._extension_user_browser

    def _restore_browser_after_extension(self) -> None:
        if self.managed_browser is not self._extension_user_browser:
            self._browser_before_extension = None
            return
        self._require_browser_adapter_idle(self._extension_user_browser)
        self._extension_user_browser.close()
        previous = self._browser_before_extension
        self._browser_before_extension = None
        if previous is not None:
            self.managed_browser = previous
