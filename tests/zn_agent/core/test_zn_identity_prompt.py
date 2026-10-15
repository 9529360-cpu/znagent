from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core import (
    KernelStore,
    ModelRoute,
    WorkerResult,
    ZNKernelRuntime,
    ZNResidentRuntime,
)
from zn_agent.core.agentic_tool_loop import DEFAULT_SYSTEM_PROMPT


class _CaptureWorker:
    def __init__(self, factory):
        self.factory = factory

    def run(self, goal, kernel_context):
        self.factory.goals.append(goal)
        self.factory.contexts.append(kernel_context)
        return WorkerResult(
            success=True,
            response="bounded answer",
            verification_passed=True,
            metrics={"model_invoked": True},
        )


class _CaptureFactory:
    def __init__(self):
        self.goals = []
        self.contexts = []

    def create(self, route):
        return _CaptureWorker(self)


def _resident(db: Path, factory: _CaptureFactory) -> ZNResidentRuntime:
    kernel = ZNKernelRuntime(
        store=KernelStore(db),
        routes=[
            ModelRoute(
                "primary",
                "test",
                "model",
                {"general": 0.8, "database": 0.8},
            )
        ],
        worker_factory=factory,
    )
    return ZNResidentRuntime(kernel=kernel)


class ZNIdentityPromptTests(unittest.TestCase):
    def _captured_context(self) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            factory = _CaptureFactory()
            resident = _resident(Path(tmp) / "kernel.db", factory)
            try:
                result = resident.submit(
                    "What does SQLite SQLITE_BUSY mean during a transaction?",
                    payload={
                        "cognition_question": "What does SQLite SQLITE_BUSY mean?",
                        "required_capabilities": ["database"],
                    },
                )
                self.assertTrue(result.success)
                self.assertEqual(len(factory.contexts), 1)
                return factory.contexts[0]
            finally:
                # Windows: an open sqlite handle locks kernel.db, so the
                # TemporaryDirectory cleanup would fail with WinError 32.
                # Release the store before the tmp dir is removed.
                resident.store.close()

    def test_kernel_worker_context_identifies_as_zn(self):
        context = self._captured_context()
        self.assertIn("You are ZN", context)
        self.assertIn("If asked who you are, say you are ZN", context)
        self.assertIn("Never present yourself as Muse Spark", context)

    def test_kernel_worker_context_drops_external_assistant_framing(self):
        context = self._captured_context()
        self.assertNotIn("external cognitive resource", context)
        self.assertNotIn("temporarily consulted by ZN", context)
        self.assertNotIn("you are not the persistent agent", context)
        self.assertNotIn("you do not own its identity", context)

    def test_kernel_worker_context_keeps_bounded_knowledge(self):
        context = self._captured_context()
        self.assertIn("BOUNDED CONTEXT", context)
        self.assertIn("only know what is in the supplied context", context)
        self.assertIn("do not claim memories", context)

    def test_tool_loop_default_system_prompt_identifies_as_zn(self):
        self.assertIn("You are ZN", DEFAULT_SYSTEM_PROMPT)
        self.assertIn("If asked who you are, say you are ZN", DEFAULT_SYSTEM_PROMPT)
        self.assertIn(
            "Never present yourself as Muse Spark", DEFAULT_SYSTEM_PROMPT
        )
        self.assertNotIn("external cognitive resource", DEFAULT_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
