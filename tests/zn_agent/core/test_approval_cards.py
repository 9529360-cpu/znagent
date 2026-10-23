from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

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
from zn_agent.core.approval_cards import (
    ApprovalCardStore,
    ApprovalGate,
    approval_kind_for_tag,
)
from zn_agent.core.body import BodyActionResult


def _registry(*descriptors: ActionDescriptor) -> ActionFabricRegistry:
    registry = ActionFabricRegistry()
    for descriptor in descriptors:
        registry.register(
            descriptor,
            availability_probe=lambda current: ActionAvailability(
                current.action_id,
                "available",
                evidence={"source": "test"},
            ),
        )
    return registry


def _descriptor(action_id: str, *, tags: tuple[str, ...] = ()) -> ActionDescriptor:
    return ActionDescriptor(
        action_id=action_id,
        provider="test",
        description="test action",
        body_action_kind="write_text",
        effect_class="potential_side_effect",
        tags=tags,
    )


class _FakeBody:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def act(self, kind: str, *, event_id: str | None = None, **args):
        self.calls.append(kind)
        return BodyActionResult(
            action_id=f"body-{len(self.calls)}",
            kind=kind,
            success=True,
            data={"dispatch_sent": True},
            event_id=event_id,
        )


class ApprovalCardStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = ApprovalCardStore(str(Path(self._tmp.name) / "test.db"))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_request_shows_action_target_scope_value_and_source(self) -> None:
        request = self.store.request_approval(
            action_kind="purchase",
            target="Acme Pro subscription",
            scope="billing:acme",
            value_text="$49 / month",
            source="routine",
        )
        self.assertEqual(request.status, "pending")
        self.assertEqual(request.action_kind, "purchase")
        self.assertEqual(request.target, "Acme Pro subscription")
        self.assertEqual(request.scope, "billing:acme")
        self.assertEqual(request.value_text, "$49 / month")
        self.assertEqual(request.source, "routine")
        # Unattended sources expire after 10 minutes.
        created = datetime.fromisoformat(request.created_at)
        expires = datetime.fromisoformat(request.expires_at)
        self.assertEqual(expires - created, timedelta(seconds=600))

    def test_duplicate_pending_request_is_reused_not_duplicated(self) -> None:
        first = self.store.request_approval(
            action_kind="send", target="team", scope="chat:team"
        )
        second = self.store.request_approval(
            action_kind="send", target="team", scope="chat:team"
        )
        self.assertEqual(first.request_id, second.request_id)
        self.assertEqual(len(self.store.pending_requests()), 1)

    def test_allow_once_approves_only_that_request(self) -> None:
        request = self.store.request_approval(
            action_kind="delete", target="old-report.pdf", scope="files:reports"
        )
        decided = self.store.decide(request.request_id, "allow_once")
        self.assertEqual(decided.status, "approved_once")
        self.assertEqual(self.store.list_rules(), [])

    def test_always_allow_approves_and_creates_narrow_rule(self) -> None:
        request = self.store.request_approval(
            action_kind="publish", target="blog post", scope="blog:site"
        )
        decided = self.store.decide(request.request_id, "always_allow")
        self.assertEqual(decided.status, "approved")
        rules = self.store.list_rules()
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].action_kind, "publish")
        self.assertEqual(rules[0].scope, "blog:site")
        self.assertEqual(rules[0].effect, "auto_allow")

    def test_deny_never_executes_and_blocks_the_gate(self) -> None:
        gate = ApprovalGate(self.store)
        first = gate.check(action_kind="delete", target="x", scope="files:x")
        self.assertFalse(first.allowed)
        self.store.decide(first.request_id, "deny")
        second = gate.check(action_kind="delete", target="x", scope="files:x")
        self.assertFalse(second.allowed)
        self.assertIn("denied", second.reason)

    def test_deny_outranks_auto_allow_rule(self) -> None:
        # A rule created after a deny must NOT silently unblock the denied
        # triple: rules are for future requests, not retroactive overrides.
        gate = ApprovalGate(self.store)
        first = gate.check(action_kind="delete", target="x", scope="files:x")
        self.store.decide(first.request_id, "deny")
        self.store.create_rule(
            action_kind="delete", scope="files:x", effect="auto_allow"
        )
        blocked = gate.check(action_kind="delete", target="x", scope="files:x")
        self.assertFalse(blocked.allowed)
        self.assertIn("denied", blocked.reason)

    def test_reconsider_denied_creates_fresh_pending_request(self) -> None:
        gate = ApprovalGate(self.store)
        first = gate.check(action_kind="delete", target="x", scope="files:x")
        self.store.decide(first.request_id, "deny")
        fresh = self.store.reconsider_denied(first.request_id)
        # The denied record is never mutated; the fresh request is a new id.
        self.assertNotEqual(fresh.request_id, first.request_id)
        self.assertEqual(fresh.status, "pending")
        self.assertEqual(fresh.action_kind, "delete")
        self.assertEqual(fresh.target, "x")
        self.assertEqual(fresh.scope, "files:x")
        denied = self.store.get_request(first.request_id)
        assert denied is not None
        self.assertEqual(denied.status, "denied")
        self.assertEqual(denied.decision, "deny")
        # The gate now sees the fresh pending request, not the deny.
        pending = gate.check(action_kind="delete", target="x", scope="files:x")
        self.assertFalse(pending.allowed)
        self.assertEqual(pending.request_id, fresh.request_id)
        self.assertIn("pending", pending.reason)
        # The fresh request can be decided normally.
        self.store.decide(fresh.request_id, "allow_once")
        allowed = gate.check(action_kind="delete", target="x", scope="files:x")
        self.assertTrue(allowed.allowed)

    def test_reconsider_denied_rejects_non_denied_requests(self) -> None:
        pending = self.store.request_approval(
            action_kind="send", target="team", scope="chat:team"
        )
        with self.assertRaises(ValueError):
            self.store.reconsider_denied(pending.request_id)
        approved = self.store.request_approval(
            action_kind="send", target="other", scope="chat:team"
        )
        self.store.decide(approved.request_id, "allow_once")
        with self.assertRaises(ValueError):
            self.store.reconsider_denied(approved.request_id)
        with self.assertRaises(ValueError):
            self.store.reconsider_denied("approval-does-not-exist")

    def test_reconsider_denied_is_audited(self) -> None:
        gate = ApprovalGate(self.store)
        first = gate.check(action_kind="delete", target="x", scope="files:x")
        self.store.decide(first.request_id, "deny")
        fresh = self.store.reconsider_denied(first.request_id, note="user changed mind")
        audit = self.store.list_audit()
        overridden = [entry for entry in audit if entry.decision == "deny_overridden"]
        self.assertEqual(len(overridden), 1)
        self.assertEqual(overridden[0].request_id, first.request_id)
        self.assertIn(fresh.request_id, overridden[0].note)
        self.assertIn("user changed mind", overridden[0].note)

    def test_reconsider_denied_can_be_denied_again(self) -> None:
        gate = ApprovalGate(self.store)
        first = gate.check(action_kind="delete", target="x", scope="files:x")
        self.store.decide(first.request_id, "deny")
        fresh = self.store.reconsider_denied(first.request_id)
        self.store.decide(fresh.request_id, "deny")
        blocked = gate.check(action_kind="delete", target="x", scope="files:x")
        self.assertFalse(blocked.allowed)
        self.assertIn("denied", blocked.reason)
        # A second explicit reconsideration works; each override is audited.
        second_fresh = self.store.reconsider_denied(fresh.request_id)
        self.assertEqual(second_fresh.status, "pending")
        audit = self.store.list_audit()
        overridden = [entry for entry in audit if entry.decision == "deny_overridden"]
        self.assertEqual(len(overridden), 2)

    def test_ask_first_beats_auto_allow_on_conflict(self) -> None:
        self.store.create_rule(action_kind="send", scope="chat:team", effect="auto_allow")
        self.store.create_rule(action_kind="send", scope="chat:team", effect="ask_first")
        self.assertEqual(
            self.store.evaluate(action_kind="send", scope="chat:team"), "ask_first"
        )

    def test_auto_allow_rule_lets_the_gate_through(self) -> None:
        self.store.create_rule(action_kind="send", scope="chat:team", effect="auto_allow")
        gate = ApprovalGate(self.store)
        outcome = gate.check(action_kind="send", target="team", scope="chat:team")
        self.assertTrue(outcome.allowed)
        self.assertEqual(self.store.pending_requests(), [])

    def test_broad_scopes_are_rejected(self) -> None:
        for scope in ("*", "browser", "browser.*", "everything", "all", ""):
            with self.assertRaises(ValueError, msg=scope):
                self.store.create_rule(
                    action_kind="send", scope=scope, effect="auto_allow"
                )
            with self.assertRaises(ValueError, msg=scope):
                self.store.request_approval(
                    action_kind="send", target="t", scope=scope
                )

    def test_unattended_request_expires_and_never_executes(self) -> None:
        now = datetime.now(timezone.utc)
        request = self.store.request_approval(
            action_kind="purchase",
            target="license",
            scope="billing:shop",
            source="routine",
            now=now,
        )
        self.assertEqual(self.store.expire_overdue(now=now + timedelta(seconds=601)), 1)
        expired = self.store.get_request(request.request_id)
        assert expired is not None
        self.assertEqual(expired.status, "expired")
        with self.assertRaises(ValueError):
            self.store.decide(request.request_id, "allow_once")
        gate = ApprovalGate(self.store)
        outcome = gate.check(
            action_kind="purchase", target="license", scope="billing:shop"
        )
        self.assertFalse(outcome.allowed)
        self.assertIn("expired", outcome.reason)

    def test_always_allow_from_expired_creates_rule_only(self) -> None:
        now = datetime.now(timezone.utc)
        request = self.store.request_approval(
            action_kind="purchase",
            target="license",
            scope="billing:shop",
            source="routine",
            now=now,
        )
        self.store.expire_overdue(now=now + timedelta(seconds=601))
        still = self.store.decide(request.request_id, "always_allow")
        self.assertEqual(still.status, "expired")
        rules = self.store.list_rules()
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].effect, "auto_allow")
        # The expired request itself never becomes executable...
        self.assertEqual(self.store.get_request(request.request_id).status, "expired")
        # ...but the rule the user just created applies to future requests.
        gate = ApprovalGate(self.store)
        outcome = gate.check(
            action_kind="purchase", target="license", scope="billing:shop"
        )
        self.assertTrue(outcome.allowed)
        self.assertEqual(self.store.get_request(request.request_id).status, "expired")

    def test_decisions_are_auditable(self) -> None:
        request = self.store.request_approval(
            action_kind="send", target="team", scope="chat:team"
        )
        self.store.decide(request.request_id, "deny")
        audit = self.store.list_audit()
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0].decision, "deny")
        self.assertEqual(audit[0].request_id, request.request_id)
        self.assertEqual(audit[0].action_kind, "send")

    # AP-1: feedback note recorded with a decision -------------------------
    def test_decide_deny_with_note_records_note_on_row_and_audit(self) -> None:
        request = self.store.request_approval(
            action_kind="send", target="team", scope="chat:team"
        )
        decided = self.store.decide(
            request.request_id, "deny", note="太贵了，换个方案"
        )
        self.assertEqual(decided.status, "denied")
        self.assertEqual(decided.decision_note, "太贵了，换个方案")
        # The note survives the DB round trip and shows in to_dict().
        reread = self.store.get_request(request.request_id)
        self.assertIsNotNone(reread)
        assert reread is not None
        self.assertEqual(reread.decision_note, "太贵了，换个方案")
        self.assertEqual(
            reread.to_dict()["decision_note"], "太贵了，换个方案"
        )
        audit = self.store.list_audit()
        self.assertEqual(len(audit), 1)
        self.assertIn("太贵了，换个方案", audit[0].note)

    def test_decide_without_note_leaves_row_and_audit_unchanged(self) -> None:
        # Lock: decisions without a note behave exactly as before.
        denied = self.store.request_approval(
            action_kind="send", target="team", scope="chat:team"
        )
        self.store.decide(denied.request_id, "deny")
        reread = self.store.get_request(denied.request_id)
        self.assertIsNotNone(reread)
        assert reread is not None
        self.assertEqual(reread.decision_note, "")
        audit = self.store.list_audit()
        self.assertEqual(audit[0].note, "")
        approved = self.store.request_approval(
            action_kind="delete", target="x", scope="files:x"
        )
        decided = self.store.decide(
            approved.request_id, "allow_once", edited_command="ls"
        )
        self.assertEqual(decided.decision_note, "")
        self.assertEqual(
            self.store.list_audit()[0].note, "command edited on approval"
        )

    def test_decide_note_is_collapsed_to_one_line(self) -> None:
        request = self.store.request_approval(
            action_kind="send", target="team", scope="chat:team"
        )
        decided = self.store.decide(
            request.request_id, "deny", note="  太贵\n了， 换方案  "
        )
        self.assertEqual(decided.decision_note, "太贵 了， 换方案")

    def test_decision_note_column_backfilled_on_old_databases(self) -> None:
        # A DB created before AP-1 lacks the column; reopening migrates it
        # and a note still round-trips.
        import sqlite3
        from contextlib import closing

        path = Path(self._tmp.name) / "old.db"
        old_store = ApprovalCardStore(str(path))
        request = old_store.request_approval(
            action_kind="send", target="team", scope="chat:team"
        )
        # NOTE: sqlite3's context manager only commits/rolls back; it does
        # NOT close the connection. The leaked handle blocks
        # TemporaryDirectory.cleanup() on Windows (WinError 32), so close
        # it deterministically with contextlib.closing.
        with closing(sqlite3.connect(path)) as conn:
            conn.execute("ALTER TABLE approval_requests DROP COLUMN decision_note")
            conn.commit()
        reopened = ApprovalCardStore(str(path))
        decided = reopened.decide(request.request_id, "deny", note="补测")
        self.assertEqual(decided.decision_note, "补测")

    def test_delete_rule(self) -> None:
        rule = self.store.create_rule(
            action_kind="send", scope="chat:team", effect="auto_allow"
        )
        self.assertTrue(self.store.delete_rule(rule.rule_id))
        self.assertEqual(self.store.list_rules(), [])
        self.assertFalse(self.store.delete_rule(rule.rule_id))


class ApprovalGateRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = ApprovalCardStore(str(Path(self._tmp.name) / "test.db"))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _runtime(self, *, with_gate: bool) -> ActionExecutionRuntime:
        registry = _registry(
            _descriptor("test.send", tags=("approval:send",)),
            _descriptor("test.plain"),
        )
        gate = ApprovalGate(self.store) if with_gate else None
        runtime = ActionExecutionRuntime(registry, _FakeBody(), approval_gate=gate)
        for action_id in ("test.send", "test.plain"):
            runtime.register_verification(
                action_id,
                observe=lambda request, result: ActionObservation(
                    request.action_id, "test", data={}
                ),
                verify=lambda request, observation, result: ActionVerification(
                    "verified", "test verifier confirmed the effect"
                ),
            )
        return runtime

    def test_untagged_action_executes_without_gate(self) -> None:
        runtime = self._runtime(with_gate=True)
        execution = runtime.execute(
            ActionRequest("test.plain", {"path": "a.txt"}, event_id="event-1")
        )
        self.assertTrue(execution.success)

    def test_tagged_action_blocks_and_creates_a_card(self) -> None:
        runtime = self._runtime(with_gate=True)
        execution = runtime.execute(
            ActionRequest(
                "test.send",
                {"approval_target": "team", "approval_scope": "chat:team"},
                event_id="event-1",
            )
        )
        self.assertFalse(execution.success)
        self.assertIn("approval_required", execution.error or "")
        pending = self.store.pending_requests()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].action_kind, "send")

    def test_tagged_action_proceeds_after_allow_once(self) -> None:
        runtime = self._runtime(with_gate=True)
        first = runtime.execute(
            ActionRequest(
                "test.send",
                {"approval_target": "team", "approval_scope": "chat:team"},
                event_id="event-1",
            )
        )
        self.assertFalse(first.success)
        request = self.store.pending_requests()[0]
        self.store.decide(request.request_id, "allow_once")
        second = runtime.execute(
            ActionRequest(
                "test.send",
                {"approval_target": "team", "approval_scope": "chat:team"},
                event_id="event-1",
            )
        )
        self.assertTrue(second.success)
        # allow_once is consumed: a third attempt blocks again.
        third = runtime.execute(
            ActionRequest(
                "test.send",
                {"approval_target": "team", "approval_scope": "chat:team"},
                event_id="event-1",
            )
        )
        self.assertFalse(third.success)

    def test_tagged_action_proceeds_with_auto_allow_rule(self) -> None:
        self.store.create_rule(
            action_kind="send", scope="chat:team", effect="auto_allow"
        )
        runtime = self._runtime(with_gate=True)
        execution = runtime.execute(
            ActionRequest(
                "test.send",
                {"approval_target": "team", "approval_scope": "chat:team"},
                event_id="event-1",
            )
        )
        self.assertTrue(execution.success)

    def test_no_gate_means_no_blocking(self) -> None:
        runtime = self._runtime(with_gate=False)
        execution = runtime.execute(
            ActionRequest(
                "test.send",
                {"approval_target": "team", "approval_scope": "chat:team"},
                event_id="event-1",
            )
        )
        self.assertTrue(execution.success)


class ApprovalKindTagTests(unittest.TestCase):
    def test_tag_parsing(self) -> None:
        self.assertEqual(approval_kind_for_tag(("approval:delete",)), "delete")
        self.assertEqual(approval_kind_for_tag(("other", "approval:send")), "send")
        self.assertIsNone(approval_kind_for_tag(("approval:everything",)))
        self.assertIsNone(approval_kind_for_tag(("approval:",)))
        self.assertIsNone(approval_kind_for_tag(()))


class ApprovalDaemonRpcTests(unittest.TestCase):
    def test_approval_rpc_round_trip_through_the_resident(self) -> None:
        import io
        from types import SimpleNamespace
        from unittest.mock import patch

        from zn_agent.core.daemon import ResidentRpcServer
        from zn_agent.core.provider_bridge import (
            build_resident_runtime_from_existing_stack,
        )

        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "zn_agent.core.life.shutil.disk_usage",
                return_value=SimpleNamespace(total=100, used=50, free=50),
            ):
                resident = build_resident_runtime_from_existing_stack(
                    config={"model": {}},
                    store_path=Path(tmp) / "kernel.db",
                )
                try:
                    server = ResidentRpcServer(
                        resident=resident,
                        input_stream=io.StringIO(),
                        output_stream=io.StringIO(),
                    )
                    created = server.handle(
                        {
                            "id": "1",
                            "method": "approval_request",
                            "params": {
                                "action_kind": "purchase",
                                "target": "Acme Pro",
                                "scope": "billing:acme",
                                "value_text": "$49 / month",
                                "source": "routine",
                            },
                        }
                    )
                    self.assertTrue(created["ok"], created)
                    request_id = created["result"]["request"]["request_id"]

                    listed = server.handle(
                        {"id": "2", "method": "approval_list", "params": {}}
                    )
                    self.assertTrue(listed["ok"], listed)
                    self.assertEqual(len(listed["result"]["pending"]), 1)

                    decided = server.handle(
                        {
                            "id": "3",
                            "method": "approval_decide",
                            "params": {"request_id": request_id, "decision": "always_allow"},
                        }
                    )
                    self.assertTrue(decided["ok"], decided)
                    self.assertEqual(decided["result"]["request"]["status"], "approved")

                    after = server.handle(
                        {"id": "4", "method": "approval_list", "params": {}}
                    )
                    self.assertEqual(after["result"]["pending"], [])
                    self.assertEqual(len(after["result"]["rules"]), 1)
                    rule_id = after["result"]["rules"][0]["rule_id"]

                    deleted = server.handle(
                        {
                            "id": "5",
                            "method": "approval_rule_delete",
                            "params": {"rule_id": rule_id},
                        }
                    )
                    self.assertTrue(deleted["ok"], deleted)

                    # A broad scope is rejected at the store (serve_forever
                    # wraps handle() errors into ok:false responses).
                    with self.assertRaises(ValueError):
                        server.handle(
                            {
                                "id": "6",
                                "method": "approval_rule_create",
                                "params": {
                                    "action_kind": "send",
                                    "scope": "browser",
                                    "effect": "auto_allow",
                                },
                            }
                        )
                finally:
                    resident.store.close()

    def test_approval_reconsider_denied_rpc_round_trip(self) -> None:
        import io
        from types import SimpleNamespace
        from unittest.mock import patch

        from zn_agent.core.daemon import ResidentRpcServer
        from zn_agent.core.provider_bridge import (
            build_resident_runtime_from_existing_stack,
        )

        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "zn_agent.core.life.shutil.disk_usage",
                return_value=SimpleNamespace(total=100, used=50, free=50),
            ):
                resident = build_resident_runtime_from_existing_stack(
                    config={"model": {}},
                    store_path=Path(tmp) / "kernel.db",
                )
                try:
                    server = ResidentRpcServer(
                        resident=resident,
                        input_stream=io.StringIO(),
                        output_stream=io.StringIO(),
                    )
                    created = server.handle(
                        {
                            "id": "1",
                            "method": "approval_request",
                            "params": {
                                "action_kind": "delete",
                                "target": "old-report.pdf",
                                "scope": "files:reports",
                                "source": "resident",
                            },
                        }
                    )
                    self.assertTrue(created["ok"], created)
                    denied_id = created["result"]["request"]["request_id"]

                    decided = server.handle(
                        {
                            "id": "2",
                            "method": "approval_decide",
                            "params": {"request_id": denied_id, "decision": "deny"},
                        }
                    )
                    self.assertTrue(decided["ok"], decided)
                    self.assertEqual(decided["result"]["request"]["status"], "denied")

                    listed = server.handle(
                        {"id": "3", "method": "approval_list", "params": {}}
                    )
                    self.assertTrue(listed["ok"], listed)
                    self.assertEqual(len(listed["result"]["denied"]), 1)
                    self.assertEqual(
                        listed["result"]["denied"][0]["request_id"], denied_id
                    )

                    reconsidered = server.handle(
                        {
                            "id": "4",
                            "method": "approval_reconsider_denied",
                            "params": {"request_id": denied_id, "note": "misclick"},
                        }
                    )
                    self.assertTrue(reconsidered["ok"], reconsidered)
                    fresh = reconsidered["result"]["request"]
                    self.assertEqual(fresh["status"], "pending")
                    self.assertNotEqual(fresh["request_id"], denied_id)

                    # The denied record itself is untouched by the override.
                    after = server.handle(
                        {"id": "5", "method": "approval_list", "params": {}}
                    )
                    self.assertEqual(len(after["result"]["pending"]), 1)
                    self.assertEqual(len(after["result"]["denied"]), 1)
                    audit = after["result"]["audit"]
                    self.assertTrue(
                        any(
                            entry["decision"] == "deny_overridden"
                            and entry["request_id"] == denied_id
                            for entry in audit
                        ),
                        audit,
                    )

                    # Reconsidering a non-denied request is rejected.
                    with self.assertRaises(ValueError):
                        server.handle(
                            {
                                "id": "6",
                                "method": "approval_reconsider_denied",
                                "params": {"request_id": fresh["request_id"]},
                            }
                        )
                finally:
                    resident.store.close()

    def test_approval_decide_note_round_trip_through_daemon(self) -> None:
        # AP-1: the daemon passes the note param through into the store; the
        # note is visible on the row and in the audit entry.
        import io
        from types import SimpleNamespace
        from unittest.mock import patch

        from zn_agent.core.daemon import ResidentRpcServer
        from zn_agent.core.provider_bridge import (
            build_resident_runtime_from_existing_stack,
        )

        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "zn_agent.core.life.shutil.disk_usage",
                return_value=SimpleNamespace(total=100, used=50, free=50),
            ):
                resident = build_resident_runtime_from_existing_stack(
                    config={"model": {}},
                    store_path=Path(tmp) / "kernel.db",
                )
                try:
                    server = ResidentRpcServer(
                        resident=resident,
                        input_stream=io.StringIO(),
                        output_stream=io.StringIO(),
                    )
                    created = server.handle(
                        {
                            "id": "1",
                            "method": "approval_request",
                            "params": {
                                "action_kind": "purchase",
                                "target": "Acme Pro",
                                "scope": "billing:acme",
                                "source": "resident",
                            },
                        }
                    )
                    self.assertTrue(created["ok"], created)
                    request_id = created["result"]["request"]["request_id"]

                    decided = server.handle(
                        {
                            "id": "2",
                            "method": "approval_decide",
                            "params": {
                                "request_id": request_id,
                                "decision": "deny",
                                "note": "太贵了",
                            },
                        }
                    )
                    self.assertTrue(decided["ok"], decided)
                    self.assertEqual(
                        decided["result"]["request"]["decision_note"], "太贵了"
                    )

                    # Without a note the params stay the old shape and the
                    # row shows an empty note.
                    created2 = server.handle(
                        {
                            "id": "3",
                            "method": "approval_request",
                            "params": {
                                "action_kind": "purchase",
                                "target": "Acme Plus",
                                "scope": "billing:acme",
                                "source": "resident",
                            },
                        }
                    )
                    request_id2 = created2["result"]["request"]["request_id"]
                    decided2 = server.handle(
                        {
                            "id": "4",
                            "method": "approval_decide",
                            "params": {"request_id": request_id2, "decision": "deny"},
                        }
                    )
                    self.assertTrue(decided2["ok"], decided2)
                    self.assertEqual(
                        decided2["result"]["request"]["decision_note"], ""
                    )
                finally:
                    resident.store.close()
