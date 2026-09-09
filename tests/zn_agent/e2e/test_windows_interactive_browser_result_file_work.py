from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
import time
import unittest
from datetime import datetime, time as day_time, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime

from test_windows_interactive_user_browser_bridge import (
    _find_installed_browsers,
    WindowsInteractiveUserBrowserBridgeProviderE2ETests,
)
from test_windows_interactive_user_browser_extension import (
    _ExtensionBrowserFixture,
    _press_extension_action_shortcut,
)
from test_windows_interactive_user_browser_managed_research_return_work import (
    _HOST,
    _SESSION_COOKIE,
    _Handler,
)


class WindowsInteractiveBrowserResultFileWorkE2ETests(unittest.TestCase):
    @staticmethod
    def _require_input_desktop() -> None:
        WindowsInteractiveUserBrowserBridgeProviderE2ETests._require_input_desktop()

    @staticmethod
    def _stamp_yesterday(path: Path) -> None:
        now = datetime.now().astimezone()
        stamp = datetime.combine(
            now.date() - timedelta(days=1),
            day_time(12),
            tzinfo=now.tzinfo,
        ).timestamp()
        os.utime(path, (stamp, stamp))

    def test_desktop_work_carries_managed_research_result_into_exact_workspace_file(self) -> None:
        self._require_input_desktop()
        browsers = _find_installed_browsers()
        if not browsers:
            self.fail("interactive Windows runner has neither stable Edge nor Chrome")

        release_code = "REL-" + secrets.token_hex(5).upper()
        repo_root = Path(__file__).resolve().parents[3]
        extension = repo_root / "apps" / "desktop" / "browser-extension"
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.release_code = release_code  # type: ignore[attr-defined]
        server.research_started = False  # type: ignore[attr-defined]
        server.login_requests = 0  # type: ignore[attr-defined]
        server.account_requests = 0  # type: ignore[attr-defined]
        server.authenticated_account_requests = 0  # type: ignore[attr-defined]
        server.state_requests = 0  # type: ignore[attr-defined]
        server.results_requests = 0  # type: ignore[attr-defined]
        server.authenticated_results_requests = 0  # type: ignore[attr-defined]
        server.unauthorized_requests = 0  # type: ignore[attr-defined]
        server.result_queries = []  # type: ignore[attr-defined]
        server.managed_requests = []  # type: ignore[attr-defined]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        port = int(server.server_address[1])
        login_url = f"http://{_HOST}:{port}/login"

        provider, executable = browsers[0]
        fixture = _ExtensionBrowserFixture(provider, executable, login_url, extension)
        runtime_tmp = tempfile.TemporaryDirectory()
        resident = None
        rpc = None
        try:
            root = Path(runtime_tmp.name)
            workspace = root / "authorized-workspace"
            workspace.mkdir()
            target = workspace / "客户报价-华东.txt"
            other = workspace / "客户报价-华南.txt"
            target.write_text("项目：A\n发布代码：待确认\n", encoding="utf-8")
            other.write_text("项目：B\n发布代码：已有\n", encoding="utf-8")
            self._stamp_yesterday(target)
            self._stamp_yesterday(other)

            fixture.start()
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if int(server.authenticated_account_requests) >= 1:  # type: ignore[attr-defined]
                    break
                time.sleep(0.05)
            self.assertGreaterEqual(int(server.authenticated_account_requests), 1)  # type: ignore[attr-defined]
            self.assertEqual(int(server.unauthorized_requests), 0)  # type: ignore[attr-defined]
            login_before = int(server.login_requests)  # type: ignore[attr-defined]
            account_before = int(server.account_requests)  # type: ignore[attr-defined]

            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            rpc = ResidentRpcServer(resident=resident)
            rpc.service.acquire()

            fixture.activate()
            _press_extension_action_shortcut()
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                if resident.user_browser_authorization().get("provider") == "zn-extension-user-browser":
                    break
                time.sleep(0.05)
            self.assertEqual(
                resident.user_browser_authorization().get("provider"),
                "zn-extension-user-browser",
            )

            thread_id = "desktop-browser-result-file-e2e"
            created = rpc.handle(
                {
                    "id": "create",
                    "method": "work_create",
                    "params": {
                        "thread_id": thread_id,
                        "title": "Research release code into workspace file",
                    },
                }
            )
            self.assertTrue(created["ok"])
            attached = rpc.handle(
                {
                    "id": "attach",
                    "method": "work_attach_workspace",
                    "params": {
                        "thread_id": thread_id,
                        "workspace_path": str(workspace),
                        "workspace_name": "Authorized workspace",
                    },
                }
            )
            self.assertTrue(attached["ok"])

            task = (
                "检查当前页面链接的两个参考页，确认它们一致的 release code，然后找到这里昨天改过、"
                "名字像报价的那个 txt，把待确认改成查到的 release code，保存后再读回来确认"
            )
            started = rpc.handle(
                {
                    "id": "start",
                    "method": "work_start",
                    "params": {
                        "thread_id": thread_id,
                        "task": task,
                        "kind": "desktop_user_event",
                        "priority": 0,
                        "payload": {"model_policy": "never"},
                    },
                }
            )
            self.assertTrue(started["ok"])
            event_id = str(started["result"]["progress"]["event_id"])

            deadline = time.monotonic() + 40.0
            final = None
            while time.monotonic() < deadline:
                resident.live_once()
                polled = rpc.handle(
                    {
                        "id": "progress",
                        "method": "work_progress",
                        "params": {
                            "thread_id": thread_id,
                            "event_id": event_id,
                            "message_limit": 160,
                        },
                    }
                )
                self.assertTrue(polled["ok"])
                if polled["result"]["progress"]["terminal"]:
                    final = polled["result"]
                    break
                time.sleep(0.05)

            self.assertIsNotNone(final, "browser+file Work did not reach a terminal result")
            assert final is not None
            self.assertTrue(final["progress"]["finalized"])
            messages = final["thread"]["messages"]
            self.assertEqual(messages[0]["role"], "user")
            self.assertEqual(messages[0]["text"], task)
            self.assertNotIn("http://", task.lower())
            self.assertNotIn("tab", task.lower())
            self.assertNotIn("selector", task.lower())
            self.assertNotIn("path", task.lower())

            managed_paths = [path for path, _cookie in server.managed_requests]  # type: ignore[attr-defined]
            if not managed_paths:
                event_record = resident.store.get_event(event_id)
                outcome = resident.store.get_event_outcome(event_id)
                authorization = resident.user_browser_authorization()
                actions = [
                    {
                        "kind": item.kind,
                        "success": item.success,
                        "error": item.error,
                    }
                    for item in reversed(resident.body.recent_actions(512))
                    if item.event_id == event_id
                ]
                print(
                    "ZN_BROWSER_RESULT_FILE_FAILURE_TRACE="
                    + json.dumps(
                        {
                            "request_recognized": resident._natural_browser_result_file_request(event_record)
                            is not None,
                            "event_status": str(event_record.status),
                            "event_last_error": event_record.last_error,
                            "outcome": {
                                "success": getattr(outcome, "success", None),
                                "reason": getattr(outcome, "reason", None),
                                "model_invocations": getattr(outcome, "model_invocations", None),
                            }
                            if outcome is not None
                            else None,
                            "authorization": {
                                "authorized": bool(authorization.get("authorized")),
                                "provider": authorization.get("provider"),
                                "authorization_scope": authorization.get("authorization_scope"),
                            },
                            "server": {
                                "login_requests": int(server.login_requests),  # type: ignore[attr-defined]
                                "account_requests": int(server.account_requests),  # type: ignore[attr-defined]
                                "authenticated_account_requests": int(server.authenticated_account_requests),  # type: ignore[attr-defined]
                                "state_requests": int(server.state_requests),  # type: ignore[attr-defined]
                                "managed_request_count": len(server.managed_requests),  # type: ignore[attr-defined]
                                "results_requests": int(server.results_requests),  # type: ignore[attr-defined]
                                "unauthorized_requests": int(server.unauthorized_requests),  # type: ignore[attr-defined]
                            },
                            "actions": actions,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    )
                )
            self.assertIn("/ref-a", managed_paths)
            self.assertIn("/ref-b", managed_paths)
            self.assertIn(
                "/ref-b/details",
                managed_paths,
                "source-B landing must force a fresh investigate/replan step",
            )
            self.assertTrue(
                all(_SESSION_COOKIE not in cookie for _path, cookie in server.managed_requests)  # type: ignore[attr-defined]
            )
            self.assertEqual(int(server.login_requests), login_before)  # type: ignore[attr-defined]
            self.assertEqual(int(server.account_requests), account_before)  # type: ignore[attr-defined]
            self.assertEqual(int(server.results_requests), 0)  # type: ignore[attr-defined]
            self.assertEqual(int(server.unauthorized_requests), 0)  # type: ignore[attr-defined]

            expected = f"项目：A\n发布代码：{release_code}\n"
            self.assertEqual(target.read_text(encoding="utf-8"), expected)
            self.assertEqual(
                other.read_text(encoding="utf-8"),
                "项目：B\n发布代码：已有\n",
            )
            actions = [
                item
                for item in reversed(resident.body.recent_actions(512))
                if item.event_id == event_id
            ]
            self.assertEqual(sum(item.kind == "write_text" for item in actions), 1)
            write_at = next(i for i, item in enumerate(actions) if item.kind == "write_text")
            rereads = [item for item in actions[write_at + 1 :] if item.kind == "read_text"]
            self.assertTrue(rereads)
            self.assertEqual(rereads[-1].output, expected)
            self.assertEqual(
                resident.user_browser_authorization().get("provider"),
                "zn-extension-user-browser",
            )

            print(
                "ZN_BROWSER_RESULT_FILE_WORK_E2E_EVIDENCE="
                + json.dumps(
                    {
                        "provider": provider,
                        "normal_language_task": task,
                        "random_release_code": release_code,
                        "user_supplied_urls_targets_or_paths": False,
                        "existing_authenticated_user_session": True,
                        "managed_sources_used": managed_paths,
                        "source_b_replanned_to_detail": "/ref-b/details" in managed_paths,
                        "managed_received_user_cookie": False,
                        "exact_workspace_file_selected": target.name,
                        "other_candidate_unchanged": True,
                        "file_write_exactly_once": True,
                        "fresh_file_reread_verified": True,
                        "same_work_finalized": True,
                        "independent_verifiers": ["http-server", "filesystem-reread"],
                    },
                    sort_keys=True,
                )
            )
        finally:
            if resident is not None:
                try:
                    if resident.user_browser_extension_status().get("authorized"):
                        resident.revoke_user_browser_extension_tab()
                except Exception:
                    pass
            if rpc is not None:
                try:
                    rpc.service.release()
                except Exception:
                    pass
            if resident is not None:
                try:
                    resident.store.close()
                except Exception:
                    pass
            fixture.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2.0)
            runtime_tmp.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
