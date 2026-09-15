from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from zn_agent.core.cognitive_resource import CognitiveResourceWorkerFactory
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.desktop_task_goal import explicit_desktop_task_goal_hint
from zn_agent.core.models import ModelRoute
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.resident_server import ResidentSocketService

import test_windows_interactive_file_desktop_goal as file_goal_e2e
import test_windows_interactive_text_entry as text_entry_e2e


class WindowsInteractiveForegroundDesktopStartContextGuardE2ETests(unittest.TestCase):
    def test_natural_current_app_goal_refuses_retarget_after_initial_grounding(self):
        text_entry_e2e.WindowsInteractiveTextEntryE2ETests._require_input_desktop()

        with tempfile.TemporaryDirectory(prefix="zn-wave7-desktop-guard-") as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            source = workspace / "订单资料.txt"
            source.write_text(file_goal_e2e.NEW_VALUE, encoding="utf-8")
            file_goal_e2e.WindowsInteractiveFileDesktopGoalE2ETests._yesterday(source)

            app_a_root = root / "app-a"
            app_b_root = root / "app-b"
            app_a_root.mkdir()
            app_b_root.mkdir()
            app_a = file_goal_e2e._OrderApp(app_a_root)
            app_b = file_goal_e2e._OrderApp(app_b_root)
            resident = None
            try:
                app_a.start()
                app_b.start()

                resident = build_resident_runtime(
                    config={"model": {}},
                    store_path=root / "kernel.db",
                )
                service = ResidentSocketService(ResidentRpcServer(resident=resident))
                self.assertIs(resident.visual_region, service.visual_region)

                proposal = file_goal_e2e._Proposal()
                resident.kernel.reconfigure_resources(
                    routes=[
                        ModelRoute(
                            route_id="wave7-language",
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

                # App A is the deictic foreground referent at durable Work ingress.
                app_a.activate()
                foreground_a, error = resident._probe_foreground_window()
                self.assertIsNotNone(foreground_a, error)
                self.assertEqual(int(foreground_a.process_id), int(app_a.process.pid))

                ledger = RecoveryBoundedWorkLedger(resident)
                thread_id = "wave7-foreground-desktop"
                ledger.create_thread(thread_id=thread_id)
                ledger.attach_workspace(thread_id, workspace)
                _, event = ledger.start(
                    thread_id,
                    file_goal_e2e.TASK,
                    payload={"model_policy": "on_demand"},
                )
                # Exercise the model-understanding path: this request is not typed
                # by the explicit parser at ingress.
                self.assertIsNone(explicit_desktop_task_goal_hint(event))
                start_context = event.payload.get("windows_companion_start_context")
                self.assertIsInstance(start_context, dict)
                self.assertEqual(
                    int(start_context["foreground"]["process_id"]),
                    int(app_a.process.pid),
                )

                # Let Resident understand and freshly ground the typed desktop goal
                # against app A, but stop before any task-owned OS-wide input.
                observation_key = getattr(
                    resident,
                    "_DESKTOP_TASK_OBSERVATION_KEY",
                    "resident_desktop_task_observation",
                )
                grounded = False
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline and not grounded:
                    app_a.activate()
                    current = resident.live_once()
                    if current is not None and current.event.event_id == event.event_id:
                        self.fail(
                            "foreground-desktop Work terminated before the initial A grounding: "
                            + str(current.reason or current.response or "")
                        )
                    state = resident.store.get_working_state()
                    if state.current_event_id == event.event_id:
                        observation = state.data.get(observation_key)
                        observation = observation if isinstance(observation, dict) else {}
                        grounded = bool(
                            state.stage == "native_deliberation"
                            and str(observation.get("phase") or "") == "focus"
                        )
                    if not grounded:
                        time.sleep(0.03)

                self.assertTrue(grounded, "typed desktop goal never reached initial A grounding")
                actions_before_switch = [
                    action
                    for action in resident.body.recent_actions(512)
                    if action.event_id == event.event_id
                    and action.kind in {"pointer_move", "pointer_click", "keyboard_text"}
                ]
                self.assertEqual(actions_before_switch, [])

                # Switch to a deliberately same-title/same-process-name sibling app
                # after initial grounding. A first-only ingress guard would let the
                # stale A action fail, return to investigation, and then silently
                # re-ground the natural "current app" goal onto B.
                app_b.activate()
                foreground_b, error = resident._probe_foreground_window()
                self.assertIsNotNone(foreground_b, error)
                self.assertEqual(int(foreground_b.process_id), int(app_b.process.pid))
                self.assertNotEqual(
                    int(foreground_b.process_id),
                    int(start_context["foreground"]["process_id"]),
                )
                self.assertEqual(foreground_b.process_name, foreground_a.process_name)
                self.assertEqual(foreground_b.title, foreground_a.title)

                result = None
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline and result is None:
                    app_b.activate()
                    current = resident.live_once()
                    if current is not None and current.event.event_id == event.event_id:
                        result = current
                    if result is None:
                        time.sleep(0.03)

                self.assertIsNotNone(result)
                assert result is not None
                self.assertFalse(result.success)
                self.assertIn("foreground_drift", str(result.reason or ""))
                self.assertGreaterEqual(proposal.calls, 1)

                actions = [
                    action
                    for action in resident.body.recent_actions(512)
                    if action.event_id == event.event_id
                    and action.kind in {"pointer_move", "pointer_click", "keyboard_text"}
                ]
                self.assertEqual(
                    actions,
                    [],
                    "stale foreground semantics must fail before any task-owned OS-wide input",
                )
                self.assertEqual(app_a.title(), file_goal_e2e.START_TITLE)
                self.assertEqual(app_b.title(), file_goal_e2e.START_TITLE)
            finally:
                app_b.close()
                app_a.close()
                if resident is not None:
                    resident.store.close()


if __name__ == "__main__":
    unittest.main()
