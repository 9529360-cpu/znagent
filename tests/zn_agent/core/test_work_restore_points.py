from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.action import NativeActionIntent
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.models import WorkingState
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work_control import ResidentWorkControl


class WorkRestorePointTests(unittest.TestCase):
    @staticmethod
    def _prepare_work_overwrite(resident, ledger, target: Path, content: str):
        thread = ledger.create_thread(thread_id="restore-point-work")
        _, event = ledger.start(
            thread.thread_id,
            "replace one exact file while retaining its old bytes",
            payload={"required_capabilities": ["filesystem"]},
        )
        claimed = resident.store.claim_event(event.event_id)
        assert claimed is not None
        intent = NativeActionIntent(
            intent_id=f"intent-{event.event_id}",
            event_id=event.event_id,
            kind="write_text",
            args={
                "path": str(target),
                "content": content,
                "append": False,
                "create_parents": True,
            },
            source="native_deliberation",
        )
        state = WorkingState(
            current_event_id=event.event_id,
            stage="native_action",
            next_action="move body: write_text",
            data={"native_action_intent": intent.to_dict()},
        )
        resident.store.save_working_state(state)
        return event, intent, state

    @staticmethod
    def _capture_before_dispatch(resident, event, state):
        original_act = resident.body.act

        def crash_before_dispatch(kind: str, *, event_id=None, **args):
            if str(kind).lower() in {"write_text", "write_file"}:
                raise SystemExit("stop after restore point, before Body dispatch")
            return original_act(kind, event_id=event_id, **args)

        resident.body.act = crash_before_dispatch
        try:
            with unittest.TestCase().assertRaisesRegex(SystemExit, "after restore point"):
                resident._native_action_step(event, state, readiness=None)
        finally:
            resident.body.act = original_act

    def test_work_overwrite_persists_exact_old_bytes_before_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "document.txt"
            target.write_bytes(b"old\x00bytes\r\n")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            ledger = RecoveryBoundedWorkLedger(resident)
            event, _, state = self._prepare_work_overwrite(
                resident,
                ledger,
                target,
                "new exact text",
            )
            original_act = resident.body.act

            def crash_before_dispatch(kind: str, *, event_id=None, **args):
                if str(kind).lower() in {"write_text", "write_file"}:
                    raise SystemExit("stop after restore point, before Body dispatch")
                return original_act(kind, event_id=event_id, **args)

            resident.body.act = crash_before_dispatch
            try:
                with self.assertRaisesRegex(SystemExit, "after restore point"):
                    resident._native_action_step(event, state, readiness=None)
                points = resident.retained_work_restore_points(event.event_id)
                self.assertEqual(len(points), 1)
                point = points[0]
                self.assertEqual(point["event_id"], event.event_id)
                self.assertEqual(point["status"], "retained")
                self.assertEqual(point["size_bytes"], len(b"old\x00bytes\r\n"))
                persisted = resident.store.get_working_state()
                checkpoint = persisted.data["work_restore_point"]
                self.assertEqual(
                    checkpoint["restore_point_id"], point["restore_point_id"]
                )
                self.assertFalse(checkpoint["automatic_restore_authority"])
                with closing(sqlite3.connect(store_path)) as conn:
                    row = conn.execute(
                        "SELECT content FROM work_restore_points WHERE event_id=?",
                        (event.event_id,),
                    ).fetchone()
                self.assertIsNotNone(row)
                assert row is not None
                self.assertEqual(bytes(row[0]), b"old\x00bytes\r\n")
                self.assertEqual(target.read_bytes(), b"old\x00bytes\r\n")
            finally:
                resident.store.close()

    def test_restore_point_survives_resident_reconstruction_without_restoring(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old state", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            ledger = RecoveryBoundedWorkLedger(resident)
            event, _, state = self._prepare_work_overwrite(
                resident,
                ledger,
                target,
                "new state",
            )
            original_act = resident.body.act

            def crash_before_dispatch(kind: str, *, event_id=None, **args):
                if str(kind).lower() in {"write_text", "write_file"}:
                    raise SystemExit("simulated process loss")
                return original_act(kind, event_id=event_id, **args)

            resident.body.act = crash_before_dispatch
            try:
                with self.assertRaises(SystemExit):
                    resident._native_action_step(event, state, readiness=None)
                first = resident.retained_work_restore_points(event.event_id)
                self.assertEqual(len(first), 1)
            finally:
                resident.store.close()

            target.write_text("external current reality", encoding="utf-8")
            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            try:
                second = restored.retained_work_restore_points(event.event_id)
                self.assertEqual(second, first)
                self.assertEqual(
                    target.read_text(encoding="utf-8"),
                    "external current reality",
                )
            finally:
                restored.store.close()

    def test_read_only_work_projection_tracks_current_target_without_private_restore_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old private restore bytes", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=store_path
            )
            ledger = RecoveryBoundedWorkLedger(resident)
            event, _, state = self._prepare_work_overwrite(
                resident, ledger, target, "new state"
            )
            control = ResidentWorkControl(ledger)
            try:
                self._capture_before_dispatch(resident, event, state)

                thread, _ = control.get_snapshot("restore-point-work")
                points = thread.metadata["restore_points"]
                self.assertEqual(len(points), 1)
                point = points[0]
                self.assertEqual(point["event_id"], event.event_id)
                self.assertEqual(point["current_status"], "unchanged")
                self.assertFalse(point["automatic_restore_authority"])
                self.assertFalse(point["restore_application_available"])

                encoded = json.dumps(points, sort_keys=True)
                for private_name in (
                    "content",
                    "content_sha256",
                    "action_signature",
                    "intent_id",
                    "message_id",
                    "pre_identity_json",
                ):
                    self.assertNotIn(private_name, encoded)
                self.assertNotIn("old private restore bytes", encoded)

                target.write_text("external changed reality", encoding="utf-8")
                changed, _ = control.get_snapshot("restore-point-work")
                self.assertEqual(
                    changed.metadata["restore_points"][0]["current_status"],
                    "changed",
                )

                target.unlink()
                missing, _ = control.get_snapshot("restore-point-work")
                self.assertEqual(
                    missing.metadata["restore_points"][0]["current_status"],
                    "missing",
                )

                target.mkdir()
                unsupported, _ = control.get_snapshot("restore-point-work")
                self.assertEqual(
                    unsupported.metadata["restore_points"][0]["current_status"],
                    "unsupported",
                )
                self.assertTrue(target.is_dir())
            finally:
                resident.store.close()

    def test_work_get_projects_restore_points_after_restart_but_work_list_stays_lightweight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("retained before restart", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=store_path
            )
            ledger = RecoveryBoundedWorkLedger(resident)
            event, _, state = self._prepare_work_overwrite(
                resident, ledger, target, "new state"
            )
            try:
                self._capture_before_dispatch(resident, event, state)
            finally:
                resident.store.close()

            restored = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=store_path
            )
            server = ResidentRpcServer(
                resident=restored,
                input_stream=io.StringIO(),
                output_stream=io.StringIO(),
            )
            try:
                listed = server.handle(
                    {"id": "list", "method": "work_list", "params": {"limit": 24}}
                )
                self.assertTrue(listed["ok"])
                listed_thread = next(
                    item for item in listed["result"] if item["id"] == "restore-point-work"
                )
                self.assertNotIn("restore_points", listed_thread["metadata"])

                fetched = server.handle(
                    {
                        "id": "get",
                        "method": "work_get",
                        "params": {"thread_id": "restore-point-work"},
                    }
                )
                self.assertTrue(fetched["ok"])
                points = fetched["result"]["metadata"]["restore_points"]
                self.assertEqual(len(points), 1)
                self.assertEqual(points[0]["current_status"], "unchanged")
                self.assertEqual(points[0]["event_id"], event.event_id)
                self.assertEqual(target.read_text(encoding="utf-8"), "retained before restart")
                encoded = json.dumps(fetched["result"], sort_keys=True)
                self.assertNotIn("retained before restart", encoded)
                self.assertNotIn("content_sha256", encoded)
            finally:
                restored.store.close()

    def test_non_work_overwrite_does_not_create_restore_point(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store_path = root / "kernel.db"
            target = root / "document.txt"
            target.write_text("old", encoding="utf-8")
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=store_path,
            )
            event = resident.enqueue(
                "replace exact file",
                payload={"required_capabilities": ["filesystem"]},
            )
            claimed = resident.store.claim_event(event.event_id)
            assert claimed is not None
            intent = NativeActionIntent(
                intent_id=f"intent-{event.event_id}",
                event_id=event.event_id,
                kind="write_text",
                args={
                    "path": str(target),
                    "content": "new",
                    "append": False,
                    "create_parents": True,
                },
                source="native_deliberation",
            )
            state = WorkingState(
                current_event_id=event.event_id,
                stage="native_action",
                next_action="move body: write_text",
                data={"native_action_intent": intent.to_dict()},
            )
            resident.store.save_working_state(state)
            try:
                resident._native_action_step(event, state, readiness=None)
                self.assertEqual(
                    resident.retained_work_restore_points(event.event_id),
                    [],
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
