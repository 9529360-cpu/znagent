from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core import side_effect_attempts
from zn_agent.core.models import EventOutcome, ExecutionPath, WorkingState
from zn_agent.core.side_effect_body import SideEffectAwareBody
from zn_agent.core.side_effect_journal import ResidentSideEffectJournal
from zn_agent.core.store import KernelStore


class SideEffectAttemptPersistenceTests(unittest.TestCase):
    def test_historical_body_and_capability_signature_identities_remain_distinct(self):
        self.assertEqual(
            SideEffectAwareBody._signature_hash(
                "command",
                {"command": "echo once"},
            ),
            "a72d9ccf6f6fd6b527f36583bf8ec5dfe6e8a4dd57b75506ff79c20e01cec85b",
        )
        self.assertEqual(
            ResidentSideEffectJournal.signature_hash(
                "capability",
                {
                    "event_id": "evt-compat",
                    "capability_name": "known-local",
                },
            ),
            "c733b68ab4d0648c740f7a43ad8c6b8322a5e7b2bc8c852e5ceb856a5e5a7b5c",
        )
        self.assertNotEqual(
            SideEffectAwareBody._signature_hash(
                "capability",
                {
                    "event_id": "evt-compat",
                    "capability_name": "known-local",
                },
            ),
            ResidentSideEffectJournal.signature_hash(
                "capability",
                {
                    "event_id": "evt-compat",
                    "capability_name": "known-local",
                },
            ),
        )

    def test_body_and_capability_journal_share_one_attempt_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            body = SideEffectAwareBody(store=store)
            journal = ResidentSideEffectJournal(store)
            try:
                signature = body._signature_hash(
                    "command",
                    {"command": "echo shared-owner"},
                )
                body._start_attempt(
                    attempt_id="sidefx-shared-owner",
                    event_id="evt-shared-owner",
                    kind="command",
                    signature_hash=signature,
                )

                through_journal = journal.attempt("sidefx-shared-owner")
                self.assertIsNotNone(through_journal)
                assert through_journal is not None
                self.assertEqual(through_journal["event_id"], "evt-shared-owner")
                self.assertEqual(through_journal["signature_hash"], signature)
                self.assertEqual(through_journal["status"], "started")

                self.assertTrue(
                    body.resolve_uncertain_attempt(
                        "sidefx-shared-owner",
                        event_id="evt-shared-owner",
                        status="verified_effect",
                        evidence_action_id="observe-shared",
                    )
                )
                resolved = journal.attempt("sidefx-shared-owner")
                self.assertIsNotNone(resolved)
                assert resolved is not None
                self.assertEqual(resolved["status"], "verified_effect")
                self.assertEqual(resolved["result_action_id"], "observe-shared")
            finally:
                store.close()

    def test_pruning_and_raw_delete_never_remove_nonterminal_recovery_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KernelStore(Path(tmp) / "kernel.db")
            body = SideEffectAwareBody(store=store)
            journal = ResidentSideEffectJournal(store)
            try:
                # First create history that really is terminal and therefore may
                # be capacity-pruned after its EventOutcome is durable.
                terminal_event = body.store.get_event("evt-terminal-history")
                self.assertIsNone(terminal_event)
                from zn_agent.core.models import AgentEvent

                store.enqueue_event(
                    AgentEvent(
                        event_id="evt-terminal-history",
                        task="terminal side effect history",
                    )
                )
                claimed_terminal = store.claim_event("evt-terminal-history")
                self.assertIsNotNone(claimed_terminal)
                terminal_signature = body._signature_hash(
                    "command",
                    {"command": "echo terminal-history"},
                )
                body._start_attempt(
                    attempt_id="sidefx-terminal-history",
                    event_id="evt-terminal-history",
                    kind="command",
                    signature_hash=terminal_signature,
                )
                self.assertTrue(
                    body.resolve_uncertain_attempt(
                        "sidefx-terminal-history",
                        event_id="evt-terminal-history",
                        status="verified_effect",
                    )
                )
                store.complete_event(
                    EventOutcome(
                        event_id="evt-terminal-history",
                        success=True,
                        execution_path=ExecutionPath.BODY,
                        response="done",
                    )
                )

                # One active event owns both a Body recovery fact and a compiled
                # capability observed fact. Neither may be deleted before the
                # event becomes terminal, even with a zero history capacity.
                store.enqueue_event(
                    AgentEvent(
                        event_id="evt-active-recovery",
                        task="retain active recovery truth",
                    )
                )
                claimed_active = store.claim_event("evt-active-recovery")
                self.assertIsNotNone(claimed_active)

                active_signature = body._signature_hash(
                    "command",
                    {"command": "echo active-recovery"},
                )
                body._start_attempt(
                    attempt_id="sidefx-active-body",
                    event_id="evt-active-recovery",
                    kind="command",
                    signature_hash=active_signature,
                )
                self.assertTrue(
                    body.resolve_uncertain_attempt(
                        "sidefx-active-body",
                        event_id="evt-active-recovery",
                        status="verified_effect",
                    )
                )

                capability_signature = journal.signature_hash(
                    "capability",
                    {
                        "event_id": "evt-active-recovery",
                        "capability_name": "active-local",
                    },
                )
                state = WorkingState(
                    current_event_id="evt-active-recovery",
                    stage="native_capability",
                    next_action="active-local",
                    data={"capability_execution": {"status": "started"}},
                )
                journal.start_with_checkpoint(
                    attempt_id="capfx-active-observed",
                    event_id="evt-active-recovery",
                    kind="capability",
                    signature_hash=capability_signature,
                    state=state,
                )
                state.data["capability_execution"] = {"status": "observed"}
                journal.observe_with_checkpoint(
                    attempt_id="capfx-active-observed",
                    event_id="evt-active-recovery",
                    state=state,
                    success=True,
                )

                with closing(side_effect_attempts.connect(store.path)) as conn:
                    removed = side_effect_attempts.prune_terminal_attempts(
                        conn,
                        max_completed=0,
                    )
                    conn.commit()
                    self.assertEqual(removed, 1)
                    remaining = {
                        str(row["attempt_id"]): str(row["status"])
                        for row in conn.execute(
                            f"SELECT attempt_id,status FROM {side_effect_attempts.TABLE}"
                        ).fetchall()
                    }
                self.assertNotIn("sidefx-terminal-history", remaining)
                self.assertEqual(remaining["sidefx-active-body"], "verified_effect")
                self.assertEqual(remaining["capfx-active-observed"], "observed")

                # The schema itself fails safe if an older/direct caller issues
                # a generic DELETE that does not know the terminal-truth rule.
                with closing(side_effect_attempts.connect(store.path)) as conn:
                    conn.execute(
                        f"DELETE FROM {side_effect_attempts.TABLE} "
                        "WHERE event_id='evt-active-recovery'"
                    )
                    conn.commit()
                self.assertIsNotNone(journal.attempt("sidefx-active-body"))
                self.assertIsNotNone(journal.attempt("capfx-active-observed"))
                self.assertIsNone(store.get_event_outcome("evt-active-recovery"))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
