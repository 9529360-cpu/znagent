from __future__ import annotations

"""Verified non-navigation command clicks using target-disappearance evidence."""

import hashlib
from typing import Any

from .browser import BrowserAction, BrowserActionAuthority, BrowserActionKind, BrowserEffectEvidence
from .managed_browser import ManagedBrowserError


_SCENE_SELECTOR_PREFIX = "browser_scene:"
_TRIGGER_ROLES = frozenset({"button", "menuitem"})
_MAX_NAME = 256


class PlaywrightBrowserSceneCommandMixin:
    """Execute one exact stateless command only with explicit disappearance proof."""

    def act(self, action: BrowserAction, authority: BrowserActionAuthority) -> BrowserEffectEvidence:
        if not self._is_scene_command(action):
            return super().act(action, authority)
        session = self._session(action.session_id)
        try:
            self._validate_authority(session, action, authority)
            if action.target is None:
                raise ManagedBrowserError("BrowserScene command click requires a current trigger")
            binding = self._scene_action_binding(
                session,
                action.target.target_id,
                page_id=action.page_id or action.target.page_id,
                expected_target=action.target,
            )
            self._scene_revalidate_binding(session, binding)
            return self._scene_command_click(session, action, binding)
        except Exception as exc:
            return self._failure(action, error=f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _is_scene_command(action: BrowserAction) -> bool:
        return bool(
            action.kind is BrowserActionKind.CLICK
            and action.target is not None
            and str(action.target.selector_hint or "").startswith(_SCENE_SELECTOR_PREFIX)
            and "target_absent_equals" in action.expected
        )

    def _scene_command_click(self, session: Any, action: BrowserAction, binding: Any) -> BrowserEffectEvidence:
        role = str(binding.scene_target.role or "")
        if role not in _TRIGGER_ROLES:
            raise ManagedBrowserError("BrowserScene stateless command supports button/menuitem triggers only")
        if action.args:
            raise ManagedBrowserError("BrowserScene stateless command does not accept coordinates/modifiers")
        if set(action.expected) != {"target_absent_equals"}:
            raise ManagedBrowserError("BrowserScene stateless command requires exactly target_absent_equals")

        descriptor = action.expected.get("target_absent_equals")
        if not isinstance(descriptor, dict) or set(descriptor) != {"role", "accessible_name"}:
            raise ManagedBrowserError(
                "target_absent_equals must contain exactly role and accessible_name"
            )
        missing_role = str(descriptor.get("role") or "").strip()
        missing_name = str(descriptor.get("accessible_name") or "").strip()
        if not missing_role or not missing_name or len(missing_name) > _MAX_NAME:
            raise ManagedBrowserError("target_absent_equals role/name is empty or too long")
        if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in missing_name):
            raise ManagedBrowserError("target_absent_equals name contains control characters")

        state = self._scene_state(session)
        page_state = state.page_scenes.get(binding.page_id)
        if page_state is None or bool(getattr(page_state.scene, "truncated", False)):
            raise ManagedBrowserError("BrowserScene command requires a fresh non-truncated scene")
        before_matches = [
            target for target in page_state.scene.targets
            if str(target.role or "") == missing_role
            and str(target.accessible_name or "") == missing_name
        ]
        if len(before_matches) != 1:
            raise ManagedBrowserError(
                "BrowserScene command requires exactly one current target matching target_absent_equals"
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
                f"BrowserScene command click failed: {type(exc).__name__}: {exc}"
            ) from exc

        self._reconcile_pages(session)
        new_page_ids = tuple(pid for pid in session.pages if pid not in before_page_ids)
        after_url = str(getattr(page, "url", "") or "")
        if new_page_ids or after_url != before_url or not self._url_allowed(after_url, session.permission):
            self._scene_invalidate_page(session.identity.session_id, binding.page_id)
            return self._evidence(
                session, action, binding, before_url, after_url,
                success=False,
                missing_role=missing_role,
                missing_name=missing_name,
                before_count=1,
                after_count=None,
                new_page_ids=new_page_ids,
                error="BrowserScene command changed URL/topology unexpectedly",
            )

        scene = self.observe_scene(session.identity.session_id, page_id=binding.page_id)
        if bool(getattr(scene, "truncated", False)):
            return self._evidence(
                session, action, binding, before_url, after_url,
                success=False,
                missing_role=missing_role,
                missing_name=missing_name,
                before_count=1,
                after_count=None,
                new_page_ids=(),
                error="BrowserScene command postcondition cannot be proven from a truncated fresh scene",
                observed_at=scene.captured_at,
            )
        after_matches = [
            target for target in scene.targets
            if str(target.role or "") == missing_role
            and str(target.accessible_name or "") == missing_name
        ]
        return self._evidence(
            session, action, binding, before_url, after_url,
            success=len(after_matches) == 0,
            missing_role=missing_role,
            missing_name=missing_name,
            before_count=1,
            after_count=len(after_matches),
            new_page_ids=(),
            error=None if len(after_matches) == 0 else "BrowserScene command target remained present",
            observed_at=scene.captured_at,
        )

    @staticmethod
    def _name_evidence(value: str) -> dict[str, Any]:
        return {
            "target_name_length": len(value),
            "target_name_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        }

    def _evidence(
        self,
        session: Any,
        action: BrowserAction,
        binding: Any,
        before_url: str,
        after_url: str,
        *,
        success: bool,
        missing_role: str,
        missing_name: str,
        before_count: int,
        after_count: int | None,
        new_page_ids: tuple[str, ...],
        error: str | None,
        observed_at: str | None = None,
    ) -> BrowserEffectEvidence:
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=observed_at or binding.target.observed_at,
            success=success,
            page_id=binding.page_id,
            url_before=before_url,
            url_after=after_url if self._url_allowed(after_url, session.permission) else "",
            target_id=action.target.target_id,
            postcondition="named_scene_target_absent_after_exact_command_click",
            data={
                "provider": session.identity.provider,
                "role": str(binding.scene_target.role or ""),
                "frame_id": binding.scene_target.frame_id,
                "absent_target_role": missing_role,
                **self._name_evidence(missing_name),
                "matching_target_count_before": before_count,
                "matching_target_count_after": after_count,
                "new_page_ids": list(new_page_ids),
                "target_revalidated_before_dispatch": True,
            },
            error=error,
        )
