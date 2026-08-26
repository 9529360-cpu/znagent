from __future__ import annotations

"""Local managed-browser adapter behind ZN-owned browser contracts.

Playwright is an implementation resource, not the browser control plane. The
adapter defaults to an ephemeral Chromium context, blocks service workers so
request routing remains authoritative, checks every HTTP(S) request and
WebSocket endpoint through ZN URL safety, and returns resident-owned effect
evidence after navigation instead of treating dispatch as completion.
"""

from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
    BrowserObservation,
    BrowserPermissionContext,
    BrowserPlane,
    BrowserSessionIdentity,
)
from .models import utc_now
from .url_safety import is_safe_url


class ManagedBrowserError(RuntimeError):
    pass


class ManagedBrowserUnavailable(ManagedBrowserError):
    pass


UrlChecker = Callable[..., bool]


@dataclass(slots=True)
class _ManagedSession:
    identity: BrowserSessionIdentity
    permission: BrowserPermissionContext
    playwright: Any
    browser: Any
    context: Any
    pages: dict[str, Any] = field(default_factory=dict)
    last_observation: dict[str, BrowserObservation] = field(default_factory=dict)


class PlaywrightManagedBrowser:
    """ZN-owned local managed browser using Playwright Chromium as one adapter."""

    name = "playwright-chromium"
    plane = BrowserPlane.MANAGED

    def __init__(
        self,
        *,
        playwright_factory: Callable[[], Any] | None = None,
        url_checker: UrlChecker = is_safe_url,
        navigation_timeout_ms: int = 30_000,
        action_timeout_ms: int = 15_000,
    ):
        self._playwright_factory = playwright_factory
        self._url_checker = url_checker
        self.navigation_timeout_ms = max(1_000, int(navigation_timeout_ms))
        self.action_timeout_ms = max(1_000, int(action_timeout_ms))
        self._sessions: dict[str, _ManagedSession] = {}

    def open_session(
        self,
        *,
        permission: BrowserPermissionContext | None = None,
        headless: bool = True,
    ) -> BrowserSessionIdentity:
        policy = permission or BrowserPermissionContext()
        if policy.allow_downloads or policy.allow_uploads:
            raise ManagedBrowserError(
                "managed-browser downloads/uploads require explicit file authority and are not enabled in this slice"
            )
        factory = self._playwright_factory or self._default_playwright_factory
        playwright = None
        browser = None
        context = None
        try:
            playwright = factory().start()
            browser = playwright.chromium.launch(headless=bool(headless))
            identity = BrowserSessionIdentity.create(
                plane=BrowserPlane.MANAGED,
                provider=self.name,
                browser_name="chromium",
                browser_version=str(getattr(browser, "version", "") or ""),
                profile_scope="ephemeral",
            )
            context = browser.new_context(
                accept_downloads=False,
                service_workers="block",
            )
            context.set_default_navigation_timeout(self.navigation_timeout_ms)
            context.set_default_timeout(self.action_timeout_ms)
            session = _ManagedSession(
                identity=identity,
                permission=policy,
                playwright=playwright,
                browser=browser,
                context=context,
            )
            self._install_network_boundary(session)
            page = context.new_page()
            page_id = self._register_page(session, page)
            self._sessions[identity.session_id] = session
            self._capture(session, page_id)
            return identity
        except ManagedBrowserError:
            self._best_effort_close(context, browser, playwright)
            raise
        except Exception as exc:
            self._best_effort_close(context, browser, playwright)
            if self._playwright_factory is None and self._looks_like_missing_playwright(exc):
                raise ManagedBrowserUnavailable(
                    "local managed browser is unavailable; install the ZN browser optional dependency and Chromium runtime"
                ) from exc
            raise ManagedBrowserError(f"failed to open local managed browser: {type(exc).__name__}: {exc}") from exc

    def close_session(self, session_id: str) -> None:
        session = self._sessions.pop(str(session_id or "").strip(), None)
        if session is None:
            return
        self._best_effort_close(session.context, session.browser, session.playwright)

    def close(self) -> None:
        for session_id in tuple(self._sessions):
            self.close_session(session_id)

    def observe(self, session_id: str, *, page_id: str = "") -> BrowserObservation:
        session = self._session(session_id)
        resolved_page_id = page_id or self._default_page_id(session)
        return self._capture(session, resolved_page_id)

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        session = self._session(action.session_id)
        try:
            self._validate_authority(session, action, authority)
            if action.kind is BrowserActionKind.NAVIGATE:
                return self._navigate(session, action, authority)
            return self._failure(
                action,
                error=f"managed browser action is not implemented yet: {action.kind.value}",
            )
        except Exception as exc:
            return self._failure(
                action,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _navigate(
        self,
        session: _ManagedSession,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        if not authority.permission.allow_navigation:
            raise ManagedBrowserError("browser navigation is not permitted")
        raw_url = str(action.args.get("url") or "").strip()
        if not raw_url:
            raise ManagedBrowserError("browser navigation requires url")
        self._require_url_allowed(raw_url, session.permission)

        page_id = action.page_id or authority.page_id or self._default_page_id(session)
        page = self._page(session, page_id)
        before = str(getattr(page, "url", "") or "")
        page.goto(raw_url, wait_until="domcontentloaded")
        observation = self._capture(session, page_id)
        self._require_url_allowed(observation.url, session.permission)

        expected_url = str(action.expected.get("url_equals") or "").strip()
        if expected_url and observation.url != expected_url:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=observation.captured_at,
                success=False,
                page_id=page_id,
                url_before=before,
                url_after=observation.url,
                postcondition="url_equals",
                error="browser navigation postcondition did not match observed URL",
            )

        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=observation.captured_at,
            success=True,
            page_id=page_id,
            url_before=before,
            url_after=observation.url,
            postcondition="safe_current_page_observed",
            data={
                "title": observation.title,
                "load_state": observation.load_state,
                "provider": session.identity.provider,
            },
        )

    def _capture(self, session: _ManagedSession, page_id: str) -> BrowserObservation:
        page = self._page(session, page_id)
        url = str(getattr(page, "url", "") or "")
        title = str(page.title() or "")
        try:
            load_state = str(page.evaluate("document.readyState") or "unknown")
        except Exception:
            load_state = "unknown"
        viewport_raw = getattr(page, "viewport_size", None)
        viewport = None
        if isinstance(viewport_raw, dict):
            width = int(viewport_raw.get("width") or 0)
            height = int(viewport_raw.get("height") or 0)
            if width > 0 and height > 0:
                viewport = (width, height)
        observation = BrowserObservation(
            session=session.identity,
            page_id=page_id,
            captured_at=utc_now(),
            url=url,
            title=title[:1024],
            load_state=load_state[:64],
            viewport=viewport,
            metadata={
                "provider": session.identity.provider,
                "page_count": len(session.pages),
                "service_workers": "blocked",
                "profile_scope": session.identity.profile_scope,
            },
        )
        session.last_observation[page_id] = observation
        return observation

    def _validate_authority(
        self,
        session: _ManagedSession,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> None:
        page_id = action.page_id or authority.page_id or self._default_page_id(session)
        observed = session.last_observation.get(page_id)
        if observed is None:
            raise ManagedBrowserError("browser action requires a current page observation")
        try:
            authority.validate_current(action, observed, session.permission)
        except ValueError as exc:
            raise ManagedBrowserError(str(exc)) from exc

    def _install_network_boundary(self, session: _ManagedSession) -> None:
        def handle_route(route: Any) -> None:
            url = str(route.request.url or "")
            if self._url_allowed(url, session.permission):
                route.continue_()
            else:
                route.abort(error_code="blockedbyclient")

        def handle_websocket(ws: Any) -> None:
            if self._websocket_url_allowed(str(ws.url or ""), session.permission):
                ws.connect_to_server()
            else:
                ws.close(code=1008, reason="blocked by ZN browser network policy")

        session.context.route("**/*", handle_route)
        route_web_socket = getattr(session.context, "route_web_socket", None)
        if callable(route_web_socket):
            route_web_socket("**/*", handle_websocket)

    def _require_url_allowed(
        self,
        url: str,
        permission: BrowserPermissionContext,
    ) -> None:
        if not self._url_allowed(url, permission):
            raise ManagedBrowserError("browser URL is outside the permitted network boundary")

    def _url_allowed(self, url: str, permission: BrowserPermissionContext) -> bool:
        text = str(url or "").strip()
        if text == "about:blank":
            return True
        if not permission.allows_origin(text):
            return False
        try:
            return bool(
                self._url_checker(
                    text,
                    allow_private=permission.allow_private_network,
                )
            )
        except Exception:
            return False

    def _websocket_url_allowed(
        self,
        url: str,
        permission: BrowserPermissionContext,
    ) -> bool:
        http_url = _websocket_to_http_url(url)
        return bool(http_url and self._url_allowed(http_url, permission))

    def _register_page(self, session: _ManagedSession, page: Any) -> str:
        for existing_id, existing_page in session.pages.items():
            if existing_page is page:
                return existing_id
        page_id = f"page-{len(session.pages) + 1}-{id(page):x}"
        session.pages[page_id] = page
        return page_id

    def _default_page_id(self, session: _ManagedSession) -> str:
        if not session.pages:
            raise ManagedBrowserError("managed browser session has no page")
        return next(iter(session.pages))

    def _page(self, session: _ManagedSession, page_id: str) -> Any:
        page = session.pages.get(str(page_id or ""))
        if page is None:
            raise ManagedBrowserError("unknown managed browser page")
        if bool(getattr(page, "is_closed", lambda: False)()):
            raise ManagedBrowserError("managed browser page is closed")
        return page

    def _session(self, session_id: str) -> _ManagedSession:
        session = self._sessions.get(str(session_id or "").strip())
        if session is None:
            raise ManagedBrowserError("unknown managed browser session")
        return session

    @staticmethod
    def _failure(action: BrowserAction, *, error: str) -> BrowserEffectEvidence:
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=False,
            page_id=action.page_id,
            target_id=action.target.target_id if action.target is not None else "",
            error=str(error or "managed browser action failed")[:2000],
        )

    @staticmethod
    def _default_playwright_factory() -> Any:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ManagedBrowserUnavailable(
                "Playwright is not installed; install znagent[browser]"
            ) from exc
        return sync_playwright()

    @staticmethod
    def _looks_like_missing_playwright(exc: Exception) -> bool:
        text = f"{type(exc).__name__}: {exc}".lower()
        return "executable doesn't exist" in text or "playwright" in text and "install" in text

    @staticmethod
    def _best_effort_close(context: Any, browser: Any, playwright: Any) -> None:
        for resource, method in (
            (context, "close"),
            (browser, "close"),
            (playwright, "stop"),
        ):
            if resource is None:
                continue
            try:
                getattr(resource, method)()
            except Exception:
                pass


def _websocket_to_http_url(value: str) -> str:
    try:
        parsed = urlsplit(str(value or "").strip())
    except (TypeError, ValueError):
        return ""
    scheme = str(parsed.scheme or "").lower()
    if scheme not in {"ws", "wss"}:
        return ""
    replacement = "http" if scheme == "ws" else "https"
    return urlunsplit((replacement, parsed.netloc, parsed.path, parsed.query, parsed.fragment))
