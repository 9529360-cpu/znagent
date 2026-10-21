"""Q9: product-level end-to-end persistence acceptance for memory.

Backlog gap this closes: unit tests prove the SQLite rows survive a
reopened KernelStore, but the product-level contract -- "after the
Daemon/Kernel is torn down and rebuilt, a new session recalls old facts
with correct semantics (superseded values no longer current,
consolidation winners kept with unioned aliases)" -- was never formally
exercised.

Both tests use the product plumbing (``build_resident_runtime`` +
``ResidentRpcServer``), the same boundary ``test_memory_conversation_
product.py`` uses for resident lifetimes:

1. ``test_supersession_and_consolidation_survive_resident_reboot`` --
   session 1 writes through the real ``remember`` RPC path (supersession
   by similarity, supersession by same-key update, consolidation),
   captures a recall snapshot, the resident runtime is torn down and
   rebuilt around the same DB file -- the same boundary a Daemon restart
   crosses -- and session 2 must recall with identical semantics.
2. ``test_facts_written_in_a_different_process_recall_correctly`` --
   the write phase runs in a FRESH OS process that builds its own
   resident runtime, writes, closes, and exits, so the reading process
   shares zero in-process state with the writer: durability is purely
   the on-disk SQLite contract.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.models import utc_now
from zn_agent.core.provider_bridge import build_resident_runtime


def _repo_python_path() -> Path:
    # tests/zn_agent/core/ -> repo root
    return Path(__file__).resolve().parents[3] / "runtime" / "python"


class _ResidentLifetime:
    """Small helper mirroring the conversation-product test plumbing."""

    def boot(self) -> None:
        self.resident = build_resident_runtime(
            config={"model": {}}, store_path=self.path
        )
        self.rpc = ResidentRpcServer(self.resident)
        self._store_open = True

    def reboot(self) -> None:
        # The real teardown/rebuild boundary: close the store, then build
        # a brand-new resident runtime around the same DB file. Nothing
        # in-process (no caches, no ledger state) is carried over.
        self.resident.store.close()
        self._store_open = False
        self.boot()

    def call(self, method: str, **params):
        response = self.rpc.handle(
            {"id": method, "method": method, "params": params}
        )
        self.assertTrue(response["ok"], response)
        return response["result"]

    def remember(self, key: str, value, aliases=()) -> None:
        self.call("remember", key=key, value=value, aliases=list(aliases))

    def listed_keys(self) -> set[str]:
        return {
            fact["key"] for fact in self.call("memory_list")
        }


class MemoryPersistenceE2ETests(_ResidentLifetime, unittest.TestCase):
    """Supersession + consolidation semantics across a resident reboot."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.root / "kernel.db"
        self._store_open = False
        self.boot()
        self.addCleanup(self._close_store)

    def _close_store(self) -> None:
        if self._store_open:
            self.resident.store.close()
            self._store_open = False

    def _write_session_one(self) -> str:
        # Supersession by similarity: near-identical value, topical key.
        self.remember("reply language", "Chinese", aliases=("lang",))
        self.remember("response language", "Chinese")
        # Supersession by same-key update: old value must stop being current.
        self.remember("hometown", "Shenzhen")
        before_update = utc_now()
        time.sleep(0.05)
        self.remember("hometown", "Shanghai")
        # Consolidation: two keys claiming one normalized alias.
        self.remember("editor tab width", "4")
        self.remember("indentation width", "2", aliases=("editor tab width",))
        # No `consolidate` RPC exists; call the same StructuredMemory the
        # remember/forget RPCs go through.
        self.resident.memory.consolidate()
        return before_update

    _QUERIES = (
        "reply language",
        "response language",
        "hometown",
        "editor tab width",
        "indentation width",
        "lang",
    )

    def _recall_snapshot(self) -> list[tuple[str, str, str, str]]:
        snapshot = []
        for query in self._QUERIES:
            match = self.resident.memory.recall(query)
            snapshot.append(
                (
                    query,
                    match.key if match else "",
                    str(match.value) if match else "",
                    match.matched_by if match else "",
                )
            )
        return snapshot

    def test_supersession_and_consolidation_survive_resident_reboot(self):
        before_update = self._write_session_one()
        snapshot_before = self._recall_snapshot()
        self.reboot()

        # Restart must not change recall semantics: identical snapshot.
        snapshot_after = self._recall_snapshot()
        self.assertEqual(snapshot_after, snapshot_before)

        memory = self.resident.memory

        # Supersession by similarity: one surviving fact, aliases unioned.
        match = memory.recall("reply language")
        self.assertEqual(match.value, "Chinese")
        match = memory.recall("response language")
        self.assertEqual(match.key, "reply language")
        self.assertEqual(match.value, "Chinese")
        aliases = next(
            fact["aliases"]
            for fact in memory.store.list_facts()
            if fact["key"] == "reply language"
        )
        self.assertIn("lang", aliases)

        # Superseded value is no longer current, but history survives.
        match = memory.recall("hometown")
        self.assertEqual(match.value, "Shanghai")
        old = memory.recall_as_of("hometown", before_update)
        self.assertIsNotNone(old)
        self.assertEqual(old.value, "Shenzhen")

        # Consolidation: winner kept with unioned alias, loser gone.
        match = memory.recall("editor tab width")
        self.assertEqual(match.key, "indentation width")
        self.assertEqual(match.value, "2")
        match = memory.recall("indentation width")
        self.assertEqual(match.value, "2")
        self.assertEqual(
            self.listed_keys(),
            {"reply language", "hometown", "indentation width"},
        )

        # The removed fact's value is not current-recallable anywhere.
        hybrid_values = {
            str(item["value"])
            for item in memory.recall_hybrid("tab width", max_facts=10)
        }
        self.assertNotIn("4", hybrid_values)


class CrossProcessPersistenceTests(_ResidentLifetime, unittest.TestCase):
    """Write in one OS process, recall in another: pure on-disk contract."""

    _WRITE_SCRIPT = (
        "from pathlib import Path\n"
        "import sys\n"
        "from zn_agent.core.daemon import ResidentRpcServer\n"
        "from zn_agent.core.provider_bridge import build_resident_runtime\n"
        "db = Path(sys.argv[1])\n"
        "resident = build_resident_runtime(config={'model': {}}, store_path=db)\n"
        "rpc = ResidentRpcServer(resident)\n"
        "def remember(**params):\n"
        "    response = rpc.handle({'id': 'remember', 'method': 'remember', 'params': params})\n"
        "    assert response['ok'], response\n"
        "remember(key='reply language', value='Chinese', aliases=['lang'])\n"
        "remember(key='response language', value='Chinese')\n"
        "remember(key='hometown', value='Shanghai')\n"
        "remember(key='editor tab width', value='4')\n"
        "remember(key='indentation width', value='2', aliases=['editor tab width'])\n"
        "resident.memory.consolidate()\n"
        "resident.store.close()\n"
    )

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.root / "kernel.db"
        self._store_open = False
        self.addCleanup(self._close_store)

    def _close_store(self) -> None:
        if self._store_open:
            self.resident.store.close()
            self._store_open = False

    def test_facts_written_in_a_different_process_recall_correctly(self):
        env = dict(os.environ)
        python_path = str(_repo_python_path())
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            python_path if not existing else python_path + os.pathsep + existing
        )
        child = subprocess.run(
            [sys.executable, "-c", self._WRITE_SCRIPT, str(self.path)],
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        self.assertEqual(child.returncode, 0, child.stderr)

        # New process, new resident runtime, same DB file: the writer's
        # process is already gone, so recall can only come from disk.
        self.boot()
        memory = self.resident.memory

        match = memory.recall("response language")
        self.assertEqual(match.key, "reply language")
        self.assertEqual(match.value, "Chinese")
        match = memory.recall("hometown")
        self.assertEqual(match.value, "Shanghai")
        match = memory.recall("editor tab width")
        self.assertEqual(match.key, "indentation width")
        self.assertEqual(match.value, "2")
        self.assertEqual(
            self.listed_keys(),
            {"reply language", "hometown", "indentation width"},
        )


if __name__ == "__main__":
    unittest.main()
