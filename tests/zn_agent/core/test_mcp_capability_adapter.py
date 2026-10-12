from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from zn_agent.core import KernelStore, ModelRoute, WorkerResult, ZNKernelRuntime
from zn_agent.core.action_execution import ActionExecutionRuntime, ActionRequest
from zn_agent.core.action_fabric import ActionFabricRegistry
from zn_agent.core.body import NativeBody
from zn_agent.core.generic_action_loop import build_generic_action_context
from zn_agent.core.mcp_capability_adapter import attach_approved_mcp_read_tools
from zn_agent.core.research_information_product_resident import (
    ProductResearchInformationResidentRuntime,
)


def _definition(*, name="read_status", read_only=True, schema=None):
    return {
        "name": name,
        "description": "Read a current status, without mutating the machine.",
        "inputSchema": schema if schema is not None else {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": read_only,
            "destructiveHint": False,
        },
    }


class _Client:
    def __init__(self, definitions=None):
        self.running = True
        self.server_name = "approved-test-server"
        self.server_version = "1.0.2"
        self.tool_definitions = tuple(definitions if definitions is not None else [_definition()])
        self.tool_names = frozenset(row["name"] for row in self.tool_definitions)
        self.calls = []

    def call_tool(self, name, arguments=None):
        self.calls.append((name, dict(arguments or {})))
        return {"isError": False, "content": [{"type": "text", "text": "status healthy"}]}


def _attach(fabric, body, client, **overrides):
    options = {
        "fabric": fabric,
        "body": body,
        "client": client,
        "provider_id": "demo",
        "expected_server_name": "approved-test-server",
        "expected_server_version": "1.0.2",
        "approved_tool_names": ("read_status",),
    }
    options.update(overrides)
    return attach_approved_mcp_read_tools(**options)


class ApprovedMcpAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fabric = ActionFabricRegistry()
        self.body = NativeBody(store=KernelStore(Path(self.tmp.name) / "kernel.db"))
        self.client = _Client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_tool_can_be_discovered_and_called_through_normal_body(self):
        attachment = _attach(self.fabric, self.body, self.client)
        try:
            descriptor = self.fabric.descriptor("mcp.demo.read_status")
            self.assertIsNotNone(descriptor)
            self.assertEqual(descriptor.effect_class, "read_only")
            self.assertEqual(descriptor.provider, "zn.mcp.demo")
            self.assertTrue(self.fabric.availability(descriptor.action_id).available)
            context = build_generic_action_context(
                fabric=self.fabric,
                device_capabilities=type("Device", (), {"foreground_application": lambda self: None})(),
                task="read live status",
            )
            self.assertEqual(
                [x["action_id"] for x in context["available_actions"]],
                ["mcp.demo.read_status"],
            )
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            outcome = runtime.execute(
                ActionRequest(descriptor.action_id, {"query": "private-query-2026"}, event_id="evt-test")
            )
            self.assertTrue(outcome.success, outcome.error)
            self.assertEqual(outcome.observations[0].data["text"], "status healthy")
            self.assertTrue(outcome.observations[0].data["untrusted_external_evidence"])
            self.assertEqual(self.client.calls, [("read_status", {"query": "private-query-2026"})])
            with sqlite3.connect(self.body.store.path) as db:
                saved = db.execute(
                    "SELECT action_json FROM native_body_actions WHERE action_id=?",
                    (outcome.body_result.action_id,),
                ).fetchone()[0]
            record = json.loads(saved)
            self.assertNotIn("private-query-2026", saved)
            self.assertTrue(record["args"]["redacted"])
            self.assertEqual(record["args"]["names"], ["query"])
        finally:
            attachment.detach()

    def test_input_validation_uses_existing_action_executor(self):
        attached = _attach(self.fabric, self.body, self.client)
        try:
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            self.assertFalse(runtime.execute(
                ActionRequest("mcp.demo.read_status", {}, event_id="evt-test")
            ).success)
            self.assertFalse(runtime.execute(
                ActionRequest("mcp.demo.read_status", {"query": "ok", "extra": "bad"}, event_id="evt-test")
            ).success)
            self.assertEqual(self.client.calls, [])
        finally:
            attached.detach()

    def test_disconnect_or_catalog_drift_fails_closed_before_dispatch(self):
        attached = _attach(self.fabric, self.body, self.client)
        try:
            self.client.running = False
            self.assertFalse(self.fabric.availability("mcp.demo.read_status").available)
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            self.assertFalse(runtime.execute(
                ActionRequest("mcp.demo.read_status", {"query": "x"})
            ).success)
            self.client.running = True
            changed = _definition()
            changed["description"] = "a changed tool definition"
            self.client.tool_definitions = (changed,)
            self.assertFalse(self.fabric.availability("mcp.demo.read_status").available)
            self.assertFalse(runtime.execute(
                ActionRequest("mcp.demo.read_status", {"query": "x"})
            ).success)
            self.assertEqual(self.client.calls, [])
        finally:
            attached.detach()

    def test_approval_requires_pinned_identity_and_connected_session(self):
        with self.assertRaisesRegex(RuntimeError, "identity/version"):
            _attach(
                self.fabric, self.body, self.client,
                expected_server_version="1.0.1",
            )
        self.client.running = False
        with self.assertRaisesRegex(RuntimeError, "explicitly connected"):
            _attach(self.fabric, self.body, self.client)
        self.assertEqual(self.fabric.names(), ())
        self.assertEqual(self.body._external_read_handlers, {})

    def test_rejects_unreviewed_and_effectful_tool_declarations(self):
        with self.assertRaisesRegex(ValueError, "not present"):
            _attach(self.fabric, self.body, self.client, approved_tool_names=("run_terminal",))
        self.client.tool_definitions = (_definition(name="read_status", read_only=False),)
        with self.assertRaisesRegex(ValueError, "annotated read tools"):
            _attach(self.fabric, self.body, self.client)
        self.assertEqual(self.fabric.names(), ())

    def test_rejects_schema_the_existing_validator_cannot_enforce(self):
        for schema in (
            {"type": "object", "properties": {"x": {"type": "array"}}},
            {"type": "object", "properties": {"x": {"type": "string"}}, "additionalProperties": True},
            {"type": "object", "properties": {}, "oneOf": [{"type": "object"}]},
        ):
            self.client.tool_definitions = (_definition(schema=schema),)
            with self.subTest(schema=schema):
                with self.assertRaises(ValueError):
                    _attach(self.fabric, self.body, self.client)
                self.assertEqual(self.fabric.names(), ())

    def test_duplicate_import_does_not_erase_approved_existing_action(self):
        attached = _attach(self.fabric, self.body, self.client)
        try:
            with self.assertRaisesRegex(ValueError, "already owns"):
                _attach(self.fabric, self.body, self.client)
            self.assertTrue(self.fabric.availability("mcp.demo.read_status").available)
        finally:
            attached.detach()
        self.assertIsNone(self.fabric.descriptor("mcp.demo.read_status"))

    def test_attachment_detaches_without_stopping_external_process(self):
        attached = _attach(self.fabric, self.body, self.client)
        kind = attached.descriptors[0].body_action_kind
        attached.detach()
        attached.detach()
        self.assertTrue(self.client.running)
        self.assertEqual(self.fabric.names(), ())
        self.assertNotIn(kind, self.body._external_read_handlers)
        rejected = self.body.act(kind, event_id="evt-after-detach", query="x")
        self.assertFalse(rejected.success)
        self.assertEqual(self.client.calls, [])


class _LoopWorker:
    def __init__(self, factory):
        self.factory = factory

    def run(self, goal, kernel_context):
        raw = goal.metadata.get("cognition_request")
        context = raw.get("context") if isinstance(raw, dict) else {}
        loop = context.get("generic_action_loop") if isinstance(context, dict) else {}
        actions = loop.get("available_actions") if isinstance(loop, dict) else []
        history = loop.get("recent_verified_executions") if isinstance(loop, dict) else []
        self.factory.contexts.append(loop)
        if not history:
            if "mcp.demo.read_status" not in [x.get("action_id") for x in actions]:
                raise AssertionError("the model did not receive the MCP action catalog")
            answer = (
                '{"zn_action_proposal":{"action_id":"mcp.demo.read_status",'
                '"arguments":{"query":"status"}}}'
            )
        else:
            self.factory.evidence = history[-1]
            answer = (
                '{"zn_action_completion":{"execution_ids":["'
                + str(history[-1]["execution_id"])
                + '"],"response":"verified the external read"}}'
            )
        return WorkerResult(
            success=True, response=answer,
            verification_passed=True, metrics={"model_invoked": True},
        )


class _LoopFactory:
    def __init__(self):
        self.contexts = []
        self.evidence = None

    def create(self, route):
        return _LoopWorker(self)


class McpReadOnlyResidentLoopTests(unittest.TestCase):
    def test_model_chooses_external_plugin_but_original_resident_owns_execution(self):
        with tempfile.TemporaryDirectory() as root:
            factory = _LoopFactory()
            kernel = ZNKernelRuntime(
                store=KernelStore(Path(root) / "kernel.db"),
                routes=[ModelRoute("primary", "test", "model", {"general": 0.9})],
                worker_factory=factory,
            )
            resident = ProductResearchInformationResidentRuntime(kernel=kernel)
            client = _Client()
            bound = _attach(resident.action_fabric, resident.body, client)
            try:
                event = resident.enqueue(
                    "read the external status",
                    kind="desktop_user_event",
                )
                result = resident.run_once(target_event_id=event.event_id)
                self.assertTrue(result.success, result.reason)
                self.assertEqual(result.response, "verified the external read")
                self.assertEqual(result.model_invocations, 2)
                self.assertEqual(len(client.calls), 1)
                self.assertEqual(factory.evidence["action_id"], "mcp.demo.read_status")
                self.assertTrue(factory.evidence["verified"])
                self.assertIsNotNone(resident.store.get_event_outcome(event.event_id))
            finally:
                bound.detach()
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
