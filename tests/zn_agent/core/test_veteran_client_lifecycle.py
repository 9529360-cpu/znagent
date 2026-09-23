from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core import veteran_engineering as veteran


# Real child processes and real protocol pipes, with deterministic startup
# faults instead of a live coding model or a timing-sensitive external service.
_CHILD = r'''
import json
import os
import sys
import time
from pathlib import Path
mode, trace_path, tools_json = sys.argv[1:]
tools = json.loads(tools_json)
for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    with Path(trace_path).open("a", encoding="utf-8") as trace:
        trace.write(json.dumps({"pid": os.getpid(), "method": method}) + "\n")
    if mode == "hang_initialize" and method == "initialize":
        time.sleep(60)
    if mode == "hang_tools" and method == "tools/list":
        time.sleep(60)
    if mode == "malformed" and method == "initialize":
        print("not-json", flush=True)
        continue
    if method == "initialize":
        result = {"protocolVersion": "2025-11-25", "serverInfo": {"name": "veteran-engineer"}}
    elif method == "tools/list":
        result = {"tools": [{"name": name} for name in tools]}
    else:
        result = {"structuredContent": {"pid": os.getpid(), "ok": True}}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
'''


class VeteranClientLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.script = self.root / "protocol_child.py"
        self.script.write_text(_CHILD, encoding="utf-8")
        self.trace = self.root / "requests.jsonl"
        self.processes = []
        original_popen = subprocess.Popen

        def spawn(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            self.processes.append(process)
            return process

        self.spawn_patch = patch.object(veteran.subprocess, "Popen", side_effect=spawn)
        self.spawn_patch.start()
        self.addCleanup(self.spawn_patch.stop)
        # Operator discovery is outside this protocol/lifecycle contract. No
        # installed worker, credential, network, or user configuration is used.
        self.policy_patch = patch.object(veteran, "ensure_veteran_operator_policy", return_value=None)
        self.policy_patch.start()
        self.addCleanup(self.policy_patch.stop)
        self.addCleanup(self._cleanup_children)

    def _cleanup_children(self) -> None:
        # Also clean up when checking the pre-fix regression deliberately fails.
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()

    def client(self, mode: str = "normal", *, timeout: float = 10.0):
        client = veteran.VeteranMcpClient(
            state_root=self.root / "state",
            command=veteran.VeteranRuntimeCommand(
                argv=(sys.executable, "-I", "-u", str(self.script), mode,
                      str(self.trace), json.dumps(sorted(veteran.VETERAN_ALLOWED_TOOLS))),
                env={}, runtime_root=self.root,
            ),
            timeout_seconds=timeout,
        )
        self.addCleanup(client.close)
        return client

    def assert_retired(self, client) -> None:
        self.assertFalse(client.running)
        self.assertIsNone(client._process)
        self.assertEqual(client.tool_names, frozenset())
        self.assertTrue(self.processes)
        for process in self.processes:
            self.assertIsNotNone(process.poll(), "failed startup must reap its real child")
            self.assertTrue(all(stream.closed for stream in (process.stdin, process.stdout, process.stderr)))

    def test_initialize_timeout_reaps_child_when_context_entry_fails(self) -> None:
        client = self.client("hang_initialize", timeout=2.0)
        with self.assertRaisesRegex(veteran.VeteranSidecarError, "timed out waiting for initialize"):
            with client:
                self.fail("failed context entry must not run its body")
        self.assert_retired(client)
        client.close()

    def test_tool_discovery_timeout_reaps_initialized_child(self) -> None:
        client = self.client("hang_tools", timeout=2.0)
        with self.assertRaisesRegex(veteran.VeteranSidecarError, "timed out waiting for tools/list"):
            client.start()
        self.assert_retired(client)
        requests = [json.loads(line)["method"] for line in self.trace.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(requests, ["initialize", "tools/list"])

    def test_malformed_handshake_does_not_leave_half_started_client(self) -> None:
        client = self.client("malformed")
        with self.assertRaisesRegex(veteran.VeteranSidecarError, "invalid JSON"):
            client.start()
        self.assert_retired(client)

    def test_interrupted_handshake_still_reaps_child(self) -> None:
        client = self.client()
        with patch.object(client, "_request_raw", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                client.start()
        self.assert_retired(client)

    def test_closed_client_restarts_with_generation_isolated_responses(self) -> None:
        client = self.client()
        first = client.start().call_tool("runtime_health")
        old_queue = client._stdout_queue
        client.close()
        self.assert_retired(client)
        client.start()
        self.assertIsNot(client._stdout_queue, old_queue)
        # A late prior-reader EOF or response cannot affect the new child.
        old_queue.put(None)
        old_queue.put('{"id":999,"result":{}}')
        second = client.call_tool("runtime_health")
        self.assertNotEqual(first["pid"], second["pid"])
        self.assertTrue(second["ok"])
        client.close()
        self.assert_retired(client)

    def test_recovery_after_failed_start_is_explicit_and_does_not_replay_tools(self) -> None:
        client = self.client("malformed")
        with self.assertRaises(veteran.VeteranSidecarError):
            client.call_tool("mission_execute", {"missionId": "must-not-be-dispatched"})
        self.assert_retired(client)
        client.command = self.client().command
        self.assertTrue(client.start().call_tool("runtime_health")["ok"])
        requests = [json.loads(line)["method"] for line in self.trace.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(requests, ["initialize", "initialize", "tools/list", "tools/call"])
        self.assertEqual(len(self.processes), 2, "no automatic startup or tool retry")


if __name__ == "__main__":
    unittest.main()
