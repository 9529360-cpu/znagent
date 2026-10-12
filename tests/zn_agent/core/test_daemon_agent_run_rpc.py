from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core import KernelStore, ModelRoute, WorkerResult, ZNKernelRuntime
from zn_agent.core.action_execution import ActionExecutionRuntime
from zn_agent.core.action_fabric import ActionAvailability, ActionDescriptor, ActionFabricRegistry
from zn_agent.core.body import BodyActionResult
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.research_information_product_resident import ProductResearchInformationResidentRuntime


class _ModelWorker:
    def __init__(self, factory):
        self.factory = factory

    def run(self, goal, kernel_context):
        self.factory.calls.append(goal.task)
        raw = goal.metadata.get("cognition_request")
        context = raw.get("context") if isinstance(raw, dict) else {}
        self.factory.contexts.append(context)
        if self.factory.mode == "plain":
            response = "model answered through Resident Work"
        else:
            loop = context.get("generic_action_loop") if isinstance(context, dict) else {}
            history = loop.get("recent_verified_executions") if isinstance(loop, dict) else []
            if not history:
                response = '{"zn_action_proposal":{"action_id":"test.read","arguments":{}}}'
            else:
                execution_id = str(history[-1].get("execution_id") or "")
                response = (
                    '{"zn_action_completion":{"execution_ids":["'
                    + execution_id
                    + '"],"response":"the fresh value was verified"}}'
                )
        return WorkerResult(
            success=True,
            response=response,
            verification_passed=True,
            metrics={"model_invoked": True},
        )


class _ModelFactory:
    def __init__(self, mode="actions"):
        self.mode = mode
        self.calls = []
        self.contexts = []

    def create(self, route):
        return _ModelWorker(self)


class _Body:
    def __init__(self):
        self.calls = []

    def act(self, kind, *, event_id=None, **kwargs):
        self.calls.append((kind, event_id, dict(kwargs)))
        return BodyActionResult(
            action_id=f"body-{len(self.calls)}",
            kind=kind,
            success=True,
            data={"value": "fresh"},
            event_id=event_id,
        )


class _Device:
    def foreground_application(self):
        return None


def _make_server(tmp_dir: str, mode="actions"):
    factory = _ModelFactory(mode)
    kernel = ZNKernelRuntime(
        store=KernelStore(Path(tmp_dir) / "kernel.db"),
        routes=[ModelRoute("primary", "test", "model", {"general": 0.9})],
        worker_factory=factory,
    )
    resident = ProductResearchInformationResidentRuntime(kernel=kernel)
    fabric = ActionFabricRegistry()
    fabric.register(
        ActionDescriptor(
            action_id="test.read",
            provider="test",
            description="Read fresh test value",
            body_action_kind="test_read",
            input_schema={"type": "object", "additionalProperties": False},
            effect_class="read_only",
            verification=("fresh Body result",),
        ),
        availability_probe=lambda descriptor: ActionAvailability(
            descriptor.action_id, "available", reason="available in test"
        ),
    )
    body = _Body()
    resident.action_fabric = fabric
    resident.action_executor = ActionExecutionRuntime(fabric, body)
    resident.device_capabilities = _Device()
    server = ResidentRpcServer(
        resident=resident,
        input_stream=io.StringIO(),
        output_stream=io.StringIO(),
    )
    return server, factory, body


class DaemonAgentRunRpcTests(unittest.TestCase):
    def test_agent_run_requires_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, _, _ = _make_server(tmp)
            try:
                with self.assertRaisesRegex(ValueError, "requires task"):
                    server.handle({"id": "1", "method": "agent_run", "params": {}})
            finally:
                server.resident.store.close()

    def test_agent_run_uses_existing_model_router_and_saves_durable_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, factory, body = _make_server(tmp, mode="plain")
            try:
                response = server.handle({
                    "id": "2", "method": "agent_run",
                    "params": {"task": "answer a question without moving the computer"},
                })
                self.assertTrue(response["ok"])
                result = response["result"]
                self.assertTrue(result["completed"], result)
                self.assertEqual(result["final_text"], "model answered through Resident Work")
                self.assertEqual(result["execution_path"], "model")
                self.assertEqual(result["stopped_reason"], "resident_completed")
                self.assertEqual(result["steps"], [])
                self.assertEqual(body.calls, [])
                self.assertEqual(len(factory.calls), 1)
                self.assertIn("generic_action_loop", factory.contexts[0])
                thread_id = result["thread"]["id"]
                saved = server.work.get_snapshot(thread_id)
                self.assertEqual([m.role for m in saved[1]], ["user", "zn"])
                self.assertEqual(saved[1][-1].text, result["final_text"])
                self.assertIsNotNone(server.work.get_run(result["work_event_id"]))
            finally:
                server.resident.store.close()

    def test_agent_run_cycles_model_and_verified_action_through_same_resident(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, factory, body = _make_server(tmp)
            try:
                response = server.handle({
                    "id": "3", "method": "agent_run",
                    "params": {"task": "read the current test value"},
                })
                result = response["result"]
                self.assertTrue(result["completed"], result)
                self.assertEqual(result["final_text"], "the fresh value was verified")
                self.assertEqual(result["execution_path"], "body")
                self.assertEqual(len(factory.calls), 2)
                self.assertEqual(len(body.calls), 1)
                self.assertEqual(body.calls[0][0], "test_read")
                self.assertTrue(factory.contexts[1]["generic_action_loop"]["recent_verified_executions"][0]["verified"])
                event = server.resident.store.get_event(result["work_event_id"])
                self.assertEqual(event.payload["agent_loop"], True)
                outcome = server.resident.store.get_event_outcome(result["work_event_id"])
                self.assertTrue(outcome.success)
                self.assertEqual(outcome.model_invocations, 2)
                # Both turns ran inside model-led Resident: no parallel
                # investigation/planner was needed between verified actions.
                self.assertIsNone(server.resident.investigator.current(result["work_event_id"]))
            finally:
                server.resident.store.close()

    def test_agent_run_reuses_work_thread_instead_of_creating_model_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, factory, _ = _make_server(tmp, mode="plain")
            try:
                one = server.handle({
                    "id": "4", "method": "agent_run",
                    "params": {"thread_id": "durable-agent-thread", "task": "first request"},
                })["result"]
                two = server.handle({
                    "id": "5", "method": "agent_run",
                    "params": {"thread_id": "durable-agent-thread", "task": "second request"},
                })["result"]
                self.assertTrue(one["completed"])
                self.assertTrue(two["completed"])
                self.assertEqual(one["thread"]["id"], "durable-agent-thread")
                self.assertEqual(two["thread"]["id"], "durable-agent-thread")
                self.assertEqual(len(factory.calls), 2)
                self.assertEqual(
                    [m.role for m in server.work.get_snapshot("durable-agent-thread")[1]],
                    ["user", "zn", "user", "zn"],
                )
            finally:
                server.resident.store.close()

    def test_model_led_turn_starts_cognition_without_native_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, factory, body = _make_server(tmp)
            try:
                event = server.resident.enqueue(
                    "read the current test value",
                    kind="desktop_user_event",
                    payload={"agent_loop": True},
                )
                thought = SimpleNamespace(
                    sequence=1, focus="task", chosen_action=None,
                    action_kind=None, action_target=None, reason="task",
                    confidence=1.0, possible_actions=(),
                )
                self.assertIsNone(
                    server.resident.run_once(target_event_id=event.event_id, thought=thought)
                )
                state = server.resident.store.get_working_state()
                self.assertEqual(state.stage, "external_cognition")
                self.assertTrue(state.data["generic_action_loop"]["model_led"])
                self.assertIn("generic_action_loop", state.data["cognition_request"]["context"])
                self.assertIsNone(server.resident.investigator.current(event.event_id))
                self.assertEqual(factory.calls, [])
                self.assertEqual(body.calls, [])
            finally:
                server.resident.store.close()

    def test_model_disabled_fails_closed_without_invoking_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, factory, body = _make_server(tmp)
            try:
                event = server.resident.enqueue(
                    "run a model-led action",
                    kind="desktop_user_event",
                    payload={"agent_loop": True, "model_policy": "never"},
                )
                result = server.resident.run_once(target_event_id=event.event_id)
                self.assertFalse(result.success)
                self.assertIn("model-led Work requires permitted cognition", result.reason)
                self.assertEqual(factory.calls, [])
                self.assertEqual(body.calls, [])
            finally:
                server.resident.store.close()

    def test_agent_run_rejects_old_sidecar_turn_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, factory, _ = _make_server(tmp)
            try:
                with self.assertRaisesRegex(ValueError, "max_turns is unsupported"):
                    server.handle({
                        "id": "6", "method": "agent_run",
                        "params": {"task": "test", "max_turns": 2},
                    })
                self.assertEqual(factory.calls, [])
            finally:
                server.resident.store.close()


if __name__ == "__main__":
    unittest.main()
