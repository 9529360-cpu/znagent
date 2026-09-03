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
from zn_agent.core.desktop_task_goal import DESKTOP_TASK_GOAL_KIND, explicit_desktop_task_goal_hint
from zn_agent.core.models import ModelRoute
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from test_windows_interactive_text_entry import WindowsInteractiveTextEntryE2ETests


TASK = "昨天那个订单文件里有编号，在我现在开的软件里帮我把对应记录找出来。"
SOURCE_VALUE = "ORDER-GROUND-731"
START_TITLE = "ZN Desktop Semantic Grounding E2E"
SUCCESS_TITLE = "ZN 对应订单记录已打开"
INPUT_NAME = "订单编号"
BUTTON_NAME = "查找"


def _user32():
    api = ctypes.WinDLL("user32", use_last_error=True)
    api.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    api.ShowWindow.restype = wintypes.BOOL
    api.BringWindowToTop.argtypes = [wintypes.HWND]
    api.BringWindowToTop.restype = wintypes.BOOL
    api.SetForegroundWindow.argtypes = [wintypes.HWND]
    api.SetForegroundWindow.restype = wintypes.BOOL
    api.GetForegroundWindow.argtypes = []
    api.GetForegroundWindow.restype = wintypes.HWND
    api.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    api.GetWindowTextLengthW.restype = ctypes.c_int
    api.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    api.GetWindowTextW.restype = ctypes.c_int
    api.IsWindowVisible.argtypes = [wintypes.HWND]
    api.IsWindowVisible.restype = wintypes.BOOL
    api.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    api.GetWindowThreadProcessId.restype = wintypes.DWORD
    api.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    api.PostMessageW.restype = wintypes.BOOL
    return api


class _SemanticProposal:
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
                "input_name": "用于识别对应订单的字段",
                "button_name": "执行查找对应记录的操作",
                "expected_title": None,
                "source_modified_yesterday": True,
            }
        return CognitiveIncrement(
            text=json.dumps(value, ensure_ascii=False),
            provider="e2e-cognition",
            model="bounded-language-fixture",
        )


class _GroundingOrderApp:
    def __init__(self, root: Path, *, duplicate_order_id: bool = False):
        self.script = root / (
            "semantic-grounding-duplicate.ps1"
            if duplicate_order_id
            else "semantic-grounding.ps1"
        )
        self.recreate_flag = root / "recreate-controls.flag"
        self.duplicate_order_id = duplicate_order_id
        self.process: subprocess.Popen | None = None
        self.hwnd = 0

    def start(self) -> None:
        self.script.write_text(self._script(), encoding="utf-8-sig")
        self.process = subprocess.Popen(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-Sta",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.script),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("semantic grounding desktop fixture exited early")
            self.hwnd = self._find_window()
            if self.hwnd:
                self.activate()
                return
            time.sleep(0.05)
        raise RuntimeError("semantic grounding desktop fixture window was not found")

    def activate(self) -> None:
        user32 = _user32()
        user32.ShowWindow(self.hwnd, 5)
        user32.BringWindowToTop(self.hwnd)
        user32.SetForegroundWindow(self.hwnd)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if int(user32.GetForegroundWindow() or 0) == self.hwnd:
                return
            time.sleep(0.02)
        raise RuntimeError("semantic grounding fixture could not become foreground")

    def trigger_recreation(self) -> None:
        if self.duplicate_order_id:
            raise RuntimeError("duplicate fixture does not support recreation")
        self.recreate_flag.write_text("recreate", encoding="utf-8")

    def title(self) -> str:
        user32 = _user32()
        length = user32.GetWindowTextLengthW(self.hwnd)
        buffer = ctypes.create_unicode_buffer(max(1, length + 1))
        user32.GetWindowTextW(self.hwnd, buffer, len(buffer))
        return buffer.value

    def close(self) -> None:
        if self.hwnd:
            try:
                _user32().PostMessageW(self.hwnd, 0x0010, 0, 0)
            except Exception:
                pass
        if self.process is not None:
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)

    def _find_window(self) -> int:
        user32 = _user32()
        callback_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [callback_t, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        matches: list[int] = []

        @callback_t
        def visit(hwnd, _):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if (
                self.process is not None
                and int(pid.value) == self.process.pid
                and user32.IsWindowVisible(hwnd)
            ):
                length = user32.GetWindowTextLengthW(hwnd)
                buffer = ctypes.create_unicode_buffer(max(1, length + 1))
                user32.GetWindowTextW(hwnd, buffer, len(buffer))
                if buffer.value == START_TITLE:
                    matches.append(int(hwnd))
            return True

        user32.EnumWindows(visit, 0)
        return matches[0] if len(matches) == 1 else 0

    def _script(self) -> str:
        duplicate = "$true" if self.duplicate_order_id else "$false"
        flag = str(self.recreate_flag).replace("'", "''")
        return f'''Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object System.Windows.Forms.Form
$form.Text = '{START_TITLE}'
$form.StartPosition = 'CenterScreen'
$form.ClientSize = '760,360'
$duplicateOrderId = {duplicate}
$recreateFlag = '{flag}'
$script:orderBox = $null
$script:orderBox2 = $null
$script:searchButton = $null

$customer = New-Object System.Windows.Forms.TextBox
$customer.AccessibleName = '客户名称'
$customer.Location = '70,55'
$customer.Size = '430,38'
$customer.Font = 'Segoe UI,14'
$notes = New-Object System.Windows.Forms.TextBox
$notes.AccessibleName = '备注'
$notes.Location = '70,175'
$notes.Size = '430,38'
$notes.Font = 'Segoe UI,14'
$cancel = New-Object System.Windows.Forms.Button
$cancel.AccessibleName = '取消'
$cancel.Text = '取消'
$cancel.Location = '520,245'
$cancel.Size = '125,45'
$form.Controls.AddRange(@($customer, $notes, $cancel))

function Add-OrderControls {{
    $script:orderBox = New-Object System.Windows.Forms.TextBox
    $script:orderBox.AccessibleName = '{INPUT_NAME}'
    $script:orderBox.Location = '70,115'
    $script:orderBox.Size = '430,38'
    $script:orderBox.Font = 'Segoe UI,14'
    $script:searchButton = New-Object System.Windows.Forms.Button
    $script:searchButton.AccessibleName = '{BUTTON_NAME}'
    $script:searchButton.Text = '{BUTTON_NAME}'
    $script:searchButton.Location = '520,113'
    $script:searchButton.Size = '125,45'
    $script:searchButton.Add_Click({{
        if ($script:orderBox.Text -eq '{SOURCE_VALUE}') {{
            $form.Text = '{SUCCESS_TITLE}'
        }}
    }})
    $form.Controls.Add($script:orderBox)
    $form.Controls.Add($script:searchButton)
    if ($duplicateOrderId) {{
        $script:orderBox2 = New-Object System.Windows.Forms.TextBox
        $script:orderBox2.AccessibleName = '{INPUT_NAME}'
        $script:orderBox2.Location = '70,225'
        $script:orderBox2.Size = '430,38'
        $script:orderBox2.Font = 'Segoe UI,14'
        $form.Controls.Add($script:orderBox2)
    }}
}}

Add-OrderControls
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 80
$timer.Add_Tick({{
    if (-not $duplicateOrderId -and (Test-Path -LiteralPath $recreateFlag)) {{
        Remove-Item -LiteralPath $recreateFlag -Force -ErrorAction SilentlyContinue
        if ($script:orderBox -ne $null) {{
            $form.Controls.Remove($script:orderBox)
            $script:orderBox.Dispose()
            $script:orderBox = $null
        }}
        if ($script:searchButton -ne $null) {{
            $form.Controls.Remove($script:searchButton)
            $script:searchButton.Dispose()
            $script:searchButton = $null
        }}
        $dummy = New-Object System.Windows.Forms.TextBox
        $dummy.AccessibleName = '临时刷新占位'
        $dummy.Location = '-1000,-1000'
        $form.Controls.Add($dummy)
        $dummy.CreateControl()
        Add-OrderControls
        $form.Controls.Remove($dummy)
        $dummy.Dispose()
        $cancel.Focus()
    }}
}})
$timer.Start()
$form.Add_Shown({{ $cancel.Focus() }})
[System.Windows.Forms.Application]::Run($form)
'''


class WindowsInteractiveDesktopSemanticGroundingE2ETests(unittest.TestCase):
    @staticmethod
    def _stamp_yesterday(path: Path) -> None:
        now = datetime.now().astimezone()
        stamp = datetime.combine(
            now.date() - timedelta(days=1),
            dt_time(12),
            tzinfo=now.tzinfo,
        ).timestamp()
        os.utime(path, (stamp, stamp))

    @staticmethod
    def _enable_cognition(resident, proposal: _SemanticProposal) -> None:
        resident.kernel.reconfigure_resources(
            routes=[
                ModelRoute(
                    route_id="e2e-desktop-semantic-grounding",
                    provider="fixture",
                    model="bounded-language-fixture",
                    capabilities={"language_understanding": 1.0, "general": 0.8},
                )
            ],
            worker_factory=CognitiveResourceWorkerFactory(
                resource_builder=lambda _route: proposal,
            ),
            max_attempts=1,
            resource_status={"available": True, "error": None},
        )

    def test_semantic_grounding_rejects_stale_runtime_id_then_regrounds_and_completes(self) -> None:
        WindowsInteractiveTextEntryE2ETests._require_input_desktop()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            source = workspace / "订单资料.txt"
            source.write_text(SOURCE_VALUE, encoding="utf-8")
            self._stamp_yesterday(source)
            app = _GroundingOrderApp(root)
            app.start()
            resident = None
            try:
                resident = build_resident_runtime(
                    config={"model": {}},
                    store_path=root / "kernel.db",
                )
                proposal = _SemanticProposal()
                self._enable_cognition(resident, proposal)
                ledger = RecoveryBoundedWorkLedger(resident)
                thread = "desktop-semantic-grounding-e2e"
                ledger.create_thread(thread_id=thread)
                ledger.attach_workspace(thread, workspace)
                app.activate()
                _, event = ledger.start(
                    thread,
                    TASK,
                    payload={"model_policy": "on_demand"},
                )
                self.assertIsNone(
                    explicit_desktop_task_goal_hint(event),
                    "real acceptance task must miss the deterministic desktop regex fast path",
                )

                observation_key = getattr(
                    resident,
                    "_DESKTOP_TASK_OBSERVATION_KEY",
                    "resident_desktop_task_observation",
                )
                result = None
                recreated = False
                stale_runtime_rejected = False
                regrounded = False
                old_edit_runtime: tuple[int, ...] = ()
                old_button_runtime: tuple[int, ...] = ()
                new_edit_runtime: tuple[int, ...] = ()
                new_button_runtime: tuple[int, ...] = ()
                trace: list[dict] = []
                deadline = time.monotonic() + 45

                while time.monotonic() < deadline and result is None:
                    state = resident.store.get_working_state()
                    observation = state.data.get(observation_key)
                    observation = observation if isinstance(observation, dict) else {}
                    target = observation.get("target")
                    target = target if isinstance(target, dict) else {}
                    phase = str(observation.get("phase") or "")
                    actions = [
                        action
                        for action in resident.body.recent_actions(512)
                        if action.event_id == event.event_id
                    ]

                    if (
                        not recreated
                        and phase == "focus"
                        and target.get("runtime_id")
                        and not any(
                            action.kind in {"pointer_click", "keyboard_text"}
                            for action in actions
                        )
                    ):
                        old_edit_runtime = tuple(int(v) for v in target["runtime_id"])
                        foreground = observation.get("foreground") or {}
                        old_button = resident.named_automation_control.find_unique_button(
                            process_id=int(foreground["process_id"]),
                            process_name=str(foreground["process_name"]).lower(),
                            name=BUTTON_NAME,
                        )
                        old_button_runtime = tuple(old_button.runtime_id)
                        app.trigger_recreation()
                        refresh_deadline = time.monotonic() + 8
                        while time.monotonic() < refresh_deadline:
                            app.activate()
                            try:
                                fresh_edit = resident.named_automation_control.find_unique_edit(
                                    process_id=int(foreground["process_id"]),
                                    process_name=str(foreground["process_name"]).lower(),
                                    name=INPUT_NAME,
                                )
                                fresh_button = resident.named_automation_control.find_unique_button(
                                    process_id=int(foreground["process_id"]),
                                    process_name=str(foreground["process_name"]).lower(),
                                    name=BUTTON_NAME,
                                )
                            except Exception:
                                time.sleep(0.05)
                                continue
                            if (
                                tuple(fresh_edit.runtime_id) != old_edit_runtime
                                and tuple(fresh_button.runtime_id) != old_button_runtime
                            ):
                                new_edit_runtime = tuple(fresh_edit.runtime_id)
                                new_button_runtime = tuple(fresh_button.runtime_id)
                                recreated = True
                                break
                            time.sleep(0.05)
                        self.assertTrue(
                            recreated,
                            "fixture recreated controls but UIA identities did not change",
                        )
                        trace.append(
                            {
                                "label": "controls_recreated_after_resident_binding",
                                "old_edit_runtime": list(old_edit_runtime),
                                "new_edit_runtime": list(new_edit_runtime),
                                "old_button_runtime": list(old_button_runtime),
                                "new_button_runtime": list(new_button_runtime),
                            }
                        )
                        continue

                    app.activate()
                    current = resident.live_once()
                    post = resident.store.get_working_state()
                    post_observation = post.data.get(observation_key)
                    post_observation = (
                        post_observation if isinstance(post_observation, dict) else {}
                    )
                    post_target = post_observation.get("target")
                    post_target = post_target if isinstance(post_target, dict) else {}
                    failures = list(post.data.get("native_action_failure_records") or [])
                    failure_text = "\n".join(
                        [str(post.data.get("local_failure") or "")]
                        + [json.dumps(item, ensure_ascii=False, default=str) for item in failures]
                    )
                    if recreated and "RuntimeId changed before input" in failure_text:
                        stale_runtime_rejected = True
                    if (
                        recreated
                        and post_target.get("runtime_id")
                        and tuple(int(v) for v in post_target["runtime_id"]) == new_edit_runtime
                    ):
                        regrounded = True
                    if recreated and not regrounded:
                        self.assertFalse(
                            any(
                                action.kind == "keyboard_text"
                                for action in resident.body.recent_actions(512)
                                if action.event_id == event.event_id
                            ),
                            "text input occurred before stale desktop grounding was replaced",
                        )
                    trace.append(
                        {
                            "stage": post.stage,
                            "next_action": post.next_action,
                            "phase": post_observation.get("phase"),
                            "target_runtime": post_target.get("runtime_id"),
                            "local_failure": str(post.data.get("local_failure") or "") or None,
                            "app_title": app.title(),
                        }
                    )
                    if current is not None and current.event.event_id == event.event_id:
                        result = current
                    if result is None:
                        time.sleep(0.03)

                self.assertTrue(recreated, json.dumps(trace[-12:], ensure_ascii=False, default=str))
                self.assertTrue(
                    stale_runtime_rejected,
                    "old UIA action authority was not explicitly rejected: "
                    + json.dumps(trace[-20:], ensure_ascii=False, default=str),
                )
                self.assertTrue(
                    regrounded,
                    "Resident never replaced stale UIA binding with the freshly recreated control: "
                    + json.dumps(trace[-20:], ensure_ascii=False, default=str),
                )
                self.assertIsNotNone(result, json.dumps(trace[-20:], ensure_ascii=False, default=str))
                self.assertTrue(result.success, result.reason)
                self.assertEqual(result.model_invocations, 2)
                self.assertEqual(proposal.calls, 2)
                self.assertEqual(app.title(), SUCCESS_TITLE)
                self.assertIn("客户名称", proposal.questions[1])
                self.assertIn(INPUT_NAME, proposal.questions[1])
                self.assertIn("备注", proposal.questions[1])
                self.assertIn(BUTTON_NAME, proposal.questions[1])
                self.assertIn("取消", proposal.questions[1])
                self.assertNotIn(str(list(old_edit_runtime)), proposal.questions[1])

                actions = [
                    action
                    for action in resident.body.recent_actions(512)
                    if action.event_id == event.event_id
                ]
                self.assertEqual(sum(action.kind == "keyboard_text" for action in actions), 1)
                self.assertEqual(sum(action.kind == "pointer_click" for action in actions), 2)
                outcome = resident.store.get_event_outcome(event.event_id)
                self.assertIsNotNone(outcome)
                self.assertTrue(outcome.success)
                self.assertIn(SUCCESS_TITLE, outcome.response)
                print(
                    "ZN_DESKTOP_SEMANTIC_GROUNDING_E2E_EVIDENCE="
                    + json.dumps(
                        {
                            "ordinary_language": True,
                            "regex_fast_path": False,
                            "fresh_candidates": ["客户名称", INPUT_NAME, "备注", BUTTON_NAME, "取消"],
                            "old_edit_runtime": list(old_edit_runtime),
                            "new_edit_runtime": list(new_edit_runtime),
                            "stale_runtime_rejected": stale_runtime_rejected,
                            "regrounded": regrounded,
                            "keyboard_actions": 1,
                            "pointer_click_actions": 2,
                            "final_title": app.title(),
                            "model_invocations": result.model_invocations,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            finally:
                if resident is not None:
                    resident.store.close()
                app.close()

    def test_duplicate_equally_named_order_fields_fail_closed_before_input(self) -> None:
        WindowsInteractiveTextEntryE2ETests._require_input_desktop()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            source = workspace / "订单资料.txt"
            source.write_text(SOURCE_VALUE, encoding="utf-8")
            self._stamp_yesterday(source)
            app = _GroundingOrderApp(root, duplicate_order_id=True)
            app.start()
            resident = None
            try:
                resident = build_resident_runtime(
                    config={"model": {}},
                    store_path=root / "kernel.db",
                )
                proposal = _SemanticProposal()
                self._enable_cognition(resident, proposal)
                ledger = RecoveryBoundedWorkLedger(resident)
                thread = "desktop-semantic-grounding-ambiguity-e2e"
                ledger.create_thread(thread_id=thread)
                ledger.attach_workspace(thread, workspace)
                app.activate()
                _, event = ledger.start(
                    thread,
                    TASK,
                    payload={"model_policy": "on_demand"},
                )
                self.assertIsNone(explicit_desktop_task_goal_hint(event))

                result = None
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline and result is None:
                    app.activate()
                    current = resident.live_once()
                    if current is not None and current.event.event_id == event.event_id:
                        result = current
                    if result is None:
                        time.sleep(0.03)

                self.assertIsNotNone(result)
                self.assertFalse(result.success)
                self.assertIn("ambiguous", result.reason)
                self.assertEqual(proposal.calls, 2)
                actions = [
                    action
                    for action in resident.body.recent_actions(512)
                    if action.event_id == event.event_id
                ]
                self.assertEqual(sum(action.kind == "keyboard_text" for action in actions), 0)
                self.assertEqual(sum(action.kind == "pointer_click" for action in actions), 0)
                self.assertEqual(app.title(), START_TITLE)
                print(
                    "ZN_DESKTOP_SEMANTIC_GROUNDING_AMBIGUITY_EVIDENCE="
                    + json.dumps(
                        {
                            "duplicate_accessible_name": INPUT_NAME,
                            "cognition_calls": proposal.calls,
                            "keyboard_actions": 0,
                            "pointer_click_actions": 0,
                            "result_success": result.success,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            finally:
                if resident is not None:
                    resident.store.close()
                app.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
