from __future__ import annotations

"""Bounded ordinary-language workspace file discovery and edit grounding."""

from typing import Any

from .investigation import InvestigationResult
from .models import WorkingState, utc_now
from .natural_file_goal import (
    compare_candidates,
    edit_intent,
    failure_reason,
    natural_workspace_text_edit_request,
    observe_candidates,
    read_target,
)
from .user_browser_extension_resident import UserBrowserExtensionResidentRuntime


class NaturalFileWorkResidentRuntime(UserBrowserExtensionResidentRuntime):
    """Ground ordinary workspace file edits into the existing Body lifecycle.

    This layer owns no planner and no mutation primitive. It discovers and compares
    bounded workspace candidates, binds one exact file from fresh evidence, then
    reuses the existing atomic overwrite Body and postcondition verification.
    """

    _NATURAL_FILE_PROBE_LABELS = (
        "enumerate bounded workspace file candidates",
        "compare plausible workspace file contents",
        "freshly read the exact selected workspace file",
    )
    def _deliberation_step(
        self,
        event,
        state: WorkingState,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        request = natural_workspace_text_edit_request(event)
        if request is None:
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        investigation = self.investigator.current(event.event_id)
        if investigation is None:
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        facts = dict(investigation.facts)
        evidence = list(investigation.evidence)
        probes = list(investigation.probes)
        probe_keys = list(investigation.probe_keys)

        discovery, notes = observe_candidates(event, self.body)
        facts["natural_file_candidates"] = discovery
        self._record_probe(
            evidence,
            probes,
            probe_keys,
            key="natural_file_candidates",
            label=self._NATURAL_FILE_PROBE_LABELS[0],
            notes=notes,
        )

        comparison: dict[str, Any] = {
            "complete": False,
            "selected": None,
            "failure_reason": str(discovery.get("failure_reason") or ""),
        }
        if discovery.get("ready") is True:
            comparison, notes = compare_candidates(event, self.body, discovery)
            self._record_probe(
                evidence,
                probes,
                probe_keys,
                key="natural_file_candidate_comparison",
                label=self._NATURAL_FILE_PROBE_LABELS[1],
                notes=notes,
            )
        facts["natural_file_candidate_comparison"] = comparison

        target_read: dict[str, Any] = {
            "complete": False,
            "failure_reason": str(comparison.get("failure_reason") or ""),
        }
        selected = comparison.get("selected")
        if isinstance(selected, dict):
            target_read, preview, notes = read_target(event, self.body, comparison)
            self._record_probe(
                evidence,
                probes,
                probe_keys,
                key="natural_file_target_read",
                label=self._NATURAL_FILE_PROBE_LABELS[2],
                notes=notes,
            )
            if isinstance(preview, dict):
                facts["file_previews"] = [preview]
                identity = target_read.get("identity")
                if isinstance(identity, dict):
                    facts["natural_file_identity"] = identity
        facts["natural_file_target_read"] = target_read

        failure = failure_reason(event, facts)
        intent = edit_intent(event, facts)

        investigation.facts = facts
        investigation.evidence = tuple(evidence[-96:])
        investigation.probes = tuple(probes[-32:])
        investigation.probe_keys = tuple(probe_keys[-32:])
        investigation.updated_at = utc_now()
        investigation.rounds += 1
        investigation.next_probe = None
        investigation.unresolved = failure
        self.investigator._save(investigation)
        state.data["native_investigation"] = self._investigation_data(investigation)
        self._merge_investigation_into_thought(
            thought,
            InvestigationResult(state=investigation),
        )

        if intent is None:
            reason = failure or (
                "bounded workspace evidence did not establish one exact safe edit target"
            )
            if thought is not None:
                if reason not in thought.unknown:
                    thought.unknown = (*thought.unknown, reason)
                thought.reason = (
                    f"{thought.reason}; filesystem evidence is insufficient for a safe edit"
                )
                self._persist_enriched_thought(thought)
            return self._checkpoint_terminal_failure(event, state, reason=reason)

        if self._action_blocked_by_current_evidence(event, state, intent):
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "the exact file edit remains blocked by unchanged failure evidence; "
                    "ZN will not replay it"
                ),
            )

        self._begin_native_action_cycle(event, state, intent)
        self.store.save_working_state(state)
        if thought is not None:
            action = "perform body action: write_text"
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
            thought.reason = (
                f"{thought.reason}; fresh bounded file evidence supports one exact overwrite"
            )
            self._persist_enriched_thought(thought)
        return None

    def _prepare_overwrite_prestate(
        self,
        event,
        state,
        intent,
        *,
        thought=None,
    ) -> bool:
        expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        investigation_identity = expected.get("precondition_file_identity")
        if isinstance(investigation_identity, dict):
            raw = state.data.get(self._OVERWRITE_PRESTATE_KEY)
            same_intent = bool(
                isinstance(raw, dict)
                and str(raw.get("intent_id") or "") == intent.intent_id
                and str(raw.get("action_signature") or "") == self._intent_signature(intent)
            )
            if not same_intent:
                state.data[self._OVERWRITE_PRESTATE_KEY] = {
                    "intent_id": intent.intent_id,
                    "action_signature": self._intent_signature(intent),
                    "identity": dict(investigation_identity),
                }
                state.data.pop(self._OVERWRITE_PRESTATE_RECHECK_KEY, None)
        return super()._prepare_overwrite_prestate(
            event,
            state,
            intent,
            thought=thought,
        )

    def _native_action_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        result = super()._native_action_step(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )
        if result is not None:
            return result

        raw_intent = state.data.get("native_action_intent")
        if not isinstance(raw_intent, dict):
            return None
        expected = raw_intent.get("expected_outcome")
        if not isinstance(expected, dict) or not isinstance(
            expected.get("precondition_file_identity"),
            dict,
        ):
            return None
        if state.stage != "native_investigation":
            return None
        failure = str(state.data.get("local_failure") or "").strip()
        if "identity no longer matches" not in failure:
            return None
        return self._checkpoint_terminal_failure(event, state, reason=failure)

    @staticmethod
    def _record_probe(
        evidence: list[str],
        probes: list[str],
        probe_keys: list[str],
        *,
        key: str,
        label: str,
        notes: list[str],
    ) -> None:
        if label not in probes:
            probes.append(label)
        probe_keys.append(key)
        for note in notes:
            text = str(note or "").strip()
            if text and text not in evidence:
                evidence.append(text)
