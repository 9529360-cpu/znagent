from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from zn_agent.core.action_execution import ActionExecutionRuntime
from zn_agent.core.action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionFabricRegistry,
)
from zn_agent.core.body import BodyActionResult, NativeBody
from zn_agent.core.models import AgentEvent, ExecutionPath
from zn_agent.core.permission_model import PermissionPolicy
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.terminal_loop import (
    TerminalPermissionContext,
    check_terminal_permission,
    execute_terminal_loop_step,
    parse_terminal_permission,
    terminal_loop_catalog,
    terminal_loop_spec,
    validate_terminal_loop_arguments,
)


def _permission(**overrides):
    values = {
        "allow_terminal": True,
        "allowed_workdirs": ("/tmp",),
    }
    values.update(overrides)
    return TerminalPermissionContext(**values)


def _body_result(*, success, output="", error=None, data=None):
    return BodyActionResult(
        action_id="body-terminal-1",
        kind="command",
        success=success,
        output=output,
        data=dict(data or {}),
        error=error,
        event_id="evt-terminal",
    )


class _FakeBody:
    """Stands in for NativeBody; returns canned results per command."""

    def __init__(self, handler=None):
        self.calls = []
        self._handler = handler or self._default_handler

    def _default_handler(self, command, kwargs):
        if command.startswith("echo "):
            return _body_result(
                success=True,
                output=command[len("echo "):] + "\n",
                data={
                    "status": "completed",
                    "exit_code": 0,
                    "cwd": kwargs.get("workdir", "/tmp"),
                    "timed_out": False,
                },
            )
        if command.startswith("exit "):
            code = int(command.split()[1])
            return _body_result(
                success=False,
                output="out\n",
                error=f"command exited with code {code}",
                data={
                    "status": "completed",
                    "exit_code": code,
                    "cwd": kwargs.get("workdir", "/tmp"),
                    "timed_out": False,
                },
            )
        if command.startswith("sleep "):
            return _body_result(
                success=False,
                output="",
                error="command timed out",
                data={
                    "status": "timeout",
                    "exit_code": None,
                    "cwd": kwargs.get("workdir", "/tmp"),
                    "timed_out": True,
                },
            )
        return _body_result(success=False, error="fake body: unknown command")

    def act(self, kind, *, event_id=None, **kwargs):
        self.calls.append((kind, event_id, dict(kwargs)))
        assert kind == "command"
        return self._handler(str(kwargs.get("command") or ""), kwargs)


class TerminalLoopStepTests(unittest.TestCase):
    def test_completed_command_returns_real_output_as_verified_evidence(self):
        body = _FakeBody()
        result = execute_terminal_loop_step(
            body,
            permission=_permission(),
            action_id="terminal.run",
            arguments={"command": "echo hello-m6", "workdir": "/tmp"},
            event_id="evt-1",
        )
        self.assertTrue(result.execution.success)
        self.assertEqual(result.execution.status, "verified")
        observation = result.execution.observations[0]
        self.assertEqual(observation.data["output"], "hello-m6\n")
        self.assertEqual(observation.data["exit_code"], 0)
        self.assertEqual(observation.data["command"], "echo hello-m6")
        self.assertEqual(len(body.calls), 1)
        kind, event_id, kwargs = body.calls[0]
        self.assertEqual(kind, "command")
        self.assertEqual(event_id, "evt-1")
        self.assertEqual(kwargs["command"], "echo hello-m6")
        self.assertEqual(kwargs["workdir"], "/tmp")
        self.assertEqual(kwargs["timeout"], 60.0)

    def test_nonzero_exit_is_failed_but_carries_real_output(self):
        body = _FakeBody()
        result = execute_terminal_loop_step(
            body,
            permission=_permission(),
            action_id="terminal.run",
            arguments={"command": "exit 3", "workdir": "/tmp"},
            event_id="evt-1",
        )
        self.assertFalse(result.execution.success)
        self.assertTrue(result.completed_with_output)
        self.assertIn("exit code 3", result.execution.error)
        self.assertEqual(result.execution.observations[0].data["output"], "out\n")
        self.assertEqual(result.execution.observations[0].data["exit_code"], 3)
        # Exactly one dispatch: a failed command is never re-run.
        self.assertEqual(len(body.calls), 1)

    def test_timeout_fails_without_trustworthy_output_and_never_redispatches(self):
        body = _FakeBody()
        result = execute_terminal_loop_step(
            body,
            permission=_permission(),
            action_id="terminal.run",
            arguments={"command": "sleep 30", "workdir": "/tmp", "timeout": 5},
            event_id="evt-1",
        )
        self.assertFalse(result.execution.success)
        self.assertFalse(result.completed_with_output)
        self.assertIn("timed out", result.execution.error)
        self.assertTrue(result.execution.observations[0].data["timed_out"])
        self.assertEqual(len(body.calls), 1)

    def test_denylisted_command_is_rejected_before_execution(self):
        body = _FakeBody()
        result = execute_terminal_loop_step(
            body,
            permission=_permission(denylist=("rm -rf",)),
            action_id="terminal.run",
            arguments={"command": "rm -rf /tmp/x", "workdir": "/tmp"},
            event_id="evt-1",
        )
        self.assertFalse(result.execution.success)
        self.assertIn("denylist", result.execution.error)
        self.assertEqual(body.calls, [])

    def test_workdir_outside_permitted_roots_is_rejected_before_execution(self):
        body = _FakeBody()
        result = execute_terminal_loop_step(
            body,
            permission=_permission(),
            action_id="terminal.run",
            arguments={"command": "echo hi", "workdir": "/etc"},
            event_id="evt-1",
        )
        self.assertFalse(result.execution.success)
        self.assertIn("workdir", result.execution.error)
        self.assertEqual(body.calls, [])

    def test_timeout_over_permission_cap_is_rejected_before_execution(self):
        body = _FakeBody()
        result = execute_terminal_loop_step(
            body,
            permission=_permission(max_timeout_seconds=30),
            action_id="terminal.run",
            arguments={"command": "echo hi", "workdir": "/tmp", "timeout": 60},
            event_id="evt-1",
        )
        self.assertFalse(result.execution.success)
        self.assertIn("timeout", result.execution.error)
        self.assertEqual(body.calls, [])

    def test_permission_policy_ask_fails_with_approval_required_and_never_executes(self):
        body = _FakeBody()
        policy = PermissionPolicy(modes={"terminal_command": "always_ask"})
        result = execute_terminal_loop_step(
            body,
            permission=_permission(permission_policy=policy),
            action_id="terminal.run",
            arguments={"command": "echo hi", "workdir": "/tmp"},
            event_id="evt-1",
        )
        self.assertFalse(result.execution.success)
        self.assertTrue(result.execution.error.startswith("approval_required:"))
        self.assertEqual(body.calls, [])

    def test_permission_policy_deny_is_absolute(self):
        body = _FakeBody()
        policy = PermissionPolicy(denylist=["rm -rf"])
        result = execute_terminal_loop_step(
            body,
            permission=_permission(permission_policy=policy),
            action_id="terminal.run",
            arguments={"command": "rm -rf /tmp/x", "workdir": "/tmp"},
            event_id="evt-1",
        )
        self.assertFalse(result.execution.success)
        self.assertIn("denied", result.execution.error)
        self.assertEqual(body.calls, [])

    def test_terminal_not_allowed_is_rejected_before_execution(self):
        body = _FakeBody()
        result = execute_terminal_loop_step(
            body,
            permission=_permission(allow_terminal=False),
            action_id="terminal.run",
            arguments={"command": "echo hi", "workdir": "/tmp"},
            event_id="evt-1",
        )
        self.assertFalse(result.execution.success)
        self.assertIn("does not allow", result.execution.error)
        self.assertEqual(body.calls, [])

    def test_body_dispatch_failure_is_a_failed_step_not_a_crash(self):
        def boom(command, kwargs):
            raise RuntimeError("terminal exploded")

        body = _FakeBody(handler=boom)
        result = execute_terminal_loop_step(
            body,
            permission=_permission(),
            action_id="terminal.run",
            arguments={"command": "echo hi", "workdir": "/tmp"},
            event_id="evt-1",
        )
        self.assertFalse(result.execution.success)
        self.assertIn("dispatch failed", result.execution.error)

    def test_unknown_action_raises(self):
        with self.assertRaises(ValueError):
            execute_terminal_loop_step(
                _FakeBody(),
                permission=_permission(),
                action_id="terminal.nope",
                arguments={"command": "echo hi", "workdir": "/tmp"},
            )

    def test_argument_validation_rejects_unknown_and_malformed_arguments(self):
        spec = terminal_loop_spec("terminal.run")
        self.assertIsNotNone(spec)
        with self.assertRaises(ValueError):
            validate_terminal_loop_arguments(
                spec, {"command": "echo hi", "workdir": "/tmp", "pty": True}
            )
        with self.assertRaises(ValueError):
            validate_terminal_loop_arguments(spec, {"command": "  ", "workdir": "/tmp"})
        with self.assertRaises(ValueError):
            validate_terminal_loop_arguments(spec, {"command": "echo hi"})
        with self.assertRaises(ValueError):
            validate_terminal_loop_arguments(
                spec, {"command": "echo hi", "workdir": "/tmp", "timeout": 0}
            )
        with self.assertRaises(ValueError):
            validate_terminal_loop_arguments(
                spec, {"command": "echo hi", "workdir": "/tmp", "timeout": 601}
            )
        with self.assertRaises(ValueError):
            validate_terminal_loop_arguments(
                spec, {"command": "echo\x00hi", "workdir": "/tmp"}
            )

    def test_permission_parsing_is_caller_owned_and_fail_closed(self):
        self.assertIsNone(parse_terminal_permission(None))
        with self.assertRaises(ValueError):
            parse_terminal_permission({"allow_terminal": "yes"})
        with self.assertRaises(ValueError):
            parse_terminal_permission({"denylist": ["("]})
        with self.assertRaises(ValueError):
            parse_terminal_permission({"max_timeout_seconds": -1})
        with self.assertRaises(ValueError):
            parse_terminal_permission({"permission_policy": {"modes": {"nope": "always_ask"}}})
        parsed = parse_terminal_permission(
            {
                "allow_terminal": True,
                "allowed_workdirs": ["/tmp"],
                "max_timeout_seconds": 30,
                "denylist": ["rm -rf"],
                "permission_policy": {"modes": {"terminal_command": "always_ask"}},
            }
        )
        self.assertTrue(parsed.allow_terminal)
        self.assertEqual(
            check_terminal_permission(
                parsed, command="echo hi", workdir="/tmp", timeout=10
            ),
            "approval_required: terminal command needs user approval "
            "under the caller permission policy",
        )

    def test_catalog_exposes_terminal_run(self):
        rows = terminal_loop_catalog()
        self.assertEqual([row["action_id"] for row in rows], ["terminal.run"])
        self.assertEqual(rows[0]["effect_class"], "potential_side_effect")
        self.assertEqual(
            rows[0]["arguments_schema"]["required"], ["command", "workdir"]
        )


class TerminalLoopRealBodyTests(unittest.TestCase):
    """End-to-end through the real Body -> ZNLocalTerminal dispatch."""

    def test_real_echo_returns_verified_output(self):
        body = NativeBody()
        result = execute_terminal_loop_step(
            body,
            permission=_permission(),
            action_id="terminal.run",
            arguments={"command": "echo hello-m6", "workdir": "/tmp"},
            event_id="evt-real-1",
        )
        self.assertTrue(result.execution.success)
        self.assertEqual(result.execution.observations[0].data["output"], "hello-m6\n")
        self.assertEqual(result.execution.observations[0].data["exit_code"], 0)

    def test_real_timeout_kills_the_command_and_returns_promptly(self):
        body = NativeBody()
        started = time.monotonic()
        result = execute_terminal_loop_step(
            body,
            permission=_permission(),
            action_id="terminal.run",
            arguments={"command": "sleep 30", "workdir": "/tmp", "timeout": 0.2},
            event_id="evt-real-2",
        )
        elapsed = time.monotonic() - started
        self.assertFalse(result.execution.success)
        self.assertFalse(result.completed_with_output)
        self.assertTrue(result.execution.observations[0].data["timed_out"])
        self.assertLess(elapsed, 10.0)

    def test_real_nonzero_exit_carries_output_for_the_next_decision(self):
        body = NativeBody()
        result = execute_terminal_loop_step(
            body,
            permission=_permission(),
            action_id="terminal.run",
            arguments={"command": "echo out; exit 3", "workdir": "/tmp"},
            event_id="evt-real-3",
        )
        self.assertFalse(result.execution.success)
        self.assertTrue(result.completed_with_output)
        self.assertEqual(result.execution.observations[0].data["output"], "out\n")
        self.assertEqual(result.execution.observations[0].data["exit_code"], 3)


class _Device:
    def installed_applications(self):
        return ()

    def foreground_application(self):
        return None


def _fabric():
    fabric = ActionFabricRegistry()
    fabric.register(
        ActionDescriptor(
            action_id="test.read",
            provider="test",
            description="Read one fresh test value.",
            body_action_kind="test_read",
            input_schema={"type": "object", "additionalProperties": False},
            effect_class="read_only",
            verification=("fresh body result",),
        ),
        availability_probe=lambda descriptor: ActionAvailability(
            descriptor.action_id,
            "available",
            reason="test action is available",
        ),
    )
    return fabric


class TerminalLoopResidentTests(unittest.TestCase):
    def _resident(self, root: Path, body, permission):
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=root / "kernel.db",
        )
        resident.action_fabric = _fabric()
        resident.action_executor = ActionExecutionRuntime(_fabric(), body)
        resident.device_capabilities = _Device()
        resident.terminal_permission_context = permission
        resident._accept_generic_action_increment = lambda event, state, increment: 1
        return resident

    @staticmethod
    def _increment(event, content):
        from zn_agent.core.cognition import CognitiveIncrement

        return CognitiveIncrement.create(
            event_id=event.event_id,
            impasse_id="impasse-test",
            source="external:test",
            question=event.task,
            content=content,
            quality=1.0,
            confidence=1.0,
        )

    @staticmethod
    def _state(event, increment):
        from zn_agent.core.models import WorkingState

        return WorkingState(
            current_event_id=event.event_id,
            stage="cognition_integration",
            data={
                "cognition_request": {
                    "context": {"generic_action_loop": {"version": 1}},
                },
                "cognitive_increment": increment.to_dict(),
                "external_cognition_result": {"model_invocations": 1},
            },
        )

    def _propose(self, resident, event, state, content, *, expect_step_none=True):
        from types import SimpleNamespace as _NS

        state.stage = "cognition_integration"
        state.data["cognition_request"] = {
            "context": {"generic_action_loop": {"version": 1}},
        }
        state.data["cognitive_increment"] = self._increment(event, content).to_dict()
        state.data["external_cognition_result"] = {"model_invocations": 1}
        admitted = resident._cognition_integration_step(
            event, state, readiness=_NS()
        )
        self.assertIsNone(admitted)
        self.assertEqual(state.stage, resident._GENERIC_ACTION_STAGE)
        executed = resident._generic_action_step(event, state)
        if expect_step_none:
            self.assertIsNone(executed)
        return executed

    def test_terminal_loop_available_only_with_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp), _FakeBody(), _permission())
            event = AgentEvent(
                event_id="evt-terminal-avail",
                task="run a command",
                kind="desktop_user_event",
            )
            try:
                self.assertTrue(resident._terminal_loop_available(event))
                resident.terminal_permission_context = _permission(allow_terminal=False)
                self.assertFalse(resident._terminal_loop_available(event))
                resident.terminal_permission_context = None
                self.assertFalse(resident._terminal_loop_available(event))
            finally:
                resident.store.close()

    def test_model_runs_command_and_completes_from_its_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = _FakeBody()
            resident = self._resident(Path(tmp), body, _permission())
            try:
                event = AgentEvent(
                    event_id="evt-terminal-loop",
                    task="print the greeting",
                    kind="desktop_user_event",
                )
                state = self._state(
                    event,
                    self._increment(
                        event,
                        '{"zn_action_proposal":{"action_id":"terminal.run",'
                        '"arguments":{"command":"echo hello-m6","workdir":"/tmp"}}}',
                    ),
                )
                resident.store.save_working_state(state)

                self._propose(
                    resident,
                    event,
                    state,
                    '{"zn_action_proposal":{"action_id":"terminal.run",'
                    '"arguments":{"command":"echo hello-m6","workdir":"/tmp"}}}',
                )
                self.assertEqual(state.stage, "native_deliberation")
                loop = state.data[resident._GENERIC_ACTION_LOOP_KEY]
                self.assertEqual(len(loop["history"]), 1)
                self.assertTrue(loop["history"][0]["verified"])
                observation = loop["history"][0]["observations"][0]
                self.assertEqual(observation["data"]["output"], "hello-m6\n")
                self.assertEqual(observation["data"]["exit_code"], 0)
                # Exactly one dispatch; nothing re-dispatched.
                self.assertEqual(len(body.calls), 1)
                evidence_id = loop["history"][-1]["execution_id"]

                from types import SimpleNamespace as _NS

                state.stage = "cognition_integration"
                state.data["cognition_request"] = {
                    "context": {"generic_action_loop": {"version": 1}},
                }
                state.data["cognitive_increment"] = self._increment(
                    event,
                    '{"zn_action_completion":{"execution_ids":["'
                    + evidence_id
                    + '"],"response":"command printed hello-m6"}}',
                ).to_dict()
                state.data["external_cognition_result"] = {"model_invocations": 1}
                completed = resident._cognition_integration_step(
                    event, state, readiness=_NS()
                )
                self.assertIsNotNone(completed)
                self.assertTrue(completed.success)
                self.assertIs(completed.execution_path, ExecutionPath.BODY)
                self.assertEqual(completed.response, "command printed hello-m6")
            finally:
                resident.store.close()

    def test_over_privileged_proposal_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = _FakeBody()
            resident = self._resident(
                Path(tmp), body, _permission(denylist=("rm -rf",))
            )
            try:
                event = AgentEvent(
                    event_id="evt-terminal-deny",
                    task="delete things",
                    kind="desktop_user_event",
                )
                state = self._state(
                    event,
                    self._increment(
                        event,
                        '{"zn_action_proposal":{"action_id":"terminal.run",'
                        '"arguments":{"command":"rm -rf /tmp/x","workdir":"/tmp"}}}',
                    ),
                )
                resident.store.save_working_state(state)

                from types import SimpleNamespace as _NS

                state.stage = "cognition_integration"
                state.data["cognition_request"] = {
                    "context": {"generic_action_loop": {"version": 1}},
                }
                state.data["cognitive_increment"] = self._increment(
                    event,
                    '{"zn_action_proposal":{"action_id":"terminal.run",'
                    '"arguments":{"command":"rm -rf /tmp/x","workdir":"/tmp"}}}',
                ).to_dict()
                state.data["external_cognition_result"] = {"model_invocations": 1}
                rejected = resident._cognition_integration_step(
                    event, state, readiness=_NS()
                )
                self.assertIsNone(rejected)
                loop = state.data[resident._GENERIC_ACTION_LOOP_KEY]
                self.assertEqual(loop["protocol_repairs"], 1)
                self.assertIn("denylist", loop["last_protocol_error"])
                self.assertEqual(body.calls, [])
            finally:
                resident.store.close()

    def test_nonzero_exit_failure_surfaces_output_for_the_next_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = _FakeBody()
            resident = self._resident(Path(tmp), body, _permission())
            try:
                event = AgentEvent(
                    event_id="evt-terminal-nonzero",
                    task="run a failing command",
                    kind="desktop_user_event",
                )
                state = self._state(
                    event,
                    self._increment(
                        event,
                        '{"zn_action_proposal":{"action_id":"terminal.run",'
                        '"arguments":{"command":"exit 3","workdir":"/tmp"}}}',
                    ),
                )
                resident.store.save_working_state(state)

                self._propose(
                    resident,
                    event,
                    state,
                    '{"zn_action_proposal":{"action_id":"terminal.run",'
                    '"arguments":{"command":"exit 3","workdir":"/tmp"}}}',
                )
                # Not model-led in this harness: failure goes to investigation,
                # but the real output travels with it for the next decision.
                self.assertEqual(state.stage, "native_investigation")
                loop = state.data[resident._GENERIC_ACTION_LOOP_KEY]
                failure = loop["last_failure"]
                self.assertEqual(failure["observations"][0]["data"]["output"], "out\n")
                self.assertEqual(failure["observations"][0]["data"]["exit_code"], 3)
                self.assertEqual(len(body.calls), 1)
            finally:
                resident.store.close()

    def test_model_led_nonzero_exit_returns_to_cognition_with_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = _FakeBody()
            resident = self._resident(Path(tmp), body, _permission())
            resident._begin_model_led_event = lambda event, state: "re-entered"
            try:
                event = AgentEvent(
                    event_id="evt-terminal-led",
                    task="run a failing command",
                    kind="desktop_user_event",
                )
                state = self._state(
                    event,
                    self._increment(
                        event,
                        '{"zn_action_proposal":{"action_id":"terminal.run",'
                        '"arguments":{"command":"exit 3","workdir":"/tmp"}}}',
                    ),
                )
                state.data[resident._GENERIC_ACTION_LOOP_KEY] = {
                    "version": 1,
                    "model_led": True,
                }
                resident.store.save_working_state(state)

                executed = self._propose(
                    resident,
                    event,
                    state,
                    '{"zn_action_proposal":{"action_id":"terminal.run",'
                    '"arguments":{"command":"exit 3","workdir":"/tmp"}}}',
                    expect_step_none=False,
                )
                # The step re-enters model-led cognition instead of
                # terminal-failing or looping on the same command.
                self.assertEqual(executed, "re-entered")
                self.assertEqual(state.stage, "model_led_prepare")
                loop = state.data[resident._GENERIC_ACTION_LOOP_KEY]
                self.assertEqual(
                    loop["last_failure"]["observations"][0]["data"]["output"], "out\n"
                )
                self.assertEqual(len(body.calls), 1)
            finally:
                resident.store.close()

    def test_timeout_goes_to_investigation_and_is_never_redispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = _FakeBody()
            resident = self._resident(Path(tmp), body, _permission())
            resident._begin_model_led_event = lambda event, state: "re-entered"
            try:
                event = AgentEvent(
                    event_id="evt-terminal-timeout",
                    task="run a hanging command",
                    kind="desktop_user_event",
                )
                state = self._state(
                    event,
                    self._increment(
                        event,
                        '{"zn_action_proposal":{"action_id":"terminal.run",'
                        '"arguments":{"command":"sleep 30","workdir":"/tmp","timeout":5}}}',
                    ),
                )
                state.data[resident._GENERIC_ACTION_LOOP_KEY] = {
                    "version": 1,
                    "model_led": True,
                }
                resident.store.save_working_state(state)

                self._propose(
                    resident,
                    event,
                    state,
                    '{"zn_action_proposal":{"action_id":"terminal.run",'
                    '"arguments":{"command":"sleep 30","workdir":"/tmp","timeout":5}}}',
                )
                # Timeout carries no trustworthy output: investigation,
                # never an automatic re-entry with the same command.
                self.assertEqual(state.stage, "native_investigation")
                self.assertEqual(len(body.calls), 1)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
