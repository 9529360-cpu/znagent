from __future__ import annotations

"""Bounded Browser -> Desktop corresponding-record transfer for E2E-14.

Only one literal business record identity crosses the application boundary. USER
Browser authorization and desktop/UIA mutation authority are re-established from
fresh reality at every phase; neither tab identity nor UIA RuntimeId is treated as
portable mutation authority.
"""

import hashlib
from typing import Any, Mapping

from .automation_text_content import text_sha256
from .models import ExecutionPath, ResidentRunResult, utc_now


_STATE_KEY = "e2e14_browser_desktop_record_transfer"
_INSTALL_MARKER = "_e2e14_browser_desktop_record_transfer_installed"
_FIELD_NAME = "客户状态"
_STATUS_ANCHORS = ("需跟进",)
_BROWSER_CUES = ("当前网站", "这个网站", "当前页面", "这个页面")
_DESKTOP_CUES = ("软件", "应用", "客户管理")
_TRANSFER_CUES = ("填", "同步", "更新", "写入")
_BROWSER_PROCESSES = frozenset(
    {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"}
)
_RECOVERY_STATUSES = frozenset({"started", "observed", "verified_effect"})
_MAX_CONTEXT_CHARS = 512


def install_browser_desktop_record_transfer_behavior(resident) -> None:
    """Attach the narrow E2E-14 seam to the existing Product Resident."""

    if getattr(resident, _INSTALL_MARKER, False):
        return
    original_advance = resident._advance_event_step

    def advance_event_step(event, state, *, readiness, learning_evidence, thought=None):
        stage = str(state.stage or "")
        request = _request(event)
        if stage == "orient" and request is not None:
            return _begin(resident, event, state, request=request)
        if stage == "e2e14_replace":
            handled, recovery = _recover_replacement_dispatch(
                resident,
                event,
                state,
            )
            if handled:
                return recovery
            return _replace(resident, event, state)
        if stage == "e2e14_verify":
            return _verify(resident, event, state)
        return original_advance(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    resident._advance_event_step = advance_event_step
    setattr(resident, _INSTALL_MARKER, True)


def _request(event) -> dict[str, str] | None:
    payload = getattr(event, "payload", {}) or {}
    task = " ".join(str(getattr(event, "task", "") or "").strip().split())
    lowered = task.casefold()
    if (
        str(getattr(event, "kind", "") or "").strip().lower() != "desktop_user_event"
        or not task
        or payload.get("body_action")
        or payload.get("native_action")
        or any(token in lowered for token in (".txt", "文件", "昨天"))
        or not any(cue in task for cue in _BROWSER_CUES)
        or not any(cue in task for cue in _DESKTOP_CUES)
        or "客户" not in task
        or "状态" not in task
        or not any(cue in task for cue in _TRANSFER_CUES)
        or "确认" not in task
    ):
        return None
    status = next((anchor for anchor in _STATUS_ANCHORS if anchor in task), "")
    if not status:
        return None
    if _FIELD_NAME not in task:
        return None
    return {"status_anchor": status, "field_name": _FIELD_NAME}


def _terminal(resident, event, state, reason: str):
    raw = state.data.get(_STATE_KEY)
    meta = dict(raw) if isinstance(raw, dict) else {}
    meta["failure"] = str(reason)[:2000]
    meta["failed_at"] = utc_now()
    state.data[_STATE_KEY] = meta
    resident.store.save_working_state(state)
    return resident._checkpoint_terminal_failure(event, state, reason=str(reason))


def _browser_fact(resident, *, status_anchor: str) -> tuple[dict[str, Any] | None, str | None]:
    authorization = resident.user_browser_extension.authorized_tab()
    if authorization is None:
        return None, "E2E-14 requires one current USER Browser tab explicitly authorized by the user"
    try:
        tab_id = int(authorization.tab_id)
        attached_at = str(authorization.attached_at or "").strip()
    except Exception:
        return None, "authorized USER Browser identity is malformed"
    if tab_id <= 0 or not attached_at:
        return None, "authorized USER Browser identity is incomplete"

    try:
        observed = resident._observe_authorized_anchor(status_anchor)
    except Exception as exc:
        return None, (
            "fresh authorized Browser evidence could not establish the requested record: "
            f"{type(exc).__name__}: {exc}"
        )
    current = resident.user_browser_extension.authorized_tab()
    if (
        current is None
        or int(current.tab_id) != tab_id
        or str(current.attached_at or "").strip() != attached_at
        or int(observed.get("tab_id") or 0) != tab_id
    ):
        return None, "USER Browser authorization generation changed during E2E-14 source sensing"

    context = " ".join(str(observed.get("context") or "").strip().split())
    if not context or len(context) > _MAX_CONTEXT_CHARS or context.count(status_anchor) != 1:
        return None, "authorized Browser evidence did not expose one unique requested status row"
    fields = [field for field in context.split() if field != status_anchor]
    if len(fields) != 1:
        return None, "authorized Browser row did not contain exactly one literal customer identifier"
    customer_id = fields[0].strip()
    if (
        not customer_id
        or len(customer_id) > 160
        or context.count(customer_id) != 1
        or any(ord(char) < 32 or ord(char) == 127 for char in customer_id)
    ):
        return None, "authorized Browser customer identifier is not a safe unique literal"

    digest = hashlib.sha256(context.encode("utf-8")).hexdigest()
    return {
        "customer_id": customer_id,
        "status": status_anchor,
        "tab_id": tab_id,
        "authorization_attached_at": attached_at,
        "context_sha256": digest,
        "observed_at": str(observed.get("observed_at") or utc_now()),
    }, None


def _same_browser_fact(expected: Mapping[str, Any], fresh: Mapping[str, Any]) -> bool:
    return all(
        str(fresh.get(key) or "") == str(expected.get(key) or "")
        for key in (
            "customer_id",
            "status",
            "tab_id",
            "authorization_attached_at",
            "context_sha256",
        )
    )


def _read_desktop_record(
    resident,
    *,
    customer_id: str,
    field_name: str,
    expected_process_id: int | None = None,
    expected_process_name: str | None = None,
    expected_window_handle: int | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        foreground = resident.foreground_window.probe()
    except Exception as exc:
        return None, f"fresh foreground application Sense failed: {type(exc).__name__}: {exc}"

    process_id = int(foreground.process_id or 0)
    process_name = str(foreground.process_name or "").strip().lower()
    window_handle = int(foreground.window_handle or 0)
    title = str(foreground.title or "").strip()
    if (
        process_id <= 0
        or window_handle <= 0
        or not process_name
        or process_name in _BROWSER_PROCESSES
        or not title
    ):
        return None, "E2E-14 requires one exact current non-browser desktop HWND/PID"
    if title.count(customer_id) != 1:
        return None, "current desktop record identity does not match the Browser customer literal"
    if expected_process_id is not None and process_id != int(expected_process_id):
        return None, "desktop process changed after E2E-14 record grounding"
    if expected_process_name is not None and process_name != str(expected_process_name).strip().lower():
        return None, "desktop process identity changed after E2E-14 record grounding"
    if expected_window_handle is not None and window_handle != int(expected_window_handle):
        return None, "desktop HWND changed after E2E-14 record grounding"

    try:
        edit = resident.named_automation_control.find_unique_edit(
            process_id=process_id,
            process_name=process_name,
            name=field_name,
        )
        read = resident.current_app_text_content.read_exact(
            process_id=process_id,
            process_name=process_name,
            window_handle=window_handle,
            name=field_name,
            runtime_id=tuple(edit.runtime_id),
            allow_read_only=False,
        )
    except Exception as exc:
        return None, f"fresh exact desktop field Sense failed closed: {type(exc).__name__}: {exc}"

    return {
        "process_id": process_id,
        "process_name": process_name,
        "window_handle": window_handle,
        "field_name": field_name,
        "runtime_id": list(edit.runtime_id),
        "chars": len(read.text),
        "sha256": text_sha256(read.text),
        "text": read.text,
        "read_identity_stable": bool(read.audit.get("read_identity_stable")),
        "observed_at": utc_now(),
    }, None


def _begin(resident, event, state, *, request: Mapping[str, str]):
    root = resident.work_ledger.work_item_for_event(event.event_id)
    if root is None or root.parent_work_item_id is not None:
        return _terminal(
            resident,
            event,
            state,
            "E2E-14 requires one existing Root Work owned by this Product Resident",
        )

    browser, failure = _browser_fact(resident, status_anchor=request["status_anchor"])
    if failure or browser is None:
        return _terminal(resident, event, state, failure or "Browser source is unavailable")
    desktop, failure = _read_desktop_record(
        resident,
        customer_id=str(browser["customer_id"]),
        field_name=request["field_name"],
    )
    if failure or desktop is None:
        return _terminal(resident, event, state, failure or "desktop record is unavailable")

    expected_text = str(browser["status"])
    already_satisfied = str(desktop["text"]) == expected_text
    meta = {
        "version": 1,
        "phase": "verify" if already_satisfied else "replace",
        "customer_id": str(browser["customer_id"]),
        "status": expected_text,
        "field_name": request["field_name"],
        "browser_source": dict(browser),
        "desktop_record": {
            "process_id": int(desktop["process_id"]),
            "process_name": str(desktop["process_name"]),
            "window_handle": int(desktop["window_handle"]),
            "field_name": request["field_name"],
            "initial_runtime_id": list(desktop["runtime_id"]),
            "grounded_at": utc_now(),
        },
        "source_value": {
            "chars": int(desktop["chars"]),
            "sha256": str(desktop["sha256"]),
        },
        "expected_value": {
            "chars": len(expected_text),
            "sha256": text_sha256(expected_text),
        },
        "replacement_dispatch_count": 0,
        "already_satisfied_at_start": already_satisfied,
        "started_at": utc_now(),
    }
    state.data[_STATE_KEY] = meta
    state.stage = "e2e14_verify" if already_satisfied else "e2e14_replace"
    state.next_action = (
        "freshly verify the authorized Browser record and corresponding desktop field"
        if already_satisfied
        else "freshly revalidate Browser record and exact desktop field before one guarded SetValue"
    )
    resident.store.save_working_state(state)
    return None


def _fresh_bound_evidence(
    resident,
    meta: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    expected_browser = meta.get("browser_source")
    desktop_record = meta.get("desktop_record")
    if not isinstance(expected_browser, Mapping) or not isinstance(desktop_record, Mapping):
        return None, None, "E2E-14 durable source/record identity is malformed"

    fresh_browser, failure = _browser_fact(
        resident,
        status_anchor=str(meta.get("status") or ""),
    )
    if failure or fresh_browser is None:
        return None, None, failure or "fresh Browser source is unavailable"
    if not _same_browser_fact(expected_browser, fresh_browser):
        return None, None, "authorized Browser source identity/content drifted after E2E-14 grounding"

    fresh_desktop, failure = _read_desktop_record(
        resident,
        customer_id=str(meta.get("customer_id") or ""),
        field_name=str(meta.get("field_name") or ""),
        expected_process_id=int(desktop_record.get("process_id") or 0),
        expected_process_name=str(desktop_record.get("process_name") or ""),
        expected_window_handle=int(desktop_record.get("window_handle") or 0),
    )
    if failure or fresh_desktop is None:
        return None, None, failure or "fresh desktop record is unavailable"
    return fresh_browser, fresh_desktop, None


def _recover_replacement_dispatch(resident, event, state):
    raw = state.data.get(_STATE_KEY)
    meta = dict(raw) if isinstance(raw, dict) else {}
    if str(meta.get("phase") or "") != "replace":
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
            f"could not inspect durable E2E-14 replacement ownership: {type(exc).__name__}: {exc}",
        )
    if not attempts:
        return False, None
    if len(attempts) != 1:
        return True, _terminal(
            resident,
            event,
            state,
            "multiple durable SetValue attempts exist for one E2E-14 event; refusing replay",
        )

    attempt = dict(attempts[0])
    attempt_id = str(attempt.get("attempt_id") or "").strip()
    status_before = str(attempt.get("status") or "").strip().lower()
    if not attempt_id or status_before not in _RECOVERY_STATUSES:
        return True, _terminal(
            resident,
            event,
            state,
            "durable E2E-14 replacement ownership is malformed; refusing replay",
        )

    _, fresh_desktop, failure = _fresh_bound_evidence(resident, meta)
    if failure or fresh_desktop is None:
        return True, _terminal(
            resident,
            event,
            state,
            failure or "fresh E2E-14 recovery evidence is unavailable",
        )
    expected = dict(meta.get("expected_value") or {})
    if (
        int(fresh_desktop["chars"]) != int(expected.get("chars") or -1)
        or str(fresh_desktop["sha256"]) != str(expected.get("sha256") or "")
    ):
        return True, _terminal(
            resident,
            event,
            state,
            "unresolved E2E-14 SetValue does not match the old expected result in fresh reality; refusing replay",
        )

    if status_before in {"started", "observed"} and not resident.body.resolve_uncertain_attempt(
        attempt_id,
        event_id=event.event_id,
        status="verified_effect",
    ):
        return True, _terminal(
            resident,
            event,
            state,
            "durable E2E-14 SetValue attempt could not be resolved from verified effect",
        )

    meta["replacement_recovery"] = {
        "attempt_id": attempt_id,
        "status_before": status_before,
        "status_after": "verified_effect",
        "runtime_id": list(fresh_desktop["runtime_id"]),
        "additional_replacement_dispatches": 0,
        "recovered_at": utc_now(),
    }
    meta["side_effect_attempt_id"] = attempt_id
    meta["phase"] = "verify"
    state.data[_STATE_KEY] = meta
    state.stage = "e2e14_verify"
    state.next_action = "freshly verify source and corresponding desktop record after SetValue recovery"
    state.blocked_by = None
    resident.store.save_working_state(state)
    return True, None


def _replace(resident, event, state):
    raw = state.data.get(_STATE_KEY)
    meta = dict(raw) if isinstance(raw, dict) else {}
    _, fresh_desktop, failure = _fresh_bound_evidence(resident, meta)
    if failure or fresh_desktop is None:
        return _terminal(resident, event, state, failure or "fresh E2E-14 evidence is unavailable")

    expected = dict(meta.get("expected_value") or {})
    source = dict(meta.get("source_value") or {})
    current_chars = int(fresh_desktop["chars"])
    current_sha = str(fresh_desktop["sha256"])
    result_matches = bool(
        current_chars == int(expected.get("chars") or -1)
        and current_sha == str(expected.get("sha256") or "")
    )
    if result_matches:
        meta["phase"] = "verify"
        meta["already_satisfied_before_dispatch"] = True
        state.data[_STATE_KEY] = meta
        state.stage = "e2e14_verify"
        state.next_action = "freshly verify source and corresponding desktop record without mutation"
        resident.store.save_working_state(state)
        return None

    source_chars = source.get("chars")
    if (
        source_chars is None
        or current_chars != int(source_chars)
        or current_sha != str(source.get("sha256") or "")
    ):
        return _terminal(
            resident,
            event,
            state,
            "desktop customer-status value drifted before E2E-14 mutation; stale source rejected",
        )
    if int(meta.get("replacement_dispatch_count") or 0) != 0:
        return _terminal(
            resident,
            event,
            state,
            "E2E-14 state already records a SetValue dispatch; refusing any second mutation",
        )

    expected_text = str(meta.get("status") or "")
    body_result = resident.body.act(
        "automation_value_replace",
        event_id=event.event_id,
        process_id=int(fresh_desktop["process_id"]),
        process_name=str(fresh_desktop["process_name"]),
        window_handle=int(fresh_desktop["window_handle"]),
        name=str(meta.get("field_name") or ""),
        runtime_id=list(fresh_desktop["runtime_id"]),
        source_chars=current_chars,
        source_sha256=current_sha,
        replacement_text=expected_text,
        result_chars=len(expected_text),
        result_sha256=text_sha256(expected_text),
    )
    safe = dict(body_result.data or {})
    meta["replacement_body_result"] = {
        key: value
        for key, value in safe.items()
        if key not in {"replacement_text", "text", "content", "output"}
    }
    attempt_id = str(safe.get("side_effect_attempt_id") or "").strip()
    if attempt_id:
        meta["side_effect_attempt_id"] = attempt_id
    state.data[_STATE_KEY] = meta

    if body_result.success and (
        not attempt_id
        or safe.get("mutation_dispatched") is not True
        or safe.get("postcondition_verified") is not True
    ):
        return _terminal(
            resident,
            event,
            state,
            "successful E2E-14 SetValue returned without complete durable dispatch/postcondition evidence; refusing replay",
        )

    if not body_result.success:
        if bool(safe.get("side_effect_uncertain")):
            _, after, after_failure = _fresh_bound_evidence(resident, meta)
            if after_failure or after is None:
                return _terminal(
                    resident,
                    event,
                    state,
                    after_failure or "SetValue became uncertain and fresh evidence is unavailable",
                )
            if (
                int(after["chars"]) == int(expected.get("chars") or -1)
                and str(after["sha256"]) == str(expected.get("sha256") or "")
                and attempt_id
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
                    "SetValue became uncertain and fresh source/record reality did not independently prove the exact expected effect; refusing replay",
                )
        elif bool(safe.get("mutation_dispatched")):
            return _terminal(
                resident,
                event,
                state,
                body_result.error or "SetValue was dispatched but exact post-read did not verify; refusing replay",
            )
        else:
            return _terminal(
                resident,
                event,
                state,
                body_result.error or "exact E2E-14 SetValue failed before a verified mutation",
            )

    meta["replacement_dispatch_count"] = 1
    meta["replacement_runtime_id"] = list(fresh_desktop["runtime_id"])
    meta["phase"] = "verify"
    state.data[_STATE_KEY] = meta
    state.stage = "e2e14_verify"
    state.next_action = "freshly verify authorized Browser source and exact corresponding desktop record"
    resident.store.save_working_state(state)
    return None


def _verify(resident, event, state):
    raw = state.data.get(_STATE_KEY)
    meta = dict(raw) if isinstance(raw, dict) else {}
    fresh_browser, fresh_desktop, failure = _fresh_bound_evidence(resident, meta)
    if failure or fresh_browser is None or fresh_desktop is None:
        return _terminal(resident, event, state, failure or "fresh E2E-14 verification evidence is unavailable")

    expected = dict(meta.get("expected_value") or {})
    if (
        int(fresh_desktop["chars"]) != int(expected.get("chars") or -1)
        or str(fresh_desktop["sha256"]) != str(expected.get("sha256") or "")
    ):
        return _terminal(
            resident,
            event,
            state,
            "fresh corresponding desktop record does not contain the exact Browser status after E2E-14",
        )

    attempt_id = str(meta.get("side_effect_attempt_id") or "").strip()
    if attempt_id and not resident.body.resolve_uncertain_attempt(
        attempt_id,
        event_id=event.event_id,
        status="verified_effect",
    ):
        return _terminal(
            resident,
            event,
            state,
            "verified E2E-14 SetValue could not close its durable side-effect ownership",
        )

    meta["final_verification"] = {
        "customer_id": str(fresh_browser["customer_id"]),
        "status": str(fresh_browser["status"]),
        "tab_id": int(fresh_browser["tab_id"]),
        "authorization_attached_at": str(fresh_browser["authorization_attached_at"]),
        "context_sha256": str(fresh_browser["context_sha256"]),
        "process_id": int(fresh_desktop["process_id"]),
        "process_name": str(fresh_desktop["process_name"]),
        "window_handle": int(fresh_desktop["window_handle"]),
        "runtime_id": list(fresh_desktop["runtime_id"]),
        "field_name": str(meta.get("field_name") or ""),
        "chars": int(fresh_desktop["chars"]),
        "sha256": str(fresh_desktop["sha256"]),
        "read_identity_stable": bool(fresh_desktop["read_identity_stable"]),
        "verified_at": utc_now(),
    }
    meta["phase"] = "complete"
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
            f"已把授权浏览器记录对应客户 {meta.get('customer_id')} 的状态同步到当前桌面记录，"
            "并用 fresh Browser + UIA 证据确认记录身份和值一致。"
        ),
        model_invocations=0,
        reason=(
            "E2E-14 VERIFIED NARROW only after same-generation authorized Browser record sensing, "
            "literal customer identity carryover, fresh exact desktop HWND/PID + semantic Edit grounding, "
            "guarded non-replayable ValuePattern replacement when needed, and fresh same-record readback"
        ),
    )
