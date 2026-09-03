from __future__ import annotations

import ctypes
import json
import os
import subprocess
import tempfile
import time
import unittest
from ctypes import wintypes
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path

from zn_agent.core.cognitive_resource import CognitiveIncrement, CognitiveResourceWorkerFactory
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.desktop_task_goal import DESKTOP_TASK_GOAL_KIND, explicit_desktop_task_goal_hint
from zn_agent.core.models import ModelRoute
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.resident_server import ResidentSocketService
from test_windows_interactive_text_entry import WindowsInteractiveTextEntryE2ETests

TASK = "找到昨天那份订单资料，把里面的编号拿到我现在开的软件里，帮我把对应记录查出来并确认结果出来了。"
INPUT_NAME = "订单编号"
BUTTON_NAME = "查找记录"
OLD_VALUE = "ORDER-OLD-401"
NEW_VALUE = "ORDER-REAL-902"
START_TITLE = "ZN Desktop Order Lookup E2E"
SUCCESS_TITLE = "ZN 订单记录已打开 #1"


def _user32():
    api = ctypes.WinDLL("user32", use_last_error=True)
    api.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]; api.ShowWindow.restype = wintypes.BOOL
    api.BringWindowToTop.argtypes = [wintypes.HWND]; api.BringWindowToTop.restype = wintypes.BOOL
    api.SetForegroundWindow.argtypes = [wintypes.HWND]; api.SetForegroundWindow.restype = wintypes.BOOL
    api.GetForegroundWindow.argtypes = []; api.GetForegroundWindow.restype = wintypes.HWND
    api.GetWindowTextLengthW.argtypes = [wintypes.HWND]; api.GetWindowTextLengthW.restype = ctypes.c_int
    api.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]; api.GetWindowTextW.restype = ctypes.c_int
    api.IsWindowVisible.argtypes = [wintypes.HWND]; api.IsWindowVisible.restype = wintypes.BOOL
    api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]; api.GetWindowThreadProcessId.restype = wintypes.DWORD
    api.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]; api.PostMessageW.restype = wintypes.BOOL
    api.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]; api.GetCursorPos.restype = wintypes.BOOL
    return api


class _Proposal:
    def __init__(self):
        self.calls = 0
        self.questions: list[str] = []

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        self.calls += 1
        self.questions.append(question)
        if "Fresh Edit names:" in question:
            value = {
                "status": "selected",
                "input_name": INPUT_NAME,
                "button_name": BUTTON_NAME,
            }
        else:
            value = {
                "kind": DESKTOP_TASK_GOAL_KIND,
                "source_name_hint": "订单",
                "input_name": INPUT_NAME,
                "button_name": BUTTON_NAME,
                "expected_title": None,
                "source_modified_yesterday": True,
            }
        return CognitiveIncrement(
            text=json.dumps(value, ensure_ascii=False),
            provider="e2e-cognition",
            model="bounded-language-fixture",
        )


class _OrderApp:
    def __init__(self, root: Path):
        self.script = root / "order-e2e.ps1"
        self.process = None
        self.hwnd = 0

    def start(self):
        self.script.write_text(self._script(), encoding="utf-8-sig")
        self.process = subprocess.Popen([
            "powershell.exe", "-NoLogo", "-NoProfile", "-Sta",
            "-ExecutionPolicy", "Bypass", "-File", str(self.script),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("desktop fixture exited early")
            self.hwnd = self._find_window()
            if self.hwnd:
                self.activate()
                return
            time.sleep(.05)
        raise RuntimeError("desktop fixture window was not found")

    def activate(self):
        user32 = _user32()
        user32.ShowWindow(self.hwnd, 5)
        user32.BringWindowToTop(self.hwnd)
        user32.SetForegroundWindow(self.hwnd)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if int(user32.GetForegroundWindow() or 0) == self.hwnd: return
            time.sleep(.02)
        raise RuntimeError("fixture could not become foreground")

    def title(self):
        user32 = _user32()
        n = user32.GetWindowTextLengthW(self.hwnd)
        buf = ctypes.create_unicode_buffer(max(1, n + 1))
        user32.GetWindowTextW(self.hwnd, buf, len(buf))
        return buf.value

    def close(self):
        if self.hwnd:
            try: _user32().PostMessageW(self.hwnd, 0x0010, 0, 0)
            except Exception: pass
        if self.process:
            try: self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=2)

    def _find_window(self):
        user32 = _user32()
        callback_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [callback_t, wintypes.LPARAM]; user32.EnumWindows.restype = wintypes.BOOL
        matches = []
        @callback_t
        def visit(hwnd, _):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if self.process and int(pid.value) == self.process.pid and user32.IsWindowVisible(hwnd):
                n = user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(max(1, n + 1))
                user32.GetWindowTextW(hwnd, buf, len(buf))
                if buf.value == START_TITLE: matches.append(int(hwnd))
            return True
        user32.EnumWindows(visit, 0)
        return matches[0] if len(matches) == 1 else 0

    @staticmethod
    def _script():
        return f'''Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$form=New-Object System.Windows.Forms.Form
$form.Text='{START_TITLE}'; $form.StartPosition='CenterScreen'; $form.ClientSize='720,330'
$script:orderBox=New-Object System.Windows.Forms.TextBox
$script:orderBox.AccessibleName='{INPUT_NAME}'; $script:orderBox.Location='70,105'; $script:orderBox.Size='430,45'; $script:orderBox.Font='Segoe UI,16'
$search=New-Object System.Windows.Forms.Button
$search.AccessibleName='{BUTTON_NAME}'; $search.Text='{BUTTON_NAME}'; $search.Location='520,103'; $search.Size='125,48'
$other=New-Object System.Windows.Forms.Button
$other.AccessibleName='其它操作'; $other.Text='其它操作'; $other.Location='70,205'; $other.Size='125,42'
$form.Controls.AddRange(@($script:orderBox,$search,$other))
$script:n=0
$search.Add_Click({{$script:n+=1; if($script:orderBox.Text -eq '{NEW_VALUE}'){{$form.Text='ZN 订单记录已打开 #' + $script:n}}}})
$form.Add_Shown({{$other.Focus()}})
[System.Windows.Forms.Application]::Run($form)'''


class WindowsInteractiveFileDesktopGoalE2ETests(unittest.TestCase):
    @staticmethod
    def _yesterday(path: Path):
        now = datetime.now().astimezone()
        stamp = datetime.combine(now.date()-timedelta(days=1), dt_time(12), tzinfo=now.tzinfo).timestamp()
        os.utime(path, (stamp, stamp))

    def test_natural_file_to_desktop_resenses_source_and_proves_result(self):
        WindowsInteractiveTextEntryE2ETests._require_input_desktop()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); workspace = root / "workspace"; workspace.mkdir()
            source = workspace / "订单资料.txt"; source.write_text(OLD_VALUE, encoding="utf-8"); self._yesterday(source)
            app = _OrderApp(root); app.start(); resident = None
            try:
                resident = build_resident_runtime(config={"model": {}}, store_path=root / "kernel.db")
                service = ResidentSocketService(ResidentRpcServer(resident=resident))
                self.assertIs(resident.visual_region, service.visual_region)
                proposal = _Proposal()
                resident.kernel.reconfigure_resources(
                    routes=[ModelRoute(route_id="e2e-language", provider="fixture", model="bounded-language-fixture", capabilities={"language_understanding":1.0,"general":.8})],
                    worker_factory=CognitiveResourceWorkerFactory(resource_builder=lambda _: proposal),
                    max_attempts=1, resource_status={"available":True,"error":None},
                )
                app.activate(); fg, error = resident._probe_foreground_window(); self.assertIsNotNone(fg, error)
                before = resident.named_automation_control.find_unique_edit(
                    process_id=fg.process_id, process_name=fg.process_name.lower(), name=INPUT_NAME)
                self.assertFalse(before.has_keyboard_focus)

                ledger = RecoveryBoundedWorkLedger(resident); thread = "file-desktop-e2e"
                ledger.create_thread(thread_id=thread); ledger.attach_workspace(thread, workspace)
                _, event = ledger.start(thread, TASK, payload={"model_policy":"on_demand"})
                self.assertIsNone(explicit_desktop_task_goal_hint(event))

                result = None; drifted = False; stale_rejected = False; first_failure = None
                state_trace = []
                last_trace = None
                submit_hit_trace = None
                observation_key = getattr(resident, "_DESKTOP_TASK_OBSERVATION_KEY", "resident_desktop_task_observation")

                def record_state(label: str):
                    nonlocal last_trace, submit_hit_trace
                    current_state = resident.store.get_working_state()
                    if current_state.current_event_id != event.event_id:
                        return
                    observation = current_state.data.get(observation_key)
                    observation = observation if isinstance(observation, dict) else {}
                    source_observation = observation.get("source")
                    source_observation = source_observation if isinstance(source_observation, dict) else {}
                    focused_observation = observation.get("focused")
                    focused_observation = focused_observation if isinstance(focused_observation, dict) else {}
                    intent_observation = current_state.data.get("native_action_intent")
                    intent_observation = intent_observation if isinstance(intent_observation, dict) else {}
                    failures = list(current_state.data.get("native_action_failure_records") or [])
                    latest_failure = failures[-1] if failures else {}
                    pointer_execution = current_state.data.get("native_pointer_click_execution")
                    pointer_execution = pointer_execution if isinstance(pointer_execution, dict) else {}
                    text_execution = current_state.data.get("native_keyboard_text_execution")
                    text_execution = text_execution if isinstance(text_execution, dict) else {}
                    verification = current_state.data.get("native_verification_result")
                    verification = verification if isinstance(verification, dict) else {}
                    progress = current_state.data.get("resident_desktop_task_progress")
                    progress = progress if isinstance(progress, dict) else {}
                    if progress.get("submit_dispatched") is True and submit_hit_trace is None:
                        try:
                            point = wintypes.POINT()
                            pointer_ok = bool(_user32().GetCursorPos(ctypes.byref(point)))
                            foreground_now, foreground_error = resident._probe_foreground_window()
                            button_now = None
                            if foreground_now is not None:
                                button_now = resident.named_automation_control.find_unique_button(
                                    process_id=foreground_now.process_id,
                                    process_name=foreground_now.process_name.lower(),
                                    name=BUTTON_NAME,
                                )
                            at_pointer = None; at_pointer_error = None
                            if pointer_ok:
                                at_pointer, at_pointer_error = resident._probe_automation_element_at_point(
                                    int(point.x), int(point.y)
                                )
                            focused_now, focused_error = resident._probe_focused_automation_element()
                            button_runtime = tuple(button_now.runtime_id) if button_now is not None else ()
                            at_pointer_runtime = tuple(at_pointer.runtime_id) if at_pointer is not None else ()
                            focused_runtime = tuple(focused_now.runtime_id) if focused_now is not None else ()
                            submit_hit_trace = {
                                "pointer_ok": pointer_ok,
                                "pointer_x": int(point.x) if pointer_ok else None,
                                "pointer_y": int(point.y) if pointer_ok else None,
                                "foreground_process": foreground_now.process_name if foreground_now is not None else None,
                                "foreground_title": foreground_now.title if foreground_now is not None else None,
                                "foreground_error": str(foreground_error or "") or None,
                                "button_runtime_id": list(button_runtime),
                                "button_rect": (
                                    [button_now.left, button_now.top, button_now.right, button_now.bottom]
                                    if button_now is not None else None
                                ),
                                "button_center_fraction": (
                                    [button_now.center_x_fraction, button_now.center_y_fraction]
                                    if button_now is not None else None
                                ),
                                "element_at_pointer_runtime_id": list(at_pointer_runtime),
                                "element_at_pointer_control_type": at_pointer.control_type if at_pointer is not None else None,
                                "element_at_pointer_class_name": at_pointer.class_name if at_pointer is not None else None,
                                "element_at_pointer_has_focus": at_pointer.has_keyboard_focus if at_pointer is not None else None,
                                "element_at_pointer_error": str(at_pointer_error or "") or None,
                                "focused_runtime_id": list(focused_runtime),
                                "focused_control_type": focused_now.control_type if focused_now is not None else None,
                                "focused_class_name": focused_now.class_name if focused_now is not None else None,
                                "focused_has_focus": focused_now.has_keyboard_focus if focused_now is not None else None,
                                "focused_error": str(focused_error or "") or None,
                                "pointer_hits_exact_button": bool(button_runtime and at_pointer_runtime == button_runtime),
                                "exact_button_has_focus": bool(button_runtime and focused_runtime == button_runtime),
                                "app_title": app.title(),
                            }
                        except Exception as exc:
                            submit_hit_trace = {"error": f"{type(exc).__name__}: {exc}", "app_title": app.title()}
                        state_trace.append({"label": "submit_hit_test", **submit_hit_trace})
                        last_trace = None
                    entry = {
                        "label": label,
                        "stage": current_state.stage,
                        "next_action": current_state.next_action,
                        "intent_kind": intent_observation.get("kind"),
                        "observation_phase": observation.get("phase"),
                        "source_sha256": source_observation.get("text_sha256"),
                        "target_has_focus": focused_observation.get("has_keyboard_focus"),
                        "local_failure": str(current_state.data.get("local_failure") or "") or None,
                        "latest_failure": {
                            "kind": latest_failure.get("kind"),
                            "source": latest_failure.get("source"),
                            "failure": latest_failure.get("failure"),
                            "evidence_fingerprint": latest_failure.get("evidence_fingerprint"),
                        } if latest_failure else None,
                        "pointer_execution": {
                            "status": pointer_execution.get("status"),
                            "input_sent": pointer_execution.get("input_sent"),
                            "success": pointer_execution.get("success"),
                            "error": pointer_execution.get("error"),
                        } if pointer_execution else None,
                        "text_execution": {
                            "status": text_execution.get("status"),
                            "input_sent": text_execution.get("input_sent"),
                            "success": text_execution.get("success"),
                            "error": text_execution.get("error"),
                        } if text_execution else None,
                        "verification": {
                            "kind": verification.get("kind"),
                            "verified": verification.get("verified"),
                            "error": verification.get("error"),
                        } if verification else None,
                        "submit_dispatched": progress.get("submit_dispatched"),
                        "app_title": app.title(),
                        "evidence_fingerprint": resident._evidence_fingerprint(event.event_id),
                    }
                    signature = json.dumps(entry, ensure_ascii=False, sort_keys=True, default=str)
                    if signature != last_trace:
                        state_trace.append(entry)
                        last_trace = signature

                deadline = time.monotonic() + 35
                while time.monotonic() < deadline and result is None:
                    state = resident.store.get_working_state(); intent = state.data.get("native_action_intent")
                    actions = [a for a in resident.body.recent_actions(256) if a.event_id == event.event_id]
                    record_state("before_pulse")
                    if not drifted and isinstance(intent, dict) and intent.get("kind") == "keyboard_text" and not any(a.kind == "keyboard_text" for a in actions):
                        source.write_text(NEW_VALUE, encoding="utf-8"); self._yesterday(source); drifted = True
                        state_trace.append({"label":"source_mutated_before_keyboard", "app_title":app.title()})
                        last_trace = None
                    app.activate(); current = resident.live_once()
                    record_state("after_pulse")
                    pulse_state = resident.store.get_working_state()
                    if first_failure is None and pulse_state.current_event_id == event.event_id:
                        local_failure = str(pulse_state.data.get("local_failure") or "")
                        records = list(pulse_state.data.get("native_action_failure_records") or [])
                        terminal = pulse_state.data.get("terminal_failure")
                        if local_failure or records or isinstance(terminal, dict):
                            pulse_intent = pulse_state.data.get("native_action_intent")
                            first_failure = {
                                "stage": pulse_state.stage,
                                "next_action": pulse_state.next_action,
                                "local_failure": local_failure or None,
                                "intent_kind": pulse_intent.get("kind") if isinstance(pulse_intent, dict) else None,
                                "failure_records": records[-2:],
                                "pointer_precondition": pulse_state.data.get("native_pointer_click_precondition"),
                                "semantic_precondition": pulse_state.data.get("native_pointer_click_semantic_precondition"),
                                "automation_target": pulse_state.data.get("native_pointer_click_automation_target"),
                                "terminal_failure": terminal,
                            }
                    if current is not None and current.event.event_id == event.event_id: result = current
                    if drifted and not any(a.kind == "keyboard_text" for a in resident.body.recent_actions(256) if a.event_id == event.event_id):
                        failure = str(resident.store.get_working_state().data.get("local_failure") or "")
                        stale_rejected |= "workspace source identity changed after investigation" in failure
                    if result is None: time.sleep(.03)

                diagnostic_state = resident.store.get_working_state()
                diagnostic_observation = diagnostic_state.data.get(observation_key)
                diagnostic_actions = [
                    {"kind": action.kind, "success": action.success, "error": action.error}
                    for action in reversed(resident.body.recent_actions(512))
                    if action.event_id == event.event_id
                ]
                self.assertTrue(
                    drifted,
                    "source-drift barrier was never reached: "
                    + json.dumps({
                        "stage": diagnostic_state.stage,
                        "next_action": diagnostic_state.next_action,
                        "result": repr(result),
                        "event_status": str(resident.store.get_event(event.event_id).status),
                        "failure_records": diagnostic_state.data.get("native_action_failure_records"),
                        "first_failure": first_failure,
                        "submit_hit_trace": submit_hit_trace,
                        "evidence_fingerprint": resident._evidence_fingerprint(event.event_id),
                        "observation_phase": diagnostic_observation.get("phase") if isinstance(diagnostic_observation, dict) else None,
                        "observation_failure": diagnostic_observation.get("failure") if isinstance(diagnostic_observation, dict) else None,
                        "actions": diagnostic_actions,
                        "state_trace": state_trace,
                    }, ensure_ascii=False, sort_keys=True, default=str),
                )
                self.assertTrue(stale_rejected); self.assertIsNotNone(result)
                if not result.success:
                    failure_evidence = {
                        "result_reason": result.reason,
                        "event_status": str(resident.store.get_event(event.event_id).status),
                        "event_last_error": resident.store.get_event(event.event_id).last_error,
                        "app_title": app.title(),
                        "first_failure": first_failure,
                        "submit_hit_trace": submit_hit_trace,
                        "actions": diagnostic_actions,
                        "state_trace": state_trace,
                    }
                    print("ZN_FILE_DESKTOP_GOAL_FAILURE_TRACE=" + json.dumps(
                        failure_evidence, ensure_ascii=False, sort_keys=True, default=str
                    ))
                    self.fail(
                        "desktop goal failed after source-drift recovery: "
                        + json.dumps(failure_evidence, ensure_ascii=False, sort_keys=True, default=str)
                    )
                self.assertEqual(result.model_invocations, 2); self.assertEqual(proposal.calls, 2)
                self.assertEqual(app.title(), SUCCESS_TITLE)
                actions = [a for a in resident.body.recent_actions(512) if a.event_id == event.event_id]
                self.assertEqual(sum(a.kind == "keyboard_text" for a in actions), 1)
                self.assertEqual(sum(a.kind == "pointer_click" for a in actions), 2)
                outcome = resident.store.get_event_outcome(event.event_id); self.assertTrue(outcome.success); self.assertIn(SUCCESS_TITLE, outcome.response)
                progress = ledger.progress(thread, event.event_id); self.assertTrue(progress["terminal"]); self.assertTrue(progress["finalized"])
                print("ZN_FILE_DESKTOP_GOAL_E2E_EVIDENCE=" + json.dumps({
                    "ordinary_language":True,"regex_fast_path":False,"initial_input_focus":False,
                    "source_drift_before_input":True,"stale_source_rejected":True,
                    "keyboard_actions":1,"pointer_click_actions":2,"submit_clicks":1,
                    "final_title":app.title(),"model_invocations":result.model_invocations,
                }, ensure_ascii=False, sort_keys=True))
            finally:
                if resident is not None: resident.store.close()
                app.close()


if __name__ == "__main__": unittest.main(verbosity=2)