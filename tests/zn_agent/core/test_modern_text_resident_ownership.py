from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from zn_agent.core.automation_text_state_sense import NativeFocusedAutomationTextSense
from zn_agent.core.completion_observation import CompletionObservationJournal
from zn_agent.core.focused_modern_text_resident import FocusedModernTextResidentRuntime
from zn_agent.core.managed_browser import PlaywrightManagedBrowser
from zn_agent.core.provider_bridge import build_resident_runtime


class ModernTextResidentOwnershipTests(unittest.TestCase):
    def test_richer_birth_root_repairs_completion_observations_once_and_status_projects_health(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            CompletionObservationJournal,
            "repair_life",
            autospec=True,
            return_value=0,
        ) as repair_life:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                repair_life.assert_called_once_with(resident.completion_observations, resident)
                self.assertEqual(
                    resident.status()["completion_observations"],
                    resident.completion_observations.health(),
                )
            finally:
                resident.managed_browser.close()
                resident.store.close()

    def test_provider_bridge_builds_resident_that_owns_modern_senses_and_browser_resource(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertIsInstance(resident, FocusedModernTextResidentRuntime)
                self.assertIsInstance(
                    resident.automation_text_state,
                    NativeFocusedAutomationTextSense,
                )
                self.assertIsInstance(resident.managed_browser, PlaywrightManagedBrowser)
                # Browser ownership is lazy: zero-model resident construction
                # must not start a browser or require the optional Playwright
                # package merely to stay alive.
                self.assertEqual(resident.managed_browser._sessions, {})
                # The read-only modern Sense/browser resource do not replace the
                # existing native text verifier or create broader keyboard authority.
                self.assertTrue(hasattr(resident, "focused_text"))
                self.assertTrue(hasattr(resident, "body"))
            finally:
                resident.managed_browser.close()
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
