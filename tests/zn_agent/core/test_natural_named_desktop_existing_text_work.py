from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.zn_agent.core import test_natural_named_desktop_input_work as _natural_named_desktop_input_work
from tests.zn_agent.core.test_natural_named_desktop_input_work import (
    TASK,
)


class NaturalNamedDesktopExistingTextWorkTests(unittest.TestCase):
    def test_existing_correct_text_skips_keyboard_but_still_submits_and_verifies_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "authorized"
            workspace.mkdir()
            target = workspace / "客户账号-华东.txt"
            target.write_text("ACCT-48291", encoding="utf-8")
            _natural_named_desktop_input_work.NaturalNamedDesktopInputWorkTests._stamp_yesterday(target)

            resident, world, body, controls, ledger = _natural_named_desktop_input_work.NaturalNamedDesktopInputWorkTests._setup(
                base,
                workspace,
                "named-input-existing-text",
            )
            body.current_text = "ACCT-48291"
            try:
                _, run = ledger.submit("named-input-existing-text", TASK)

                self.assertTrue(run.success, run)
                self.assertEqual(body.focus_click_count, 1)
                self.assertEqual(body.keyboard_calls, [])
                self.assertEqual(body.current_text, "ACCT-48291")
                self.assertEqual(body.submit_click_count, 1)
                self.assertEqual(world.title, "查询结果")
                self.assertGreaterEqual(controls.edit_calls, 3)
                self.assertGreaterEqual(controls.button_calls, 2)

                actions = [
                    item
                    for item in reversed(resident.body.recent_actions(512))
                    if item.event_id == run.event.event_id
                ]
                self.assertEqual(sum(item.kind == "keyboard_text" for item in actions), 0)
                self.assertEqual(sum(item.kind == "pointer_click" for item in actions), 2)
                final = resident.store.get_event_outcome(run.event.event_id)
                self.assertIsNotNone(final)
                self.assertTrue(final.success)
                self.assertIn("title=查询结果", final.response)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
