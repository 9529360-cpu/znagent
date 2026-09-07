from __future__ import annotations

"""Verified tab lifecycle and history movements for Playwright browser Bodies."""

from typing import Any

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


class PlaywrightBrowserTabNavigationMixin:
    """Add normal tab/history behavior without creating a Browser control plane.

    Every movement still uses the existing BrowserActionAuthority path. Existing
    USER tabs are treated as user-owned; only pages causally created by ZN through
    OPEN_TAB are marked as ZN-created and eligible for CLOSE_TAB.
    """

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        if action.kind not in _TAB_ACTIONS:
            return super().act(action, authority)

        session = self._session(action.session_id)
        try:
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

    def _tab_open(
        self,
        session: Any,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        if not authority.permission.allow_page_interaction:
            raise ManagedBrowserError("opening a browser tab is not permitted")

        raw_url = str(action.args.get("url") or "").strip()
        if raw_url:
            if not authority.permission.allow_navigation:
                raise ManagedBrowserError(
                    "opening a browser tab with a URL requires navigation permission"
                )
            self._require_url_allowed(raw_url, session.permission)

        self._reconcile_pages(session)
        before_page_ids = set(session.pages)
        page = session.context.new_page()
        page_id = self._register_page(session, page)
        if page_id in before_page_ids:
            raise ManagedBrowserError(
                "browser provider reused an existing page identity for OPEN_TAB"
            )
        self._mark_zn_created_page(session, page_id)

        try:
            if raw_url:
                page.goto(raw_url, wait_until="domcontentloaded")
            bring_to_front = getattr(page, "bring_to_front", None)
            if callable(bring_to_front):
                bring_to_front()
            session.default_page_id = page_id
            observation = self._capture(session, page_id)
            self._require_url_allowed(observation.url, session.permission)
        except Exception:
            try:
                page.close()
            finally:
                self._reconcile_pages(session)
                self._forget_page_ownership(session, page_id)
            raise

        expected_url = str(action.expected.get("url_equals") or "").strip()
        if expected_url:
            self._require_url_allowed(expected_url, session.permission)
            if observation.url != expected_url:
                return BrowserEffectEvidence(
                    action_id=action.action_id,
                    session_id=action.session_id,
                    observed_at=observation.captured_at,
                    success=False,
                    page_id=page_id,
                    url_after=observation.url,
                    postcondition="new_zn_owned_tab_url_equals",
                    data={
                        "provider": session.identity.provider,
                        "ownership": "zn_created",
                        "expected_url": expected_url,
                    },
                    error="new browser tab URL postcondition did not match",
                )

        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=observation.captured_at,
            success=True,
            page_id=page_id,
            url_after=observation.url,
            postcondition="new_zn_owned_tab_observed",
            data={
                "provider": session.identity.provider,
                "ownership": "zn_created",
                "title": observation.title,
                "load_state": observation.load_state,
            },
        )

    def _tab_switch(
        self,
        session: Any,
        action: BrowserAction,
    ) -> BrowserEffectEvidence:
        page_id = str(action.page_id or "").strip()
        if not page_id:
            raise ManagedBrowserError("SWITCH_TAB requires an explicit page_id")
        page = self._page(session, page_id)
        before_url = str(getattr(page, "url", "") or "")
        self._require_url_allowed(before_url, session.permission)

        bring_to_front = getattr(page, "bring_to_front", None)
        if not callable(bring_to_front):
            raise ManagedBrowserError("browser provider cannot activate a tab")
        bring_to_front()
        observation = self._capture(session, page_id)
        try:
            visible = bool(page.evaluate("document.visibilityState === 'visible'"))
        except Exception:
            visible = False
        if not visible:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=observation.captured_at,
                success=False,
                page_id=page_id,
                url_before=before_url,
                url_after=observation.url,
                postcondition="target_tab_visible_after_switch",
                data={"provider": session.identity.provider},
                error="browser tab activation was not observed",
            )

        session.default_page_id = page_id
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=observation.captured_at,
            success=True,
            page_id=page_id,
            url_before=before_url,
            url_after=observation.url,
            postcondition="target_tab_visible_after_switch",
            data={"provider": session.identity.provider},
        )

    def _tab_close(
        self,
        session: Any,
        action: BrowserAction,
    ) -> BrowserEffectEvidence:
        page_id = str(action.page_id or "").strip()
        if not page_id:
            raise ManagedBrowserError("CLOSE_TAB requires an explicit page_id")
        ownership = self._page_ownership(session, page_id)
        if ownership != "zn_created":
            raise ManagedBrowserError(
                "ZN refuses to close a browser tab it did not create"
            )

        page = self._page(session, page_id)
        before_url = str(getattr(page, "url", "") or "")
        page.close()
        self._reconcile_pages(session)
        if page_id in session.pages:
            raise ManagedBrowserError("browser tab close was not observed")
        self._forget_page_ownership(session, page_id)
        self._invalidate_scene_if_available(session.identity.session_id, page_id)

        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=True,
            page_id=page_id,
            url_before=before_url,
            postcondition="zn_owned_tab_absent_after_close",
            data={
                "provider": session.identity.provider,
                "ownership": "zn_created",
                "remaining_page_ids": list(session.pages),
            },
        )

    def _history_move(
        self,
        session: Any,
        action: BrowserAction,
    ) -> BrowserEffectEvidence:
        page_id = action.page_id or self._default_page_id(session)
        page = self._page(session, page_id)
        before_url = str(getattr(page, "url", "") or "")
        self._require_url_allowed(before_url, session.permission)

        expected_url = str(action.expected.get("url_equals") or "").strip()
        if action.kind in {BrowserActionKind.BACK, BrowserActionKind.FORWARD}:
            if not expected_url:
                raise ManagedBrowserError(
                    "BACK/FORWARD requires explicit expected url_equals evidence"
                )
            self._require_url_allowed(expected_url, session.permission)
        else:
            expected_url = expected_url or before_url
            self._require_url_allowed(expected_url, session.permission)

        if action.kind is BrowserActionKind.BACK:
            page.go_back(wait_until="domcontentloaded")
        elif action.kind is BrowserActionKind.FORWARD:
            page.go_forward(wait_until="domcontentloaded")
        elif action.kind is BrowserActionKind.RELOAD:
            page.reload(wait_until="domcontentloaded")
        else:
            raise ManagedBrowserError(
                f"unsupported history movement: {action.kind.value}"
            )

        self._invalidate_scene_if_available(session.identity.session_id, page_id)
        observation = self._capture(session, page_id)
        self._require_url_allowed(observation.url, session.permission)
        if observation.url != expected_url:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=observation.captured_at,
                success=False,
                page_id=page_id,
                url_before=before_url,
                url_after=observation.url,
                postcondition="url_equals_after_history_action",
                data={
                    "provider": session.identity.provider,
                    "expected_url": expected_url,
                },
                error="browser history postcondition did not match observed URL",
            )

        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=observation.captured_at,
            success=True,
            page_id=page_id,
            url_before=before_url,
            url_after=observation.url,
            postcondition="url_equals_after_history_action",
            data={
                "provider": session.identity.provider,
                "expected_url": expected_url,
                "title": observation.title,
                "load_state": observation.load_state,
            },
        )

    def _mark_zn_created_page(self, session: Any, page_id: str) -> None:
        scene_state = getattr(self, "_scene_state", None)
        if callable(scene_state):
            scene_state(session).page_ownership[page_id] = "zn_created"

    def _forget_page_ownership(self, session: Any, page_id: str) -> None:
        scene_state = getattr(self, "_scene_state", None)
        if callable(scene_state):
            scene_state(session).page_ownership.pop(page_id, None)

    def _page_ownership(self, session: Any, page_id: str) -> str:
        scene_state = getattr(self, "_scene_state", None)
        if callable(scene_state):
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
        return (
            "zn_created"
            if session.identity.plane is BrowserPlane.MANAGED
            else "user_existing"
        )

    def _invalidate_scene_if_available(self, session_id: str, page_id: str) -> None:
        invalidator = getattr(self, "_scene_invalidate_page", None)
        if callable(invalidator):
            invalidator(session_id, page_id)
