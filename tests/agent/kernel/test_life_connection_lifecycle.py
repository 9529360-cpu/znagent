from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.kernel.provider_bridge import build_resident_runtime


class LifeConnectionLifecycleTests(unittest.TestCase):
    def test_life_sqlite_connections_are_closed_after_pulse(self) -> None:
        real_connect = sqlite3.connect
        opened: list[sqlite3.Connection] = []

        def tracking_connect(*args, **kwargs):
            conn = real_connect(*args, **kwargs)
            opened.append(conn)
            return conn

        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "agent.kernel.life.sqlite3.connect",
                side_effect=tracking_connect,
            ):
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
