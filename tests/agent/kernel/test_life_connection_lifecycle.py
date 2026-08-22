from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.kernel.life import ZNLifeCore
from agent.kernel.provider_bridge import build_resident_runtime


class LifeConnectionLifecycleTests(unittest.TestCase):
    def test_life_sqlite_connections_are_closed_after_pulse(self) -> None:
        real_connect = ZNLifeCore._connect
        opened: list[sqlite3.Connection] = []

        def tracking_connect(life: ZNLifeCore) -> sqlite3.Connection:
            conn = real_connect(life)
            opened.append(conn)
            return conn

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ZNLifeCore, "_connect", tracking_connect):
                resident = build_resident_runtime(
                    config={"model": {}},
                    store_path=Path(tmp) / "kernel.db",
                )
                resident.pulse()
                resident.life.snapshot()

            self.assertGreater(len(opened), 0)
            for conn in opened:
                with self.assertRaises(sqlite3.ProgrammingError):
                    conn.execute("SELECT 1")
            resident.store.close()


if __name__ == "__main__":
    unittest.main()
