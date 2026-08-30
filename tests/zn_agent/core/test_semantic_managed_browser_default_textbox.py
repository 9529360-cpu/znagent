from __future__ import annotations

import unittest

from zn_agent.core.browser import BrowserTargetQueryKind
from zn_agent.core.semantic_managed_browser import (
    SemanticPlaywrightManagedBrowser,
    _SEMANTIC_TEXTBOX_EVIDENCE_SCRIPT,
)


class SemanticManagedBrowserDefaultTextboxTests(unittest.TestCase):
    def test_default_input_type_is_part_of_native_textbox_provider_contract(self) -> None:
        self.assertIn('inputType === "" || inputType === "text"', _SEMANTIC_TEXTBOX_EVIDENCE_SCRIPT)
        SemanticPlaywrightManagedBrowser._validate_semantic_evidence(
            BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME,
            {
                "connected": True,
                "visible": True,
                "tag": "input",
                "input_type": "",
                "native_textbox": True,
                "is_password": False,
                "disabled": False,
                "read_only": False,
            },
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
