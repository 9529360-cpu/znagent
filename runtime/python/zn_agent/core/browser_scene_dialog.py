from __future__ import annotations

"""Verified page-level ARIA dialog open/close transitions for BrowserScene clicks."""

import hashlib
from typing import Any

from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
)
from .managed_browser import ManagedBrowserError
from .models import utc_now


_SCENE_SELECTOR_PREFIX = "browser_scene:"
_DIALOG_TRIGGER_ROLES = frozenset({"button", "menuitem"})
_DIALOG_EXPECTED_KEYS = frozenset({"dialog_open_equals", "dialog_closed_equals"})
_MAX_DIALOG_NAME = 256

_DIALOG_CONTAINS_CONTROL_SCRIPT = r"""
(dialog, control) => Boolean(
  dialog && control && dialog.isConnected && control.isConnected &&
  dialog.contains(control)
)
"""


class PlaywrightBrowserSceneDialogMixin:
    """Click one exact trigger and prove a named ARIA dialog appears or disappears."""

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        if not self._is_scene_dialog_click(action):
            return super().act(action, authority)

        session = self._session(action.session_id)
        try:
            self._validate_authority(session, action, authority)
            if action.target is None:
                raise ManagedBrowserError(
                    "BrowserScene dialog transition requires a current trigger target"
                )
            binding = self._scene_action_binding(
                session,
                action.target.target_id,
                page_id=action.page_id or action.target.page_id,
                expected_target=action.target,
            )
            self._scene_revalidate_binding(session, binding)
            return self._scene_dialog_click(session, action, binding)
        except Exception as exc:
            return self._failure(action, error=f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _is_scene_dialog_click(action: BrowserAction) -> bool:
        return bool(
            action.kind is BrowserActionKind.CLICK
            and action.target is not None
            and str(action.target.selector_hint or "").startswith(_SCENE_SELECTOR_PREFIX)
            and bool(set(action.expected).intersection(_DIALOG_EXPECTED_KEYS))
        )

    def _scene_dialog_click(
        self,
        session: Any,
        action: BrowserAction,
        binding: Any,
    ) -> BrowserEffectEvidence:
        role = str(binding.scene_target.role or "")
        if role not in _DIALOG_TRIGGER_ROLES:
            raise ManagedBrowserError(
                "BrowserScene dialog transition supports button/menuitem triggers only"
            )
        if action.args:
            raise ManagedBrowserError(
                "BrowserScene dialog transition does not accept coordinates/modifiers"
            )

        expected_key, dialog_name, expect_open = self._dialog_expected(action)
        page_state, matches_before = self._current_dialog_bindings(
            session,
            binding.page_id,
            dialog_name,
        )
        if bool(getattr(page_state.scene, "truncated", False)):
            raise ManagedBrowserError(
                "BrowserScene dialog transition requires a non-truncated current scene"
            )

        if expect_open:
            if matches_before:
                raise ManagedBrowserError(
                    "BrowserScene dialog-open postcondition is already observed before dispatch"
                )
        else:
            if len(matches_before) != 1:
                raise ManagedBrowserError(
                    "BrowserScene dialog-close requires exactly one current named dialog"
                )
            if not self._dialog_contains_control(matches_before[0].handle, binding.handle):
                raise ManagedBrowserError(
                    "BrowserScene dialog-close trigger is not contained by the exact current dialog"
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
                f"BrowserScene dialog trigger click failed: {type(exc).__name__}: {exc}"
            ) from exc

        self._reconcile_pages(session)
        new_page_ids = tuple(
            page_id for page_id in session.pages if page_id not in before_page_ids
        )
        after_url = str(getattr(page, "url", "") or "")
        if not self._url_allowed(after_url, session.permission):
            self._scene_invalidate_page(session.identity.session_id, binding.page_id)
            return self._dialog_failure_evidence(
                session,
                action,
                binding,
                expected_key=expected_key,
                dialog_name=dialog_name,
                before_url=before_url,
                after_url="",
                new_page_ids=new_page_ids,
                error="BrowserScene dialog transition left browser authority",
            )
        if after_url != before_url:
            self._scene_invalidate_page(session.identity.session_id, binding.page_id)
            return self._dialog_failure_evidence(
                session,
                action,
                binding,
                expected_key=expected_key,
                dialog_name=dialog_name,
                before_url=before_url,
                after_url=after_url,
                new_page_ids=new_page_ids,
                error=(
                    "BrowserScene dialog transition changed page URL without a navigation postcondition"
                ),
            )
        if new_page_ids:
            self._scene_invalidate_page(session.identity.session_id, binding.page_id)
            return self._dialog_failure_evidence(
                session,
                action,
                binding,
                expected_key=expected_key,
                dialog_name=dialog_name,
                before_url=before_url,
                after_url=after_url,
                new_page_ids=new_page_ids,
                error=(
                    "BrowserScene dialog transition opened a fresh page; popup attribution is not supported"
                ),
            )

        scene = self.observe_scene(
            session.identity.session_id,
            page_id=binding.page_id,
        )
        if bool(getattr(scene, "truncated", False)):
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=scene.captured_at,
                success=False,
                page_id=binding.page_id,
                url_before=before_url,
                url_after=after_url,
                target_id=action.target.target_id,
                postcondition=(
                    "named_dialog_visible_after_exact_scene_click"
                    if expect_open
                    else "named_dialog_absent_after_exact_scene_click"
                ),
                data={
                    "provider": session.identity.provider,
                    "role": role,
                    "frame_id": binding.scene_target.frame_id,
                    **self._dialog_name_fingerprint(dialog_name),
                    "expected_key": expected_key,
                    "scene_truncated_after": True,
                    "new_page_ids": [],
                    "target_revalidated_before_dispatch": True,
                },
                error=(
                    "BrowserScene dialog postcondition cannot be proven from a truncated fresh scene"
                ),
            )

        matches_after = [
            target
            for target in tuple(getattr(scene, "targets", ()) or ())
            if str(getattr(target, "role", "") or "") == "dialog"
            and str(getattr(target, "accessible_name", "") or "") == dialog_name
        ]
        if expect_open:
            success = len(matches_after) == 1
            postcondition = "named_dialog_visible_after_exact_scene_click"
            error = (
                None
                if success
                else "BrowserScene named dialog did not appear uniquely after trigger click"
            )
        else:
            success = len(matches_after) == 0
            postcondition = "named_dialog_absent_after_exact_scene_click"
            error = (
                None
                if success
                else "BrowserScene named dialog remained visible after close click"
            )

        data = {
            "provider": session.identity.provider,
            "role": role,
            "frame_id": binding.scene_target.frame_id,
            **self._dialog_name_fingerprint(dialog_name),
            "expected_key": expected_key,
            "matching_dialog_count_before": len(matches_before),
            "matching_dialog_count_after": len(matches_after),
            "new_page_ids": [],
            "target_revalidated_before_dispatch": True,
            "fresh_scene_id": str(getattr(scene, "scene_id", "") or ""),
        }
        if expect_open and len(matches_after) == 1:
            data["dialog_target_id_after"] = str(
                getattr(matches_after[0], "target_id", "") or ""
            )

        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=scene.captured_at,
            success=success,
            page_id=binding.page_id,
            url_before=before_url,
            url_after=after_url,
            target_id=action.target.target_id,
            postcondition=postcondition,
            data=data,
            error=error,
        )

    @staticmethod
    def _dialog_expected(action: BrowserAction) -> tuple[str, str, bool]:
        keys = set(action.expected)
        if len(keys) != 1:
            raise ManagedBrowserError(
                "BrowserScene dialog transition requires exactly one dialog postcondition"
            )
        key = next(iter(keys))
        if key not in _DIALOG_EXPECTED_KEYS:
            raise ManagedBrowserError(
                "BrowserScene dialog transition requires dialog_open_equals or dialog_closed_equals"
            )
        raw_name = action.expected.get(key)
        if not isinstance(raw_name, str):
            raise ManagedBrowserError(
                "BrowserScene dialog postcondition requires a string accessible name"
            )
        name = raw_name.strip()
        if not name:
            raise ManagedBrowserError(
                "BrowserScene dialog postcondition requires a non-empty accessible name"
            )
        if len(name) > _MAX_DIALOG_NAME:
            raise ManagedBrowserError(
                f"BrowserScene dialog accessible name is limited to {_MAX_DIALOG_NAME} characters"
            )
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in name):
            raise ManagedBrowserError(
                "BrowserScene dialog accessible name must not contain control characters"
            )
        return key, name, key == "dialog_open_equals"

    def _current_dialog_bindings(
        self,
        session: Any,
        page_id: str,
        dialog_name: str,
    ) -> tuple[Any, list[Any]]:
        state = self._scene_state(session)
        page_state = state.page_scenes.get(page_id)
        if page_state is None:
            raise ManagedBrowserError(
                "BrowserScene dialog transition requires a fresh current scene"
            )
        matches = [
            binding
            for binding in page_state.bindings.values()
            if str(binding.scene_target.role or "") == "dialog"
            and str(binding.scene_target.accessible_name or "") == dialog_name
        ]
        return page_state, matches

    @staticmethod
    def _dialog_contains_control(dialog_handle: Any, control_handle: Any) -> bool:
        try:
            return bool(
                dialog_handle.evaluate(
                    _DIALOG_CONTAINS_CONTROL_SCRIPT,
                    control_handle,
                )
            )
        except Exception as exc:
            raise ManagedBrowserError(
                f"BrowserScene dialog containment verification failed: {type(exc).__name__}: {exc}"
            ) from exc

    @staticmethod
    def _dialog_name_fingerprint(dialog_name: str) -> dict[str, Any]:
        return {
            "dialog_name_length": len(dialog_name),
            "dialog_name_sha256": hashlib.sha256(
                dialog_name.encode("utf-8")
            ).hexdigest(),
        }

    def _dialog_failure_evidence(
        self,
        session: Any,
        action: BrowserAction,
        binding: Any,
        *,
        expected_key: str,
        dialog_name: str,
        before_url: str,
        after_url: str,
        new_page_ids: tuple[str, ...],
        error: str,
    ) -> BrowserEffectEvidence:
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=False,
            page_id=binding.page_id,
            url_before=before_url,
            url_after=after_url,
            target_id=action.target.target_id,
            postcondition=(
                "named_dialog_visible_after_exact_scene_click"
                if expected_key == "dialog_open_equals"
                else "named_dialog_absent_after_exact_scene_click"
            ),
            data={
                "provider": session.identity.provider,
                "role": str(binding.scene_target.role or ""),
                "frame_id": binding.scene_target.frame_id,
                **self._dialog_name_fingerprint(dialog_name),
                "expected_key": expected_key,
                "new_page_ids": list(new_page_ids),
                "target_revalidated_before_dispatch": True,
            },
            error=error,
        )
