from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.app_competence import AppCompetenceRegistry
from zn_agent.core.app_competence_execution import AppCompetenceRecipeExecutor
from zn_agent.core.provider_bridge import build_resident_runtime


class AppCompetenceResidentWiringTests(unittest.TestCase):
    def test_product_resident_reuses_existing_action_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertIsInstance(resident.app_competences, AppCompetenceRegistry)
                self.assertIsInstance(
                    resident.app_competence_executor,
                    AppCompetenceRecipeExecutor,
                )
                self.assertIs(
                    resident.app_competence_executor.registry,
                    resident.app_competences,
                )
                self.assertIs(
                    resident.app_competence_executor.action_runtime,
                    resident.action_executor,
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
