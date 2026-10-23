from __future__ import annotations

"""Verified bounded non-Enter key presses for exact BrowserScene targets."""

import hashlib
from typing import Any

from .browser import BrowserAction, BrowserActionAuthority, BrowserActionKind, BrowserEffectEvidence
from .managed_browser import ManagedBrowserError
from .models import utc_now


_SCENE_SELECTOR_PREFIX = "browser_scene:"
_SAFE_KEYS = frozenset({"Tab", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"})
_TAB_ROLES = frozenset(
    {"button", "link", "textbox", "searchbox", "textarea", "checkbox", "radio", "combobox", "menuitem", "tab"}
)
_ESCAPE_ROLES = frozenset(
    {"button", "textbox", "searchbox", "textarea", "combobox", "menuitem", "tab"}
)
_ARROW_ROLES = frozenset({"tab", "radio", "menuitem"})
_MAX_NAME = 256

_FOCUSED_SCRIPT = r"""
(element) => Boolean(
  element && element.isConnected && element.ownerDocument &&
  element.ownerDocument.activeElement === element
)
"""


class PlaywrightBrowserSceneKeypressMixin:
    """Handle Tab/Escape/Arrow keys only when a resident-owned postcondition is provable."""

    def act(self, action: BrowserAction, authority: BrowserActionAuthority) -> BrowserEffectEvidence:
        if not self._is_scene_non_enter_press(action):
            return super().act(action, authority)
        session = self._session(action.session_id)
        try:
            self._validate_authority(session, action, authority)
            if action.target is None:
                raise ManagedBrowserError("BrowserScene keypress requires a current target")
            binding = self._scene_action_binding(
                session,
                action.target.target_id,
                page_id=action.page_id or action.target.page_id,
                expected_target=action.target,
            )
            self._scene_revalidate_binding(session, binding)
            return self._scene_non_enter_press(session, action, binding)
        except Exception as exc:
            return self._failure(action, error=f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _is_scene_non_enter_press(action: BrowserAction) -> bool:
        if action.kind is not BrowserActionKind.PRESS or action.target is None:
            return False
        if not str(action.target.selector_hint or "").startswith(_SCENE_SELECTOR_PREFIX):
            return False
        return str(action.args.get("key") or "").strip() != "Enter"

    def _scene_non_enter_press(self, session: Any, action: BrowserAction, binding: Any) -> BrowserEffectEvidence:
        if set(action.args) != {"key"}:
            raise ManagedBrowserError("BrowserScene bounded keypress requires exactly one key argument")
        key = str(action.args.get("key") or "").strip()
        if key not in _SAFE_KEYS:
            raise ManagedBrowserError(
                "BrowserScene bounded keypress accepts only Tab, Escape, ArrowUp, ArrowDown, ArrowLeft, ArrowRight"
            )
        role = str(binding.scene_target.role or "")
        before_descriptor: dict[str, Any] | None = None
        if key == "Tab":
            if role not in _TAB_ROLES:
                raise ManagedBrowserError("BrowserScene Tab requires an interactive focusable-role target")
            if action.expected != {"target_blurred_equals": True}:
                raise ManagedBrowserError("BrowserScene Tab requires target_blurred_equals=true")
        elif key == "Escape":
            if role not in _ESCAPE_ROLES:
                raise ManagedBrowserError("BrowserScene Escape target role is not supported")
            before_descriptor = self._require_unique_expected_target(
                session,
                binding.page_id,
                action,
                expected_key="target_absent_equals",
                state_name="",
            )
        else:
            if role not in _ARROW_ROLES:
                raise ManagedBrowserError("BrowserScene Arrow key requires tab/radio/menuitem target")
            before_descriptor = self._require_unique_expected_target(
                session,
                binding.page_id,
                action,
                expected_key="state_target_equals",
                state_name="required",
            )
            state_name = str(before_descriptor["state"])
            before_target = before_descriptor["target"]
            before_value = getattr(before_target, state_name, None)
            if type(before_value) is not bool:
                raise ManagedBrowserError(
                    f"BrowserScene Arrow expected target does not expose boolean {state_name} state"
                )
            if before_value is True:
                raise ManagedBrowserError(
                    "BrowserScene Arrow state postcondition is already observed before dispatch"
                )

        page = self._page(session, binding.page_id)
        before_url = str(getattr(page, "url", "") or "")
        self._require_url_allowed(before_url, session.permission)
        self._reconcile_pages(session)
        before_page_ids = set(session.pages)
        try:
            binding.handle.press(key)
        except Exception as exc:
            self._scene_failed_mutation(session, binding.page_id)
            raise ManagedBrowserError(
                f"BrowserScene {key} dispatch failed: {type(exc).__name__}: {exc}"
            ) from exc

        self._reconcile_pages(session)
        new_page_ids = tuple(pid for pid in session.pages if pid not in before_page_ids)
        after_url = str(getattr(page, "url", "") or "")
        if not self._url_allowed(after_url, session.permission) or after_url != before_url or new_page_ids:
            self._scene_invalidate_page(session.identity.session_id, binding.page_id)
            return self._keypress_evidence(
                session,
                action,
                binding,
                key=key,
                before_url=before_url,
                after_url=after_url,
                success=False,
                new_page_ids=new_page_ids,
                data={},
                error="BrowserScene bounded keypress changed URL or page topology unexpectedly",
            )

        if key == "Tab":
            try:
                focused_after = bool(binding.handle.evaluate(_FOCUSED_SCRIPT))
            except Exception as exc:
                self._scene_failed_mutation(session, binding.page_id)
                raise ManagedBrowserError(
                    f"BrowserScene Tab focus verification failed: {type(exc).__name__}: {exc}"
                ) from exc
            self._scene_invalidate_page(session.identity.session_id, binding.page_id)
            return self._keypress_evidence(
                session,
                action,
                binding,
                key=key,
                before_url=before_url,
                after_url=after_url,
                success=not focused_after,
                new_page_ids=(),
                data={"focused_after": focused_after},
                error=None if not focused_after else "BrowserScene Tab did not move focus away from exact target",
            )

        scene = self.observe_scene(session.identity.session_id, page_id=binding.page_id)
        if bool(getattr(scene, "truncated", False)):
            return self._keypress_evidence(
                session,
                action,
                binding,
                key=key,
                before_url=before_url,
                after_url=after_url,
                success=False,
                new_page_ids=(),
                data={"fresh_scene_truncated": True},
                error="BrowserScene keypress postcondition cannot be proven from a truncated fresh scene",
                observed_at=scene.captured_at,
            )

        descriptor = before_descriptor or {}
        matches = self._scene_matches(scene, str(descriptor["role"]), str(descriptor["accessible_name"]))
        if key == "Escape":
            success = len(matches) == 0
            data = {
                "expected_target_role": descriptor["role"],
                **self._name_fingerprint(str(descriptor["accessible_name"])),
                "matching_target_count_after": len(matches),
            }
            error = None if success else "BrowserScene Escape expected target remained present"
        else:
            state_name = str(descriptor["state"])
            success = len(matches) == 1 and getattr(matches[0], state_name, None) is True
            data = {
                "expected_target_role": descriptor["role"],
                **self._name_fingerprint(str(descriptor["accessible_name"])),
                "expected_state": state_name,
                "matching_target_count_after": len(matches),
                "state_after": (
                    getattr(matches[0], state_name, None) if len(matches) == 1 else None
                ),
            }
            error = None if success else f"BrowserScene Arrow expected target did not become {state_name}=true"
        return self._keypress_evidence(
            session,
            action,
            binding,
            key=key,
            before_url=before_url,
            after_url=after_url,
            success=success,
            new_page_ids=(),
            data=data,
            error=error,
            observed_at=scene.captured_at,
        )

    def _require_unique_expected_target(
        self,
        session: Any,
        page_id: str,
        action: BrowserAction,
        *,
        expected_key: str,
        state_name: str,
    ) -> dict[str, Any]:
        if set(action.expected) != {expected_key}:
            raise ManagedBrowserError(f"BrowserScene keypress requires exactly {expected_key}")
        raw = action.expected.get(expected_key)
        required_keys = {"role", "accessible_name"}
        if state_name:
            required_keys.update({"state", "value"})
        if not isinstance(raw, dict) or set(raw) != required_keys:
            raise ManagedBrowserError(
                f"BrowserScene {expected_key} descriptor has invalid fields"
            )
        role = str(raw.get("role") or "").strip().lower()
        name = str(raw.get("accessible_name") or "").strip()
        if not role or not name or len(name) > _MAX_NAME:
            raise ManagedBrowserError("BrowserScene keypress expected target role/name is invalid")
        descriptor: dict[str, Any] = {"role": role, "accessible_name": name}
        if state_name:
            state = str(raw.get("state") or "").strip().lower()
            value = raw.get("value")
            if state not in {"selected", "checked"} or value is not True:
                raise ManagedBrowserError(
                    "BrowserScene Arrow state_target_equals requires selected/checked value=true"
                )
            if role == "tab" and state != "selected":
                raise ManagedBrowserError("BrowserScene tab Arrow target must prove selected=true")
            if role == "radio" and state != "checked":
                raise ManagedBrowserError("BrowserScene radio Arrow target must prove checked=true")
            if role == "menuitem" and state != "selected":
                raise ManagedBrowserError("BrowserScene menuitem Arrow target must prove selected=true")
            descriptor.update({"state": state, "value": True})

        state = self._scene_state(session)
        page_state = state.page_scenes.get(page_id)
        if page_state is None or bool(getattr(page_state.scene, "truncated", False)):
            raise ManagedBrowserError("BrowserScene keypress requires a fresh non-truncated current scene")
        matches = self._scene_matches(page_state.scene, role, name)
        if len(matches) != 1:
            raise ManagedBrowserError("BrowserScene keypress expected target must match exactly once before dispatch")
        descriptor["target"] = matches[0]
        return descriptor

    @staticmethod
    def _scene_matches(scene: Any, role: str, name: str) -> list[Any]:
        return [
            target
            for target in tuple(getattr(scene, "targets", ()) or ())
            if str(getattr(target, "role", "") or "").lower() == role
            and str(getattr(target, "accessible_name", "") or "") == name
        ]

    @staticmethod
    def _name_fingerprint(value: str) -> dict[str, Any]:
        return {
            "expected_target_name_length": len(value),
            "expected_target_name_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        }

    def _keypress_evidence(
        self,
        session: Any,
        action: BrowserAction,
        binding: Any,
        *,
        key: str,
        before_url: str,
        after_url: str,
        success: bool,
        new_page_ids: tuple[str, ...],
        data: dict[str, Any],
        error: str | None,
        observed_at: str | None = None,
    ) -> BrowserEffectEvidence:
        payload = {
            "provider": session.identity.provider,
            "role": str(binding.scene_target.role or ""),
            "frame_id": binding.scene_target.frame_id,
            "key": key,
            "new_page_ids": list(new_page_ids),
            "target_revalidated_before_dispatch": True,
            **data,
        }
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=observed_at or utc_now(),
            success=success,
            page_id=binding.page_id,
            url_before=before_url,
            url_after=after_url if self._url_allowed(after_url, session.permission) else "",
            target_id=action.target.target_id,
            postcondition="bounded_scene_keypress_verified",
            data=payload,
            error=error,
        )
