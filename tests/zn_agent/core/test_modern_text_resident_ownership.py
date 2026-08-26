from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.automation_text_state_sense import NativeFocusedAutomationTextSense
from zn_agent.core.focused_modern_text_resident import FocusedModernTextResidentRuntime
from zn_agent.core.provider_bridge import build_resident_runtime


class ModernTextResidentOwnershipTests(unittest.TestCase):
    def test_provider_bridge_builds_resident_that_owns_readonly_modern_text_sense(self):
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
                # The new read-only Sense does not replace the existing native
                # text mutation verifier or create a broader keyboard Body.
                self.assertTrue(hasattr(resident, "focused_text"))
                self.assertTrue(hasattr(resident, "body"))
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
