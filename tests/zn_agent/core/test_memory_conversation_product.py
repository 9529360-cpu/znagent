from __future__ import annotations

import json
import socket
import threading
import time
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.cognitive_resource import CognitiveResourceWorkerFactory, OpenAICompatibleCognitiveResource
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.models import ModelRoute
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.resident_server import ResidentSocketService


class _WireClient:
    """Capture the actual adapter request, without a live model or paid API."""
    def __init__(self, requests):
        self.requests = requests
        self.chat = SimpleNamespace(completions=self)

    def create(self, **request):
        self.requests.append(request)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Controlled provider response."), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3, total_tokens=10),
        )

    def close(self):
        pass


class MemoryConversationProductTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.root / "kernel.db"
        self.requests = []
        self.boot()
        self.addCleanup(lambda: self.resident.store.close())

    def boot(self):
        self.resident = build_resident_runtime(config={"model": {}}, store_path=self.path)
        self.resident.kernel.reconfigure_resources(
            routes=[ModelRoute("memory-local", "custom", "test-resource", {
                "general": 1.0, "reasoning": 1.0, "language_understanding": 1.0,
            }, metadata={"local": True, "base_url": "http://127.0.0.1:1/v1"})],
            worker_factory=CognitiveResourceWorkerFactory(lambda route: OpenAICompatibleCognitiveResource(
                route, client_builder=lambda **_: _WireClient(self.requests),
            )), resource_status={"available": True}, max_attempts=1,
        )
        self.rpc = ResidentRpcServer(self.resident)

    def call(self, method, **params):
        response = self.rpc.handle({"id": method, "method": method, "params": params})
        self.assertTrue(response["ok"])
        return response["result"]

    def start(self, task, *, thread="conversation", payload=None):
        result = self.call("work_start", thread_id=thread, task=task, payload=payload or {})
        return result["progress"]["event_id"]

    def finish(self, event_id, *, thread="conversation"):
        for _ in range(80):
            result = self.call("work_progress", thread_id=thread, event_id=event_id)
            if result["progress"]["finalized"]:
                return result["thread"]
            self.resident.live_once()
        self.fail("Product Work did not finish")

    def last_context(self):
        self.assertTrue(self.requests)
        system = next(m["content"] for m in self.requests[-1]["messages"] if m["role"] == "system")
        return json.loads(system.split("BOUNDED CONTEXT:\n", 1)[1])["bounded_context"]

    def seed(self):
        self.call("remember", key="project", value={"name": "Artemis", "decision": "offline first"}, aliases=["active project"])
        self.call("remember", key="response language", value="\u7b80\u4f53\u4e2d\u6587")
        self.call("remember", key="response style", value="Concise explanations")
        self.call("remember", key="private topic", value="foreign-private-value", aliases=["unrelated topic"])

    def test_rpc_saved_facts_preferences_and_history_reach_real_adapter_after_restart(self):
        self.seed()
        identity = self.resident.kernel.identity
        first = self.finish(self.start("Explain the active project approach"))
        memory = self.last_context()["resident_memory"]
        self.assertEqual(memory["facts"][0]["value"]["name"], "Artemis")
        self.assertEqual({p["dimension"] for p in memory["response_preferences"]}, {"language", "style"})
        foreign = self.start("Explain the unrelated topic", thread="foreign")
        self.finish(foreign, thread="foreign")
        self.resident.store.close()
        self.boot()
        second = self.finish(self.start("Describe that approach further"))
        context = self.last_context()
        self.assertEqual(context["resident_memory"]["facts"][0]["value"]["decision"], "offline first")
        self.assertEqual(context["resident_memory"]["facts"][0]["matched_in"], "previous_user_message")
        self.assertIn("Explain the active project approach", json.dumps(context["work_conversation"]))
        self.assertNotIn("foreign-private-value", json.dumps(context))
        self.assertNotIn("unrelated topic", json.dumps(context))
        self.assertEqual(self.resident.kernel.identity, identity)
        before = len(self.requests)
        # Reconnect/snapshot projection must not resubmit or replay the old Work.
        restored_face = ResidentRpcServer(self.resident)
        snapshot = restored_face.handle({"method": "work_get", "params": {"thread_id": "conversation"}})["result"]
        self.assertEqual(snapshot["messages"], second["messages"])
        self.assertIsNone(snapshot["active_run"])
        self.resident.store.close()
        self.boot()
        snapshot = self.call("work_get", thread_id="conversation")
        self.assertEqual(snapshot["messages"], second["messages"])
        self.assertEqual(len(self.requests), before)
        self.assertEqual(self.resident.kernel.identity, identity)
        self.assertEqual(sum(m["role"] == "user" for m in snapshot["messages"]), 2)
        self.assertEqual(sum(m["role"] == "zn" for m in snapshot["messages"]), 2)
        self.assertEqual(snapshot["messages"][:len(first["messages"])], first["messages"])

    def test_updated_and_forgotten_facts_are_not_reused_from_a_projection_cache(self):
        self.seed()
        self.finish(self.start("Explain the active project"))
        self.call("remember", key="project", value={"name": "Artemis", "decision": "revised decision"}, aliases=["active project"])
        self.call("remember", key="response language", value="English")
        self.resident.store.close()
        self.boot()
        self.finish(self.start("Explain the active project again"))
        memory = self.last_context()["resident_memory"]
        self.assertEqual(memory["facts"][0]["value"]["decision"], "revised decision")
        self.assertEqual(next(p["value"] for p in memory["response_preferences"] if p["dimension"] == "language"), "English")
        self.call("forget", key="project")
        self.call("forget", key="response language")
        self.resident.store.close()
        self.boot()
        self.finish(self.start("Explain the active project again"))
        memory = self.last_context()["resident_memory"]
        self.assertEqual(memory["facts"], [])
        self.assertEqual([p["dimension"] for p in memory["response_preferences"]], ["style"])

    def test_isolation_opt_out_and_current_policy_survive_product_context_binding(self):
        self.seed()
        self.finish(self.start("Explain the active project"))
        for payload in ({"allow_memory": False}, {"allow_memory": 0}, {"cognition_question": "What is a mutex?"}, {"unknown": "What is a mutex?"}):
            with self.subTest(payload=payload):
                event_id = self.start("Explain the active project again", payload={**payload, "route_policy": {"data_classification": "local_only"}})
                self.finish(event_id)
                context = self.last_context()
                self.assertNotIn("resident_memory", context)
                self.assertNotIn("work_conversation", context)
                self.assertEqual(context["route_policy"]["data_classification"], "local_only")
                self.assertNotIn("offline first", json.dumps(context))

    @staticmethod
    def socket_call(endpoint, method, **params):
        with socket.create_connection((endpoint["host"], endpoint["port"]), timeout=3) as connection:
            with connection.makefile("rwb") as stream:
                def send(payload):
                    stream.write((json.dumps(payload) + "\n").encode("utf-8"))
                    stream.flush()
                    result = json.loads(stream.readline())
                    if not result.get("ok"):
                        raise AssertionError(result)
                    return result["result"]
                send({"id": "auth", "method": "authenticate", "params": {
                    "secret": endpoint["authentication"]["secret"],
                }})
                return send({"id": method, "method": method, "params": params})

    def start_socket(self):
        self.rpc.life_interval = 0.25
        service = ResidentSocketService(self.rpc, endpoint_path=self.root / "endpoint.json")
        # Screen sampling is not part of this memory/transport contract.
        service._start_visual_loop = lambda: None
        errors = []
        def serve():
            try:
                service.serve_forever()
            except BaseException as error:
                errors.append(error)
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        def stop():
            if service._server is not None:
                service._server.shutdown()
            thread.join(10)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
        self.addCleanup(stop)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                endpoint = json.loads(service.endpoint_path.read_text(encoding="utf-8"))
                return service, thread, endpoint
            except (OSError, ValueError):
                if not thread.is_alive():
                    self.fail(f"service stopped: {errors}")
                time.sleep(0.02)
        self.fail("no endpoint")

    def socket_finish(self, endpoint, event_id):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            result = self.socket_call(endpoint, "work_progress", thread_id="conversation", event_id=event_id)
            if result["progress"]["finalized"]:
                return result["thread"]
            time.sleep(0.05)
        self.fail("socket Work did not finish")

    def test_authenticated_disconnect_reopen_and_process_reconstruction_keep_memory_and_work_aligned(self):
        self.seed()
        identity = self.resident.kernel.identity
        service, thread, endpoint = self.start_socket()
        started = self.socket_call(endpoint, "work_start", thread_id="conversation", task="Explain the active project")
        event_id = started["progress"]["event_id"]
        # Every call makes and closes an independent authenticated connection.
        snapshot = self.socket_call(endpoint, "work_get", thread_id="conversation")
        if snapshot["active_run"] is not None:
            self.assertEqual(snapshot["active_run"]["event_id"], event_id)
        completed = self.socket_finish(endpoint, event_id)
        self.assertEqual(len(self.requests), 1)
        self.socket_call(endpoint, "shutdown")
        thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertFalse(service.endpoint_path.exists())
        self.boot()
        service, thread, endpoint = self.start_socket()
        reopened = self.socket_call(endpoint, "work_get", thread_id="conversation")
        self.assertEqual(reopened["messages"], completed["messages"])
        self.assertIsNone(reopened["active_run"])
        following = self.socket_call(endpoint, "work_start", thread_id="conversation", task="Describe that approach further")
        final = self.socket_finish(endpoint, following["progress"]["event_id"])
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.last_context()["resident_memory"]["facts"][0]["value"]["decision"], "offline first")
        self.assertEqual(self.resident.kernel.identity, identity)
        self.assertEqual(sum(m["role"] == "user" for m in final["messages"]), 2)
        self.assertEqual(sum(m["role"] == "zn" for m in final["messages"]), 2)
        self.socket_call(endpoint, "shutdown")
        thread.join(10)
        self.assertFalse(thread.is_alive())

    def test_pre_dispatch_restart_preserves_context_and_finishes_exactly_one_work(self):
        self.seed()
        event_id = self.start("Explain the active project")
        for _ in range(64):
            state = self.resident.store.get_working_state()
            if state.stage == "external_cognition":
                break
            self.resident.live_once()
        else:
            self.fail("did not reach prepared cognition")
        prepared = state.data["cognition_request"]["context"]["resident_memory"]
        self.assertEqual(self.requests, [])
        self.resident.store.close()
        self.boot()
        snapshot = self.call("work_get", thread_id="conversation")
        self.assertEqual(snapshot["active_run"]["event_id"], event_id)
        completed = self.finish(event_id)
        self.assertEqual(self.last_context()["resident_memory"], prepared)
        self.assertEqual(len(self.requests), 1)
        again = self.call("work_progress", thread_id="conversation", event_id=event_id)
        self.assertEqual(again["thread"]["messages"], completed["messages"])
        self.assertEqual(len(self.requests), 1)


if __name__ == "__main__":
    unittest.main()
