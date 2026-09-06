from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zn_agent.core.delegated_work_coordinator import DelegatedWorkCoordinator
from zn_agent.core.provider_bridge import build_resident_runtime


class DelegatedWorkCoordinatorTests(unittest.TestCase):
    def test_active_product_runtime_composes_one_internal_coordinator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                first = resident._delegated_work_coordinator()
                second = resident._delegated_work_coordinator()
                self.assertIs(first, second)
                self.assertIsInstance(first, DelegatedWorkCoordinator)
                self.assertIs(first.resident, resident)
                self.assertIs(first.resident.work_ledger, resident.work_ledger)
                self.assertIs(first.resident.kernel.router, resident.kernel.router)
                self.assertIs(first.resident.body, resident.body)
            finally:
                resident.store.close()

    def test_active_prepare_path_routes_through_coordinator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                coordinator = resident._delegated_work_coordinator()
                sentinel = SimpleNamespace(bound=True)
                event = SimpleNamespace()
                root = SimpleNamespace()
                request = SimpleNamespace()
                completed = []
                with patch.object(coordinator, "prepare_request", return_value=sentinel) as prepare:
                    result = resident._prepare_delegated_worker_request(
                        event,
                        root,
                        request,
                        completed,
                    )
                self.assertIs(result, sentinel)
                prepare.assert_called_once_with(event, root, request, completed)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
