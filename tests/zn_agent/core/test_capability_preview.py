from __future__ import annotations

import unittest

from zn_agent.core.capabilities import (
    CallableCapability,
    preview_capability,
)
from zn_agent.core.models import AgentEvent, CapabilityResult, WorkingState


def _event():
    return AgentEvent("e1", "do the thing", payload={})


class PreviewContractTests(unittest.TestCase):
    def _cap(self, previewer=None, replay_safe=False):
        return CallableCapability(
            name="demo",
            matcher=lambda event: 1.0,
            handler=lambda event, state: CapabilityResult(
                action_id="a", kind="demo", success=True, event_id="e1",
                started_at="t0", completed_at="t1",
            ),
            replay_safe=replay_safe,
            previewer=previewer,
        )

    def test_preview_returned(self):
        cap = self._cap(previewer=lambda e, s: "would write /tmp/x")
        self.assertEqual(
            preview_capability(cap, _event(), None), "would write /tmp/x"
        )

    def test_no_previewer_returns_none(self):
        cap = self._cap()
        self.assertIsNone(preview_capability(cap, _event(), None))

    def test_legacy_capability_without_preview(self):
        class Legacy:
            name = "legacy"
            def match(self, event): return 1.0
            def execute(self, event, state): return None
        self.assertIsNone(preview_capability(Legacy(), _event(), None))

    def test_previewer_exception_returns_none(self):
        def boom(event, state):
            raise RuntimeError("x")
        cap = self._cap(previewer=boom)
        self.assertIsNone(preview_capability(cap, _event(), None))

    def test_empty_preview_returns_none(self):
        cap = self._cap(previewer=lambda e, s: "   ")
        self.assertIsNone(preview_capability(cap, _event(), None))

    def test_preview_truncated(self):
        cap = self._cap(previewer=lambda e, s: "x" * 5000)
        result = preview_capability(cap, _event(), None)
        assert result is not None
        self.assertEqual(len(result), 2000)


if __name__ == "__main__":
    unittest.main()
