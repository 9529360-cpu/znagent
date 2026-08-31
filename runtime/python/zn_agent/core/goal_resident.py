from __future__ import annotations

"""Resident-owned continuation for bounded multi-step world-state goals.

A verified Body movement is not automatically a completed user goal. This layer
keeps one typed composite repository goal alive across multiple verified
movements, clears stale action evidence after each substep, and forces a fresh
Investigation before deciding what to do next. It deliberately owns no generic
planner and stores no replayable action sequence.
"""

from typing import Any

from .repo_goal import (
    repo_text_staged_action_intents,
    repo_text_staged_request,
    repo_text_staged_state,
)
from .repo_test_resident import RepositoryVerifyingResidentRuntime
from .models import utc_now


class ResidentGoalRuntime(RepositoryVerifyingResidentRuntime):
    """Continue one typed goal until fresh reality proves the whole goal complete."""

    _RESIDENT_GOAL_PROGRESS_KEY = "resident_goal_progress"
    _MAX_RESIDENT_GOAL_PROGRESS = 16

    def _deliberation_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        request = repo_text_staged_request(event)
        if request is None:
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        investigation = self.investigator.current(event.event_id)
        facts = dict(investigation.facts) if investigation is not None else {}
        goal_state = repo_text_staged_state(event, facts)
        intents = repo_text_staged_action_intents(event, facts)

        if goal_state is not None and goal_state.get("satisfied"):
            # The normal path should have resolved during Investigation as soon as
            # fresh text + Git facts proved the whole goal. If a persisted older
            # Investigation reaches deliberation with the same facts, re-enter
            # Investigation rather than manufacturing completion here.
            state.stage = "native_investigation"
            state.next_action = "reconfirm the complete resident goal from current reality"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        if intents:
            intent = intents[0]
            if not self._action_blocked_by_current_evidence(event, state, intent):
                self._begin_native_action_cycle(event, state, intent)
                self.store.save_working_state(state)
                if thought is not None:
                    action = f"perform goal substep through body: {intent.kind}"
                    if action not in thought.possible_actions:
                        thought.possible_actions = (*thought.possible_actions, action)
                    known = (
                        "the current resident goal still has an independently observable "
                        "unsatisfied subcondition"
                    )
                    if known not in thought.known:
                        thought.known = (*thought.known, known)
                    thought.reason = (
                        f"{thought.reason}; current evidence formed one bounded next movement "
                        "without precommitting the later goal steps"
                    )
                    self._persist_enriched_thought(thought)
                return None

        blocked = str((goal_state or {}).get("blocked") or "").strip()
        reason = blocked or (
            "current Investigation exhausted its probes without proving a safe next "
            "movement for the typed resident goal"
        )
        self.life.begin_impasse(
            event,
            reason=reason,
            required_capabilities=self._required_capabilities(event),
            local_failure=None,
        )
        return self._checkpoint_terminal_failure(event, state, reason=reason)

    def _complete_successful_body_action(
        self,
        event,
        state,
        intent,
        *,
        response: str,
        reason: str,
    ):
        """Treat a verified movement as progress until the composite goal is re-sensed."""

        if repo_text_staged_request(event) is None:
            return super()._complete_successful_body_action(
                event,
                state,
                intent,
                response=response,
                reason=reason,
            )

        verification = state.data.get("native_verification_result")
        if not isinstance(verification, dict) or verification.get("verified") is not True:
            return super()._complete_successful_body_action(
                event,
                state,
                intent,
                response=response,
                reason=reason,
            )

        latest = state.data.get("latest_verified_experience")
        experience_id = (
            str(latest.get("experience_id") or "").strip()
            if isinstance(latest, dict)
            else ""
        )
        raw_progress = state.data.get(self._RESIDENT_GOAL_PROGRESS_KEY)
        progress = list(raw_progress) if isinstance(raw_progress, list) else []
        progress.append(
            {
                "action_kind": str(intent.kind or ""),
                "verification_kind": str(verification.get("kind") or ""),
                "experience_id": experience_id or None,
                "verified_at": utc_now(),
            }
        )
        state.data[self._RESIDENT_GOAL_PROGRESS_KEY] = progress[
            -self._MAX_RESIDENT_GOAL_PROGRESS :
        ]

        self._reset_investigation_after_goal_substep(event, state, intent)
        state.stage = "native_investigation"
        state.next_action = "re-sense the composite goal after the verified substep"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _reset_investigation_after_goal_substep(self, event, state, intent) -> None:
        investigation = self.investigator.current(event.event_id)
        if investigation is not None:
            investigation.updated_at = utc_now()
            investigation.probes = ()
            investigation.probe_keys = ()
            investigation.facts = {}
            investigation.unresolved = None
            investigation.next_probe = None
            investigation.status = "open"
            investigation.resolution = None
            investigation.evidence = (
                *investigation.evidence,
                f"verified resident-goal substep completed: {intent.kind}; re-sensing current reality",
            )[-64:]
            self.investigator._save(investigation)

        for key in (
            "native_investigation",
            "native_deliberation",
            "native_action_intent",
            "native_action_result",
            "native_verification",
            "native_verification_result",
            "native_completion",
            "local_failure",
            self._REPO_TEXT_BASELINE_KEY,
            self._TARGETED_TEST_EXECUTION_KEY,
            self._PROCEDURAL_INFLUENCE_KEY,
        ):
            state.data.pop(key, None)
