from __future__ import annotations

"""Resident-owned continuation for bounded multi-step world-state goals.

A verified Body movement is not automatically a completed user goal. This layer
keeps one typed composite repository goal alive across multiple verified
movements, clears stale action evidence after each substep, and forces a fresh
Investigation before deciding what to do next. It deliberately owns no generic
planner and stores no replayable action sequence.
"""

from dataclasses import replace
from typing import Any

from .models import ExecutionPath, utc_now
from .repo_goal import (
    repo_text_staged_action_intents,
    repo_text_staged_request,
    repo_text_staged_state,
)
from .repo_test_resident import RepositoryVerifyingResidentRuntime


class ResidentGoalRuntime(RepositoryVerifyingResidentRuntime):
    """Continue one typed goal until fresh reality proves the whole goal complete."""

    _RESIDENT_GOAL_PROGRESS_KEY = "resident_goal_progress"
    _MAX_RESIDENT_GOAL_PROGRESS = 16

    def _investigation_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        """Do not let a satisfied subcondition terminate a composite goal."""

        if repo_text_staged_request(event) is None:
            return super()._investigation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        local_failure = str(state.data.get("local_failure") or "").strip() or None
        investigation = self.investigator.investigate(
            event,
            readiness,
            learning_evidence=learning_evidence,
            local_failure=local_failure,
        )
        goal_state = repo_text_staged_state(event, investigation.state.facts)

        # The generic investigator can truthfully answer a narrower subquestion,
        # such as "the exact text is already present". For a composite user goal
        # that is progress, not completion. Re-open the same durable Investigation
        # and let current evidence choose the next probe instead of publishing a
        # false terminal outcome.
        if investigation.resolved and not bool(goal_state and goal_state.get("satisfied")):
            following = self.investigator._choose_next_probe(
                event,
                readiness,
                facts=investigation.state.facts,
                performed=set(investigation.state.probe_keys),
                learning_evidence=learning_evidence,
            )
            investigation.state.status = "open"
            investigation.state.resolution = None
            investigation.state.unresolved = (
                str((goal_state or {}).get("blocked") or "").strip()
                or "the complete resident goal still has an unsatisfied subcondition"
            )
            investigation.state.next_probe = following
            investigation.state.updated_at = utc_now()
            self.investigator._save(investigation.state)
            investigation.resolved = False
            investigation.response = ""
            investigation.can_continue = bool(following)

        state.data["native_investigation"] = self._investigation_data(investigation.state)
        self._merge_investigation_into_thought(thought, investigation)
        if thought is not None:
            self._persist_enriched_thought(thought)

        goal_state = repo_text_staged_state(event, investigation.state.facts)
        if goal_state is not None and goal_state.get("satisfied"):
            domains = self.kernel.self_model.observe_native_outcome(
                event.task,
                self._required_capabilities(event),
                success=True,
                quality=0.95,
            )
            completion = {
                "execution_path": ExecutionPath.INVESTIGATION.value,
                "success": True,
                "response": (
                    f"{goal_state['path']}: requested repository text and staged state "
                    "are both satisfied"
                ),
                "model_invocations": 0,
                "reason": (
                    "ZN completed the multi-step resident goal only after fresh file-content "
                    "and structured Git observations simultaneously proved the final state"
                ),
            }
            state.stage = "investigation_completion"
            state.next_action = "publish terminal EventOutcome"
            state.data["native_domains"] = list(domains)
            state.data["investigation_completion"] = completion
            self.store.record_runtime_task(model_invocations=0)
            self.store.save_working_state(state)
            return self._investigation_completion_result(event, completion)

        if investigation.can_continue:
            state.stage = "native_investigation"
            state.next_action = f"run native probe {investigation.state.next_probe}"
            self.store.save_working_state(state)
            return None

        state.stage = "native_deliberation"
        state.next_action = "form the next bounded movement from current goal evidence"
        self.store.save_working_state(state)
        return None

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
            # A persisted older state may reach deliberation with complete facts.
            # Re-enter Investigation so the normal evidence-owned completion path
            # publishes the result rather than manufacturing completion here.
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

    def _verification_contract(self, event, intent, *, result=None):
        """Map a composite staging substep back onto the existing typed Git verifier."""

        request = repo_text_staged_request(event)
        raw_goal = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        if (
            request is not None
            and intent.kind == "command"
            and intent.source == "resident_choice"
            and str(raw_goal.get("kind") or "").strip().lower() == "git_path_staged"
        ):
            staged_event = replace(
                event,
                payload={
                    **dict(event.payload or {}),
                    "expected_outcome": {
                        "kind": "git_path_staged",
                        "path": request["path"],
                    },
                },
            )
            return super()._verification_contract(
                staged_event,
                intent,
                result=result,
            )
        return super()._verification_contract(event, intent, result=result)

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
