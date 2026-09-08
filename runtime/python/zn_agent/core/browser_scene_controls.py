from __future__ import annotations

"""Verified stateful BrowserScene clicks for exact retained controls.

A provider click only proves that dispatch was attempted. ZN keeps action authority
bound to the exact retained BrowserScene handle, revalidates that handle at the
last possible moment, dispatches at most once, and requires a fresh ARIA boolean
transition from that same node. Once provider dispatch may have happened, the old
BrowserScene is invalidated so later work must ground itself in current reality.
"""

import time
from typing import Any

from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
)
from .managed_browser import ManagedBrowserError
from .models import utc_now


_SCENE_PREFIX = "browser_scene:"
_CONTROL_STATE_KEYS = {
    "pressed_equals": ("pressed", frozenset({"button"})),
    "expanded_equals": ("expanded", frozenset({"button", "menuitem"})),
    "selected_equals": ("selected", frozenset({"tab"})),
}
_STATE_SETTLE_SECONDS = 0.75
_STATE_POLL_SECONDS = 0.05

_CONTROL_STATE_SCRIPT = r"""
(element) => {
  const attr = (name) => {
    if (!element || !element.getAttribute) return null;
    const value = element.getAttribute(name);
    return value === null ? null : String(value);
  };
  return {
    connected: Boolean(element && element.isConnected),
    native_disabled: Boolean(element && "disabled" in element && element.disabled === true),
    aria_disabled: attr("aria-disabled"),
    aria_pressed: attr("aria-pressed"),
    aria_expanded: attr("aria-expanded"),
    aria_selected: attr("aria-selected"),
  };
}
"""


class PlaywrightBrowserSceneControlMixin:
    """Execute one exact stateful control click and prove its ARIA post-state."""

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        if not self._scene_control_is_action(action):
            return super().act(action, authority)

        session = self._session(action.session_id)
        expected_key = ""
        state_name = ""
        expected_state: bool | None = None
        try:
            expected_key, state_name, expected_state = self._scene_control_validate_shape(
                action
            )
            self._validate_authority(session, action, authority)
            if not authority.permission.allow_page_interaction:
                raise ManagedBrowserError(
                    "BrowserScene stateful control click requires page-interaction permission"
                )

            assert action.target is not None
            binding = self._scene_action_binding(
                session,
                action.target.target_id,
                page_id=action.page_id or action.target.page_id,
                expected_target=action.target,
            )
            self._scene_control_revalidate_exact(session, binding)
            return self._scene_control_click(
                session,
                action,
                binding,
                expected_key=expected_key,
                state_name=state_name,
                expected_state=expected_state,
            )
        except ManagedBrowserError as exc:
            return self._failure(action, error=f"ManagedBrowserError: {exc}")
        except Exception as exc:
            return self._failure(
                action,
                error=(
                    f"{type(exc).__name__}: "
                    "BrowserScene stateful control pre-dispatch verification failed"
                ),
            )

    @staticmethod
    def _scene_control_is_action(action: BrowserAction) -> bool:
        return bool(
            action.kind is BrowserActionKind.CLICK
            and action.target is not None
            and str(action.target.selector_hint or "").startswith(_SCENE_PREFIX)
            and any(key in action.expected for key in _CONTROL_STATE_KEYS)
        )

    def _scene_control_validate_shape(
        self,
        action: BrowserAction,
    ) -> tuple[str, str, bool]:
        if action.target is None:
            raise ManagedBrowserError(
                "BrowserScene stateful control click requires an exact current target"
            )
        self._scene_action_exact_keys(action.args, set(), "CLICK args")

        present = tuple(key for key in _CONTROL_STATE_KEYS if key in action.expected)
        if len(present) != 1:
            raise ManagedBrowserError(
                "BrowserScene stateful control CLICK expected must declare exactly one boolean state postcondition"
            )
        expected_key = present[0]
        self._scene_action_exact_keys(
            action.expected,
            {expected_key},
            "CLICK expected",
        )
        expected_state = action.expected.get(expected_key)
        if type(expected_state) is not bool:
            raise ManagedBrowserError(f"{expected_key} must be a boolean")
        state_name, _roles = _CONTROL_STATE_KEYS[expected_key]
        return expected_key, state_name, expected_state

    def _scene_control_click(
        self,
        session: Any,
        action: BrowserAction,
        binding: Any,
        *,
        expected_key: str,
        state_name: str,
        expected_state: bool,
    ) -> BrowserEffectEvidence:
        role = str(binding.scene_target.role or "")
        allowed_roles = _CONTROL_STATE_KEYS[expected_key][1]
        if role not in allowed_roles:
            raise ManagedBrowserError(
                "BrowserScene stateful control role does not match the requested state postcondition"
            )
        if bool(getattr(binding.scene_target, "sensitive", False)) and not (
            session.permission.allow_sensitive_fields
        ):
            raise ManagedBrowserError(
                "BrowserScene stateful control target is sensitive and not authorized"
            )
        if str(getattr(binding.scene_target, "href", "") or ""):
            raise ManagedBrowserError(
                "BrowserScene stateful control refuses link-backed targets"
            )
        if not bool(getattr(binding.scene_target, "enabled", True)):
            raise ManagedBrowserError(
                "BrowserScene stateful control target is disabled"
            )

        state_before = self._scene_control_state(binding.handle, state_name)
        if state_before is expected_state:
            raise ManagedBrowserError(
                "BrowserScene stateful control postcondition is already observed before dispatch"
            )

        page = self._page(session, binding.page_id)
        before_url = str(getattr(page, "url", "") or "")
        self._require_url_allowed(before_url, session.permission)
        provider_pages_before = self._scene_action_provider_pages(session)
        default_before = str(session.default_page_id or "")

        # No mutable-target operation may occur between this exact-node proof and
        # the provider click. In particular, do not re-resolve by role/name here.
        self._scene_control_revalidate_exact(session, binding)

        dispatched = False
        state_after: bool | None = None
        fresh_pages: tuple[Any, ...] = ()
        new_page_ids: tuple[str, ...] = ()
        topology_unchanged = False
        try:
            # Entering provider click means the external effect may already have
            # happened even if the provider subsequently raises.
            dispatched = True
            try:
                binding.handle.click()
            except Exception as exc:
                raise ManagedBrowserError(
                    "BrowserScene stateful control provider click failed: "
                    f"{type(exc).__name__}"
                ) from exc

            state_after = self._scene_control_wait_for_state(
                session,
                binding,
                page=page,
                before_url=before_url,
                provider_pages_before=provider_pages_before,
                default_before=default_before,
                state_name=state_name,
                expected_state=expected_state,
            )
            fresh_pages, new_page_ids, topology_unchanged = (
                self._scene_control_topology_status(
                    session,
                    provider_pages_before,
                    default_before=default_before,
                )
            )
            self._scene_control_require_same_page(session, page, binding.page_id, before_url)
            if not topology_unchanged:
                raise ManagedBrowserError(
                    "BrowserScene stateful control changed top-level page topology"
                )
            if state_after is not expected_state:
                raise ManagedBrowserError(
                    "BrowserScene stateful control ARIA postcondition was not observed"
                )
        except Exception as exc:
            if dispatched:
                # Capture only bounded boolean/topology evidence from the exact
                # handle if still possible. Never re-locate another same-name node.
                try:
                    if state_after is None:
                        state_after = self._scene_control_state(
                            binding.handle,
                            state_name,
                        )
                except Exception:
                    state_after = None
                try:
                    fresh_pages, new_page_ids, topology_unchanged = (
                        self._scene_control_topology_status(
                            session,
                            provider_pages_before,
                            default_before=default_before,
                        )
                    )
                except Exception:
                    fresh_pages = ()
                    new_page_ids = ()
                    topology_unchanged = False

                self._scene_action_dispatched_failure(session, binding.page_id)
                return self._scene_control_evidence(
                    session,
                    action,
                    binding,
                    before_url=before_url,
                    page=page,
                    expected_key=expected_key,
                    state_name=state_name,
                    expected_state=expected_state,
                    state_before=state_before,
                    state_after=state_after,
                    dispatch_count=1,
                    new_page_ids=new_page_ids,
                    new_page_count=len(fresh_pages),
                    topology_unchanged=topology_unchanged,
                    success=False,
                    error=self._scene_control_safe_error(exc, stage="post-dispatch"),
                )
            raise

        # State transition has been proven on the retained node. Dispose all old
        # BrowserScene bindings now so any next action must obtain a fresh scene.
        self._scene_invalidate_page(
            session.identity.session_id,
            binding.page_id,
        )
        return self._scene_control_evidence(
            session,
            action,
            binding,
            before_url=before_url,
            page=page,
            expected_key=expected_key,
            state_name=state_name,
            expected_state=expected_state,
            state_before=state_before,
            state_after=state_after,
            dispatch_count=1,
            new_page_ids=(),
            new_page_count=0,
            topology_unchanged=True,
            success=True,
            error=None,
        )

    def _scene_control_revalidate_exact(self, session: Any, binding: Any) -> None:
        try:
            self._scene_revalidate_binding(session, binding)
        except Exception as exc:
            # Revalidation may cross provider seams whose messages can contain
            # accessible labels. Preserve only the resident-owned stale meaning.
            raise ManagedBrowserError(
                "BrowserScene stateful control exact target is stale or changed before dispatch"
            ) from exc

    def _scene_control_wait_for_state(
        self,
        session: Any,
        binding: Any,
        *,
        page: Any,
        before_url: str,
        provider_pages_before: tuple[Any, ...],
        default_before: str,
        state_name: str,
        expected_state: bool,
    ) -> bool:
        deadline = time.monotonic() + _STATE_SETTLE_SECONDS
        last_state: bool | None = None
        while True:
            self._scene_control_require_same_page(
                session,
                page,
                binding.page_id,
                before_url,
            )
            _fresh, _ids, topology_unchanged = self._scene_control_topology_status(
                session,
                provider_pages_before,
                default_before=default_before,
            )
            if not topology_unchanged:
                raise ManagedBrowserError(
                    "BrowserScene stateful control changed top-level page topology"
                )

            last_state = self._scene_control_state(binding.handle, state_name)
            if last_state is expected_state:
                # Recheck page/topology after the successful state read so the
                # proof includes the same bounded world-state boundary.
                self._scene_control_require_same_page(
                    session,
                    page,
                    binding.page_id,
                    before_url,
                )
                _fresh, _ids, topology_unchanged = self._scene_control_topology_status(
                    session,
                    provider_pages_before,
                    default_before=default_before,
                )
                if not topology_unchanged:
                    raise ManagedBrowserError(
                        "BrowserScene stateful control changed top-level page topology"
                    )
                return last_state

            now = time.monotonic()
            if now >= deadline:
                return last_state
            time.sleep(min(_STATE_POLL_SECONDS, max(0.0, deadline - now)))

    @staticmethod
    def _scene_control_state(handle: Any, state_name: str) -> bool:
        try:
            raw = handle.evaluate(_CONTROL_STATE_SCRIPT)
        except Exception as exc:
            raise ManagedBrowserError(
                "BrowserScene stateful control state observation failed: "
                f"{type(exc).__name__}"
            ) from exc
        if not isinstance(raw, dict) or not bool(raw.get("connected")):
            raise ManagedBrowserError(
                "BrowserScene stateful control exact target is detached"
            )

        aria_disabled = PlaywrightBrowserSceneControlMixin._scene_control_optional_aria_bool(
            raw.get("aria_disabled"),
            "aria-disabled",
        )
        if bool(raw.get("native_disabled")) or aria_disabled is True:
            raise ManagedBrowserError(
                "BrowserScene stateful control target is disabled"
            )

        raw_state = raw.get(f"aria_{state_name}")
        return PlaywrightBrowserSceneControlMixin._scene_control_required_aria_bool(
            raw_state,
            f"aria-{state_name}",
        )

    @staticmethod
    def _scene_control_optional_aria_bool(raw: Any, label: str) -> bool | None:
        if raw is None:
            return None
        if raw == "true":
            return True
        if raw == "false":
            return False
        raise ManagedBrowserError(
            f"BrowserScene stateful control {label} must be literal true/false when present"
        )

    @staticmethod
    def _scene_control_required_aria_bool(raw: Any, label: str) -> bool:
        parsed = PlaywrightBrowserSceneControlMixin._scene_control_optional_aria_bool(
            raw,
            label,
        )
        if parsed is None:
            raise ManagedBrowserError(
                f"BrowserScene stateful control requires an explicit boolean {label} attribute"
            )
        return parsed

    def _scene_control_require_same_page(
        self,
        session: Any,
        page: Any,
        page_id: str,
        before_url: str,
    ) -> None:
        if page_id not in session.pages or session.pages.get(page_id) is not page:
            raise ManagedBrowserError(
                "BrowserScene stateful control exact page identity changed"
            )
        current_url = str(getattr(page, "url", "") or "")
        self._require_url_allowed(current_url, session.permission)
        if current_url != before_url:
            raise ManagedBrowserError(
                "BrowserScene stateful control changed the top-level URL"
            )

    def _scene_control_topology_status(
        self,
        session: Any,
        before: tuple[Any, ...],
        *,
        default_before: str,
    ) -> tuple[tuple[Any, ...], tuple[str, ...], bool]:
        current = self._scene_action_provider_pages(session)
        fresh = tuple(
            page
            for page in current
            if not any(page is old for old in before)
        )
        missing = tuple(
            page
            for page in before
            if not any(page is now for now in current)
        )
        known_ids: list[str] = []
        for page in fresh:
            for page_id, registered in session.pages.items():
                if registered is page:
                    known_ids.append(page_id)
                    break
        unchanged = bool(
            not fresh
            and not missing
            and len(current) == len(before)
            and str(session.default_page_id or "") == default_before
        )
        return fresh, tuple(known_ids), unchanged

    @staticmethod
    def _scene_control_safe_error(exc: Exception, *, stage: str) -> str:
        if isinstance(exc, ManagedBrowserError):
            return f"ManagedBrowserError: {exc}"
        return (
            f"{type(exc).__name__}: "
            f"BrowserScene stateful control {stage} verification failed"
        )

    def _scene_control_evidence(
        self,
        session: Any,
        action: BrowserAction,
        binding: Any,
        *,
        before_url: str,
        page: Any,
        expected_key: str,
        state_name: str,
        expected_state: bool,
        state_before: bool,
        state_after: bool | None,
        dispatch_count: int,
        new_page_ids: tuple[str, ...],
        new_page_count: int,
        topology_unchanged: bool,
        success: bool,
        error: str | None,
    ) -> BrowserEffectEvidence:
        candidate_url = str(getattr(page, "url", "") or "")
        url_after = (
            candidate_url
            if self._url_allowed(candidate_url, session.permission)
            else ""
        )
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=success,
            page_id=binding.page_id,
            url_before=before_url,
            url_after=url_after,
            target_id=action.target.target_id if action.target else "",
            postcondition=f"same_scene_target_aria_{state_name}_equals",
            data={
                "provider": session.identity.provider,
                "role": str(binding.scene_target.role or ""),
                "frame_id": str(binding.scene_target.frame_id or ""),
                "state": state_name,
                "state_before": state_before,
                "state_after": state_after,
                "expected_state": expected_state,
                "expected_key": expected_key,
                "dispatch_count": int(dispatch_count),
                "target_revalidated_before_dispatch": True,
                "new_page_ids": list(new_page_ids),
                "new_page_count": int(new_page_count),
                "fresh_pages_unclaimed": bool(new_page_count),
                "page_topology_unchanged": bool(topology_unchanged),
            },
            error=error,
        )
