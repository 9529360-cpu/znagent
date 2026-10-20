from __future__ import annotations

"""P3-13: identical overwrite re-dispatches are idempotent at the restore-point layer.

DSH-4 known boundary: a repeated identical write_file/write_text dispatch within
one event used to crash the restore-point layer on intent_id
(`durable Work restore point conflicts on intent_id`). The same
(event_id, action_signature, target_path) must now return the already-verified
existing restore point instead of crashing.
"""

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger


class WorkRestorePointIdempotentRedispatchTests(unittest.TestCase):
    @staticmethod
    def _intent(event_id: str, target: Path, tag: str) -> NativeActionIntent:
        return NativeActionIntent(
            intent_id=f"intent-{tag}",
            event_id=event_id,
            kind="write_text",
            args={
                "path": str(target),
                "content": "same content\n",
                "append": False,
                "create_parents": True,
            },
            source="native_deliberation",
        )

    def test_identical_redispatch_returns_same_restore_point_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old stable state", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=store_path
            )
            try:
                ledger = RecoveryBoundedWorkLedger(resident)
                thread = ledger.create_thread(thread_id="restore-idempotent")
                _, event = ledger.start(
                    thread.thread_id,
                    "repeat the identical overwrite",
                    payload={"required_capabilities": ["filesystem"]},
                )
                assert resident.store.claim_event(event.event_id) is not None

                original_act = resident.body.act

                def stop_before_dispatch(kind: str, *, event_id=None, **args):
                    if str(kind).lower() in {"write_text", "write_file"}:
                        raise SystemExit("stop after restore point, before Body dispatch")
                    return original_act(kind, event_id=event_id, **args)

                resident.body.act = stop_before_dispatch
                try:
                    restore_point_ids = []
                    for n in range(1, 6):
                        intent = self._intent(event.event_id, target, f"redispatch-{n}")
                        state = WorkingState(
                            current_event_id=event.event_id,
                            stage="native_action",
                            next_action="move body: write_text",
                            data={"native_action_intent": intent.to_dict()},
                        )
                        resident.store.save_working_state(state)
                        # Must not crash (previously: RuntimeError on intent_id,
                        # i.e. the DSH-4 known boundary).
                        with self.assertRaisesRegex(
                            SystemExit, "stop after restore point"
                        ):
                            resident._native_action_step(event, state, readiness=None)
                        held = resident.store.get_working_state()
                        restore_point_ids.append(
                            held.data["work_restore_point"]["restore_point_id"]
                        )
                finally:
                    resident.body.act = original_act

                # All five dispatches resolve to the same restore point.
                self.assertEqual(len(set(restore_point_ids)), 1)
                retained = resident.retained_work_restore_points(event.event_id)
                self.assertEqual(len(retained), 1)
                self.assertEqual(
                    retained[0]["restore_point_id"], restore_point_ids[0]
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
