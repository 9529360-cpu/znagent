from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.models import AgentEvent
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.work import ResidentWorkLedger
from tests.zn_agent.core.test_browser_work_named_button import _FakeNamedButtonBrowser


class BrowserWorkNaturalButtonTests(unittest.TestCase):
    @staticmethod
    def _event(task: str) -> AgentEvent:
        return AgentEvent(event_id="evt-browser-natural-button", task=task)

    def test_natural_named_button_requires_exact_name_start_and_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertEqual(
                    resident._natural_named_button_request(
                        self._event(
                            'open https://example.com/start and click button "Continue"; '
                            'verify https://example.com/done'
                        )
                    ),
                    (
                        "https://example.com/start",
                        "Continue",
                        "https://example.com/done",
                    ),
                )
                self.assertEqual(
                    resident._natural_named_button_request(
                        self._event(
                            "打开 https://example.com/start 并点击“继续”按钮；"
                            "验证 https://example.com/done"
                        )
                    ),
                    (
                        "https://example.com/start",
                        "继续",
                        "https://example.com/done",
                    ),
                )
                missing_destination = self._event(
                    'open https://example.com/start and click button "Continue"'
                )
                self.assertIsNone(
                    resident._natural_named_button_request(missing_destination)
                )
                self.assertIsNone(resident._natural_navigation_url(missing_destination))
                self.assertIsNone(
                    resident._natural_named_button_request(
                        self._event(
                            "open https://example.com/start and click button Continue; "
                            "verify https://example.com/done"
                        )
                    )
                )
                self.assertIsNone(
                    resident._natural_named_button_request(
                        self._event(
                            'open https://example.com/start and click button "One" then "Two"; '
                            'verify https://example.com/done'
                        )
                    )
                )
            finally:
                resident.store.close()

    def test_normal_work_clicks_exact_named_button_without_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            browser = _FakeNamedButtonBrowser()
            resident.managed_browser = browser
            ledger = ResidentWorkLedger(resident)
            try:
                ledger.create_thread(thread_id="browser-natural-button")
                (_, messages), result = ledger.submit(
                    "browser-natural-button",
                    'open https://example.com/start and click button "Continue"; '
                    'verify https://example.com/done',
                )

                self.assertTrue(result.success, result.reason)
                self.assertEqual(result.response, "https://example.com/done")
                self.assertEqual(result.model_invocations, 0)
                self.assertEqual(browser.url, "https://example.com/done")
                self.assertEqual(len(browser.queries), 1)
                self.assertEqual(browser.queries[0].value, "Continue")
                self.assertEqual(browser.close_calls, 1)
                self.assertTrue(
                    any(
                        message.role == "zn"
                        and message.text == "https://example.com/done"
                        for message in messages
                    )
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
