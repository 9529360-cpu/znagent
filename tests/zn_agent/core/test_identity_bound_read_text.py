from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.file_identity import (
    observe_file_identity,
    read_text_for_exact_file_identity,
)
from zn_agent.core.provider_bridge import build_resident_runtime


class IdentityBoundReadTextTests(unittest.TestCase):
    def test_exact_read_rejects_path_swap_before_reading_foreign_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "source.txt"
            original = root / "original.txt"
            decoy = root / "decoy.txt"
            target.write_text("approved source\n", encoding="utf-8")
            decoy.write_text("FOREIGN-SWAP-SECRET\n", encoding="utf-8")
            baseline = observe_file_identity(target, max_hash_bytes=64 * 1024)
            real_open = Path.open
            expected_path = os.path.normcase(str(baseline["path"]))
            swapped = False

            def swap_then_open(path: Path, *args, **kwargs):
                nonlocal swapped
                current_path = os.path.normcase(os.path.abspath(str(path)))
                if not swapped and current_path == expected_path:
                    swapped = True
                    os.replace(target, original)
                    os.replace(decoy, target)
                return real_open(path, *args, **kwargs)

            with patch.object(Path, "open", swap_then_open):
                text, current, error = read_text_for_exact_file_identity(
                    target,
                    baseline,
                    max_bytes=64 * 1024,
                )

            self.assertTrue(swapped)
            self.assertIsNone(text)
            self.assertIsNone(current)
            self.assertIn("identity", str(error or "").lower())

    def test_product_body_keeps_exact_read_live_but_redacts_durable_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "source.txt"
            secret = "TRANSIENT-EXACT-SOURCE-9f84"
            target.write_text(secret + "\n", encoding="utf-8")
            baseline = observe_file_identity(target, max_hash_bytes=64 * 1024)
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            try:
                result = resident.body.act(
                    "read_text",
                    event_id="evt-identity-bound-read",
                    path=str(target),
                    max_chars=20_000,
                    max_bytes=64 * 1024,
                    expected_file_identity=dict(baseline),
                )
                self.assertTrue(result.success, result)
                self.assertIn(secret, result.output)
                self.assertTrue(result.data.get("identity_bound"))

                persisted = next(
                    item
                    for item in resident.body.recent_actions(16)
                    if item.action_id == result.action_id
                )
                self.assertEqual(persisted.output, "")
                self.assertTrue(persisted.data.get("read_text_output_redacted"))
                self.assertEqual(
                    persisted.data.get("content_sha256"),
                    baseline.get("content_sha256"),
                )

                with closing(sqlite3.connect(resident.store.path)) as conn:
                    row = conn.execute(
                        "SELECT action_json,result_json FROM native_body_actions WHERE action_id=?",
                        (result.action_id,),
                    ).fetchone()
                self.assertIsNotNone(row)
                action_json, result_json = str(row[0]), str(row[1])
                self.assertNotIn(secret, action_json)
                self.assertNotIn(secret, result_json)
                action = json.loads(action_json)
                self.assertNotIn("expected_file_identity", action["args"])
                self.assertTrue(action["args"]["expected_file_identity_bound"])
                self.assertEqual(
                    action["args"]["expected_content_sha256"],
                    baseline["content_sha256"],
                )

                generic = resident.body.act(
                    "read_text",
                    event_id="evt-generic-read",
                    path=str(target),
                    max_chars=20_000,
                )
                self.assertTrue(generic.success, generic)
                generic_persisted = next(
                    item
                    for item in resident.body.recent_actions(16)
                    if item.action_id == generic.action_id
                )
                self.assertIn(secret, generic_persisted.output)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
