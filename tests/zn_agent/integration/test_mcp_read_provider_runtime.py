from __future__ import annotations

"""Real official MCP stdio subprocess -> ZN Body -> clean shutdown proof.

The managed-browser Windows CI lane installs the existing pinned mcp==2.2.0
extra. Nothing is installed/downloaded dynamically by ZN or this test.
"""

import hashlib
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core import KernelStore
from zn_agent.core.action_execution import ActionExecutionRuntime, ActionRequest
from zn_agent.core.action_fabric import ActionFabricRegistry
from zn_agent.core.body import NativeBody
from zn_agent.core.mcp_read_capability_host import (
    ApprovedMcpReadProvider,
    McpReadCapabilityHost,
    PinnedMcpFile,
)
from zn_agent.core.stdio_mcp import StdioMcpCommand


@unittest.skipUnless(importlib.util.find_spec("mcp") is not None, "requires pinned MCP browser extra")
class RealMcpReadProviderContract(unittest.TestCase):
    def test_pinned_stdio_provider_is_a_real_body_capability_and_stops(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = Path(__file__).with_name("mcp_read_server_fixture.py")
            server_script = root / "approved_server.py"
            shutil.copyfile(fixture, server_script)
            executable = Path(sys.executable).resolve()
            script_hash = hashlib.sha256(server_script.read_bytes()).hexdigest()
            with executable.open("rb") as stream:
                executable_hash = hashlib.file_digest(stream, "sha256").hexdigest()
            names = {
                "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LOCALAPPDATA",
                "APPDATA", "VIRTUAL_ENV", "PYTHONUTF8",
            }
            environment = {name: value for name, value in os.environ.items() if name.upper() in names}
            environment["PYTHONUNBUFFERED"] = "1"
            approval = ApprovedMcpReadProvider(
                provider_id="ci_stdio",
                expected_server_name="approved-test-server",
                expected_server_version="1.0.2",
                approved_tool_names=("read_status",),
                command=StdioMcpCommand(
                    argv=(str(executable), str(server_script)),
                    cwd=root,
                    env=environment,
                ),
                pinned_files=(
                    PinnedMcpFile(executable, executable_hash),
                    PinnedMcpFile(server_script, script_hash),
                ),
                timeout_seconds=20.0,
            )
            store = KernelStore(root / "zn-kernel.db")
            body = NativeBody(store=store)
            fabric = ActionFabricRegistry()
            host = McpReadCapabilityHost(
                SimpleNamespace(action_fabric=fabric, body=body),
                approvals=(approval,),
            )
            try:
                self.assertFalse(host.catalog()[0]["connected"])
                connected = host.connect("ci_stdio")
                self.assertTrue(connected["connected"], connected)
                self.assertEqual(connected["action_ids"], ["mcp.ci_stdio.read_status"])
                runtime = ActionExecutionRuntime(fabric, body)
                execution = runtime.execute(ActionRequest(
                    "mcp.ci_stdio.read_status",
                    {"query": "actual-child"},
                    event_id="real-ci-work",
                ))
                self.assertTrue(execution.success, execution.error)
                self.assertIn(
                    "real-mcp-status:actual-child",
                    execution.observations[0].data["text"],
                )
                self.assertTrue(execution.observations[0].data["untrusted_external_evidence"])
                self.assertFalse(host.disconnect("ci_stdio")["connected"])
                self.assertEqual(fabric.descriptors(), ())
                self.assertEqual(body._external_read_handlers, {})
                # The canonical Action Fabric rejects unknown/uninstalled
                # actions before they can enter Body (KeyError contract).
                with self.assertRaises(KeyError):
                    runtime.execute(ActionRequest(
                        "mcp.ci_stdio.read_status",
                        {"query": "not-allowed-after-stop"},
                        event_id="real-ci-later",
                    ))
                self.assertTrue(host.connect("ci_stdio")["connected"])
            finally:
                host.close()
                store.close()
            self.assertEqual(body._external_read_handlers, {})
            self.assertEqual(fabric.descriptors(), ())
            with self.assertRaisesRegex(RuntimeError, "shut down"):
                host.connect("ci_stdio")


if __name__ == "__main__":
    unittest.main()
