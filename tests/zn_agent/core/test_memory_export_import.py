"""Q15: memory export / import (Blueprint §6.5 export/migrate)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.memory_export import (
    MEMORY_EXPORT_VERSION,
    export_facts_to_file,
    import_facts_from_file,
)
from zn_agent.core.provider_bridge import build_resident_runtime


class MemoryExportImportTests(unittest.TestCase):
    """Versioned facts takeout and restore, incl. conflict and path policy."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.resident = build_resident_runtime(
            config={"model": {}}, store_path=self.root / "kernel.db"
        )
        self.addCleanup(lambda: self.resident.store.close())
        self.store = self.resident.store
        self.memory = self.resident.memory

    def _export_path(self, name="memory-export.json"):
        return self.root / name

    def _seed(self):
        self.memory.remember(
            "project", {"name": "Artemis"}, aliases=("active project",)
        )
        self.memory.remember(
            "response language",
            "Chinese",
            sensitivity="sensitive",
            expires_at="2031-06-01T00:00:00+00:00",
        )
        self.memory.remember("ephemeral note", "do not keep", sensitivity="non_retainable")

    def _wipe_facts(self):
        for fact in self.store.list_facts():
            self.store.delete_fact(fact["key"])

    # -- export ---------------------------------------------------------

    def test_export_payload_is_versioned_and_complete(self):
        self._seed()
        result = export_facts_to_file(self.store, str(self._export_path()))
        self.assertEqual(result["exported"], 3)
        self.assertEqual(result["version"], MEMORY_EXPORT_VERSION)

        payload = json.loads(self._export_path().read_text(encoding="utf-8"))
        self.assertEqual(
            set(payload), {"version", "exported_at", "fact_count", "facts"}
        )
        self.assertEqual(payload["version"], MEMORY_EXPORT_VERSION)
        self.assertEqual(payload["fact_count"], 3)
        by_key = {entry["key"]: entry for entry in payload["facts"]}
        # Full fidelity per row, values included (explicit takeout).
        project = by_key["project"]
        self.assertEqual(project["value"], {"name": "Artemis"})
        self.assertEqual(project["aliases"], ["active project"])
        self.assertEqual(project["sensitivity"], "normal")
        self.assertIsNone(project["expires_at"])
        lang = by_key["response language"]
        self.assertEqual(lang["value"], "Chinese")
        self.assertEqual(lang["sensitivity"], "sensitive")
        self.assertEqual(lang["expires_at"], "2031-06-01T00:00:00+00:00")
        self.assertTrue(project["created_at"] and project["updated_at"])
        # non_retainable facts belong to the user too: takeout includes them.
        self.assertEqual(by_key["ephemeral note"]["sensitivity"], "non_retainable")

    def test_export_contains_only_facts_no_credential_store_material(self):
        self._seed()
        export_facts_to_file(self.store, str(self._export_path()))
        payload = json.loads(self._export_path().read_text(encoding="utf-8"))
        self.assertEqual(
            set(payload), {"version", "exported_at", "fact_count", "facts"}
        )
        for entry in payload["facts"]:
            self.assertEqual(
                set(entry),
                {
                    "key",
                    "value",
                    "aliases",
                    "created_at",
                    "updated_at",
                    "expires_at",
                    "sensitivity",
                },
                entry,
            )

    def test_export_rejects_path_traversal(self):
        self._seed()
        with self.assertRaises(ValueError) as ctx:
            export_facts_to_file(self.store, str(self.root / ".." / "evil.json"))
        self.assertIn("traversal", str(ctx.exception))

    def test_export_rejects_missing_parent_directory(self):
        with self.assertRaises(ValueError) as ctx:
            export_facts_to_file(self.store, str(self.root / "nope" / "out.json"))
        self.assertIn("does not exist", str(ctx.exception))

    def test_export_rejects_directory_target(self):
        with self.assertRaises(ValueError) as ctx:
            export_facts_to_file(self.store, str(self.root))
        self.assertIn("directory", str(ctx.exception))

    # -- import ---------------------------------------------------------

    def test_round_trip_restores_sensitivity_and_expiry(self):
        self._seed()
        export_facts_to_file(self.store, str(self._export_path()))
        self._wipe_facts()
        self.assertEqual(self.store.list_facts(), [])

        result = import_facts_from_file(self.store, str(self._export_path()))
        self.assertEqual(
            result, {"imported": 3, "skipped": 0, "overwritten": 0,
                     "version": MEMORY_EXPORT_VERSION}
        )
        by_key = {fact["key"]: fact for fact in self.store.list_facts()}
        self.assertEqual(by_key["project"]["value"], {"name": "Artemis"})
        self.assertEqual(tuple(by_key["project"]["aliases"]), ("active project",))
        self.assertEqual(by_key["response language"]["sensitivity"], "sensitive")
        self.assertEqual(
            by_key["response language"]["expires_at"], "2031-06-01T00:00:00+00:00"
        )
        self.assertEqual(
            by_key["ephemeral note"]["sensitivity"], "non_retainable"
        )

    def test_import_conflict_default_skips_without_touching(self):
        self._seed()
        export_facts_to_file(self.store, str(self._export_path()))
        # Re-importing the same file: everything is a conflict -> skip.
        result = import_facts_from_file(self.store, str(self._export_path()))
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["skipped"], 3)
        self.assertEqual(result["overwritten"], 0)
        # The existing rows are untouched.
        by_key = {fact["key"]: fact for fact in self.store.list_facts()}
        self.assertEqual(by_key["project"]["value"], {"name": "Artemis"})

    def test_import_overwrite_replaces_conflicts(self):
        self._seed()
        export_facts_to_file(self.store, str(self._export_path()))
        # Drift the live store, then import with overwrite.
        self.memory.remember("project", {"name": "Drifted"})
        result = import_facts_from_file(
            self.store, str(self._export_path()), overwrite=True
        )
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["overwritten"], 3)
        self.assertEqual(
            self.store.get_fact("project"), {"name": "Artemis"}
        )

    def test_import_partial_overlap(self):
        self._seed()
        export_facts_to_file(self.store, str(self._export_path()))
        self._wipe_facts()
        self.memory.remember("project", {"name": "Fresh"})  # one conflict only
        result = import_facts_from_file(self.store, str(self._export_path()))
        self.assertEqual(result["imported"], 2)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["overwritten"], 0)

    def test_import_rejects_missing_file(self):
        with self.assertRaises(ValueError) as ctx:
            import_facts_from_file(self.store, str(self.root / "absent.json"))
        self.assertIn("does not exist", str(ctx.exception))

    def test_import_rejects_path_traversal(self):
        with self.assertRaises(ValueError) as ctx:
            import_facts_from_file(self.store, str(self.root / ".." / "evil.json"))
        self.assertIn("traversal", str(ctx.exception))

    def test_import_rejects_non_json(self):
        bad = self.root / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            import_facts_from_file(self.store, str(bad))
        self.assertIn("not valid JSON", str(ctx.exception))
        self.assertEqual(self.store.list_facts(), [])

    def test_import_rejects_wrong_version(self):
        bad = self.root / "v2.json"
        bad.write_text(
            json.dumps({"version": 2, "fact_count": 0, "facts": []}),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError) as ctx:
            import_facts_from_file(self.store, str(bad))
        self.assertIn("unsupported memory export version", str(ctx.exception))

    def test_import_rejects_malformed_entries_without_partial_writes(self):
        self.memory.remember("kept", "original")
        for broken in (
            {"version": 1, "facts": [{"value": "no key"}]},  # missing key
            {"version": 1, "facts": [{"key": "k", "sensitivity": "bogus"}]},
            {"version": 1, "facts": [{"key": "k", "expires_at": "not-a-date"}]},
            {"version": 1, "facts": "not-a-list"},
            {"version": 1, "facts": [{"key": "", "value": 1}]},
        ):
            bad = self.root / "broken.json"
            bad.write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaises(ValueError, msg=json.dumps(broken)):
                import_facts_from_file(self.store, str(bad))
        # Fail closed: the pre-existing row is untouched, nothing landed.
        self.assertEqual(self.store.get_fact("kept"), "original")
        self.assertEqual(len(self.store.list_facts()), 1)

    def test_import_refuses_credential_shaped_value(self):
        # The M15 gate runs on import too: a raw credential-shaped value in
        # the export file is refused explicitly, not silently dropped.
        bad = self.root / "cred.json"
        bad.write_text(
            json.dumps(
                {
                    "version": 1,
                    "fact_count": 1,
                    "facts": [
                        {
                            "key": "service login",
                            "value": "api_key=topsecretvalue",
                            "aliases": [],
                            "created_at": None,
                            "updated_at": None,
                            "expires_at": None,
                            "sensitivity": "normal",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError) as ctx:
            import_facts_from_file(self.store, str(bad))
        self.assertIn("credential", str(ctx.exception).lower())
        self.assertEqual(self.store.list_facts(), [])

    # -- daemon RPC -----------------------------------------------------

    def test_rpc_export_import_end_to_end(self):
        rpc = ResidentRpcServer(self.resident)

        def call(method, **params):
            response = rpc.handle({"id": method, "method": method, "params": params})
            self.assertTrue(response["ok"], response.get("error"))
            return response["result"]

        self._seed()
        exported = call("memory_export", path=str(self._export_path()))
        self.assertEqual(exported["exported"], 3)
        self.assertTrue(exported["file"].endswith("memory-export.json"))

        self._wipe_facts()
        imported = call("memory_import", path=str(self._export_path()))
        self.assertEqual(imported["imported"], 3)
        self.assertEqual(imported["skipped"], 0)

        # Unknown method names stay unknown; bad import is explicit.
        with self.assertRaises(ValueError):
            rpc.handle(
                {"id": "x", "method": "memory_export", "params": {"path": ""}}
            )
        with self.assertRaises(ValueError) as ctx:
            rpc.handle(
                {
                    "id": "y",
                    "method": "memory_import",
                    "params": {"path": str(self.root / "absent.json")},
                }
            )
        self.assertIn("does not exist", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
