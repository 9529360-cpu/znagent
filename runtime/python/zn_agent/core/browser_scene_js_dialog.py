from __future__ import annotations

"""Causal native JavaScript dialog handling for exact BrowserScene clicks."""

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
_DIALOG_TRIGGER_ROLES = frozenset({"button", "link", "menuitem"})
_DIALOG_TYPES = frozenset({"alert", "confirm", "prompt"})
_DIALOG_ACTIONS = frozenset({"accept", "dismiss"})
_DIALOG_EXPECTED_KEYS = frozenset({"js_dialog_type", "js_dialog_action", "url_equals"})
_MAX_PROMPT_TEXT_CHARS = 4096


def _fingerprint(value: str) -> dict[str, Any]:
    return {
        "length": len(value),
        "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
    }


class PlaywrightBrowserSceneJsDialogMixin:
    """Handle one native alert/confirm/prompt in the exact click action window."""

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        if not self._is_scene_js_dialog_click(action):
            return super().act(action, authority)

        session = self._session(action.session_id)
        try:
            self._validate_authority(session, action, authority)
            if action.target is None:
                raise ManagedBrowserError(
                    "BrowserScene JavaScript dialog action requires a current trigger target"
                )
            binding = self._scene_action_binding(
                session,
                action.target.target_id,
                page_id=action.page_id or action.target.page_id,
                expected_target=action.target,
            )
            self._scene_revalidate_binding(session, binding)
            return self._scene_js_dialog_click(session, action, authority, binding)
        except Exception as exc:
            return self._failure(action, error=f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _is_scene_js_dialog_click(action: BrowserAction) -> bool:
        return bool(
            action.kind is BrowserActionKind.CLICK
            and action.target is not None
            and str(action.target.selector_hint or "").startswith(_SCENE_SELECTOR_PREFIX)
            and ("js_dialog_type" in action.expected or "js_dialog_action" in action.expected)
        )

    def _scene_js_dialog_click(
        self,
        session: Any,
        action: BrowserAction,
        authority: BrowserActionAuthority,
        binding: Any,
    ) -> BrowserEffectEvidence:
        role = str(binding.scene_target.role or "")
        if role not in _DIALOG_TRIGGER_ROLES:
            raise ManagedBrowserError(
                "BrowserScene JavaScript dialog trigger supports button/link/menuitem targets only"
            )
        expected_type, expected_action, expected_url = self._validate_dialog_request(
            action,
            authority,
            session,
        )
        prompt_text, prompt_fp = self._validate_prompt_text(
            action,
            authority,
            expected_type=expected_type,
            expected_action=expected_action,
        )

        page = self._page(session, binding.page_id)
        before_url = str(getattr(page, "url", "") or "")
        self._require_url_allowed(before_url, session.permission)
        self._reconcile_pages(session)
        before_page_ids = set(session.pages)
        dialog_events: list[dict[str, Any]] = []
        handler_errors: list[str] = []

        def handle_dialog(dialog: Any) -> None:
            observed_type = str(getattr(dialog, "type", "") or "").strip().lower()
            message = str(getattr(dialog, "message", "") or "")
            default_value = str(getattr(dialog, "default_value", "") or "")
            event = {
                "type": observed_type,
                "message": _fingerprint(message),
                "default_value": _fingerprint(default_value),
                "handled_action": "",
                "expected_type_match": observed_type == expected_type,
            }
            # One exact click is authorized to resolve one expected dialog only.
            # Additional or wrong-type dialogs are dismissed to unblock the page,
            # but the resident-owned result is marked failed afterward.
            desired = (
                expected_action
                if not dialog_events and observed_type == expected_type
                else "dismiss"
            )
            try:
                if desired == "accept":
                    accept = getattr(dialog, "accept", None)
                    if not callable(accept):
                        raise RuntimeError("dialog provider has no accept method")
                    if observed_type == "prompt" and prompt_text is not None:
                        accept(prompt_text=prompt_text)
                    else:
                        accept()
                else:
                    dismiss = getattr(dialog, "dismiss", None)
                    if not callable(dismiss):
                        raise RuntimeError("dialog provider has no dismiss method")
                    dismiss()
                event["handled_action"] = desired
            except Exception as exc:
                handler_errors.append(f"{type(exc).__name__}: {exc}")
                # Best-effort safe release. Never accept an unexpected dialog.
                try:
                    dismiss = getattr(dialog, "dismiss", None)
                    if callable(dismiss):
                        dismiss()
                        event["handled_action"] = "dismiss"
                except Exception as dismiss_exc:
                    handler_errors.append(
                        f"dismiss {type(dismiss_exc).__name__}: {dismiss_exc}"
                    )
            finally:
                dialog_events.append(event)

        add_listener = getattr(page, "on", None)
        remove_listener = getattr(page, "remove_listener", None)
        if not callable(add_listener) or not callable(remove_listener):
            raise ManagedBrowserError(
                "browser provider cannot install and remove a scoped dialog listener"
            )

        listener_installed = False
        try:
            add_listener("dialog", handle_dialog)
            listener_installed = True
            binding.handle.click()
        except Exception as exc:
            self._scene_failed_mutation(session, binding.page_id)
            raise ManagedBrowserError(
                f"BrowserScene JavaScript dialog trigger click failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            prompt_text = None
            if listener_installed:
                try:
                    remove_listener("dialog", handle_dialog)
                except Exception as exc:
                    handler_errors.append(
                        f"remove_listener {type(exc).__name__}: {exc}"
                    )

        self._reconcile_pages(session)
        new_page_ids = tuple(
            page_id for page_id in session.pages if page_id not in before_page_ids
        )
        after_url = str(getattr(page, "url", "") or "")
        safe_after_url = after_url if self._url_allowed(after_url, session.permission) else ""

        data: dict[str, Any] = {
            "provider": session.identity.provider,
            "role": role,
            "frame_id": binding.scene_target.frame_id,
            "expected_dialog_type": expected_type,
            "expected_dialog_action": expected_action,
            "dialog_event_count": len(dialog_events),
            "new_page_ids": list(new_page_ids),
            "target_revalidated_before_dispatch": True,
        }
        if prompt_fp is not None:
            data["prompt_text_length"] = prompt_fp["length"]
            data["prompt_text_sha256"] = prompt_fp["sha256"]
        if dialog_events:
            first = dialog_events[0]
            data.update(
                {
                    "observed_dialog_type": first["type"],
                    "observed_dialog_action": first["handled_action"],
                    "dialog_message_length": first["message"]["length"],
                    "dialog_message_sha256": first["message"]["sha256"],
                    "dialog_default_value_length": first["default_value"]["length"],
                    "dialog_default_value_sha256": first["default_value"]["sha256"],
                }
            )

        error = ""
        if not self._url_allowed(after_url, session.permission):
            error = "BrowserScene JavaScript dialog action left browser authority"
        elif new_page_ids:
            error = (
                "BrowserScene JavaScript dialog action opened a fresh page; popup attribution "
                "is not supported in this slice"
            )
        elif handler_errors:
            error = "BrowserScene JavaScript dialog handler failed: " + "; ".join(handler_errors)
        elif len(dialog_events) != 1:
            error = (
                "BrowserScene JavaScript dialog action requires exactly one dialog event in the click window"
            )
        elif dialog_events[0]["type"] != expected_type:
            error = "BrowserScene JavaScript dialog type did not match the explicit expectation"
        elif dialog_events[0]["handled_action"] != expected_action:
            error = "BrowserScene JavaScript dialog action did not match the explicit expectation"
        elif expected_url:
            if after_url != expected_url:
                error = "BrowserScene JavaScript dialog URL postcondition did not match"
        elif after_url != before_url:
            error = (
                "BrowserScene JavaScript dialog action changed page URL without explicit url_equals"
            )

        self._scene_invalidate_page(session.identity.session_id, binding.page_id)
        success = not error
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=success,
            page_id=binding.page_id,
            url_before=before_url,
            url_after=safe_after_url,
            target_id=action.target.target_id,
            postcondition="causal_native_js_dialog_handled",
            data=data,
            error=None if success else error,
        )

    @staticmethod
    def _validate_dialog_request(
        action: BrowserAction,
        authority: BrowserActionAuthority,
        session: Any,
    ) -> tuple[str, str, str]:
        keys = set(action.expected)
        if not {"js_dialog_type", "js_dialog_action"}.issubset(keys):
            raise ManagedBrowserError(
                "BrowserScene JavaScript dialog requires js_dialog_type and js_dialog_action"
            )
        if not keys.issubset(_DIALOG_EXPECTED_KEYS):
            raise ManagedBrowserError(
                "BrowserScene JavaScript dialog only accepts js_dialog_type/js_dialog_action/url_equals expectations"
            )
        expected_type = str(action.expected.get("js_dialog_type") or "").strip().lower()
        expected_action = str(action.expected.get("js_dialog_action") or "").strip().lower()
        if expected_type not in _DIALOG_TYPES:
            raise ManagedBrowserError(
                "BrowserScene JavaScript dialog supports alert/confirm/prompt only"
            )
        if expected_action not in _DIALOG_ACTIONS:
            raise ManagedBrowserError(
                "BrowserScene JavaScript dialog action must be accept or dismiss"
            )
        expected_url = str(action.expected.get("url_equals") or "").strip()
        if expected_url:
            if not authority.permission.allow_navigation:
                raise ManagedBrowserError(
                    "BrowserScene JavaScript dialog URL postcondition requires navigation permission"
                )
            if not session.permission.allows_origin(expected_url):
                raise ManagedBrowserError(
                    "BrowserScene JavaScript dialog expected URL is outside browser authority"
                )
        return expected_type, expected_action, expected_url

    @staticmethod
    def _validate_prompt_text(
        action: BrowserAction,
        authority: BrowserActionAuthority,
        *,
        expected_type: str,
        expected_action: str,
    ) -> tuple[str | None, dict[str, Any] | None]:
        keys = set(action.args)
        if not keys:
            return None, None
        if keys != {"prompt_text"}:
            raise ManagedBrowserError(
                "BrowserScene JavaScript dialog only accepts optional prompt_text args"
            )
        if expected_type != "prompt" or expected_action != "accept":
            raise ManagedBrowserError(
                "BrowserScene prompt_text is only valid when accepting an expected prompt"
            )
        if not authority.permission.allow_text_entry:
            raise ManagedBrowserError(
                "BrowserScene prompt_text requires text-entry permission"
            )
        value = action.args.get("prompt_text")
        if not isinstance(value, str):
            raise ManagedBrowserError("BrowserScene prompt_text must be a string")
        if len(value) > _MAX_PROMPT_TEXT_CHARS:
            raise ManagedBrowserError(
                f"BrowserScene prompt_text is limited to {_MAX_PROMPT_TEXT_CHARS} characters"
            )
        return value, _fingerprint(value)
