from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from test_windows_interactive_user_browser_semantic_grounding import (
    _Handler,
    WindowsInteractiveUserBrowserSemanticGroundingE2ETests,
)


_RECOVERY_CODE = "ZN-RECOVERY-4Q7M-9K2P"


class _RecoveryCodeHandler(_Handler):
    def _account_page(self, mode: str) -> bytes:
        if mode != "recovery":
            return super()._account_page(mode)
        body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>ZN Recovery Code E2E</title></head>
<body><h1>需要账户恢复验证</h1>
<form action="/mfa-complete" method="get">
<label>Recovery code<input aria-label="Recovery code" id="account_recovery_code" name="backup_code" type="text" autocomplete="off" value="{_RECOVERY_CODE}"></label>
<button type="submit" aria-label="继续">继续</button>
</form></body></html>"""
        return body.encode("utf-8")


class WindowsInteractiveUserBrowserRecoveryCodeE2ETests(unittest.TestCase):
    _require_input_desktop = staticmethod(
        WindowsInteractiveUserBrowserSemanticGroundingE2ETests._require_input_desktop
    )
    _enable_cognition = staticmethod(
        WindowsInteractiveUserBrowserSemanticGroundingE2ETests._enable_cognition
    )
    _make_runtime = WindowsInteractiveUserBrowserSemanticGroundingE2ETests._make_runtime
    _close_runtime = WindowsInteractiveUserBrowserSemanticGroundingE2ETests._close_runtime
    _start_work = WindowsInteractiveUserBrowserSemanticGroundingE2ETests._start_work

    def _start_server(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _RecoveryCodeHandler)
        server.login_requests = 0  # type: ignore[attr-defined]
        server.account_requests = {}  # type: ignore[attr-defined]
        server.result_requests = {"authorized": 0, "decoy": 0}  # type: ignore[attr-defined]
        server.result_queries = {"authorized": [], "decoy": []}  # type: ignore[attr-defined]
        server.unauthorized_requests = 0  # type: ignore[attr-defined]
        server.enable_drift = False  # type: ignore[attr-defined]
        server.drift_applied = 0  # type: ignore[attr-defined]
        server.mfa_completions = 0  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def test_prefilled_recovery_code_is_redacted_before_resident_or_model_observation(self) -> None:
        self._require_input_desktop()
        env = self._make_runtime("recovery")
        try:
            event_id = self._start_work(env, "recovery-code")
            resident = env["resident"]
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                resident.live_once()
                state = resident.store.get_working_state()
                if state.blocked_by == "user_presence_required":
                    break
                time.sleep(0.03)

            state = resident.store.get_working_state()
            self.assertEqual(state.current_event_id, event_id)
            self.assertEqual(state.stage, "native_investigation")
            self.assertEqual(state.blocked_by, "user_presence_required")
            blocker = state.data[resident._USER_PRESENCE_BLOCKER_STATE_KEY]
            self.assertEqual(blocker["kind"], "one_time_code")

            actions = [
                action
                for action in resident.body.recent_actions(512)
                if action.event_id == event_id
            ]
            self.assertEqual(actions, [])
            self.assertEqual(env["cognition"].calls, 1)

            sense = resident._extension_user_browser.observe_semantic_candidates()
            encoded_sense = json.dumps(sense, ensure_ascii=False, sort_keys=True)
            self.assertNotIn(_RECOVERY_CODE, encoded_sense)
            candidates = [
                item
                for item in sense["candidates"]
                if item.get("name") == "Recovery code"
            ]
            self.assertEqual(len(candidates), 1)
            recovery = candidates[0]
            self.assertTrue(recovery["sensitive"])
            self.assertEqual(recovery["sensitive_kind"], "one_time_code")
            self.assertEqual(recovery["text_length"], 0)
            self.assertEqual(
                recovery["text_sha256"],
                hashlib.sha256(b"").hexdigest(),
            )
            self.assertEqual(recovery["form_method"], "")
            self.assertEqual(recovery["form_action"], "")
            self.assertEqual(recovery["form_signature"], "")
            self.assertEqual(recovery["query_parameter"], "")

            progress = env["rpc"].handle(
                {
                    "id": "progress-recovery-code",
                    "method": "work_progress",
                    "params": {
                        "thread_id": "semantic-browser-recovery-code",
                        "event_id": event_id,
                    },
                }
            )["result"]["progress"]
            self.assertEqual(progress["stage"], "waiting_for_user")
            self.assertEqual(progress["blocked_by"], "user_presence_required")
            self.assertFalse(progress["terminal"])

            secret_surfaces = [
                "\n".join(env["cognition"].questions),
                json.dumps(state.data, ensure_ascii=False, default=str),
                json.dumps(progress, ensure_ascii=False, default=str),
                repr(actions),
            ]
            for surface in secret_surfaces:
                self.assertNotIn(_RECOVERY_CODE, surface)

            db_path = Path(env["runtime_tmp"].name) / "kernel.db"
            with sqlite3.connect(db_path) as conn:
                work_messages = conn.execute(
                    "SELECT text, detail_json FROM work_messages WHERE thread_id=? ORDER BY created_at",
                    ("semantic-browser-recovery-code",),
                ).fetchall()
            self.assertNotIn(
                _RECOVERY_CODE,
                json.dumps(work_messages, ensure_ascii=False, default=str),
            )
            self.assertNotIn(_RECOVERY_CODE.encode("utf-8"), db_path.read_bytes())
        finally:
            self._close_runtime(env)


if __name__ == "__main__":
    unittest.main(verbosity=2)
