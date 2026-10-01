from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.models import ModelRoute, WorkerResult
from zn_agent.core.provider_bridge import build_resident_runtime


class _CaptureFactory:
    """A deterministic provider boundary, not a product response implementation."""

    def __init__(self):
        self.contexts = []

    def create(self, route):
        return self

    def run(self, goal, kernel_context):
        self.contexts.append(kernel_context)
        return WorkerResult(
            success=True,
            response="Tidal generation converts the energy of moving seawater into electricity.",
            verification_passed=True,
            metrics={"model_invoked": True},
        )


class WorkConversationResidentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "kernel.db"
        self.resident = build_resident_runtime(config={"model": {}}, store_path=self.path)
        self.server = ResidentRpcServer(self.resident)
        self.addCleanup(lambda: self.resident.store.close())

    def start(self, thread, task, *, payload=None):
        result = self.server.handle({
            "id": "start", "method": "work_start",
            "params": {"thread_id": thread, "task": task, "payload": payload or {}},
        })["result"]
        return result["progress"]["event_id"]

    def finish(self, thread, event_id):
        for _ in range(64):
            self.resident.live_once()
            progress = self.server.handle({
                "id": "progress", "method": "work_progress",
                "params": {"thread_id": thread, "event_id": event_id},
            })["result"]["progress"]
            if progress["finalized"]:
                return self.server.work.get_snapshot(thread)[1]
        self.fail(f"Work did not finalize: {progress}")

    def seed_history(self):
        self.resident.memory.remember("Explain tidal generation", "Tidal turbines use seawater currents.")
        first = self.start("conversation", "Explain tidal generation")
        messages = self.finish("conversation", first)
        self.assertTrue(any(m.role == "zn" and "seawater currents" in m.text for m in messages))
        self.resident.memory.remember("Another conversation", "unrelated-thread-private-value")
        other = self.start("unrelated", "Another conversation")
        self.finish("unrelated", other)

    def test_rpc_follow_up_reaches_provider_with_durable_context_after_restart(self):
        self.seed_history()
        identity = self.resident.kernel.identity
        self.resident.store.close()
        self.resident = build_resident_runtime(config={"model": {}}, store_path=self.path)
        self.server = ResidentRpcServer(self.resident)
        self.assertEqual(self.resident.kernel.identity, identity)
        factory = _CaptureFactory()
        self.resident.kernel.reconfigure_resources(
            routes=[ModelRoute(
                "conversation-local", "test", "bounded-resource",
                {"general": 1.0, "reasoning": 1.0, "language_understanding": 1.0},
                metadata={"local": True},
            )],
            worker_factory=factory,
            resource_status={"available": True},
            max_attempts=1,
        )
        event_id = self.start("conversation", "Explain the principle behind that answer")
        messages = self.finish("conversation", event_id)
        self.assertTrue(factory.contexts, "The normal Product Resident must actually call cognition")
        histories = []
        for context in factory.contexts:
            if "BOUNDED CONTEXT:\n" not in context:
                continue
            data = json.loads(context.split("BOUNDED CONTEXT:\n", 1)[1])
            history = data["bounded_context"].get("work_conversation")
            if history:
                histories.append(history)
            self.assertNotIn("unrelated-thread-private-value", context)
        self.assertTrue(histories, "Persisted messages must reach the active provider request")
        text = json.dumps(histories, ensure_ascii=False)
        self.assertIn("Explain tidal generation", text)
        self.assertIn("seawater currents", text)
        self.assertTrue(all(not h["execution_authority"] and not h["completion_evidence"] for h in histories))
        self.assertTrue(any(m.role == "zn" and "moving seawater" in m.text for m in messages))
        self.resident.store.close()
        self.resident = build_resident_runtime(config={"model": {}}, store_path=self.path)
        self.server = ResidentRpcServer(self.resident)
        restored = self.server.work.get_snapshot("conversation")[1]
        self.assertEqual([m.message_id for m in restored], [m.message_id for m in messages])
        self.assertEqual([m.text for m in restored], [m.text for m in messages])

    def test_ask_mode_reaches_model_without_executing_explicit_body_effect(self):
        factory = _CaptureFactory()
        self.resident.kernel.reconfigure_resources(
            routes=[ModelRoute(
                "ask-local", "test", "bounded-resource",
                {"general": 1.0, "reasoning": 1.0, "language_understanding": 1.0},
                metadata={"local": True},
            )],
            worker_factory=factory,
            resource_status={"available": True},
            max_attempts=1,
        )
        target = Path(self.tmp.name) / "must-not-exist.txt"
        event_id = self.start(
            "ask-conversation",
            "Explain tidal generation without changing my computer",
            payload={
                "execution_mode": "ask",
                "body_action": {
                    "kind": "write_text",
                    "path": str(target),
                    "content": "this must never be written",
                },
            },
        )
        messages = self.finish("ask-conversation", event_id)

        self.assertTrue(factory.contexts, "Ask must still reach the configured cognitive resource")
        self.assertFalse(target.exists(), "Ask must not execute an explicit write Body action")
        self.assertFalse(
            any(
                action.event_id == event_id and action.kind == "write_text"
                for action in self.resident.body.recent_actions(100)
            )
        )
        self.assertTrue(
            any(
                message.role == "zn" and "moving seawater" in message.text
                for message in messages
            )
        )
        event = self.resident.store.get_event(event_id)
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.payload.get("execution_mode"), "ask")

    def test_product_builder_keeps_route_policy_and_isolated_question_boundary(self):
        self.seed_history()
        policy = {"data_classification": "local_only"}
        event_id = self.start("conversation", "Explain the principle", payload={"route_policy": policy})
        event = self.resident.store.get_event(event_id)
        impasse = SimpleNamespace(impasse_id="bounded-context-test", local_failure=None)
        request = self.resident._build_cognition_request(event, impasse, ("general",))
        self.assertEqual(request.context["route_policy"], policy)
        self.assertIn("work_conversation", request.context)
        event.payload["cognition_question"] = "What is a mutex?"
        isolated = self.resident._build_cognition_request(event, impasse, ("general",))
        self.assertEqual(isolated.question, "What is a mutex?")
        self.assertEqual(isolated.context["route_policy"], policy)
        self.assertNotIn("work_conversation", isolated.context)


if __name__ == "__main__":
    unittest.main()
