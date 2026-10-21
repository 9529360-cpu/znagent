from __future__ import annotations

"""Q16: sensitive-tier memory facts never enter the proactive surface.

``non_retainable`` / ``sensitive`` routine facts must not be rendered into
the suggestion bar (fail closed: unknown future tiers are withheld too),
while explicit reads (``memory_list`` / ``recall`` / ``forget``) still see
them -- Q11 semantics are unchanged.
"""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.suggestions import SuggestionEngine
from zn_agent.core.work import ResidentWorkLedger


class SuggestionsSensitivityTests(unittest.TestCase):
    @staticmethod
    def _resident(db: Path):
        return build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=db,
        )

    def _engine(self, tmp: str):
        db = Path(tmp) / "kernel.db"
        resident = self._resident(db)
        ledger = ResidentWorkLedger(resident)
        engine = SuggestionEngine(resident, ledger)
        return resident, ledger, engine

    def test_non_retainable_routine_fact_never_enters_suggestions(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, _ledger, engine = self._engine(tmp)
            try:
                resident.memory.remember(
                    "routine:nightly backup",
                    "back up the workstation at 03:00",
                    sensitivity="non_retainable",
                )
                suggestions = engine.list_suggestions()
                self.assertEqual(suggestions, [])
                # The fact itself is still durable and visible via the
                # explicit read path (Q11 semantics unchanged).
                by_key = {
                    f["key"]: f for f in resident.store.list_facts()
                }
                self.assertIn("routine:nightly backup", by_key)
                self.assertEqual(
                    by_key["routine:nightly backup"]["sensitivity"],
                    "non_retainable",
                )
                self.assertEqual(
                    by_key["routine:nightly backup"]["value"],
                    "back up the workstation at 03:00",
                )
            finally:
                resident.store.close()

    def test_sensitive_routine_fact_is_withheld_and_value_never_leaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, _ledger, engine = self._engine(tmp)
            try:
                secret = "confirm the 6225**** account balance"
                resident.memory.remember(
                    "routine:weekly balance check", secret, sensitivity="sensitive"
                )
                suggestions = engine.list_suggestions()
                self.assertEqual(suggestions, [])
                # No value text may leak into any suggestion title/task,
                # even from a different source kind.
                rendered = " ".join(
                    f"{s.get('title', '')} {s.get('task', '')}"
                    for s in suggestions
                )
                self.assertNotIn(secret, rendered)
                by_key = {
                    f["key"]: f for f in resident.store.list_facts()
                }
                self.assertIn("routine:weekly balance check", by_key)
                self.assertEqual(
                    by_key["routine:weekly balance check"]["sensitivity"],
                    "sensitive",
                )
            finally:
                resident.store.close()

    def test_normal_routine_fact_still_suggested(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, _ledger, engine = self._engine(tmp)
            try:
                resident.memory.remember(
                    "routine:weekly review", "review the weekly notes"
                )
                suggestions = engine.list_suggestions()
                self.assertEqual(len(suggestions), 1)
                item = suggestions[0]
                self.assertEqual(item["kind"], "routine")
                self.assertEqual(item["task"], "review the weekly notes")
                self.assertEqual(
                    item["source"]["fact_key"], "routine:weekly review"
                )
            finally:
                resident.store.close()

    def test_mixed_tiers_only_normal_enters_the_bar(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, _ledger, engine = self._engine(tmp)
            try:
                resident.memory.remember(
                    "routine:a-normal", "do the normal thing"
                )
                resident.memory.remember(
                    "routine:b-sensitive",
                    "do the sensitive thing",
                    sensitivity="sensitive",
                )
                resident.memory.remember(
                    "routine:c-non-retainable",
                    "do the non-retainable thing",
                    sensitivity="non_retainable",
                )
                suggestions = engine.list_suggestions()
                self.assertEqual(len(suggestions), 1)
                self.assertEqual(
                    suggestions[0]["source"]["fact_key"], "routine:a-normal"
                )
            finally:
                resident.store.close()

    def test_unknown_future_tier_is_withheld_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident, _ledger, engine = self._engine(tmp)
            try:
                # Direct SQL: remember() would reject an unknown tier via
                # normalize_sensitivity, so an out-of-band row is the only
                # way a future tier reaches the store before code knows it.
                now = "2026-10-21T15:00:00+00:00"
                with closing(sqlite3.connect(db)) as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO facts("
                        "fact_key,value_json,aliases_json,"
                        "created_at,updated_at,expires_at,sensitivity"
                        ") VALUES(?,?,?,?,?,?,?)",
                        (
                            "routine:future tier",
                            json.dumps("a future-tier task"),
                            "[]",
                            now,
                            now,
                            None,
                            "confidential_v9",
                        ),
                    )
                    conn.commit()
                suggestions = engine.list_suggestions()
                self.assertEqual(suggestions, [])
                # The row itself is still readable explicitly (Q11).
                by_key = {
                    f["key"]: f for f in resident.store.list_facts()
                }
                self.assertIn("routine:future tier", by_key)
                self.assertEqual(
                    by_key["routine:future tier"]["sensitivity"],
                    "confidential_v9",
                )
            finally:
                resident.store.close()

    def test_suggestions_rpc_does_not_expose_withheld_facts(self):
        import io

        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            try:
                server = ResidentRpcServer(
                    resident=resident,
                    input_stream=io.StringIO(),
                    output_stream=io.StringIO(),
                )
                resident.memory.remember(
                    "routine:quiet backup",
                    "back up the home directory",
                    sensitivity="sensitive",
                )
                listed = server.handle(
                    {"id": "1", "method": "suggestions_list", "params": {}}
                )
                self.assertTrue(listed["ok"])
                self.assertEqual(listed["result"], [])

                # The explicit memory_list RPC still shows the fact's key
                # and tier (Q11: values are never rendered by memory_list).
                memory = server.handle(
                    {"id": "2", "method": "memory_list", "params": {}}
                )
                self.assertTrue(memory["ok"])
                by_key = {f["key"]: f for f in memory["result"]}
                self.assertIn("routine:quiet backup", by_key)
                self.assertEqual(
                    by_key["routine:quiet backup"]["sensitivity"], "sensitive"
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
