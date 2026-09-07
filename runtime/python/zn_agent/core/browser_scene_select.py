from __future__ import annotations

"""Verified native select actions for exact BrowserScene targets.

This mixin keeps option selection inside the existing BrowserAction authority path.
It supports one current native ``select``/combobox and one explicit option value.
Completion is never inferred from the provider return value: ZN either re-observes
the same exact select with the requested value, or (when explicitly authorized)
proves the expected same-page navigation URL after the exact select dispatch.
"""

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
_MAX_OPTION_VALUE_UTF16_UNITS = 256
_MAX_SELECTED_VALUE_CHARS = 1024

_NATIVE_SELECT_STATE_SCRIPT = r"""
(element) => {
  if (!element || !element.isConnected) return { connected: false };
  const tag = String(element.tagName || "").toLowerCase();
  const supported = tag === "select";
  const selected = supported
    ? Array.from(element.selectedOptions || []).map((option) => String(option.value || ""))
    : [];
  return {
    connected: true,
    supported,
    disabled: Boolean(element.disabled),
    multiple: Boolean(element.multiple),
    selected,
  };
}
"""


def _fingerprint(value: str) -> dict[str, Any]:
    return {
        "length": len(value),
        "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
    }


class PlaywrightBrowserSceneSelectMixin:
    """Select one option on one exact native BrowserScene combobox target."""

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        if not self._is_scene_select_action(action):
            return super().act(action, authority)

        session = self._session(action.session_id)
        try:
            self._validate_authority(session, action, authority)
            if action.target is None:
                raise ManagedBrowserError(
                    "BrowserScene select_option requires a current target"
                )
            binding = self._scene_action_binding(
                session,
                action.target.target_id,
                page_id=action.page_id or action.target.page_id,
                expected_target=action.target,
            )
            self._scene_revalidate_binding(session, binding)
            return self._scene_select_option(session, action, authority, binding)
        except Exception as exc:
            return self._failure(
                action,
                error=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _is_scene_select_action(action: BrowserAction) -> bool:
        return bool(
            action.kind is BrowserActionKind.SELECT_OPTION
            and action.target is not None
            and str(action.target.selector_hint or "").startswith(
                _SCENE_SELECTOR_PREFIX
            )
        )

    def _scene_select_option(
        self,
        session: Any,
        action: BrowserAction,
        authority: BrowserActionAuthority,
        binding: Any,
    ) -> BrowserEffectEvidence:
        if str(binding.scene_target.role or "") != "combobox":
            raise ManagedBrowserError(
                "BrowserScene select_option requires a combobox target"
            )
        requested, expected = self._scene_requested_option_value(action)
        before = self._scene_native_select_value(binding.handle)
        if before == requested:
            raise ManagedBrowserError(
                "BrowserScene select_option requested value is already selected before dispatch"
            )

        page = self._page(session, binding.page_id)
        before_url = str(getattr(page, "url", "") or "")
        expected_url = str(action.expected.get("url_equals") or "").strip()
        navigation_expected = bool(expected_url)
        if navigation_expected:
            if not authority.permission.allow_navigation:
                raise ManagedBrowserError(
                    "BrowserScene select_option navigation requires navigation permission"
                )
            self._require_url_allowed(expected_url, session.permission)
            if expected_url == before_url:
                raise ManagedBrowserError(
                    "BrowserScene select_option expected URL is already observed before dispatch"
                )

        self._reconcile_pages(session)
        before_page_ids = set(session.pages)
        try:
            binding.handle.select_option(value=requested)
        except Exception as exc:
            self._scene_failed_mutation(session, binding.page_id)
            raise ManagedBrowserError(
                f"BrowserScene select_option dispatch failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            requested = ""

        self._reconcile_pages(session)
        new_page_ids = tuple(
            page_id for page_id in session.pages if page_id not in before_page_ids
        )
        after_url = str(getattr(page, "url", "") or "")
        if new_page_ids:
            self._scene_invalidate_page(session.identity.session_id, binding.page_id)
            observation = self._capture(session, binding.page_id)
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=observation.captured_at,
                success=False,
                page_id=binding.page_id,
                url_before=before_url,
                url_after=observation.url,
                target_id=action.target.target_id,
                postcondition="scene_select_no_ambiguous_new_page",
                data={
                    "provider": session.identity.provider,
                    "new_page_ids": list(new_page_ids),
                    "requested_value_length": expected["length"],
                    "requested_value_sha256": expected["sha256"],
                },
                error=(
                    "BrowserScene select_option produced a fresh page; popup/new-tab "
                    "selection is not attributed in this slice"
                ),
            )

        if navigation_expected:
            self._scene_invalidate_page(session.identity.session_id, binding.page_id)
            if not self._url_allowed(after_url, session.permission):
                return BrowserEffectEvidence(
                    action_id=action.action_id,
                    session_id=action.session_id,
                    observed_at=utc_now(),
                    success=False,
                    page_id=binding.page_id,
                    url_before=before_url,
                    url_after="",
                    target_id=action.target.target_id,
                    postcondition="url_equals_after_exact_scene_select",
                    data={
                        "provider": session.identity.provider,
                        "requested_value_length": expected["length"],
                        "requested_value_sha256": expected["sha256"],
                        "expected_url": expected_url,
                    },
                    error="BrowserScene select_option left the permitted browser boundary",
                )
            observation = self._capture(session, binding.page_id)
            data = {
                "provider": session.identity.provider,
                "requested_value_length": expected["length"],
                "requested_value_sha256": expected["sha256"],
                "expected_url": expected_url,
                "target_revalidated_before_dispatch": True,
            }
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
                postcondition="url_equals_after_exact_scene_select",
                data=data,
                error=(
                    None
                    if success
                    else "BrowserScene select_option navigation postcondition did not match"
                ),
            )

        if after_url != before_url:
            self._scene_invalidate_page(session.identity.session_id, binding.page_id)
            safe_after = after_url if self._url_allowed(after_url, session.permission) else ""
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=utc_now(),
                success=False,
                page_id=binding.page_id,
                url_before=before_url,
                url_after=safe_after,
                target_id=action.target.target_id,
                postcondition="same_url_after_exact_scene_select",
                data={
                    "provider": session.identity.provider,
                    "requested_value_length": expected["length"],
                    "requested_value_sha256": expected["sha256"],
                },
                error=(
                    "BrowserScene select_option caused navigation without an explicit "
                    "url_equals postcondition"
                ),
            )

        after = self._scene_native_select_value(binding.handle)
        observation = self._scene_post_target_observation(session, binding)
        before_fp = _fingerprint(before)
        after_fp = _fingerprint(after)
        success = (
            int(after_fp["length"]) == int(expected["length"])
            and str(after_fp["sha256"]) == str(expected["sha256"])
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
            postcondition="same_scene_target_selected_value",
            data={
                "provider": session.identity.provider,
                "frame_id": binding.scene_target.frame_id,
                "selected_value_length_before": before_fp["length"],
                "selected_value_sha256_before": before_fp["sha256"],
                "selected_value_length_after": after_fp["length"],
                "selected_value_sha256_after": after_fp["sha256"],
                "expected_value_length": expected["length"],
                "expected_value_sha256": expected["sha256"],
                "expected_utf16_units": expected["utf16_units"],
            },
            error=(
                None
                if success
                else "BrowserScene select_option postcondition was not observed"
            ),
        )

    @staticmethod
    def _scene_requested_option_value(
        action: BrowserAction,
    ) -> tuple[str, dict[str, Any]]:
        value = action.args.get("value")
        if not isinstance(value, str):
            raise ManagedBrowserError(
                "BrowserScene select_option requires one explicit string value argument"
            )
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
            raise ManagedBrowserError(
                "BrowserScene select_option value must not contain control characters"
            )
        try:
            units = len(value.encode("utf-16-le")) // 2
        except UnicodeEncodeError as exc:
            raise ManagedBrowserError(
                "BrowserScene select_option value contains invalid Unicode"
            ) from exc
        if units > _MAX_OPTION_VALUE_UTF16_UNITS:
            raise ManagedBrowserError(
                f"BrowserScene select_option value is limited to {_MAX_OPTION_VALUE_UTF16_UNITS} UTF-16 code units"
            )
        expected = _fingerprint(value)
        expected["utf16_units"] = units
        return value, expected

    @staticmethod
    def _scene_native_select_value(handle: Any) -> str:
        raw = handle.evaluate(_NATIVE_SELECT_STATE_SCRIPT)
        if not isinstance(raw, dict) or not bool(raw.get("connected")):
            raise ManagedBrowserError("BrowserScene select target is detached")
        if not bool(raw.get("supported")):
            raise ManagedBrowserError(
                "BrowserScene select_option supports native select targets only"
            )
        if bool(raw.get("disabled")):
            raise ManagedBrowserError("BrowserScene select target is disabled")
        if bool(raw.get("multiple")):
            raise ManagedBrowserError(
                "BrowserScene select_option first slice refuses multi-select targets"
            )
        selected = raw.get("selected")
        if (
            not isinstance(selected, list)
            or len(selected) != 1
            or not isinstance(selected[0], str)
        ):
            raise ManagedBrowserError(
                "BrowserScene select target does not expose exactly one selected value"
            )
        value = selected[0]
        if len(value) > _MAX_SELECTED_VALUE_CHARS:
            raise ManagedBrowserError(
                "BrowserScene selected value exceeds bounded effect evidence"
            )
        return value
