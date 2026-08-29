from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.completion_observation import CompletionObservationJournal


class _Store:
    def __init__(self, path: Path) -> None:
        self.path = path


class _Life:
    def __init__(self, *, fail_event: str | None = None) -> None:
        self.fail_event = fail_event
        self.observed: list[str] = []

    def observe_action(self, result) -> None:
        event_id = result.event.event_id
        self.observed.append(event_id)
        if event_id == self.fail_event:
            raise RuntimeError("persistent private life failure")


class _Resident:
    def __init__(
        self,
        event_ids: list[str],
        *,
        missing_result: str | None = None,
        fail_event: str | None = None,
    ) -> None:
        self._event_ids = set(event_ids)
        self.missing_result = missing_result
        self.life = _Life(fail_event=fail_event)

    def result_for(self, event_id: str):
        if event_id == self.missing_result or event_id not in self._event_ids:
            return None
        return SimpleNamespace(event=SimpleNamespace(event_id=event_id))


class CompletionObservationBacklogRecoveryTests(unittest.TestCase):
    def test_startup_sweep_attempts_backlog_beyond_legacy_128_limit_once_each(self):
        with tempfile.TemporaryDirectory() as root:
            database = Path(root) / "kernel.db"
            journal = CompletionObservationJournal(_Store(database))
            event_ids = [f"event-{index:03d}" for index in range(200)]
            with closing(sqlite3.connect(database)) as conn:
                conn.executemany(
                    "INSERT INTO resident_completion_observations"
                    "(event_id,stage,status,attempts,last_error,updated_at) "
                    "VALUES(?,'life','pending',0,NULL,?)",
                    [(event_id, f"2026-01-01T00:00:{index:03d}Z") for index, event_id in enumerate(event_ids)],
                )
                conn.commit()

            # The first row cannot reconstruct its EventOutcome and the second
            # repeatedly fails Life observation. Neither may starve rows 128+.
            resident = _Resident(
                event_ids,
                missing_result=event_ids[0],
                fail_event=event_ids[1],
            )
            repaired = journal.repair_life(resident)

            self.assertEqual(repaired, 198)
            self.assertEqual(len(resident.life.observed), 199)
            self.assertEqual(len(set(resident.life.observed)), 199)
            self.assertIn(event_ids[-1], resident.life.observed)
            self.assertEqual(journal.state(event_ids[0])["status"], "pending")
            self.assertEqual(journal.state(event_ids[1])["status"], "pending")
            self.assertEqual(journal.state(event_ids[-1])["status"], "completed")

    def test_explicit_limit_keeps_bounded_manual_repair_behavior(self):
        with tempfile.TemporaryDirectory() as root:
            database = Path(root) / "kernel.db"
            journal = CompletionObservationJournal(_Store(database))
            event_ids = [f"event-{index:03d}" for index in range(20)]
            with closing(sqlite3.connect(database)) as conn:
                conn.executemany(
                    "INSERT INTO resident_completion_observations"
                    "(event_id,stage,status,attempts,last_error,updated_at) "
                    "VALUES(?,'life','pending',0,NULL,?)",
                    [(event_id, f"2026-01-01T00:00:{index:03d}Z") for index, event_id in enumerate(event_ids)],
                )
                conn.commit()

            resident = _Resident(event_ids)
            repaired = journal.repair_life(resident, limit=5)

            self.assertEqual(repaired, 5)
            self.assertEqual(len(resident.life.observed), 5)
            self.assertEqual(journal.pending_count(stage="life"), 15)


if __name__ == "__main__":
    unittest.main(verbosity=2)
