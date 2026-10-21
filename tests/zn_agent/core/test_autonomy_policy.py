from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from zn_agent.core import recurring_will_behavior
from zn_agent.core.autonomy_policy import (
    AUTONOMY_LEVELS,
    DEFAULT_LEVEL,
    OBSERVE_ONLY,
    REQUIRE_APPROVAL,
    SUGGEST,
    AutonomyPolicyStore,
    autonomy_domain_for_trigger_kind,
    connector_domain,
    may_materialize_next_task,
    normalize_level,
    validate_domain,
)
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack
from zn_agent.core.suggestions import SuggestionEngine
from zn_agent.core.work import ResidentWorkLedger


class AutonomyPolicyTests(unittest.TestCase):
    @staticmethod
    def _resident(db: Path):
        return build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=db,
        )

    @staticmethod
    def _engine(resident):
        return SuggestionEngine(resident, ResidentWorkLedger(resident))

    def test_default_level_is_require_approval_for_all_domains(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            try:
                policy = AutonomyPolicyStore(resident)
                for domain in (
                    "recurring.interval",
                    "recurring.cron",
                    "recurring.file_changed",
                    "connector.weather",
                    "connector.mail",
                    "some.unknown.domain",
                ):
                    self.assertEqual(
                        policy.get_level(domain),
                        REQUIRE_APPROVAL,
                        f"domain {domain} must fail closed",
                    )
                self.assertEqual(DEFAULT_LEVEL, REQUIRE_APPROVAL)
                self.assertEqual(len(AUTONOMY_LEVELS), 5)
            finally:
                resident.store.close()

    def test_set_level_roundtrip_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            resident = self._resident(db)
            try:
                policy = AutonomyPolicyStore(resident)
                record = policy.set_level("recurring.interval", OBSERVE_ONLY)
                self.assertEqual(record["domain"], "recurring.interval")
                self.assertEqual(record["level"], OBSERVE_ONLY)
                self.assertEqual(policy.get_level("recurring.interval"), OBSERVE_ONLY)
                # An untouched domain still fails closed.
                self.assertEqual(
                    policy.get_level("recurring.cron"), REQUIRE_APPROVAL
                )
            finally:
                resident.store.close()

            # Rebuild the resident on the same db: the policy survives restart.
            resident = self._resident(db)
            try:
                policy = AutonomyPolicyStore(resident)
                self.assertEqual(
                    policy.get_level("recurring.interval"), OBSERVE_ONLY
                )
                levels = {
                    item["domain"]: item["level"]
                    for item in policy.list_levels()
                }
                self.assertEqual(levels.get("recurring.interval"), OBSERVE_ONLY)
            finally:
                resident.store.close()

    def test_set_level_rejects_unknown_level_and_bad_domain(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            try:
                policy = AutonomyPolicyStore(resident)
                with self.assertRaises(ValueError):
                    policy.set_level("recurring.interval", "yolo_mode")
                with self.assertRaises(ValueError):
                    policy.set_level("", OBSERVE_ONLY)
                with self.assertRaises(ValueError):
                    policy.set_level("has spaces", OBSERVE_ONLY)
                # The failed writes stored nothing.
                self.assertEqual(policy.list_levels(), [])
            finally:
                resident.store.close()

    def test_level_helpers_fail_closed(self):
        self.assertEqual(normalize_level("bogus"), REQUIRE_APPROVAL)
        self.assertEqual(normalize_level(None), REQUIRE_APPROVAL)
        self.assertEqual(normalize_level("OBSERVE_ONLY"), OBSERVE_ONLY)
        # Only observe_only sits below suggest for the materialize gate.
        self.assertFalse(may_materialize_next_task(OBSERVE_ONLY))
        self.assertTrue(may_materialize_next_task(SUGGEST))
        self.assertTrue(may_materialize_next_task("prepare"))
        self.assertTrue(may_materialize_next_task("execute_reversible"))
        self.assertTrue(may_materialize_next_task(REQUIRE_APPROVAL))
        self.assertTrue(may_materialize_next_task("bogus"))

    def test_domain_helpers(self):
        self.assertEqual(
            autonomy_domain_for_trigger_kind("interval"), "recurring.interval"
        )
        self.assertEqual(
            autonomy_domain_for_trigger_kind("file_changed"),
            "recurring.file_changed",
        )
        self.assertEqual(connector_domain("weather"), "connector.weather")
        self.assertEqual(connector_domain("web_search"), "connector.web_search")
        with self.assertRaises(ValueError):
            validate_domain("UPPER IS FINE? no")

    def _due_intention(self, resident, now):
        return resident.schedule_recurring_intention(
            "periodically check one durable goal",
            task="recheck the durable goal from fresh evidence",
            interval_seconds=60,
            source="user",
            first_due_at=now - timedelta(seconds=1),
        )

    def test_observe_only_gate_routes_due_trigger_to_suggestion_bar(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            try:
                now = datetime.now(timezone.utc)
                intention = self._due_intention(resident, now)
                AutonomyPolicyStore(resident).set_level(
                    "recurring.interval", OBSERVE_ONLY
                )

                activated = resident.recurring_will.activate_due(now=now)
                self.assertEqual(len(activated), 1)

                # The occurrence did NOT become a Will next_task.
                ready = resident.will.get(intention.intention_id)
                self.assertIsNotNone(ready)
                assert ready is not None
                self.assertIsNone(ready.next_task)

                # The pending stamp was cleared exactly like a handoff:
                # the slot is neither lost nor retried.
                trigger = resident.recurring_will.get(intention.intention_id)
                self.assertIsNotNone(trigger)
                assert trigger is not None
                self.assertIsNone(trigger.pending_scheduled_at)

                # The occurrence is in the P1-1 suggestion bar instead.
                engine = self._engine(resident)
                gated = [
                    item
                    for item in engine.list_suggestions()
                    if item["kind"] == "autonomy_gated"
                ]
                self.assertEqual(len(gated), 1)
                item = gated[0]
                self.assertEqual(
                    item["task"], "recheck the durable goal from fresh evidence"
                )
                self.assertIsNone(item["thread_id"])
                self.assertEqual(item["source"]["type"], "autonomy_gate")
                self.assertEqual(item["source"]["domain"], "recurring.interval")
                self.assertEqual(item["source"]["level"], OBSERVE_ONLY)
                self.assertEqual(
                    item["source"]["intention_id"], intention.intention_id
                )
            finally:
                resident.store.close()

    def test_gated_occurrence_dedup_and_dismissal(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            try:
                policy = AutonomyPolicyStore(resident)
                stamp = datetime.now(timezone.utc).isoformat()
                key_a = policy.record_gated_occurrence(
                    intention_id="intent-1",
                    task="check the goal",
                    domain="recurring.interval",
                    level=OBSERVE_ONLY,
                    scheduled_at=stamp,
                )
                # Recording the same occurrence twice never pushes a duplicate.
                key_b = policy.record_gated_occurrence(
                    intention_id="intent-1",
                    task="check the goal",
                    domain="recurring.interval",
                    level=OBSERVE_ONLY,
                    scheduled_at=stamp,
                )
                self.assertEqual(key_a, key_b)

                engine = self._engine(resident)
                gated = [
                    item
                    for item in engine.list_suggestions()
                    if item["kind"] == "autonomy_gated"
                ]
                self.assertEqual(len(gated), 1)
                self.assertEqual(gated[0]["key"], key_a)

                # A different occurrence gets its own stable key.
                policy.record_gated_occurrence(
                    intention_id="intent-1",
                    task="check the goal",
                    domain="recurring.interval",
                    level=OBSERVE_ONLY,
                    scheduled_at=datetime.now(timezone.utc).isoformat(),
                )
                gated = [
                    item
                    for item in engine.list_suggestions()
                    if item["kind"] == "autonomy_gated"
                ]
                self.assertEqual(len(gated), 2)

                # P1-1 dismissal semantics: dismissed, never pushed again.
                engine.dismiss(key_a)
                remaining = [
                    item
                    for item in engine.list_suggestions()
                    if item["kind"] == "autonomy_gated"
                ]
                self.assertEqual(len(remaining), 1)
                self.assertNotEqual(remaining[0]["key"], key_a)
            finally:
                resident.store.close()

    def test_suggest_level_and_default_materialize_normally(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            try:
                now = datetime.now(timezone.utc)
                policy = AutonomyPolicyStore(resident)

                policy.set_level("recurring.interval", SUGGEST)
                intention = self._due_intention(resident, now)
                activated = resident.recurring_will.activate_due(now=now)
                self.assertEqual(len(activated), 1)
                ready = resident.will.get(intention.intention_id)
                self.assertIsNotNone(ready)
                assert ready is not None
                self.assertEqual(
                    ready.next_task,
                    "recheck the durable goal from fresh evidence",
                )

                # Default require_approval also materializes: materialize
                # is scheduling, not execution; approval gates execution.
                policy.set_level("recurring.interval", REQUIRE_APPROVAL)
                intention2 = self._due_intention(resident, now)
                activated = resident.recurring_will.activate_due(now=now)
                self.assertEqual(len(activated), 1)
                ready2 = resident.will.get(intention2.intention_id)
                self.assertIsNotNone(ready2)
                assert ready2 is not None
                self.assertEqual(
                    ready2.next_task,
                    "recheck the durable goal from fresh evidence",
                )
            finally:
                resident.store.close()

    def test_fail_closed_when_policy_store_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            try:
                now = datetime.now(timezone.utc)
                intention = self._due_intention(resident, now)
                with mock.patch.object(
                    recurring_will_behavior,
                    "AutonomyPolicyStore",
                    side_effect=RuntimeError("simulated policy store failure"),
                ):
                    activated = resident.recurring_will.activate_due(now=now)
                # Fail closed: treated as require_approval, which still
                # materializes (scheduling is not execution).
                self.assertEqual(len(activated), 1)
                ready = resident.will.get(intention.intention_id)
                self.assertIsNotNone(ready)
                assert ready is not None
                self.assertEqual(
                    ready.next_task,
                    "recheck the durable goal from fresh evidence",
                )
                # Nothing was routed to the suggestion bar.
                engine = self._engine(resident)
                gated = [
                    item
                    for item in engine.list_suggestions()
                    if item["kind"] == "autonomy_gated"
                ]
                self.assertEqual(gated, [])
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
