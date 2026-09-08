from __future__ import annotations

"""Bounded same-Work Browser -> File -> Desktop continuation for E2E-24.

The behavior decorates the one product Resident. It owns no scheduler, router,
store, browser session, action primitive, or second completion truth. Only the
business customer fact crosses phases; Browser authorization, file identity,
foreground HWND/PID, UIA RuntimeId and final app evidence are freshly grounded
at their own authority boundaries.
"""

import ctypes
import json
import os
import re
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Any, Mapping

from .action import NativeActionIntent
from .desktop_task_goal import DESKTOP_TASK_GOAL_KIND
from .goal_resident import ResidentGoalRuntime
from .models import utc_now
from .natural_file_goal import fresh_workspace_text, observe_workspace_text_source


_STATE_KEY = "resident_e2e24_browser_file_desktop"
_INSTALL_MARKER = "_zn_e2e24_browser_file_desktop_behavior_installed"
_UNDERSTANDING_KEY = "_resident_goal_understanding"
_DESKTOP_SEMANTIC_GOAL_KEY = "_resident_desktop_semantic_goal"
_GOAL_KIND = "browser_file_desktop_customer_status"
_BROWSER_CUES = ("当前网站", "这个网站", "当前页面", "这个页面")
_DESKTOP_CUES = ("软件", "应用", "客户管理")
_STATUS_ANCHORS = ("需跟进",)
_IDENTIFIER_CUES = ("编号", "账号", "号码", "标识", "id", "ID")
_FILE_HINT = re.compile(
    r"名字(?:里)?(?:像|包含|带有|带)\s*[\"“'‘]?(?P<v>[^\"”'’‘，,。；;\r\n]{1,64}?)[\"”'’]?\s*"
    r"的(?:那个|那份|那个文件|文件)?(?:客户状态)?\s*\.?\s*txt(?=[，,。；;\s]|$)",
    re.I,
)
_BROWSER_PROCESSES = {
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
    "opera.exe",
}


def install_browser_file_desktop_handoff_behavior(resident) -> None:
    """Install only the narrow E2E-24 compositional seam on the existing Resident."""

    if getattr(resident, _INSTALL_MARKER, False):
        return

    original_orient = resident._orient_step
    original_deliberation = resident._deliberation_step
    original_complete = resident._complete_successful_body_action
    original_resume_completion = resident._resume_native_completion
    original_desktop_investigation = resident._desktop_task_investigation

    def orient_step(event, state, *, readiness, thought=None):
        request = _request(event)
        if request is None:
            return original_orient(event, state, readiness=readiness, thought=thought)
        phase = str(_progress(state).get("phase") or "browser_file")
        if phase == "desktop_ground":
            return _ground_desktop_goal(resident, event, state, request=request)
        if phase == "desktop":
            return original_orient(event, state, readiness=readiness, thought=thought)
        return ResidentGoalRuntime._orient_step(
            resident,
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    def deliberation_step(
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        request = _request(event)
        progress = _progress(state)
        phase = str(progress.get("phase") or "browser_file")
        if request is None or phase == "desktop":
            return original_deliberation(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )
        if phase == "desktop_ground":
            state.stage = "native_orient"
            state.next_action = "freshly ground the current desktop application"
            resident._sync_execution_context(event, state)
            resident.store.save_working_state(state)
            return None

        prepared = _prepare_browser_and_file(resident, event, state, request=request)
        if isinstance(prepared, str):
            return resident._checkpoint_terminal_failure(event, state, reason=prepared)
        intent = prepared
        if resident._action_blocked_by_current_evidence(event, state, intent):
            return resident._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "the exact E2E-24 file mutation remains blocked by unchanged evidence; "
                    "ZN will not replay it"
                ),
            )
        resident._begin_native_action_cycle(event, state, intent)
        progress = _progress(state)
        progress.update(
            {
                "phase": "file_write_pending",
                "file_intent_id": intent.intent_id,
                "updated_at": utc_now(),
            }
        )
        state.data[_STATE_KEY] = progress
        resident._sync_execution_context(event, state)
        resident.store.save_working_state(state)
        return None

    def complete_successful_body_action(event, state, intent, *, response: str, reason: str):
        progress = _progress(state)
        handoff = bool(
            _request(event) is not None
            and progress.get("phase") == "file_write_pending"
            and str(progress.get("file_intent_id") or "") == str(intent.intent_id or "")
            and str(intent.kind or "").lower() == "write_text"
        )
        if not handoff:
            return original_complete(event, state, intent, response=response, reason=reason)
        result = original_complete(event, state, intent, response=response, reason=reason)
        if result is None or not result.success:
            return result
        return _roll_forward_verified_file(resident, event, state, intent=intent, result=result)

    def resume_native_completion(event, state):
        progress = _progress(state)
        raw_intent = state.data.get("native_action_intent")
        try:
            intent = NativeActionIntent.from_dict(raw_intent) if isinstance(raw_intent, dict) else None
        except (TypeError, ValueError):
            intent = None
        handoff = bool(
            _request(event) is not None
            and progress.get("phase") == "file_write_pending"
            and intent is not None
            and str(progress.get("file_intent_id") or "") == str(intent.intent_id or "")
            and str(intent.kind or "").lower() == "write_text"
        )
        result = original_resume_completion(event, state)
        if not handoff or result is None or not result.success:
            return result
        return _roll_forward_verified_file(resident, event, state, intent=intent, result=result)

    def desktop_task_investigation(event, state, *, readiness, thought=None):
        progress = _progress(state)
        if _request(event) is None or progress.get("phase") != "desktop":
            return original_desktop_investigation(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )
        try:
            foreground = resident.foreground_window.probe()
            hwnd, pid = _foreground_hwnd_pid()
        except Exception as exc:
            return resident._fail_composite_goal_investigation(
                event,
                state,
                reason=f"fresh E2E-24 desktop identity Sense failed: {type(exc).__name__}: {exc}",
            )
        if (
            hwnd != int(progress.get("desktop_hwnd") or 0)
            or pid != int(progress.get("desktop_process_id") or 0)
            or int(foreground.process_id) != pid
            or str(foreground.process_name or "").strip().lower()
            != str(progress.get("desktop_process_name") or "")
        ):
            return resident._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "the exact foreground HWND/PID changed after desktop grounding; "
                    "E2E-24 authority was not transferred to a sibling/replacement window"
                ),
            )
        desktop_progress = state.data.get(resident._DESKTOP_TASK_PROGRESS_KEY)
        desktop_progress = dict(desktop_progress) if isinstance(desktop_progress, dict) else {}
        if desktop_progress.get("submit_dispatched") is True:
            title = str(foreground.title or "").strip()
            customer_id = str(progress.get("customer_id") or "")
            status = str(progress.get("status") or "")
            if not customer_id or not status or customer_id not in title or status not in title:
                return resident._fail_composite_goal_investigation(
                    event,
                    state,
                    reason=(
                        "the desktop submit was already dispatched once, but fresh exact-HWND/PID "
                        "application evidence did not prove the same customer and requested status; "
                        "no replay is allowed"
                    ),
                )
            progress["desktop_postcondition"] = {
                "window_handle": hwnd,
                "process_id": pid,
                "title": title,
                "customer_id": customer_id,
                "status": status,
                "verified_at": utc_now(),
            }
            state.data[_STATE_KEY] = progress
            resident.store.save_working_state(state)
        return original_desktop_investigation(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    resident._orient_step = orient_step
    resident._deliberation_step = deliberation_step
    resident._complete_successful_body_action = complete_successful_body_action
    resident._resume_native_completion = resume_native_completion
    resident._desktop_task_investigation = desktop_task_investigation
    setattr(resident, _INSTALL_MARKER, True)


def _request(event) -> dict[str, str] | None:
    payload = event.payload or {}
    task = " ".join(str(event.task or "").strip().split())
    if (
        str(event.kind or "").lower() != "desktop_user_event"
        or not str(payload.get("workspace_path") or "").strip()
        or payload.get("body_action")
        or payload.get("native_action")
        or "昨天" not in task
        or "客户" not in task
        or ("文件" not in task and "txt" not in task.lower())
        or not any(cue in task for cue in _BROWSER_CUES)
        or not any(cue in task for cue in _DESKTOP_CUES)
        or not any(cue in task for cue in ("标记", "跟进"))
        or "确认" not in task
    ):
        return None
    status = next((cue for cue in _STATUS_ANCHORS if cue in task), "")
    if not status:
        return None
    hint_match = _FILE_HINT.search(task)
    if hint_match is not None:
        hint = " ".join(hint_match.group("v").strip().split())
    elif "客户状态" in task:
        hint = "客户状态"
    else:
        return None
    if not hint:
        return None
    return {
        "workspace_path": str(payload["workspace_path"]),
        "file_hint": hint,
        "status_anchor": status,
    }


def _progress(state) -> dict[str, Any]:
    raw = state.data.get(_STATE_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def _prepare_browser_and_file(resident, event, state, *, request: Mapping[str, str]):
    progress = _progress(state)
    customer_id = str(progress.get("customer_id") or "").strip()
    status = str(progress.get("status") or "").strip()
    if not customer_id or not status:
        authorization = resident.user_browser_extension.authorized_tab()
        if authorization is None:
            return "E2E-24 requires one current USER Browser tab explicitly authorized by the user"
        tab_id = int(authorization.tab_id)
        attached_at = str(authorization.attached_at)
        try:
            observed = resident._observe_authorized_anchor(request["status_anchor"])
        except Exception as exc:
            return (
                "fresh authorized Browser evidence could not establish one exact abnormal record: "
                f"{type(exc).__name__}: {exc}"
            )
        current = resident.user_browser_extension.authorized_tab()
        if (
            current is None
            or int(current.tab_id) != tab_id
            or str(current.attached_at) != attached_at
            or int(observed.get("tab_id") or 0) != tab_id
        ):
            return "USER Browser authorization generation changed during E2E-24 evidence sensing"
        context = " ".join(str(observed.get("context") or "").strip().split())
        if not context or context.count(request["status_anchor"]) != 1:
            return "authorized Browser evidence did not expose one unique requested status row"
        extracted, failure, invocations = _extract_customer_fact(
            resident,
            event,
            context=context,
            status_anchor=request["status_anchor"],
        )
        if failure:
            return failure
        customer_id = extracted["customer_id"]
        status = extracted["status"]
        progress.update(
            {
                "phase": "browser_verified",
                "customer_id": customer_id,
                "status": status,
                "browser_evidence": {
                    "tab_id": tab_id,
                    "authorization_attached_at": attached_at,
                    "url": str(observed.get("url") or ""),
                    "title": str(observed.get("title") or ""),
                    "status_anchor": status,
                    "observed_at": str(observed.get("observed_at") or utc_now()),
                },
                "model_invocations": int(progress.get("model_invocations") or 0) + invocations,
                "updated_at": utc_now(),
            }
        )
        state.data[_STATE_KEY] = progress
        _save_model_accounting(resident, event, state, progress)
        resident._sync_execution_context(event, state)
        resident.store.save_working_state(state)

    source, failure = observe_workspace_text_source(
        event,
        resident.body,
        workspace_path=request["workspace_path"],
        name_hint=request["file_hint"],
        modified_yesterday=True,
    )
    if failure:
        return "fresh workspace evidence could not establish one exact E2E-24 file: " + failure
    current_text, failure = fresh_workspace_text(event, resident.body, source)
    if failure:
        return "E2E-24 file identity changed before mutation authority: " + failure
    expected_text = customer_id
    if current_text == expected_text:
        return (
            "the exact E2E-24 file already contains the abnormal customer; this representative "
            "path refuses to manufacture a duplicate write"
        )
    identity = source.get("identity")
    if not isinstance(identity, Mapping):
        return "exact E2E-24 file source lost its fresh identity before mutation admission"
    exact_file_hint = Path(str(source["path"])).stem
    intent = NativeActionIntent(
        intent_id=f"e2e24-file-{uuid.uuid4().hex[:12]}",
        event_id=event.event_id,
        kind="write_text",
        args={
            "path": str(source["path"]),
            "content": expected_text,
            "append": False,
            "create_parents": False,
        },
        expected_outcome={
            "kind": "text_equals",
            "path": str(source["path"]),
            "expected_text": expected_text,
            "precondition_file_identity": dict(identity),
        },
        reason=(
            "fresh authorized Browser evidence established one business customer identity, while "
            "fresh workspace evidence independently established one exact file mutation authority"
        ),
        source="resident_choice",
    )
    progress.update(
        {
            "phase": "file_ready",
            "file_hint": request["file_hint"],
            "exact_file_hint": exact_file_hint,
            "file_before": {
                "path": str(source["path"]),
                "identity": dict(identity),
                "text_sha256": str(source.get("text_sha256") or ""),
                "observed_at": utc_now(),
            },
            "updated_at": utc_now(),
        }
    )
    state.data[_STATE_KEY] = progress
    resident.store.save_working_state(state)
    return intent


def _extract_customer_fact(resident, event, *, context: str, status_anchor: str):
    fields = [field for field in context.split() if field != status_anchor]
    if len(fields) == 1 and 0 < len(fields[0]) <= 160:
        customer_id = fields[0]
        if not any(ord(char) < 32 or ord(char) == 127 for char in customer_id):
            return {"customer_id": customer_id, "status": status_anchor}, None, 0

    decision = resident.budget.decide(event, memory_hit=False, local_capability_available=False)
    if not decision.use_model:
        return {}, (
            "fresh Browser row needs bounded language interpretation, but model use is disabled; "
            "ZN will not guess the customer identity"
        ), 0
    question = (
        "Interpret only this freshly sensed structured row from the exact authorized USER Browser tab. "
        "Return exactly one JSON object and no prose: "
        '{"status":"selected","customer_id":"EXACT LITERAL FROM ROW","customer_status":"EXACT STATUS ANCHOR"}. '
        "Select only when the row contains one business customer identifier associated with the supplied "
        "status anchor. Otherwise return {\"status\":\"ambiguous\"}. Do not infer a customer, mutate "
        "anything, return browser authority, or claim completion. "
        f"Status anchor: {json.dumps(status_anchor, ensure_ascii=False)}\n"
        f"Fresh authorized row: {json.dumps(context, ensure_ascii=False)}"
    )
    result = resident.kernel.run_goal(
        question,
        required_capabilities=("language_understanding",),
        priority=event.priority,
        metadata={"resident_event_id": event.event_id, "purpose": "e2e24_browser_fact_interpretation_only"},
        max_attempts_override=1,
        goal_id=f"goal-e2e24-browser-fact-{event.event_id}",
    )
    invocations = resident._model_invocations(result)
    try:
        raw = (
            json.loads(result.worker_result.response)
            if result.worker_result.success and result.assessment.success
            else None
        )
    except (TypeError, ValueError):
        raw = None
    if not isinstance(raw, dict) or set(raw) != {"status", "customer_id", "customer_status"}:
        return {}, "bounded cognition did not return the permitted Browser fact schema", invocations
    customer_id = " ".join(str(raw.get("customer_id") or "").strip().split())
    customer_status = " ".join(str(raw.get("customer_status") or "").strip().split())
    if (
        str(raw.get("status") or "").strip() != "selected"
        or not customer_id
        or len(customer_id) > 160
        or customer_status != status_anchor
        or context.count(customer_id) != 1
        or context.count(customer_status) != 1
        or any(ord(char) < 32 or ord(char) == 127 for char in customer_id)
    ):
        return {}, (
            "cognition output was not exactly grounded in the one fresh authorized Browser row; "
            "model text was not accepted as a business fact"
        ), invocations
    return {"customer_id": customer_id, "status": customer_status}, None, invocations


def _roll_forward_verified_file(resident, event, state, *, intent, result):
    progress = _progress(state)
    request = _request(event)
    if request is None:
        return result
    exact_hint = str(progress.get("exact_file_hint") or "").strip()
    if not exact_hint:
        return resident._checkpoint_terminal_failure(
            event,
            state,
            reason="verified file mutation lost its exact selected file identity",
        )
    source, failure = observe_workspace_text_source(
        event,
        resident.body,
        workspace_path=request["workspace_path"],
        name_hint=exact_hint,
        modified_yesterday=False,
    )
    if failure:
        return resident._checkpoint_terminal_failure(
            event,
            state,
            reason="fresh post-write file re-sense failed: " + failure,
        )
    text, failure = fresh_workspace_text(event, resident.body, source)
    customer_id = str(progress.get("customer_id") or "")
    if failure or text != customer_id:
        return resident._checkpoint_terminal_failure(
            event,
            state,
            reason=(
                "fresh post-write file reread did not independently prove the exact Browser customer "
                "identity; desktop authority was not attempted"
            ),
        )
    progress.update(
        {
            "phase": "desktop_ground",
            "exact_file_hint": Path(str(source["path"])).stem,
            "file_verified": {
                "path": str(source["path"]),
                "identity": dict(source.get("identity") or {}),
                "text_sha256": str(source.get("text_sha256") or ""),
                "customer_id": customer_id,
                "verified_at": utc_now(),
            },
            "updated_at": utc_now(),
        }
    )
    state.data[_STATE_KEY] = progress
    resident._reset_investigation_after_goal_substep(event, state, intent)
    state.data.pop("native_completion", None)
    state.stage = "native_orient"
    state.next_action = "freshly sense the current desktop application and ground the customer operation"
    resident._sync_execution_context(event, state)
    resident.store.save_working_state(state)
    return None


def _ground_desktop_goal(resident, event, state, *, request):
    progress = _progress(state)
    exact_file_hint = str(progress.get("exact_file_hint") or "").strip()
    if not exact_file_hint:
        return resident._checkpoint_terminal_failure(
            event,
            state,
            reason="E2E-24 desktop phase lost the freshly verified exact file identity",
        )
    try:
        foreground = resident.foreground_window.probe()
        hwnd, pid = _foreground_hwnd_pid()
    except Exception as exc:
        return resident._checkpoint_terminal_failure(
            event,
            state,
            reason=f"fresh E2E-24 foreground application Sense failed: {type(exc).__name__}: {exc}",
        )
    process_name = str(foreground.process_name or "").strip().lower()
    if (
        int(foreground.process_id) != pid
        or not process_name
        or process_name in _BROWSER_PROCESSES
        or not str(foreground.title or "").strip()
    ):
        return resident._checkpoint_terminal_failure(
            event,
            state,
            reason="E2E-24 desktop phase requires one exact current non-browser HWND/PID",
        )
    try:
        edits = resident.named_automation_control.list_safe_edits(
            process_id=pid,
            process_name=process_name,
        )
        buttons = resident.named_automation_control.list_buttons(
            process_id=pid,
            process_name=process_name,
        )
    except Exception as exc:
        return resident._checkpoint_terminal_failure(
            event,
            state,
            reason=f"fresh E2E-24 UIA candidate Sense failed closed: {type(exc).__name__}: {exc}",
        )
    edit_names = tuple(item.name for item in edits)
    button_names = tuple(item.name for item in buttons)
    selection, failure, invocations = _select_desktop_names(
        resident,
        event,
        edit_names=edit_names,
        button_names=button_names,
    )
    if failure:
        return resident._checkpoint_terminal_failure(event, state, reason=failure)
    input_name, button_name = selection
    semantic = {
        "kind": DESKTOP_TASK_GOAL_KIND,
        "source_name_hint": exact_file_hint,
        "input_name": "customer identifier field",
        "button_name": "mark the exact customer for follow-up",
        "expected_title": None,
        "source_modified_yesterday": False,
    }
    grounded = dict(semantic)
    grounded["input_name"] = input_name
    grounded["button_name"] = button_name
    event.payload = dict(event.payload or {})
    event.payload[_DESKTOP_SEMANTIC_GOAL_KEY] = semantic
    event.payload["desktop_task_goal"] = grounded
    progress.update(
        {
            "phase": "desktop",
            "desktop_hwnd": hwnd,
            "desktop_process_id": pid,
            "desktop_process_name": process_name,
            "desktop_grounded_names": {"input_name": input_name, "button_name": button_name},
            "model_invocations": int(progress.get("model_invocations") or 0) + invocations,
            "desktop_grounded_at": utc_now(),
            "updated_at": utc_now(),
        }
    )
    state.data[_STATE_KEY] = progress
    _save_model_accounting(resident, event, state, progress)
    resident.store._save_event(event)
    state.data.pop("local_failure", None)
    state.stage = "native_investigation"
    state.next_action = "freshly bind exact current UIA identity for the grounded customer operation"
    resident._sync_execution_context(event, state)
    resident.store.save_working_state(state)
    return None


def _select_desktop_names(resident, event, *, edit_names: tuple[str, ...], button_names: tuple[str, ...]):
    input_candidates = [
        name
        for name in edit_names
        if "客户" in name and any(cue in name for cue in _IDENTIFIER_CUES)
    ]
    button_candidates = [name for name in button_names if name and name in str(event.task or "")]
    if len(input_candidates) == 1 and len(button_candidates) == 1:
        if edit_names.count(input_candidates[0]) == 1 and button_names.count(button_candidates[0]) == 1:
            return (input_candidates[0], button_candidates[0]), None, 0

    decision = resident.budget.decide(event, memory_hit=False, local_capability_available=False)
    if not decision.use_model:
        return (), (
            "fresh desktop semantic candidates are ambiguous and model use is disabled; "
            "ZN refused first-item selection"
        ), 0
    question = (
        "Choose only among the freshly observed accessible names below for the user's current customer-management "
        "goal. Return exactly {\"status\":\"selected\",\"input_name\":\"ONE OBSERVED EDIT NAME\","
        "\"button_name\":\"ONE OBSERVED BUTTON NAME\"} only when each is uniquely appropriate. Otherwise "
        "return {\"status\":\"ambiguous\"}. Never return indexes, RuntimeIds, HWND/PID, coordinates, "
        "authority, actions, customer values, or completion. "
        f"User task: {event.task}\n"
        f"Fresh Edit names: {json.dumps(edit_names, ensure_ascii=False)}\n"
        f"Fresh Button names: {json.dumps(button_names, ensure_ascii=False)}"
    )
    result = resident.kernel.run_goal(
        question,
        required_capabilities=("language_understanding",),
        priority=event.priority,
        metadata={"resident_event_id": event.event_id, "purpose": "e2e24_desktop_fresh_candidate_grounding_only"},
        max_attempts_override=1,
        goal_id=f"goal-e2e24-desktop-ground-{event.event_id}-{uuid.uuid4().hex[:8]}",
    )
    invocations = resident._model_invocations(result)
    try:
        raw = (
            json.loads(result.worker_result.response)
            if result.worker_result.success and result.assessment.success
            else None
        )
    except (TypeError, ValueError):
        raw = None
    if not isinstance(raw, dict) or str(raw.get("status") or "") != "selected":
        return (), "fresh desktop semantic target selection was ambiguous", invocations
    input_name = " ".join(str(raw.get("input_name") or "").strip().split())
    button_name = " ".join(str(raw.get("button_name") or "").strip().split())
    if edit_names.count(input_name) != 1 or button_names.count(button_name) != 1:
        return (), (
            "desktop cognition did not select exactly one uniquely observed safe Edit and Button; "
            "ZN refused first-item fallback"
        ), invocations
    return (input_name, button_name), None, invocations


def _save_model_accounting(resident, event, state, progress: Mapping[str, Any]) -> None:
    invocations = max(0, int(progress.get("model_invocations") or 0))
    event.payload = dict(event.payload or {})
    existing = event.payload.get(_UNDERSTANDING_KEY)
    metadata = dict(existing) if isinstance(existing, dict) else {}
    metadata.update(
        {
            "source": "bounded_cognition_proposal",
            "goal_kind": _GOAL_KIND,
            "model_invocations": invocations,
        }
    )
    event.payload[_UNDERSTANDING_KEY] = metadata
    state.data[_UNDERSTANDING_KEY] = dict(metadata)
    resident.store._save_event(event)


def _foreground_hwnd_pid() -> tuple[int, int]:
    if os.name != "nt":
        raise RuntimeError("exact foreground HWND/PID Sense is available only on Windows")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    hwnd = int(user32.GetForegroundWindow() or 0)
    if hwnd <= 0:
        raise RuntimeError("Windows did not report a foreground HWND")
    process_id = wintypes.DWORD(0)
    thread_id = int(user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id)))
    pid = int(process_id.value)
    if thread_id <= 0 or pid <= 0:
        raise RuntimeError("foreground HWND process identity is unavailable")
    return hwnd, pid
