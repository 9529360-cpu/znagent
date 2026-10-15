from __future__ import annotations

import unittest
from types import SimpleNamespace

from zn_agent.core.action_authority import ApprovalSnapshot, canonical_args_digest
from zn_agent.core.action_execution import (
    ActionExecutionRuntime,
    ActionRequest,
    ExecutionContext,
    ExecutionMiddlewareChain,
)
from zn_agent.core.action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionFabricRegistry,
)
from zn_agent.core.approval_cards import ApprovalGateOutcome
from zn_agent.core.body import BodyActionResult


class _FakeBody:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, dict]] = []

    def act(self, kind: str, *, event_id: str | None = None, **args):
        self.calls.append((kind, event_id, dict(args)))
        return BodyActionResult(
            action_id=f"body-{len(self.calls)}",
            kind=kind,
            success=True,
            data={},
            event_id=event_id,
        )


def _registry(descriptor: ActionDescriptor) -> ActionFabricRegistry:
    registry = ActionFabricRegistry()
    registry.register(
        descriptor,
        availability_probe=lambda current: ActionAvailability(
            current.action_id,
            "available",
            evidence={"source": "test"},
        ),
    )
    return registry


def _gated_descriptor() -> ActionDescriptor:
    return ActionDescriptor(
        action_id="test.effect.send",
        provider="zn.test",
        description="Gated side effect",
        body_action_kind="test_effect_send",
        effect_class="read_only",
        tags=("approval:send",),
    )


def _allowing_gate(*, approved_command: str | None = None):
    def check(**kwargs):
        return ApprovalGateOutcome(
            True,
            reason="test approval",
            approved_command=approved_command,
        )

    return SimpleNamespace(check=check)


def _denying_gate():
    def check(**kwargs):
        return ApprovalGateOutcome(False, reason="test deny")

    return SimpleNamespace(check=check)


class ApprovalSnapshotTests(unittest.TestCase):
    def test_digest_is_order_independent(self) -> None:
        self.assertEqual(
            canonical_args_digest({"a": 1, "b": {"c": 2}}),
            canonical_args_digest({"b": {"c": 2}, "a": 1}),
        )

    def test_capture_and_verify_unchanged(self) -> None:
        snapshot = ApprovalSnapshot.capture(
            "test.effect.send",
            {"target": "someone", "value": 3},
            "event-1",
        )
        self.assertEqual(snapshot.verify("test.effect.send", {"target": "someone", "value": 3}, "event-1"), [])
        self.assertTrue(snapshot.matches("test.effect.send", {"target": "someone", "value": 3}, "event-1"))

    def test_verify_reports_changed_removed_action_and_event(self) -> None:
        snapshot = ApprovalSnapshot.capture(
            "test.effect.send",
            {"target": "someone", "value": 3},
            "event-1",
        )
        mismatches = snapshot.verify(
            "test.effect.send", {"target": "attacker"}, "event-1"
        )
        self.assertIn("approved parameter changed: target", mismatches)
        self.assertIn("approved parameter removed: value", mismatches)
        self.assertTrue(
            any("action changed" in item for item in snapshot.verify("other.action", {"target": "someone", "value": 3}, "event-1"))
        )
        self.assertIn(
            "event_id changed after approval",
            snapshot.verify("test.effect.send", {"target": "someone", "value": 3}, "event-2"),
        )

    def test_capture_applies_approved_edited_command(self) -> None:
        snapshot = ApprovalSnapshot.capture(
            "test.effect.send",
            {"command": "echo original"},
            "event-1",
            approved_command="echo edited",
        )
        self.assertEqual(snapshot.approved_args["command"], "echo edited")
        self.assertEqual(
            snapshot.verify("test.effect.send", {"command": "echo original"}, "event-1"),
            ["approved parameter changed: command"],
        )
        self.assertEqual(snapshot.verify("test.effect.send", {"command": "echo edited"}, "event-1"), [])


class ApprovalMiddlewareChainTests(unittest.TestCase):
    def test_middleware_chain_runs_in_order(self) -> None:
        descriptor = _gated_descriptor()
        body = _FakeBody()
        runtime = ActionExecutionRuntime(
            _registry(descriptor), body, approval_gate=_allowing_gate()
        )
        order: list[str] = []

        def custom_middleware(context, next_step):
            order.append("custom")
            return next_step()

        runtime.register_middleware(custom_middleware)
        runtime.register_argument_binder(
            descriptor.action_id,
            lambda args: (order.append("binder"), dict(args))[1],
        )
        result = runtime.execute(
            ActionRequest(descriptor.action_id, {"target": "someone"})
        )
        self.assertTrue(result.success)
        self.assertEqual(order, ["custom", "binder"])
        self.assertEqual(len(body.calls), 1)
        self.assertIn("approval granted", " ".join(result.audit))
        self.assertIn("post-approval revalidation passed", result.audit)

    def test_chain_short_circuit_never_dispatches(self) -> None:
        descriptor = _gated_descriptor()
        body = _FakeBody()
        runtime = ActionExecutionRuntime(_registry(descriptor), body)

        def blocking_middleware(context, next_step):
            return runtime._failure(
                context.request,
                context.descriptor,
                context.started_at,
                "custom middleware blocked",
            )

        runtime.register_middleware(blocking_middleware)
        result = runtime.execute(
            ActionRequest(descriptor.action_id, {"target": "someone"})
        )
        self.assertFalse(result.success)
        self.assertIn("custom middleware blocked", result.error or "")
        self.assertEqual(body.calls, [])

    def test_approved_params_unchanged_execute(self) -> None:
        descriptor = _gated_descriptor()
        body = _FakeBody()
        runtime = ActionExecutionRuntime(
            _registry(descriptor), body, approval_gate=_allowing_gate()
        )
        result = runtime.execute(
            ActionRequest(descriptor.action_id, {"target": "someone", "value": 3})
        )
        self.assertTrue(result.success)
        self.assertEqual(len(body.calls), 1)
        self.assertEqual(body.calls[0][2]["target"], "someone")

    def test_post_approval_mutation_is_refused_without_dispatch(self) -> None:
        descriptor = _gated_descriptor()
        body = _FakeBody()
        runtime = ActionExecutionRuntime(
            _registry(descriptor), body, approval_gate=_allowing_gate()
        )

        def tampering_binder(args):
            mutated = dict(args)
            mutated["target"] = "attacker"
            return mutated

        runtime.register_argument_binder(descriptor.action_id, tampering_binder)
        result = runtime.execute(
            ActionRequest(descriptor.action_id, {"target": "someone"})
        )
        self.assertFalse(result.success)
        self.assertIn("post-approval revalidation refused", result.error or "")
        self.assertIn("approved parameter changed: target", result.error or "")
        self.assertEqual(body.calls, [])
        self.assertTrue(any("refused" in entry for entry in result.audit))

    def test_post_approval_deletion_is_refused_without_dispatch(self) -> None:
        descriptor = _gated_descriptor()
        body = _FakeBody()
        runtime = ActionExecutionRuntime(
            _registry(descriptor), body, approval_gate=_allowing_gate()
        )

        def deleting_binder(args):
            pruned = dict(args)
            del pruned["target"]
            return pruned

        runtime.register_argument_binder(descriptor.action_id, deleting_binder)
        result = runtime.execute(
            ActionRequest(descriptor.action_id, {"target": "someone"})
        )
        self.assertFalse(result.success)
        self.assertIn("approved parameter removed: target", result.error or "")
        self.assertEqual(body.calls, [])

    def test_binder_added_key_is_allowed(self) -> None:
        descriptor = _gated_descriptor()
        body = _FakeBody()
        runtime = ActionExecutionRuntime(
            _registry(descriptor), body, approval_gate=_allowing_gate()
        )

        def binding_binder(args):
            bound = dict(args)
            bound["workspace_root"] = "/resident/workspace"
            return bound

        runtime.register_argument_binder(descriptor.action_id, binding_binder)
        result = runtime.execute(
            ActionRequest(descriptor.action_id, {"target": "someone"})
        )
        self.assertTrue(result.success, result.error)
        self.assertEqual(body.calls[0][2]["workspace_root"], "/resident/workspace")

    def test_approved_edited_command_wins_over_binder_command(self) -> None:
        descriptor = _gated_descriptor()
        body = _FakeBody()
        runtime = ActionExecutionRuntime(
            _registry(descriptor),
            body,
            approval_gate=_allowing_gate(approved_command="echo edited"),
        )

        def evil_binder(args):
            bound = dict(args)
            bound["command"] = "echo evil"
            return bound

        runtime.register_argument_binder(descriptor.action_id, evil_binder)
        result = runtime.execute(
            ActionRequest(
                descriptor.action_id,
                {"target": "someone", "command": "echo original"},
            )
        )
        self.assertTrue(result.success, result.error)
        self.assertEqual(body.calls[0][2]["command"], "echo edited")

    def test_approval_denied_never_dispatches(self) -> None:
        descriptor = _gated_descriptor()
        body = _FakeBody()
        runtime = ActionExecutionRuntime(
            _registry(descriptor), body, approval_gate=_denying_gate()
        )
        result = runtime.execute(
            ActionRequest(descriptor.action_id, {"target": "someone"})
        )
        self.assertFalse(result.success)
        self.assertEqual(body.calls, [])
        self.assertTrue(any("approval blocked" in entry for entry in result.audit))

    def test_no_gate_passes_through_without_snapshot(self) -> None:
        descriptor = _gated_descriptor()
        body = _FakeBody()
        runtime = ActionExecutionRuntime(_registry(descriptor), body)
        result = runtime.execute(
            ActionRequest(descriptor.action_id, {"target": "someone"})
        )
        self.assertTrue(result.success)
        self.assertEqual(result.audit, ())
        self.assertEqual(len(body.calls), 1)

    def test_chain_composes_middlewares_in_registration_order(self) -> None:
        seen: list[str] = []
        context = ExecutionContext(
            request=ActionRequest("test.effect.send", {"target": "someone"}),
            descriptor=_gated_descriptor(),
            started_at="2026-10-15T00:00:00Z",
        )

        def first(ctx, next_step):
            seen.append("first")
            return next_step()

        def second(ctx, next_step):
            seen.append("second")
            return next_step()

        chain = ExecutionMiddlewareChain([first, second])
        sentinel = object()
        outcome = chain.run(context, lambda: sentinel)
        self.assertIs(outcome, sentinel)
        self.assertEqual(seen, ["first", "second"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
