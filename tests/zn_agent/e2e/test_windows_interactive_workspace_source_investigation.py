from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from zn_agent.core.cognitive_resource import CognitiveResourceWorkerFactory
from zn_agent.core.models import EventStatus, ModelRoute
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger

from test_windows_interactive_file_desktop_goal import (
    BUTTON_NAME,
    INPUT_NAME,
    NEW_VALUE,
    OLD_VALUE,
    START_TITLE,
    SUCCESS_TITLE,
    _OrderApp,
    _Proposal,
    WindowsInteractiveFileDesktopGoalE2ETests,
)
from test_windows_interactive_text_entry import WindowsInteractiveTextEntryE2ETests


TASK = "找到昨天那个订单文件里的编号，在我现在开的软件里查一下对应记录。"


class WindowsInteractiveWorkspaceSourceInvestigationE2ETests(unittest.TestCase):
    def test_ambiguous_workspace_source_stays_non_mutating_then_same_work_continues(self) -> None:
        WindowsInteractiveTextEntryE2ETests._require_input_desktop()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            source = workspace / "orders-yesterday-a.txt"
            decoy = workspace / "orders-yesterday-b.txt"
            source.write_text(OLD_VALUE, encoding="utf-8")
            decoy.write_text("ORDER-DECOY-771", encoding="utf-8")
            WindowsInteractiveFileDesktopGoalE2ETests._yesterday(source)
            WindowsInteractiveFileDesktopGoalE2ETests._yesterday(decoy)

            app = _OrderApp(root)
            app.start()
            resident = None
            try:
                resident = build_resident_runtime(
                    config={"model": {}},
                    store_path=root / "kernel.db",
                )
                proposal = _Proposal()
                resident.kernel.reconfigure_resources(
                    routes=[
                        ModelRoute(
                            route_id="e2e-language",
                            provider="fixture",
                            model="bounded-language-fixture",
                            capabilities={"language_understanding": 1.0, "general": 0.8},
                        )
                    ],
                    worker_factory=CognitiveResourceWorkerFactory(
                        resource_builder=lambda _: proposal
                    ),
                    max_attempts=1,
                    resource_status={"available": True, "error": None},
                )

                ledger = RecoveryBoundedWorkLedger(resident)
                thread = "workspace-source-investigation-e2e"
                ledger.create_thread(thread_id=thread)
                ledger.attach_workspace(thread, workspace)
                _, event = ledger.start(
                    thread,
                    TASK,
                    payload={"model_policy": "on_demand"},
                )

                ambiguity_seen = False
                for _ in range(12):
                    app.activate()
                    resident.live_once()
                    state = resident.store.get_working_state()
                    if state.blocked_by == "workspace_source_ambiguous":
                        ambiguity_seen = True
                        break
                    time.sleep(0.02)
                self.assertTrue(ambiguity_seen, "Resident never exposed workspace ambiguity")

                state = resident.store.get_working_state()
                self.assertEqual(state.stage, "native_investigation")
                self.assertEqual(state.blocked_by, "workspace_source_ambiguous")
                self.assertIn("re-sense the workspace", state.next_action or "")
                self.assertEqual(resident.store.get_event(event.event_id).status, EventStatus.PROCESSING)
                self.assertIsNone(resident.store.get_event_outcome(event.event_id))
                self.assertEqual(proposal.calls, 1, "desktop grounding must wait for source identity")
                self.assertEqual(app.title(), START_TITLE)
                self.assertEqual(source.read_text(encoding="utf-8"), OLD_VALUE)
                self.assertEqual(decoy.read_text(encoding="utf-8"), "ORDER-DECOY-771")

                actions = [
                    item
                    for item in resident.body.recent_actions(512)
                    if item.event_id == event.event_id
                ]
                self.assertEqual(sum(item.kind == "keyboard_text" for item in actions), 0)
                self.assertEqual(sum(item.kind == "pointer_click" for item in actions), 0)
                self.assertEqual(sum(item.kind == "write_text" for item in actions), 0)

                progress = ledger.progress(thread, event.event_id)
                self.assertFalse(progress["terminal"])
                self.assertEqual(progress["stage"], "native_investigation")

                # New world evidence resolves the ambiguity. Resident must perform a
                # fresh workspace enumeration; it may not promote a cached candidate.
                decoy.unlink()

                drifted = False
                stale_rejected = False
                result = None
                deadline = time.monotonic() + 35.0
                while time.monotonic() < deadline and result is None:
                    state = resident.store.get_working_state()
                    intent = state.data.get("native_action_intent")
                    event_actions = [
                        item
                        for item in resident.body.recent_actions(512)
                        if item.event_id == event.event_id
                    ]
                    if (
                        not drifted
                        and isinstance(intent, dict)
                        and intent.get("kind") == "keyboard_text"
                        and not any(item.kind == "keyboard_text" for item in event_actions)
                    ):
                        source.write_text(NEW_VALUE, encoding="utf-8")
                        WindowsInteractiveFileDesktopGoalE2ETests._yesterday(source)
                        drifted = True

                    app.activate()
                    current = resident.live_once()
                    current_state = resident.store.get_working_state()
                    failure = str(current_state.data.get("local_failure") or "")
                    stale_rejected |= (
                        "workspace source identity changed after investigation" in failure
                    )
                    if current is not None and current.event.event_id == event.event_id:
                        result = current
                        break
                    time.sleep(0.02)

                self.assertTrue(drifted, "source-drift boundary was never reached")
                self.assertTrue(stale_rejected, "stale exact source value was not rejected")
                self.assertIsNotNone(result)
                self.assertTrue(result.success, result)
                self.assertEqual(proposal.calls, 2)
                self.assertEqual(app.title(), SUCCESS_TITLE)

                actions = [
                    item
                    for item in resident.body.recent_actions(1024)
                    if item.event_id == event.event_id
                ]
                keyboard_count = sum(item.kind == "keyboard_text" for item in actions)
                pointer_count = sum(item.kind == "pointer_click" for item in actions)
                write_count = sum(item.kind == "write_text" for item in actions)
                self.assertEqual(keyboard_count, 1)
                self.assertEqual(pointer_count, 2)
                self.assertEqual(write_count, 0)
                self.assertEqual(source.read_text(encoding="utf-8"), NEW_VALUE)
                self.assertFalse(decoy.exists())

                outcome = resident.store.get_event_outcome(event.event_id)
                self.assertIsNotNone(outcome)
                self.assertTrue(outcome.success)
                self.assertIn(SUCCESS_TITLE, outcome.response)

                print(
                    "ZN_WORKSPACE_SOURCE_INVESTIGATION_E2E_EVIDENCE="
                    + json.dumps(
                        {
                            "ordinary_language_task": TASK,
                            "initial_plausible_sources": 2,
                            "ambiguity_became_open_investigation": True,
                            "event_terminal_during_ambiguity": False,
                            "desktop_grounding_calls_during_ambiguity": 0,
                            "keyboard_actions_during_ambiguity": 0,
                            "pointer_actions_during_ambiguity": 0,
                            "file_writes_during_ambiguity": 0,
                            "disambiguating_evidence": "one candidate disappeared before a fresh Sense",
                            "fresh_source_after_resolution": source.name,
                            "source_drift_before_input": True,
                            "stale_source_rejected": True,
                            "final_keyboard_actions": keyboard_count,
                            "final_pointer_actions": pointer_count,
                            "resident_file_writes": write_count,
                            "final_app_title": app.title(),
                            "independent_oracle": "windows-window-title",
                            "same_work_event_id": event.event_id,
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
