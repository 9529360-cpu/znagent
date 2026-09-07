from __future__ import annotations

"""Verified target-scoped scroll/hover actions for exact BrowserScene nodes."""

from typing import Any

from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
)
from .managed_browser import ManagedBrowserError


_SCENE_SELECTOR_PREFIX = "browser_scene:"
_POINTER_ACTIONS = frozenset(
    {
        BrowserActionKind.SCROLL_INTO_VIEW,
        BrowserActionKind.HOVER,
    }
)

_VIEWPORT_STATE_SCRIPT = r"""
(element) => {
  if (!element || !element.isConnected) return { connected: false };
  const rect = element.getBoundingClientRect();
  const width = Number(rect.width || 0);
  const height = Number(rect.height || 0);
  const viewportWidth = Number(window.innerWidth || document.documentElement?.clientWidth || 0);
  const viewportHeight = Number(window.innerHeight || document.documentElement?.clientHeight || 0);
  const left = Number(rect.left || 0);
  const top = Number(rect.top || 0);
  const right = Number(rect.right || 0);
  const bottom = Number(rect.bottom || 0);
  const intersects = width > 0 && height > 0 && viewportWidth > 0 && viewportHeight > 0 &&
    right > 0 && bottom > 0 && left < viewportWidth && top < viewportHeight;
  const centerX = left + width / 2;
  const centerY = top + height / 2;
  const center_in_viewport = width > 0 && height > 0 &&
    centerX >= 0 && centerX <= viewportWidth && centerY >= 0 && centerY <= viewportHeight;
  return {
    connected: true,
    width,
    height,
    left,
    top,
    right,
    bottom,
    viewport_width: viewportWidth,
    viewport_height: viewportHeight,
    intersects,
    center_in_viewport,
  };
}
"""

_HOVER_STATE_SCRIPT = r"""
(element) => Boolean(element && element.isConnected && element.matches(':hover'))
"""


class PlaywrightBrowserScenePointerMixin:
    """Scroll to or hover one current exact BrowserScene target."""

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        if not self._is_scene_pointer_action(action):
            return super().act(action, authority)

        session = self._session(action.session_id)
        try:
            self._validate_authority(session, action, authority)
            if action.target is None:
                raise ManagedBrowserError(
                    "BrowserScene scroll/hover requires a current target"
                )
            binding = self._scene_action_binding(
                session,
                action.target.target_id,
                page_id=action.page_id or action.target.page_id,
                expected_target=action.target,
            )
            self._scene_revalidate_binding(session, binding)
            return self._scene_pointer_action(session, action, binding)
        except Exception as exc:
            return self._failure(action, error=f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _is_scene_pointer_action(action: BrowserAction) -> bool:
        return bool(
            action.kind in _POINTER_ACTIONS
            and action.target is not None
            and str(action.target.selector_hint or "").startswith(_SCENE_SELECTOR_PREFIX)
        )

    def _scene_pointer_action(
        self,
        session: Any,
        action: BrowserAction,
        binding: Any,
    ) -> BrowserEffectEvidence:
        if action.args:
            raise ManagedBrowserError(
                "BrowserScene scroll/hover first slice does not accept provider-specific args"
            )
        if action.expected:
            raise ManagedBrowserError(
                "BrowserScene scroll/hover does not accept navigation postconditions"
            )

        page = self._page(session, binding.page_id)
        before_url = str(getattr(page, "url", "") or "")
        self._require_url_allowed(before_url, session.permission)
        before_page_ids = set(session.pages)
        before_state = self._scene_viewport_state(binding.handle)
        if not bool(before_state.get("connected")):
            raise ManagedBrowserError("BrowserScene pointer target is detached before dispatch")

        try:
            if action.kind is BrowserActionKind.SCROLL_INTO_VIEW:
                scroll = getattr(binding.handle, "scroll_into_view_if_needed", None)
                if not callable(scroll):
                    raise ManagedBrowserError(
                        "browser provider cannot scroll an exact BrowserScene target into view"
                    )
                scroll()
            elif action.kind is BrowserActionKind.HOVER:
                hover = getattr(binding.handle, "hover", None)
                if not callable(hover):
                    raise ManagedBrowserError(
                        "browser provider cannot hover an exact BrowserScene target"
                    )
                hover()
            else:
                raise ManagedBrowserError(
                    f"unsupported BrowserScene pointer action: {action.kind.value}"
                )
        except ManagedBrowserError:
            self._scene_failed_mutation(session, binding.page_id)
            raise
        except Exception as exc:
            self._scene_failed_mutation(session, binding.page_id)
            raise ManagedBrowserError(
                f"BrowserScene {action.kind.value} dispatch failed: {type(exc).__name__}: {exc}"
            ) from exc

        self._reconcile_pages(session)
        new_page_ids = tuple(
            page_id for page_id in session.pages if page_id not in before_page_ids
        )
        current_url = str(getattr(page, "url", "") or "")
        if not self._url_allowed(current_url, session.permission):
            self._scene_invalidate_page(session.identity.session_id, binding.page_id)
            raise ManagedBrowserError(
                "BrowserScene pointer action moved the page outside browser authority"
            )
        if current_url != before_url:
            self._scene_invalidate_page(session.identity.session_id, binding.page_id)
            return self._pointer_failure_evidence(
                session,
                action,
                binding,
                before_url,
                current_url,
                before_state,
                new_page_ids,
                error="BrowserScene pointer action changed page URL",
            )
        if new_page_ids:
            self._scene_invalidate_page(session.identity.session_id, binding.page_id)
            return self._pointer_failure_evidence(
                session,
                action,
                binding,
                before_url,
                current_url,
                before_state,
                new_page_ids,
                error="BrowserScene pointer action opened a fresh page; attribution is not supported",
            )

        after_state = self._scene_viewport_state(binding.handle)
        if not bool(after_state.get("connected")):
            self._scene_invalidate_page(session.identity.session_id, binding.page_id)
            raise ManagedBrowserError("BrowserScene pointer target detached after dispatch")

        hovered = None
        if action.kind is BrowserActionKind.HOVER:
            try:
                hovered = bool(binding.handle.evaluate(_HOVER_STATE_SCRIPT))
            except Exception as exc:
                self._scene_failed_mutation(session, binding.page_id)
                raise ManagedBrowserError(
                    f"BrowserScene hover state verification failed: {type(exc).__name__}: {exc}"
                ) from exc

        observation = self._scene_post_target_observation(session, binding)
        if action.kind is BrowserActionKind.SCROLL_INTO_VIEW:
            success = bool(after_state.get("intersects"))
            postcondition = "same_scene_target_intersects_viewport_after_scroll"
            error = None if success else "BrowserScene target did not intersect viewport after scroll"
        else:
            success = bool(hovered and after_state.get("intersects"))
            postcondition = "same_scene_target_hovered"
            error = None if success else "BrowserScene target hover state was not observed"

        data = {
            "provider": session.identity.provider,
            "role": str(binding.scene_target.role or ""),
            "frame_id": binding.scene_target.frame_id,
            "target_revalidated_before_dispatch": True,
            "new_page_ids": [],
            "viewport_before": self._bounded_viewport_evidence(before_state),
            "viewport_after": self._bounded_viewport_evidence(after_state),
        }
        if hovered is not None:
            data["hovered"] = hovered

        # Scroll can lazy-load content and hover can reveal overlays. Prove this
        # target first, then invalidate the scene so any subsequent action must
        # ground against a fresh BrowserScene rather than stale candidate order.
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
            postcondition=postcondition,
            data=data,
            error=error,
        )

    @staticmethod
    def _scene_viewport_state(handle: Any) -> dict[str, Any]:
        raw = handle.evaluate(_VIEWPORT_STATE_SCRIPT)
        if not isinstance(raw, dict):
            raise ManagedBrowserError("browser provider returned invalid viewport evidence")
        return raw

    @staticmethod
    def _bounded_viewport_evidence(state: dict[str, Any]) -> dict[str, Any]:
        evidence: dict[str, Any] = {}
        for key in (
            "width",
            "height",
            "left",
            "top",
            "right",
            "bottom",
            "viewport_width",
            "viewport_height",
        ):
            value = state.get(key)
            if isinstance(value, (int, float)):
                evidence[key] = float(value)
        evidence["intersects"] = bool(state.get("intersects"))
        evidence["center_in_viewport"] = bool(state.get("center_in_viewport"))
        return evidence

    def _pointer_failure_evidence(
        self,
        session: Any,
        action: BrowserAction,
        binding: Any,
        before_url: str,
        current_url: str,
        before_state: dict[str, Any],
        new_page_ids: tuple[str, ...],
        *,
        error: str,
    ) -> BrowserEffectEvidence:
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=binding.target.observed_at,
            success=False,
            page_id=binding.page_id,
            url_before=before_url,
            url_after=current_url,
            target_id=action.target.target_id,
            postcondition=(
                "same_scene_target_intersects_viewport_after_scroll"
                if action.kind is BrowserActionKind.SCROLL_INTO_VIEW
                else "same_scene_target_hovered"
            ),
            data={
                "provider": session.identity.provider,
                "role": str(binding.scene_target.role or ""),
                "frame_id": binding.scene_target.frame_id,
                "target_revalidated_before_dispatch": True,
                "new_page_ids": list(new_page_ids),
                "viewport_before": self._bounded_viewport_evidence(before_state),
            },
            error=error,
        )
