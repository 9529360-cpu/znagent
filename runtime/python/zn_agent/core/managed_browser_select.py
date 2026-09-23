from __future__ import annotations

"""Verified native-select mutation for the ZN managed-browser adapter.

The provider-neutral action accepts either one explicit HTML option value or one
explicit visible option label. Playwright owns the mechanical selection; ZN owns
exact target authority, same-node continuity, bounded value handling and fresh
selected-option verification.
"""

import hashlib
from typing import Any

from .browser import BrowserAction, BrowserEffectEvidence
from .browser_select_option import browser_select_option_request
from .models import utc_now


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
  const selectedOptions = connected && supported
    ? Array.from(element.selectedOptions || [])
    : [];
  return {
    connected,
    supported,
    disabled,
    multiple,
    selected_values: selectedOptions.map((option) => String(option.value || "")),
    selected_labels: selectedOptions.map((option) => String(option.label || "")),
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


def _read_native_select_state(handle: Any) -> dict[str, str]:
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
    selected_values = raw.get("selected_values")
    selected_labels = raw.get("selected_labels")
    if (
        not isinstance(selected_values, list)
        or not isinstance(selected_labels, list)
        or len(selected_values) != 1
        or len(selected_labels) != 1
        or not isinstance(selected_values[0], str)
        or not isinstance(selected_labels[0], str)
    ):
        raise ManagedSelectError(
            "managed browser select target does not expose exactly one selected option"
        )
    value = selected_values[0]
    label = selected_labels[0]
    if len(value) > _MAX_SELECTED_VALUE_CHARS or len(label) > _MAX_SELECTED_VALUE_CHARS:
        raise ManagedSelectError(
            "managed browser selected option exceeds the bounded effect-evidence size"
        )
    return {"value": value, "label": label}


def perform_select_option(owner: Any, session: Any, action: BrowserAction) -> BrowserEffectEvidence:
    """Select one native option and prove a fresh exact-node selected value/label."""

    if action.target is None:
        raise ManagedSelectError("browser select_option requires a current target")
    if action.target.role != "combobox":
        raise ManagedSelectError(
            "browser select_option currently requires a native select/combobox target"
        )

    try:
        request = browser_select_option_request(action.args)
    except ValueError as exc:
        raise ManagedSelectError(str(exc)) from exc

    page_id = action.page_id or action.target.page_id or owner._default_page_id(session)
    page = owner._page(session, page_id)
    binding = owner._revalidate_target_binding(session, page_id, action.target)
    before_url = str(getattr(page, "url", "") or "")
    before_state = _read_native_select_state(binding.handle)
    if before_state[request.mode] == request.requested:
        raise ManagedSelectError(
            f"browser select_option requested {request.mode} is already selected before dispatch"
        )

    requested = request.requested
    try:
        if request.mode == "value":
            binding.handle.select_option(value=requested)
        else:
            binding.handle.select_option(label=requested)
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
        after_state = _read_native_select_state(fresh_binding.handle)
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
    before_fp = _value_fingerprint(before_state[request.mode])
    after_fp = _value_fingerprint(after_state[request.mode])
    data = {
        "provider": session.identity.provider,
        "selection_mode": request.mode,
        "exact_node_continuity": same_exact_node,
        "selection_dispatched": True,
        f"selected_{request.mode}_length_before": before_fp["length"],
        f"selected_{request.mode}_sha256_before": before_fp["sha256"],
        f"selected_{request.mode}_length_after": after_fp["length"],
        f"selected_{request.mode}_sha256_after": after_fp["sha256"],
        f"expected_{request.mode}_length": request.length,
        f"expected_{request.mode}_sha256": request.sha256,
        "expected_utf16_units": request.utf16_units,
    }
    postcondition = f"same_exact_target_selected_{request.mode}"

    error = None
    if post_target is None:
        error = "browser select_option postcondition lost the current target"
    elif not same_exact_node:
        error = "browser select_option postcondition observed a replaced target node"
    elif post_target.target_id != action.target.target_id:
        error = "browser select_option postcondition observed changed target identity"
    elif after_fp["length"] != request.length or after_fp["sha256"] != request.sha256:
        error = "browser select_option postcondition was not observed"

    return BrowserEffectEvidence(
        action_id=action.action_id,
        session_id=action.session_id,
        observed_at=post_observation.captured_at,
        success=error is None,
        page_id=page_id,
        url_before=before_url,
        url_after=after_url,
        target_id=post_target.target_id if post_target is not None else action.target.target_id,
        postcondition=postcondition,
        data=data,
        error=error,
    )
