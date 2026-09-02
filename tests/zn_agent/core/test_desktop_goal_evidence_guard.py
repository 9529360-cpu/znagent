from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.models import AgentEvent, WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime


class DesktopGoalEvidenceGuardTests(unittest.TestCase):
    def test_fresh_desktop_state_requalifies_movement_without_clock_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                event = AgentEvent(
                    event_id="evt-desktop-evidence-guard",
                    task="use the current desktop input",
                    kind="desktop_user_event",
                )
                state = WorkingState(
                    current_event_id=event.event_id,
                    stage="native_deliberation",
                    data={
                        resident._DESKTOP_TASK_OBSERVATION_KEY: {
                            "phase": "focus",
                            "source": {
                                "path": "C:/workspace/order.txt",
                                "text_chars": 9,
                                "text_sha256": "source-v1",
                                "captured_at": "2026-09-02T10:00:00+00:00",
                            },
                            "foreground": {
                                "process_id": 42,
                                "process_name": "order.exe",
                                "title": "Orders",
                                "captured_at": "2026-09-02T10:00:00+00:00",
                            },
                            "target": {
                                "runtime_id": [42, 7, 9],
                                "control_type": 50004,
                                "has_keyboard_focus": False,
                                "captured_at": "2026-09-02T10:00:00+00:00",
                            },
                            "focused": None,
                            "text": None,
                            "button": None,
                            "failure": None,
                            "observed_at": "2026-09-02T10:00:00+00:00",
                        }
                    },
                )
                resident.store.save_working_state(state)
                intent = NativeActionIntent(
                    intent_id="desktop-focus-attempt",
                    event_id=event.event_id,
                    kind="pointer_click",
                    args={"x_fraction": 0.5, "y_fraction": 0.5, "button": "left"},
                    expected_outcome={"kind": resident._DESKTOP_EDIT_FOCUS_KIND},
                )

                first = resident._evidence_fingerprint(event.event_id)
                resident._record_failed_action(
                    event,
                    state,
                    intent,
                    source="precondition",
                    failure="target was not ready",
                )
                resident.store.save_working_state(state)
                self.assertTrue(
                    resident._action_blocked_by_current_evidence(event, state, intent)
                )

                same = dict(state.data[resident._DESKTOP_TASK_OBSERVATION_KEY])
                same["observed_at"] = "2026-09-02T10:05:00+00:00"
                state.data[resident._DESKTOP_TASK_OBSERVATION_KEY] = same
                resident.store.save_working_state(state)
                self.assertEqual(first, resident._evidence_fingerprint(event.event_id))
                self.assertTrue(
                    resident._action_blocked_by_current_evidence(event, state, intent)
                )

                changed = dict(same)
                changed["phase"] = "fill"
                changed["focused"] = {
                    "runtime_id": [42, 7, 9],
                    "control_type": 50004,
                    "has_keyboard_focus": True,
                    "captured_at": "2026-09-02T10:05:00+00:00",
                }
                changed["target"] = dict(changed["target"])
                changed["target"]["has_keyboard_focus"] = True
                state.data[resident._DESKTOP_TASK_OBSERVATION_KEY] = changed
                resident.store.save_working_state(state)

                self.assertNotEqual(first, resident._evidence_fingerprint(event.event_id))
                self.assertFalse(
                    resident._action_blocked_by_current_evidence(event, state, intent)
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
