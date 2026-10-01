import tempfile
import unittest
from pathlib import Path

from zn_agent.core.action import derive_native_action_intents
from zn_agent.core.application_goal import application_open_goal
from zn_agent.core.execution_mode import (
    EXECUTION_MODE_AGENT,
    EXECUTION_MODE_ASK,
    normalize_execution_mode,
)
from zn_agent.core.models import AgentEvent
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.windows_audio_intent import (
    windows_audio_volume_read_goal,
    windows_audio_volume_set_goal,
)
from zn_agent.core.windows_brightness_intent import (
    windows_brightness_read_goal,
    windows_brightness_set_goal,
)
from zn_agent.core.work import ResidentWorkLedger


class DesktopExecutionModeTests(unittest.TestCase):
    def test_execution_mode_is_strict_and_defaults_to_agent(self):
        self.assertEqual(normalize_execution_mode(None), EXECUTION_MODE_AGENT)
        self.assertEqual(normalize_execution_mode(" ASK "), EXECUTION_MODE_ASK)
        with self.assertRaisesRegex(ValueError, "ask.*agent"):
            normalize_execution_mode("automatic")

    def test_work_rejects_invalid_mode_before_creating_user_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            ledger = ResidentWorkLedger(resident)
            try:
                with self.assertRaisesRegex(ValueError, "execution_mode"):
                    ledger.start(
                        "mode-invalid",
                        "do something",
                        payload={"execution_mode": "automatic"},
                    )
                self.assertIsNone(ledger.get_thread("mode-invalid"))
            finally:
                resident.store.close()

    def test_ask_filters_effectful_native_intents_but_keeps_read_only_intents(self):
        write_event = AgentEvent(
            event_id="evt-ask-write",
            task="write a file",
            kind="desktop_user_event",
            payload={
                "execution_mode": "ask",
                "body_action": {
                    "kind": "write_text",
                    "path": "answer.txt",
                    "content": "no",
                },
            },
        )
        self.assertEqual(derive_native_action_intents(write_event), ())

        read_event = AgentEvent(
            event_id="evt-ask-read",
            task="read a file",
            kind="desktop_user_event",
            payload={
                "execution_mode": "ask",
                "body_action": {"kind": "read_text", "path": "answer.txt"},
            },
        )
        intents = derive_native_action_intents(read_event)
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].kind, "read_text")

    def test_ask_keeps_read_only_windows_intents_but_blocks_set_and_app_open(self):
        ask_volume_set = AgentEvent(
            event_id="evt-ask-volume-set",
            task="set volume to 50%",
            kind="desktop_user_event",
            payload={"execution_mode": "ask"},
        )
        ask_volume_read = AgentEvent(
            event_id="evt-ask-volume-read",
            task="what is the current volume?",
            kind="desktop_user_event",
            payload={"execution_mode": "ask"},
        )
        ask_brightness_set = AgentEvent(
            event_id="evt-ask-brightness-set",
            task="set screen brightness to 40%",
            kind="desktop_user_event",
            payload={"execution_mode": "ask"},
        )
        ask_brightness_read = AgentEvent(
            event_id="evt-ask-brightness-read",
            task="what is the current screen brightness?",
            kind="desktop_user_event",
            payload={"execution_mode": "ask"},
        )
        ask_open = AgentEvent(
            event_id="evt-ask-open",
            task="open Notepad",
            kind="desktop_user_event",
            payload={"execution_mode": "ask"},
        )

        self.assertIsNone(windows_audio_volume_set_goal(ask_volume_set))
        self.assertIsNotNone(windows_audio_volume_read_goal(ask_volume_read))
        self.assertIsNone(windows_brightness_set_goal(ask_brightness_set))
        self.assertIsNotNone(windows_brightness_read_goal(ask_brightness_read))
        self.assertIsNone(application_open_goal(ask_open))

        agent_open = AgentEvent(
            event_id="evt-agent-open",
            task="open Notepad",
            kind="desktop_user_event",
            payload={"execution_mode": "agent"},
        )
        self.assertIsNotNone(application_open_goal(agent_open))

    def test_product_body_fail_closes_effects_in_ask_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "answer.txt"
            target.write_text("before", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            try:
                ask_event = resident.enqueue(
                    "inspect but do not change the file",
                    kind="desktop_user_event",
                    payload={"execution_mode": "ask"},
                )
                observed = resident.body.act(
                    "read_text",
                    event_id=ask_event.event_id,
                    path=str(target),
                )
                self.assertTrue(observed.success)
                self.assertEqual(observed.output, "before")

                blocked = resident.body.act(
                    "write_text",
                    event_id=ask_event.event_id,
                    path=str(target),
                    content="after",
                )
                self.assertFalse(blocked.success)
                self.assertIn("Ask mode", blocked.error or "")
                self.assertEqual(target.read_text(encoding="utf-8"), "before")

                agent_event = resident.enqueue(
                    "change the file",
                    kind="desktop_user_event",
                    payload={"execution_mode": "agent"},
                )
                changed = resident.body.act(
                    "write_text",
                    event_id=agent_event.event_id,
                    path=str(target),
                    content="after",
                )
                self.assertTrue(changed.success)
                self.assertEqual(target.read_text(encoding="utf-8"), "after")
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
