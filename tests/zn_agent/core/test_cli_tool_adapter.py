from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from zn_agent.core import KernelStore
from zn_agent.core.action_execution import ActionExecutionRuntime, ActionRequest
from zn_agent.core.action_fabric import ActionFabricRegistry
from zn_agent.core.body import NativeBody
from zn_agent.core.cli_tool_adapter import (
    ApprovedCliWriteTool,
    CliOutputSpec,
    CliRunResult,
    CliToolDeclaration,
    attach_cli_tools,
    example_git_version_tool,
)
from zn_agent.core.mcp_capability_adapter import McpWritePostcondition


def _echo_tool(**overrides):
    options = {
        "name": "echo_message",
        "description": "Echo one message back to stdout",
        "command": sys.executable,
        "argv_template": ("-c", "import sys; print(sys.argv[1])", "{message}"),
        "params": {"message": {"type": "string", "required": True}},
    }
    options.update(overrides)
    return CliToolDeclaration(**options)


def _attach(fabric, body, tools, **overrides):
    options = {
        "fabric": fabric,
        "body": body,
        "tools": tools,
        "provider_id": "demo",
    }
    options.update(overrides)
    return attach_cli_tools(**options)


def _approval(tool_name, **overrides):
    options = {
        "tool_name": tool_name,
        "effect_class": "reversible_side_effect",
        "approval_kind": "send",
        "verification": ("file contains content",),
    }
    options.update(overrides)
    return ApprovedCliWriteTool(**options)


def _append_tool(target: Path) -> CliToolDeclaration:
    return CliToolDeclaration(
        name="append_note",
        description="Append one note line to a file",
        command=sys.executable,
        argv_template=(
            "-c",
            "import sys; open(sys.argv[1], 'a').write(sys.argv[2] + chr(10))",
            "{path}",
            "{content}",
        ),
        params={
            "path": {"type": "string", "required": True},
            "content": {"type": "string", "required": True},
        },
        effect_class="reversible_side_effect",
    )


def _file_probe(target: Path):
    def check(args, result):
        ok = str(args.get("content") or "") in target.read_text()
        return McpWritePostcondition(
            ok,
            "file contains content" if ok else "file missing content",
            {"path": str(target)},
        )

    return check


class CliToolAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fabric = ActionFabricRegistry()
        self.body = NativeBody(store=KernelStore(Path(self.tmp.name) / "kernel.db"))

    def tearDown(self):
        self.body.store.close()
        self.tmp.cleanup()

    def _execute(self, runtime, action_id, args, *, event_id="evt-1"):
        return runtime.execute(ActionRequest(action_id, args, event_id=event_id))

    def test_read_tool_registers_and_executes_real_process(self):
        attachment = _attach(self.fabric, self.body, (_echo_tool(),))
        try:
            descriptor = self.fabric.descriptor("cli.demo.echo_message")
            self.assertIsNotNone(descriptor)
            self.assertEqual(descriptor.effect_class, "read_only")
            self.assertEqual(descriptor.replay_semantics, "read_only")
            self.assertIn("cli", descriptor.tags)
            self.assertIn(
                "explicit_cli_tool_approval", descriptor.required_authority
            )
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            outcome = self._execute(
                runtime, "cli.demo.echo_message", {"message": "hello cli"}
            )
            self.assertTrue(outcome.success, outcome.error)
            self.assertEqual(outcome.body_result.output.strip(), "hello cli")
            self.assertEqual(outcome.body_result.data["exit_code"], 0)
            self.assertTrue(
                outcome.body_result.data["untrusted_external_evidence"]
            )
        finally:
            attachment.detach()

    def test_example_git_version_tool_is_retrievable_and_runs(self):
        tool = example_git_version_tool()
        self.assertEqual(tool.effect_class, "read_only")
        self.assertEqual(tool.command, "git")
        attachment = _attach(self.fabric, self.body, (tool,))
        try:
            relevant = self.fabric.relevant_actions(task="git version")
            self.assertIn(
                "cli.demo.git_version", [item.action_id for item in relevant]
            )
            if shutil.which("git") is None:
                self.skipTest("git not on PATH in this environment")
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            outcome = self._execute(runtime, "cli.demo.git_version", {})
            self.assertTrue(outcome.success, outcome.error)
            self.assertIn("version", outcome.body_result.data["parsed"])
        finally:
            attachment.detach()

    def test_unrelated_task_does_not_retrieve_cli_tools(self):
        attachment = _attach(
            self.fabric, self.body, (_echo_tool(), example_git_version_tool())
        )
        try:
            relevant = self.fabric.relevant_actions(task="set screen brightness")
            self.assertNotIn(
                "cli.demo.echo_message", [item.action_id for item in relevant]
            )
            self.assertNotIn(
                "cli.demo.git_version", [item.action_id for item in relevant]
            )
        finally:
            attachment.detach()

    def test_json_lines_and_regex_output_parsing(self):
        json_tool = CliToolDeclaration(
            name="show_json",
            description="Print one JSON object",
            command=sys.executable,
            argv_template=(
                "-c",
                "import json, sys; print(json.dumps({'value': sys.argv[1]}))",
                "{message}",
            ),
            params={"message": {"type": "string", "required": True}},
            output=CliOutputSpec(mode="json"),
        )
        lines_tool = CliToolDeclaration(
            name="show_lines",
            description="Print three lines",
            command=sys.executable,
            argv_template=(
                "-c",
                "print('one'); print('two'); print('three')",
            ),
            output=CliOutputSpec(mode="lines"),
        )
        regex_tool = CliToolDeclaration(
            name="show_code",
            description="Print a code",
            command=sys.executable,
            argv_template=("-c", "print('CODE-1234')"),
            output=CliOutputSpec(mode="regex", pattern=r"CODE-(?P<code>\d+)"),
        )
        attachment = _attach(
            self.fabric, self.body, (json_tool, lines_tool, regex_tool)
        )
        try:
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            json_outcome = self._execute(
                runtime, "cli.demo.show_json", {"message": "abc"}
            )
            self.assertTrue(json_outcome.success, json_outcome.error)
            self.assertEqual(
                json_outcome.body_result.data["parsed"], {"value": "abc"}
            )
            lines_outcome = self._execute(runtime, "cli.demo.show_lines", {})
            self.assertTrue(lines_outcome.success, lines_outcome.error)
            self.assertEqual(
                lines_outcome.body_result.data["parsed"],
                ["one", "two", "three"],
            )
            regex_outcome = self._execute(runtime, "cli.demo.show_code", {})
            self.assertTrue(regex_outcome.success, regex_outcome.error)
            self.assertEqual(
                regex_outcome.body_result.data["parsed"], {"code": "1234"}
            )
        finally:
            attachment.detach()

    def test_regex_output_mismatch_is_explicit_failure(self):
        tool = CliToolDeclaration(
            name="show_code",
            description="Print a code",
            command=sys.executable,
            argv_template=("-c", "print('nothing here')"),
            output=CliOutputSpec(mode="regex", pattern=r"CODE-(?P<code>\d+)"),
        )
        attachment = _attach(self.fabric, self.body, (tool,))
        try:
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            outcome = self._execute(runtime, "cli.demo.show_code", {})
            self.assertFalse(outcome.success)
            self.assertIn("did not match", outcome.error)
        finally:
            attachment.detach()

    def test_invalid_json_output_is_explicit_failure(self):
        tool = CliToolDeclaration(
            name="show_json",
            description="Print non-JSON",
            command=sys.executable,
            argv_template=("-c", "print('not json')"),
            output=CliOutputSpec(mode="json"),
        )
        attachment = _attach(self.fabric, self.body, (tool,))
        try:
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            outcome = self._execute(runtime, "cli.demo.show_json", {})
            self.assertFalse(outcome.success)
            self.assertIn("not valid JSON", outcome.error)
        finally:
            attachment.detach()

    def test_argument_validation_blocks_execution(self):
        seen: list[list[str]] = []

        class _RecordingRunner:
            def run(self, argv, *, timeout_seconds, working_dir, env):
                seen.append(list(argv))
                return CliRunResult(0, b"ok", b"")

        tool = CliToolDeclaration(
            name="echo_message",
            description="Echo one message",
            command=sys.executable,
            argv_template=("-c", "import sys; print(sys.argv[1])", "{message}"),
            params={
                "message": {"type": "string", "required": True},
                "count": {"type": "integer", "required": False, "default": 1},
                "mode": {
                    "type": "string",
                    "required": False,
                    "enum": ["fast", "slow"],
                    "default": "fast",
                },
            },
        )
        attachment = _attach(
            self.fabric, self.body, (tool,), runner=_RecordingRunner()
        )
        try:
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            for bad_args in (
                {"message": "hi", "surprise": 1},
                {"count": 2},
                {"message": 7},
                {"message": "hi", "mode": "warp"},
            ):
                outcome = self._execute(runtime, "cli.demo.echo_message", bad_args)
                self.assertFalse(outcome.success, bad_args)
            # Option-like values are refused by the CLI handler itself.
            outcome = self._execute(
                runtime, "cli.demo.echo_message", {"message": "--help"}
            )
            self.assertFalse(outcome.success)
            self.assertIn("looks like an option", outcome.error)
            self.assertEqual(seen, [])
            # Defaults fill in, and the declared default reaches argv.
            outcome = self._execute(
                runtime, "cli.demo.echo_message", {"message": "hi"}
            )
            self.assertTrue(outcome.success, outcome.error)
            self.assertEqual(seen, [[sys.executable, "-c", "import sys; print(sys.argv[1])", "hi"]])
        finally:
            attachment.detach()

    def test_option_like_values_allowed_when_declared(self):
        tool = _echo_tool(allow_option_like_values=True)
        attachment = _attach(self.fabric, self.body, (tool,))
        try:
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            outcome = self._execute(
                runtime, "cli.demo.echo_message", {"message": "--help"}
            )
            self.assertTrue(outcome.success, outcome.error)
            self.assertEqual(outcome.body_result.output.strip(), "--help")
        finally:
            attachment.detach()

    def test_nonzero_exit_is_explicit_failure_with_stderr(self):
        tool = CliToolDeclaration(
            name="failer",
            description="Exit non-zero with stderr",
            command=sys.executable,
            argv_template=(
                "-c",
                "import sys; sys.stderr.write('boom detail'); sys.exit(3)",
            ),
        )
        attachment = _attach(self.fabric, self.body, (tool,))
        try:
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            outcome = self._execute(runtime, "cli.demo.failer", {})
            self.assertFalse(outcome.success)
            self.assertIn("exited with 3", outcome.error)
            self.assertIn("boom detail", outcome.error)
        finally:
            attachment.detach()

    def test_timeout_is_explicit_failure(self):
        tool = CliToolDeclaration(
            name="sleeper",
            description="Sleep longer than its timeout",
            command=sys.executable,
            argv_template=("-c", "import time; time.sleep(30)"),
            timeout_seconds=1.0,
        )
        attachment = _attach(self.fabric, self.body, (tool,))
        try:
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            outcome = self._execute(runtime, "cli.demo.sleeper", {})
            self.assertFalse(outcome.success)
            self.assertIn("timed out", outcome.error)
        finally:
            attachment.detach()

    def test_missing_executable_is_explicit_failure(self):
        tool = CliToolDeclaration(
            name="ghost",
            description="A tool whose executable does not exist",
            command="zn-definitely-missing-tool-xyz",
        )
        attachment = _attach(self.fabric, self.body, (tool,))
        try:
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            outcome = self._execute(runtime, "cli.demo.ghost", {})
            self.assertFalse(outcome.success)
            # The availability probe gates dispatch before any spawn.
            self.assertIn("not on PATH", outcome.error)
        finally:
            attachment.detach()

    def test_spawn_failure_after_probe_is_explicit_failure(self):
        class _VanishingRunner:
            def run(self, argv, *, timeout_seconds, working_dir, env):
                raise FileNotFoundError("executable vanished mid-flight")

        attachment = _attach(
            self.fabric, self.body, (_echo_tool(),), runner=_VanishingRunner()
        )
        try:
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            outcome = self._execute(
                runtime, "cli.demo.echo_message", {"message": "hi"}
            )
            self.assertFalse(outcome.success)
            self.assertIn("executable not found", outcome.error)
        finally:
            attachment.detach()

    def test_working_dir_and_env_reach_the_process(self):
        workdir = Path(self.tmp.name) / "work"
        workdir.mkdir()
        tool = CliToolDeclaration(
            name="show_context",
            description="Print cwd and one env marker",
            command=sys.executable,
            argv_template=(
                "-c",
                "import os; print(os.getcwd()); print(os.environ.get('ZN_TEST_MARKER', ''))",
            ),
            working_dir=str(workdir),
            env={"ZN_TEST_MARKER": "marker-yes"},
            output=CliOutputSpec(mode="lines"),
        )
        attachment = _attach(self.fabric, self.body, (tool,))
        try:
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            outcome = self._execute(runtime, "cli.demo.show_context", {})
            self.assertTrue(outcome.success, outcome.error)
            self.assertEqual(
                outcome.body_result.data["parsed"],
                [str(workdir), "marker-yes"],
            )
        finally:
            attachment.detach()

    def test_write_tools_disabled_by_default(self):
        target = Path(self.tmp.name) / "notes.txt"
        attachment = _attach(self.fabric, self.body, (_append_tool(target),))
        try:
            self.assertIsNone(self.fabric.descriptor("cli.demo.append_note"))
            self.assertEqual(attachment.disabled_write_tools, ("append_note",))
            self.assertFalse(target.exists())
        finally:
            attachment.detach()

    def test_approved_write_verifies_through_postcondition_probe(self):
        target = Path(self.tmp.name) / "notes.txt"
        attachment = _attach(
            self.fabric,
            self.body,
            (_append_tool(target),),
            approved_write_tools=(_approval("append_note"),),
            postcondition_probes={"append_note": _file_probe(target)},
        )
        try:
            descriptor = self.fabric.descriptor("cli.demo.append_note")
            self.assertIsNotNone(descriptor)
            self.assertEqual(descriptor.effect_class, "reversible_side_effect")
            self.assertEqual(descriptor.replay_semantics, "verify_before_replay")
            self.assertIn("approval:send", descriptor.tags)
            self.assertIn("cli_write", descriptor.tags)
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            attachment.register_verifications(runtime)
            outcome = self._execute(
                runtime,
                "cli.demo.append_note",
                {"path": str(target), "content": "first line"},
            )
            self.assertTrue(outcome.success, outcome.error)
            self.assertEqual(outcome.verification.status, "verified")
            self.assertEqual(target.read_text(), "first line\n")
        finally:
            attachment.detach()

    def test_write_replay_refused_without_redispatch(self):
        target = Path(self.tmp.name) / "notes.txt"
        attachment = _attach(
            self.fabric,
            self.body,
            (_append_tool(target),),
            approved_write_tools=(_approval("append_note"),),
            postcondition_probes={"append_note": _file_probe(target)},
        )
        try:
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            attachment.register_verifications(runtime)
            args = {"path": str(target), "content": "once"}
            self.assertTrue(
                self._execute(runtime, "cli.demo.append_note", args).success
            )
            second = self._execute(runtime, "cli.demo.append_note", args)
            self.assertFalse(second.success)
            self.assertIn("replay refused", second.error)
            self.assertEqual(target.read_text(), "once\n")
        finally:
            attachment.detach()

    def test_write_without_verifier_fails_closed_after_dispatch(self):
        target = Path(self.tmp.name) / "notes.txt"
        attachment = _attach(
            self.fabric,
            self.body,
            (_append_tool(target),),
            approved_write_tools=(_approval("append_note"),),
            postcondition_probes={"append_note": _file_probe(target)},
        )
        try:
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            # Deliberately NOT calling register_verifications.
            outcome = self._execute(
                runtime,
                "cli.demo.append_note",
                {"path": str(target), "content": "dispatched"},
            )
            self.assertFalse(outcome.success)
            self.assertIn("no independent postcondition verifier", outcome.error)
            self.assertEqual(target.read_text(), "dispatched\n")
        finally:
            attachment.detach()

    def test_postcondition_failure_reports_failed(self):
        target = Path(self.tmp.name) / "notes.txt"
        attachment = _attach(
            self.fabric,
            self.body,
            (_append_tool(target),),
            approved_write_tools=(_approval("append_note"),),
            postcondition_probes={
                "append_note": lambda args, result: McpWritePostcondition(
                    False, "postcondition probe saw no effect"
                )
            },
        )
        try:
            runtime = ActionExecutionRuntime(self.fabric, self.body)
            attachment.register_verifications(runtime)
            outcome = self._execute(
                runtime,
                "cli.demo.append_note",
                {"path": str(target), "content": "written"},
            )
            self.assertFalse(outcome.success)
            self.assertEqual(outcome.verification.status, "failed")
            self.assertIn("no effect", outcome.error)
        finally:
            attachment.detach()

    def test_approval_probe_mismatch_refused(self):
        target = Path(self.tmp.name) / "notes.txt"
        with self.assertRaisesRegex(ValueError, "postcondition probe"):
            _attach(
                self.fabric,
                self.body,
                (_append_tool(target),),
                approved_write_tools=(_approval("append_note"),),
                postcondition_probes={},
            )
        with self.assertRaisesRegex(ValueError, "postcondition probe"):
            _attach(
                self.fabric,
                self.body,
                (_append_tool(target),),
                approved_write_tools=(),
                postcondition_probes={"append_note": _file_probe(target)},
            )

    def test_illegal_declarations_rejected(self):
        def declare(**overrides):
            base = {
                "name": "tool",
                "description": "A tool",
                "command": sys.executable,
            }
            base.update(overrides)
            return CliToolDeclaration(**base)

        cases = {
            "shell metachar in command": {"command": "git; rm -rf /"},
            "relative path command": {"command": "bin/git"},
            "bad tool name": {"name": "1tool"},
            "empty description": {"description": "  "},
            "unknown placeholder param": {
                "argv_template": ("{nope}",),
            },
            "bad param type": {
                "params": {"message": {"type": "object"}},
            },
            "required with default": {
                "params": {
                    "message": {
                        "type": "string",
                        "required": True,
                        "default": "hi",
                    }
                },
            },
            "enum default outside enum": {
                "params": {
                    "mode": {
                        "type": "string",
                        "enum": ["a"],
                        "default": "b",
                    }
                },
            },
            "timeout too small": {"timeout_seconds": 0.5},
            "timeout too large": {"timeout_seconds": 61.0},
            "secret env name": {"env": {"MY_API_TOKEN": "x"}},
            "relative working_dir": {"working_dir": "relative/path"},
            "bad exit code": {"expected_exit_codes": (256,)},
        }
        for label, overrides in cases.items():
            with self.subTest(label=label), self.assertRaises(ValueError):
                declare(**overrides)
        # A declared-but-unreferenced param is allowed (params are validated
        # even when unused); only a placeholder naming an undeclared param fails.
        declare(
            params={"message": {"type": "string"}},
            argv_template=("fixed",),
        )
        # Output-spec errors surface when the spec itself is built.
        with self.assertRaises(ValueError):
            CliOutputSpec(mode="regex")
        with self.assertRaises(ValueError):
            CliOutputSpec(mode="text", pattern="x")
        with self.assertRaises(ValueError):
            CliOutputSpec(mode="yaml")

    def test_attach_rejects_bad_provider_and_missing_working_dir(self):
        with self.assertRaisesRegex(ValueError, "provider_id"):
            _attach(self.fabric, self.body, (_echo_tool(),), provider_id="Bad ID")
        missing = Path(self.tmp.name) / "no-such-dir"
        tool = _echo_tool(working_dir=str(missing))
        with self.assertRaisesRegex(ValueError, "working_dir"):
            _attach(self.fabric, self.body, (tool,))

    def test_audit_history_redacts_cli_arguments(self):
        attachment = _attach(self.fabric, self.body, (_echo_tool(),))
        try:
            descriptor = self.fabric.descriptor("cli.demo.echo_message")
            assert descriptor is not None and descriptor.body_action_kind
            result = self.body.act(
                descriptor.body_action_kind,
                event_id="evt-redact",
                message="super-secret-value",
            )
            self.assertTrue(result.success, result.error)
            recent = self.body.recent_actions(1)
            self.assertEqual(len(recent), 1)
            self.assertTrue(recent[0].data["external_read_redacted"])
            self.assertNotIn("super-secret-value", str(recent[0].data))
        finally:
            attachment.detach()

    def test_detach_unregisters(self):
        attachment = _attach(self.fabric, self.body, (_echo_tool(),))
        self.assertIsNotNone(self.fabric.descriptor("cli.demo.echo_message"))
        attachment.detach()
        self.assertIsNone(self.fabric.descriptor("cli.demo.echo_message"))
        attachment.detach()  # Idempotent.


if __name__ == "__main__":
    unittest.main()
