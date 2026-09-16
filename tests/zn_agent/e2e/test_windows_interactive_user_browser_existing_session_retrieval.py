from __future__ import annotations

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from zn_agent.core.cognitive_resource import CognitiveIncrement

from test_windows_interactive_user_browser_semantic_grounding import (
    _Handler,
    _SESSION_COOKIE,
    _TITLE,
    WindowsInteractiveUserBrowserSemanticGroundingE2ETests,
)


_SUBJECT = "Alice"
_TASK = "去我已经登录的系统里查 Alice 最近三笔订单，把状态告诉我。"
_RECORDS = (
    "订单 #ZN-733 | 2026-09-15 | 状态: 已发货",
    "订单 #ZN-732 | 2026-09-14 | 状态: 处理中",
    "订单 #ZN-731 | 2026-09-13 | 状态: 已完成",
)
_RESULT_TITLE = "ZN Recent Orders Result E2E"


class _MultiRecordHandler(_Handler):
    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path != "/results":
            return super().do_GET()
        if not self._has_existing_session():
            self.server.unauthorized_requests += 1  # type: ignore[attr-defined]
            self._write(401, "text/plain; charset=utf-8", b"existing browser login required")
            return
        self.server.result_requests["authorized"] += 1  # type: ignore[attr-defined]
        values = parse_qs(parsed.query, keep_blank_values=True).get("customer", [])
        value = values[0] if len(values) == 1 else ""
        self.server.result_queries["authorized"].append(value)  # type: ignore[attr-defined]
        if value != _SUBJECT:
            self._write(400, "text/plain; charset=utf-8", b"unexpected customer query")
            return
        rows = "".join(f"<p>{record}</p>" for record in _RECORDS)
        body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{_RESULT_TITLE}</title></head>
<body><main><article><h2>客户 {_SUBJECT} 最近三笔订单</h2>{rows}</article></main></body></html>""".encode(
            "utf-8"
        )
        self._write(200, "text/html; charset=utf-8", body)

    def _account_page(self, mode: str) -> bytes:
        del mode
        return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{_TITLE}</title></head>
<body><main>
<h1>Customer order portal</h1>
<form id="orders" action="/results" method="get">
<label>Customer <input aria-label="客户" name="customer" type="text" autocomplete="off"></label>
<button type="submit" aria-label="查询订单">查询订单</button>
</form>
</main></body></html>""".encode("utf-8")


class _MultiRecordCognition:
    def __init__(self):
        self.calls = 0
        self.questions: list[str] = []

    @staticmethod
    def _observed_name(question: str, name: str) -> bool:
        return f'"name": "{name}"' in question

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        del context
        self.calls += 1
        self.questions.append(question)
        if "Interpret only the user's desired outcome in the current browser" in question:
            value = {
                "kind": "user_browser_semantic_lookup",
                "subject_value": _SUBJECT,
                "subject_semantics": "客户姓名",
                "operation": "查找这个客户最近三笔订单",
                "desired_result": "确认最近三笔订单的状态",
            }
        elif "Select the one safe textbox" in question:
            value = (
                {"status": "selected", "name": "客户"}
                if self._observed_name(question, "客户")
                else {"status": "ambiguous"}
            )
        elif "Select the button" in question:
            value = (
                {"status": "selected", "name": "查询订单"}
                if self._observed_name(question, "查询订单")
                else {"status": "ambiguous"}
            )
        elif "plural record set" in question:
            value = {"status": "verified", "records": list(_RECORDS)}
        else:
            value = {"status": "not_verified"}
        return CognitiveIncrement(
            text=json.dumps(value, ensure_ascii=False),
            provider="e2e-cognition",
            model="bounded-language-fixture",
        )


class WindowsInteractiveUserBrowserExistingSessionRetrievalE2ETests(unittest.TestCase):
    _require_input_desktop = staticmethod(
        WindowsInteractiveUserBrowserSemanticGroundingE2ETests._require_input_desktop
    )
    _enable_cognition = staticmethod(
        WindowsInteractiveUserBrowserSemanticGroundingE2ETests._enable_cognition
    )
    _make_runtime = WindowsInteractiveUserBrowserSemanticGroundingE2ETests._make_runtime
    _close_runtime = WindowsInteractiveUserBrowserSemanticGroundingE2ETests._close_runtime
    _run_to_terminal = WindowsInteractiveUserBrowserSemanticGroundingE2ETests._run_to_terminal

    def _start_server(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MultiRecordHandler)
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

    def _start_multi_work(self, env) -> str:
        rpc = env["rpc"]
        thread_id = "e2e04-existing-session-retrieval"
        created = rpc.handle(
            {
                "id": "create",
                "method": "work_create",
                "params": {"thread_id": thread_id, "title": "Existing-session order retrieval"},
            }
        )
        self.assertTrue(created["ok"])
        started = rpc.handle(
            {
                "id": "start",
                "method": "work_start",
                "params": {
                    "thread_id": thread_id,
                    "task": _TASK,
                    "kind": "desktop_user_event",
                    "priority": 0,
                    "payload": {"model_policy": "on_demand"},
                },
            }
        )
        self.assertTrue(started["ok"])
        return str(started["result"]["progress"]["event_id"])

    def test_e2e04_reads_three_fresh_records_from_same_existing_authorized_session(self) -> None:
        self._require_input_desktop()
        env = self._make_runtime("normal")
        try:
            cognition = _MultiRecordCognition()
            env["cognition"] = cognition
            self._enable_cognition(env["resident"], cognition)
            resident = env["resident"]
            authorization_before = resident.user_browser_extension.authorized_tab()
            self.assertIsNotNone(authorization_before)
            self.assertGreaterEqual(env["server"].account_requests.get("normal", 0), 1)  # type: ignore[attr-defined]
            login_before = int(env["server"].login_requests)  # type: ignore[attr-defined]

            event_id = self._start_multi_work(env)
            result, trace = self._run_to_terminal(env, event_id, timeout=35.0)
            self.assertIsNotNone(result, json.dumps(trace[-20:], ensure_ascii=False, default=str))
            self.assertTrue(result.success, result.reason)
            self.assertEqual(
                result.response,
                f"{_SUBJECT}:\n" + "\n".join(f"- {record}" for record in _RECORDS),
            )
            self.assertEqual(env["server"].result_requests["authorized"], 1)  # type: ignore[attr-defined]
            self.assertEqual(env["server"].result_queries["authorized"], [_SUBJECT])  # type: ignore[attr-defined]
            self.assertEqual(env["server"].result_requests["decoy"], 0)  # type: ignore[attr-defined]
            self.assertEqual(env["server"].unauthorized_requests, 0)  # type: ignore[attr-defined]
            self.assertEqual(int(env["server"].login_requests), login_before)  # type: ignore[attr-defined]

            authorization_after = resident.user_browser_extension.authorized_tab()
            self.assertIsNotNone(authorization_after)
            self.assertEqual(authorization_after.tab_id, authorization_before.tab_id)
            self.assertEqual(authorization_after.attached_at, authorization_before.attached_at)
            fresh_tab = resident.probe_user_browser_extension_tab()
            self.assertEqual(fresh_tab["tab_id"], authorization_before.tab_id)
            self.assertIn("/results?customer=Alice", fresh_tab["url"])
            self.assertEqual(fresh_tab["title"], _RESULT_TITLE)

            actions = [
                action for action in resident.body.recent_actions(512) if action.event_id == event_id
            ]
            self.assertEqual(sum(a.kind == "browser_type_named_text" for a in actions), 1)
            self.assertEqual(sum(a.kind == "browser_click_named_button_to_url" for a in actions), 1)
            questions = "\n".join(cognition.questions)
            self.assertTrue(any("plural record set" in question for question in cognition.questions))
            self.assertNotIn("backend:", questions)
            self.assertNotIn("tab_id", questions)
            self.assertNotIn(_SESSION_COOKIE, questions)

            print(
                "ZN_E2E04_EXISTING_SESSION_RETRIEVAL="
                + json.dumps(
                    {
                        "normal_language_task": _TASK,
                        "ordinary_language": True,
                        "existing_authenticated_session": True,
                        "same_authorized_tab_generation": True,
                        "fresh_exact_tab_verified": True,
                        "requested_record_count": 3,
                        "fresh_result_container": True,
                        "verbatim_records": list(_RECORDS),
                        "browser_mutations": 2,
                        "business_mutations": 0,
                        "session_cookie_copied_to_cognition": False,
                        "session_login_replayed": False,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        finally:
            self._close_runtime(env)


if __name__ == "__main__":
    unittest.main()
