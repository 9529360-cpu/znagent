from __future__ import annotations

import hashlib
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core import KernelStore, ModelRoute, WorkerResult, ZNKernelRuntime
from zn_agent.core.action_execution import ActionExecutionRuntime, ActionRequest
from zn_agent.core.action_fabric import ActionFabricRegistry
from zn_agent.core.body import BodyAction, NativeBody
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.mcp_read_capability_host import (
    ApprovedMcpReadProvider, McpReadCapabilityHost, PinnedMcpFile,
)
from zn_agent.core.research_information_product_resident import (
    ProductResearchInformationResidentRuntime,
)
from zn_agent.core.stdio_mcp import StdioMcpCommand


def _tool():
    return {
        "name": "read_status",
        "description": "Read current state without a side effect",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    }


class _FakeStdioClient:
    def __init__(self, **kwargs):
        self.command = kwargs["command"]
        self.running = False
        self.server_name = "approved-test-server"
        self.server_version = "1.0.2"
        self.tool_names = frozenset({"read_status"})
        self.tool_definitions = (_tool(),)
        self.start_calls = 0
        self.close_calls = 0
        self.calls = []
        self.fail_start = False
        self.on_call = None

    def start(self):
        self.start_calls += 1
        self.running = True
        if self.fail_start:
            raise RuntimeError("sensitive private startup stderr")
        return self

    def close(self):
        self.close_calls += 1
        self.running = False

    def call_tool(self, name, arguments=None):
        # Deliberately mimic StdioMcpClient.call_tool's auto-start behavior:
        # a stopped provider MUST NOT resurrect through a stale Body callback.
        if not self.running:
            self.start()
        if self.on_call is not None:
            self.on_call()
        self.calls.append((name, dict(arguments or {})))
        return {"content": [{"type": "text", "text": "state healthy"}], "isError": False}


class _Factory:
    def __init__(self):
        self.created = []
        self.fail_start = False
        self.version = "1.0.2"
        self.read_only = True

    def __call__(self, **kwargs):
        client = _FakeStdioClient(**kwargs)
        client.fail_start = self.fail_start
        client.server_version = self.version
        if not self.read_only:
            client.tool_definitions[0]["annotations"]["readOnlyHint"] = False
        self.created.append(client)
        return client


def _approved(root: Path):
    exe = root / "reviewed-test-plugin.exe"
    exe.write_bytes(b"trusted test MCP executable")
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    return ApprovedMcpReadProvider(
        provider_id="demo",
        expected_server_name="approved-test-server",
        expected_server_version="1.0.2",
        approved_tool_names=("read_status",),
        command=StdioMcpCommand(
            argv=(str(exe), "--stdio"),
            cwd=root,
            env={"PRIVATE_SECRET": "never return this value"},
        ),
        pinned_files=(PinnedMcpFile(exe, digest),),
    )


class McpReadCapabilityHostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.approval = _approved(self.root)
        self.store = KernelStore(self.root / "kernel.db")
        self.body = NativeBody(store=self.store)
        self.fabric = ActionFabricRegistry()
        self.factory = _Factory()
        self.host = McpReadCapabilityHost(
            SimpleNamespace(body=self.body, action_fabric=self.fabric),
            approvals=(self.approval,),
            client_factory=self.factory,
        )

    def tearDown(self):
        self.host.close()
        self.store.close()
        self.tmp.cleanup()

    def test_no_plugin_process_runs_before_explicit_connect(self):
        status = self.host.catalog()
        self.assertEqual(len(status), 1)
        self.assertFalse(status[0]["connected"])
        self.assertEqual(status[0]["action_ids"], [])
        self.assertEqual(self.factory.created, [])
        self.assertNotIn("PRIVATE_SECRET", json.dumps(status))
        self.assertNotIn(str(self.approval.command.argv[0]), json.dumps(status))
        self.assertEqual(self.fabric.descriptors(), ())
        with self.assertRaisesRegex(ValueError, "no preapproved"):
            self.host.connect("unapproved")

    def test_connect_dispatches_only_via_existing_action_fabric_and_body(self):
        status = self.host.connect("demo")
        self.assertTrue(status["connected"])
        self.assertEqual(status["action_ids"], ["mcp.demo.read_status"])
        self.assertEqual(len(self.factory.created), 1)
        self.assertEqual(self.factory.created[0].start_calls, 1)
        result = ActionExecutionRuntime(self.fabric, self.body).execute(
            ActionRequest("mcp.demo.read_status", {"query": "status"}, event_id="evt-host")
        )
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.observations[0].data["text"], "state healthy")
        self.assertEqual(self.factory.created[0].calls, [("read_status", {"query": "status"})])
        same = self.host.connect("demo")
        self.assertTrue(same["connected"])
        self.assertEqual(len(self.factory.created), 1)

    def test_disconnect_removes_only_its_actions_and_cannot_restart_stale_client(self):
        self.host.connect("demo")
        kind = self.fabric.descriptor("mcp.demo.read_status").body_action_kind
        callback = self.body._external_read_handlers[kind]
        client = self.factory.created[0]
        self.assertFalse(self.host.disconnect("demo")["connected"])
        self.assertEqual(client.close_calls, 1)
        self.assertIsNone(self.fabric.descriptor("mcp.demo.read_status"))
        self.assertNotIn(kind, self.body._external_read_handlers)
        with self.assertRaisesRegex(RuntimeError, "no longer current"):
            callback(
                BodyAction("stale-action", kind, {"query": "old"}, event_id="evt-stale"),
                "started",
            )
        self.assertEqual(client.start_calls, 1)
        self.assertFalse(client.running)
        self.assertEqual(self.host.disconnect("demo")["action_ids"], [])

    def test_reconnect_gets_fresh_session_without_resurrecting_old_one(self):
        self.host.connect("demo")
        previous = self.factory.created[0]
        self.host.disconnect("demo")
        new_status = self.host.connect("demo")
        self.assertTrue(new_status["connected"])
        self.assertEqual(len(self.factory.created), 2)
        self.assertFalse(previous.running)
        self.assertTrue(self.factory.created[1].running)
        self.assertEqual(self.factory.created[1].start_calls, 1)

    def test_modified_pinned_binary_never_starts(self):
        Path(self.approval.command.argv[0]).write_bytes(b"tampered")
        with self.assertRaisesRegex(RuntimeError, "integrity changed"):
            self.host.connect("demo")
        self.assertEqual(self.factory.created, [])
        self.assertEqual(self.fabric.descriptors(), ())

    def test_wrong_server_version_rejects_and_closes_child(self):
        self.factory.version = "8.0.0"
        with self.assertRaisesRegex(RuntimeError, "admission failed"):
            self.host.connect("demo")
        self.assertEqual(self.factory.created[0].close_calls, 1)
        self.assertNotIn("8.0.0", json.dumps(self.host.catalog()))
        self.assertIsNone(self.fabric.descriptor("mcp.demo.read_status"))

    def test_non_read_only_tool_never_enters_body(self):
        self.factory.read_only = False
        with self.assertRaisesRegex(RuntimeError, "admission failed"):
            self.host.connect("demo")
        self.assertEqual(self.factory.created[0].close_calls, 1)
        self.assertEqual(self.fabric.descriptors(), ())

    def test_partial_start_failure_also_closes_child_and_scrubs_provider_error(self):
        self.factory.fail_start = True
        with self.assertRaisesRegex(RuntimeError, "^approved MCP admission failed: RuntimeError$") as caught:
            self.host.connect("demo")
        self.assertNotIn("private startup stderr", str(caught.exception))
        self.assertEqual(self.factory.created[0].close_calls, 1)

    def test_shutdown_prevents_reactivation_and_clears_body(self):
        self.host.connect("demo")
        client = self.factory.created[0]
        self.host.close()
        self.host.close()
        self.assertFalse(client.running)
        self.assertEqual(client.close_calls, 1)
        self.assertEqual(self.fabric.descriptors(), ())
        with self.assertRaisesRegex(RuntimeError, "shut down"):
            self.host.connect("demo")

    def test_disallow_shell_inline_code_and_unpinned_interpreter(self):
        pin = self.approval.pinned_files[0]
        for argv in (
            ("cmd.exe", "/c", "anything"),
            ("/bin/sh", "-c", "echo 1"),
        ):
            with self.subTest(argv=argv):
                with self.assertRaises(ValueError):
                    ApprovedMcpReadProvider(
                        provider_id="demo",
                        expected_server_name="test",
                        expected_server_version="1",
                        approved_tool_names=("read_status",),
                        command=StdioMcpCommand(argv=argv, cwd=self.root, env={}),
                        pinned_files=(pin,),
                    )
        python_exe = self.root / "python.exe"
        python_exe.write_bytes(b"dummy interpreter")
        script = self.root / "server.py"
        script.write_text("print('mcp')", encoding="utf-8")
        python_pin = PinnedMcpFile(python_exe, hashlib.sha256(python_exe.read_bytes()).hexdigest())
        script_pin = PinnedMcpFile(script, hashlib.sha256(script.read_bytes()).hexdigest())
        with self.assertRaisesRegex(ValueError, "pinned script"):
            ApprovedMcpReadProvider(
                "demo", "test", "1", ("read_status",),
                StdioMcpCommand((str(python_exe), str(script)), self.root, {}),
                (python_pin,),
            )
        valid = ApprovedMcpReadProvider(
            "demo", "test", "1", ("read_status",),
            StdioMcpCommand((str(python_exe), str(script)), self.root, {}),
            (python_pin, script_pin),
        )
        self.assertEqual(len(valid.pinned_files), 2)
        with self.assertRaisesRegex(ValueError, "inline/module"):
            ApprovedMcpReadProvider(
                "demo", "test", "1", ("read_status",),
                StdioMcpCommand(
                    (str(python_exe), "-c", "print('evil')", str(script)),
                    self.root, {},
                ),
                (python_pin, script_pin),
            )

    def test_disconnection_waits_for_inflight_read_and_cannot_relaunch_child(self):
        self.host.connect("demo")
        client = self.factory.created[0]
        entered = threading.Event()
        release = threading.Event()
        returned = []
        client.on_call = lambda: (entered.set(), release.wait(5))
        runtime = ActionExecutionRuntime(self.fabric, self.body)
        caller = threading.Thread(
            target=lambda: returned.append(runtime.execute(
                ActionRequest("mcp.demo.read_status", {"query": "live"}, event_id="evt-lock")
            )),
            daemon=True,
        )
        caller.start()
        self.assertTrue(entered.wait(3))
        stopped = threading.Event()
        closer = threading.Thread(
            target=lambda: (self.host.disconnect("demo"), stopped.set()),
            daemon=True,
        )
        closer.start()
        self.assertFalse(stopped.wait(0.05))
        release.set()
        caller.join(timeout=5)
        closer.join(timeout=5)
        self.assertFalse(caller.is_alive())
        self.assertFalse(closer.is_alive())
        self.assertTrue(stopped.is_set())
        self.assertTrue(returned[0].success, returned[0].error)
        self.assertEqual(client.start_calls, 1)
        self.assertEqual(client.close_calls, 1)


class _ThinkingWorker:
    def __init__(self, factory):
        self.factory = factory

    def run(self, goal, kernel_context):
        raw = goal.metadata.get("cognition_request")
        ctx = raw.get("context") if isinstance(raw, dict) else {}
        loop = ctx.get("generic_action_loop") if isinstance(ctx, dict) else {}
        self.factory.catalogs.append(loop)
        history = loop.get("recent_verified_executions", [])
        if not history:
            if "mcp.demo.read_status" not in [
                x["action_id"] for x in loop.get("available_actions", [])
            ]:
                raise AssertionError("approved MCP tool was invisible to model")
            answer = (
                '{"zn_action_proposal":{"action_id":"mcp.demo.read_status",'
                '"arguments":{"query":"status"}}}'
            )
        else:
            last = history[-1]
            self.factory.verified = last
            answer = (
                '{"zn_action_completion":{"execution_ids":["'
                + last["execution_id"] + '"],"response":"verified plugin observation"}}'
            )
        return WorkerResult(
            success=True,
            response=answer,
            verification_passed=True,
            metrics={"model_invoked": True},
        )


class _ThinkingFactory:
    def __init__(self):
        self.catalogs = []
        self.verified = None

    def create(self, route):
        return _ThinkingWorker(self)


class McpReadCapabilityProductTests(unittest.TestCase):
    def test_approved_provider_connect_then_desktop_work_then_shutdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            approval = _approved(root)
            thinking = _ThinkingFactory()
            kernel = ZNKernelRuntime(
                store=KernelStore(root / "kernel.db"),
                routes=[ModelRoute("primary", "test", "model", {"general": 0.9})],
                worker_factory=thinking,
            )
            resident = ProductResearchInformationResidentRuntime(kernel=kernel)
            clients = _Factory()
            server = ResidentRpcServer(
                resident=resident,
                input_stream=io.StringIO(),
                output_stream=io.StringIO(),
                mcp_approvals=(approval,),
                mcp_client_factory=clients,
            )
            try:
                def call(method, **params):
                    return server.handle({"id": "rpc", "method": method, "params": params})["result"]

                self.assertFalse(call("mcp_capabilities")[0]["connected"])
                for params in (
                    {"provider_id": "unreviewed"},
                    {"provider_id": "demo", "command": "powershell"},
                    {"provider_id": "demo", "env": {"TOKEN": "stolen"}},
                ):
                    with self.subTest(params=params), self.assertRaises(ValueError):
                        call("mcp_connect", **params)
                self.assertEqual(len(clients.created), 0)
                self.assertTrue(call("mcp_connect", provider_id="demo")["connected"])
                self.assertEqual(len(clients.created), 1)

                thread = server.work.create_thread(title="MCP Body work")
                started = call(
                    "work_start",
                    thread_id=thread.thread_id,
                    task="read the current approved plugin status",
                    kind="desktop_user_event",
                    payload={"agent_loop": True},
                )
                event_id = started["progress"]["event_id"]
                for _ in range(25):
                    if resident.result_for(event_id) is not None:
                        break
                    resident.live_once()
                run = resident.result_for(event_id)
                self.assertIsNotNone(run)
                self.assertTrue(run.success, run.reason)
                self.assertEqual(run.response, "verified plugin observation")
                self.assertEqual(run.model_invocations, 2)
                self.assertEqual(clients.created[0].calls, [("read_status", {"query": "status"})])
                self.assertTrue(thinking.verified["verified"])
                self.assertEqual(thinking.verified["action_id"], "mcp.demo.read_status")
                self.assertTrue(call("work_progress", thread_id=thread.thread_id, event_id=event_id)["progress"]["finalized"])
                self.assertTrue(call("shutdown")["shutting_down"])
                self.assertFalse(clients.created[0].running)
                self.assertIsNone(resident.action_fabric.descriptor("mcp.demo.read_status"))
                with self.assertRaisesRegex(RuntimeError, "shut down"):
                    call("mcp_connect", provider_id="demo")
            finally:
                server.mcp_capabilities.close()
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
