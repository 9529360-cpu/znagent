from __future__ import annotations

"""Authorized existing-browser adapter behind ZN-owned Browser contracts.

The mature browser-agent pattern here is deliberately narrow: ZN connects to an
already-authorized local Chromium CDP endpoint, adopts the user's existing page
and semantic Playwright grounding, but does not copy a profile, export cookies,
launch another browser, create a page, or close the user's browser.

CDP transport and Playwright are replaceable Body resources. Browser identity,
permission, fresh action authority and completion evidence remain resident-owned.
"""

import ipaddress
from dataclasses import replace
from typing import Any, Callable
from urllib.parse import urlsplit

from .browser import BrowserPermissionContext, BrowserPlane, BrowserSessionIdentity
from .managed_browser import ManagedBrowserError, _ManagedSession
from .semantic_managed_browser import SemanticPlaywrightManagedBrowser


class UserBrowserBridgeError(ManagedBrowserError):
    pass


class UserBrowserBridgeUnavailable(UserBrowserBridgeError):
    pass


class AuthorizedCDPUserBrowser(SemanticPlaywrightManagedBrowser):
    """Connect to one explicitly authorized existing local Chromium session."""

    name = "playwright-user-cdp"
    plane = BrowserPlane.USER

    def __init__(
        self,
        *,
        endpoint: str,
        playwright_factory: Callable[[], Any] | None = None,
        **kwargs: Any,
    ):
        super().__init__(playwright_factory=playwright_factory, **kwargs)
        self.endpoint = self._validate_endpoint(endpoint)

    def open_session(
        self,
        *,
        permission: BrowserPermissionContext | None = None,
        headless: bool = False,
    ) -> BrowserSessionIdentity:
        # ``headless`` is intentionally ignored: ZN is attaching to a browser the
        # user already owns rather than launching a provider process.
        del headless
        policy = permission or BrowserPermissionContext()
        if policy.allow_downloads or policy.allow_uploads:
            raise UserBrowserBridgeError(
                "user-browser downloads/uploads require separate explicit file authority"
            )

        factory = self._playwright_factory or self._default_playwright_factory
        playwright = None
        try:
            playwright = factory().start()
            browser = playwright.chromium.connect_over_cdp(self.endpoint)
            contexts = tuple(getattr(browser, "contexts", ()) or ())
            if len(contexts) != 1:
                raise UserBrowserBridgeError(
                    "authorized user-browser first slice requires exactly one observable browser context"
                )
            context = contexts[0]
            pages = tuple(getattr(context, "pages", ()) or ())
            if not pages:
                raise UserBrowserBridgeError(
                    "authorized user-browser session has no existing page"
                )

            active_page = self._select_current_page(pages)
            identity = BrowserSessionIdentity.create(
                plane=BrowserPlane.USER,
                provider=self.name,
                browser_name="chromium",
                browser_version=str(getattr(browser, "version", "") or ""),
                profile_scope="user_existing",
            )
            session = _ManagedSession(
                identity=identity,
                permission=policy,
                playwright=playwright,
                browser=browser,
                context=context,
            )
            for page in pages:
                self._register_page(session, page)
            for page_id, page in session.pages.items():
                if page is active_page:
                    session.default_page_id = page_id
                    break
            if not session.default_page_id:
                raise UserBrowserBridgeError(
                    "authorized user-browser current page could not be bound"
                )

            self._sessions[identity.session_id] = session
            try:
                self._capture(session, session.default_page_id)
            except Exception:
                self._sessions.pop(identity.session_id, None)
                raise
            return identity
        except UserBrowserBridgeError:
            self._disconnect_only(playwright)
            raise
        except Exception as exc:
            self._disconnect_only(playwright)
            if self._playwright_factory is None and self._looks_like_missing_playwright(exc):
                raise UserBrowserBridgeUnavailable(
                    "Playwright is unavailable; install znagent[browser] before attaching an authorized browser"
                ) from exc
            raise UserBrowserBridgeError(
                f"failed to attach authorized user browser: {type(exc).__name__}: {exc}"
            ) from exc

    def close_session(self, session_id: str) -> None:
        session = self._sessions.pop(str(session_id or "").strip(), None)
        if session is None:
            return
        self._dispose_all_target_bindings(session)
        # Never call Browser.close() or BrowserContext.close() for a USER plane:
        # those objects belong to the user. Stopping the Playwright client only
        # tears down ZN's transport connection.
        self._disconnect_only(session.playwright)

    def _capture(self, session: _ManagedSession, page_id: str, **kwargs: Any):
        observation = super()._capture(session, page_id, **kwargs)
        metadata = dict(observation.metadata)
        metadata["service_workers"] = "user_owned_unmodified"
        metadata["attachment"] = "authorized_existing_session"
        metadata["network_policy"] = "user_browser_unmodified; ZN action authority enforced"
        user_observation = replace(observation, metadata=metadata)
        session.last_observation[page_id] = user_observation
        return user_observation

    @classmethod
    def _validate_endpoint(cls, endpoint: str) -> str:
        raw = str(endpoint or "").strip()
        if not raw:
            raise ValueError("authorized user-browser endpoint must not be empty")
        try:
            parsed = urlsplit(raw)
        except ValueError as exc:
            raise ValueError("authorized user-browser endpoint is invalid") from exc
        if parsed.scheme.lower() not in {"http", "https", "ws", "wss"}:
            raise ValueError("authorized user-browser endpoint must use HTTP(S) or WS(S)")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("authorized user-browser endpoint must not contain credentials")
        host = str(parsed.hostname or "").strip().lower()
        if not host:
            raise ValueError("authorized user-browser endpoint requires a host")
        if not cls._is_loopback_host(host):
            raise ValueError(
                "authorized user-browser endpoint must be loopback-local in this slice"
            )
        if parsed.port is None:
            raise ValueError("authorized user-browser endpoint requires an explicit port")
        return raw

    @staticmethod
    def _is_loopback_host(host: str) -> bool:
        if host == "localhost":
            return True
        try:
            return bool(ipaddress.ip_address(host).is_loopback)
        except ValueError:
            return False

    @classmethod
    def _select_current_page(cls, pages: tuple[Any, ...]) -> Any:
        visible: list[Any] = []
        healthy: list[Any] = []
        for page in pages:
            if cls._page_is_closed(page):
                continue
            try:
                if bool(page.evaluate("document.visibilityState === 'visible'")):
                    visible.append(page)
            except Exception:
                pass
            try:
                if bool(page.evaluate("document.readyState !== undefined")):
                    healthy.append(page)
            except Exception:
                pass

        if len(visible) == 1:
            return visible[0]
        if len(visible) > 1:
            raise UserBrowserBridgeError(
                "authorized user-browser current tab is ambiguous: multiple visible pages"
            )
        if len(healthy) == 1:
            return healthy[0]
        raise UserBrowserBridgeError(
            "authorized user-browser current tab could not be uniquely observed"
        )

    @staticmethod
    def _disconnect_only(playwright: Any) -> None:
        if playwright is None:
            return
        try:
            playwright.stop()
        except Exception:
            pass
