from __future__ import annotations

"""Verified tab lifecycle and history movements for Playwright browser Bodies."""

from typing import Any
from urllib.parse import urlsplit

from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
    BrowserPlane,
)
from .managed_browser import ManagedBrowserError
from .models import utc_now


_TAB_ACTIONS = frozenset(
    {
        BrowserActionKind.OPEN_TAB,
        BrowserActionKind.SWITCH_TAB,
        BrowserActionKind.CLOSE_TAB,
        BrowserActionKind.BACK,
        BrowserActionKind.FORWARD,
        BrowserActionKind.RELOAD,
    }
)
_HISTORY_ACTIONS = frozenset(
    {
        BrowserActionKind.BACK,
        BrowserActionKind.FORWARD,
        BrowserActionKind.RELOAD,
    }
)


class PlaywrightBrowserTabNavigationMixin:
    """Add bounded tab/history effects without creating another browser control plane."""

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        if action.kind not in _TAB_ACTIONS:
            return super().act(action, authority)

        session = self._session(action.session_id)
        try:
            self._validate_tab_action_shape(action)
            self._validate_authority(session, action, authority)
            if action.kind is BrowserActionKind.OPEN_TAB:
                return self._tab_open(session, action, authority)
            if action.kind is BrowserActionKind.SWITCH_TAB:
                return self._tab_switch(session, action)
            if action.kind is BrowserActionKind.CLOSE_TAB:
                return self._tab_close(session, action)
            return self._history_move(session, action)
        except Exception as exc:
            return self._failure(
                action,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _validate_tab_action_shape(self, action: BrowserAction) -> None:
        if action.target is not None:
            raise ManagedBrowserError(
                f"{action.kind.value} does not accept a browser element target"
            )

        if action.kind is BrowserActionKind.OPEN_TAB:
            self._require_exact_keys(action.args, {"url"}, label="OPEN_TAB args")
            self._require_exact_keys(
                action.expected,
                {"url_equals"},
                label="OPEN_TAB expected",
            )
            self._required_http_url(action.args, "url", label="OPEN_TAB args.url")
            self._required_http_url(
                action.expected,
                "url_equals",
                label="OPEN_TAB expected.url_equals",
            )
            if action.page_id:
                raise ManagedBrowserError("OPEN_TAB does not accept a target page_id")
            return

        if action.kind in {BrowserActionKind.SWITCH_TAB, BrowserActionKind.CLOSE_TAB}:
            self._require_exact_keys(action.args, set(), label=f"{action.kind.value} args")
            self._require_exact_keys(
                action.expected,
                set(),
                label=f"{action.kind.value} expected",
            )
            if not str(action.page_id or "").strip():
                raise ManagedBrowserError(
                    f"{action.kind.value} requires an explicit stable page_id"
                )
            return

        if action.kind in _HISTORY_ACTIONS:
            self._require_exact_keys(action.args, set(), label=f"{action.kind.value} args")
            self._require_exact_keys(
                action.expected,
                {"url_equals"},
                label=f"{action.kind.value} expected",
            )
            self._required_http_url(
                action.expected,
                "url_equals",
                label=f"{action.kind.value} expected.url_equals",
            )
            return

        raise ManagedBrowserError(f"unsupported tab/history action: {action.kind.value}")

    @staticmethod
    def _require_exact_keys(
        value: dict[str, Any],
        allowed: set[str],
        *,
        label: str,
    ) -> None:
        actual = set(value)
        if actual != allowed:
            unexpected = sorted(actual - allowed)
            missing = sorted(allowed - actual)
            details: list[str] = []
            if unexpected:
                details.append("unexpected=" + ",".join(unexpected))
            if missing:
                details.append("missing=" + ",".join(missing))
            suffix = "; ".join(details) or "invalid keys"
            raise ManagedBrowserError(f"{label} must use only its declared schema ({suffix})")

    @staticmethod
    def _required_url(value: dict[str, Any], key: str, *, label: str) -> str:
        raw = value.get(key)
        if not isinstance(raw, str) or not raw.strip():
            raise ManagedBrowserError(f"{label} must be a non-empty URL string")
        return raw.strip()

    @classmethod
    def _required_http_url(cls, value: dict[str, Any], key: str, *, label: str) -> str:
        url = cls._required_url(value, key, label=label)
        try:
            parsed = urlsplit(url)
        except ValueError as exc:
            raise ManagedBrowserError(f"{label} must be an HTTP(S) URL") from exc
        if str(parsed.scheme or "").lower() not in {"http", "https"} or not parsed.hostname:
            raise ManagedBrowserError(f"{label} must be an HTTP(S) URL")
        return url

    def _tab_open(
        self,
        session: Any,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        if session.identity.plane is BrowserPlane.USER:
            raise ManagedBrowserError(
                "OPEN_TAB is not permitted on the authorized existing user browser"
            )
        if not authority.permission.allow_page_interaction:
            raise ManagedBrowserError("opening a browser tab requires page-interaction permission")
        if not authority.permission.allow_navigation:
            raise ManagedBrowserError("opening a browser tab requires navigation permission")

        requested_url = self._required_http_url(action.args, "url", label="OPEN_TAB args.url")
        expected_url = self._required_http_url(
            action.expected,
            "url_equals",
            label="OPEN_TAB expected.url_equals",
        )
        self._require_url_allowed(requested_url, session.permission)
        self._require_url_allowed(expected_url, session.permission)

        self._reconcile_pages(session)
        previous_default = session.default_page_id
        previous_pages = dict(session.pages)
        created_page: Any | None = None
        created_page_id = ""
        causally_created = False
        try:
            created_page = session.context.new_page()
            if created_page is None:
                raise ManagedBrowserError("browser provider returned no page for OPEN_TAB")
            if any(created_page is page for page in previous_pages.values()):
                raise ManagedBrowserError(
                    "browser provider reused an existing Page for OPEN_TAB"
                )
            causally_created = True

            created_page_id = self._register_page(session, created_page)
            if created_page_id in previous_pages:
                raise ManagedBrowserError(
                    "browser provider reused an existing page identity for OPEN_TAB"
                )
            self._mark_zn_created_page(session, created_page_id)

            created_page.goto(requested_url, wait_until="domcontentloaded")
            self._invalidate_target_binding(session, created_page_id)
            observed_new = self._capture(session, created_page_id)
            self._require_url_allowed(observed_new.url, session.permission)
            if observed_new.url != expected_url:
                raise ManagedBrowserError(
                    "new browser tab URL postcondition did not match"
                )

            session.default_page_id = created_page_id
            fresh_default = self.observe(session.identity.session_id)
            if session.default_page_id != created_page_id:
                raise ManagedBrowserError(
                    "new browser tab did not remain the exact session default page"
                )
            if fresh_default.page_id != created_page_id:
                raise ManagedBrowserError(
                    "fresh default observation did not resolve the new browser tab"
                )
            self._require_url_allowed(fresh_default.url, session.permission)
            if fresh_default.url != expected_url:
                raise ManagedBrowserError(
                    "fresh default observation did not match OPEN_TAB expected URL"
                )
        except Exception as exc:
            rollback = self._rollback_open_tab(
                session,
                created_page if causally_created else None,
                created_page_id if causally_created else "",
                previous_default,
            )
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=rollback["observed_at"],
                success=False,
                page_id=created_page_id,
                url_after=rollback.get("default_url", ""),
                postcondition="open_tab_failed_and_exact_created_page_rolled_back",
                data={
                    "provider": session.identity.provider,
                    "created_page_id": created_page_id,
                    "rollback_complete": rollback["rollback_complete"],
                    "restored_default_page_id": rollback.get("default_page_id", ""),
                },
                error=f"{type(exc).__name__}: {exc}",
            )

        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=fresh_default.captured_at,
            success=True,
            page_id=created_page_id,
            url_after=fresh_default.url,
            postcondition="new_zn_owned_tab_is_exact_fresh_default_with_expected_url",
            data={
                "provider": session.identity.provider,
                "ownership": "zn_created",
                "default_page_id": session.default_page_id,
                "fresh_page_id": fresh_default.page_id,
                "title": fresh_default.title,
                "load_state": fresh_default.load_state,
                "os_foreground_verified": False,
            },
        )

    def _rollback_open_tab(
        self,
        session: Any,
        created_page: Any | None,
        created_page_id: str,
        previous_default: str,
    ) -> dict[str, Any]:
        rollback_complete = created_page is None
        if created_page is not None:
            try:
                if not self._page_is_closed(created_page):
                    created_page.close()
            except Exception:
                rollback_complete = False
            try:
                self._reconcile_pages(session)
            except Exception:
                rollback_complete = False
            if created_page_id:
                exact_still_live = (
                    created_page_id in session.pages
                    and session.pages.get(created_page_id) is created_page
                )
                rollback_complete = rollback_complete or not exact_still_live
                if not exact_still_live:
                    self._forget_page_ownership(session, created_page_id)

        try:
            self._reconcile_pages(session)
        except Exception:
            rollback_complete = False

        if previous_default and previous_default in session.pages:
            session.default_page_id = previous_default
        elif session.default_page_id not in session.pages:
            session.default_page_id = next(iter(session.pages), "")

        observed_at = utc_now()
        default_url = ""
        if session.default_page_id:
            try:
                restored = self.observe(session.identity.session_id)
                observed_at = restored.captured_at
                default_url = restored.url
            except Exception:
                rollback_complete = False

        return {
            "rollback_complete": bool(rollback_complete),
            "default_page_id": session.default_page_id,
            "default_url": default_url,
            "observed_at": observed_at,
        }

    def _tab_switch(
        self,
        session: Any,
        action: BrowserAction,
    ) -> BrowserEffectEvidence:
        page_id = str(action.page_id or "").strip()
        page = self._page(session, page_id)
        before_url = str(getattr(page, "url", "") or "")
        self._require_url_allowed(before_url, session.permission)

        bring_to_front = getattr(page, "bring_to_front", None)
        if not callable(bring_to_front):
            raise ManagedBrowserError("browser provider cannot activate a tab")

        previous_default = session.default_page_id
        bring_to_front()
        self._invalidate_target_binding(session, page_id)
        if previous_default and previous_default != page_id and previous_default in session.pages:
            self._invalidate_target_binding(session, previous_default)

        if session.identity.plane is BrowserPlane.USER:
            workspace = self.observe_browser_workspace(session.identity.session_id)
            if not workspace.foreground_known or workspace.foreground_page_id != page_id:
                raise ManagedBrowserError(
                    "user browser tab activation was not uniquely observed as visible"
                )

        session.default_page_id = page_id
        try:
            fresh_default = self.observe(session.identity.session_id)
            if session.default_page_id != page_id:
                raise ManagedBrowserError(
                    "SWITCH_TAB did not preserve the exact default page identity"
                )
            if fresh_default.page_id != page_id:
                raise ManagedBrowserError(
                    "fresh default observation did not resolve SWITCH_TAB target"
                )
            self._require_url_allowed(fresh_default.url, session.permission)
        except Exception:
            if previous_default in session.pages:
                session.default_page_id = previous_default
            raise

        postcondition = (
            "user_tab_is_unique_visible_exact_fresh_default"
            if session.identity.plane is BrowserPlane.USER
            else "managed_tab_is_exact_fresh_default"
        )
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=fresh_default.captured_at,
            success=True,
            page_id=page_id,
            url_before=before_url,
            url_after=fresh_default.url,
            postcondition=postcondition,
            data={
                "provider": session.identity.provider,
                "provider_activation_dispatched": True,
                "default_page_id": session.default_page_id,
                "fresh_page_id": fresh_default.page_id,
                "user_visible_verified": session.identity.plane is BrowserPlane.USER,
                "os_foreground_verified": False,
            },
        )

    def _tab_close(
        self,
        session: Any,
        action: BrowserAction,
    ) -> BrowserEffectEvidence:
        if session.identity.plane is BrowserPlane.USER:
            raise ManagedBrowserError(
                "CLOSE_TAB cannot close an existing user-browser page in this slice"
            )

        self._reconcile_pages(session)
        page_id = str(action.page_id or "").strip()
        page = self._page(session, page_id)
        ownership = self._page_ownership(session, page_id)
        if ownership != "zn_created":
            raise ManagedBrowserError("ZN refuses to close a browser tab it did not create")
        if len(session.pages) <= 1:
            raise ManagedBrowserError("ZN refuses to close the last live browser tab")

        before_url = str(getattr(page, "url", "") or "")
        self._require_url_allowed(before_url, session.permission)
        remaining_page_id = self._select_safe_remaining_page(session, exclude_page_id=page_id)
        if not remaining_page_id:
            raise ManagedBrowserError(
                "CLOSE_TAB requires another live authorized page to keep the session usable"
            )

        close_error: Exception | None = None
        try:
            page.close()
        except Exception as exc:
            close_error = exc
        self._reconcile_pages(session)
        if page_id in session.pages:
            if close_error is not None:
                raise ManagedBrowserError(
                    f"browser provider close failed and the exact tab remains live: {type(close_error).__name__}: {close_error}"
                ) from close_error
            raise ManagedBrowserError("browser tab close was not observed")
        self._forget_page_ownership(session, page_id)

        if remaining_page_id not in session.pages:
            remaining_page_id = self._select_safe_remaining_page(
                session,
                exclude_page_id=page_id,
            )
        if not remaining_page_id:
            raise ManagedBrowserError(
                "browser tab closed but no authorized live default page remained"
            )
        session.default_page_id = remaining_page_id
        fresh_default = self.observe(session.identity.session_id)
        if fresh_default.page_id != remaining_page_id:
            raise ManagedBrowserError(
                "fresh observation did not resolve the promoted remaining page"
            )
        if session.default_page_id != remaining_page_id:
            raise ManagedBrowserError(
                "closed default page left an inconsistent session default"
            )
        self._require_url_allowed(fresh_default.url, session.permission)

        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=fresh_default.captured_at,
            success=True,
            page_id=page_id,
            url_before=before_url,
            postcondition="zn_owned_tab_absent_and_session_has_fresh_live_default",
            data={
                "provider": session.identity.provider,
                "ownership": "zn_created",
                "closed_page_id": page_id,
                "default_page_id": session.default_page_id,
                "fresh_default_page_id": fresh_default.page_id,
                "remaining_page_ids": list(session.pages),
            },
        )

    def _select_safe_remaining_page(
        self,
        session: Any,
        *,
        exclude_page_id: str,
    ) -> str:
        self._reconcile_pages(session)
        candidates: list[str] = []
        if session.default_page_id and session.default_page_id != exclude_page_id:
            candidates.append(session.default_page_id)
        candidates.extend(
            page_id
            for page_id in session.pages
            if page_id != exclude_page_id and page_id not in candidates
        )
        for page_id in candidates:
            page = session.pages.get(page_id)
            if page is None or self._page_is_closed(page):
                continue
            url = str(getattr(page, "url", "") or "")
            try:
                self._require_url_allowed(url, session.permission)
            except Exception:
                continue
            return page_id
        return ""

    def _history_move(
        self,
        session: Any,
        action: BrowserAction,
    ) -> BrowserEffectEvidence:
        page_id = action.page_id or self._default_page_id(session)
        page = self._page(session, page_id)
        before_url = str(getattr(page, "url", "") or "")
        self._require_url_allowed(before_url, session.permission)
        expected_url = self._required_http_url(
            action.expected,
            "url_equals",
            label=f"{action.kind.value} expected.url_equals",
        )
        self._require_url_allowed(expected_url, session.permission)

        if action.kind in {BrowserActionKind.BACK, BrowserActionKind.FORWARD}:
            if expected_url == before_url:
                raise ManagedBrowserError(
                    f"{action.kind.value} expected URL already matches the current URL; refusing no-op completion"
                )

        try:
            if action.kind is BrowserActionKind.BACK:
                provider_result = page.go_back(wait_until="domcontentloaded")
            elif action.kind is BrowserActionKind.FORWARD:
                provider_result = page.go_forward(wait_until="domcontentloaded")
            elif action.kind is BrowserActionKind.RELOAD:
                page.reload(wait_until="domcontentloaded")
                provider_result = True
            else:
                raise ManagedBrowserError(f"unsupported history movement: {action.kind.value}")
        finally:
            self._invalidate_target_binding(session, page_id)
        fresh = self._capture(session, page_id)
        self._require_url_allowed(fresh.url, session.permission)

        if action.kind in {BrowserActionKind.BACK, BrowserActionKind.FORWARD} and provider_result is None:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=fresh.captured_at,
                success=False,
                page_id=page_id,
                url_before=before_url,
                url_after=fresh.url,
                postcondition="history_transition_requires_provider_transition_and_exact_fresh_url",
                data={
                    "provider": session.identity.provider,
                    "provider_transition_reported": False,
                    "expected_url": expected_url,
                },
                error="browser provider reported no history transition",
            )

        if fresh.url != expected_url:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=fresh.captured_at,
                success=False,
                page_id=page_id,
                url_before=before_url,
                url_after=fresh.url,
                postcondition=(
                    "reload_dispatch_requires_exact_fresh_url"
                    if action.kind is BrowserActionKind.RELOAD
                    else "history_transition_requires_provider_transition_and_exact_fresh_url"
                ),
                data={
                    "provider": session.identity.provider,
                    "provider_transition_reported": action.kind is not BrowserActionKind.RELOAD,
                    "reload_dispatched": action.kind is BrowserActionKind.RELOAD,
                    "expected_url": expected_url,
                },
                error="browser history/reload URL postcondition did not match fresh observation",
            )

        if action.kind is BrowserActionKind.RELOAD:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=fresh.captured_at,
                success=True,
                page_id=page_id,
                url_before=before_url,
                url_after=fresh.url,
                postcondition="reload_dispatched_and_exact_fresh_url_observed",
                data={
                    "provider": session.identity.provider,
                    "reload_dispatched": True,
                    "expected_url": expected_url,
                    "business_state_verified": False,
                    "title": fresh.title,
                    "load_state": fresh.load_state,
                },
            )

        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=fresh.captured_at,
            success=True,
            page_id=page_id,
            url_before=before_url,
            url_after=fresh.url,
            postcondition="history_transition_reported_and_exact_fresh_url_observed",
            data={
                "provider": session.identity.provider,
                "provider_transition_reported": True,
                "expected_url": expected_url,
                "title": fresh.title,
                "load_state": fresh.load_state,
            },
        )

    def _mark_zn_created_page(self, session: Any, page_id: str) -> None:
        scene_state = getattr(self, "_scene_state", None)
        if not callable(scene_state):
            raise ManagedBrowserError("BrowserScene ownership state is unavailable")
        scene_state(session).page_ownership[page_id] = "zn_created"

    def _forget_page_ownership(self, session: Any, page_id: str) -> None:
        scene_state = getattr(self, "_scene_state", None)
        if callable(scene_state):
            scene_state(session).page_ownership.pop(page_id, None)

    def _page_ownership(self, session: Any, page_id: str) -> str:
        scene_state = getattr(self, "_scene_state", None)
        if not callable(scene_state):
            raise ManagedBrowserError("BrowserScene ownership state is unavailable")
        state = scene_state(session)
        existing = state.page_ownership.get(page_id)
        if existing:
            return existing
        default = (
            "user_existing"
            if session.identity.plane is BrowserPlane.USER
            else "zn_created"
        )
        state.page_ownership[page_id] = default
        return default
