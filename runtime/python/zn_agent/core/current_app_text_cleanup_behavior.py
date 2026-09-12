from __future__ import annotations

"""Resident-owned bounded current-app text cleanup representative path (E2E-13)."""

import time
import uuid
from dataclasses import asdict
from typing import Any

from .action import NativeActionIntent
from .automation_text_content import NativeAutomationTextContentSense, text_sha256
from .current_app_text_cleanup_goal import (
    CURRENT_APP_TEXT_CLEANUP_GOAL_KEY,
    CurrentAppTextCleanupGoal,
    current_app_text_cleanup_goal,
    deterministic_text_cleanup,
)
from .models import ExecutionPath, ResidentRunResult, utc_now


_STATE_KEY = "e2e13_current_app_text_cleanup"
_INSTALL_MARKER = "_e2e13_current_app_text_cleanup_installed"
_MAX_REGROUNDS = 3
_MAX_FINAL_OBSERVATIONS = 40
_BROWSER_PROCESSES = frozenset(
    {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"}
)


def _same_process(foreground, meta: dict[str, Any], *, require_old_hwnd: bool) -> bool:
    same = bool(
        int(foreground.process_id) == int(meta.get("process_id") or 0)
        and str(foreground.process_name or "").strip().lower()
        == str(meta.get("process_name") or "").strip().lower()
    )
    if require_old_hwnd:
        same = same and int(foreground.window_handle or 0) == int(meta.get("source_window_handle") or 0)
    return same


def _safe_goal(goal: CurrentAppTextCleanupGoal) -> dict[str, str]:
    return goal.to_dict()


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
    state.data.setdefault(_STATE_KEY, {})["failure"] = str(reason)[:2000]
    resident.store.save_working_state(state)
    return resident._checkpoint_terminal_failure(event, state, reason=str(reason))


def _refresh_source_evidence(
    resident,
    event,
    state,
    meta: dict[str, Any],
    *,
    reason: str,
):
    foreground = resident.foreground_window.probe()
    if not _same_process(foreground, meta, require_old_hwnd=True):
        return None, _terminal(
            resident,
            event,
            state,
            "foreground/process drifted before current-app cleanup mutation",
        )
    goal = CurrentAppTextCleanupGoal(**dict(meta["goal"]))
    edit = resident.named_automation_control.find_unique_edit(
        process_id=int(foreground.process_id),
        process_name=str(foreground.process_name),
        name=goal.field_name,
    )
    read = resident.current_app_text_content.read_exact(
        process_id=int(foreground.process_id),
        process_name=str(foreground.process_name),
        window_handle=int(foreground.window_handle),
        name=goal.field_name,
        runtime_id=tuple(edit.runtime_id),
        allow_read_only=False,
    )
    transformed = deterministic_text_cleanup(read.text)
    reground_count = int(meta.get("reground_count") or 0) + 1
    if reground_count > _MAX_REGROUNDS:
        return None, _terminal(
            resident,
            event,
            state,
            "current-app text changed or rebuilt too many times before mutation",
        )
    meta.update(
        {
            "source_target": _target_audit(edit),
            "source_evidence": {
                **read.audit,
                "line_count": transformed.source_line_count,
                "semantic_target_name": goal.field_name,
                "reason": reason,
            },
            "transform": transformed.audit,
            "reground_count": reground_count,
            "last_regrounded_at": utc_now(),
        }
    )
    state.data[_STATE_KEY] = meta
    state.stage = "e2e13_replace"
    state.next_action = "use fresh exact source evidence for bounded ValuePattern replacement"
    resident.store.save_working_state(state)
    return transformed, None


def _begin(resident, event, state, goal: CurrentAppTextCleanupGoal):
    root = resident.work_ledger.work_item_for_event(event.event_id)
    if root is None or root.parent_work_item_id is not None:
        return _terminal(
            resident,
            event,
            state,
            "E2E-13 current-app cleanup requires one existing Root Work owned by this Product Resident",
        )
    foreground = resident.foreground_window.probe()
    process_name = str(foreground.process_name or "").strip().lower()
    if (
        int(foreground.window_handle or 0) <= 0
        or process_name in _BROWSER_PROCESSES
    ):
        return _terminal(
            resident,
            event,
            state,
            "E2E-13 requires one foreground non-browser desktop application",
        )

    edit = resident.named_automation_control.find_unique_edit(
        process_id=int(foreground.process_id),
        process_name=str(foreground.process_name),
        name=goal.field_name,
    )
    # Saving must already be uniquely groundable before any edit mutation occurs.
    save_button = resident.named_automation_control.find_unique_button(
        process_id=int(foreground.process_id),
        process_name=str(foreground.process_name),
        name=goal.save_button_name,
    )
    read = resident.current_app_text_content.read_exact(
        process_id=int(foreground.process_id),
        process_name=str(foreground.process_name),
        window_handle=int(foreground.window_handle),
        name=goal.field_name,
        runtime_id=tuple(edit.runtime_id),
        allow_read_only=False,
    )
    transformed = deterministic_text_cleanup(read.text)

    meta = {
        "version": 1,
        "goal": _safe_goal(goal),
        "phase": "replace",
        "process_id": int(foreground.process_id),
        "process_name": process_name,
        "source_window_handle": int(foreground.window_handle),
        "source_window_title": str(foreground.title or "")[:240],
        "source_target": _target_audit(edit),
        "source_evidence": {
            **read.audit,
            "line_count": transformed.source_line_count,
            "semantic_target_name": goal.field_name,
        },
        "transform": transformed.audit,
        "initial_save_target": {
            "runtime_id": list(save_button.runtime_id),
            "semantic_name": goal.save_button_name,
            "captured_at": save_button.captured_at,
        },
        "reground_count": 0,
        "save_dispatch_count": 0,
        "final_observation_count": 0,
        "started_at": utc_now(),
    }
    event.payload[CURRENT_APP_TEXT_CLEANUP_GOAL_KEY] = goal.to_dict()
    state.data[_STATE_KEY] = meta
    state.stage = "e2e13_replace"
    state.next_action = "freshly revalidate source identity/content then perform exact bounded replacement"
    resident.store.save_working_state(state)
    return None


def _replace(resident, event, state):
    meta = dict(state.data.get(_STATE_KEY) or {})
    goal = CurrentAppTextCleanupGoal(**dict(meta["goal"]))
    foreground = resident.foreground_window.probe()
    if not _same_process(foreground, meta, require_old_hwnd=True):
        return _terminal(resident, event, state, "foreground/process drifted before replacement")

    edit = resident.named_automation_control.find_unique_edit(
        process_id=int(foreground.process_id),
        process_name=str(foreground.process_name),
        name=goal.field_name,
    )
    prior_runtime = tuple(int(v) for v in meta.get("source_target", {}).get("runtime_id") or ())
    if tuple(edit.runtime_id) != prior_runtime:
        _, terminal = _refresh_source_evidence(
            resident,
            event,
            state,
            meta,
            reason="RuntimeId changed before mutation; old evidence rejected",
        )
        return terminal

    read = resident.current_app_text_content.read_exact(
        process_id=int(foreground.process_id),
        process_name=str(foreground.process_name),
        window_handle=int(foreground.window_handle),
        name=goal.field_name,
        runtime_id=tuple(edit.runtime_id),
        allow_read_only=False,
    )
    current_hash = text_sha256(read.text)
    source = dict(meta.get("source_evidence") or {})
    if len(read.text) != int(source.get("chars") or -1) or current_hash != str(source.get("sha256") or ""):
        _, terminal = _refresh_source_evidence(
            resident,
            event,
            state,
            meta,
            reason="content drifted before mutation; stale transform rejected",
        )
        return terminal

    transformed = deterministic_text_cleanup(read.text)
    expected = dict(meta.get("transform") or {})
    if (
        transformed.source_sha256 != str(expected.get("source_sha256") or "")
        or transformed.result_sha256 != str(expected.get("result_sha256") or "")
        or transformed.result_chars != int(expected.get("result_chars") or -1)
    ):
        return _terminal(resident, event, state, "deterministic transform no longer matches fresh source evidence")

    body_result = resident.body.act(
        "automation_value_replace",
        event_id=event.event_id,
        process_id=int(foreground.process_id),
        process_name=str(foreground.process_name),
        window_handle=int(foreground.window_handle),
        name=goal.field_name,
        runtime_id=list(edit.runtime_id),
        source_chars=transformed.source_chars,
        source_sha256=transformed.source_sha256,
        replacement_text=transformed.result_text,
        result_chars=transformed.result_chars,
        result_sha256=transformed.result_sha256,
    )
    safe_result = dict(body_result.data or {})
    meta["replacement_body_result"] = {
        key: value
        for key, value in safe_result.items()
        if key not in {"replacement_text", "text", "content", "output"}
    }
    state.data[_STATE_KEY] = meta

    if not body_result.success:
        if bool(safe_result.get("side_effect_uncertain")):
            attempt_id = str(safe_result.get("side_effect_attempt_id") or "")
            fresh_edit = resident.named_automation_control.find_unique_edit(
                process_id=int(foreground.process_id),
                process_name=str(foreground.process_name),
                name=goal.field_name,
            )
            fresh = resident.current_app_text_content.read_exact(
                process_id=int(foreground.process_id),
                process_name=str(foreground.process_name),
                window_handle=int(foreground.window_handle),
                name=goal.field_name,
                runtime_id=tuple(fresh_edit.runtime_id),
                allow_read_only=False,
            )
            if (
                len(fresh.text) == transformed.result_chars
                and text_sha256(fresh.text) == transformed.result_sha256
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
                    "replacement dispatch became uncertain and fresh reality did not independently prove the expected effect; refusing replay",
                )
        elif bool(safe_result.get("mutation_dispatched")):
            return _terminal(
                resident,
                event,
                state,
                body_result.error or "replacement was dispatched but exact post-read did not verify; refusing replay",
            )
        else:
            return _terminal(
                resident,
                event,
                state,
                body_result.error or "exact replacement failed before a verified mutation",
            )

    meta["phase"] = "verify_replacement"
    meta["replacement_verified_at"] = utc_now()
    state.data[_STATE_KEY] = meta
    state.stage = "e2e13_verify_replacement"
    state.next_action = "freshly reread the exact edit before save"
    resident.store.save_working_state(state)
    return None


def _verify_replacement(resident, event, state):
    meta = dict(state.data.get(_STATE_KEY) or {})
    goal = CurrentAppTextCleanupGoal(**dict(meta["goal"]))
    expected = dict(meta.get("transform") or {})
    foreground = resident.foreground_window.probe()
    if not _same_process(foreground, meta, require_old_hwnd=True):
        return _terminal(resident, event, state, "foreground/process drifted after replacement before save")
    edit = resident.named_automation_control.find_unique_edit(
        process_id=int(foreground.process_id),
        process_name=str(foreground.process_name),
        name=goal.field_name,
    )
    fresh = resident.current_app_text_content.read_exact(
        process_id=int(foreground.process_id),
        process_name=str(foreground.process_name),
        window_handle=int(foreground.window_handle),
        name=goal.field_name,
        runtime_id=tuple(edit.runtime_id),
        allow_read_only=False,
    )
    digest = text_sha256(fresh.text)
    if len(fresh.text) != int(expected.get("result_chars") or -1) or digest != str(expected.get("result_sha256") or ""):
        return _terminal(resident, event, state, "fresh post-replacement UIA Value did not match deterministic expected result")
    meta["replacement_fresh_readback"] = {
        **fresh.audit,
        "semantic_target_name": goal.field_name,
    }
    meta["phase"] = "save_prepare"
    state.data[_STATE_KEY] = meta
    state.stage = "e2e13_save_prepare"
    state.next_action = "freshly reacquire exact save Button and enter non-replayable pointer lifecycle"
    resident.store.save_working_state(state)
    return None


def _save_prepare(resident, event, state):
    meta = dict(state.data.get(_STATE_KEY) or {})
    goal = CurrentAppTextCleanupGoal(**dict(meta["goal"]))
    foreground = resident.foreground_window.probe()
    if not _same_process(foreground, meta, require_old_hwnd=True):
        return _terminal(resident, event, state, "foreground/process drifted before Save authority")
    button = resident.named_automation_control.find_unique_button(
        process_id=int(foreground.process_id),
        process_name=str(foreground.process_name),
        name=goal.save_button_name,
    )
    meta["save_target"] = {
        "runtime_id": list(button.runtime_id),
        "semantic_name": goal.save_button_name,
        "center_x_fraction": float(button.center_x_fraction),
        "center_y_fraction": float(button.center_y_fraction),
        "captured_at": button.captured_at,
    }
    meta["phase"] = "save_dispatch"
    state.data[_STATE_KEY] = meta
    intent = NativeActionIntent(
        intent_id=f"e2e13-save-{uuid.uuid4().hex[:12]}",
        event_id=event.event_id,
        kind="pointer_click",
        args={
            "x_fraction": float(button.center_x_fraction),
            "y_fraction": float(button.center_y_fraction),
            "button": "left",
        },
        expected_outcome={
            "kind": "e2e13_save_click",
            "button_name": goal.save_button_name,
            "runtime_id": list(button.runtime_id),
            "window_handle": int(foreground.window_handle),
        },
        reason="E2E-13 save uses the existing durable pointer-click non-replay lifecycle after fresh exact Button grounding",
        source="e2e13_current_app_text_cleanup",
    )
    resident._begin_native_action_cycle(event, state, intent)
    resident.store.save_working_state(state)
    return None


def _canonical_windows_text(value: str) -> str:
    normalized = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return "\r\n".join(normalized.split("\n"))


def _result_field_name(goal: CurrentAppTextCleanupGoal) -> str:
    if goal.save_button_name == "保存":
        return "保存内容"
    if goal.save_button_name.casefold() == "save":
        return "Saved content"
    return f"{goal.save_button_name}内容"


def _final_verify(resident, event, state):
    meta = dict(state.data.get(_STATE_KEY) or {})
    goal = CurrentAppTextCleanupGoal(**dict(meta["goal"]))
    expected = dict(meta.get("transform") or {})
    execution = state.data.get(getattr(resident, "_POINTER_CLICK_EXECUTION_KEY", "native_pointer_click_execution"))
    if not (
        isinstance(execution, dict)
        and str(execution.get("status") or "") == "completed"
        and execution.get("success") is True
    ):
        return _terminal(resident, event, state, "Save pointer dispatch is not durably proven successful; refusing replay")
    if int(meta.get("save_dispatch_count") or 0) == 0:
        meta["save_dispatch_count"] = 1
        meta["save_action_id"] = str(execution.get("action_id") or "")

    foreground = resident.foreground_window.probe()
    observations = int(meta.get("final_observation_count") or 0) + 1
    meta["final_observation_count"] = observations
    state.data[_STATE_KEY] = meta

    if (
        int(foreground.process_id) != int(meta.get("process_id") or 0)
        or str(foreground.process_name or "").strip().lower() != str(meta.get("process_name") or "").strip().lower()
    ):
        return _terminal(resident, event, state, "Save result foreground changed to a different process")
    if int(foreground.window_handle or 0) == int(meta.get("source_window_handle") or 0):
        if observations >= _MAX_FINAL_OBSERVATIONS:
            return _terminal(resident, event, state, "Save did not produce a fresh same-process result HWND")
        time.sleep(0.03)
        resident.store.save_working_state(state)
        return None

    title = str(foreground.title or "")
    title_ok = bool(goal.field_name in title and ("已保存" in title or "saved" in title.casefold()))
    if not title_ok:
        if observations < 6:
            time.sleep(0.03)
            resident.store.save_working_state(state)
            return None
        return _terminal(resident, event, state, "fresh result window title did not satisfy the saved-work-record postcondition")

    candidates = resident.current_app_text_content.list_value_edits(
        process_id=int(foreground.process_id),
        process_name=str(foreground.process_name),
        window_handle=int(foreground.window_handle),
    )
    result_name = _result_field_name(goal)
    matches = [candidate for candidate in candidates if candidate.name == result_name]
    if len(matches) != 1:
        if observations < 6:
            time.sleep(0.03)
            resident.store.save_working_state(state)
            return None
        return _terminal(
            resident,
            event,
            state,
            f"fresh result window did not expose exactly one {result_name!r} UIA Edit",
        )
    target = matches[0]
    final_read = resident.current_app_text_content.read_exact(
        process_id=int(foreground.process_id),
        process_name=str(foreground.process_name),
        window_handle=int(foreground.window_handle),
        name=result_name,
        runtime_id=tuple(target.runtime_id),
        allow_read_only=True,
    )
    canonical = _canonical_windows_text(final_read.text)
    final_hash = text_sha256(canonical)
    if (
        len(canonical) != int(expected.get("result_chars") or -1)
        or final_hash != str(expected.get("result_sha256") or "")
    ):
        return _terminal(resident, event, state, "fresh result-window application readback did not match deterministic expected text")

    meta["final_verification"] = {
        "new_window_handle": int(foreground.window_handle),
        "same_process": True,
        "title": title[:240],
        "title_postcondition": True,
        "semantic_target_name": result_name,
        "chars": len(canonical),
        "sha256": final_hash,
        "line_count": int(expected.get("result_line_count") or 0),
        "target": _target_audit(target),
        "read_identity_stable": True,
        "verified_at": utc_now(),
    }
    meta["phase"] = "complete"
    state.data[_STATE_KEY] = meta
    state.stage = "complete"
    state.next_action = None
    state.blocked_by = None
    resident.store.save_working_state(state)
    removed_blank = int(expected.get("removed_blank_line_count") or 0)
    removed_duplicate = int(expected.get("removed_duplicate_line_count") or 0)
    return ResidentRunResult(
        event=event,
        execution_path=ExecutionPath.BODY,
        success=True,
        response=(
            f"当前应用中的{goal.field_name}已按确定性规则整理并保存；"
            f"fresh 结果窗口已验证 {int(expected.get('result_line_count') or 0)} 行，"
            f"移除空行 {removed_blank}、重复行 {removed_duplicate}。"
        ),
        model_invocations=0,
        reason=(
            "E2E-13 VERIFIED NARROW only after fresh exact UIA source read, deterministic cleanup, "
            "guarded exact ValuePattern replacement, one durable Save pointer dispatch, and fresh "
            "same-process new-window application readback"
        ),
    )


def install_current_app_text_cleanup_behavior(resident) -> None:
    """Attach E2E-13 to the one existing Product Resident/Body lifecycle."""
    if getattr(resident, _INSTALL_MARKER, False):
        return
    resident.current_app_text_content = NativeAutomationTextContentSense()

    original_advance = resident._advance_event_step
    original_pointer_contract = resident._pointer_click_contract
    original_pointer_final = resident._pointer_click_final_input_precondition

    def pointer_contract(event, intent):
        expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        if intent.kind == "pointer_click" and str(expected.get("kind") or "") == "e2e13_save_click":
            args = intent.args if isinstance(intent.args, dict) else {}
            try:
                x = float(args["x_fraction"])
                y = float(args["y_fraction"])
            except (KeyError, TypeError, ValueError):
                return None, "E2E-13 Save pointer intent lost its bounded coordinates"
            if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
                return None, "E2E-13 Save pointer coordinates are outside the screen fraction bound"
            return {
                "kind": resident._POINTER_CLICK_POSTCONDITION_KIND,
                "center_x_fraction": round(x, 6),
                "center_y_fraction": round(y, 6),
                "width_fraction": resident._POINTER_CLICK_DEFAULT_REGION,
                "height_fraction": resident._POINTER_CLICK_DEFAULT_REGION,
            }, None
        return original_pointer_contract(event, intent)

    def pointer_final(event, state, intent, contract, prepared):
        expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        if intent.kind == "pointer_click" and str(expected.get("kind") or "") == "e2e13_save_click":
            meta = dict(state.data.get(_STATE_KEY) or {})
            goal = CurrentAppTextCleanupGoal(**dict(meta.get("goal") or {}))
            foreground = resident.foreground_window.probe()
            if not _same_process(foreground, meta, require_old_hwnd=True):
                return "E2E-13 Save foreground/HWND/process drifted at final input boundary"
            fresh = resident.named_automation_control.find_unique_button(
                process_id=int(foreground.process_id),
                process_name=str(foreground.process_name),
                name=goal.save_button_name,
            )
            expected_runtime = tuple(int(v) for v in expected.get("runtime_id") or ())
            if tuple(fresh.runtime_id) != expected_runtime:
                return "E2E-13 Save Button RuntimeId became stale at final input boundary"
            if (
                abs(float(fresh.center_x_fraction) - float(contract["center_x_fraction"])) > 0.002
                or abs(float(fresh.center_y_fraction) - float(contract["center_y_fraction"])) > 0.002
            ):
                return "E2E-13 Save Button center drifted at final input boundary"
            return None
        return original_pointer_final(event, state, intent, contract, prepared)

    def advance_event_step(event, state, *, readiness, learning_evidence, thought=None):
        stage = str(state.stage or "")
        request = current_app_text_cleanup_goal(event)
        if stage == "orient" and request is not None:
            return _begin(resident, event, state, request)
        if stage == "e2e13_replace":
            return _replace(resident, event, state)
        if stage == "e2e13_verify_replacement":
            return _verify_replacement(resident, event, state)
        if stage == "e2e13_save_prepare":
            return _save_prepare(resident, event, state)

        meta = state.data.get(_STATE_KEY)
        phase = str(meta.get("phase") or "") if isinstance(meta, dict) else ""
        if phase == "save_dispatch":
            if stage == "native_verification":
                return _final_verify(resident, event, state)
            if stage == "native_investigation":
                execution = state.data.get(getattr(resident, "_POINTER_CLICK_EXECUTION_KEY", "native_pointer_click_execution"))
                if isinstance(execution, dict) and str(execution.get("status") or "") == "completed" and execution.get("success") is True:
                    return _final_verify(resident, event, state)
                return _terminal(
                    resident,
                    event,
                    state,
                    "Save dispatch was not proven successful; E2E-13 will not click Save again",
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
