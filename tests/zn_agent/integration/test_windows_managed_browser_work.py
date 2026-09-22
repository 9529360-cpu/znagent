from __future__ import annotations

import http.server
import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from zn_agent.core.browser_rpc import BrowserResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.resident_server import ResidentSocketService


class _FixtureHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/done":
            payload = (
                "<!doctype html><html><head><title>ZN Work Button Done</title></head>"
                "<body><main>semantic button navigation completed</main></body></html>"
            ).encode("utf-8")
        else:
            payload = (
                "<!doctype html><html><head><title>ZN Work Browser Closed Loop</title></head>"
                "<body><main>structured Work reached resident-owned Chromium</main>"
                '<label><input id="consent" type="checkbox">Consent</label>'
                '<label><input type="checkbox">Email updates</label>'
                '<label>Search <input type="text" aria-label="Search"></label>'
                '<input type="password" aria-label="Password" value="">'
                '<button type="button" onclick="location.href=\'/done\'">Continue</button>'
                "</body></html>"
            ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


class ManagedBrowserWorkWindowsContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
        cls.web_thread = threading.Thread(target=cls.web.serve_forever, daemon=True)
        cls.web_thread.start()
        port = int(cls.web.server_address[1])
        cls.url = f"http://127.0.0.1:{port}/"
        cls.done_url = f"http://127.0.0.1:{port}/done"

    @classmethod
    def tearDownClass(cls):
        cls.web.shutdown()
        cls.web.server_close()
        cls.web_thread.join(timeout=5)

    @staticmethod
    def _request(endpoint: dict, request_id: str, method: str, params=None) -> dict:
        with socket.create_connection(
            (str(endpoint["host"]), int(endpoint["port"])), timeout=5.0
        ) as client:
            client.settimeout(10.0)
            stream = client.makefile("rb")
            client.sendall(
                (
                    json.dumps(
                        {
                            "id": f"{request_id}-auth",
                            "method": "authenticate",
                            "params": {"secret": endpoint["authentication"]["secret"]},
                        }
                    )
                    + "\n"
                ).encode("utf-8")
            )
            auth = json.loads(stream.readline().decode("utf-8"))
            if not auth.get("ok"):
                return auth
            client.sendall(
                (
                    json.dumps(
                        {
                            "id": request_id,
                            "method": method,
                            "params": dict(params or {}),
                        }
                    )
                    + "\n"
                ).encode("utf-8")
            )
            raw = stream.readline()
            if not raw:
                raise AssertionError("resident endpoint closed without a response")
            return json.loads(raw.decode("utf-8"))

    def _run_work(self, *, thread_id: str, task: str, payload: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}}, store_path=root / "kernel.db"
            )
            rpc = BrowserResidentRpcServer(resident=resident, life_interval=0.1)
            endpoint_path = root / "resident-endpoint.json"
            service = ResidentSocketService(rpc, endpoint_path=endpoint_path)
            resident_thread = threading.Thread(target=service.serve_forever, daemon=True)
            resident_thread.start()

            deadline = time.monotonic() + 10.0
            endpoint = None
            while time.monotonic() < deadline:
                if endpoint_path.is_file():
                    try:
                        endpoint = json.loads(endpoint_path.read_text(encoding="utf-8"))
                        break
                    except (OSError, ValueError, TypeError, json.JSONDecodeError):
                        pass
                time.sleep(0.02)
            self.assertIsNotNone(endpoint)
            assert endpoint is not None

            try:
                started = self._request(
                    endpoint,
                    "work-start",
                    "work_start",
                    {
                        "thread_id": thread_id,
                        "task": task,
                        "payload": payload,
                    },
                )
                self.assertTrue(started["ok"], started)
                progress = started["result"]["progress"]
                event_id = progress["event_id"]

                deadline = time.monotonic() + 30.0
                final = None
                while time.monotonic() < deadline:
                    polled = self._request(
                        endpoint,
                        "work-progress",
                        "work_progress",
                        {"thread_id": thread_id, "event_id": event_id},
                    )
                    self.assertTrue(polled["ok"], polled)
                    progress = polled["result"]["progress"]
                    if progress.get("terminal") and progress.get("finalized"):
                        final = polled["result"]
                        break
                    time.sleep(0.1)

                self.assertIsNotNone(final, progress)
                assert final is not None
                return final
            finally:
                shutdown = self._request(endpoint, "shutdown", "shutdown")
                self.assertTrue(shutdown["ok"], shutdown)
                resident_thread.join(timeout=10.0)
                self.assertFalse(resident_thread.is_alive())
                self.assertFalse(endpoint_path.exists())

    def test_structured_work_navigates_real_chromium_and_verifies_before_completion(self):
        final = self._run_work(
            thread_id="managed-browser-work-contract",
            task="navigate the managed browser to the structured local fixture",
            payload={
                "required_capabilities": ["browser"],
                "body_action": {
                    "kind": "browser_navigate",
                    "args": {
                        "url": self.url,
                        "allow_private_network": True,
                    },
                },
                "expected_outcome": {
                    "kind": "browser_url_equals",
                    "url": self.url,
                },
                "model_policy": "never",
            },
        )
        progress = final["progress"]
        self.assertEqual(progress["status"], "completed")
        self.assertEqual(progress["stage"], "complete")
        self.assertIsNone(progress["recovery"])
        action_kinds = [item["kind"] for item in progress["body_actions"]]
        self.assertIn("browser_navigate", action_kinds)
        self.assertIn("browser_observe", action_kinds)
        self.assertIn("browser_close", action_kinds)
        messages = final["thread"]["messages"]
        self.assertEqual([item["role"] for item in messages], ["user", "zn", "activity"])
        self.assertEqual(messages[1]["text"], "ZN Work Browser Closed Loop")

    def test_structured_work_sets_real_chromium_checkbox_with_verified_target_state(self):
        final = self._run_work(
            thread_id="managed-browser-checkbox-work-contract",
            task="set the explicit local checkbox through resident-owned Chromium",
            payload={
                "required_capabilities": ["browser"],
                "body_action": {
                    "kind": "browser_set_checkbox",
                    "args": {
                        "url": self.url,
                        "dom_id": "consent",
                        "checked": True,
                        "allow_private_network": True,
                    },
                },
                "model_policy": "never",
            },
        )
        progress = final["progress"]
        self.assertEqual(progress["status"], "completed")
        self.assertEqual(progress["stage"], "complete")
        self.assertIsNone(progress["recovery"])
        browser_actions = [
            item for item in progress["body_actions"] if item["kind"] == "browser_set_checkbox"
        ]
        self.assertEqual(len(browser_actions), 1)
        self.assertTrue(browser_actions[0]["success"])
        messages = final["thread"]["messages"]
        self.assertEqual([item["role"] for item in messages], ["user", "zn", "activity"])
        self.assertEqual(messages[1]["text"], "checkbox #consent is checked")

    def test_structured_work_sets_idless_checkbox_by_exact_accessible_name(self):
        final = self._run_work(
            thread_id="managed-browser-named-checkbox-work-contract",
            task="set the idless named checkbox through resident-owned Chromium",
            payload={
                "required_capabilities": ["browser"],
                "body_action": {
                    "kind": "browser_set_named_checkbox",
                    "args": {
                        "url": self.url,
                        "target_name": "Email updates",
                        "checked": True,
                        "allow_private_network": True,
                    },
                },
                "model_policy": "never",
            },
        )
        progress = final["progress"]
        self.assertEqual(progress["status"], "completed")
        self.assertEqual(progress["stage"], "complete")
        self.assertIsNone(progress["recovery"])
        browser_actions = [
            item
            for item in progress["body_actions"]
            if item["kind"] == "browser_set_named_checkbox"
        ]
        self.assertEqual(len(browser_actions), 1)
        self.assertTrue(browser_actions[0]["success"])
        messages = final["thread"]["messages"]
        self.assertEqual([item["role"] for item in messages], ["user", "zn", "activity"])
        self.assertEqual(messages[1]["text"], 'checkbox "Email updates" is checked')

    def test_structured_work_clicks_exact_named_button_and_verifies_destination(self):
        final = self._run_work(
            thread_id="managed-browser-named-button-work-contract",
            task="click one exact named button and verify its explicit same-origin destination",
            payload={
                "required_capabilities": ["browser"],
                "body_action": {
                    "kind": "browser_click_named_button_to_url",
                    "args": {
                        "url": self.url,
                        "target_name": "Continue",
                        "expected_url": self.done_url,
                        "allow_private_network": True,
                    },
                },
                "model_policy": "never",
            },
        )
        progress = final["progress"]
        self.assertEqual(progress["status"], "completed")
        self.assertEqual(progress["stage"], "complete")
        self.assertIsNone(progress["recovery"])
        browser_actions = [
            item
            for item in progress["body_actions"]
            if item["kind"] == "browser_click_named_button_to_url"
        ]
        self.assertEqual(len(browser_actions), 1)
        self.assertTrue(browser_actions[0]["success"])
        self.assertEqual(browser_actions[0]["summary"], self.done_url)
        messages = final["thread"]["messages"]
        self.assertEqual([item["role"] for item in messages], ["user", "zn", "activity"])
        self.assertEqual(messages[1]["text"], self.done_url)

    def test_structured_work_types_exact_named_textbox_and_keeps_plaintext_out_of_progress(self):
        typed = "ZN real Chromium text ✓"
        final = self._run_work(
            thread_id="managed-browser-named-text-work-contract",
            task="type explicit non-secret text into one exact named textbox",
            payload={
                "required_capabilities": ["browser"],
                "body_action": {
                    "kind": "browser_type_named_text",
                    "args": {
                        "url": self.url,
                        "target_name": "Search",
                        "text": typed,
                        "allow_private_network": True,
                    },
                },
                "model_policy": "never",
            },
        )
        progress = final["progress"]
        self.assertEqual(progress["status"], "completed")
        self.assertEqual(progress["stage"], "complete")
        self.assertIsNone(progress["recovery"])
        browser_actions = [
            item
            for item in progress["body_actions"]
            if item["kind"] == "browser_type_named_text"
        ]
        self.assertEqual(len(browser_actions), 1)
        self.assertTrue(browser_actions[0]["success"])
        self.assertNotIn(typed, json.dumps(progress, ensure_ascii=False))
        self.assertIn("typed", browser_actions[0]["summary"])
        messages = final["thread"]["messages"]
        self.assertEqual([item["role"] for item in messages], ["user", "zn", "activity"])
        self.assertNotIn(typed, messages[1]["text"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
