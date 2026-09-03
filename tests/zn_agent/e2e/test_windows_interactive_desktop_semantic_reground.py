from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from zn_agent.core.cognitive_resource import CognitiveIncrement
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.desktop_task_goal import DESKTOP_TASK_GOAL_KIND, explicit_desktop_task_goal_hint
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.resident_server import ResidentSocketService
from test_windows_interactive_desktop_semantic_grounding import (
    BUTTON_NAME,
    INPUT_NAME,
    SOURCE_VALUE,
    START_TITLE,
    SUCCESS_TITLE,
    TASK,
    WindowsInteractiveDesktopSemanticGroundingE2ETests,
    _GroundingOrderApp,
)
from test_windows_interactive_text_entry import WindowsInteractiveTextEntryE2ETests


FRESH_INPUT_NAME = "订单号"
FRESH_BUTTON_NAME = "查询订单"


class _SemanticRegroundProposal:
    def __init__(self):
        self.calls = 0
        self.questions: list[str] = []

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        self.calls += 1
        self.questions.append(question)
        if "Fresh Edit names:" not in question:
            value = {
                "kind": DESKTOP_TASK_GOAL_KIND,
                "source_name_hint": "订单",
                "input_name": "用于识别对应订单的字段",
                "button_name": "执行查找对应记录的操作",
                "expected_title": None,
                "source_modified_yesterday": True,
            }
        elif FRESH_INPUT_NAME in question and FRESH_BUTTON_NAME in question:
            value = {
                "status": "selected",
                "input_name": FRESH_INPUT_NAME,
                "button_name": FRESH_BUTTON_NAME,
            }
        else:
            value = {
                "status": "selected",
                "input_name": INPUT_NAME,
                "button_name": BUTTON_NAME,
            }
        return CognitiveIncrement(
            text=json.dumps(value, ensure_ascii=False),
            provider="e2e-cognition",
            model="bounded-language-fixture",
        )


class _SemanticDriftOrderApp(_GroundingOrderApp):
    def _script(self) -> str:
        flag = str(self.recreate_flag).replace("'", "''")
        return f'''Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object System.Windows.Forms.Form
$form.Text = '{START_TITLE}'
$form.StartPosition = 'CenterScreen'
$form.ClientSize = '760,360'
$recreateFlag = '{flag}'
$script:orderBox = $null
$script:searchButton = $null
$script:fresh = $false

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
    $inputName = if ($script:fresh) {{ '{FRESH_INPUT_NAME}' }} else {{ '{INPUT_NAME}' }}
    $buttonName = if ($script:fresh) {{ '{FRESH_BUTTON_NAME}' }} else {{ '{BUTTON_NAME}' }}
    $script:orderBox = New-Object System.Windows.Forms.TextBox
    $script:orderBox.AccessibleName = $inputName
    $script:orderBox.Location = '70,115'
    $script:orderBox.Size = '430,38'
    $script:orderBox.Font = 'Segoe UI,14'
    $script:searchButton = New-Object System.Windows.Forms.Button
    $script:searchButton.AccessibleName = $buttonName
    $script:searchButton.Text = $buttonName
    $script:searchButton.Location = '520,113'
    $script:searchButton.Size = '125,45'
    $script:searchButton.Add_Click({{
        if ($script:orderBox.Text -eq '{SOURCE_VALUE}') {{
            $form.Text = '{SUCCESS_TITLE}'
        }}
    }})
    $form.Controls.Add($script:orderBox)
    $form.Controls.Add($script:searchButton)
}}

Add-OrderControls
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 80
$timer.Add_Tick({{
    if (Test-Path -LiteralPath $recreateFlag) {{
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
        $script:fresh = $true
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


class WindowsInteractiveDesktopSemanticRegroundE2ETests(unittest.TestCase):
    def test_runtime_label_drift_is_resensed_semantically_then_completed(self) -> None:
        WindowsInteractiveTextEntryE2ETests._require_input_desktop()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            source = workspace / "订单资料.txt"
            source.write_text(SOURCE_VALUE, encoding="utf-8")
            WindowsInteractiveDesktopSemanticGroundingE2ETests._stamp_yesterday(source)
            app = _SemanticDriftOrderApp(root)
            app.start()
            resident = None
            try:
                resident = build_resident_runtime(
                    config={"model": {}},
                    store_path=root / "kernel.db",
                )
                service = ResidentSocketService(ResidentRpcServer(resident=resident))
                self.assertIs(resident.visual_region, service.visual_region)
                proposal = _SemanticRegroundProposal()
                WindowsInteractiveDesktopSemanticGroundingE2ETests._enable_cognition(
                    resident,
                    proposal,
                )
                ledger = RecoveryBoundedWorkLedger(resident)
                thread = "desktop-semantic-reground-e2e"
                ledger.create_thread(thread_id=thread)
                ledger.attach_workspace(thread, workspace)
                app.activate()
                _, event = ledger.start(
                    thread,
                    TASK,
                    payload={"model_policy": "on_demand"},
                )
                self.assertIsNone(explicit_desktop_task_goal_hint(event))

                observation_key = getattr(
                    resident,
                    "_DESKTOP_TASK_OBSERVATION_KEY",
                    "resident_desktop_task_observation",
                )
                result = None
                drifted = False
                old_action_rejected = False
                semantic_regrounded = False
                old_edit_runtime: tuple[int, ...] = ()
                fresh_edit_runtime: tuple[int, ...] = ()
                trace: list[dict] = []
                deadline = time.monotonic() + 50

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
                        not drifted
                        and phase == "focus"
                        and target.get("runtime_id")
                        and not any(action.kind == "pointer_click" for action in actions)
                    ):
                        old_edit_runtime = tuple(int(v) for v in target["runtime_id"])
                        foreground = observation.get("foreground") or {}
                        app.trigger_recreation()
                        refresh_deadline = time.monotonic() + 8
                        while time.monotonic() < refresh_deadline:
                            app.activate()
                            old_missing = False
                            try:
                                resident.named_automation_control.find_unique_edit(
                                    process_id=int(foreground["process_id"]),
                                    process_name=str(foreground["process_name"]).lower(),
                                    name=INPUT_NAME,
                                )
                            except Exception:
                                old_missing = True
                            try:
                                fresh_edit = resident.named_automation_control.find_unique_edit(
                                    process_id=int(foreground["process_id"]),
                                    process_name=str(foreground["process_name"]).lower(),
                                    name=FRESH_INPUT_NAME,
                                )
                                resident.named_automation_control.find_unique_button(
                                    process_id=int(foreground["process_id"]),
                                    process_name=str(foreground["process_name"]).lower(),
                                    name=FRESH_BUTTON_NAME,
                                )
                            except Exception:
                                time.sleep(0.05)
                                continue
                            fresh_edit_runtime = tuple(fresh_edit.runtime_id)
                            if old_missing and fresh_edit_runtime != old_edit_runtime:
                                drifted = True
                                break
                            time.sleep(0.05)
                        self.assertTrue(
                            drifted,
                            "fixture did not replace old semantic labels with fresh controls",
                        )
                        continue

                    app.activate()
                    current = resident.live_once()
                    post = resident.store.get_working_state()
                    post_observation = post.data.get(observation_key)
                    post_observation = (
                        post_observation if isinstance(post_observation, dict) else {}
                    )
                    failures = list(post.data.get("native_action_failure_records") or [])
                    failure_text = "\n".join(
                        [str(post.data.get("local_failure") or "")]
                        + [json.dumps(item, ensure_ascii=False, default=str) for item in failures]
                    )
                    if drifted and "exact named desktop control could not be freshly revalidated" in failure_text:
                        old_action_rejected = True
                    persisted = resident.store.get_event(event.event_id)
                    grounded = (
                        persisted.payload.get("desktop_task_goal")
                        if persisted is not None
                        else None
                    )
                    if (
                        drifted
                        and isinstance(grounded, dict)
                        and grounded.get("input_name") == FRESH_INPUT_NAME
                        and grounded.get("button_name") == FRESH_BUTTON_NAME
                    ):
                        semantic_regrounded = True
                    if drifted and not semantic_regrounded:
                        self.assertFalse(
                            any(
                                action.kind == "keyboard_text"
                                for action in resident.body.recent_actions(512)
                                if action.event_id == event.event_id
                            ),
                            "text input occurred before semantic re-ground completed",
                        )
                    trace.append(
                        {
                            "stage": post.stage,
                            "next_action": post.next_action,
                            "phase": post_observation.get("phase"),
                            "local_failure": str(post.data.get("local_failure") or "") or None,
                            "grounded": grounded,
                            "app_title": app.title(),
                        }
                    )
                    if current is not None and current.event.event_id == event.event_id:
                        result = current
                    if result is None:
                        time.sleep(0.03)

                self.assertTrue(drifted, json.dumps(trace[-16:], ensure_ascii=False, default=str))
                self.assertTrue(
                    old_action_rejected,
                    "old exact-name action authority was not rejected before input: "
                    + json.dumps(trace[-24:], ensure_ascii=False, default=str),
                )
                self.assertTrue(
                    semantic_regrounded,
                    "Resident never re-grounded the retained semantic goal to fresh labels: "
                    + json.dumps(trace[-24:], ensure_ascii=False, default=str),
                )
                self.assertIsNotNone(result, json.dumps(trace[-24:], ensure_ascii=False, default=str))
                self.assertTrue(result.success, result.reason)
                self.assertEqual(result.model_invocations, 3)
                self.assertEqual(proposal.calls, 3)
                self.assertEqual(app.title(), SUCCESS_TITLE)
                self.assertIn(INPUT_NAME, proposal.questions[1])
                self.assertIn(BUTTON_NAME, proposal.questions[1])
                self.assertIn(FRESH_INPUT_NAME, proposal.questions[2])
                self.assertIn(FRESH_BUTTON_NAME, proposal.questions[2])
                self.assertNotIn(INPUT_NAME, proposal.questions[2].split("Fresh Edit names:", 1)[1].split("Fresh Button names:", 1)[0])

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
                final_event = resident.store.get_event(event.event_id)
                semantic_goal = final_event.payload.get("_resident_desktop_semantic_goal") or {}
                self.assertEqual(semantic_goal.get("input_name"), "用于识别对应订单的字段")
                self.assertEqual(semantic_goal.get("button_name"), "执行查找对应记录的操作")
                reground = resident.store.get_working_state().data.get(
                    "resident_desktop_semantic_reground"
                ) or {}
                self.assertEqual(reground.get("count"), 1)
                print(
                    "ZN_DESKTOP_SEMANTIC_REGROUND_E2E_EVIDENCE="
                    + json.dumps(
                        {
                            "ordinary_language": True,
                            "regex_fast_path": False,
                            "semantic_goal_preserved": True,
                            "label_drift": [
                                f"{INPUT_NAME}->{FRESH_INPUT_NAME}",
                                f"{BUTTON_NAME}->{FRESH_BUTTON_NAME}",
                            ],
                            "old_edit_runtime": list(old_edit_runtime),
                            "fresh_edit_runtime": list(fresh_edit_runtime),
                            "old_action_rejected": old_action_rejected,
                            "fresh_semantic_reground": semantic_regrounded,
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
