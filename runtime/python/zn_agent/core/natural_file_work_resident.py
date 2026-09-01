from __future__ import annotations

"""Bounded ordinary-language workspace file discovery and edit grounding."""

import re
from dataclasses import replace
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
from .user_browser_managed_research_resident import UserBrowserManagedResearchResidentRuntime


_BROWSER_FILE_HINT = re.compile(
    r"名字(?:里)?(?:像|包含|带有|带)\s*[\"“'‘]?(?P<v>[^\"”'’‘，,。；;\r\n]{1,64}?)[\"”'’]?\s*"
    r"的(?:那个|那份|那个文件|文件)?\s*\.?\s*txt(?=[，,。；;\s]|$)",
    re.I,
)
_BROWSER_FILE_SOURCE = re.compile(
    r"把\s*[\"“'‘]?(?P<v>[^\"”'’‘，,。；;\r\n]{1,128}?)[\"”'’]?\s*改成\s*"
    r"(?:查到的|确认的|研究得到的|刚查到的|刚确认的)?\s*(?:release\s+code|代码)",
    re.I,
)


class NaturalFileWorkResidentRuntime(UserBrowserManagedResearchResidentRuntime):
    """Ground ordinary Work file edits into the existing Body lifecycle.

    This layer owns no planner and no mutation primitive. It closes two bounded
    language-to-evidence gaps:

    * discover/compare one exact workspace file before using ``write_text``;
    * for one browser+file task, reuse the existing managed-reference research
      path to establish a release code, then feed that fact into the same file
      grounding and verified overwrite path.

    The inherited overwrite Body still owns atomic save, durable side-effect
    accounting, non-replay recovery, and postcondition verification.
    """

    _NATURAL_FILE_PROBE_LABELS = (
        "enumerate bounded workspace file candidates",
        "compare plausible workspace file contents",
        "freshly read the exact selected workspace file",
    )
    _BROWSER_FILE_RESEARCH_STATE_KEY = "resident_browser_result_file_edit"

    @classmethod
    def _natural_browser_result_file_request(cls, event) -> dict[str, str] | None:
        payload = event.payload or {}
        task = " ".join(str(event.task or "").strip().split())
        lowered = task.lower()
        if (
            str(event.kind or "").lower() != "desktop_user_event"
            or not str(payload.get("workspace_path") or "").strip()
            or payload.get("body_action")
            or payload.get("native_action")
            or "昨天" not in task
            or "保存" not in task
            or not any(cue in task for cue in ("读回来", "读回确认", "重新读", "确认"))
            or not ("reference" in lowered or "参考" in task)
            or not ("release code" in lowered or "代码" in task)
        ):
            return None
        hint = _BROWSER_FILE_HINT.search(task)
        source = _BROWSER_FILE_SOURCE.search(task)
        if hint is None or source is None:
            return None
        name_hint = hint.group("v").strip()
        old_text = source.group("v").strip()
        if not name_hint or not old_text:
            return None
        return {
            "workspace_path": str(payload["workspace_path"]),
            "name_hint": name_hint,
            "old_text": old_text,
        }

    @classmethod
    def _required_capabilities(cls, event) -> tuple[str, ...]:
        if (
            (event.payload or {}).get("required_capabilities") is None
            and cls._natural_browser_result_file_request(event) is not None
        ):
            return ("browser",)
        return super()._required_capabilities(event)

    def _deliberation_step(
        self,
        event,
        state: WorkingState,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        effective_event = event
        browser_file_request = self._natural_browser_result_file_request(event)
        if browser_file_request is not None:
            prepared = self._prepare_browser_result_file_event(
                event,
                state,
                browser_file_request,
                thought=thought,
            )
            if prepared is None:
                return None
            if isinstance(prepared, str):
                return self._checkpoint_terminal_failure(event, state, reason=prepared)
            effective_event = prepared

        request = natural_workspace_text_edit_request(effective_event)
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

        discovery, notes = observe_candidates(effective_event, self.body)
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
            comparison, notes = compare_candidates(effective_event, self.body, discovery)
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
            target_read, preview, notes = read_target(effective_event, self.body, comparison)
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

        failure = failure_reason(effective_event, facts)
        intent = edit_intent(effective_event, facts)

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
            reason = (
                "the exact file edit remains blocked by unchanged failure evidence; "
                "ZN will not replay it"
            )
            return self._checkpoint_terminal_failure(event, state, reason=reason)

        self._begin_native_action_cycle(event, state, intent)
        self.store.save_working_state(state)
        if thought is not None:
            action = "perform body action: write_text"
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
            if browser_file_request is not None:
                thought.reason = (
                    f"{thought.reason}; two managed-browser sources established the replacement value, "
                    "then fresh bounded file evidence supported one exact overwrite"
                )
            else:
                thought.reason = (
                    f"{thought.reason}; fresh bounded file evidence supports one exact overwrite"
                )
            self._persist_enriched_thought(thought)
        return None

    def _prepare_browser_result_file_event(
        self,
        event,
        state: WorkingState,
        request: dict[str, str],
        *,
        thought=None,
    ):
        raw = state.data.get(self._BROWSER_FILE_RESEARCH_STATE_KEY)
        if isinstance(raw, dict) and str(raw.get("release_code") or "").strip():
            evidence = raw
        else:
            if self.user_browser_extension.authorized_tab() is None:
                return (
                    "browser+file work requires one current browser tab explicitly authorized "
                    "through the ZN browser bridge"
                )
            try:
                initial = self._discover_authorized_reference_context()
                references = self._rank_reference_candidates(initial.get("references"))
                if len(references) < 2:
                    raise RuntimeError(
                        "the authorized page did not expose at least two bounded reference candidates"
                    )
                research = self._research_managed_references(references)
                fresh_tab = self.probe_user_browser_extension_tab()
            except Exception as exc:
                return (
                    "ZN could not establish the browser evidence needed for the file edit: "
                    f"{type(exc).__name__}: {exc}"
                )
            release_code = str(research.get("release_code") or "").strip()
            sources = research.get("sources")
            if not release_code or not isinstance(sources, list) or len(sources) < 2:
                return "managed browser research did not establish two-source agreement on one release code"
            evidence = {
                "release_code": release_code,
                "sources": sources,
                "initial_authorized_page": {
                    "url": str(initial.get("url") or ""),
                    "title": str(initial.get("title") or ""),
                    "observed_at": str(initial.get("observed_at") or ""),
                },
                "fresh_authorized_page": {
                    "url": str(fresh_tab.get("url") or ""),
                    "title": str(fresh_tab.get("title") or ""),
                    "observed_at": str(fresh_tab.get("observed_at") or ""),
                },
            }
            state.data[self._BROWSER_FILE_RESEARCH_STATE_KEY] = evidence
            state.data.pop("local_failure", None)
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            if thought is not None:
                known = (
                    "two independently observed managed-browser sources agreed on one release code "
                    "before ZN touched the workspace file"
                )
                if known not in thought.known:
                    thought.known = (*thought.known, known)
                thought.reason = (
                    f"{thought.reason}; browser investigation produced evidence only, not mutation authority"
                )
                self._persist_enriched_thought(thought)

        release_code = str(evidence.get("release_code") or "").strip()
        if not release_code:
            return "durable browser research evidence no longer contains a usable release code"
        synthetic_task = (
            f"找到这里昨天改过、名字像{request['name_hint']}的那个 txt，"
            f"把{request['old_text']}改成{release_code}，保存后再读回来确认"
        )
        return replace(event, task=synthetic_task)

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
