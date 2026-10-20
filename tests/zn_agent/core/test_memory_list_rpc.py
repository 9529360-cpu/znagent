from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.two_level_memory import TwoLevelMemory


class MemoryListRpcTests(unittest.TestCase):
    """The read-only ``memory_list`` RPC: inventory without values."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.resident = build_resident_runtime(
            config={"model": {}}, store_path=self.root / "kernel.db"
        )
        self.addCleanup(lambda: self.resident.store.close())
        self.rpc = ResidentRpcServer(self.resident)

    def call(self, method, **params):
        response = self.rpc.handle(
            {"id": method, "method": method, "params": params}
        )
        self.assertTrue(response["ok"], response.get("error"))
        return response["result"]

    def test_empty_memory_lists_nothing(self):
        self.assertEqual(self.call("memory_list"), [])

    def test_lists_keys_aliases_updated_at_and_tier_without_values(self):
        self.call(
            "remember", key="project", value={"name": "Artemis"}, aliases=["active project"]
        )
        self.call("remember", key="response language", value="Chinese", aliases=[])
        listed = self.call("memory_list")
        self.assertEqual(len(listed), 2)
        by_key = {item["key"]: item for item in listed}
        self.assertEqual(set(by_key), {"project", "response language"})
        for item in listed:
            self.assertEqual(
                set(item), {"key", "aliases", "updated_at", "tier"}, item
            )
            self.assertNotIn("value", item)
        self.assertEqual(by_key["project"]["aliases"], ["active project"])
        self.assertEqual(by_key["response language"]["aliases"], [])
        self.assertTrue(by_key["project"]["updated_at"])
        self.assertEqual(by_key["project"]["tier"], "hot")
        self.assertEqual(by_key["response language"]["tier"], "hot")

    def test_value_never_leaks(self):
        self.call("remember", key="secret-key", value="super-secret-value")
        listed = self.call("memory_list")
        self.assertEqual(len(listed), 1)
        serialized = str(listed)
        self.assertNotIn("super-secret-value", serialized)

    def test_limit_is_respected(self):
        for i in range(5):
            self.call("remember", key=f"key-{i}", value=i)
        listed = self.call("memory_list", limit=2)
        self.assertEqual(len(listed), 2)

    def test_limit_is_capped(self):
        for i in range(3):
            self.call("remember", key=f"key-{i}", value=i)
        # The server-side cap is 200; an absurd limit must not error.
        listed = self.call("memory_list", limit=10_000)
        self.assertEqual(len(listed), 3)
        self.assertEqual(ResidentRpcServer._limit({"limit": 10_000}), 200)

    def test_deep_tier_is_reported(self):
        self.call("remember", key="hot-fact", value=1)
        self.call("remember", key="deep-fact", value=2)
        self.assertTrue(TwoLevelMemory(self.resident.memory).demote("deep-fact"))
        by_key = {item["key"]: item for item in self.call("memory_list")}
        self.assertEqual(by_key["deep-fact"]["tier"], "deep")
        self.assertEqual(by_key["hot-fact"]["tier"], "hot")

    def test_forget_still_uses_existing_path(self):
        self.call("remember", key="doomed", value="x")
        self.assertEqual(len(self.call("memory_list")), 1)
        forgotten = self.call("forget", key="doomed")
        self.assertEqual(forgotten, {"forgotten": True, "key": "doomed"})
        self.assertEqual(self.call("memory_list"), [])


if __name__ == "__main__":
    unittest.main()
