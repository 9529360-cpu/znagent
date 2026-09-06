from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.capabilities import ExactTaskCapability
from zn_agent.core.models import CapabilityResult
from zn_agent.core.provider_bridge import build_resident_runtime


class DirectWorkAvoidsDelegationTests(unittest.TestCase):
    def test_deterministic_native_capability_uses_no_worker_run_or_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident = build_resident_runtime(config={"model": {}}, store_path=root / "kernel.db")
            try:
                resident.capabilities.register(
                    ExactTaskCapability(
                        name="deterministic-project-check",
                        triggers=("report deterministic project state",),
                        handler=lambda event, state: CapabilityResult(
                            success=True,
                            response="project state is locally known",
                        ),
                    )
                )
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="direct", title="Direct")
                _, event = ledger.start(
                    "direct",
                    "report deterministic project state",
                    payload={"model_policy": "never"},
                )

                result = resident.run_once(target_event_id=event.event_id)

                self.assertIsNotNone(result)
                assert result is not None
                self.assertTrue(result.success)
                self.assertEqual(result.model_invocations, 0)
                self.assertEqual(result.response, "project state is locally known")
                self.assertEqual(ledger.list_worker_runs(thread_id="direct"), [])
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
