from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.body import BodyAction, BodyActionResult
from zn_agent.core.current_app_text_body import CurrentAppTextAwareBody
from zn_agent.core.local_service_recovery_behavior import (
    _INSTALL_MARKER,
    _Blocked,
    _observe_repair_script_identity,
    _relative_file,
    _request,
    _same_identity,
    _same_repair_script_identity,
    _service_context,
)
from zn_agent.core.path_context import canonical_host_path
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.store import KernelStore


TASK = (
    "看看这个服务为什么挂了，项目里的 `repair_service.py` 是它的安全修复脚本；"
    "能安全修就修，修好以后确认它真的恢复。"
)


class LocalServiceRecoveryAdmissionTests(unittest.TestCase):
    @staticmethod
    def _event(task: str, **payload):
        return SimpleNamespace(
            kind="desktop_user_event",
            task=task,
            payload=dict(payload),
        )

    def test_request_requires_service_repair_verify_intent_and_one_python_script(self) -> None:
        request = _request(self._event(TASK))
        self.assertEqual(request, {"repair_script": "repair_service.py"})

        self.assertIsNone(_request(self._event("看看这个服务为什么挂了。")))
        self.assertIsNone(
            _request(
                self._event(
                    "看看这个服务为什么挂了，`repair_service.py` 能安全修就修。"
                )
            )
        )
        ambiguous = _request(
            self._event(
                "看看这个服务为什么挂了，`a.py` 和 `b.py` 都能安全修，修好后确认恢复。"
            )
        )
        self.assertEqual(ambiguous, {"repair_script": ""})
        self.assertIsNone(self._event(TASK, body_action="command") and _request(
            self._event(TASK, body_action="command")
        ))

    def test_relative_repair_file_cannot_escape_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_workspace = root / "workspace"
            raw_workspace.mkdir()
            (raw_workspace / "repair_service.py").write_text("print('ok')\n", encoding="utf-8")
            outside = root / "outside.py"
            outside.write_text("print('no')\n", encoding="utf-8")

            # Real Work attachment canonicalizes host paths before they become
            # durable authority. Mirror that product contract here so Windows
            # NetworkService 8.3 TEMP aliases do not create an artificial
            # short-path-vs-long-path containment mismatch in this helper test.
            workspace = canonical_host_path(raw_workspace).resolve(strict=True)
            resolved = _relative_file(
                workspace,
                "repair_service.py",
                code="repair_authority_missing",
                suffix=".py",
            )
            self.assertEqual(
                resolved,
                canonical_host_path(raw_workspace / "repair_service.py").resolve(strict=True),
            )

            with self.assertRaises(_Blocked):
                _relative_file(
                    workspace,
                    "../outside.py",
                    code="repair_authority_missing",
                    suffix=".py",
                )

    def test_service_context_is_loopback_and_log_scope_is_attached_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = canonical_host_path(tmp).resolve(strict=True)
            (workspace / "service.log").write_text("boot\n", encoding="utf-8")
            event = self._event(
                TASK,
                local_service_context={
                    "host": "127.0.0.1",
                    "port": 8129,
                    "expected_process_name": "python.exe",
                    "health_path": "/health",
                    "log_relative_path": "service.log",
                },
            )
            args, log_path = _service_context(event, workspace)
            self.assertEqual(args["port"], 8129)
            self.assertEqual(args["log_root"], str(workspace))
            self.assertEqual(log_path, (workspace / "service.log").resolve())
            self.assertEqual(args["health_url"], "http://127.0.0.1:8129/health")

            outside = self._event(
                TASK,
                local_service_context={
                    "host": "example.com",
                    "port": 8129,
                    "expected_process_name": "python.exe",
                    "health_path": "/health",
                    "log_relative_path": "service.log",
                },
            )
            with self.assertRaises(_Blocked):
                _service_context(outside, workspace)

    def test_pid_plus_creation_time_is_required_for_identity_stability(self) -> None:
        baseline = {"pid": 42, "created_at_epoch": 1000.25}
        self.assertTrue(_same_identity(baseline, {"pid": 42, "created_at_epoch": 1000.25}))
        self.assertFalse(_same_identity(baseline, {"pid": 42, "created_at_epoch": 1001.25}))
        self.assertFalse(_same_identity(baseline, {"pid": 43, "created_at_epoch": 1000.25}))

    def test_repair_script_identity_detects_content_drift_without_persisting_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "repair_service.py"
            script.write_text("print('first')\n", encoding="utf-8")
            baseline = _observe_repair_script_identity(script)
            unchanged = _observe_repair_script_identity(script)
            self.assertTrue(_same_repair_script_identity(baseline, unchanged))
            self.assertEqual(len(str(baseline["content_sha256"])), 64)
            self.assertNotIn(str(script), json.dumps(baseline, ensure_ascii=False))

            script.write_text("print('changed before dispatch')\n", encoding="utf-8")
            drifted = _observe_repair_script_identity(script)
            self.assertFalse(_same_repair_script_identity(baseline, drifted))
            self.assertNotEqual(baseline["content_sha256"], drifted["content_sha256"])


class LocalServiceRecoveryProductTests(unittest.TestCase):
    def test_final_product_runtime_installs_local_service_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertTrue(getattr(resident, _INSTALL_MARKER, False))
            finally:
                resident.store.close()

    def test_missing_service_context_fails_before_any_command_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "repair_service.py").write_text("print('must not run')\n", encoding="utf-8")
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            try:
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="e2e21-missing-context")
                ledger.attach_workspace("e2e21-missing-context", workspace)
                _, run = ledger.submit("e2e21-missing-context", TASK)
                self.assertFalse(run.success)
                self.assertIn("service_context_missing", run.reason)
                command_actions = [
                    item
                    for item in resident.body.recent_actions(128)
                    if item.event_id == run.event.event_id and item.kind == "command"
                ]
                self.assertEqual(command_actions, [])
            finally:
                resident.store.close()

    def test_local_service_repair_history_redacts_command_workdir_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = KernelStore(root / "kernel.db")
            body = CurrentAppTextAwareBody(store=store)
            secret_workspace = root / "private-workspace"
            secret_command = f"C:/private/python.exe {secret_workspace}/repair_service.py"
            action = BodyAction(
                action_id="repair-history",
                kind="command",
                args={
                    "command": secret_command,
                    "workdir": str(secret_workspace),
                    "local_service_repair": True,
                },
                event_id="repair-history",
            )
            result = BodyActionResult(
                action_id=action.action_id,
                kind="command",
                success=True,
                output="repair applied from private-workspace",
                data={
                    "command": secret_command,
                    "cwd": str(secret_workspace),
                    "output": "repair applied from private-workspace",
                    "status": "completed",
                    "exit_code": 0,
                },
                event_id=action.event_id,
            )
            try:
                body._record(action, result)
                with closing(sqlite3.connect(root / "kernel.db")) as conn:
                    row = conn.execute(
                        "SELECT action_json,result_json FROM native_body_actions WHERE action_id=?",
                        (action.action_id,),
                    ).fetchone()
                self.assertIsNotNone(row)
                durable = " ".join(str(value) for value in row or ())
                self.assertNotIn("private-workspace", durable)
                self.assertNotIn("repair_service.py", durable)
                self.assertNotIn("repair applied", durable)
                self.assertIn("command_redacted", durable)
                self.assertIn("workdir_redacted", durable)
                self.assertIn("output_redacted", durable)
                parsed_action = json.loads(row[0])
                parsed_result = json.loads(row[1])
                self.assertTrue(parsed_action["args"]["command_redacted"])
                self.assertTrue(parsed_result["data"]["output_redacted"])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
