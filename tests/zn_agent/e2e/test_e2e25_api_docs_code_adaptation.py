from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from zn_agent.core.config import load_zn_config
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import (
    build_resident_runtime,
    build_zn_cognitive_resource_plan,
)

from test_windows_interactive_user_browser_bridge import (
    WindowsInteractiveUserBrowserBridgeProviderE2ETests,
)
from test_windows_interactive_user_browser_extension import (
    _ExtensionBrowserFixture,
    _press_extension_action_shortcut,
)


_HOST = "zn-extension-e2e.test"
_USER_COOKIE = "zn_e2e25_user_session=private-user-browser-only"
_GOAL = "按这个网站的新 API 文档把项目适配一下，然后跑起来确认能用。"
_MAX_PULSES = 700


def _bundled_chromium_executable() -> Path:
    """Use Playwright's extension-capable Chromium, not branded Chrome/Edge.

    Current stable Chrome and Edge no longer accept the side-load flags used by
    this real extension fixture. The bundled Chromium keeps the same real
    browser-window + extension + explicit-current-tab authorization path while
    avoiding a branded-browser mechanism that is no longer supported.
    """

    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
    if not executable.is_file():
        raise RuntimeError(
            "Playwright Chromium is not installed; guarded E2E-25 requires "
            "`python -m playwright install chromium`"
        )
    return executable


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        cookie = str(self.headers.get("Cookie") or "")
        self.server.requests.append((parsed.path, cookie, time.time()))  # type: ignore[attr-defined]
        if parsed.path == "/seed":
            self.send_response(302)
            self.send_header("Set-Cookie", f"{_USER_COOKIE}; Path=/; HttpOnly; SameSite=Strict")
            self.send_header("Location", "/docs")
            self.end_headers()
            return
        if parsed.path == "/docs":
            body = b"""<!doctype html><html><head><title>ZN E2E25 API Docs</title></head><body>
<h1>Items API version 2</h1>
<p>Current contract: GET /v2/items</p>
<pre>{\"items\":[{\"id\":\"alpha\",\"status\":\"ready\"}]}</pre>
<p>Deprecated: GET /v1/items is removed and returns HTTP 410.</p>
</body></html>"""
            self._write(200, body, "text/html; charset=utf-8")
            return
        if parsed.path == "/v1/items":
            self._write(410, b'{"error":"v1 removed"}', "application/json")
            return
        if parsed.path == "/v2/items":
            self._write(
                200,
                b'{"items":[{"id":"alpha","status":"ready"}]}',
                "application/json",
            )
            return
        self._write(404, b"not found", "text/plain")

    def _write(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return None


class E2E25ApiDocsCodeAdaptationTests(unittest.TestCase):
    @staticmethod
    def _require_input_desktop() -> None:
        WindowsInteractiveUserBrowserBridgeProviderE2ETests._require_input_desktop()

    def test_current_api_docs_adapt_existing_workspace_and_verify_real_result(self) -> None:
        self._require_input_desktop()
        if os.environ.get("ZN_E2E25_REAL_MODEL", "").strip().lower() not in {
            "1",
            "true",
            "yes",
        }:
            self.skipTest("set ZN_E2E25_REAL_MODEL=1 only on the guarded real-model runner")
        config = load_zn_config()
        plan = build_zn_cognitive_resource_plan(config)
        real_routes = [
            route
            for route in plan.routes
            if route.provider != "none" and str(route.model).strip()
        ]
        if not plan.available or not real_routes:
            self.skipTest("E2E-25 real acceptance requires a configured cognitive resource")

        repo_root = Path(__file__).resolve().parents[3]
        extension = repo_root / "apps" / "desktop" / "browser-extension"
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.requests = []  # type: ignore[attr-defined]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        port = int(server.server_address[1])
        seed_url = f"http://{_HOST}:{port}/seed"
        api_base = f"http://127.0.0.1:{port}"

        provider = "playwright-chromium"
        executable = _bundled_chromium_executable()
        fixture = _ExtensionBrowserFixture(provider, executable, seed_url, extension)
        runtime_tmp = tempfile.TemporaryDirectory(prefix="zn-e2e25-")
        resident = None
        rpc = None
        try:
            root_dir = Path(runtime_tmp.name)
            workspace = root_dir / "existing-project"
            workspace.mkdir()
            client = workspace / "client.py"
            result_file = workspace / "result.json"
            old_source = (
                "import json\n"
                "import urllib.request\n"
                "from pathlib import Path\n\n"
                f"BASE_URL = {api_base!r}\n"
                "ENDPOINT = '/v1/items'\n\n"
                "with urllib.request.urlopen(BASE_URL + ENDPOINT, timeout=5) as response:\n"
                "    payload = json.load(response)\n"
                "item = payload['items'][0]\n"
                "result = f\"{item['id']}:{item['status']}\"\n"
                "Path('result.json').write_text(json.dumps({'result': result, 'endpoint': ENDPOINT}), encoding='utf-8')\n"
                "print(result)\n"
                "print('saved=result.json')\n"
            )
            client.write_text(old_source, encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
            subprocess.run(["git", "config", "user.email", "e2e25@zn.invalid"], cwd=workspace, check=True)
            subprocess.run(["git", "config", "user.name", "ZN E2E25"], cwd=workspace, check=True)
            subprocess.run(["git", "add", "client.py"], cwd=workspace, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "baseline old api client"], cwd=workspace, check=True)

            baseline = subprocess.run(
                [sys.executable, "client.py"],
                cwd=workspace,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            self.assertNotEqual(baseline.returncode, 0, "old client unexpectedly works against current API")
            self.assertFalse(result_file.exists())
            baseline_end = time.time()
            baseline_v1 = [r for r in server.requests if r[0] == "/v1/items" and r[2] <= baseline_end]  # type: ignore[attr-defined]
            self.assertEqual(len(baseline_v1), 1)
            self.assertFalse(any(r[0] == "/v2/items" for r in server.requests))  # type: ignore[attr-defined]

            fixture.start()
            deadline = time.monotonic() + 12.0
            docs_with_user_cookie = []
            while time.monotonic() < deadline:
                docs_with_user_cookie = [
                    r for r in server.requests  # type: ignore[attr-defined]
                    if r[0] == "/docs" and _USER_COOKIE in r[1]
                ]
                if docs_with_user_cookie:
                    break
                time.sleep(0.05)
            self.assertTrue(docs_with_user_cookie)

            resident = build_resident_runtime(config=config, store_path=root_dir / "kernel.db")
            only_route = real_routes[0]
            resident.kernel.reconfigure_resources(
                routes=[only_route],
                worker_factory=plan.worker_factory,
                max_attempts=1,
                resource_status={"available": True, "error": None},
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
            authorized = resident.user_browser_extension.authorized_tab()
            self.assertIsNotNone(authorized)
            assert authorized is not None
            tab_id = int(authorized.tab_id)
            attached_at = str(authorized.attached_at)
            self.assertTrue(attached_at)
            self.assertTrue(str(authorized.url).endswith("/docs"))

            thread_id = "e2e25-current-api-docs-code-adaptation"
            self.assertTrue(
                rpc.handle({"id": "create", "method": "work_create", "params": {"thread_id": thread_id, "title": "Adapt existing API client"}})["ok"]
            )
            self.assertTrue(
                rpc.handle({"id": "attach", "method": "work_attach_workspace", "params": {"thread_id": thread_id, "workspace_path": str(workspace), "workspace_name": "Existing project"}})["ok"]
            )
            started = rpc.handle(
                {
                    "id": "start",
                    "method": "work_start",
                    "params": {
                        "thread_id": thread_id,
                        "task": _GOAL,
                        "kind": "desktop_user_event",
                        "priority": 0,
                        "payload": {"model_policy": "on_demand", "allow_private_research": True},
                    },
                }
            )
            self.assertTrue(started["ok"])
            event_id = str(started["result"]["progress"]["event_id"])
            terminal = None
            for pulse in range(1, _MAX_PULSES + 1):
                resident.live_once()
                run_result = resident.result_for(event_id)
                if run_result is not None:
                    terminal = run_result
                    break
                if pulse % 50 == 0:
                    state = resident.store.get_working_state()
                    runs = resident.work_ledger.list_worker_runs(thread_id=thread_id, limit=64)
                    print(
                        "ZN_E2E25_HEARTBEAT="
                        + json.dumps(
                            {
                                "pulse": pulse,
                                "stage": state.stage,
                                "failure": str(state.data.get("local_failure") or "")[:1600],
                                "workers": [
                                    {
                                        "kind": run.executor_kind,
                                        "state": run.state,
                                        "verification": run.verification_status,
                                        "error": str(run.error or "")[:700],
                                    }
                                    for run in runs[-10:]
                                ],
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                time.sleep(0.02)

            self.assertIsNotNone(terminal, "E2E-25 did not reach evidence-bound Root completion")
            assert terminal is not None
            self.assertTrue(terminal.success, terminal.reason)
            self.assertGreater(terminal.model_invocations, 0, "guarded E2E-25 did not use the configured real model")
            root = resident.work_ledger.work_item_for_event(event_id)
            self.assertIsNotNone(root)
            assert root is not None
            self.assertEqual(root.status, "completed")
            self.assertIn("zn_independent_acceptance", str(root.result or ""))
            self.assertEqual(root.plan_version, resident.work_ledger.plan_version(thread_id))

            items = resident.work_ledger.list_work_items(thread_id, limit=256)
            children = [
                item for item in items
                if item.parent_work_item_id == root.work_item_id
                and item.plan_version == root.plan_version
            ]
            page_read = next(item for item in children if item.status == "completed" and any(c.startswith("page_read:") for c in item.acceptance_criteria))
            file_read = next(item for item in children if item.status == "completed" and any(c.startswith("file_read:") for c in item.acceptance_criteria))
            write = next(item for item in children if item.status == "completed" and any(c.startswith("text_equals:") for c in item.acceptance_criteria))
            verifier = next(item for item in children if item.status == "completed" and any(c.startswith("independent_python_verification:") for c in item.acceptance_criteria))
            research = json.loads(str(page_read.result))
            source = json.loads(str(file_read.result))
            self.assertIn("GET /v2/items", research["text"])
            self.assertIn("/v1/items", source["text"])
            self.assertNotIn("/v2/items", source["text"])
            self.assertEqual(source["path"], "client.py")
            self.assertFalse(source["truncated"])

            final_source = client.read_text(encoding="utf-8")
            self.assertIn("/v2/items", final_source)
            self.assertNotIn("/v1/items", final_source)
            persisted = json.loads(result_file.read_text(encoding="utf-8"))
            self.assertEqual(persisted, {"result": "alpha:ready", "endpoint": "/v2/items"})

            final_window_start = time.time()
            independent = subprocess.run(
                [sys.executable, "client.py"], cwd=workspace,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False,
            )
            self.assertEqual(independent.returncode, 0, independent.stdout)
            self.assertIn("alpha:ready", independent.stdout)
            final_requests = [r for r in server.requests if r[2] >= final_window_start]  # type: ignore[attr-defined]
            self.assertTrue(any(r[0] == "/v2/items" for r in final_requests))
            self.assertFalse(any(r[0] == "/v1/items" for r in final_requests))

            docs_requests = [r for r in server.requests if r[0] == "/docs"]  # type: ignore[attr-defined]
            self.assertTrue(any(_USER_COOKIE in r[1] for r in docs_requests))
            self.assertTrue(any(_USER_COOKIE not in r[1] for r in docs_requests), "managed docs fetch must not inherit USER Browser cookie")

            current_auth = resident.user_browser_extension.authorized_tab()
            self.assertIsNotNone(current_auth)
            assert current_auth is not None
            self.assertEqual(int(current_auth.tab_id), tab_id)
            self.assertEqual(str(current_auth.attached_at), attached_at)

            actions = [
                action for action in reversed(resident.body.recent_actions(1024))
                if action.event_id == event_id
            ]
            read_positions = [i for i, action in enumerate(actions) if action.kind == "read_text" and str(action.data.get("path") or "").endswith("client.py")]
            write_positions = [i for i, action in enumerate(actions) if action.kind == "write_text"]
            self.assertTrue(read_positions and write_positions)
            self.assertEqual(len(write_positions), 1, "representative adaptation should make one minimal source write")
            self.assertLess(min(read_positions), min(write_positions), "existing source was not Body-read before mutation")
            self.assertTrue(all(Path(str(action.data.get("path") or action.output)).resolve().is_relative_to(workspace.resolve()) for action in actions if action.kind == "write_text"))
            self.assertTrue(any(action.kind == "command" and action.success for action in actions))

            git_state = resident.body.act("git_state", event_id=event_id, path=str(workspace))
            git_diff = resident.body.act("git_diff", event_id=event_id, path=str(workspace))
            fresh_file = resident.body.act("read_text", event_id=event_id, path=str(client), max_chars=5000)
            self.assertTrue(git_state.success)
            self.assertTrue(git_diff.success)
            self.assertIn("client.py", git_diff.output)
            self.assertTrue(fresh_file.success)
            self.assertEqual(fresh_file.output, final_source)

            runs = resident.work_ledger.list_worker_runs(thread_id=thread_id, limit=128)
            current_runs = [r for r in runs if r.plan_version == root.plan_version]
            self.assertTrue(any(r.executor_kind == "research" and r.verification_status == "accepted" for r in current_runs))
            self.assertGreaterEqual(sum(r.executor_kind == "coding" and r.verification_status == "accepted" for r in current_runs), 3)
            self.assertTrue(any(r.executor_kind == "review" and r.verification_status == "accepted" for r in current_runs))
            self.assertTrue(str(verifier.result))

            goal_contexts = []
            for run in current_runs:
                goal = resident.store.get_goal(run.model_goal_id)
                if goal is None or not isinstance(goal.metadata, dict):
                    continue
                request = goal.metadata.get("cognition_request")
                if isinstance(request, dict):
                    goal_contexts.append(json.dumps(request.get("context") or {}, ensure_ascii=False))
            combined_context = "\n".join(goal_contexts)
            self.assertIn("/v1/items", combined_context)
            self.assertIn("/v2/items", combined_context)
            self.assertNotIn(_USER_COOKIE, combined_context)

            print(
                "ZN_E2E25_API_DOCS_CODE_ADAPTATION="
                + json.dumps(
                    {
                        "provider": provider,
                        "normal_language_goal": _GOAL,
                        "user_prompt_contains_url": "http" in _GOAL.casefold(),
                        "user_prompt_contains_filename": "client.py" in _GOAL,
                        "baseline_old_api_failed": baseline.returncode != 0,
                        "current_page_resolved_from_authorized_tab": research["url"].endswith("/docs"),
                        "same_authorization_generation": str(current_auth.attached_at) == attached_at,
                        "managed_received_user_cookie": False,
                        "docs_contract_observed": "GET /v2/items" in research["text"],
                        "existing_source_observed_before_write": min(read_positions) < min(write_positions),
                        "old_endpoint_observed_from_file": "/v1/items" in source["text"],
                        "new_endpoint_persisted": "/v2/items" in final_source,
                        "independent_output": independent.stdout.strip(),
                        "final_window_v2_called": any(r[0] == "/v2/items" for r in final_requests),
                        "final_window_v1_called": any(r[0] == "/v1/items" for r in final_requests),
                        "git_diff_proved_workspace_delta": "client.py" in git_diff.output,
                        "root_completed": root.status == "completed",
                        "model_invocations": terminal.model_invocations,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                flush=True,
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
            runtime_tmp.cleanup()
            fixture.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
