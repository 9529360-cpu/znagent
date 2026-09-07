from __future__ import annotations

"""Bounded CLEAR/PRESS actions for exact BrowserScene text targets."""

from typing import Any

from .browser import BrowserAction, BrowserActionAuthority, BrowserActionKind, BrowserEffectEvidence
from .browser_scene_controls import PlaywrightBrowserSceneControlMixin
from .browser_scene_pointer import PlaywrightBrowserScenePointerMixin
from .browser_scene_select import PlaywrightBrowserSceneSelectMixin
from .browser_scene_table import PlaywrightBrowserSceneTableMixin
from .managed_browser import ManagedBrowserError


_SCENE_SELECTOR_PREFIX = "browser_scene:"
_CLEAR_ROLES = frozenset({"textbox", "searchbox", "textarea"})
_ENTER_ROLES = frozenset({"textbox", "searchbox"})


class PlaywrightBrowserSceneClearPressMixin(
    PlaywrightBrowserSceneControlMixin,
    PlaywrightBrowserScenePointerMixin,
    PlaywrightBrowserSceneTableMixin,
    PlaywrightBrowserSceneSelectMixin,
):
    """Add conservative text clearing and Enter navigation to scene targets."""

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        if not self._is_scene_clear_press(action):
            return super().act(action, authority)

        session = self._session(action.session_id)
        try:
            self._validate_authority(session, action, authority)
            binding = self._scene_action_binding(
                session,
                action.target.target_id,
                page_id=action.page_id or action.target.page_id,
                expected_target=action.target,
            )
            self._scene_revalidate_binding(session, binding)
            if action.kind is BrowserActionKind.CLEAR:
                return self._scene_clear(session, action, binding)
            return self._scene_press_enter(session, action, authority, binding)
        except Exception as exc:
            return self._failure(action, error=f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _is_scene_clear_press(action: BrowserAction) -> bool:
        return bool(
            action.kind in {BrowserActionKind.CLEAR, BrowserActionKind.PRESS}
            and action.target is not None
            and str(action.target.selector_hint or "").startswith(_SCENE_SELECTOR_PREFIX)
        )

    def _scene_clear(
        self,
        session: Any,
        action: BrowserAction,
        binding: Any,
    ) -> BrowserEffectEvidence:
        role = str(binding.scene_target.role or "")
        if role not in _CLEAR_ROLES:
            raise ManagedBrowserError("BrowserScene clear requires textbox/searchbox/textarea")
        before = self._scene_text_state(binding.handle)
        if int(before["text_length"]) == 0:
            raise ManagedBrowserError("BrowserScene clear target is already empty before dispatch")

        page = self._page(session, binding.page_id)
        before_url = str(getattr(page, "url", "") or "")
        try:
            binding.handle.fill("")
        except Exception as exc:
            self._scene_failed_mutation(session, binding.page_id)
            raise ManagedBrowserError(
                f"BrowserScene clear dispatch failed: {type(exc).__name__}: {exc}"
            ) from exc

        after = self._scene_text_state(binding.handle)
        observation = self._scene_post_target_observation(session, binding)
        success = int(after["text_length"]) == 0
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=observation.captured_at,
            success=success,
            page_id=binding.page_id,
            url_before=before_url,
            url_after=observation.url,
            target_id=action.target.target_id,
            postcondition="same_scene_target_text_empty",
            data={
                "provider": session.identity.provider,
                "role": role,
                "frame_id": binding.scene_target.frame_id,
                "text_length_before": before["text_length"],
                "text_sha256_before": before["text_sha256"],
                "text_length_after": after["text_length"],
                "text_sha256_after": after["text_sha256"],
            },
            error=None if success else "BrowserScene clear postcondition was not observed",
        )

    def _scene_press_enter(
        self,
        session: Any,
        action: BrowserAction,
        authority: BrowserActionAuthority,
        binding: Any,
    ) -> BrowserEffectEvidence:
        role = str(binding.scene_target.role or "")
        if role not in _ENTER_ROLES:
            raise ManagedBrowserError(
                "BrowserScene press Enter currently supports textbox/searchbox only"
            )
        key = str(action.args.get("key") or "").strip()
        if key != "Enter":
            raise ManagedBrowserError(
                "BrowserScene press first slice only accepts the exact Enter key"
            )
        if not authority.permission.allow_navigation:
            raise ManagedBrowserError(
                "BrowserScene Enter navigation requires navigation permission"
            )
        expected_url = str(action.expected.get("url_equals") or "").strip()
        if not expected_url:
            raise ManagedBrowserError(
                "BrowserScene Enter requires explicit expected url_equals evidence"
            )
        self._require_url_allowed(expected_url, session.permission)

        page = self._page(session, binding.page_id)
        before_url = str(getattr(page, "url", "") or "")
        if before_url == expected_url:
            raise ManagedBrowserError(
                "BrowserScene Enter expected URL is already observed before dispatch"
            )
        before_page_ids = set(session.pages)
        try:
            binding.handle.press("Enter")
        except Exception as exc:
            self._scene_failed_mutation(session, binding.page_id)
            raise ManagedBrowserError(
                f"BrowserScene Enter dispatch failed: {type(exc).__name__}: {exc}"
            ) from exc

        self._scene_invalidate_page(session.identity.session_id, binding.page_id)
        self._reconcile_pages(session)
        new_page_ids = tuple(page_id for page_id in session.pages if page_id not in before_page_ids)
        observation = self._capture(session, binding.page_id)
        self._require_url_allowed(observation.url, session.permission)
        data = {
            "provider": session.identity.provider,
            "role": role,
            "frame_id": binding.scene_target.frame_id,
            "key": "Enter",
            "expected_url": expected_url,
            "new_page_ids": list(new_page_ids),
            "target_revalidated_before_dispatch": True,
        }
        if new_page_ids:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=observation.captured_at,
                success=False,
                page_id=binding.page_id,
                url_before=before_url,
                url_after=observation.url,
                target_id=action.target.target_id,
                postcondition="same_page_url_equals_after_exact_scene_enter",
                data=data,
                error="BrowserScene Enter opened a new page; popup attribution is not supported for PRESS",
            )
        success = observation.url == expected_url
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=observation.captured_at,
            success=success,
            page_id=binding.page_id,
            url_before=before_url,
            url_after=observation.url,
            target_id=action.target.target_id,
            postcondition="same_page_url_equals_after_exact_scene_enter",
            data=data,
            error=None if success else "BrowserScene Enter URL postcondition did not match",
        )
