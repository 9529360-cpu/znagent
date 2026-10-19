from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core import KernelStore
from zn_agent.core.action_execution import ActionExecutionRuntime, ActionRequest
from zn_agent.core.action_fabric import ActionFabricRegistry
from zn_agent.core.body import NativeBody
from zn_agent.core.mcp_capability_adapter import (
    McpWritePostcondition,
    mcp_write_replay_identity,
)
from zn_agent.core.openapi_rest_adapter import (
    ApprovedRestWriteTool,
    RestHttpResponse,
    UrllibRestHttpClient,
    attach_openapi_rest_tools,
    parse_openapi_spec,
)


def _spec(**overrides):
    base = {
        "openapi": "3.0.3",
        "info": {"title": "Demo Pet API", "version": "1.0.0"},
        "servers": [{"url": "https://api.example.test/v1"}],
        "paths": {
            "/pets": {
                "get": {
                    "operationId": "list_pets",
                    "summary": "List pets",
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "responses": {"200": {"description": "ok"}},
                },
                "post": {
                    "operationId": "create_pet",
                    "summary": "Create a pet",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"name": {"type": "string"}},
                                    "required": ["name"],
                                    "additionalProperties": False,
                                }
                            }
                        }
                    },
                    "responses": {"201": {"description": "created"}},
                },
            },
            "/pets/{petId}": {
                "get": {
                    "operationId": "get_pet",
                    "summary": "Get one pet",
                    "parameters": [
                        {
                            "name": "petId",
                            "in": "path",
                            "required": True,
                            "schema": {"$ref": "#/components/schemas/PetId"},
                        }
                    ],
                    "responses": {"200": {"description": "ok"}},
                },
                "delete": {
                    "operationId": "delete_pet",
                    "summary": "Delete a pet",
                    "parameters": [
                        {
                            "name": "petId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"204": {"description": "deleted"}},
                },
            },
        },
        "components": {
            "schemas": {"PetId": {"type": "string"}},
        },
    }
    base.update(overrides)
    return base


class _FakeHttp:
    """Mock HTTP service: records requests, answers from a tiny store."""

    def __init__(self):
        self.calls = []
        self.pets: dict[str, str] = {"p1": "Fido"}
        self.fail_next: Exception | None = None
        self.status_next: int | None = None

    def request(self, method, url, *, params, headers, json_body, timeout_seconds):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "params": dict(params),
                "headers": dict(headers),
                "json_body": json_body,
            }
        )
        if self.fail_next is not None:
            exc = self.fail_next
            self.fail_next = None
            raise exc
        if self.status_next is not None:
            status = self.status_next
            self.status_next = None
            return RestHttpResponse(status, {}, b'{"error": "nope"}')
        if method == "get" and url.endswith("/pets"):
            items = [
                {"id": pet_id, "name": name}
                for pet_id, name in sorted(self.pets.items())
            ]
            return RestHttpResponse(
                200, {}, json.dumps({"pets": items}).encode("utf-8")
            )
        if method == "get" and "/pets/" in url:
            pet_id = url.rsplit("/", 1)[-1]
            if pet_id in self.pets:
                return RestHttpResponse(
                    200,
                    {},
                    json.dumps({"id": pet_id, "name": self.pets[pet_id]}).encode(),
                )
            return RestHttpResponse(404, {}, b'{"error": "not found"}')
        if method == "post" and url.endswith("/pets"):
            name = (json_body or {}).get("name", "")
            pet_id = f"p{len(self.pets) + 1}"
            self.pets[pet_id] = str(name)
            return RestHttpResponse(
                201, {}, json.dumps({"id": pet_id, "name": name}).encode()
            )
        if method == "delete" and "/pets/" in url:
            self.pets.pop(url.rsplit("/", 1)[-1], None)
            return RestHttpResponse(204, {}, b"")
        return RestHttpResponse(404, {}, b'{"error": "not found"}')


def _attach(fabric, body, client, **overrides):
    options = {
        "fabric": fabric,
        "body": body,
        "spec": _spec(),
        "provider_id": "demo",
        "http_client": client,
    }
    options.update(overrides)
    return attach_openapi_rest_tools(**options)


def _approval(**overrides):
    options = {
        "tool_name": "create_pet",
        "effect_class": "reversible_side_effect",
        "approval_kind": "send",
        "verification": ("pet exists",),
    }
    options.update(overrides)
    return ApprovedRestWriteTool(**options)


def _probe(client):
    def check(args, result):
        name = str(args.get("name") or "")
        ok = name in client.pets.values()
        return McpWritePostcondition(
            ok,
            "pet exists in service state" if ok else "pet missing from service state",
            {"name": name},
        )

    return check


class OpenApiRestAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fabric = ActionFabricRegistry()
        self.body = NativeBody(store=KernelStore(Path(self.tmp.name) / "kernel.db"))
        self.client = _FakeHttp()

    def tearDown(self):
        self.body.store.close()
        self.tmp.cleanup()

    def _execute(self, runtime, action_id, args, *, event_id="evt-1"):
        return runtime.execute(ActionRequest(action_id, args, event_id=event_id))

    def test_read_tool_registers_and_calls_mock_service(self):
        attachment = _attach(self.fabric, self.body, self.client)
        try:
            descriptor = self.fabric.descriptor("rest.demo.list_pets")
            self.assertIsNotNone(descriptor)
            self.assertEqual(descriptor.effect_class, "read_only")
            self.assertEqual(descriptor.replay_semantics, "read_only")
            self.assertIn("rest", descriptor.tags)
            self.assertIn("openapi", descriptor.tags)
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            outcome = self._execute(runtime, "rest.demo.list_pets", {"limit": 10})
            self.assertTrue(outcome.success, outcome.error)
            self.assertIn("Fido", outcome.body_result.output)
            self.assertEqual(self.client.calls[0]["method"], "get")
            self.assertTrue(
                self.client.calls[0]["url"].endswith("/pets"),
                self.client.calls[0]["url"],
            )
            self.assertEqual(self.client.calls[0]["params"], {"limit": 10})
            self.assertEqual(
                outcome.body_result.data["status_code"], 200
            )
            self.assertTrue(
                outcome.body_result.data["untrusted_external_evidence"]
            )
        finally:
            attachment.detach()

    def test_path_param_substitution_and_url_encoding(self):
        attachment = _attach(self.fabric, self.body, self.client)
        try:
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            outcome = self._execute(
                runtime, "rest.demo.get_pet", {"petId": "p1"}
            )
            self.assertTrue(outcome.success, outcome.error)
            self.assertIn("Fido", outcome.body_result.output)
            self.assertTrue(
                self.client.calls[0]["url"].endswith("/pets/p1"),
                self.client.calls[0]["url"],
            )
        finally:
            attachment.detach()

    def test_local_ref_parameter_schema_resolves(self):
        parsed = parse_openapi_spec(_spec())
        get_pet = next(
            op for op in parsed.operations if op.operation_id == "get_pet"
        )
        self.assertEqual(
            get_pet.input_schema["properties"]["petId"]["type"], "string"
        )

    def test_json_text_spec_parses(self):
        parsed = parse_openapi_spec(json.dumps(_spec()))
        self.assertEqual(
            {op.operation_id for op in parsed.operations},
            {"list_pets", "get_pet", "create_pet", "delete_pet"},
        )

    def test_write_tools_disabled_by_default(self):
        attachment = _attach(self.fabric, self.body, self.client)
        try:
            self.assertIsNone(self.fabric.descriptor("rest.demo.create_pet"))
            self.assertIsNone(self.fabric.descriptor("rest.demo.delete_pet"))
            self.assertEqual(
                attachment.disabled_write_operations,
                ("create_pet", "delete_pet"),
            )
        finally:
            attachment.detach()

    def test_approved_write_verifies_through_postcondition_probe(self):
        attachment = _attach(
            self.fabric,
            self.body,
            self.client,
            approved_write_tools=(_approval(),),
            postcondition_probes={"create_pet": _probe(self.client)},
        )
        try:
            descriptor = self.fabric.descriptor("rest.demo.create_pet")
            self.assertIsNotNone(descriptor)
            self.assertEqual(descriptor.effect_class, "reversible_side_effect")
            self.assertEqual(descriptor.replay_semantics, "verify_before_replay")
            self.assertIn("approval:send", descriptor.tags)
            self.assertIn("rest_write", descriptor.tags)
            self.assertIn(
                "explicit_rest_write_tool_approval",
                descriptor.required_authority,
            )
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            attachment.register_verifications(runtime)
            outcome = self._execute(
                runtime, "rest.demo.create_pet", {"name": "Whiskers"}
            )
            self.assertTrue(outcome.success, outcome.error)
            self.assertEqual(outcome.verification.status, "verified")
            self.assertEqual(
                outcome.body_result.data["replay_identity"],
                mcp_write_replay_identity(
                    provider_id="demo",
                    tool_name="create_pet",
                    args={"name": "Whiskers"},
                    event_id="evt-1",
                ),
            )
            self.assertEqual(
                self.client.calls, [self.client.calls[0]]
            )
            self.assertEqual(self.client.calls[0]["method"], "post")
            self.assertEqual(self.client.calls[0]["json_body"], {"name": "Whiskers"})
        finally:
            attachment.detach()

    def test_write_replay_refused_without_redispatch(self):
        attachment = _attach(
            self.fabric,
            self.body,
            self.client,
            approved_write_tools=(_approval(),),
            postcondition_probes={"create_pet": _probe(self.client)},
        )
        try:
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            attachment.register_verifications(runtime)
            self.assertTrue(
                self._execute(
                    runtime, "rest.demo.create_pet", {"name": "Whiskers"}
                ).success
            )
            second = self._execute(
                runtime, "rest.demo.create_pet", {"name": "Whiskers"}
            )
            self.assertFalse(second.success)
            self.assertIn("replay refused", second.error)
            self.assertEqual(len(self.client.calls), 1)
        finally:
            attachment.detach()

    def test_write_without_verifier_fails_closed_after_dispatch(self):
        attachment = _attach(
            self.fabric,
            self.body,
            self.client,
            approved_write_tools=(_approval(),),
            postcondition_probes={"create_pet": _probe(self.client)},
        )
        try:
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            # Deliberately NOT calling register_verifications.
            outcome = self._execute(
                runtime, "rest.demo.create_pet", {"name": "Whiskers"}
            )
            self.assertFalse(outcome.success)
            self.assertIn("no independent postcondition verifier", outcome.error)
            self.assertEqual(len(self.client.calls), 1)
        finally:
            attachment.detach()

    def test_postcondition_failure_reports_failed(self):
        attachment = _attach(
            self.fabric,
            self.body,
            self.client,
            approved_write_tools=(_approval(),),
            postcondition_probes={
                "create_pet": lambda args, result: McpWritePostcondition(
                    False, "postcondition probe saw no effect"
                )
            },
        )
        try:
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            attachment.register_verifications(runtime)
            outcome = self._execute(
                runtime, "rest.demo.create_pet", {"name": "Whiskers"}
            )
            self.assertFalse(outcome.success)
            self.assertEqual(outcome.verification.status, "failed")
            self.assertIn("no effect", outcome.error)
            self.assertEqual(len(self.client.calls), 1)
        finally:
            attachment.detach()

    def test_illegal_specs_rejected(self):
        cases = {}
        no_version = _spec()
        no_version["openapi"] = "2.0"
        cases["swagger version"] = no_version
        empty_paths = _spec()
        empty_paths["paths"] = {}
        cases["empty paths"] = empty_paths
        no_title = _spec()
        no_title["info"] = {}
        cases["missing title"] = no_title
        dup_id = _spec()
        dup_id["paths"]["/pets"]["get"]["operationId"] = "get_pet"
        cases["duplicate operationId"] = dup_id
        get_body = _spec()
        get_body["paths"]["/pets"]["get"]["requestBody"] = {
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    }
                }
            }
        }
        cases["GET with requestBody"] = get_body
        complex_schema = _spec()
        complex_schema["paths"]["/pets"]["get"]["parameters"] = [
            {
                "name": "filter",
                "in": "query",
                "required": False,
                "schema": {"type": "array", "items": {"type": "string"}},
            }
        ]
        cases["array schema"] = complex_schema
        external_ref = _spec()
        external_ref["paths"]["/pets/{petId}"]["get"]["parameters"] = [
            {
                "name": "petId",
                "in": "path",
                "required": True,
                "schema": {"$ref": "https://example.test/schemas.json#/PetId"},
            }
        ]
        cases["external $ref"] = external_ref
        path_mismatch = _spec()
        path_mismatch["paths"]["/pets/{petId}"]["get"]["parameters"] = []
        cases["path param mismatch"] = path_mismatch
        no_2xx = _spec()
        no_2xx["paths"]["/pets"]["get"]["responses"] = {
            "404": {"description": "missing"}
        }
        cases["no 2xx response"] = no_2xx
        for label, bad in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    parse_openapi_spec(bad)
                with self.assertRaises(ValueError):
                    _attach(self.fabric, self.body, self.client, spec=bad)

    def test_base_url_and_credential_rules(self):
        with self.assertRaises(ValueError):
            _attach(
                self.fabric,
                self.body,
                self.client,
                base_url="https://user:secret@api.example.test/v1",
            )
        with self.assertRaises(ValueError):
            _attach(
                self.fabric,
                self.body,
                self.client,
                base_url="ftp://api.example.test/v1",
            )
        with self.assertRaises(ValueError):
            _attach(
                self.fabric,
                self.body,
                self.client,
                credential_ref="Bearer not-a-reference",
            )
        with self.assertRaises(ValueError):
            _attach(
                self.fabric,
                self.body,
                self.client,
                credential_ref="credential:api-key:abc123",
            )
        with self.assertRaises(ValueError):
            _attach(
                self.fabric, self.body, self.client, timeout_seconds=0.5
            )
        with self.assertRaises(ValueError):
            _attach(
                self.fabric, self.body, self.client, timeout_seconds=61.0
            )

    def test_credential_resolver_headers_applied_opaquely(self):
        seen = {}

        def resolver(ref):
            seen["ref"] = ref
            return {"Authorization": "Bearer test-token"}

        attachment = _attach(
            self.fabric,
            self.body,
            self.client,
            credential_ref="credential:api-key:abc123",
            credential_resolver=resolver,
        )
        try:
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            outcome = self._execute(runtime, "rest.demo.list_pets", {})
            self.assertTrue(outcome.success, outcome.error)
            self.assertEqual(seen["ref"], "credential:api-key:abc123")
            self.assertEqual(
                self.client.calls[0]["headers"].get("Authorization"),
                "Bearer test-token",
            )
        finally:
            attachment.detach()

    def test_approval_probe_mismatch_refused(self):
        with self.assertRaises(ValueError):
            _attach(
                self.fabric,
                self.body,
                self.client,
                approved_write_tools=(_approval(),),
                postcondition_probes={},
            )
        with self.assertRaises(ValueError):
            _attach(
                self.fabric,
                self.body,
                self.client,
                approved_write_tools=(_approval(),),
                postcondition_probes={
                    "create_pet": _probe(self.client),
                    "delete_pet": _probe(self.client),
                },
            )
        with self.assertRaises(ValueError):
            _attach(
                self.fabric,
                self.body,
                self.client,
                approved_write_tools=(
                    _approval(tool_name="list_pets"),
                ),
                postcondition_probes={"list_pets": _probe(self.client)},
            )

    def test_non_2xx_read_fails(self):
        attachment = _attach(self.fabric, self.body, self.client)
        try:
            self.client.status_next = 500
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            outcome = self._execute(runtime, "rest.demo.list_pets", {})
            self.assertFalse(outcome.success)
            self.assertIn("500", outcome.error)
        finally:
            attachment.detach()

    def test_unknown_and_missing_args_rejected(self):
        attachment = _attach(self.fabric, self.body, self.client)
        try:
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            unknown = self._execute(
                runtime, "rest.demo.list_pets", {"bogus": 1}
            )
            self.assertFalse(unknown.success)
            self.assertEqual(len(self.client.calls), 0)
            # create_pet is disabled, so exercise missing-arg on the read op
            # with a required path param instead.
            missing = self._execute(runtime, "rest.demo.get_pet", {})
            self.assertFalse(missing.success)
            self.assertEqual(len(self.client.calls), 0)
        finally:
            attachment.detach()

    def test_detach_unregisters(self):
        attachment = _attach(self.fabric, self.body, self.client)
        self.assertIsNotNone(self.fabric.descriptor("rest.demo.list_pets"))
        attachment.detach()
        self.assertIsNone(self.fabric.descriptor("rest.demo.list_pets"))
        attachment.detach()  # Idempotent.

    def test_real_http_against_local_mock_server(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # Keep test output quiet.
                pass

            def do_GET(self):
                if self.path == "/pets":
                    payload = json.dumps(
                        {"pets": [{"id": "p1", "name": "Fido"}]}
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                else:
                    self.send_response(404)
                    self.end_headers()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            attachment = attach_openapi_rest_tools(
                fabric=self.fabric,
                body=self.body,
                spec=_spec(),
                provider_id="demo",
                base_url=f"http://127.0.0.1:{port}",
                http_client=UrllibRestHttpClient(),
            )
            try:
                runtime = ActionExecutionRuntime(self.fabric, self.body)
                outcome = self._execute(runtime, "rest.demo.list_pets", {})
                self.assertTrue(outcome.success, outcome.error)
                self.assertIn("Fido", outcome.body_result.output)
            finally:
                attachment.detach()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
