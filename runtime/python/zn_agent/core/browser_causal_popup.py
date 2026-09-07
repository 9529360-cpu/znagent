from __future__ import annotations

"""Action-scoped causal popup attribution for exact BrowserScene clicks.

The causal Page is obtained from Playwright's ``page.expect_popup()`` around the
exact click. Provider page snapshots are used only to detect ambiguity; they are
never used to guess which new tab belongs to the action.
"""

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


_SCENE_PREFIX = "browser_scene:"
_NAV_ROLES = frozenset({"link", "button"})
_POPUP_POSTCONDITION = "causal_popup_opener_and_url_verified"


class PlaywrightBrowserCausalPopupMixin:
    """Verify one explicitly declared BrowserScene popup without tab-order heuristics."""

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        if not self._causal_popup_is_action(action):
            return super().act(action, authority)

        session = self._session(action.session_id)
        try:
            expected_url = self._causal_popup_validate_shape(action)
            if session.identity.plane is BrowserPlane.USER:
                raise ManagedBrowserError(
                    "causal popup CLICK is not permitted on the authorized existing user browser"
                )
            self._validate_authority(session, action, authority)
            if not authority.permission.allow_page_interaction:
                raise ManagedBrowserError(
                    "BrowserScene popup click requires page-interaction permission"
                )
            if not authority.permission.allow_navigation:
                raise ManagedBrowserError(
                    "BrowserScene popup click requires navigation permission"
                )
            self._require_url_allowed(expected_url, session.permission)

            assert action.target is not None
            binding = self._scene_action_binding(
                session,
                action.target.target_id,
                page_id=action.page_id or action.target.page_id,
                expected_target=action.target,
            )
            self._scene_revalidate_binding(session, binding)
            return self._causal_popup_click(
                session,
                action,
                binding,
                expected_url=expected_url,
            )
        except Exception as exc:
            return self._failure(action, error=f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _causal_popup_is_action(action: BrowserAction) -> bool:
        return bool(
            action.kind is BrowserActionKind.CLICK
            and action.target is not None
            and str(action.target.selector_hint or "").startswith(_SCENE_PREFIX)
            and "popup_url_equals" in action.expected
        )

    def _causal_popup_validate_shape(self, action: BrowserAction) -> str:
        if action.target is None:
            raise ManagedBrowserError("BrowserScene popup CLICK requires an exact target")
        self._scene_action_exact_keys(action.args, set(), "CLICK args")
        self._scene_action_exact_keys(
            action.expected,
            {"popup_url_equals"},
            "CLICK expected",
        )
        return self._scene_action_http_url(
            action.expected.get("popup_url_equals"),
            "CLICK expected.popup_url_equals",
        )

    def _causal_popup_click(
        self,
        session: Any,
        action: BrowserAction,
        binding: Any,
        *,
        expected_url: str,
    ) -> BrowserEffectEvidence:
        if binding.scene_target.role not in _NAV_ROLES:
            raise ManagedBrowserError(
                "BrowserScene popup click currently supports link/button targets"
            )

        opener_page_id = binding.page_id
        opener = self._page(session, opener_page_id)
        before_url = str(getattr(opener, "url", "") or "")
        self._require_url_allowed(before_url, session.permission)
        default_before = session.default_page_id
        provider_pages_before = self._scene_action_provider_pages(session)
        session_page_ids_before = tuple(session.pages)

        expect_popup = getattr(opener, "expect_popup", None)
        if not callable(expect_popup):
            raise ManagedBrowserError(
                "browser provider does not support action-scoped popup observation"
            )

        popup: Any | None = None
        popup_page_id = ""
        popup_proven_fresh = False
        dispatched = False

        # Revalidate at the last possible point before opening the provider event
        # window. The click is then executed *inside* expect_popup(), which is the
        # causal evidence. We never infer causality from context.pages ordering.
        self._scene_revalidate_binding(session, binding)
        try:
            with expect_popup(timeout=self.action_timeout_ms) as popup_info:
                dispatched = True
                binding.handle.click()
            popup = popup_info.value
        except Exception as exc:
            if dispatched:
                self._causal_popup_refresh_opener_after_attempt(session, opener_page_id)
            return self._causal_popup_failure(
                session,
                action,
                opener_page_id=opener_page_id,
                popup=None,
                popup_page_id="",
                popup_proven_fresh=False,
                before_url=before_url,
                expected_url=expected_url,
                default_before=default_before,
                provider_pages_before=provider_pages_before,
                session_page_ids_before=session_page_ids_before,
                error=f"{type(exc).__name__}: {exc}",
            )

        self._scene_invalidate_page(session.identity.session_id, opener_page_id)

        try:
            if popup is None:
                raise ManagedBrowserError("popup expectation returned no Page")
            if popup is opener or any(popup is old for old in provider_pages_before):
                raise ManagedBrowserError(
                    "popup expectation did not return a fresh Page identity"
                )
            popup_proven_fresh = True
            if self._page_is_closed(popup):
                raise ManagedBrowserError("causal popup closed before verification")

            provider_pages_now = self._scene_action_provider_pages(session)
            if not any(popup is page for page in provider_pages_now):
                raise ManagedBrowserError(
                    "causal popup is not present in the current provider page set"
                )

            popup_page_id = self._register_page(session, popup)
            if popup_page_id in session_page_ids_before:
                raise ManagedBrowserError(
                    "causal popup reused a pre-existing stable page identity"
                )

            opener_fn = getattr(popup, "opener", None)
            if not callable(opener_fn):
                raise ManagedBrowserError("browser provider cannot report popup opener")
            opener_matches = opener_fn() is opener
            if not opener_matches:
                raise ManagedBrowserError("causal popup opener did not match exact opener Page")

            wait_for_url = getattr(popup, "wait_for_url", None)
            if not callable(wait_for_url):
                raise ManagedBrowserError(
                    "browser provider cannot wait for explicit popup URL completion"
                )
            try:
                wait_for_url(
                    expected_url,
                    wait_until="domcontentloaded",
                    timeout=self.navigation_timeout_ms,
                )
            except Exception:
                pass

            popup_url = str(getattr(popup, "url", "") or "")
            self._require_url_allowed(popup_url, session.permission)
            if popup_url != expected_url:
                raise ManagedBrowserError(
                    "causal popup URL postcondition did not match popup_url_equals"
                )

            self._reconcile_pages(session)
            provider_pages_after = self._scene_action_provider_pages(session)
            fresh_pages = tuple(
                page
                for page in provider_pages_after
                if not any(page is old for old in provider_pages_before)
            )
            if not any(page is popup for page in fresh_pages):
                raise ManagedBrowserError(
                    "causal popup disappeared from the fresh provider page set"
                )
            new_page_ids = self._causal_popup_page_ids(session, fresh_pages)
            if len(fresh_pages) != 1:
                raise ManagedBrowserError(
                    "ambiguous popup action: additional fresh top-level page observed"
                )
            if set(new_page_ids) != {popup_page_id}:
                raise ManagedBrowserError(
                    "causal popup stable identity does not match fresh page evidence"
                )
            if session.default_page_id != default_before:
                raise ManagedBrowserError(
                    "causal popup action unexpectedly changed the session default page"
                )
            if opener_page_id not in session.pages or session.pages[opener_page_id] is not opener:
                raise ManagedBrowserError("exact opener Page identity is no longer live")

            observed_popup = self._capture(session, popup_page_id)
            self._require_url_allowed(observed_popup.url, session.permission)
            if observed_popup.url != expected_url:
                raise ManagedBrowserError(
                    "fresh causal popup observation did not match popup_url_equals"
                )
            if session.default_page_id != default_before:
                raise ManagedBrowserError(
                    "capturing causal popup unexpectedly changed the session default page"
                )

            self._mark_zn_created_page(session, popup_page_id)
            ownership = self._page_ownership(session, popup_page_id)
            if ownership != "zn_created":
                raise ManagedBrowserError("causal popup ownership was not recorded")

            observed_opener = self._capture(session, opener_page_id)
            self._require_url_allowed(observed_opener.url, session.permission)
            if observed_opener.url != before_url:
                raise ManagedBrowserError(
                    "causal popup click unexpectedly changed the opener top-level URL"
                )
            if session.default_page_id != default_before:
                raise ManagedBrowserError(
                    "causal popup verification did not preserve the original default page"
                )

            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=observed_popup.captured_at,
                success=True,
                page_id=opener_page_id,
                url_before=before_url,
                url_after=observed_opener.url,
                target_id=action.target.target_id if action.target else "",
                postcondition=_POPUP_POSTCONDITION,
                data={
                    "provider": session.identity.provider,
                    "opener_page_id": opener_page_id,
                    "popup_page_id": popup_page_id,
                    "expected_popup_url": expected_url,
                    "popup_url": observed_popup.url,
                    "ownership": ownership,
                    "opener_matches": True,
                    "new_page_ids": list(new_page_ids),
                    "default_page_id_before": default_before,
                    "default_page_id_after": session.default_page_id,
                    "target_revalidated_before_dispatch": True,
                },
            )
        except Exception as exc:
            return self._causal_popup_failure(
                session,
                action,
                opener_page_id=opener_page_id,
                popup=popup,
                popup_page_id=popup_page_id,
                popup_proven_fresh=popup_proven_fresh,
                before_url=before_url,
                expected_url=expected_url,
                default_before=default_before,
                provider_pages_before=provider_pages_before,
                session_page_ids_before=session_page_ids_before,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _causal_popup_failure(
        self,
        session: Any,
        action: BrowserAction,
        *,
        opener_page_id: str,
        popup: Any | None,
        popup_page_id: str,
        popup_proven_fresh: bool,
        before_url: str,
        expected_url: str,
        default_before: str,
        provider_pages_before: tuple[Any, ...],
        session_page_ids_before: tuple[str, ...],
        error: str,
    ) -> BrowserEffectEvidence:
        rollback_complete = True
        if popup is not None and popup_proven_fresh:
            rollback_complete = self._causal_popup_close_exact_page(
                session,
                popup,
                popup_page_id,
            )

        try:
            self._reconcile_pages(session)
        except Exception:
            rollback_complete = False

        if default_before and default_before in session.pages:
            session.default_page_id = default_before
        elif session.default_page_id not in session.pages:
            session.default_page_id = next(iter(session.pages), "")

        new_page_ids: tuple[str, ...] = ()
        try:
            provider_pages_after = self._scene_action_provider_pages(session)
            fresh_remaining = tuple(
                page
                for page in provider_pages_after
                if not any(page is old for old in provider_pages_before)
            )
            new_page_ids = self._causal_popup_page_ids(session, fresh_remaining)
        except Exception:
            rollback_complete = False

        observed_at = utc_now()
        opener_url = ""
        if opener_page_id in session.pages:
            try:
                self._scene_invalidate_page(session.identity.session_id, opener_page_id)
                observed = self._capture(session, opener_page_id)
                observed_at = observed.captured_at
                opener_url = observed.url
            except Exception:
                session.last_observation.pop(opener_page_id, None)
                rollback_complete = False

        opener_matches = False
        if popup is not None:
            opener_fn = getattr(popup, "opener", None)
            if callable(opener_fn):
                try:
                    opener_matches = opener_fn() is session.pages.get(opener_page_id)
                except Exception:
                    opener_matches = False

        popup_url = ""
        if popup is not None:
            try:
                candidate_popup_url = str(getattr(popup, "url", "") or "")
                if self._url_allowed(candidate_popup_url, session.permission):
                    popup_url = candidate_popup_url
            except Exception:
                popup_url = ""

        recorded_ownership = ""
        if popup_page_id:
            try:
                recorded_ownership = self._scene_state(session).page_ownership.get(
                    popup_page_id,
                    "",
                )
            except Exception:
                recorded_ownership = ""

        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=observed_at,
            success=False,
            page_id=opener_page_id,
            url_before=before_url,
            url_after=opener_url,
            target_id=action.target.target_id if action.target else "",
            postcondition=_POPUP_POSTCONDITION,
            data={
                "provider": session.identity.provider,
                "opener_page_id": opener_page_id,
                "popup_page_id": popup_page_id,
                "expected_popup_url": expected_url,
                "popup_url": popup_url,
                "ownership": recorded_ownership,
                "opener_matches": opener_matches,
                "new_page_ids": list(new_page_ids),
                "default_page_id_before": default_before,
                "default_page_id_after": session.default_page_id,
                "target_revalidated_before_dispatch": True,
                "rollback_complete": rollback_complete,
                "preexisting_page_ids": list(session_page_ids_before),
            },
            error=error,
        )

    def _causal_popup_close_exact_page(
        self,
        session: Any,
        popup: Any,
        popup_page_id: str,
    ) -> bool:
        """Rollback only the Page returned by the action-scoped popup expectation."""

        complete = True
        try:
            if not self._page_is_closed(popup):
                popup.close()
        except Exception:
            complete = False
        try:
            self._reconcile_pages(session)
        except Exception:
            complete = False
        if popup_page_id:
            exact_still_live = (
                popup_page_id in session.pages
                and session.pages.get(popup_page_id) is popup
            )
            if exact_still_live:
                complete = False
            else:
                self._forget_page_ownership(session, popup_page_id)
                self._scene_invalidate_page(session.identity.session_id, popup_page_id)
        return complete

    def _causal_popup_refresh_opener_after_attempt(
        self,
        session: Any,
        opener_page_id: str,
    ) -> None:
        self._scene_invalidate_page(session.identity.session_id, opener_page_id)
        try:
            self._capture(session, opener_page_id)
        except Exception:
            session.last_observation.pop(opener_page_id, None)

    def _causal_popup_page_ids(
        self,
        session: Any,
        pages: tuple[Any, ...],
    ) -> tuple[str, ...]:
        result: list[str] = []
        for page in pages:
            for page_id, registered in session.pages.items():
                if registered is page:
                    result.append(page_id)
                    break
        return tuple(result)
