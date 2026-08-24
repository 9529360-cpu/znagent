from __future__ import annotations

import io
import sqlite3
import tempfile
import traceback
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime


class ResidentSQLiteLifecycleTests(unittest.TestCase):
    def test_resident_and_rpc_short_connections_are_explicitly_closed(self) -> None:
        real_connect = sqlite3.connect
        opened: list[tuple[sqlite3.Connection, str]] = []

        def tracking_connect(*args, **kwargs):
            conn = real_connect(*args, **kwargs)
            origin = "".join(traceback.format_stack(limit=12))
            opened.append((conn, origin))
            return conn

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            with patch.object(sqlite3, "connect", tracking_connect):
                resident = build_resident_runtime(
                    config={"model": {}},
                    store_path=db,
                )
                server = ResidentRpcServer(
                    resident=resident,
                    input_stream=io.StringIO(),
                    output_stream=io.StringIO(),
                )
                resident.pulse()
                created = server.handle(
                    {
                        "id": "create",
                        "method": "work_create",
                        "params": {"title": "connection lifecycle probe"},
                    }
                )
                self.assertTrue(created["ok"])
                listed = server.handle(
                    {"id": "list", "method": "work_list", "params": {"limit": 5}}
                )
                self.assertTrue(listed["ok"])

            resident.store.close()

            leaked: list[str] = []
            for conn, origin in opened:
                try:
                    conn.execute("SELECT 1")
                except sqlite3.ProgrammingError:
                    continue
                else:
                    leaked.append(origin)
                    conn.close()

            self.assertEqual(
                leaked,
                [],
                "SQLite connections remained open after their owning operation:\n"
                + "\n--- leaked connection ---\n".join(leaked),
            )


if __name__ == "__main__":
    unittest.main()
