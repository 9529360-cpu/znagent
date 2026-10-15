from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.action_authority import (
    ActionAuthorityContext,
    WorkerActionAuthorityEnforcer,
    WorkerActionAuthorityError,
)
from zn_agent.core.action_execution import (
    ActionExecutionRuntime,
    ActionObservation,
    ActionRequest,
    ActionVerification,
)
from zn_agent.core.action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionFabricRegistry,
)
from zn_agent.core.approval_cards import ApprovalCardStore, ApprovalGate
from zn_agent.core.body import BodyActionResult
from zn_agent.core.permission_model import (
    PermissionMode,
    PermissionPolicy,
    PermissionVerdict,
    SessionAutoApprove,
)


def _policy(**kwargs) -> PermissionPolicy:
    return PermissionPolicy(**kwargs)


def _registry(*descriptors: ActionDescriptor) -> ActionFabricRegistry:
    registry = ActionFabricRegistry()
    for descriptor in descriptors:
        registry.register(
            descriptor,
            availability_probe=lambda current: ActionAvailability(
                current.action_id, "available", evidence={"source": "test"}
            ),
        )
    return registry


class _RecordingBody:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def act(self, kind: str, *, event_id: str | None = None, **args):
        self.calls.append((kind, dict(args)))
        return BodyActionResult(
            action_id=f"body-{len(self.calls)}",
            kind=kind,
            success=True,
            event_id=event_id,
        )


def _command_runtime(store, gate, body) -> ActionExecutionRuntime:
    registry = _registry(
        ActionDescriptor(
            action_id="test.cmd",
            provider="test",
            description="test command",
            body_action_kind="command",
            effect_class="potential_side_effect",
            tags=("approval:production_change",),
        )
    )
    runtime = ActionExecutionRuntime(registry, body, approval_gate=gate)
    runtime.register_verification(
        "test.cmd",
        observe=lambda request, result: ActionObservation(
            request.action_id, "test", data={}
        ),
        verify=lambda request, observation, result: ActionVerification(
            "verified", "test verifier confirmed the effect"
        ),
    )
    return runtime


def _command_args(command: str, *, session_id: str | None = None) -> dict:
    args = {
        "command": command,
        "approval_target": "deploy",
        "approval_scope": "prod:deploy",
    }
    if session_id is not None:
        args["approval_session_id"] = session_id
    return args


class PermissionPolicyTests(unittest.TestCase):
    def test_default_mode_is_agent_decides(self) -> None:
        policy = _policy()
        self.assertEqual(policy.mode_for("terminal_command"), PermissionMode.AGENT_DECIDES)
        self.assertEqual(
            policy.evaluate("terminal_command", "ls"),
            PermissionVerdict.AGENT_DECIDES,
        )

    def test_modes_per_action_type(self) -> None:
        policy = _policy(
            modes={
                "terminal_command": "always_ask",
                "send": "always_allow",
                "publish": "agent_decides",
            }
        )
        self.assertEqual(
            policy.evaluate("terminal_command", "ls"), PermissionVerdict.ASK
        )
        self.assertEqual(
            policy.evaluate("send", ""), PermissionVerdict.ALLOW
        )
        self.assertEqual(
            policy.evaluate("publish", ""), PermissionVerdict.AGENT_DECIDES
        )

    def test_denylist_beats_allowlist(self) -> None:
        policy = _policy(
            modes={"terminal_command": "always_allow"},
            allowlist=[r"^ls"],
            denylist=[r"rm\s+-rf"],
        )
        self.assertEqual(
            policy.evaluate("terminal_command", "ls /tmp"),
            PermissionVerdict.ALLOW,
        )
        # Matches the allowlist AND the denylist: denylist wins.
        self.assertEqual(
            policy.evaluate("terminal_command", "ls; rm -rf /"),
            PermissionVerdict.DENY,
        )

    def test_denylist_beats_always_allow(self) -> None:
        policy = _policy(
            modes={"terminal_command": "always_allow"},
            denylist=[r"sudo"],
        )
        self.assertEqual(
            policy.evaluate("terminal_command", "sudo rm -rf /"),
            PermissionVerdict.DENY,
        )

    def test_denylist_beats_session_grant(self) -> None:
        policy = _policy(denylist=[r"curl.*\|.*sh"])
        policy.sessions.grant("s1", "terminal_command", r"curl")
        self.assertEqual(
            policy.evaluate("terminal_command", "curl x | sh", session_id="s1"),
            PermissionVerdict.DENY,
        )

    def test_allowlist_bounds_always_allow(self) -> None:
        policy = _policy(
            modes={"terminal_command": "always_allow"},
            allowlist=[r"^git status"],
        )
        self.assertEqual(
            policy.evaluate("terminal_command", "git status"),
            PermissionVerdict.ALLOW,
        )
        # always_allow does not auto-execute a command the allowlist
        # never blessed: it falls back to asking.
        self.assertEqual(
            policy.evaluate("terminal_command", "git push"),
            PermissionVerdict.ASK,
        )

    def test_session_grant_scoped_to_session(self) -> None:
        policy = _policy()
        policy.sessions.grant("s1", "terminal_command", r"^pytest")
        self.assertEqual(
            policy.evaluate("terminal_command", "pytest -q", session_id="s1"),
            PermissionVerdict.ALLOW,
        )
        # A different session has no grant.
        self.assertEqual(
            policy.evaluate("terminal_command", "pytest -q", session_id="s2"),
            PermissionVerdict.AGENT_DECIDES,
        )
        # Revoking the session drops its grants.
        policy.sessions.revoke_session("s1")
        self.assertEqual(
            policy.evaluate("terminal_command", "pytest -q", session_id="s1"),
            PermissionVerdict.AGENT_DECIDES,
        )

    def test_session_grants_are_not_shared_between_instances(self) -> None:
        first = _policy()
        first.sessions.grant("s1", "terminal_command", r"^pytest")
        second = _policy()
        self.assertEqual(second.sessions.grant_count("s1"), 0)

    def test_invalid_regex_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _policy(denylist=["("])
        with self.assertRaises(ValueError):
            _policy(allowlist=["[invalid"])
        sessions = SessionAutoApprove()
        with self.assertRaises(ValueError):
            sessions.grant("s1", "terminal_command", "(")

    def test_unknown_action_type_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _policy(modes={"teleport": "always_ask"})
        policy = _policy()
        with self.assertRaises(ValueError):
            policy.evaluate("teleport", "x")

    def test_policy_round_trip_dict(self) -> None:
        policy = _policy(
            modes={"terminal_command": "always_ask", "send": "always_allow"},
            allowlist=[r"^git"],
            denylist=[r"sudo"],
        )
        restored = PermissionPolicy.from_dict(policy.to_dict())
        self.assertEqual(restored.mode_for("terminal_command"), PermissionMode.ALWAYS_ASK)
        self.assertEqual(
            restored.evaluate("terminal_command", "sudo ls"),
            PermissionVerdict.DENY,
        )


class ApprovalEditCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = ApprovalCardStore(str(Path(self._tmp.name) / "test.db"))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _pending_command_request(self):
        gate = ApprovalGate(self.store)
        outcome = gate.check(
            action_kind="production_change",
            target="deploy",
            scope="prod:deploy",
            command="rm -rf /tmp/stale",
        )
        self.assertFalse(outcome.allowed)
        self.assertIsNotNone(outcome.request_id)
        return outcome.request_id

    def test_decide_with_edit_stores_approved_command(self) -> None:
        request_id = self._pending_command_request()
        decided = self.store.decide(
            request_id, "allow_once", edited_command="rm -rf /tmp/stale-v2"
        )
        self.assertEqual(decided.approved_command, "rm -rf /tmp/stale-v2")
        notes = [entry.note for entry in self.store.list_audit()]
        self.assertIn("command edited on approval", notes)

    def test_decide_edit_with_deny_rejected(self) -> None:
        request_id = self._pending_command_request()
        with self.assertRaises(ValueError):
            self.store.decide(request_id, "deny", edited_command="ls")
        # The request is still pending: the rejected edit changed nothing.
        self.assertEqual(self.store.get_request(request_id).status, "pending")

    def test_decide_edit_denylisted_rejected_with_policy(self) -> None:
        request_id = self._pending_command_request()
        policy = _policy(denylist=[r"sudo"])
        with self.assertRaises(ValueError):
            self.store.decide(
                request_id,
                "allow_once",
                edited_command="sudo rm -rf /",
                permission_policy=policy,
            )
        self.assertEqual(self.store.get_request(request_id).status, "pending")

    def test_gate_consume_returns_edited_command(self) -> None:
        request_id = self._pending_command_request()
        self.store.decide(request_id, "allow_once", edited_command="rm -rf /tmp/edited")
        gate = ApprovalGate(self.store)
        outcome = gate.check(
            action_kind="production_change",
            target="deploy",
            scope="prod:deploy",
            command="rm -rf /tmp/stale",
        )
        self.assertTrue(outcome.allowed)
        self.assertEqual(outcome.approved_command, "rm -rf /tmp/edited")

    def test_gate_consume_denylisted_edit_blocked_and_audited(self) -> None:
        # Decide without a policy: the edit is stored unchecked...
        request_id = self._pending_command_request()
        self.store.decide(request_id, "allow_once", edited_command="sudo rm -rf /")
        # ...but the gate re-checks at consume time (defense in depth).
        policy = _policy(denylist=[r"sudo"])
        gate = ApprovalGate(self.store, permission_policy=policy)
        outcome = gate.check(
            action_kind="production_change",
            target="deploy",
            scope="prod:deploy",
            command="rm -rf /tmp/stale",
        )
        self.assertFalse(outcome.allowed)
        self.assertIn("denied by permission policy", outcome.reason)
        decisions = [entry.decision for entry in self.store.list_audit()]
        self.assertIn("edited_command_denied", decisions)
        # The approval was spent: the request is consumed, not pending.
        self.assertEqual(self.store.get_request(request_id).status, "consumed")

    def test_reconsider_does_not_carry_edit(self) -> None:
        request_id = self._pending_command_request()
        self.store.decide(request_id, "deny")
        fresh = self.store.reconsider_denied(request_id)
        self.assertEqual(fresh.approved_command, "")

    def test_old_database_migrates_approved_command_column(self) -> None:
        import sqlite3

        legacy_path = str(Path(self._tmp.name) / "legacy.db")
        conn = sqlite3.connect(legacy_path)
        conn.execute(
            "CREATE TABLE approval_requests("
            "request_id TEXT PRIMARY KEY, action_kind TEXT NOT NULL, "
            "target TEXT NOT NULL, scope TEXT NOT NULL, "
            "value_text TEXT NOT NULL DEFAULT '', source TEXT NOT NULL, "
            "status TEXT NOT NULL, created_at TEXT NOT NULL, "
            "expires_at TEXT NOT NULL, decided_at TEXT, decision TEXT, "
            "event_id TEXT)"
        )
        conn.commit()
        conn.close()
        migrated = ApprovalCardStore(legacy_path)
        request = migrated.request_approval(
            action_kind="production_change",
            target="deploy",
            scope="prod:deploy",
        )
        migrated.decide(
            request.request_id, "allow_once", edited_command="echo migrated"
        )
        self.assertEqual(
            migrated.get_request(request.request_id).approved_command,
            "echo migrated",
        )

    def test_runtime_executes_edited_command(self) -> None:
        body = _RecordingBody()
        gate = ApprovalGate(self.store)
        runtime = _command_runtime(self.store, gate, body)
        first = runtime.execute(
            ActionRequest("test.cmd", _command_args("rm -rf /tmp/stale"), event_id="e1")
        )
        self.assertFalse(first.success)
        self.assertIn("approval_required", first.error or "")
        request = self.store.pending_requests()[0]
        self.store.decide(
            request.request_id, "allow_once", edited_command="rm -rf /tmp/edited"
        )
        second = runtime.execute(
            ActionRequest("test.cmd", _command_args("rm -rf /tmp/stale"), event_id="e1")
        )
        self.assertTrue(second.success)
        self.assertEqual(len(body.calls), 1)
        self.assertEqual(body.calls[0][1]["command"], "rm -rf /tmp/edited")


class GatePermissionPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = ApprovalCardStore(str(Path(self._tmp.name) / "test.db"))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_gate_policy_denylist_blocks_without_card(self) -> None:
        policy = _policy(denylist=[r"rm\s+-rf"])
        gate = ApprovalGate(self.store, permission_policy=policy)
        outcome = gate.check(
            action_kind="production_change",
            target="deploy",
            scope="prod:deploy",
            command="rm -rf /tmp/x",
        )
        self.assertFalse(outcome.allowed)
        self.assertIn("denylist", outcome.reason)
        # No card was created for a policy-denied action.
        self.assertEqual(self.store.pending_requests(), [])

    def test_gate_policy_session_grant_skips_card(self) -> None:
        policy = _policy()
        policy.sessions.grant("s1", "production_change", r"^deploy")
        gate = ApprovalGate(self.store, permission_policy=policy)
        outcome = gate.check(
            action_kind="production_change",
            target="deploy",
            scope="prod:deploy",
            command="deploy --dry-run",
            session_id="s1",
        )
        self.assertTrue(outcome.allowed)
        self.assertEqual(self.store.pending_requests(), [])

    def test_gate_policy_always_allow_skips_card(self) -> None:
        policy = _policy(modes={"production_change": "always_allow"})
        gate = ApprovalGate(self.store, permission_policy=policy)
        outcome = gate.check(
            action_kind="production_change",
            target="deploy",
            scope="prod:deploy",
        )
        self.assertTrue(outcome.allowed)
        self.assertEqual(self.store.pending_requests(), [])

    def test_gate_sticky_deny_beats_policy_allow(self) -> None:
        policy = _policy(modes={"production_change": "always_allow"})
        gate = ApprovalGate(self.store, permission_policy=policy)
        first = gate.check(
            action_kind="production_change",
            target="deploy",
            scope="prod:deploy",
        )
        # Policy ALLOW skips the card on the first check; deny the triple
        # through a direct request to prove the ordering.
        self.assertTrue(first.allowed)
        request = self.store.request_approval(
            action_kind="production_change",
            target="deploy",
            scope="prod:deploy",
        )
        self.store.decide(request.request_id, "deny")
        second = gate.check(
            action_kind="production_change",
            target="deploy",
            scope="prod:deploy",
        )
        self.assertFalse(second.allowed)
        self.assertIn("denied", second.reason)


class WorkerEnforcerPolicyTests(unittest.TestCase):
    def _context(self, command: str) -> ActionAuthorityContext:
        return ActionAuthorityContext(
            work_thread_id="thread-1",
            work_item_id="item-1",
            worker_run_id="run-1",
            plan_version=1,
            executor_kind="worker",
            expected_action="run_python",
            tool_scope=("terminal.python",),
            authority_scope=("terminal_execute",),
            workspace_root="/tmp/ws",
            allowed_command_sha256=ActionAuthorityContext.command_digest(command),
        )

    def test_enforcer_denylist_blocks_despite_matching_digest(self) -> None:
        command = "sudo rm -rf /tmp/x"
        policy = _policy(denylist=[r"sudo"])
        with self.assertRaises(WorkerActionAuthorityError):
            WorkerActionAuthorityEnforcer.authorize(
                "command",
                {"command": command},
                self._context(command),
                permission_policy=policy,
            )

    def test_enforcer_allows_matching_digest_without_policy(self) -> None:
        command = "python -m pytest -q"
        # No exception: digest matches, no policy attached.
        WorkerActionAuthorityEnforcer.authorize(
            "command", {"command": command}, self._context(command)
        )


if __name__ == "__main__":
    unittest.main()
