from __future__ import annotations

import unittest

from zn_agent.core.browser import BrowserAction, BrowserActionAuthority, BrowserActionKind
from tests.zn_agent.core.test_managed_browser_press import _DIGEST, _PressAdapter, _TEXT


class ManagedBrowserPressOriginTests(unittest.TestCase):
    def test_enter_press_rejects_cross_origin_expected_url_before_dispatch(self) -> None:
        adapter = _PressAdapter()
        action = BrowserAction.create(
            session_id=adapter.session.identity.session_id,
            kind=BrowserActionKind.PRESS,
            page_id="page-1",
            target=adapter.target,
            args={"key": "Enter"},
            expected={
                "url_equals": "https://other.example/done",
                "text_length": len(_TEXT),
                "text_sha256": _DIGEST,
            },
        )
        authority = BrowserActionAuthority.from_observation(
            action,
            adapter.observation,
            adapter.permission,
        )

        effect = adapter.act(action, authority)

        self.assertFalse(effect.success)
        self.assertIn("same-origin expected URL", effect.error or "")
        self.assertEqual(adapter.press_dispatches, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
