from __future__ import annotations

"""Verified non-navigation clicks for stateful BrowserScene controls."""

import time
from typing import Any

from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
)
from .managed_browser import ManagedBrowserError


_SCENE_SELECTOR_PREFIX = "browser_scene:"
_CONTROL_ROLES = frozenset({"button", "menuitem", "tab"})
_CONTROL_STATE_KEYS = {
    "pressed_equals": ("pressed", frozenset({"button"})),
    "expanded_equals": ("expanded", frozenset({"button", "menuitem"})),
    "selected_equals": ("selected", frozenset({"tab"})),
}
_STATE_SETTLE_SECONDS = 0.75
_STATE_POLL_SECONDS = 0.05

_CONTROL_STATE_SCRIPT = r"""
(element) => {
  if (!element || !element.isConnected) return { connected: false };
  const ariaBool = (name) => {
    const raw = String(element.getAttribute?.(name) || "").trim().toLowerCase();
    if (raw === "true") return true;
    if (raw === "false") return false;
    return null;
  };
  return {
    connected: true,
    disabled: Boolean(element.disabled) || ariaBool("aria-disabled") === true,
    pressed: ariaBool("aria-pressed"),
    expanded: ariaBool("aria-expanded"),
    selected: ariaBool("aria-selected"),
  };
}
"""


class PlaywrightBrowserSceneControlMixin:
    """Click exact stateful controls only when ZN can prove a state transition."""

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        if not self._is_scene_control_click(action):
            return super().act(action, authority)

        session = self._session(action.session_id)
        try:
            self._validate_authority(session, action, authority)
            if action.target is None:
                raise ManagedBrowserError(
                    "BrowserScene stateful click requires a current target"
                )
            binding = self._scene_action_binding(
                session,
                action.target.target_id,
                page_id=action.page_id or action.target.page_id,
                expected_target=action.target,
            )
            self._scene_revalidate_binding(session, binding)
            return self._scene_control_click(session, action, binding)
        except Exception as exc:
            return self._failure(action, error=f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _is_scene_control_click(action: BrowserAction) -> bool:
        if action.kind is not BrowserActionKind.CLICK or action.target is None:
            return False
        if not str(action.target.selector_hint or "").startswith(_SCENE_SELECTOR_PREFIX):
            return False
        if str(action.expected.get("url_equals") or "").strip():
            return False
        if str(action.expected.get("popup_url_equals") or "").strip():
            return False
        return str(action.target.role or "") in _CONTROL_ROLES

    def _scene_control_click(
        self,
        session: Any,
        action: BrowserAction,
        binding: Any,
    ) -> BrowserEffectEvidence:
        role = str(binding.scene_target.role or "")
        if role not in _CONTROL_ROLES:
            raise ManagedBrowserError(
                "BrowserScene stateful click supports button/menuitem/tab targets only"
            )
        if action.args:
            raise ManagedBrowserError(
                "BrowserScene stateful click does not accept coordinates/modifiers"
            )

        expected_key, state_name, expected_value = self._control_expected_state(
            action,
            role,
        )
        before_state = self._control_state(binding.handle)
        if bool(before_state.get("disabled")):
            raise ManagedBrowserError("BrowserScene stateful click target is disabled")
        before_value = before_state.get(state_name)
        if type(before_value) is not bool:
            raise ManagedBrowserError(
                f"BrowserScene {role} target does not expose aria-{state_name}"
            )
        if before_value is expected_value:
            raise ManagedBrowserError(
                "BrowserScene stateful click postcondition is already observed before dispatch"
            )

        page = self._page(session, binding.page_id)
        before_url = str(getattr(page, "url", "") or "")
        self._require_url_allowed(before_url, session.permission)
        self._reconcile_pages(session)
        before_page_ids = set(session.pages)

        try:
            binding.handle.click()
        except Exception as exc:
            self._scene_failed_mutation(session, binding.page_id)
            raise ManagedBrowserError(
                f"BrowserScene stateful click dispatch failed: {type(exc).__name__}: {exc}"
            ) from exc

        self._reconcile_pages(session)
        new_page_ids = tuple(
            page_id for page_id in session.pages if page_id not in before_page_ids
        )
        after_url = str(getattr(page, "url", "") or "")
        if not self._url_allowed(after_url, session.permission):
            self._scene_invalidate_page(session.identity.session_id, binding.page_id)
            return self._control_failure_evidence(
                session,
                action,
                binding,
                role=role,
                state_name=state_name,
                expected_value=expected_value,
                before_value=before_value,
                before_url=before_url,
                after_url="",
                new_page_ids=new_page_ids,
                error="BrowserScene stateful click left browser authority",
            )
        if after_url != before_url:
            self._scene_invalidate_page(session.identity.session_id, binding.page_id)
            return self._control_failure_evidence(
                session,
                action,
                binding,
                role=role,
                state_name=state_name,
                expected_value=expected_value,
                before_value=before_value,
                before_url=before_url,
                after_url=after_url,
                new_page_ids=new_page_ids,
                error=(
                    "BrowserScene stateful click changed page URL without an explicit "
                    "navigation postcondition"
                ),
            )
        if new_page_ids:
            self._scene_invalidate_page(session.identity.session_id, binding.page_id)
            return self._control_failure_evidence(
                session,
                action,
                binding,
                role=role,
                state_name=state_name,
                expected_value=expected_value,
                before_value=before_value,
                before_url=before_url,
                after_url=after_url,
                new_page_ids=new_page_ids,
                error=(
                    "BrowserScene stateful click opened a fresh page; popup attribution "
                    "is not supported for this click"
                ),
            )

        after_state = self._wait_control_state(
            binding.handle,
            state_name,
            expected_value,
        )
        if not bool(after_state.get("connected")):
            self._scene_invalidate_page(session.identity.session_id, binding.page_id)
            raise ManagedBrowserError(
                "BrowserScene stateful click target detached before postcondition proof"
            )
        after_value = after_state.get(state_name)
        observation = self._scene_post_target_observation(session, binding)
        success = type(after_value) is bool and after_value is expected_value
        data = {
            "provider": session.identity.provider,
            "role": role,
            "frame_id": binding.scene_target.frame_id,
            "state": state_name,
            "state_before": before_value,
            "state_after": after_value if type(after_value) is bool else None,
            "expected_state": expected_value,
            "expected_key": expected_key,
            "new_page_ids": [],
            "target_revalidated_before_dispatch": True,
        }

        # Stateful controls commonly reveal overlays or change candidate order.
        # Prove the exact retained target first, then require a fresh scene.
        self._scene_invalidate_page(session.identity.session_id, binding.page_id)
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=observation.captured_at,
            success=success,
            page_id=binding.page_id,
            url_before=before_url,
            url_after=observation.url,
            target_id=action.target.target_id,
            postcondition=f"same_scene_target_aria_{state_name}_equals",
            data=data,
            error=(
                None
                if success
                else f"BrowserScene aria-{state_name} postcondition was not observed"
            ),
        )

    @staticmethod
    def _control_expected_state(
        action: BrowserAction,
        role: str,
    ) -> tuple[str, str, bool]:
        keys = set(action.expected)
        if len(keys) != 1:
            raise ManagedBrowserError(
                "BrowserScene stateful click requires exactly one explicit state postcondition"
            )
        key = next(iter(keys))
        spec = _CONTROL_STATE_KEYS.get(key)
        if spec is None:
            raise ManagedBrowserError(
                "BrowserScene stateful click supports pressed_equals, expanded_equals, or selected_equals"
            )
        state_name, roles = spec
        if role not in roles:
            raise ManagedBrowserError(
                f"BrowserScene {role} click does not support {key}"
            )
        value = action.expected.get(key)
        if type(value) is not bool:
            raise ManagedBrowserError(
                f"BrowserScene {key} postcondition must be a boolean"
            )
        return key, state_name, value

    @staticmethod
    def _control_state(handle: Any) -> dict[str, Any]:
        raw = handle.evaluate(_CONTROL_STATE_SCRIPT)
        if not isinstance(raw, dict):
            raise ManagedBrowserError(
                "browser provider returned invalid BrowserScene control state"
            )
        return raw

    def _wait_control_state(
        self,
        handle: Any,
        state_name: str,
        expected_value: bool,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + _STATE_SETTLE_SECONDS
        latest: dict[str, Any] = {}
        while True:
            latest = self._control_state(handle)
            if not bool(latest.get("connected")):
                return latest
            value = latest.get(state_name)
            if type(value) is bool and value is expected_value:
                return latest
            if time.monotonic() >= deadline:
                return latest
            time.sleep(_STATE_POLL_SECONDS)

    @staticmethod
    def _control_failure_evidence(
        session: Any,
        action: BrowserAction,
        binding: Any,
        *,
        role: str,
        state_name: str,
        expected_value: bool,
        before_value: bool,
        before_url: str,
        after_url: str,
        new_page_ids: tuple[str, ...],
        error: str,
    ) -> BrowserEffectEvidence:
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=binding.target.observed_at,
            success=False,
            page_id=binding.page_id,
            url_before=before_url,
            url_after=after_url,
            target_id=action.target.target_id,
            postcondition=f"same_scene_target_aria_{state_name}_equals",
            data={
                "provider": session.identity.provider,
                "role": role,
                "frame_id": binding.scene_target.frame_id,
                "state": state_name,
                "state_before": before_value,
                "expected_state": expected_value,
                "new_page_ids": list(new_page_ids),
                "target_revalidated_before_dispatch": True,
            },
            error=error,
        )
