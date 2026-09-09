from __future__ import annotations

"""Bounded recovery of one active desktop goal across one safe Windows modal.

This composes onto the existing Resident and existing pointer lifecycle. It does
not introduce a dialog agent, router, store, scheduler, Work status, input path,
or completion truth. Parent, modal, and post-dismiss control authority are each
established independently from fresh evidence.
"""

import uuid
from dataclasses import asdict
from typing import Any

from .action import NativeActionIntent
from .desktop_task_goal import desktop_task_goal
from .modal_window_sense import (
    NativeModalWindowSense,
    WINDOW_INTERACTION_BLOCKED_BY_MODAL,
    WINDOW_INTERACTION_READY,
    select_safe_modal_action,
)
from .models import utc_now


_STATE_KEY = "resident_desktop_modal_recovery"
_INSTALL_MARKER = "_zn_desktop_modal_recovery_behavior_installed"
_MODAL_DISMISS_KIND = "desktop_modal_safe_dismissed"
_MAX_RECOVERY_OBSERVATIONS = 12


def install_desktop_modal_recovery_behavior(resident) -> None:
    if getattr(resident, _INSTALL_MARKER, False):
        return

    resident.modal_window = NativeModalWindowSense()
    original_investigation = resident._desktop_task_investigation
    original_deliberation = resident._deliberation_step
    original_pointer_contract = resident._pointer_click_contract
    original_final_precondition = resident._pointer_click_final_input_precondition
    original_verify_pointer = resident._verify_pointer_click_effect

    def desktop_task_investigation(event, state, *, readiness, thought=None):
        if desktop_task_goal(event) is None:
            return original_investigation(event, state, readiness=readiness, thought=thought)
        progress = _progress(state)
        phase = str(progress.get("phase") or "")
        if phase == "stale_modal_target_blocked":
            return resident._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "the admitted modal Button changed before input; no dialog input was sent and "
                    "this bounded slice fails closed instead of silently retargeting"
                ),
            )
        if phase == "dismiss_dispatched":
            return _recover_exact_parent(
                resident,
                event,
                state,
                readiness=readiness,
                thought=thought,
                original_investigation=original_investigation,
            )

        parent = _parent(progress)
        if parent is not None:
            try:
                foreground = resident.foreground_window.probe()
            except Exception as exc:
                return resident._fail_composite_goal_investigation(
                    event,
                    state,
                    reason=(
                        "fresh foreground Sense failed while preserving exact desktop parent "
                        f"authority: {type(exc).__name__}: {exc}"
                    ),
                )
            current_hwnd = int(getattr(foreground, "window_handle", 0) or 0)
            if current_hwnd > 0 and current_hwnd != int(parent["window_handle"]):
                return _investigate_interruption(
                    resident,
                    event,
                    state,
                    progress=progress,
                    parent=parent,
                )

        result = original_investigation(event, state, readiness=readiness, thought=thought)
        _remember_parent_and_target(resident, state)
        return result

    def deliberation_step(event, state, *, readiness, learning_evidence, thought=None):
        progress = _progress(state)
        if desktop_task_goal(event) is None or progress.get("phase") != "modal_ready":
            return original_deliberation(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )
        modal = progress.get("modal")
        parent = _parent(progress)
        if not isinstance(modal, dict) or parent is None:
            return resident._fail_composite_goal_investigation(
                event,
                state,
                reason="modal recovery lost exact dialog/parent evidence before action admission",
            )
        if int(progress.get("dispatch_count") or 0) != 0:
            return resident._fail_composite_goal_investigation(
                event,
                state,
                reason="modal recovery already dispatched input and will not replay it",
            )
        runtime_id = [int(v) for v in modal.get("safe_action_runtime_id") or ()]
        if not runtime_id:
            return resident._fail_composite_goal_investigation(
                event,
                state,
                reason="modal recovery lost exact safe Button RuntimeId authority",
            )
        intent = NativeActionIntent(
            intent_id=f"desktop-modal-{uuid.uuid4().hex[:12]}",
            event_id=event.event_id,
            kind="pointer_click",
            args={
                "x_fraction": float(modal["safe_action_center_x_fraction"]),
                "y_fraction": float(modal["safe_action_center_y_fraction"]),
                "button": "left",
                "target_runtime_id": runtime_id,
            },
            expected_outcome={
                "kind": _MODAL_DISMISS_KIND,
                "parent_hwnd": int(parent["window_handle"]),
                "parent_process_id": int(parent["process_id"]),
                "parent_process_name": str(parent["process_name"]),
                "dialog_hwnd": int(modal["dialog_hwnd"]),
                "owner_hwnd": int(modal["owner_hwnd"]),
                "root_owner_hwnd": int(modal["root_owner_hwnd"]),
                "parent_root_owner_hwnd": int(modal["parent_root_owner_hwnd"]),
                "safe_action_name": str(modal["safe_action_name"]),
                "safe_action_runtime_id": runtime_id,
                "safe_action_center_x_fraction": float(modal["safe_action_center_x_fraction"]),
                "safe_action_center_y_fraction": float(modal["safe_action_center_y_fraction"]),
            },
            reason=(
                "fresh Win32 owner/root-owner plus UIA IsModal/BlockedByModalWindow evidence proved "
                "one exact blocking modal, and deterministic semantics proved one non-destructive "
                "defer/continue action contained by that exact dialog"
            ),
            source="resident_choice",
        )
        if resident._action_blocked_by_current_evidence(event, state, intent):
            return resident._checkpoint_terminal_failure(
                event,
                state,
                reason="the same modal input is blocked by unchanged evidence; refusing replay",
            )
        resident._begin_native_action_cycle(event, state, intent)
        progress["modal_intent_id"] = intent.intent_id
        progress["updated_at"] = utc_now()
        state.data[_STATE_KEY] = progress
        resident.store.save_working_state(state)
        return None

    def pointer_click_contract(event, intent):
        if _is_modal_intent(event, intent):
            return {
                "kind": resident._POINTER_CLICK_POSTCONDITION_KIND,
                "center_x_fraction": float(intent.args["x_fraction"]),
                "center_y_fraction": float(intent.args["y_fraction"]),
                "width_fraction": resident._POINTER_CLICK_DEFAULT_REGION,
                "height_fraction": resident._POINTER_CLICK_DEFAULT_REGION,
            }, None
        return original_pointer_contract(event, intent)

    def final_input_precondition(event, state, intent, contract, prepared):
        if not _is_modal_intent(event, intent):
            return original_final_precondition(event, state, intent, contract, prepared)
        progress = _progress(state)
        admitted = progress.get("modal")
        expected = intent.expected_outcome
        if not isinstance(admitted, dict) or not isinstance(expected, dict):
            return "modal action lost admitted exact dialog evidence before input"
        try:
            fresh = resident.modal_window.probe(
                parent_hwnd=int(expected["parent_hwnd"]),
                parent_process_id=int(expected["parent_process_id"]),
                parent_process_name=str(expected["parent_process_name"]),
            )
            if fresh is None:
                raise RuntimeError("exact modal disappeared before admitted input")
            fresh_button, failure = select_safe_modal_action(fresh, user_goal=str(event.task or ""))
            if fresh_button is None:
                raise RuntimeError(str(failure or "fresh modal no longer has one safe action"))
            if not _same_modal_authority(admitted, expected, fresh, fresh_button):
                raise RuntimeError("exact modal/Button authority changed before input")
        except Exception as exc:
            progress["phase"] = "stale_modal_target_blocked"
            progress["stale_target_error"] = f"{type(exc).__name__}: {exc}"
            progress["updated_at"] = utc_now()
            state.data[_STATE_KEY] = progress
            resident.store.save_working_state(state)
            return (
                "fresh exact modal Button revalidation failed before input: "
                f"{type(exc).__name__}: {exc}"
            )
        return None

    def verify_pointer_click_effect(event, state, intent, contract, *, thought=None):
        if not _is_modal_intent(event, intent):
            return original_verify_pointer(event, state, intent, contract, thought=thought)
        progress = _progress(state)
        execution = state.data.get(resident._POINTER_CLICK_EXECUTION_KEY)
        action_result = state.data.get("native_action_result")
        action_id = str(execution.get("action_id") or "").strip() if isinstance(execution, dict) else ""
        dispatch_proven = bool(
            isinstance(execution, dict)
            and str(execution.get("intent_id") or "") == intent.intent_id
            and str(execution.get("status") or "") == "completed"
            and execution.get("success") is True
            and action_id
            and isinstance(action_result, dict)
            and str(action_result.get("action_id") or "") == action_id
            and str(action_result.get("kind") or "").strip().lower() == "pointer_click"
            and action_result.get("success") is True
        )
        if not dispatch_proven:
            return resident._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "modal dismiss reached verification without durable proof of the exact pointer "
                    "dispatch; side-effect delivery is uncertain and no replay is allowed"
                ),
            )
        if int(progress.get("dispatch_count") or 0) != 0:
            return resident._fail_composite_goal_investigation(
                event,
                state,
                reason="modal dismiss dispatch was already recorded; refusing duplicate input",
            )
        progress.update(
            {
                "phase": "dismiss_dispatched",
                "dispatch_count": 1,
                "pointer_action_id": action_id,
                "recovery_observations": 0,
                "dispatched_at": utc_now(),
                "updated_at": utc_now(),
            }
        )
        resident._reset_investigation_after_goal_substep(event, state, intent)
        state.data[_STATE_KEY] = progress
        state.data.pop(resident._DESKTOP_TASK_OBSERVATION_KEY, None)
        state.stage = "native_investigation"
        state.next_action = (
            "freshly observe exact modal disappearance and exact parent recovery; do not replay input"
        )
        resident._sync_execution_context(event, state)
        resident.store.save_working_state(state)
        return None

    resident._desktop_task_investigation = desktop_task_investigation
    resident._deliberation_step = deliberation_step
    resident._pointer_click_contract = pointer_click_contract
    resident._pointer_click_final_input_precondition = final_input_precondition
    resident._verify_pointer_click_effect = verify_pointer_click_effect
    setattr(resident, _INSTALL_MARKER, True)


def _investigate_interruption(resident, event, state, *, progress, parent):
    try:
        modal = resident.modal_window.probe(
            parent_hwnd=int(parent["window_handle"]),
            parent_process_id=int(parent["process_id"]),
            parent_process_name=str(parent["process_name"]),
        )
    except Exception as exc:
        return resident._fail_composite_goal_investigation(
            event,
            state,
            reason=(
                "foreground desktop interruption could not be proven as the exact blocking modal "
                "for the admitted parent; zero autonomous dialog input: "
                f"{type(exc).__name__}: {exc}"
            ),
        )
    if modal is None:
        return resident._fail_composite_goal_investigation(
            event,
            state,
            reason=(
                "foreground HWND changed away from the admitted desktop parent without one exact "
                "blocking modal relationship; refusing authority transfer"
            ),
        )
    safe_action, failure = select_safe_modal_action(modal, user_goal=str(event.task or ""))
    if safe_action is None:
        return resident._fail_composite_goal_investigation(
            event,
            state,
            reason=(
                "exact blocking modal requires user decision; zero autonomous dialog mutation: "
                + str(failure or "no uniquely safe action")
            ),
        )
    if int(progress.get("dispatch_count") or 0) > 0:
        return resident._fail_composite_goal_investigation(
            event,
            state,
            reason="one modal dismiss input was already dispatched; refusing any replay",
        )
    pre_runtime = [int(v) for v in progress.get("latest_target_runtime_id") or ()]
    progress.update(
        {
            "phase": "modal_ready",
            "modal": {
                **asdict(modal),
                "safe_action_name": safe_action.name,
                "safe_action_runtime_id": list(safe_action.runtime_id),
                "safe_action_center_x_fraction": safe_action.center_x_fraction,
                "safe_action_center_y_fraction": safe_action.center_y_fraction,
            },
            "pre_modal_target_runtime_id": pre_runtime,
            "modal_observed_at": utc_now(),
            "updated_at": utc_now(),
        }
    )
    state.data[_STATE_KEY] = progress
    state.data.pop("local_failure", None)
    state.stage = "native_deliberation"
    state.next_action = "admit the one exact safe modal defer/continue action"
    resident._sync_execution_context(event, state)
    resident.store.save_working_state(state)
    return None


def _same_modal_authority(admitted, expected, fresh, fresh_button) -> bool:
    admitted_runtime = tuple(int(v) for v in expected.get("safe_action_runtime_id") or ())
    return bool(
        int(fresh.dialog_hwnd) == int(expected["dialog_hwnd"])
        and int(fresh.parent_hwnd) == int(expected["parent_hwnd"])
        and int(fresh.owner_hwnd) == int(expected["owner_hwnd"])
        and int(fresh.root_owner_hwnd) == int(expected["root_owner_hwnd"])
        and int(fresh.parent_root_owner_hwnd) == int(expected["parent_root_owner_hwnd"])
        and fresh.is_modal
        and fresh.dialog_visible
        and fresh.dialog_enabled
        and int(fresh.parent_interaction_state) == WINDOW_INTERACTION_BLOCKED_BY_MODAL
        and int(admitted.get("dialog_hwnd") or 0) == int(fresh.dialog_hwnd)
        and int(admitted.get("parent_hwnd") or 0) == int(fresh.parent_hwnd)
        and int(admitted.get("owner_hwnd") or 0) == int(fresh.owner_hwnd)
        and int(admitted.get("root_owner_hwnd") or 0) == int(fresh.root_owner_hwnd)
        and int(admitted.get("parent_root_owner_hwnd") or 0) == int(fresh.parent_root_owner_hwnd)
        and tuple(fresh_button.runtime_id) == admitted_runtime
        and int(fresh_button.dialog_hwnd) == int(fresh.dialog_hwnd)
        and int(fresh_button.process_id) == int(fresh.dialog_process_id)
        and str(fresh_button.name or "").strip() == str(expected.get("safe_action_name") or "").strip()
        and fresh_button.is_enabled
        and not fresh_button.is_offscreen
        and abs(float(fresh_button.center_x_fraction) - float(expected["safe_action_center_x_fraction"])) <= 0.002
        and abs(float(fresh_button.center_y_fraction) - float(expected["safe_action_center_y_fraction"])) <= 0.002
    )


def _is_modal_intent(event, intent) -> bool:
    expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
    return bool(
        desktop_task_goal(event) is not None
        and intent.kind == "pointer_click"
        and str(expected.get("kind") or "").strip().lower() == _MODAL_DISMISS_KIND
    )


def _progress(state) -> dict[str, Any]:
    raw = state.data.get(_STATE_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def _parent(progress: dict[str, Any]) -> dict[str, Any] | None:
    value = progress.get("parent")
    if not isinstance(value, dict):
        return None
    try:
        hwnd = int(value.get("window_handle") or 0)
        pid = int(value.get("process_id") or 0)
    except (TypeError, ValueError):
        return None
    name = str(value.get("process_name") or "").strip().lower()
    if hwnd <= 0 or pid <= 0 or not name:
        return None
    return {**value, "window_handle": hwnd, "process_id": pid, "process_name": name}


def _remember_parent_and_target(resident, state) -> None:
    observation = state.data.get(resident._DESKTOP_TASK_OBSERVATION_KEY)
    if not isinstance(observation, dict) or observation.get("failure"):
        return
    foreground = observation.get("foreground")
    target = observation.get("target")
    if not isinstance(foreground, dict):
        return
    try:
        hwnd = int(foreground.get("window_handle") or 0)
        pid = int(foreground.get("process_id") or 0)
    except (TypeError, ValueError):
        return
    process_name = str(foreground.get("process_name") or "").strip().lower()
    if hwnd <= 0 or pid <= 0 or not process_name:
        return
    progress = _progress(state)
    existing = _parent(progress)
    if existing is not None and (
        int(existing["window_handle"]) != hwnd
        or int(existing["process_id"]) != pid
        or str(existing["process_name"]) != process_name
    ):
        return
    if existing is None:
        progress["parent"] = {
            "window_handle": hwnd,
            "process_id": pid,
            "process_name": process_name,
            "title": str(foreground.get("title") or ""),
            "class_name": str(foreground.get("class_name") or ""),
            "bound_at": utc_now(),
        }
    if isinstance(target, dict) and target.get("runtime_id"):
        runtime_id = [int(v) for v in target.get("runtime_id") or ()]
        progress["latest_target_runtime_id"] = runtime_id
        if str(progress.get("phase") or "") == "recovered":
            progress["post_modal_target_runtime_id"] = runtime_id
    progress["updated_at"] = utc_now()
    state.data[_STATE_KEY] = progress
    resident.store.save_working_state(state)


def _recover_exact_parent(
    resident,
    event,
    state,
    *,
    readiness,
    thought,
    original_investigation,
):
    progress = _progress(state)
    parent = _parent(progress)
    modal = progress.get("modal")
    if parent is None or not isinstance(modal, dict) or int(modal.get("dialog_hwnd") or 0) <= 0:
        return resident._fail_composite_goal_investigation(
            event,
            state,
            reason="modal dismiss lost its exact pre-modal parent/dialog authority",
        )
    try:
        recovered = resident.modal_window.probe_parent_recovery(
            parent_hwnd=int(parent["window_handle"]),
            parent_process_id=int(parent["process_id"]),
            parent_process_name=str(parent["process_name"]),
            dismissed_dialog_hwnd=int(modal["dialog_hwnd"]),
        )
    except Exception as exc:
        return resident._fail_composite_goal_investigation(
            event,
            state,
            reason=(
                "modal input was dispatched once, but the exact original parent cannot be freshly "
                "re-established; refusing replay or authority transfer: "
                f"{type(exc).__name__}: {exc}"
            ),
        )

    observations = int(progress.get("recovery_observations") or 0) + 1
    recovered_ok = bool(
        recovered.modal_absent
        and not recovered.dismissed_dialog_exists
        and int(recovered.dismissed_dialog_hwnd) == int(modal["dialog_hwnd"])
        and recovered.foreground
        and recovered.visible
        and recovered.enabled
        and int(recovered.parent_interaction_state) == WINDOW_INTERACTION_READY
        and int(recovered.parent_hwnd) == int(parent["window_handle"])
        and int(recovered.parent_process_id) == int(parent["process_id"])
        and str(recovered.parent_process_name or "").strip().lower() == str(parent["process_name"])
    )
    progress["recovery_observations"] = observations
    progress["last_recovery_observation"] = asdict(recovered)
    progress["updated_at"] = utc_now()
    state.data[_STATE_KEY] = progress
    if not recovered_ok:
        if observations >= _MAX_RECOVERY_OBSERVATIONS:
            return resident._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "one modal dismiss was dispatched, but bounded fresh observations did not prove "
                    "exact dialog disappearance plus exact parent ReadyForUserInteraction; no replay; "
                    f"last_recovery_observation={asdict(recovered)!r}"
                ),
            )
        state.data.pop("local_failure", None)
        state.stage = "native_investigation"
        state.next_action = (
            "bounded fresh poll for exact dialog disappearance and parent recovery; do not replay input"
        )
        resident._sync_execution_context(event, state)
        resident.store.save_working_state(state)
        return None

    progress["phase"] = "recovered"
    progress["recovered_parent"] = asdict(recovered)
    progress["recovered_at"] = utc_now()
    progress["updated_at"] = utc_now()
    state.data[_STATE_KEY] = progress
    state.data.pop(resident._DESKTOP_TASK_OBSERVATION_KEY, None)
    state.data.pop("local_failure", None)
    resident.store.save_working_state(state)
    result = original_investigation(event, state, readiness=readiness, thought=thought)
    _remember_parent_and_target(resident, state)
    return result


DESKTOP_MODAL_RECOVERY_STATE_KEY = _STATE_KEY
DESKTOP_MODAL_DISMISS_KIND = _MODAL_DISMISS_KIND
MAX_DESKTOP_MODAL_RECOVERY_OBSERVATIONS = _MAX_RECOVERY_OBSERVATIONS
