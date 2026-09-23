from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from zn_agent.core.resident_server import ResidentSocketService


class ResidentStartupAdmissionTests(unittest.TestCase):
    """Startup may admit Work only after the reconnect endpoint is publishable."""

    def service(self):
        service = ResidentSocketService.__new__(ResidentSocketService)
        calls = Mock()
        service.rpc = SimpleNamespace(
            service=SimpleNamespace(acquire=calls.acquire, release=calls.release),
            resident=SimpleNamespace(live_once=calls.live_once, store=SimpleNamespace(close=calls.close)),
            _start_life_loop=calls.life_start,
            _stop_life_loop=calls.life_stop,
        )
        service.host, service.port = "127.0.0.1", 0
        service._session_secret = "synthetic-startup-test"
        service._server = None
        service.channels = SimpleNamespace(start=calls.channels_start, stop=calls.channels_stop)
        service._start_visual_loop = calls.visual_start
        service._stop_visual_loop = calls.visual_stop
        service._write_endpoint = calls.publish
        service._remove_owned_endpoint = calls.retire
        service._close_managed_browser = calls.browser_close
        server = Mock(server_address=("127.0.0.1", 12345))
        server.serve_forever = calls.serve
        return service, calls, server

    def test_only_existing_life_loop_drives_work_after_endpoint_publication(self):
        service, calls, server = self.service()
        with patch("zn_agent.core.resident_server._ResidentTcpServer") as builder:
            builder.return_value.__enter__.return_value = server
            self.assertEqual(service.serve_forever(), 0)
        calls.live_once.assert_not_called()
        names = [call[0] for call in calls.mock_calls]
        self.assertLess(names.index("acquire"), names.index("publish"))
        for start in ("life_start", "visual_start", "channels_start"):
            self.assertLess(names.index("publish"), names.index(start))
            self.assertLess(names.index(start), names.index("serve"))
        calls.publish.assert_called_once_with("127.0.0.1", 12345)
        calls.release.assert_called_once_with()
        calls.close.assert_called_once_with()

    def test_bind_failure_starts_no_work_or_background_organs(self):
        service, calls, _ = self.service()
        with patch("zn_agent.core.resident_server._ResidentTcpServer", side_effect=OSError("port unavailable")):
            with self.assertRaisesRegex(OSError, "port unavailable"):
                service.serve_forever()
        for callback in (calls.live_once, calls.life_start, calls.visual_start, calls.channels_start, calls.publish):
            callback.assert_not_called()
        calls.release.assert_called_once_with()
        calls.close.assert_called_once_with()

    def test_endpoint_failure_starts_no_work_and_closes_bound_server(self):
        service, calls, server = self.service()
        calls.publish.side_effect = OSError("endpoint unavailable")
        with patch("zn_agent.core.resident_server._ResidentTcpServer") as builder:
            builder.return_value.__enter__.return_value = server
            with self.assertRaisesRegex(OSError, "endpoint unavailable"):
                service.serve_forever()
            builder.return_value.__exit__.assert_called_once()
        for callback in (calls.live_once, calls.life_start, calls.visual_start, calls.channels_start, calls.serve):
            callback.assert_not_called()
        calls.retire.assert_called_once_with()
        calls.release.assert_called_once_with()
        calls.close.assert_called_once_with()

    def test_lease_refusal_never_binds_or_dispatches_work(self):
        service, calls, _ = self.service()
        calls.acquire.side_effect = RuntimeError("another resident")
        with patch("zn_agent.core.resident_server._ResidentTcpServer") as builder:
            with self.assertRaisesRegex(RuntimeError, "another resident"):
                service.serve_forever()
            builder.assert_not_called()
        calls.live_once.assert_not_called()
        calls.life_start.assert_not_called()
        calls.publish.assert_not_called()


class ResidentRestartCognitionReadinessTests(unittest.TestCase):
    @staticmethod
    def request(endpoint, method, params=None, *, authenticate=True):
        with socket.create_connection((endpoint["host"], endpoint["port"]), timeout=3.0) as client:
            client.settimeout(3.0)
            with client.makefile("rwb") as stream:
                def exchange(request):
                    stream.write((json.dumps(request) + "\n").encode("utf-8"))
                    stream.flush()
                    raw = stream.readline()
                    if not raw:
                        raise AssertionError("Resident closed before replying")
                    return json.loads(raw)
                if authenticate:
                    response = exchange({"id": "auth", "method": "authenticate", "params": {
                        "secret": endpoint["authentication"]["secret"],
                    }})
                    if response.get("ok") is not True:
                        raise AssertionError("Resident authentication failed")
                return exchange({"id": "request", "method": method, "params": params or {}})

    def test_restart_reconnects_while_saved_cognition_waits_then_finishes_same_work(self):
        # This test uses the actual product Resident, SQLite, Work facade, Kernel,
        # life thread and TCP/auth transport. Only the provider is a controlled
        # boundary; it blocks until released and never calls a paid model.
        from zn_agent.core.daemon import ResidentRpcServer
        from zn_agent.core.models import ModelRoute, WorkerResult
        from zn_agent.core.provider_bridge import build_resident_runtime

        entered, release = threading.Event(), threading.Event()
        requests = []

        class Provider:
            def create(self, route):
                return self

            def run(self, goal, kernel_context):
                requests.append(goal.goal_id)
                entered.set()
                if not release.wait(30.0):
                    raise TimeoutError("test provider was not released")
                return WorkerResult(
                    success=True,
                    response="Tidal generation depends on moving seawater.",
                    metrics={"model_invoked": True},
                )

        def configure(resident):
            resident.kernel.reconfigure_resources(
                routes=[ModelRoute(
                    "startup-local", "test", "bounded-test-resource",
                    {"general": 1.0, "reasoning": 1.0, "language_understanding": 1.0},
                    metadata={"local": True},
                )],
                worker_factory=Provider(), resource_status={"available": True}, max_attempts=1,
            )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "kernel.db"
            resident = build_resident_runtime(config={"model": {}}, store_path=path)
            configure(resident)
            rpc = ResidentRpcServer(resident, life_interval=0.25)
            started = rpc.handle({"id": "start", "method": "work_start", "params": {
                "thread_id": "startup-work", "task": "Explain the principle of tidal generation",
            }})["result"]
            event_id = started["progress"]["event_id"]
            identity = resident.kernel.identity
            try:
                for _ in range(64):
                    state = resident.store.get_working_state()
                    if state.current_event_id == event_id and state.stage == "external_cognition":
                        break
                    resident.live_once()
                else:
                    self.fail("Work did not reach a durable pre-dispatch cognition checkpoint")
                self.assertEqual(requests, [])
            finally:
                resident.store.close()

            resident = build_resident_runtime(config={"model": {}}, store_path=path)
            configure(resident)
            rpc = ResidentRpcServer(resident, life_interval=0.25)
            service = ResidentSocketService(rpc, endpoint_path=Path(tmp) / "endpoint.json")
            # No real screen sampling is needed for the reconnect/cognition contract.
            service._start_visual_loop = Mock()
            errors = []

            def serve():
                try:
                    service.serve_forever()
                except BaseException as exc:
                    errors.append(exc)

            thread = threading.Thread(target=serve, name="test-startup-service", daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 10.0
                endpoint = None
                while time.monotonic() < deadline and thread.is_alive():
                    try:
                        endpoint = json.loads(service.endpoint_path.read_text(encoding="utf-8"))
                        break
                    except (OSError, ValueError):
                        time.sleep(0.02)
                self.assertIsNotNone(endpoint, "saved cognition stalled endpoint publication")
                self.assertTrue(entered.wait(10.0), "existing life loop did not resume cognition")
                self.assertFalse(release.is_set())
                denied = self.request(endpoint, "work_start", {
                    "thread_id": "untrusted", "task": "must not be accepted",
                }, authenticate=False)
                self.assertFalse(denied["ok"])
                self.assertEqual(denied["error"], "authentication required")
                # Each request is a separate connect/auth/disconnect cycle while
                # the same model call remains blocked. Neither resubmits Work.
                self.assertTrue(self.request(endpoint, "ping")["result"]["alive"])
                snapshot = self.request(endpoint, "work_get", {"thread_id": "startup-work"})["result"]
                self.assertEqual(snapshot["active_run"]["event_id"], event_id)
                progress = self.request(endpoint, "work_progress", {
                    "thread_id": "startup-work", "event_id": event_id,
                })["result"]["progress"]
                self.assertFalse(progress["finalized"])
                self.assertEqual(len(requests), 1)
                release.set()
                deadline = time.monotonic() + 20.0
                while time.monotonic() < deadline:
                    result = self.request(endpoint, "work_progress", {
                        "thread_id": "startup-work", "event_id": event_id,
                    })["result"]
                    if result["progress"]["finalized"]:
                        break
                    time.sleep(0.05)
                else:
                    self.fail("resumed Work did not finalize after provider release")
                messages = result["thread"]["messages"]
                self.assertEqual(sum(m["role"] == "user" for m in messages), 1)
                self.assertTrue(any(m["role"] == "zn" and "moving seawater" in m["text"] for m in messages))
                self.assertEqual(len(requests), 1)
                self.assertEqual(resident.kernel.identity, identity)
                self.assertTrue(self.request(endpoint, "shutdown")["ok"])
            finally:
                release.set()
                # Also unwinds the original implementation after the readiness
                # assertion fails, so the regression itself leaves no live owner.
                deadline = time.monotonic() + 10.0
                while thread.is_alive() and time.monotonic() < deadline:
                    try:
                        endpoint = json.loads(service.endpoint_path.read_text(encoding="utf-8"))
                        self.request(endpoint, "shutdown")
                        break
                    except (OSError, ValueError, AssertionError):
                        time.sleep(0.02)
                thread.join(timeout=10.0)
                self.assertFalse(thread.is_alive(), "test Resident failed to stop")
                self.assertEqual(errors, [])
                resident.store.close()
            self.assertFalse(service.endpoint_path.exists())
            restored = build_resident_runtime(config={"model": {}}, store_path=path)
            try:
                self.assertEqual(restored.kernel.identity, identity)
                restored_messages = ResidentRpcServer(restored).work.get_snapshot("startup-work")[1]
                self.assertEqual([m.message_id for m in restored_messages], [m["id"] for m in messages])
                self.assertEqual([m.text for m in restored_messages], [m["text"] for m in messages])
                self.assertEqual(len(requests), 1)
            finally:
                restored.store.close()


if __name__ == "__main__":
    unittest.main()
