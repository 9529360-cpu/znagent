from __future__ import annotations

import ctypes
import json
import tempfile
import time
import unittest
from ctypes import wintypes
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.desktop_task_goal import explicit_desktop_task_goal_hint
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.resident_server import ResidentSocketService
from test_windows_interactive_desktop_semantic_grounding import (
    BUTTON_NAME,
    INPUT_NAME,
    SOURCE_VALUE,
    START_TITLE,
    SUCCESS_TITLE,
    WindowsInteractiveDesktopSemanticGroundingE2ETests,
    _GroundingOrderApp,
    _SemanticProposal,
    _user32,
)
from test_windows_interactive_text_entry import WindowsInteractiveTextEntryE2ETests


TASK = "找到昨天那份订单资料，把里面的编号拿到我现在开的软件里，找到对应记录并确认处理好了。"
MODAL_TITLE = "更新提示"
SAFE_ACTION = "稍后继续"
RISKY_ACTION = "立即更新"
_MODAL_STATE_KEY = "resident_desktop_modal_recovery"


class _ModalRecoveryOrderApp(_GroundingOrderApp):
    def __init__(self, root: Path):
        super().__init__(root)
        self.modal_flag = root / "show-modal.flag"
        self.safe_count_file = root / "safe-dismiss-count.txt"
        self.risky_count_file = root / "risky-update-count.txt"

    def trigger_modal(self) -> None:
        self.modal_flag.write_text("show", encoding="utf-8")

    def modal_hwnd(self) -> int:
        return self._find_visible_title(MODAL_TITLE)

    def safe_count(self) -> int:
        return self._read_count(self.safe_count_file)

    def risky_count(self) -> int:
        return self._read_count(self.risky_count_file)

    @staticmethod
    def _read_count(path: Path) -> int:
        try:
            return int(path.read_text(encoding="utf-8-sig").strip() or "0")
        except (OSError, ValueError):
            return 0

    def _find_visible_title(self, title: str) -> int:
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
                if buffer.value == title:
                    matches.append(int(hwnd))
            return True

        user32.EnumWindows(visit, 0)
        return matches[0] if len(matches) == 1 else 0

    def _script(self) -> str:
        modal_flag = str(self.modal_flag).replace("'", "''")
        safe_file = str(self.safe_count_file).replace("'", "''")
        risky_file = str(self.risky_count_file).replace("'", "''")
        return f'''Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object System.Windows.Forms.Form
$form.Text = '{START_TITLE}'
$form.StartPosition = 'CenterScreen'
$form.ClientSize = '760,360'
$modalFlag = '{modal_flag}'
$safeFile = '{safe_file}'
$riskyFile = '{risky_file}'
$script:orderBox = $null
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
        if ($script:orderBox.Text -eq '{SOURCE_VALUE}') {{ $form.Text = '{SUCCESS_TITLE}' }}
    }})
    $form.Controls.Add($script:orderBox)
    $form.Controls.Add($script:searchButton)
}}

function Recreate-OrderControls {{
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
    $dummy.AccessibleName = 'modal-dismiss-refresh-placeholder'
    $dummy.Location = '-1000,-1000'
    $form.Controls.Add($dummy)
    $dummy.CreateControl()
    Add-OrderControls
    $form.Controls.Remove($dummy)
    $dummy.Dispose()
    $cancel.Focus()
}}

function Increment-Count([string]$path) {{
    $count = 0
    if (Test-Path -LiteralPath $path) {{
        try {{ $count = [int](Get-Content -LiteralPath $path -Raw) }} catch {{ $count = 0 }}
    }}
    [IO.File]::WriteAllText($path, [string]($count + 1))
}}

Add-OrderControls
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 60
$timer.Add_Tick({{
    if (Test-Path -LiteralPath $modalFlag) {{
        Remove-Item -LiteralPath $modalFlag -Force -ErrorAction SilentlyContinue
        $dialog = New-Object System.Windows.Forms.Form
        $dialog.Text = '{MODAL_TITLE}'
        $dialog.StartPosition = 'CenterParent'
        $dialog.ClientSize = '430,190'
        $dialog.FormBorderStyle = 'FixedDialog'
        $dialog.MinimizeBox = $false
        $dialog.MaximizeBox = $false
        $message = New-Object System.Windows.Forms.Label
        $message.Text = '有可用更新。当前工作可以稍后继续。'
        $message.AccessibleName = '有可用更新。当前工作可以稍后继续。'
        $message.Location = '35,30'
        $message.Size = '360,45'
        $safe = New-Object System.Windows.Forms.Button
        $safe.Text = '{SAFE_ACTION}'
        $safe.AccessibleName = '{SAFE_ACTION}'
        $safe.Location = '85,105'
        $safe.Size = '115,42'
        $risky = New-Object System.Windows.Forms.Button
        $risky.Text = '{RISKY_ACTION}'
        $risky.AccessibleName = '{RISKY_ACTION}'
        $risky.Location = '230,105'
        $risky.Size = '115,42'
        $safe.Add_Click({{ Increment-Count $safeFile; $dialog.Close() }})
        $risky.Add_Click({{ Increment-Count $riskyFile; $dialog.Close() }})
        $dialog.Controls.AddRange(@($message, $safe, $risky))
        [void]$dialog.ShowDialog($form)
        $dialog.Dispose()
        Recreate-OrderControls
    }}
}})
$timer.Start()
$form.Add_Shown({{ $cancel.Focus() }})
[System.Windows.Forms.Application]::Run($form)
'''


class WindowsInteractiveDesktopModalRecoveryE2ETests(unittest.TestCase):
    def test_unexpected_same_process_modal_is_safely_dismissed_then_original_work_regrounds(self) -> None:
        WindowsInteractiveTextEntryE2ETests._require_input_desktop()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            source = workspace / "订单资料.txt"
            source.write_text(SOURCE_VALUE, encoding="utf-8")
            WindowsInteractiveDesktopSemanticGroundingE2ETests._stamp_yesterday(source)
            app = _ModalRecoveryOrderApp(root)
            app.start()
            resident = None
            try:
                resident = build_resident_runtime(config={"model": {}}, store_path=root / "kernel.db")
                service = ResidentSocketService(ResidentRpcServer(resident=resident))
                self.assertIs(resident.visual_region, service.visual_region)
                WindowsInteractiveDesktopSemanticGroundingE2ETests._enable_cognition(
                    resident, _SemanticProposal()
                )
                ledger = RecoveryBoundedWorkLedger(resident)
                thread = "desktop-modal-recovery-e2e"
                ledger.create_thread(thread_id=thread)
                ledger.attach_workspace(thread, workspace)
                app.activate()
                _, event = ledger.start(thread, TASK, payload={"model_policy": "on_demand"})
                self.assertIsNone(explicit_desktop_task_goal_hint(event))

                observation_key = getattr(
                    resident,
                    "_DESKTOP_TASK_OBSERVATION_KEY",
                    "resident_desktop_task_observation",
                )
                result = None
                modal_triggered = False
                modal_seen = False
                old_edit_runtime: tuple[int, ...] = ()
                fresh_edit_runtime: tuple[int, ...] = ()
                trace: list[dict] = []
                deadline = time.monotonic() + 55

                while time.monotonic() < deadline and result is None:
                    state = resident.store.get_working_state()
                    observation = state.data.get(observation_key)
                    observation = observation if isinstance(observation, dict) else {}
                    target = observation.get("target")
                    target = target if isinstance(target, dict) else {}
                    actions = [
                        action
                        for action in resident.body.recent_actions(512)
                        if action.event_id == event.event_id
                    ]
                    if (
                        not modal_triggered
                        and str(observation.get("phase") or "") == "focus"
                        and target.get("runtime_id")
                        and not any(a.kind in {"pointer_click", "keyboard_text"} for a in actions)
                    ):
                        old_edit_runtime = tuple(int(v) for v in target["runtime_id"])
                        app.trigger_modal()
                        modal_deadline = time.monotonic() + 8
                        while time.monotonic() < modal_deadline:
                            if app.modal_hwnd():
                                modal_seen = True
                                break
                            time.sleep(0.03)
                        self.assertTrue(modal_seen, "fixture did not show the real modal dialog")
                        modal_triggered = True
                        continue

                    if not modal_seen or not app.modal_hwnd():
                        try:
                            app.activate()
                        except RuntimeError:
                            pass
                    current = resident.live_once()
                    post = resident.store.get_working_state()
                    recovery = post.data.get(_MODAL_STATE_KEY)
                    recovery = recovery if isinstance(recovery, dict) else {}
                    post_observation = post.data.get(observation_key)
                    post_observation = post_observation if isinstance(post_observation, dict) else {}
                    post_target = post_observation.get("target")
                    post_target = post_target if isinstance(post_target, dict) else {}
                    if (
                        modal_triggered
                        and app.safe_count() == 1
                        and not app.modal_hwnd()
                        and post_target.get("runtime_id")
                    ):
                        candidate = tuple(int(v) for v in post_target["runtime_id"])
                        if candidate != old_edit_runtime:
                            fresh_edit_runtime = candidate
                    trace.append(
                        {
                            "stage": post.stage,
                            "next_action": post.next_action,
                            "desktop_phase": post_observation.get("phase"),
                            "modal_phase": recovery.get("phase"),
                            "safe_count": app.safe_count(),
                            "risky_count": app.risky_count(),
                            "app_title": app.title(),
                            "local_failure": str(post.data.get("local_failure") or "") or None,
                        }
                    )
                    if current is not None and current.event.event_id == event.event_id:
                        result = current
                    if result is None:
                        time.sleep(0.025)

                self.assertTrue(modal_triggered, json.dumps(trace[-20:], ensure_ascii=False))
                self.assertTrue(modal_seen)
                self.assertIsNotNone(result, json.dumps(trace[-30:], ensure_ascii=False))
                self.assertTrue(result.success, result.reason)
                self.assertEqual(app.safe_count(), 1)
                self.assertEqual(app.risky_count(), 0)
                self.assertEqual(app.title(), SUCCESS_TITLE)
                self.assertTrue(old_edit_runtime)
                self.assertTrue(fresh_edit_runtime)
                self.assertNotEqual(old_edit_runtime, fresh_edit_runtime)

                final_state = resident.store.get_working_state()
                recovery = final_state.data.get(_MODAL_STATE_KEY)
                self.assertIsInstance(recovery, dict)
                modal = recovery.get("modal") or {}
                recovered = recovery.get("recovered_parent") or {}
                self.assertEqual(modal.get("dialog_title"), MODAL_TITLE)
                self.assertEqual(modal.get("safe_action_name"), SAFE_ACTION)
                self.assertTrue(modal.get("is_modal"))
                self.assertEqual(modal.get("parent_interaction_state"), 3)
                self.assertEqual(modal.get("owner_hwnd"), app.hwnd)
                self.assertEqual(modal.get("root_owner_hwnd"), modal.get("dialog_hwnd"))
                self.assertEqual(modal.get("parent_root_owner_hwnd"), app.hwnd)
                self.assertEqual(recovery.get("dispatch_count"), 1)
                self.assertTrue(recovered.get("modal_absent"))
                self.assertFalse(recovered.get("dismissed_dialog_exists"))
                self.assertEqual(recovered.get("dismissed_dialog_hwnd"), modal.get("dialog_hwnd"))
                self.assertEqual(recovered.get("parent_hwnd"), app.hwnd)
                self.assertEqual(recovered.get("parent_interaction_state"), 2)
                self.assertTrue(recovered.get("foreground"))
                self.assertTrue(recovered.get("wait_for_input_idle"))
                self.assertEqual(tuple(recovery.get("pre_modal_target_runtime_id") or ()), old_edit_runtime)
                self.assertEqual(tuple(recovery.get("post_modal_target_runtime_id") or ()), fresh_edit_runtime)

                actions = [
                    action
                    for action in resident.body.recent_actions(512)
                    if action.event_id == event.event_id
                ]
                self.assertEqual(sum(a.kind == "keyboard_text" for a in actions), 1)
                self.assertEqual(sum(a.kind == "pointer_click" for a in actions), 3)
                outcome = resident.store.get_event_outcome(event.event_id)
                self.assertIsNotNone(outcome)
                self.assertTrue(outcome.success)
                self.assertIn(SUCCESS_TITLE, outcome.response)
                self.assertEqual(event.payload.get("work_thread_id"), thread)
                print(
                    "ZN_DESKTOP_MODAL_RECOVERY_E2E_EVIDENCE="
                    + json.dumps(
                        {
                            "same_root_work": True,
                            "parent_hwnd": app.hwnd,
                            "dialog_hwnd": modal.get("dialog_hwnd"),
                            "owner_hwnd": modal.get("owner_hwnd"),
                            "root_owner_hwnd": modal.get("root_owner_hwnd"),
                            "parent_root_owner_hwnd": modal.get("parent_root_owner_hwnd"),
                            "is_modal": modal.get("is_modal"),
                            "parent_interaction_state": modal.get("parent_interaction_state"),
                            "safe_action": modal.get("safe_action_name"),
                            "dialog_dispatch_count": recovery.get("dispatch_count"),
                            "modal_absent": recovered.get("modal_absent"),
                            "old_edit_runtime": list(old_edit_runtime),
                            "fresh_edit_runtime": list(fresh_edit_runtime),
                            "final_title": app.title(),
                            "unsafe_update_count": app.risky_count(),
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
