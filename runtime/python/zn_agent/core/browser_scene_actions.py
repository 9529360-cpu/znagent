from __future__ import annotations

"""Authority-bound actions for BrowserScene targets.

BrowserScene remains a sensing substrate. This mixin only bridges a freshly
revalidated scene target into the existing BrowserAction/BrowserActionAuthority
contract and performs a deliberately small set of mutations with independent
postcondition evidence. It does not plan work or create a second browser agent.
"""

import hashlib
from dataclasses import replace
from typing import Any

from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
    BrowserObservation,
)
from .managed_browser import ManagedBrowserError
from .models import utc_now


_SCENE_SELECTOR_PREFIX = "browser_scene:"
_SCENE_ACTIONS = frozenset(
    {
        BrowserActionKind.FOCUS,
        BrowserActionKind.CLICK,
        BrowserActionKind.TYPE_TEXT,
        BrowserActionKind.CHECK,
        BrowserActionKind.UNCHECK,
    }
)
_SCENE_TEXT_ROLES = frozenset({"textbox", "searchbox", "textarea"})
_SCENE_NAV_CLICK_ROLES = frozenset({"link", "button"})
_SCENE_CHECK_ROLES = frozenset({"checkbox", "radio"})

_SCENE_FOCUS_STATE_SCRIPT = r"""
(element) => Boolean(
  element && element.isConnected && element.ownerDocument &&
  element.ownerDocument.activeElement === element
)
"""

_SCENE_CHECKED_STATE_SCRIPT = r"""
(element) => {
  if (!element || !element.isConnected) return { connected: false };
  const tag = String(element.tagName || "").toLowerCase();
  const type = String(element.getAttribute?.("type") || "").toLowerCase();
  const supported = tag === "input" && (type === "checkbox" || type === "radio");
  return {
    connected: true,
    supported,
    type,
    disabled: Boolean(element.disabled),
    checked: supported ? Boolean(element.checked) : null,
  };
}
"""

_SCENE_TEXT_STATE_SCRIPT = r"""
(element) => {
  if (!element || !element.isConnected) return { connected: false };
  const tag = String(element.tagName || "").toLowerCase();
  const type = String(element.getAttribute?.("type") || "").toLowerCase();
  const supported = tag === "textarea" ||
    (tag === "input" && (type === "" || type === "text" || type === "search"));
  return {
    connected: true,
    supported,
    sensitive: tag === "input" && type === "password",
    disabled: Boolean(element.disabled),
    read_only: Boolean(element.readOnly),
    value: supported && typeof element.value === "string" ? element.value : "",
  };
}
"""


class PlaywrightBrowserSceneActionMixin:
    """Execute a bounded action set against exact, current BrowserScene nodes."""

    def observe_scene_target(
        self,
        session_id: str,
        target_id: str,
        *,
        page_id: str = "",
    ) -> BrowserObservation:
        """Return an authority-ready observation for one current scene target."""

        session = self._session(session_id)
        binding = self._scene_action_binding(
            session,
            str(target_id or "").strip(),
            page_id=page_id,
        )
        self._scene_revalidate_binding(session, binding)
        page = self._page(session, binding.page_id)
        current_url = str(getattr(page, "url", "") or "")
        self._require_url_allowed(current_url, session.permission)
        captured_at = utc_now()
        target = replace(
            binding.target,
            observed_at=captured_at,
            url=current_url,
        )
        binding.target = target

        title = ""
        try:
            title = str(page.title() or "")[:1024]
        except Exception:
            title = ""
        try:
            load_state = str(page.evaluate("document.readyState") or "unknown")[:64]
        except Exception:
            load_state = "unknown"
        viewport_raw = getattr(page, "viewport_size", None)
        viewport = None
        if isinstance(viewport_raw, dict):
            width = int(viewport_raw.get("width") or 0)
            height = int(viewport_raw.get("height") or 0)
            if width > 0 and height > 0:
                viewport = (width, height)

        invalidate_managed = getattr(self, "_invalidate_target_binding", None)
        if callable(invalidate_managed):
            invalidate_managed(session, binding.page_id)
        observation = BrowserObservation(
            session=session.identity,
            page_id=binding.page_id,
            captured_at=captured_at,
            url=current_url,
            title=title,
            load_state=load_state,
            target=target,
            viewport=viewport,
            metadata={
                "provider": session.identity.provider,
                "grounding": "browser_scene",
                "scene_target_role": binding.scene_target.role,
                "scene_frame_id": binding.scene_target.frame_id,
            },
        )
        session.last_observation[binding.page_id] = observation
        return observation

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        if not self._is_scene_action_target(action):
            return super().act(action, authority)
        if action.kind not in _SCENE_ACTIONS:
            return self._failure(
                action,
                error=(
                    "ManagedBrowserError: BrowserScene target action is not implemented yet: "
                    f"{action.kind.value}"
                ),
            )

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
            if action.kind is BrowserActionKind.FOCUS:
                return self._scene_focus(session, action, binding)
            if action.kind is BrowserActionKind.CLICK:
                return self._scene_navigation_click(
                    session,
                    action,
                    authority,
                    binding,
                )
            if action.kind is BrowserActionKind.TYPE_TEXT:
                return self._scene_type_text(session, action, binding)
            if action.kind is BrowserActionKind.CHECK:
                return self._scene_check(session, action, binding, checked=True)
            if action.kind is BrowserActionKind.UNCHECK:
                return self._scene_check(session, action, binding, checked=False)
            raise ManagedBrowserError(
                f"unsupported BrowserScene action: {action.kind.value}"
            )
        except Exception as exc:
            return self._failure(
                action,
                error=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _is_scene_action_target(action: BrowserAction) -> bool:
        return bool(
            action.target is not None
            and str(action.target.selector_hint or "").startswith(
                _SCENE_SELECTOR_PREFIX
            )
        )

    def _scene_action_binding(
        self,
        session: Any,
        target_id: str,
        *,
        page_id: str = "",
        expected_target: Any = None,
    ) -> Any:
        resolved_page_id = str(page_id or "").strip() or self._default_page_id(session)
        state = self._scene_state(session)
        page_state = state.page_scenes.get(resolved_page_id)
        if page_state is None:
            raise ManagedBrowserError(
                "BrowserScene action requires a fresh scene for the target page"
            )
        binding = page_state.bindings.get(str(target_id or "").strip())
        if binding is None:
            raise ManagedBrowserError("BrowserScene action target is stale or unknown")
        if expected_target is not None and binding.target != expected_target:
            raise ManagedBrowserError(
                "BrowserScene action target evidence changed before dispatch"
            )
        return binding

    def _scene_focus(
        self,
        session: Any,
        action: BrowserAction,
        binding: Any,
    ) -> BrowserEffectEvidence:
        page = self._page(session, binding.page_id)
        before_url = str(getattr(page, "url", "") or "")
        try:
            binding.handle.focus()
            focused = bool(binding.handle.evaluate(_SCENE_FOCUS_STATE_SCRIPT))
        except Exception as exc:
            self._scene_failed_mutation(session, binding.page_id)
            raise ManagedBrowserError(
                f"BrowserScene focus dispatch failed: {type(exc).__name__}: {exc}"
            ) from exc
        if not focused:
            self._scene_failed_mutation(session, binding.page_id)
            raise ManagedBrowserError("BrowserScene focus postcondition was not observed")

        observation = self._scene_post_target_observation(session, binding)
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=observation.captured_at,
            success=True,
            page_id=binding.page_id,
            url_before=before_url,
            url_after=observation.url,
            target_id=action.target.target_id,
            postcondition="same_scene_target_focused",
            data={
                "provider": session.identity.provider,
                "frame_id": binding.scene_target.frame_id,
                "focused": True,
            },
        )

    def _scene_navigation_click(
        self,
        session: Any,
        action: BrowserAction,
        authority: BrowserActionAuthority,
        binding: Any,
    ) -> BrowserEffectEvidence:
        role = binding.scene_target.role
        if role not in _SCENE_NAV_CLICK_ROLES:
            raise ManagedBrowserError(
                "BrowserScene verified navigation click currently supports link/button targets"
            )
        if not authority.permission.allow_navigation:
            raise ManagedBrowserError(
                "BrowserScene navigation click requires navigation permission"
            )
        expected_url = str(action.expected.get("url_equals") or "").strip()
        if not expected_url:
            raise ManagedBrowserError(
                "BrowserScene click requires explicit expected url_equals evidence in this slice"
            )
        self._require_url_allowed(expected_url, session.permission)

        page = self._page(session, binding.page_id)
        before_url = str(getattr(page, "url", "") or "")
        if before_url == expected_url:
            raise ManagedBrowserError(
                "BrowserScene click expected URL is already observed before dispatch"
            )
        try:
            binding.handle.click()
        except Exception as exc:
            self._scene_failed_mutation(session, binding.page_id)
            raise ManagedBrowserError(
                f"BrowserScene navigation click dispatch failed: {type(exc).__name__}: {exc}"
            ) from exc

        self._scene_invalidate_page(session.identity.session_id, binding.page_id)
        observation = self._capture(session, binding.page_id)
        self._require_url_allowed(observation.url, session.permission)
        data = {
            "provider": session.identity.provider,
            "role": role,
            "frame_id": binding.scene_target.frame_id,
            "expected_url": expected_url,
            "target_revalidated_before_dispatch": True,
        }
        if observation.url != expected_url:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=observation.captured_at,
                success=False,
                page_id=binding.page_id,
                url_before=before_url,
                url_after=observation.url,
                target_id=action.target.target_id,
                postcondition="url_equals_after_exact_scene_target_click",
                data=data,
                error="BrowserScene navigation click postcondition did not match observed URL",
            )
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=observation.captured_at,
            success=True,
            page_id=binding.page_id,
            url_before=before_url,
            url_after=observation.url,
            target_id=action.target.target_id,
            postcondition="url_equals_after_exact_scene_target_click",
            data=data,
        )

    def _scene_type_text(
        self,
        session: Any,
        action: BrowserAction,
        binding: Any,
    ) -> BrowserEffectEvidence:
        if binding.scene_target.role not in _SCENE_TEXT_ROLES:
            raise ManagedBrowserError(
                "BrowserScene type_text requires textbox/searchbox/textarea"
            )
        text, expected = self._validate_managed_text(action.args.get("text"))
        page = self._page(session, binding.page_id)
        before_url = str(getattr(page, "url", "") or "")
        before = self._scene_text_state(binding.handle)
        if int(before["text_length"]) != 0:
            raise ManagedBrowserError(
                "BrowserScene type_text first slice refuses a non-empty target"
            )
        try:
            binding.handle.fill(text)
        except Exception as exc:
            self._scene_failed_mutation(session, binding.page_id)
            raise ManagedBrowserError(
                f"BrowserScene type_text dispatch failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            text = ""

        after = self._scene_text_state(binding.handle)
        observation = self._scene_post_target_observation(session, binding)
        data = {
            "provider": session.identity.provider,
            "role": binding.scene_target.role,
            "frame_id": binding.scene_target.frame_id,
            "text_length_before": before["text_length"],
            "text_sha256_before": before["text_sha256"],
            "text_length_after": after["text_length"],
            "text_sha256_after": after["text_sha256"],
            "expected_text_length": expected["text_length"],
            "expected_text_sha256": expected["text_sha256"],
        }
        success = (
            int(after["text_length"]) == int(expected["text_length"])
            and str(after["text_sha256"]) == str(expected["text_sha256"])
        )
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=observation.captured_at,
            success=success,
            page_id=binding.page_id,
            url_before=before_url,
            url_after=observation.url,
            target_id=action.target.target_id,
            postcondition="same_scene_target_text_equals_requested",
            data=data,
            error=None if success else "BrowserScene type_text postcondition was not observed",
        )

    def _scene_check(
        self,
        session: Any,
        action: BrowserAction,
        binding: Any,
        *,
        checked: bool,
    ) -> BrowserEffectEvidence:
        role = binding.scene_target.role
        if role not in _SCENE_CHECK_ROLES:
            raise ManagedBrowserError(
                "BrowserScene check/uncheck requires checkbox or radio"
            )
        if role == "radio" and not checked:
            raise ManagedBrowserError("BrowserScene refuses to uncheck a radio target")
        before_state = self._scene_checked_state(binding.handle)
        if bool(before_state) is checked:
            raise ManagedBrowserError(
                "BrowserScene checked postcondition is already observed before dispatch"
            )
        page = self._page(session, binding.page_id)
        before_url = str(getattr(page, "url", "") or "")
        try:
            if checked:
                binding.handle.check()
            else:
                binding.handle.uncheck()
        except Exception as exc:
            self._scene_failed_mutation(session, binding.page_id)
            raise ManagedBrowserError(
                f"BrowserScene checked-state dispatch failed: {type(exc).__name__}: {exc}"
            ) from exc

        after_state = self._scene_checked_state(binding.handle)
        observation = self._scene_post_target_observation(session, binding)
        success = bool(after_state) is checked
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=observation.captured_at,
            success=success,
            page_id=binding.page_id,
            url_before=before_url,
            url_after=observation.url,
            target_id=action.target.target_id,
            postcondition=(
                "same_scene_target_checked"
                if checked
                else "same_scene_target_unchecked"
            ),
            data={
                "provider": session.identity.provider,
                "role": role,
                "frame_id": binding.scene_target.frame_id,
                "checked_before": before_state,
                "checked_after": after_state,
            },
            error=None if success else "BrowserScene checked-state postcondition was not observed",
        )

    def _scene_post_target_observation(self, session: Any, binding: Any) -> BrowserObservation:
        try:
            return self.observe_scene_target(
                session.identity.session_id,
                binding.target.target_id,
                page_id=binding.page_id,
            )
        except Exception as exc:
            self._scene_failed_mutation(session, binding.page_id)
            raise ManagedBrowserError(
                f"BrowserScene target could not be re-observed after mutation: {type(exc).__name__}: {exc}"
            ) from exc

    def _scene_failed_mutation(self, session: Any, page_id: str) -> None:
        self._scene_invalidate_page(session.identity.session_id, page_id)
        self._refresh_page_observation_after_failed_mutation(session, page_id)

    @staticmethod
    def _scene_checked_state(handle: Any) -> bool:
        raw = handle.evaluate(_SCENE_CHECKED_STATE_SCRIPT)
        if not isinstance(raw, dict) or not bool(raw.get("connected")):
            raise ManagedBrowserError("BrowserScene checked target is detached")
        if not bool(raw.get("supported")):
            raise ManagedBrowserError(
                "BrowserScene checked-state mutation supports native checkbox/radio only"
            )
        if bool(raw.get("disabled")):
            raise ManagedBrowserError("BrowserScene checked target is disabled")
        checked = raw.get("checked")
        if type(checked) is not bool:
            raise ManagedBrowserError("BrowserScene checked state is unavailable")
        return checked

    @staticmethod
    def _scene_text_state(handle: Any) -> dict[str, Any]:
        raw = handle.evaluate(_SCENE_TEXT_STATE_SCRIPT)
        if not isinstance(raw, dict) or not bool(raw.get("connected")):
            raise ManagedBrowserError("BrowserScene text target is detached")
        if not bool(raw.get("supported")):
            raise ManagedBrowserError(
                "BrowserScene text mutation supports input[type=text/search] and textarea only"
            )
        if bool(raw.get("sensitive")):
            raise ManagedBrowserError(
                "BrowserScene type_text first slice refuses password targets"
            )
        if bool(raw.get("disabled")):
            raise ManagedBrowserError("BrowserScene text target is disabled")
        if bool(raw.get("read_only")):
            raise ManagedBrowserError("BrowserScene text target is read-only")
        value = raw.get("value")
        if not isinstance(value, str):
            raise ManagedBrowserError("BrowserScene text value is unavailable")
        result = {
            "text_length": len(value),
            "text_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        }
        value = ""
        return result
