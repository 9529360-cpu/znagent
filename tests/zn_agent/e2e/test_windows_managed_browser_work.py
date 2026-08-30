from __future__ import annotations

import contextlib
import http.server
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "runtime" / "python"


class _FixtureHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path == "/done":
            body = b"""<!doctype html>
<html>
<head><title>ZN Work Button Done</title></head>
<body><h1>Done</h1></body>
</html>"""
        else:
            body = b"""<!doctype html>
<html>
<head><title>ZN Work Browser Fixture</title></head>
<body>
  <label><input id="consent" type="checkbox"> Consent</label>
  <label><input type="checkbox"> Email updates</label>
  <button type="button" onclick="location.href='/done'">Continue</button>
</body>
</html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args) -> None:
        return


class _ThreadingTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


class ManagedBrowserWorkWindowsE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if os.name != "nt":
            raise unittest.SkipTest("Windows managed-browser Work E2E requires Windows")
        cls.server = _ThreadingTCPServer(("127.0.0.1", 0), _FixtureHandler)
        cls.server_thread = threading.Thread(
            target=cls.server.serve_forever,
            daemon=True,
        )
        cls.server_thread.start()
        cls.port = int(cls.server.server_address[1])
        cls.url = f"http://127.0.0.1:{cls.port}/"
        cls.done_url = f"http://127.0.0.1:{cls.port}/done"

    @classmethod
    def tearDownClass(cls) -> None:
        with contextlib.suppress(Exception):
            cls.server.shutdown()
        with contextlib.suppress(Exception):
            cls.server.server_close()
        with contextlib.suppress(Exception):
            cls.server_thread.join(timeout=2)

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.store_path = Path(self.tempdir.name) / "kernel.db"
        self.port_file = Path(self.tempdir.name) / "resident.port"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PYTHON_ROOT)
        env["ZN_RESIDENT_PORT_FILE"] = str(self.port_file)
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "zn_agent.core.resident_server",
                "--store",
                str(self.store_path),
                "--host",
                "127.0.0.1",
                "--port",
                "0",
            ],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.addCleanup(self._stop_resident)
        self.resident_port = self._wait_for_resident()
        self.base_url = f"http://127.0.0.1:{self.resident_port}"

    def _stop_resident(self) -> None:
        if getattr(self, "process", None) is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.process.returncode not in {0, -15, 1}:
            stdout, stderr = self.process.communicate(timeout=1)
            raise AssertionError(
                f"resident exited {self.process.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )

    def _wait_for_resident(self) -> int:
        deadline = time.time() + 15
        while time.time() < deadline:
            if self.process.poll() is not None:
                stdout, stderr = self.process.communicate(timeout=1)
                raise AssertionError(
                    f"resident exited before startup: {self.process.returncode}\n"
                    f"stdout:\n{stdout}\nstderr:\n{stderr}"
                )
            try:
                text = self.port_file.read_text(encoding="utf-8").strip()
                if text:
                    port = int(text)
                    with urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                        if response.status == 200:
                            return port
            except (FileNotFoundError, OSError, ValueError, HTTPError):
                pass
            time.sleep(0.1)
        raise AssertionError("resident did not publish a healthy port")

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict | None = None,
    ) -> dict:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    def _run_work(self, *, thread_id: str, task: str, payload: dict) -> dict:
        started = self._request(
            f"/work/threads/{thread_id}/start",
            method="POST",
            payload={"task": task, "payload": payload},
        )
        event_id = started["event"]["event_id"]
        deadline = time.time() + 20
        while time.time() < deadline:
            progress = self._request(f"/work/threads/{thread_id}/events/{event_id}")
            if progress["progress"]["terminal"]:
                return progress
            time.sleep(0.1)
        raise AssertionError(f"Work event did not complete: {event_id}")

    def test_structured_work_navigates_real_chromium_and_verifies_before_completion(self):
        final = self._run_work(
            thread_id="managed-browser-nav-work-e2e",
            task="open a local browser page using structured exact authority",
            payload={
                "required_capabilities": ["browser"],
                "body_action": {
                    "kind": "browser_navigate",
                    "args": {
                        "url": self.url,
                        "expected_url": self.url,
                        "allow_private_network": True,
                    },
                },
                "expected_outcome": {"kind": "browser_url_equals", "url": self.url},
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
            if item["kind"] == "browser_navigate"
        ]
        self.assertEqual(len(browser_actions), 1)
        self.assertTrue(browser_actions[0]["success"])
        messages = final["thread"]["messages"]
        self.assertEqual([item["role"] for item in messages], ["user", "zn", "activity"])
        self.assertEqual(messages[1]["text"], "ZN Work Browser Fixture")

    def test_structured_work_sets_real_chromium_checkbox_with_verified_target_state(self):
        final = self._run_work(
            thread_id="managed-browser-checkbox-work-e2e",
            task="set one explicit local checkbox through managed Chromium",
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
            item
            for item in progress["body_actions"]
            if item["kind"] == "browser_set_checkbox"
        ]
        self.assertEqual(len(browser_actions), 1)
        self.assertTrue(browser_actions[0]["success"])
        messages = final["thread"]["messages"]
        self.assertEqual([item["role"] for item in messages], ["user", "zn", "activity"])
        self.assertEqual(messages[1]["text"], "checkbox #consent is checked")

    def test_structured_work_sets_idless_checkbox_by_exact_accessible_name(self):
        final = self._run_work(
            thread_id="managed-browser-named-checkbox-work-e2e",
            task="set one exact named local checkbox through managed Chromium",
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
            thread_id="managed-browser-named-button-work-e2e",
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
