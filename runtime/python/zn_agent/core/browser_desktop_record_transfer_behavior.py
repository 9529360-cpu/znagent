from __future__ import annotations

"""E2E-14: one bounded USER Browser record -> current desktop record transfer.

The representative slice moves exactly one scalar field. The USER Browser is
source authority: it first identifies one unique visible source row, then the
current desktop app must expose the same read-only business key before any
mutation. Existing UIA replacement, durable side-effect attempts, pointer Save
lifecycle and Root Work acceptance remain the only effect/completion truths.
"""

import hashlib
import json
import time
import uuid
from typing import Any

from .action import NativeActionIntent
from .automation_text_content import text_sha256
from .models import ExecutionPath, ResidentRunResult, utc_now

_STATE_KEY = "e2e14_browser_desktop_record_transfer"
_INSTALL_MARKER = "_e2e14_browser_desktop_record_transfer_installed"
_ACCEPTANCE = "cross_app_record_transfer:v1"
_KEY_NAME = "客户编号"
_FIELD_NAME = "跟进状态"
_SAVE_NAME = "保存"
_SOURCE_ANCHOR = "需跟进"
_MAX_SCALAR_CHARS = 160
_MAX_FINAL_OBSERVATIONS = 40
_BROWSER_PROCESSES = frozenset(
    {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"}
)
_TASK_CUES = ("当前浏览器", "浏览器")
_DESTINATION_CUES = ("客户管理软件", "客户管理")


class _Blocked(RuntimeError):
    pass


def _sha(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _bounded_audit(value: str) -> dict[str, Any]:
    text = str(value)
    return {"chars": len(text), "sha256": _sha(text)}


def _same_text(value: str, audit: dict[str, Any]) -> bool:
    return len(value) == int(audit.get("chars") or -1) and _sha(value) == str(
        audit.get("sha256") or ""
    )


def _title_has_saved_marker(value: str) -> bool:
    text = str(value or "")
    return "已保存" in text or "saved" in text.casefold()


def _is_request(event) -> bool:
    if str(getattr(event, "kind", "") or "").strip().lower() != "desktop_user_event":
        return False
    payload = getattr(event, "payload", {}) or {}
    if payload.get("body_action") or payload.get("native_action"):
        return False
    task = " ".join(str(getattr(event, "task", "") or "").split())
    lowered = task.casefold()
    return bool(
        any(cue.casefold() in lowered for cue in _TASK_CUES)
        and any(cue.casefold() in lowered for cue in _DESTINATION_CUES)
        and _SOURCE_ANCHOR in task
        and (_FIELD_NAME in task or "跟进信息" in task)
        and (_SAVE_NAME in task or "save" in lowered)
        and ("填" in task or "transfer" in lowered or "copy" in lowered)
    )


def _target_audit(target) -> dict[str, Any]:
    return {
        "runtime_id": list(target.runtime_id),
        "process_id": int(target.process_id),
        "process_name": str(target.process_name),
        "semantic_name": str(target.name),
        "control_type": int(target.control_type),
        "is_enabled": bool(target.is_enabled),
        "is_offscreen": bool(target.is_offscreen),
        "is_password": bool(target.is_password),
        "is_value_pattern_available": bool(target.is_value_pattern_available),
        "value_is_read_only": target.value_is_read_only,
        "captured_at": str(target.captured_at),
        "source": str(target.source),
    }


def _terminal(resident, event, state, reason: str):
    meta = state.data.setdefault(_STATE_KEY, {})
    if isinstance(meta, dict):
        meta["failure"] = str(reason)[:2000]
    resident.store.save_working_state(state)
    return resident._checkpoint_terminal_failure(event, state, reason=str(reason))


def _foreground(resident, meta: dict[str, Any] | None = None, *, require_hwnd: bool):
    foreground = resident.foreground_window.probe()
    process_name = str(foreground.process_name or "").strip().lower()
    if int(foreground.window_handle or 0) <= 0 or process_name in _BROWSER_PROCESSES:
        raise _Blocked("E2E-14 requires one foreground non-browser desktop application")
    if meta is not None:
        if (
            int(foreground.process_id) != int(meta.get("process_id") or 0)
            or process_name != str(meta.get("process_name") or "").strip().lower()
        ):
            raise _Blocked("destination application process identity drifted")
        if require_hwnd and int(foreground.window_handle) != int(
            meta.get("source_window_handle") or 0
        ):
            raise _Blocked("destination application HWND drifted before commit")
    return foreground


def _read_field(resident, foreground, name: str, *, allow_read_only: bool):
    target = resident.named_automation_control.find_unique_edit(
        process_id=int(foreground.process_id),
        process_name=str(foreground.process_name),
        name=name,
    )
    read = resident.current_app_text_content.read_exact(
        process_id=int(foreground.process_id),
        process_name=str(foreground.process_name),
        window_handle=int(foreground.window_handle),
        name=name,
        runtime_id=tuple(target.runtime_id),
        allow_read_only=allow_read_only,
    )
    return target, read


def _parse_source_context(context: str) -> tuple[str, str]:
    """Parse one narrow structured row: ``<business key> 需跟进``.

    The status token is user-visible source semantics, not a selector. The
    extension must already have proven there is exactly one structured visible
    result containing that token.
    """

    normalized = " ".join(str(context or "").split())
    if normalized.count(_SOURCE_ANCHOR) != 1 or not normalized.endswith(_SOURCE_ANCHOR):
        raise _Blocked("source row did not expose exactly one supported follow-up status")
    business_key = normalized[: -len(_SOURCE_ANCHOR)].strip(" :-—|\t")
    if not business_key or len(business_key) > _MAX_SCALAR_CHARS:
        raise _Blocked("source business key is empty or outside the bounded limit")
    if _SOURCE_ANCHOR in business_key or any(
        ord(char) < 0x20 and char not in "\t\r\n" for char in business_key
    ):
        raise _Blocked("source business key is not one safe bounded scalar")
    return business_key, _SOURCE_ANCHOR


def _source_observation(
    resident,
    *,
    expected_tab_id: int | None = None,
    expected_attached_at: str | None = None,
) -> tuple[dict[str, Any], str, str]:
    authorization = resident.user_browser_extension.authorized_tab()
    if authorization is None:
        raise _Blocked("no exact USER Browser tab is currently authorized")
    tab_id = int(authorization.tab_id)
    attached_at = str(authorization.attached_at or "")
    if expected_tab_id is not None and tab_id != int(expected_tab_id):
        raise _Blocked("USER Browser tab identity changed")
    if expected_attached_at is not None and attached_at != str(expected_attached_at):
        raise _Blocked("USER Browser authorization generation changed")
    try:
        observed = resident._observe_authorized_anchor(_SOURCE_ANCHOR)
    except Exception as exc:
        raise _Blocked(
            "fresh USER Browser source could not prove exactly one structured source record: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    current = resident.user_browser_extension.authorized_tab()
    if (
        current is None
        or int(current.tab_id) != tab_id
        or str(current.attached_at or "") != attached_at
        or int(observed.get("tab_id") or 0) != tab_id
    ):
        raise _Blocked("USER Browser authorization generation changed during source observation")
    context = " ".join(str(observed.get("context") or "").split())
    business_key, scalar = _parse_source_context(context)
    url = str(observed.get("url") or "")
    title = str(observed.get("title") or "")
    if not url:
        raise _Blocked("USER Browser source did not expose a stable current page URL")
    return (
        {
            "tab_id": tab_id,
            "authorization_attached_at": attached_at,
            "url": _bounded_audit(url),
            "title": _bounded_audit(title),
            "row": _bounded_audit(context),
            "business_key": _bounded_audit(business_key),
            "value": _bounded_audit(scalar),
            "observed_at": str(observed.get("observed_at") or ""),
            "source": str(observed.get("source") or ""),
        },
        business_key,
        scalar,
    )


def _source_exact(current: dict[str, Any], expected: dict[str, Any]) -> bool:
    return bool(
        int(current.get("tab_id") or 0) == int(expected.get("tab_id") or 0)
        and str(current.get("authorization_attached_at") or "")
        == str(expected.get("authorization_attached_at") or "")
        and dict(current.get("url") or {}) == dict(expected.get("url") or {})
        and dict(current.get("business_key") or {}) == dict(expected.get("business_key") or {})
        and dict(current.get("row") or {}) == dict(expected.get("row") or {})
        and dict(current.get("value") or {}) == dict(expected.get("value") or {})
    )


def _fresh_binding(
    resident,
    meta: dict[str, Any],
    *,
    require_hwnd: bool,
    require_initial_value: bool,
):
    source, source_key, source_value = _source_observation(
        resident,
        expected_tab_id=int(meta.get("source", {}).get("tab_id") or 0),
        expected_attached_at=str(meta.get("source", {}).get("authorization_attached_at") or ""),
    )
    if not _source_exact(source, dict(meta.get("source") or {})):
        raise _Blocked("USER Browser source record/value drifted from the captured transfer source")
    if not _same_text(source_key, dict(meta.get("business_key") or {})):
        raise _Blocked("USER Browser business record identity drifted")

    foreground = _foreground(resident, meta, require_hwnd=require_hwnd)
    key_target, key_read = _read_field(resident, foreground, _KEY_NAME, allow_read_only=True)
    if key_target.value_is_read_only is not True:
        raise _Blocked("fresh destination business-key field is no longer read-only")
    key_value = str(key_read.text)
    if not _same_text(key_value, dict(meta.get("business_key") or {})) or key_value != source_key:
        raise _Blocked("desktop destination business record no longer matches Browser source identity")
    field_target, field_read = _read_field(
        resident,
        foreground,
        _FIELD_NAME,
        allow_read_only=not require_hwnd,
    )
    if require_hwnd and field_target.value_is_read_only is not False:
        raise _Blocked("fresh destination transfer field is no longer writable")
    field_text = str(field_read.text)
    if require_initial_value and not _same_text(
        field_text, dict(meta.get("destination_initial_value") or {})
    ):
        raise _Blocked("desktop destination field changed before transfer mutation")
    return foreground, key_target, key_read, field_target, field_read, source_key, source_value


def _begin(resident, event, state):
    root = resident.work_ledger.work_item_for_event(event.event_id)
    if root is None or root.parent_work_item_id is not None or not root.acceptance_criteria:
        return _terminal(
            resident,
            event,
            state,
            "E2E-14 requires one criterion-bound Root Work owned by the Product Resident",
        )
    try:
        source, source_key, _source_value = _source_observation(resident)
        foreground = _foreground(resident, require_hwnd=True)
        key_target, key_read = _read_field(resident, foreground, _KEY_NAME, allow_read_only=True)
        if key_target.value_is_read_only is not True:
            raise _Blocked("destination business-key field must be independently read-only")
        business_key = str(key_read.text)
        if not business_key or len(business_key) > _MAX_SCALAR_CHARS:
            raise _Blocked("destination business-key value is empty or outside the bounded limit")
        if business_key != source_key:
            raise _Blocked("current desktop record does not match the Browser source business key")
        field_target, field_read = _read_field(resident, foreground, _FIELD_NAME, allow_read_only=False)
        if field_target.value_is_read_only is not False:
            raise _Blocked("destination transfer field must expose one writable UIA ValuePattern")
        save_button = resident.named_automation_control.find_unique_button(
            process_id=int(foreground.process_id),
            process_name=str(foreground.process_name),
            name=_SAVE_NAME,
        )
    except Exception as exc:
        return _terminal(
            resident,
            event,
            state,
            "E2E-14 preflight could not prove one source-first Browser record and matching "
            f"desktop record/field/Save target: {type(exc).__name__}: {exc}",
        )

    meta = {
        "version": 1,
        "acceptance": _ACCEPTANCE,
        "phase": "replace",
        "process_id": int(foreground.process_id),
        "process_name": str(foreground.process_name or "").strip().lower(),
        "source_window_handle": int(foreground.window_handle),
        "source_window_title": _bounded_audit(str(foreground.title or "")),
        "business_key": _bounded_audit(source_key),
        "business_key_target": _target_audit(key_target),
        "destination_field_target": _target_audit(field_target),
        "destination_initial_value": _bounded_audit(str(field_read.text)),
        "source": source,
        "initial_save_target": {
            "runtime_id": list(save_button.runtime_id),
            "semantic_name": _SAVE_NAME,
            "captured_at": str(save_button.captured_at),
        },
        "replacement_dispatch_count": 0,
        "save_dispatch_count": 0,
        "final_observation_count": 0,
        "started_at": utc_now(),
    }
    state.data[_STATE_KEY] = meta
    state.stage = "e2e14_replace"
    state.next_action = (
        "freshly re-prove Browser source first, then matching desktop business key before one replacement"
    )
    state.blocked_by = None
    resident.store.save_working_state(state)
    return None


def _resolve_uncertain_replacement(resident, event, state) -> tuple[bool, ResidentRunResult | None]:
    if str(getattr(state, "stage", "") or "") != "e2e14_replace":
        return False, None
    raw_meta = state.data.get(_STATE_KEY)
    if not isinstance(raw_meta, dict) or str(raw_meta.get("phase") or "") != "replace":
        return False, None
    reader = getattr(resident.body, "value_replacement_attempts", None)
    if not callable(reader):
        return False, None
    try:
        attempts = list(reader(event.event_id))
    except Exception as exc:
        return True, _terminal(
            resident,
            event,
            state,
            f"E2E-14 could not inspect durable replacement ownership: {type(exc).__name__}: {exc}",
        )
    if not attempts:
        return False, None
    if len(attempts) != 1:
        return True, _terminal(
            resident,
            event,
            state,
            "E2E-14 found multiple unresolved replacement attempts; refusing all replay",
        )
    attempt = dict(attempts[0])
    attempt_id = str(attempt.get("attempt_id") or "").strip()
    status = str(attempt.get("status") or "").strip().lower()
    if not attempt_id or status not in {"started", "observed", "verified_effect"}:
        return True, _terminal(
            resident,
            event,
            state,
            "E2E-14 durable replacement ownership is malformed; refusing replay",
        )
    meta = dict(raw_meta)
    try:
        foreground, _key_target, _key_read, _field_target, field_read, _source_key, _source_value = (
            _fresh_binding(
                resident,
                meta,
                require_hwnd=True,
                require_initial_value=False,
            )
        )
    except Exception as exc:
        return True, _terminal(
            resident,
            event,
            state,
            "E2E-14 interrupted replacement can only be reconciled from fresh exact Browser/Desktop reality; "
            f"{type(exc).__name__}: {exc}",
        )
    expected = dict(meta.get("source", {}).get("value") or {})
    if not _same_text(str(field_read.text), expected):
        return True, _terminal(
            resident,
            event,
            state,
            "E2E-14 interrupted replacement is not proven in fresh destination reality; holding uncertainty and refusing replay",
        )
    if status in {"started", "observed"} and not resident.body.resolve_uncertain_attempt(
        attempt_id,
        event_id=event.event_id,
        status="verified_effect",
    ):
        return True, _terminal(
            resident,
            event,
            state,
            "E2E-14 could not resolve the durable replacement attempt from verified effect",
        )
    meta["replacement_recovery"] = {
        "attempt_id": attempt_id,
        "status_before": status,
        "status_after": "verified_effect",
        "process_id": int(foreground.process_id),
        "window_handle": int(foreground.window_handle),
        "expected_value": expected,
        "additional_replacement_dispatches": 0,
        "recovered_at": utc_now(),
    }
    meta["phase"] = "verify_replacement"
    state.data[_STATE_KEY] = meta
    state.stage = "e2e14_verify_replacement"
    state.next_action = "freshly verify Browser source and transferred desktop field before Save"
    state.blocked_by = None
    resident.store.save_working_state(state)
    return True, None


def _replace(resident, event, state):
    meta = dict(state.data.get(_STATE_KEY) or {})
    try:
        foreground, _key_target, _key_read, field_target, field_read, _source_key, source_value = (
            _fresh_binding(
                resident,
                meta,
                require_hwnd=True,
                require_initial_value=True,
            )
        )
    except Exception as exc:
        return _terminal(
            resident,
            event,
            state,
            f"E2E-14 fresh pre-mutation authority failed closed: {type(exc).__name__}: {exc}",
        )

    expected = dict(meta.get("source", {}).get("value") or {})
    current_value = str(field_read.text)
    if _same_text(current_value, expected):
        meta["replacement_skipped_already_equal"] = True
    else:
        result = resident.body.act(
            "automation_value_replace",
            event_id=event.event_id,
            process_id=int(foreground.process_id),
            process_name=str(foreground.process_name),
            window_handle=int(foreground.window_handle),
            name=_FIELD_NAME,
            runtime_id=list(field_target.runtime_id),
            source_chars=len(current_value),
            source_sha256=text_sha256(current_value),
            replacement_text=source_value,
            result_chars=int(expected.get("chars") or 0),
            result_sha256=str(expected.get("sha256") or ""),
        )
        safe_result = {
            key: value
            for key, value in dict(result.data or {}).items()
            if key not in {"replacement_text", "text", "content", "output"}
        }
        meta["replacement_body_result"] = safe_result
        meta["replacement_dispatch_count"] = 1
        state.data[_STATE_KEY] = meta
        if not result.success:
            if bool(safe_result.get("side_effect_uncertain")):
                attempt_id = str(safe_result.get("side_effect_attempt_id") or "")
                try:
                    _target, fresh = _read_field(
                        resident,
                        foreground,
                        _FIELD_NAME,
                        allow_read_only=False,
                    )
                except Exception as exc:
                    return _terminal(
                        resident,
                        event,
                        state,
                        "E2E-14 replacement became uncertain and destination could not be freshly reread; "
                        f"{type(exc).__name__}: {exc}",
                    )
                if (
                    attempt_id
                    and _same_text(str(fresh.text), expected)
                    and resident.body.resolve_uncertain_attempt(
                        attempt_id,
                        event_id=event.event_id,
                        status="verified_effect",
                    )
                ):
                    meta["replacement_uncertainty_resolved"] = "verified_effect"
                else:
                    return _terminal(
                        resident,
                        event,
                        state,
                        "E2E-14 replacement effect remained uncertain; refusing any blind replay",
                    )
            elif bool(safe_result.get("mutation_dispatched")):
                return _terminal(
                    resident,
                    event,
                    state,
                    result.error
                    or "E2E-14 replacement dispatched without exact postcondition; refusing replay",
                )
            else:
                return _terminal(
                    resident,
                    event,
                    state,
                    result.error or "E2E-14 replacement failed before a verified mutation",
                )

    meta["phase"] = "verify_replacement"
    meta["replacement_verified_at"] = utc_now()
    state.data[_STATE_KEY] = meta
    state.stage = "e2e14_verify_replacement"
    state.next_action = "freshly reread Browser source and transferred desktop field before Save"
    resident.store.save_working_state(state)
    return None


def _verify_replacement(resident, event, state):
    meta = dict(state.data.get(_STATE_KEY) or {})
    try:
        _foreground_now, _key_target, _key_read, field_target, field_read, _source_key, _source_value = (
            _fresh_binding(
                resident,
                meta,
                require_hwnd=True,
                require_initial_value=False,
            )
        )
    except Exception as exc:
        return _terminal(
            resident,
            event,
            state,
            f"E2E-14 post-replacement fresh verification failed: {type(exc).__name__}: {exc}",
        )
    expected = dict(meta.get("source", {}).get("value") or {})
    if not _same_text(str(field_read.text), expected):
        return _terminal(
            resident,
            event,
            state,
            "E2E-14 fresh destination readback did not equal the current Browser scalar",
        )
    meta["replacement_fresh_readback"] = {
        "value": _bounded_audit(str(field_read.text)),
        "target": _target_audit(field_target),
        "verified_at": utc_now(),
    }
    meta["phase"] = "save_prepare"
    state.data[_STATE_KEY] = meta
    state.stage = "e2e14_save_prepare"
    state.next_action = "freshly prove Browser source and matching desktop record again, then Save once"
    resident.store.save_working_state(state)
    return None


def _save_prepare(resident, event, state):
    meta = dict(state.data.get(_STATE_KEY) or {})
    try:
        foreground, _key_target, _key_read, _field_target, field_read, _source_key, _source_value = (
            _fresh_binding(
                resident,
                meta,
                require_hwnd=True,
                require_initial_value=False,
            )
        )
        expected = dict(meta.get("source", {}).get("value") or {})
        if not _same_text(str(field_read.text), expected):
            raise _Blocked("destination field no longer matches Browser source before Save")
        pre_save_title = str(foreground.title or "")
        if _title_has_saved_marker(pre_save_title):
            raise _Blocked("destination application already reports saved state before Save")
        button = resident.named_automation_control.find_unique_button(
            process_id=int(foreground.process_id),
            process_name=str(foreground.process_name),
            name=_SAVE_NAME,
        )
    except Exception as exc:
        return _terminal(
            resident,
            event,
            state,
            f"E2E-14 Save preflight failed closed: {type(exc).__name__}: {exc}",
        )
    meta["pre_save_title"] = _bounded_audit(pre_save_title)
    meta["save_target"] = {
        "runtime_id": list(button.runtime_id),
        "semantic_name": _SAVE_NAME,
        "center_x_fraction": float(button.center_x_fraction),
        "center_y_fraction": float(button.center_y_fraction),
        "captured_at": str(button.captured_at),
    }
    meta["phase"] = "save_dispatch"
    state.data[_STATE_KEY] = meta
    intent = NativeActionIntent(
        intent_id=f"e2e14-save-{uuid.uuid4().hex[:12]}",
        event_id=event.event_id,
        kind="pointer_click",
        args={
            "x_fraction": float(button.center_x_fraction),
            "y_fraction": float(button.center_y_fraction),
            "button": "left",
        },
        expected_outcome={
            "kind": "e2e14_save_click",
            "button_name": _SAVE_NAME,
            "runtime_id": list(button.runtime_id),
            "window_handle": int(foreground.window_handle),
        },
        reason=(
            "E2E-14 commits only after fresh source-first USER Browser evidence, matching desktop "
            "business key, destination field readback and exact Save grounding"
        ),
        source="e2e14_browser_desktop_record_transfer",
    )
    resident._begin_native_action_cycle(event, state, intent)
    resident.store.save_working_state(state)
    return None


def _safe_summary(meta: dict[str, Any]) -> str:
    final = dict(meta.get("final_verification") or {})
    payload = {
        "e2e14_evidence": "independent_cross_app_readback",
        "version": 1,
        "browser_tab_id": int(meta.get("source", {}).get("tab_id") or 0),
        "browser_authorization_attached_at": str(
            meta.get("source", {}).get("authorization_attached_at") or ""
        ),
        "browser_url": dict(meta.get("source", {}).get("url") or {}),
        "browser_row": dict(meta.get("source", {}).get("row") or {}),
        "business_key": dict(meta.get("business_key") or {}),
        "expected_value": dict(meta.get("source", {}).get("value") or {}),
        "replacement_dispatch_count": int(meta.get("replacement_dispatch_count") or 0),
        "save_dispatch_count": int(meta.get("save_dispatch_count") or 0),
        "process_id": int(meta.get("process_id") or 0),
        "process_name": str(meta.get("process_name") or ""),
        "source_window_handle": int(meta.get("source_window_handle") or 0),
        "final_window_handle": int(final.get("window_handle") or 0),
        "final_business_key": dict(final.get("business_key") or {}),
        "final_value": dict(final.get("value") or {}),
        "source_exact": bool(final.get("source_exact")),
        "pre_save_title": dict(meta.get("pre_save_title") or {}),
        "post_save_title": dict(final.get("post_save_title") or {}),
        "title_saved_postcondition": bool(final.get("title_saved_postcondition")),
        "title_saved_transition": bool(final.get("title_saved_transition")),
        "root_readback_verified": bool(final.get("readback_verified")),
        "verified_at": str(final.get("verified_at") or ""),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _accept_root(resident, event, meta: dict[str, Any]) -> None:
    root = resident.work_ledger.work_item_for_event(event.event_id)
    if root is None or root.parent_work_item_id is not None or not root.acceptance_criteria:
        raise RuntimeError("E2E-14 final verification lost criterion-bound Root Work")
    items = resident.work_ledger.list_work_items(root.work_thread_id, limit=256)

    def child(title: str, objective: str, criterion: str):
        current = [
            item
            for item in items
            if item.parent_work_item_id == root.work_item_id
            and item.plan_version == root.plan_version
            and item.title == title
            and item.objective == objective
            and list(item.acceptance_criteria) == [criterion]
        ]
        if len(current) > 1:
            raise RuntimeError(f"ambiguous E2E-14 WorkItems for {title!r}")
        if current:
            return current[0]
        return resident.work_ledger.create_child_item(
            root_work_item_id=root.work_item_id,
            objective=objective,
            acceptance_criteria=[criterion],
            title=title,
        )

    summary = _safe_summary(meta)
    execution = child(
        "E2E-14 bounded cross-app execution",
        "Transfer one bounded Browser scalar into the exact matching current desktop business record and Save once",
        "Browser-source-first identity plus one bounded mutation reached fresh saved-state verification",
    )
    if execution.status != "completed":
        resident.work_ledger.complete_child_item(execution.work_item_id, result=summary)
    verifier = child(
        "E2E-14 cross-app saved-state verifier",
        "Independently re-prove USER Browser source and fresh desktop record/value after Save",
        "independent_python_verification:e2e14 Browser source hash and fresh desktop business-key/value hashes match",
    )
    if verifier.status != "completed":
        verifier = resident.work_ledger.complete_child_item(verifier.work_item_id, result=summary)
    accepted = resident.work_ledger.accept_root_with_current_evidence(
        event.event_id,
        verifier_work_item_id=verifier.work_item_id,
        verification_summary=summary,
    )
    if accepted.status != "completed":
        raise RuntimeError("E2E-14 independent Root acceptance did not complete")
    meta["root_work_item_id"] = accepted.work_item_id
    meta["root_work_status"] = accepted.status
    meta["root_accepted_at"] = utc_now()


def _final_verify(resident, event, state):
    meta = dict(state.data.get(_STATE_KEY) or {})
    execution = state.data.get(
        getattr(resident, "_POINTER_CLICK_EXECUTION_KEY", "native_pointer_click_execution")
    )
    if not (
        isinstance(execution, dict)
        and str(execution.get("status") or "") == "completed"
        and execution.get("success") is True
    ):
        return _terminal(
            resident,
            event,
            state,
            "E2E-14 Save pointer dispatch is not durably proven successful; refusing replay",
        )
    if int(meta.get("save_dispatch_count") or 0) == 0:
        meta["save_dispatch_count"] = 1
        meta["save_action_id"] = str(execution.get("action_id") or "")

    pre_save_title = dict(meta.get("pre_save_title") or {})
    try:
        pre_save_title_chars = int(pre_save_title["chars"])
    except (KeyError, TypeError, ValueError):
        pre_save_title_chars = -1
    if pre_save_title_chars < 0 or len(str(pre_save_title.get("sha256") or "")) != 64:
        return _terminal(
            resident,
            event,
            state,
            "E2E-14 Save completion lost the bounded unsaved pre-Save title evidence",
        )

    observations = int(meta.get("final_observation_count") or 0) + 1
    meta["final_observation_count"] = observations
    state.data[_STATE_KEY] = meta

    try:
        source, source_key, _source_value = _source_observation(
            resident,
            expected_tab_id=int(meta.get("source", {}).get("tab_id") or 0),
            expected_attached_at=str(meta.get("source", {}).get("authorization_attached_at") or ""),
        )
    except Exception as exc:
        return _terminal(
            resident,
            event,
            state,
            f"E2E-14 final Browser source could not be freshly re-proven: {type(exc).__name__}: {exc}",
        )
    if not _source_exact(source, dict(meta.get("source") or {})):
        return _terminal(resident, event, state, "E2E-14 final Browser source drifted after transfer")
    if not _same_text(source_key, dict(meta.get("business_key") or {})):
        return _terminal(resident, event, state, "E2E-14 final Browser business identity drifted")

    try:
        foreground = _foreground(resident, meta, require_hwnd=False)
        key_target, key_read = _read_field(resident, foreground, _KEY_NAME, allow_read_only=True)
        if key_target.value_is_read_only is not True:
            raise _Blocked("final destination business-key field is no longer read-only")
        field_target, field_read = _read_field(resident, foreground, _FIELD_NAME, allow_read_only=True)
    except Exception as exc:
        if observations < _MAX_FINAL_OBSERVATIONS:
            time.sleep(0.03)
            resident.store.save_working_state(state)
            return None
        return _terminal(
            resident,
            event,
            state,
            f"E2E-14 saved application state could not be freshly reacquired: {type(exc).__name__}: {exc}",
        )

    key_value = str(key_read.text)
    value = str(field_read.text)
    if not _same_text(key_value, dict(meta.get("business_key") or {})) or key_value != source_key:
        return _terminal(
            resident,
            event,
            state,
            "E2E-14 final desktop business record is not the Browser source record",
        )
    expected = dict(meta.get("source", {}).get("value") or {})
    if not _same_text(value, expected):
        return _terminal(
            resident,
            event,
            state,
            "E2E-14 final saved desktop field does not match Browser source value",
        )
    title = str(foreground.title or "")
    title_saved = _title_has_saved_marker(title)
    if not title_saved:
        if observations < 6:
            time.sleep(0.03)
            resident.store.save_working_state(state)
            return None
        return _terminal(
            resident,
            event,
            state,
            "E2E-14 final application did not prove one saved-state postcondition",
        )

    meta["final_verification"] = {
        "window_handle": int(foreground.window_handle),
        "hwnd_changed": int(foreground.window_handle)
        != int(meta.get("source_window_handle") or 0),
        "business_key": _bounded_audit(key_value),
        "value": _bounded_audit(value),
        "business_key_target": _target_audit(key_target),
        "value_target": _target_audit(field_target),
        "source_exact": True,
        "pre_save_title": pre_save_title,
        "post_save_title": _bounded_audit(title),
        "title_saved_postcondition": True,
        "title_saved_transition": True,
        "readback_verified": True,
        "verified_at": utc_now(),
    }
    meta["phase"] = "complete"
    try:
        _accept_root(resident, event, meta)
    except Exception as exc:
        state.data[_STATE_KEY] = meta
        return _terminal(
            resident,
            event,
            state,
            f"E2E-14 fresh evidence could not pass Root Work acceptance: {type(exc).__name__}: {exc}",
        )
    state.data[_STATE_KEY] = meta
    state.stage = "complete"
    state.next_action = None
    state.blocked_by = None
    resident.store.save_working_state(state)
    return ResidentRunResult(
        event=event,
        execution_path=ExecutionPath.BODY,
        success=True,
        response=(
            "当前浏览器中唯一需跟进客户的跟进状态已写入当前匹配的客户管理记录，"
            "保存后已重新核对来源、客户编号和跟进状态。"
        ),
        model_invocations=0,
        reason=(
            "E2E-14 VERIFIED NARROW only after source-first exact USER Browser record evidence, "
            "fresh matching desktop business-key authority, shared durable UIA replacement ownership, "
            "one Save pointer lifecycle, causal saved-state transition, fresh cross-app readback and Root acceptance"
        ),
    )


def install_browser_desktop_record_transfer_behavior(resident) -> None:
    """Compose E2E-14 onto the existing Product Resident and shared Body truths."""
    if getattr(resident, _INSTALL_MARKER, False):
        return
    original_advance = resident._advance_event_step
    original_pointer_contract = resident._pointer_click_contract
    original_pointer_final = resident._pointer_click_final_input_precondition

    def pointer_contract(event, intent):
        expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        if intent.kind == "pointer_click" and str(expected.get("kind") or "") == "e2e14_save_click":
            args = intent.args if isinstance(intent.args, dict) else {}
            try:
                x = float(args["x_fraction"])
                y = float(args["y_fraction"])
            except (KeyError, TypeError, ValueError):
                return None, "E2E-14 Save pointer intent lost bounded coordinates"
            if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
                return None, "E2E-14 Save pointer coordinates are outside screen-fraction bounds"
            return {
                "kind": resident._POINTER_CLICK_POSTCONDITION_KIND,
                "center_x_fraction": round(x, 6),
                "center_y_fraction": round(y, 6),
                "width_fraction": resident._POINTER_CLICK_DEFAULT_REGION,
                "height_fraction": resident._POINTER_CLICK_DEFAULT_REGION,
            }, None
        return original_pointer_contract(event, intent)

    def pointer_final(event, state, intent, contract, prepared):
        expected_outcome = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        if intent.kind == "pointer_click" and str(expected_outcome.get("kind") or "") == "e2e14_save_click":
            meta = dict(state.data.get(_STATE_KEY) or {})
            try:
                (
                    foreground,
                    _key_target,
                    _key_read,
                    _field_target,
                    field_read,
                    _source_key,
                    _source_value,
                ) = _fresh_binding(
                    resident,
                    meta,
                    require_hwnd=True,
                    require_initial_value=False,
                )
                if not _same_text(
                    str(field_read.text),
                    dict(meta.get("source", {}).get("value") or {}),
                ):
                    return "E2E-14 destination value drifted before final Save input boundary"
                current_title = str(foreground.title or "")
                pre_save_title = dict(meta.get("pre_save_title") or {})
                if not pre_save_title or not _same_text(current_title, pre_save_title):
                    return "E2E-14 application title drifted after Save preparation"
                if _title_has_saved_marker(current_title):
                    return "E2E-14 application already reports saved state before final Save input boundary"
                button = resident.named_automation_control.find_unique_button(
                    process_id=int(foreground.process_id),
                    process_name=str(foreground.process_name),
                    name=_SAVE_NAME,
                )
            except Exception as exc:
                return (
                    "E2E-14 final Save authority could not be freshly proven: "
                    f"{type(exc).__name__}: {exc}"
                )
            expected_runtime = tuple(int(v) for v in expected_outcome.get("runtime_id") or ())
            if tuple(button.runtime_id) != expected_runtime:
                return "E2E-14 Save Button RuntimeId became stale at final input boundary"
            if (
                abs(float(button.center_x_fraction) - float(contract["center_x_fraction"])) > 0.002
                or abs(float(button.center_y_fraction) - float(contract["center_y_fraction"])) > 0.002
            ):
                return "E2E-14 Save Button center drifted at final input boundary"
            return None
        return original_pointer_final(event, state, intent, contract, prepared)

    def advance_event_step(event, state, *, readiness, learning_evidence, thought=None):
        handled, recovery_result = _resolve_uncertain_replacement(resident, event, state)
        if handled:
            return recovery_result
        stage = str(state.stage or "")
        if stage == "orient" and _is_request(event):
            return _begin(resident, event, state)
        handlers = {
            "e2e14_replace": _replace,
            "e2e14_verify_replacement": _verify_replacement,
            "e2e14_save_prepare": _save_prepare,
        }
        if stage in handlers:
            return handlers[stage](resident, event, state)
        meta = state.data.get(_STATE_KEY)
        phase = str(meta.get("phase") or "") if isinstance(meta, dict) else ""
        if phase == "save_dispatch":
            if stage == "native_verification":
                return _final_verify(resident, event, state)
            if stage == "native_investigation":
                execution = state.data.get(
                    getattr(resident, "_POINTER_CLICK_EXECUTION_KEY", "native_pointer_click_execution")
                )
                if (
                    isinstance(execution, dict)
                    and str(execution.get("status") or "") == "completed"
                    and execution.get("success") is True
                ):
                    return _final_verify(resident, event, state)
                return _terminal(
                    resident,
                    event,
                    state,
                    "E2E-14 Save dispatch was not proven successful; refusing a second Save",
                )
        return original_advance(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    resident._pointer_click_contract = pointer_contract
    resident._pointer_click_final_input_precondition = pointer_final
    resident._advance_event_step = advance_event_step
    setattr(resident, _INSTALL_MARKER, True)
