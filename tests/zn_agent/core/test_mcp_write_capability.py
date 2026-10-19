from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core import KernelStore
from zn_agent.core.action_execution import ActionExecutionRuntime, ActionRequest
from zn_agent.core.action_fabric import ActionFabricRegistry
from zn_agent.core.approval_cards import ApprovalGateOutcome
from zn_agent.core.body import NativeBody
from zn_agent.core.mcp_capability_adapter import (
    ApprovedMcpWriteTool,
    McpWritePostcondition,
    attach_approved_mcp_write_tools,
    mcp_write_replay_identity,
)


def _definition(*, name="create_note", read_only=False, destructive=False):
    return {
        "name": name,
        "description": f"Write tool {name}.",
        "inputSchema": {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": read_only,
            "destructiveHint": destructive,
        },
    }


class _Client:
    def __init__(self, definitions=None):
        self.running = True
        self.server_name = "approved-test-server"
        self.server_version = "1.0.2"
        self.tool_definitions = tuple(
            definitions if definitions is not None else [_definition()]
        )
        self.tool_names = frozenset(row["name"] for row in self.tool_definitions)
        self.calls = []
        self.notes: list[str] = []
        self.fail_next: Exception | None = None
        self.error_next = False

    def call_tool(self, name, arguments=None):
        args = dict(arguments or {})
        if self.fail_next is not None:
            exc = self.fail_next
            self.fail_next = None
            raise exc
        self.calls.append((name, args))
        if self.error_next:
            self.error_next = False
            return {"isError": True, "content": [{"type": "text", "text": "provider blew up"}]}
        if name == "create_note":
            self.notes.append(str(args.get("title") or ""))
        return {"isError": False, "content": [{"type": "text", "text": f"created {args.get('title')}"}]}


def _approval(*, effect_class="reversible_side_effect", approval_kind="send", verification=("note exists",)):
    return ApprovedMcpWriteTool(
        tool_name="create_note",
        effect_class=effect_class,
        approval_kind=approval_kind,
        verification=verification,
    )


def _probe(client):
    def check(args, result):
        title = str(args.get("title") or "")
        ok = title in client.notes
        return McpWritePostcondition(
            ok,
            "note exists in provider state" if ok else "note missing from provider state",
            {"title": title},
        )

    return check


def _attach(fabric, body, client, **overrides):
    options = {
        "fabric": fabric,
        "body": body,
        "client": client,
        "provider_id": "demo",
        "expected_server_name": "approved-test-server",
        "expected_server_version": "1.0.2",
        "approved_tools": (_approval(),),
        "postcondition_probes": {"create_note": _probe(client)},
    }
    options.update(overrides)
    return attach_approved_mcp_write_tools(**options)


def _allowing_gate():
    def check(**kwargs):
        return ApprovalGateOutcome(True, reason="test approval")

    return SimpleNamespace(check=check)


def _denying_gate():
    def check(**kwargs):
        return ApprovalGateOutcome(False, reason="test deny")

    return SimpleNamespace(check=check)


class McpWriteCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fabric = ActionFabricRegistry()
        self.body = NativeBody(store=KernelStore(Path(self.tmp.name) / "kernel.db"))
        self.client = _Client()

    def tearDown(self):
        self.body.store.close()
        self.tmp.cleanup()

    def _runtime(self, gate=None):
        return ActionExecutionRuntime(self.fabric, self.body, approval_gate=gate)

    def _execute(self, runtime, *, event_id="evt-1", args=None):
        return runtime.execute(
            ActionRequest(
                "mcp.demo.create_note",
                args if args is not None else {"title": "hello"},
                event_id=event_id,
            )
        )

    def test_descriptor_carries_write_contract(self):
        attachment = _attach(self.fabric, self.body, self.client)
        try:
            descriptor = self.fabric.descriptor("mcp.demo.create_note")
            self.assertIsNotNone(descriptor)
            self.assertEqual(descriptor.effect_class, "reversible_side_effect")
            self.assertEqual(descriptor.replay_semantics, "verify_before_replay")
            self.assertEqual(descriptor.reversibility, "reversible")
            self.assertIn("approval:send", descriptor.tags)
            self.assertIn("mcp_write", descriptor.tags)
            self.assertIn("explicit_mcp_write_tool_approval", descriptor.required_authority)
            self.assertIn("note exists", descriptor.postconditions)
            self.assertTrue(self.fabric.availability(descriptor.action_id).available)
        finally:
            attachment.detach()

    def test_approved_write_verifies_through_postcondition_probe(self):
        attachment = _attach(self.fabric, self.body, self.client)
        try:
            runtime = self._runtime()
            attachment.register_verifications(runtime)
            outcome = self._execute(runtime)
            self.assertTrue(outcome.success, outcome.error)
            self.assertEqual(self.client.calls, [("create_note", {"title": "hello"})])
            self.assertEqual(
                outcome.body_result.data["replay_identity"],
                mcp_write_replay_identity(
                    provider_id="demo",
                    tool_name="create_note",
                    args={"title": "hello"},
                    event_id="evt-1",
                ),
            )
            self.assertEqual(outcome.verification.status, "verified")
        finally:
            attachment.detach()

    def test_postcondition_failure_reports_failed_without_reclaiming_success(self):
        # Separate run: probe that always fails.
        fabric = ActionFabricRegistry()
        body = NativeBody(store=KernelStore(Path(self.tmp.name) / "kernel2.db"))
        try:
            client = _Client()
            attachment = attach_approved_mcp_write_tools(
                fabric=fabric,
                body=body,
                client=client,
                provider_id="demo",
                expected_server_name="approved-test-server",
                expected_server_version="1.0.2",
                approved_tools=(_approval(),),
                postcondition_probes={
                    "create_note": lambda args, result: McpWritePostcondition(
                        False, "postcondition probe saw no effect"
                    )
                },
            )
            runtime = ActionExecutionRuntime(fabric, body)
            attachment.register_verifications(runtime)
            outcome = runtime.execute(
                ActionRequest("mcp.demo.create_note", {"title": "hello"}, event_id="evt-1")
            )
            self.assertFalse(outcome.success)
            self.assertEqual(outcome.verification.status, "failed")
            self.assertIn("no effect", outcome.error)
            # The effect WAS dispatched; only the verification failed.
            self.assertEqual(client.calls, [("create_note", {"title": "hello"})])
            attachment.detach()
        finally:
            body.store.close()

    def test_missing_verifier_wiring_fails_closed_after_dispatch(self):
        attachment = _attach(self.fabric, self.body, self.client)
        try:
            runtime = self._runtime()
            # Deliberately NOT calling register_verifications.
            outcome = self._execute(runtime)
            self.assertFalse(outcome.success)
            self.assertIn("no independent postcondition verifier", outcome.error)
            self.assertEqual(self.client.calls, [("create_note", {"title": "hello"})])
        finally:
            attachment.detach()

    def test_replay_of_same_occurrence_refuses_without_redispatch(self):
        attachment = _attach(self.fabric, self.body, self.client)
        try:
            runtime = self._runtime()
            attachment.register_verifications(runtime)
            self.assertTrue(self._execute(runtime).success)
            second = self._execute(runtime)
            self.assertFalse(second.success)
            self.assertIn("replay refused", second.error)
            self.assertEqual(self.client.calls, [("create_note", {"title": "hello"})])
        finally:
            attachment.detach()

    def test_new_event_id_is_a_distinct_occurrence(self):
        attachment = _attach(self.fabric, self.body, self.client)
        try:
            runtime = self._runtime()
            attachment.register_verifications(runtime)
            self.assertTrue(self._execute(runtime, event_id="evt-1").success)
            self.assertTrue(self._execute(runtime, event_id="evt-2").success)
            self.assertEqual(len(self.client.calls), 2)
        finally:
            attachment.detach()

    def test_replay_identity_ignores_resident_bindings(self):
        base = mcp_write_replay_identity(
            provider_id="demo",
            tool_name="create_note",
            args={"title": "hello"},
            event_id="evt-1",
        )
        self.assertEqual(
            base,
            mcp_write_replay_identity(
                provider_id="demo",
                tool_name="create_note",
                args={"title": "hello", "__zn_authority_context": {"worker": "x"}},
                event_id="evt-1",
            ),
        )
        self.assertNotEqual(
            base,
            mcp_write_replay_identity(
                provider_id="demo",
                tool_name="create_note",
                args={"title": "hello"},
                event_id="evt-2",
            ),
        )

    def test_approval_denial_never_dispatches(self):
        attachment = _attach(self.fabric, self.body, self.client)
        try:
            runtime = self._runtime(gate=_denying_gate())
            attachment.register_verifications(runtime)
            outcome = self._execute(runtime)
            self.assertFalse(outcome.success)
            self.assertIn("approval_required", outcome.error)
            self.assertEqual(self.client.calls, [])
        finally:
            attachment.detach()

    def test_approval_allow_dispatches(self):
        attachment = _attach(self.fabric, self.body, self.client)
        try:
            runtime = self._runtime(gate=_allowing_gate())
            attachment.register_verifications(runtime)
            outcome = self._execute(runtime)
            self.assertTrue(outcome.success, outcome.error)
            self.assertEqual(self.client.calls, [("create_note", {"title": "hello"})])
        finally:
            attachment.detach()

    def test_unapproved_write_tool_stays_disabled(self):
        client = _Client(definitions=[_definition(), _definition(name="delete_all")])
        attachment = _attach(self.fabric, self.body, client)
        try:
            self.assertIsNone(self.fabric.descriptor("mcp.demo.delete_all"))
            with self.assertRaises(KeyError):
                self._runtime().execute(
                    ActionRequest("mcp.demo.delete_all", {"title": "x"}, event_id="evt-1")
                )
            self.assertEqual(client.calls, [])
        finally:
            attachment.detach()

    def test_write_attach_refuses_read_only_tool(self):
        client = _Client(definitions=[_definition(read_only=True)])
        with self.assertRaises(ValueError):
            _attach(self.fabric, self.body, client)
        self.assertIsNone(self.fabric.descriptor("mcp.demo.create_note"))

    def test_write_attach_refuses_missing_annotations(self):
        definition = _definition()
        del definition["annotations"]
        client = _Client(definitions=[definition])
        with self.assertRaises(ValueError):
            _attach(self.fabric, self.body, client)

    def test_write_attach_requires_exact_probe_coverage(self):
        with self.assertRaises(ValueError):
            _attach(self.fabric, self.body, self.client, postcondition_probes={})
        with self.assertRaises(ValueError):
            _attach(
                self.fabric,
                self.body,
                self.client,
                postcondition_probes={
                    "create_note": _probe(self.client),
                    "delete_all": _probe(self.client),
                },
            )

    def test_approval_record_validation(self):
        with self.assertRaises(ValueError):
            ApprovedMcpWriteTool(
                tool_name="create_note",
                effect_class="read_only",
                approval_kind="send",
                verification=("note exists",),
            )
        with self.assertRaises(ValueError):
            ApprovedMcpWriteTool(
                tool_name="create_note",
                effect_class="reversible_side_effect",
                approval_kind="not_a_kind",
                verification=("note exists",),
            )
        with self.assertRaises(ValueError):
            ApprovedMcpWriteTool(
                tool_name="create_note",
                effect_class="reversible_side_effect",
                approval_kind="send",
                verification=(),
            )

    def test_provider_error_records_identity_and_blocks_replay(self):
        attachment = _attach(self.fabric, self.body, self.client)
        try:
            runtime = self._runtime()
            attachment.register_verifications(runtime)
            self.client.error_next = True
            first = self._execute(runtime)
            self.assertFalse(first.success)
            self.assertIn("uncertain", first.error)
            second = self._execute(runtime)
            self.assertFalse(second.success)
            self.assertIn("replay refused", second.error)
            # Only the first dispatch reached the provider.
            self.assertEqual(len(self.client.calls), 1)
        finally:
            attachment.detach()

    def test_transport_exception_leaves_identity_unrecorded(self):
        attachment = _attach(self.fabric, self.body, self.client)
        try:
            runtime = self._runtime()
            attachment.register_verifications(runtime)
            self.client.fail_next = RuntimeError("connection reset")
            first = self._execute(runtime)
            self.assertFalse(first.success)
            second = self._execute(runtime, event_id="evt-1")
            self.assertTrue(second.success, second.error)
            self.assertEqual(len(self.client.calls), 1)
        finally:
            attachment.detach()

    def test_catalog_drift_fails_closed_before_dispatch(self):
        attachment = _attach(self.fabric, self.body, self.client)
        try:
            changed = _definition()
            changed["description"] = "a changed tool definition"
            self.client.tool_definitions = (changed,)
            self.assertFalse(self.fabric.availability("mcp.demo.create_note").available)
            runtime = self._runtime()
            attachment.register_verifications(runtime)
            self.assertFalse(self._execute(runtime).success)
            self.assertEqual(self.client.calls, [])
        finally:
            attachment.detach()

    def test_audit_redacts_write_payload_but_keeps_replay_identity(self):
        attachment = _attach(self.fabric, self.body, self.client)
        try:
            runtime = self._runtime()
            attachment.register_verifications(runtime)
            outcome = self._execute(runtime)
            self.assertTrue(outcome.success)
            with closing(sqlite3.connect(self.body.store.path)) as db:
                saved_action, saved_result = db.execute(
                    "SELECT action_json, result_json FROM native_body_actions WHERE action_id=?",
                    (outcome.body_result.action_id,),
                ).fetchone()
            record = json.loads(saved_action)
            audit = json.loads(saved_result)
            self.assertNotIn("hello", saved_action)
            self.assertNotIn("created hello", saved_result)
            self.assertTrue(record["args"]["redacted"])
            self.assertEqual(record["args"]["names"], ["title"])
            self.assertTrue(audit["data"]["external_write_redacted"])
            self.assertEqual(
                audit["data"]["replay_identity"],
                outcome.body_result.data["replay_identity"],
            )
        finally:
            attachment.detach()

    def test_detach_removes_descriptor_and_handler(self):
        attachment = _attach(self.fabric, self.body, self.client)
        kind = self.fabric.descriptor("mcp.demo.create_note").body_action_kind
        attachment.detach()
        self.assertIsNone(self.fabric.descriptor("mcp.demo.create_note"))
        result = self.body.act(kind, event_id="evt-1", title="hello")
        self.assertFalse(result.success)
        self.assertEqual(self.client.calls, [])
