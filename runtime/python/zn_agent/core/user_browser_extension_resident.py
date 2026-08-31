from __future__ import annotations

"""Resident composition for explicit current-tab browser-extension authorization."""

import re
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

from .action import NativeActionIntent
from .browser import BrowserPlane
from .user_browser_extension_adapter import AuthorizedExtensionUserBrowser
from .user_browser_extension_relay import (
    ResidentUserBrowserExtensionRelay,
    UserBrowserExtensionRelayError,
)
from .user_browser_resident import UserBrowserBridgeResidentRuntime


_EN_SEARCH_THIS_PAGE_RE = re.compile(
    r"^\s*(?:search|find)\s+(?:this|the\s+current)\s+(?:page|site)\s+for\s+(.+?)\s*[.!?]?\s*$",
    re.IGNORECASE,
)
_EN_SEARCH_FOR_ON_PAGE_RE = re.compile(
    r"^\s*(?:search|find)\s+for\s+(.+?)\s+(?:on|in)\s+(?:this|the\s+current)\s+(?:page|site)\s*[.!?]?\s*$",
    re.IGNORECASE,
)
_ZH_SEARCH_THIS_PAGE_RE = re.compile(
    r"^\s*(?:在)?(?:这个|当前)(?:页面|网页|网站)(?:里|中|上)?\s*(?:搜索|查找|搜一下|查一下)\s*[：:]?\s*(.+?)\s*[。！？!?]?\s*$"
)


class UserBrowserExtensionResidentRuntime(UserBrowserBridgeResidentRuntime):
    """Own the loopback authorization surface used by the ZN browser extension."""

    _NATURAL_SEARCH_STATE_KEY = "resident_user_browser_natural_search"

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

    @classmethod
    def _natural_current_page_search(cls, event) -> str | None:
        payload = event.payload or {}
        if payload.get("body_action") or payload.get("native_action"):
            return None
        task = str(event.task or "")
        matches = []
        for pattern in (
            _EN_SEARCH_THIS_PAGE_RE,
            _EN_SEARCH_FOR_ON_PAGE_RE,
            _ZH_SEARCH_THIS_PAGE_RE,
        ):
            match = pattern.fullmatch(task)
            if match is not None:
                matches.append(match.group(1))
        if len(matches) != 1:
            return None
        query = str(matches[0] or "").strip()
        if len(query) >= 2 and query[0] in {'"', "'", "“"} and query[-1] in {'"', "'", "”"}:
            query = query[1:-1].strip()
        if not query or len(query) > 512:
            return None
        if any(ord(char) < 32 or ord(char) == 127 for char in query):
            return None
        return query

    @classmethod
    def _required_capabilities(cls, event) -> tuple[str, ...]:
        payload = event.payload or {}
        if (
            payload.get("required_capabilities") is None
            and cls._natural_current_page_search(event) is not None
        ):
            return ("browser",)
        return super()._required_capabilities(event)

    def _investigation_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        query = self._natural_current_page_search(event)
        if query is None:
            return super()._investigation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        if self.user_browser_extension.authorized_tab() is None:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "this-page search requires one current browser tab explicitly authorized "
                    "through the ZN browser bridge"
                ),
            )
        self._adopt_authorized_extension_browser()
        try:
            evidence = self._discover_unique_search_form(query)
        except Exception as exc:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "ZN could not identify one unique safe search form on the current authorized "
                    f"page: {type(exc).__name__}: {exc}"
                ),
            )

        state.data[self._NATURAL_SEARCH_STATE_KEY] = evidence
        state.data.pop("local_failure", None)
        if thought is not None:
            known = (
                "fresh authorized-page evidence identified one unique empty native search field, "
                "its submit button, and a same-origin GET result route"
            )
            if known not in thought.known:
                thought.known = (*thought.known, known)
            thought.reason = (
                f"{thought.reason}; ZN grounded the user's ordinary search request in the current "
                "authorized page without asking for a URL, DOM id, coordinate, or control name"
            )
            self._persist_enriched_thought(thought)

        state.stage = "native_deliberation"
        state.next_action = "form the current-page search movement from fresh semantic evidence"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _discover_unique_search_form(self, query: str) -> dict[str, Any]:
        authorized = self.user_browser_extension.authorized_tab()
        if authorized is None:
            raise UserBrowserExtensionRelayError("no user browser tab is currently authorized")
        command = self.user_browser_extension.request_command(
            "probe_current_tab",
            args={"discover_unique_search_form": True},
            timeout_seconds=5.0,
        )
        if command.get("success") is not True:
            raise UserBrowserExtensionRelayError(
                str(command.get("error") or "authorized browser search-form discovery failed")
            )
        result = command.get("result")
        if not isinstance(result, dict):
            raise UserBrowserExtensionRelayError(
                "authorized browser search-form discovery returned no structured evidence"
            )
        try:
            tab_id = int(result.get("tab_id"))
        except (TypeError, ValueError) as exc:
            raise UserBrowserExtensionRelayError(
                "authorized browser search-form discovery returned invalid tab identity"
            ) from exc
        if tab_id != authorized.tab_id:
            raise UserBrowserExtensionRelayError(
                "authorized browser search-form discovery changed tab identity"
            )

        current_url = self._normal_http_url(result.get("url"), "current page")
        action_url = self._normal_http_url(result.get("form_action"), "search form action")
        if self._origin(current_url) != self._origin(action_url):
            raise UserBrowserExtensionRelayError(
                "autonomous search form action left the current page origin"
            )
        action = urlsplit(action_url)
        if action.query or action.fragment:
            raise UserBrowserExtensionRelayError(
                "autonomous search currently requires a GET form action without preset query or fragment"
            )
        if str(result.get("form_method") or "").strip().lower() != "get":
            raise UserBrowserExtensionRelayError(
                "autonomous current-page search requires a safe GET form"
            )

        parameter = self._bounded_label(result.get("query_parameter"), "query parameter", 128)
        textbox_name = self._bounded_label(result.get("textbox_name"), "search textbox name", 160)
        button_name = self._bounded_label(result.get("button_name"), "search button name", 160)
        textbox_target_id = self._bounded_label(
            result.get("textbox_target_id"), "search textbox identity", 256
        )
        button_target_id = self._bounded_label(
            result.get("button_target_id"), "search button identity", 256
        )
        expected_url = urlunsplit(
            (action.scheme, action.netloc, action.path, urlencode([(parameter, query)]), "")
        )
        if expected_url == current_url:
            raise UserBrowserExtensionRelayError(
                "autonomous search expected result is already the current page"
            )
        return {
            "url": current_url,
            "textbox_name": textbox_name,
            "textbox_target_id": textbox_target_id,
            "button_name": button_name,
            "button_target_id": button_target_id,
            "expected_url": expected_url,
            "query_parameter": parameter,
            "observed_at": str(command.get("completed_at") or ""),
            "source": "zn_browser_extension_search_discovery",
        }

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
        natural_query = self._natural_current_page_search(event)
        if natural_query is not None:
            if self.user_browser_extension.authorized_tab() is None:
                return self._fail_composite_goal_investigation(
                    event,
                    state,
                    reason="the explicitly authorized current browser tab is no longer available",
                )
            self._adopt_authorized_extension_browser()
            evidence = state.data.get(self._NATURAL_SEARCH_STATE_KEY)
            if not isinstance(evidence, dict):
                state.stage = "native_investigation"
                state.next_action = "re-observe the current page and identify its search form"
                self._sync_execution_context(event, state)
                self.store.save_working_state(state)
                return None
            intent = NativeActionIntent(
                intent_id=f"browser-natural-search-{event.event_id}",
                event_id=event.event_id,
                kind=self._BROWSER_FILL_AND_SUBMIT,
                args={
                    "url": str(evidence.get("url") or ""),
                    "textbox_name": str(evidence.get("textbox_name") or ""),
                    "text": natural_query,
                    "button_name": str(evidence.get("button_name") or ""),
                    "expected_url": str(evidence.get("expected_url") or ""),
                },
                reason=(
                    "fresh authorized-page discovery proved one unique empty safe GET search form; "
                    "the existing guarded form Body will re-observe each target and final page"
                ),
                source="resident_choice",
            )
            if not self._action_blocked_by_current_evidence(event, state, intent):
                self._begin_native_action_cycle(event, state, intent)
                self.store.save_working_state(state)
                if thought is not None:
                    action = "search the current authorized page through the existing browser Body"
                    if action not in thought.possible_actions:
                        thought.possible_actions = (*thought.possible_actions, action)
                    thought.reason = (
                        f"{thought.reason}; the next movement uses the existing guarded form path "
                        "so text entry, fresh button observation, click, final observation and "
                        "restart non-replay remain resident-owned"
                    )
                    self._persist_enriched_thought(thought)
                return None
            return None

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

    @staticmethod
    def _normal_http_url(value: Any, label: str) -> str:
        url = str(value or "").strip()
        try:
            parsed = urlsplit(url)
        except ValueError as exc:
            raise UserBrowserExtensionRelayError(f"{label} URL is invalid") from exc
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise UserBrowserExtensionRelayError(f"{label} is not an HTTP(S) URL")
        return url

    @staticmethod
    def _origin(value: str) -> tuple[str, str, int | None]:
        parsed = urlsplit(value)
        try:
            port = parsed.port
        except ValueError as exc:
            raise UserBrowserExtensionRelayError("browser URL has an invalid port") from exc
        return parsed.scheme.lower(), str(parsed.hostname or "").lower(), port

    @staticmethod
    def _bounded_label(value: Any, label: str, limit: int) -> str:
        text = str(value or "").strip()
        if not text or len(text) > limit:
            raise UserBrowserExtensionRelayError(f"{label} is invalid")
        if any(ord(char) < 32 or ord(char) == 127 for char in text):
            raise UserBrowserExtensionRelayError(f"{label} contains control characters")
        return text

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
