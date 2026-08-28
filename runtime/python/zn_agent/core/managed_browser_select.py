from __future__ import annotations

"""Verified native-select mutation for the ZN managed-browser adapter.

This stays separate from provider/session ownership so the action remains a small
resident-owned effect contract: one current native ``select`` element, one
explicit option value, one provider dispatch, then a fresh observation proving
that the exact same DOM node now exposes the requested selected value.
"""

import hashlib
from typing import Any

from .browser import BrowserAction, BrowserEffectEvidence
from .models import utc_now


_MAX_OPTION_VALUE_UTF16_UNITS = 256
_MAX_SELECTED_VALUE_CHARS = 1024

_EXACT_NODE_EQUAL_SCRIPT = r"""
(element, other) => Boolean(element && other && element === other)
"""

_NATIVE_SELECT_STATE_SCRIPT = r"""
(element) => {
  const connected = Boolean(element && element.isConnected);
  const tag = String(element && element.tagName || "").toLowerCase();
  const supported = tag === "select";
  const disabled = Boolean(element && element.disabled);
  const multiple = Boolean(element && element.multiple);
  const selected = connected && supported
    ? Array.from(element.selectedOptions || []).map((option) => String(option.value || ""))
    : [];
  return {
    connected,
    supported,
    disabled,
    multiple,
    selected,
  };
}
"""


class ManagedSelectError(RuntimeError):
    pass


def _value_fingerprint(value: str) -> dict[str, Any]:
    return {
        "length": len(value),
        "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
    }


def _requested_value(action: BrowserAction) -> tuple[str, dict[str, Any]]:
    if "value" not in action.args or not isinstance(action.args.get("value"), str):
        raise ManagedSelectError(
            "browser select_option requires one explicit string value argument"
        )
    value = action.args["value"]
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ManagedSelectError(
            "browser select_option value must not contain control characters"
        )
    try:
        encoded = value.encode("utf-16-le")
    except UnicodeEncodeError as exc:
        raise ManagedSelectError(
            "browser select_option value contains an invalid Unicode scalar sequence"
        ) from exc
    units = len(encoded) // 2
    if units > _MAX_OPTION_VALUE_UTF16_UNITS:
        raise ManagedSelectError(
            f"browser select_option value is limited to {_MAX_OPTION_VALUE_UTF16_UNITS} UTF-16 code units"
        )
    fingerprint = _value_fingerprint(value)
    fingerprint["utf16_units"] = units
    return value, fingerprint


def _read_native_select_value(handle: Any) -> str:
    try:
        raw = handle.evaluate(_NATIVE_SELECT_STATE_SCRIPT)
    except Exception as exc:
        raise ManagedSelectError(
            f"managed browser select state provider failed: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise ManagedSelectError(
            "managed browser select state provider returned invalid evidence"
        )
    if not bool(raw.get("connected")):
        raise ManagedSelectError("managed browser select target is detached")
    if not bool(raw.get("supported")):
        raise ManagedSelectError(
            "managed browser select_option currently supports only native select targets"
        )
    if bool(raw.get("disabled")):
        raise ManagedSelectError("managed browser select target is disabled")
    if bool(raw.get("multiple")):
        raise ManagedSelectError(
            "managed browser select_option first slice refuses multi-select targets"
        )
    selected = raw.get("selected")
    if not isinstance(selected, list) or len(selected) != 1 or not isinstance(selected[0], str):
        raise ManagedSelectError(
            "managed browser select target does not expose exactly one selected value"
        )
    value = selected[0]
    if len(value) > _MAX_SELECTED_VALUE_CHARS:
        raise ManagedSelectError(
            "managed browser selected value exceeds the bounded effect-evidence size"
        )
    return value


def perform_select_option(owner: Any, session: Any, action: BrowserAction) -> BrowserEffectEvidence:
    """Select one native option and prove the fresh exact-node selected value."""

    if action.target is None:
        raise ManagedSelectError("browser select_option requires a current target")
    if action.target.role != "combobox":
        raise ManagedSelectError(
            "browser select_option currently requires a native select/combobox target"
        )

    requested, expected = _requested_value(action)
    page_id = action.page_id or action.target.page_id or owner._default_page_id(session)
    page = owner._page(session, page_id)
    binding = owner._revalidate_target_binding(session, page_id, action.target)
    before_url = str(getattr(page, "url", "") or "")
    before_value = _read_native_select_value(binding.handle)
    if before_value == requested:
        raise ManagedSelectError(
            "browser select_option requested value is already selected before dispatch"
        )

    try:
        # Provider return values are deliberately ignored. Completion comes only
        # from the independently re-observed exact node below.
        binding.handle.select_option(value=requested)
    except Exception as exc:
        owner._refresh_page_observation_after_failed_mutation(session, page_id)
        raise ManagedSelectError(
            f"managed browser select_option dispatch failed: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        requested = ""

    post_captured_at = utc_now()
    try:
        fresh_binding = owner._acquire_target_binding(
            session,
            page_id,
            binding.query,
            observed_at=post_captured_at,
        )
    except Exception as exc:
        owner._refresh_page_observation_after_failed_mutation(session, page_id)
        raise ManagedSelectError(
            f"managed browser select_option target could not be re-observed: {exc}"
        ) from exc

    try:
        same_exact_node = bool(
            binding.handle.evaluate(_EXACT_NODE_EQUAL_SCRIPT, fresh_binding.handle)
        )
    except Exception:
        same_exact_node = False
    try:
        after_value = _read_native_select_value(fresh_binding.handle)
    except Exception as exc:
        owner._dispose_target_binding(fresh_binding)
        owner._refresh_page_observation_after_failed_mutation(session, page_id)
        raise ManagedSelectError(
            f"browser select_option postcondition could not be observed: {exc}"
        ) from exc

    try:
        post_observation = owner._capture(
            session,
            page_id,
            target=fresh_binding.target,
            captured_at=post_captured_at,
            target_binding=fresh_binding,
        )
    except Exception:
        owner._dispose_target_binding(fresh_binding)
        owner._refresh_page_observation_after_failed_mutation(session, page_id)
        raise

    after_url = post_observation.url
    post_target = post_observation.target
    before_fp = _value_fingerprint(before_value)
    after_fp = _value_fingerprint(after_value)
    data = {
        "provider": session.identity.provider,
        "exact_node_continuity": same_exact_node,
        "selection_dispatched": True,
        "selected_value_length_before": before_fp["length"],
        "selected_value_sha256_before": before_fp["sha256"],
        "selected_value_length_after": after_fp["length"],
        "selected_value_sha256_after": after_fp["sha256"],
        "expected_value_length": expected["length"],
        "expected_value_sha256": expected["sha256"],
        "expected_utf16_units": expected["utf16_units"],
    }
    postcondition = "same_exact_target_selected_value"

    if post_target is None:
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=post_observation.captured_at,
            success=False,
            page_id=page_id,
            url_before=before_url,
            url_after=after_url,
            target_id=action.target.target_id,
            postcondition=postcondition,
            data=data,
            error="browser select_option postcondition lost the current target",
        )
    if not same_exact_node:
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=post_observation.captured_at,
            success=False,
            page_id=page_id,
            url_before=before_url,
            url_after=after_url,
            target_id=post_target.target_id,
            postcondition=postcondition,
            data=data,
            error="browser select_option postcondition observed a replaced target node",
        )
    if post_target.target_id != action.target.target_id:
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=post_observation.captured_at,
            success=False,
            page_id=page_id,
            url_before=before_url,
            url_after=after_url,
            target_id=post_target.target_id,
            postcondition=postcondition,
            data=data,
            error="browser select_option postcondition observed changed target identity",
        )
    if (
        int(after_fp["length"]) != int(expected["length"])
        or str(after_fp["sha256"]) != str(expected["sha256"])
    ):
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=post_observation.captured_at,
            success=False,
            page_id=page_id,
            url_before=before_url,
            url_after=after_url,
            target_id=post_target.target_id,
            postcondition=postcondition,
            data=data,
            error="browser select_option postcondition was not observed",
        )

    return BrowserEffectEvidence(
        action_id=action.action_id,
        session_id=action.session_id,
        observed_at=post_observation.captured_at,
        success=True,
        page_id=page_id,
        url_before=before_url,
        url_after=after_url,
        target_id=post_target.target_id,
        postcondition=postcondition,
        data=data,
    )
