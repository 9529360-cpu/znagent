from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.action_authority import (
    ActionAuthorityContext,
    WorkerActionAuthorityEnforcer,
    WorkerActionAuthorityError,
)
from zn_agent.core.sandbox import (
    OneShotEscalationManager,
    SandboxDeniedError,
    SandboxGate,
    SandboxPolicy,
    SandboxTier,
    classify_call,
    parse_sandbox_tier,
)


def _write_context(workspace: Path) -> ActionAuthorityContext:
    return ActionAuthorityContext(
        work_thread_id="thread-dsh6",
        work_item_id="item-dsh6",
        worker_run_id="run-dsh6",
        plan_version=1,
        executor_kind="test-worker",
        expected_action="write_file",
        tool_scope=("workspace.write",),
        authority_scope=("workspace_write",),
        workspace_root=str(workspace),
    )


class SandboxTierTests(unittest.TestCase):
    def test_parse_tier(self) -> None:
        self.assertEqual(parse_sandbox_tier("read_only"), SandboxTier.READ_ONLY)
        self.assertEqual(
            parse_sandbox_tier("WORKSPACE_WRITE"), SandboxTier.WORKSPACE_WRITE
        )
        self.assertEqual(
            parse_sandbox_tier("danger_full_access"),
            SandboxTier.DANGER_FULL_ACCESS,
        )
        with self.assertRaises(ValueError):
            parse_sandbox_tier("yolo")

    def test_classify_call(self) -> None:
        self.assertEqual(classify_call("read_text"), "read")
        self.assertEqual(classify_call("write_text"), "write")
        self.assertEqual(classify_call("command"), "command")
        self.assertEqual(classify_call("run_python"), "command")
        self.assertEqual(classify_call("send_message"), "other")
        self.assertEqual(classify_call("definitely_not_a_kind"), "other")

    def test_read_only_denies_all_writes_commands_and_side_effects(self) -> None:
        policy = SandboxPolicy(tier=SandboxTier.READ_ONLY)
        self.assertTrue(policy.check("read_text", {"path": "/etc/passwd"}).allowed)
        self.assertFalse(policy.check("write_text", {"path": "/tmp/x.txt"}).allowed)
        self.assertFalse(policy.check("command", {"command": "echo hi"}).allowed)
        self.assertFalse(policy.check("send_message", {"text": "hi"}).allowed)
        self.assertFalse(policy.check("mystery_kind", {}).allowed)

    def test_workspace_write_confines_writes_to_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            outside = Path(tmp) / "outside.txt"
            policy = SandboxPolicy(
                tier=SandboxTier.WORKSPACE_WRITE, workspace_root=str(workspace)
            )
            self.assertTrue(
                policy.check(
                    "write_text", {"path": str(workspace / "note.txt")}
                ).allowed
            )
            self.assertFalse(
                policy.check("write_text", {"path": str(outside)}).allowed
            )
            # Path traversal out of the workspace is still outside.
            self.assertFalse(
                policy.check(
                    "write_text", {"path": str(workspace / ".." / "outside.txt")}
                ).allowed
            )
            self.assertTrue(
                policy.check("read_text", {"path": str(outside)}).allowed
            )
            # Raw commands are not provably workspace-confined: fail closed.
            self.assertFalse(
                policy.check("command", {"command": "echo hi"}).allowed
            )
            # Side-effecting kinds are denied.
            self.assertFalse(
                policy.check("send_message", {"text": "hi"}).allowed
            )

    def test_workspace_write_without_root_denies_writes(self) -> None:
        policy = SandboxPolicy(tier=SandboxTier.WORKSPACE_WRITE, workspace_root=None)
        self.assertFalse(policy.check("write_text", {"path": "/tmp/x.txt"}).allowed)
        self.assertFalse(policy.check("write_text", {}).allowed)
        self.assertTrue(policy.check("read_text", {"path": "/tmp/x.txt"}).allowed)

    def test_danger_full_access_allows_everything_but_audits(self) -> None:
        policy = SandboxPolicy(tier=SandboxTier.DANGER_FULL_ACCESS)
        self.assertTrue(policy.check("write_text", {"path": "/etc/x"}).allowed)
        self.assertTrue(policy.check("command", {"command": "rm -rf /"}).allowed)
        self.assertTrue(policy.check("send_message", {"text": "hi"}).allowed)
        self.assertEqual(len(policy.audit), 3)
        self.assertTrue(all(e.event == "allow" for e in policy.audit))
        self.assertTrue(
            all(e.tier == "danger_full_access" for e in policy.audit)
        )


class OneShotEscalationTests(unittest.TestCase):
    def _gate(self) -> SandboxGate:
        return SandboxGate(
            SandboxPolicy(tier=SandboxTier.READ_ONLY, workspace_root=None)
        )

    def test_escalation_allows_exactly_one_retry(self) -> None:
        gate = self._gate()
        args = {"path": "/tmp/one-shot.txt", "content": "hello"}
        first = gate.authorize("write_text", args)
        self.assertFalse(first.allowed)
        self.assertIsNotNone(first.escalation_id)
        assert first.escalation_id is not None
        token = gate.escalation.approve(first.escalation_id)
        retried = gate.authorize("write_text", args, token.token_id)
        self.assertTrue(retried.allowed)
        self.assertTrue(retried.escalated)
        # The same token does NOT authorize a second identical call.
        second = gate.authorize("write_text", args, token.token_id)
        self.assertFalse(second.allowed)
        # And a fresh call without a token is still denied.
        third = gate.authorize("write_text", args)
        self.assertFalse(third.allowed)

    def test_escalation_token_bound_to_exact_call(self) -> None:
        gate = self._gate()
        denied = gate.authorize("write_text", {"path": "/tmp/a.txt"})
        assert denied.escalation_id is not None
        token = gate.escalation.approve(denied.escalation_id)
        # Different args: same token must not authorize a different call.
        other = gate.authorize(
            "write_text", {"path": "/tmp/b.txt"}, token.token_id
        )
        self.assertFalse(other.allowed)
        # The token is still unconsumed (a failed consume does not burn it),
        # so the original call still retries once.
        original = gate.authorize(
            "write_text", {"path": "/tmp/a.txt"}, token.token_id
        )
        self.assertTrue(original.allowed)

    def test_denied_escalation_executes_nothing(self) -> None:
        gate = self._gate()
        denied = gate.authorize("write_text", {"path": "/tmp/nope.txt"})
        assert denied.escalation_id is not None
        gate.escalation.deny(denied.escalation_id, reason="user said no")
        # No token exists for a denied request; approving it now is an error.
        with self.assertRaises(ValueError):
            gate.escalation.approve(denied.escalation_id)
        # The call is still denied without a token.
        again = gate.authorize("write_text", {"path": "/tmp/nope.txt"})
        self.assertFalse(again.allowed)
        events = [e.event for e in gate.policy.audit]
        self.assertIn("escalate_deny", events)
        self.assertNotIn("escalate_consume", events)

    def test_escalation_full_audit_trail(self) -> None:
        gate = self._gate()
        denied = gate.authorize("command", {"command": "echo hi"})
        assert denied.escalation_id is not None
        token = gate.escalation.approve(denied.escalation_id)
        gate.authorize("command", {"command": "echo hi"}, token.token_id)
        events = [e.event for e in gate.policy.audit]
        for expected in (
            "deny",
            "escalate_request",
            "escalate_approve",
            "escalate_consume",
        ):
            self.assertIn(expected, events)
        # The consume entry is marked escalated.
        consume = [e for e in gate.policy.audit if e.event == "escalate_consume"]
        self.assertEqual(len(consume), 1)
        self.assertTrue(consume[0].escalated)

    def test_require_raises_with_escalation_id(self) -> None:
        gate = self._gate()
        with self.assertRaises(SandboxDeniedError) as ctx:
            gate.require("write_text", {"path": "/tmp/x.txt"})
        self.assertIn("escalation_id=", str(ctx.exception))

    def test_manager_rejects_unknown_and_double_decide(self) -> None:
        manager = OneShotEscalationManager()
        with self.assertRaises(ValueError):
            manager.approve("esc-nope")
        with self.assertRaises(ValueError):
            manager.deny("esc-nope")
        req = manager.request("write_text", {"path": "/tmp/x.txt"})
        manager.deny(req.request_id)
        with self.assertRaises(ValueError):
            manager.approve(req.request_id)


class AuthorityWiringTests(unittest.TestCase):
    def test_enforcer_with_read_only_sandbox_denies_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            context = _write_context(workspace)
            policy = SandboxPolicy(tier=SandboxTier.READ_ONLY)
            with self.assertRaises(WorkerActionAuthorityError):
                WorkerActionAuthorityEnforcer.authorize(
                    "write_text",
                    {"path": str(workspace / "a.txt")},
                    context,
                    sandbox_policy=policy,
                )

    def test_enforcer_with_workspace_sandbox_allows_inside_denies_outside(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            context = _write_context(workspace)
            policy = SandboxPolicy(
                tier=SandboxTier.WORKSPACE_WRITE, workspace_root=str(workspace)
            )
            # Inside the workspace: authority + sandbox both pass.
            WorkerActionAuthorityEnforcer.authorize(
                "write_text",
                {"path": str(workspace / "a.txt")},
                context,
                sandbox_policy=policy,
            )
            # Outside the workspace: denied (both the authority scope and
            # the sandbox confine writes to the workspace).
            with self.assertRaises(WorkerActionAuthorityError):
                WorkerActionAuthorityEnforcer.authorize(
                    "write_text",
                    {"path": str(Path(tmp) / "outside.txt")},
                    context,
                    sandbox_policy=policy,
                )

    def test_enforcer_escalation_token_allows_one_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            context = _write_context(workspace)
            gate = SandboxGate(
                SandboxPolicy(tier=SandboxTier.READ_ONLY)
            )
            args = {"path": str(workspace / "escalated.txt")}
            with self.assertRaises(WorkerActionAuthorityError):
                WorkerActionAuthorityEnforcer.authorize(
                    "write_text", args, context, sandbox_gate=gate
                )
            pending = [
                r
                for r in gate.escalation.requests.values()
                if r.status == "pending"
            ]
            self.assertEqual(len(pending), 1)
            token = gate.escalation.approve(pending[0].request_id)
            # Exactly one retry with the token.
            WorkerActionAuthorityEnforcer.authorize(
                "write_text", args, context, sandbox_gate=gate,
                escalation_token=token.token_id,
            )
            with self.assertRaises(WorkerActionAuthorityError):
                WorkerActionAuthorityEnforcer.authorize(
                    "write_text", args, context, sandbox_gate=gate,
                    escalation_token=token.token_id,
                )

    def test_enforcer_without_sandbox_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            context = _write_context(workspace)
            # No sandbox configured: pre-existing authority behavior.
            WorkerActionAuthorityEnforcer.authorize(
                "write_text",
                {"path": str(workspace / "a.txt")},
                context,
            )


if __name__ == "__main__":
    unittest.main()
