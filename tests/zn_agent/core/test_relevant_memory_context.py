from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core import KernelStore, ModelRoute, WorkerResult, ZNKernelRuntime, ZNResidentRuntime
from zn_agent.core.memory import StructuredMemory


class ContextWorker:
    def __init__(self, contexts: list[str]):
        self.contexts = contexts

    def run(self, goal, kernel_context):
        self.contexts.append(kernel_context)
        return WorkerResult(
            success=True,
            response="model result",
            verification_passed=True,
            metrics={"model_invoked": True},
        )


class ContextFactory:
    def __init__(self):
        self.contexts: list[str] = []

    def create(self, route):
        return ContextWorker(self.contexts)


def resident_for(db: Path, factory: ContextFactory) -> ZNResidentRuntime:
    kernel = ZNKernelRuntime(
        store=KernelStore(db),
        routes=[ModelRoute("primary", "test", "model", {"general": 0.8})],
        worker_factory=factory,
    )
    return ZNResidentRuntime(kernel=kernel)


class RelevantMemoryContextTests(unittest.TestCase):
    def test_context_lookup_uses_saved_keys_and_aliases_with_strict_bounds(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        store = KernelStore(Path(tmp) / "memory.db")
        self.addCleanup(store.close)
        memory = StructuredMemory(store)
        memory.remember(
            "project", "ZN Agent", aliases=("当前项目", "active project")
        )
        memory.remember("unrelated", "should stay private", aliases=("home address",))
        memory.remember("long", "x" * 2_000, aliases=("large detail",))

        self.assertEqual(
            memory.relevant_context("帮我继续当前项目的开发"),
            [{"key": "project", "value": "ZN Agent"}],
        )
        self.assertEqual(memory.relevant_context("update the active project"), [
            {"key": "project", "value": "ZN Agent"}
        ])
        self.assertEqual(memory.relevant_context("please project the image"), [])
        self.assertEqual(
            memory.relevant_context("large detail", max_json_chars=100), []
        )

    def test_relevant_saved_memory_reaches_allowed_cognition_context(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        factory = ContextFactory()
        resident = resident_for(Path(tmp) / "kernel.db", factory)
        self.addCleanup(resident.store.close)
        resident.memory.remember("project", "ZN Agent", aliases=("current project",))

        result = resident.submit("prepare a short update for my current project")

        self.assertTrue(result.success)
        self.assertEqual(len(factory.contexts), 1)
        self.assertIn('"related_memory_facts": [', factory.contexts[0])
        self.assertIn('"value": "ZN Agent"', factory.contexts[0])

    def test_allow_memory_false_keeps_saved_facts_out_of_model_context(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        factory = ContextFactory()
        resident = resident_for(Path(tmp) / "kernel.db", factory)
        self.addCleanup(resident.store.close)
        resident.memory.remember("project", "ZN Agent", aliases=("current project",))

        result = resident.submit(
            "prepare a short update for my current project",
            payload={"allow_memory": False},
        )

        self.assertEqual(len(factory.contexts), 1)
        self.assertNotIn("related_memory_facts", factory.contexts[0])
        self.assertNotIn("ZN Agent", factory.contexts[0])


if __name__ == "__main__":
    unittest.main()

