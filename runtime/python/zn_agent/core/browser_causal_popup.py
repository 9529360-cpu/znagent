from __future__ import annotations

"""Causal popup/new-tab evidence for exact BrowserScene clicks.

This layer does not discover a new page after the fact. It waits for the popup in
the same provider action window that dispatches the already-authorized exact scene
target click, then proves opener identity, stable ZN page identity, ownership and
an explicit URL postcondition before reporting success.
"""

from typing import Any

from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
)
from .managed_browser import ManagedBrowserError


_SCENE_SELECTOR_PREFIX = "browser_scene:"
_POPUP_CLICK_ROLES = frozenset({"link", "button"})


class PlaywrightBrowserCausalPopupMixin:
    """Attribute one popup to one exact scene-target click without tab guessing."""

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        if not self._is_causal_popup_action(action):
            return super().act(action, authority)

        session = self._session(action.session_id)
        try:
            self._validate_authority(session, action, authority)
            if action.target is None:
                raise ManagedBrowserError("causal popup click requires a current target")
            binding = self._scene_action_binding(
                session,
                action.target.target_id,
                page_id=action.page_id or action.target.page_id,
                expected_target=action.target,
            )
            self._scene_revalidate_binding(session, binding)
            return self._causal_popup_click(session, action, authority, binding)
        except Exception as exc:
            return self._failure(
                action,
                error=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _is_causal_popup_action(action: BrowserAction) -> bool:
        return bool(
            action.kind is BrowserActionKind.CLICK
            and action.target is not None
            and str(action.target.selector_hint or "").startswith(_SCENE_SELECTOR_PREFIX)
            and str(action.expected.get("popup_url_equals") or "").strip()
        )

    def _causal_popup_click(
        self,
        session: Any,
        action: BrowserAction,
        authority: BrowserActionAuthority,
        binding: Any,
    ) -> BrowserEffectEvidence:
        role = str(binding.scene_target.role or "")
        if role not in _POPUP_CLICK_ROLES:
            raise ManagedBrowserError(
                "causal popup click currently supports BrowserScene link/button targets"
            )
        if not authority.permission.allow_navigation:
            raise ManagedBrowserError("causal popup click requires navigation permission")
        expected_url = str(action.expected.get("popup_url_equals") or "").strip()
        if not expected_url:
            raise ManagedBrowserError(
                "causal popup click requires explicit expected popup_url_equals"
            )
        if str(action.expected.get("url_equals") or "").strip():
            raise ManagedBrowserError(
                "causal popup click cannot combine popup_url_equals with same-page url_equals"
            )
        self._require_url_allowed(expected_url, session.permission)

        opener_page_id = binding.page_id
        opener = self._page(session, opener_page_id)
        opener_url_before = str(getattr(opener, "url", "") or "")
        before_page_ids = set(session.pages)
        before_page_objects = tuple(session.pages.values())
        default_page_id_before = session.default_page_id

        expect_popup = getattr(opener, "expect_popup", None)
        if not callable(expect_popup):
            raise ManagedBrowserError(
                "browser provider cannot causally observe a popup from the opener page"
            )

        try:
            with expect_popup() as popup_info:
                binding.handle.click()
            popup = popup_info.value
        except Exception as exc:
            self._scene_failed_mutation(session, opener_page_id)
            raise ManagedBrowserError(
                f"causal popup click dispatch/observation failed: {type(exc).__name__}: {exc}"
            ) from exc

        self._scene_invalidate_page(session.identity.session_id, opener_page_id)
        if popup is None or popup is opener or any(
            popup is existing for existing in before_page_objects
        ):
            self._refresh_page_observation_after_failed_mutation(session, opener_page_id)
            raise ManagedBrowserError(
                "causal popup provider did not yield one fresh page identity"
            )

        popup_page_id = self._register_page(session, popup)
        if popup_page_id in before_page_ids:
            self._refresh_page_observation_after_failed_mutation(session, opener_page_id)
            raise ManagedBrowserError(
                "causal popup reused a browser page identity that existed before the click"
            )
        self._mark_zn_created_page(session, popup_page_id)
        self._reconcile_pages(session)
        self._restore_default_page(session, default_page_id_before)

        opener_matches = self._popup_opener_matches(popup, opener)
        if not opener_matches:
            closed_ids = self._close_new_causal_pages(session, before_page_ids)
            opener_observation = self._capture(session, opener_page_id)
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=opener_observation.captured_at,
                success=False,
                page_id=opener_page_id,
                url_before=opener_url_before,
                url_after=opener_observation.url,
                target_id=action.target.target_id,
                postcondition="causal_popup_opener_and_url_verified",
                data={
                    "provider": session.identity.provider,
                    "role": role,
                    "frame_id": binding.scene_target.frame_id,
                    "opener_page_id": opener_page_id,
                    "popup_page_id": popup_page_id,
                    "opener_matches": False,
                    "rolled_back_page_ids": closed_ids,
                },
                error="causal popup opener identity did not match the clicked page",
            )

        wait_error = ""
        wait_for_url = getattr(popup, "wait_for_url", None)
        if callable(wait_for_url):
            try:
                wait_for_url(expected_url, wait_until="domcontentloaded")
            except Exception as exc:
                wait_error = f"{type(exc).__name__}: {exc}"
        else:
            wait_for_load_state = getattr(popup, "wait_for_load_state", None)
            if callable(wait_for_load_state):
                try:
                    wait_for_load_state("domcontentloaded")
                except Exception as exc:
                    wait_error = f"{type(exc).__name__}: {exc}"

        popup_url = str(getattr(popup, "url", "") or "")
        if not self._url_allowed(popup_url, session.permission):
            closed_ids = self._close_new_causal_pages(session, before_page_ids)
            opener_observation = self._capture(session, opener_page_id)
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=opener_observation.captured_at,
                success=False,
                page_id=opener_page_id,
                url_before=opener_url_before,
                url_after=opener_observation.url,
                target_id=action.target.target_id,
                postcondition="causal_popup_opener_and_url_verified",
                data={
                    "provider": session.identity.provider,
                    "role": role,
                    "frame_id": binding.scene_target.frame_id,
                    "opener_page_id": opener_page_id,
                    "popup_page_id": popup_page_id,
                    "opener_matches": True,
                    "popup_url_in_authority_scope": False,
                    "rolled_back_page_ids": closed_ids,
                },
                error="causal popup left the permitted browser boundary and was closed",
            )

        self._reconcile_pages(session)
        self._restore_default_page(session, default_page_id_before)
        new_page_ids = tuple(
            page_id for page_id in session.pages if page_id not in before_page_ids
        )
        opener_observation = self._capture(session, opener_page_id)
        popup_observation = self._capture(session, popup_page_id)

        data = {
            "provider": session.identity.provider,
            "role": role,
            "frame_id": binding.scene_target.frame_id,
            "opener_page_id": opener_page_id,
            "popup_page_id": popup_page_id,
            "popup_url": popup_observation.url,
            "popup_title": popup_observation.title,
            "ownership": "zn_created",
            "opener_matches": True,
            "target_revalidated_before_dispatch": True,
            "expected_popup_url": expected_url,
            "new_page_ids": list(new_page_ids),
            "default_page_id_before": default_page_id_before,
            "default_page_id_after": session.default_page_id,
        }
        if wait_error:
            data["wait_error"] = wait_error

        exactly_one_new_page = new_page_ids == (popup_page_id,)
        default_preserved = session.default_page_id == default_page_id_before
        url_matches = popup_observation.url == expected_url
        success = bool(exactly_one_new_page and default_preserved and url_matches)
        if not success:
            if not exactly_one_new_page:
                error = "causal popup click produced an ambiguous new-page set"
            elif not default_preserved:
                error = "causal popup click changed ZN default-page identity"
            else:
                error = "causal popup URL postcondition did not match"
            data["rolled_back_page_ids"] = self._close_new_causal_pages(
                session,
                before_page_ids,
            )
            self._restore_default_page(session, default_page_id_before)
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=popup_observation.captured_at,
                success=False,
                page_id=opener_page_id,
                url_before=opener_url_before,
                url_after=opener_observation.url,
                target_id=action.target.target_id,
                postcondition="causal_popup_opener_and_url_verified",
                data=data,
                error=error,
            )

        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=popup_observation.captured_at,
            success=True,
            page_id=opener_page_id,
            url_before=opener_url_before,
            url_after=opener_observation.url,
            target_id=action.target.target_id,
            postcondition="causal_popup_opener_and_url_verified",
            data=data,
        )

    @staticmethod
    def _popup_opener_matches(popup: Any, opener: Any) -> bool:
        try:
            getter = getattr(popup, "opener", None)
            return bool(callable(getter) and getter() is opener)
        except Exception:
            return False

    @staticmethod
    def _restore_default_page(session: Any, default_page_id: str) -> None:
        if default_page_id in session.pages:
            session.default_page_id = default_page_id

    def _close_new_causal_pages(
        self,
        session: Any,
        before_page_ids: set[str],
    ) -> list[str]:
        self._reconcile_pages(session)
        new_page_ids = [
            page_id for page_id in session.pages if page_id not in before_page_ids
        ]
        for page_id in new_page_ids:
            page = session.pages.get(page_id)
            try:
                close = getattr(page, "close", None)
                if callable(close):
                    close()
            finally:
                self._forget_page_ownership(session, page_id)
                self._scene_invalidate_page(session.identity.session_id, page_id)
        self._reconcile_pages(session)
        return new_page_ids
