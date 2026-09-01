from __future__ import annotations

"""Natural Work: authorized browser research -> current desktop app -> verified result."""

import hashlib
import uuid
from dataclasses import replace
from typing import Any, Mapping

from .action import NativeActionIntent
from .keyboard_text_body import KeyboardTextBody
from .models import WorkingState, utc_now
from .natural_file_desktop_submit_resident import (
    NaturalFileDesktopSubmitResidentRuntime,
    _BUTTON_RE,
    _RESULT_TITLE_RE,
)
from .user_browser_extension_relay import UserBrowserExtensionRelayError


class NaturalBrowserDesktopSubmitResidentRuntime(NaturalFileDesktopSubmitResidentRuntime):
    """Close one browser-investigation -> desktop-action Work in the same resident.

    Browser research decides only the bounded value to carry forward. It does not
    create desktop target authority. After managed Chromium has independently
    observed two agreeing reference sources, ZN freshly re-senses the authorized
    USER browser tab, then separately grounds the *current* non-browser foreground
    application and focused Edit. The release code is not persisted in the
    keyboard action intent; only its digest/length and exact desktop scopes are.

    Verified text entry is progress, not completion. The inherited desktop-submit
    lifecycle then freshly finds one exact named Button, revalidates it at the
    final pointer boundary, sends at most one non-replayable click, and completes
    only after a fresh exact foreground process/title observation.
    """

    _BROWSER_DESKTOP_RESEARCH_STATE_KEY = "natural_browser_desktop_research"
    _BROWSER_DESKTOP_RESEARCH_FACT_KEY = "natural_browser_desktop_research"
    _BROWSER_DESKTOP_DESTINATION_FACT_KEY = "natural_browser_desktop_destination"
    _BROWSER_DESKTOP_OUTCOME_KIND = "managed_reference_release_code_to_focused_text"
    _BROWSER_RESEARCH_PROBE_LABEL = "research two authorized-page references in isolated managed Chromium"
    _BROWSER_DESKTOP_PROBE_LABEL = "freshly bind the current desktop Edit after browser research"

    @classmethod
    def _natural_browser_desktop_submit_request(cls, event) -> dict[str, str] | None:
        payload = event.payload or {}
        if (
            str(event.kind or "").strip().lower() != "desktop_user_event"
            or payload.get("body_action")
            or payload.get("native_action")
        ):
            return None
        task = " ".join(str(event.task or "").strip().split())
        if not task or len(task) > 1600:
            return None
        lowered = task.lower()
        has_current_page = any(
            cue in lowered for cue in ("current browser page", "current page", "authorized page")
        ) or any(cue in task for cue in ("当前浏览器页面", "当前页面", "已授权的当前浏览器", "已授权页面"))
        has_reference = "reference" in lowered or "参考" in task
        has_code = (
            "release code" in lowered
            or ("release" in lowered and "code" in lowered)
            or "发布代码" in task
            or "发行代码" in task
            or "代码" in task
        )
        has_agreement = any(cue in lowered for cue in ("agree", "same code", "consistent")) or any(
            cue in task for cue in ("一致", "相同", "共同")
        )
        has_desktop = any(
            cue in lowered for cue in ("current app", "open app", "desktop app", "current software")
        ) or any(cue in task for cue in ("当前打开的软件", "当前软件", "这个软件", "打开的软件"))
        has_input = any(cue in lowered for cue in ("textbox", "text box", "input")) or "输入框" in task
        has_fill = any(cue in lowered for cue in ("fill", "enter", "type", "put")) or any(
            cue in task for cue in ("填到", "填进", "输入到", "输入进", "放到")
        )
        has_confirmation = any(cue in lowered for cue in ("confirm", "verify")) or "确认" in task or "验证" in task
        buttons = [match.group("name").strip() for match in _BUTTON_RE.finditer(task)]
        titles = [match.group("title").strip() for match in _RESULT_TITLE_RE.finditer(task)]
        unique_buttons = list(dict.fromkeys(value for value in buttons if value))
        unique_titles = list(dict.fromkeys(value for value in titles if value))
        if not (
            has_current_page
            and has_reference
            and has_code
            and has_agreement
            and has_desktop
            and has_input
            and has_fill
            and has_confirmation
            and len(unique_buttons) == 1
            and len(unique_titles) == 1
        ):
            return None
        return {
            "button_name": unique_buttons[0],
            "expected_title": unique_titles[0],
        }

    @classmethod
    def _natural_file_desktop_submit_request(cls, event) -> dict[str, str] | None:
        browser_request = cls._natural_browser_desktop_submit_request(event)
        if browser_request is not None:
            return browser_request
        return super()._natural_file_desktop_submit_request(event)

    @classmethod
    def _required_capabilities(cls, event) -> tuple[str, ...]:
        payload = event.payload or {}
        if (
            payload.get("required_capabilities") is None
            and cls._natural_browser_desktop_submit_request(event) is not None
        ):
            return ("browser",)
        return super()._required_capabilities(event)

    def _investigation_step(
        self,
        event,
        state: WorkingState,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        request = self._natural_browser_desktop_submit_request(event)
        if request is None:
            return super()._investigation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        progress = state.data.get(self._DESKTOP_SUBMIT_STATE_KEY)
        if isinstance(progress, dict) and progress.get("typed_verified") is True:
            state.stage = "native_deliberation"
            state.next_action = "freshly locate the named Button in the current desktop application"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        existing = state.data.get(self._BROWSER_DESKTOP_RESEARCH_STATE_KEY)
        if self._research_state_is_complete(existing):
            state.stage = "native_deliberation"
            state.next_action = "freshly sense the current desktop target for the researched release code"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        if self.user_browser_extension.authorized_tab() is None:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "browser-to-desktop research requires one current USER browser tab explicitly "
                    "authorized through the ZN browser bridge"
                ),
            )

        try:
            initial = self._discover_authorized_reference_context()
            references = self._rank_reference_candidates(initial.get("references"))
            if len(references) < 2:
                raise UserBrowserExtensionRelayError(
                    "the authorized page did not expose at least two bounded reference candidates"
                )
            research = self._research_managed_references(references)
            release_code, units = KeyboardTextBody.validate_text(
                str(research.get("release_code") or "")
            )
            sources = self._bounded_research_sources(research.get("sources"))
            distinct_sources = {
                str(item.get("source_url") or "").strip()
                for item in sources
                if str(item.get("source_url") or "").strip()
            }
            if len(distinct_sources) < 2:
                raise RuntimeError(
                    "managed reference investigation did not preserve two distinct agreeing sources"
                )

            fresh_tab = self.probe_user_browser_extension_tab()
            initial_tab_id = int(initial.get("tab_id") or 0)
            fresh_tab_id = int(fresh_tab.get("tab_id") or 0)
            initial_url = str(initial.get("url") or "").strip()
            fresh_url = str(fresh_tab.get("url") or "").strip()
            if (
                initial_tab_id <= 0
                or fresh_tab_id != initial_tab_id
                or not initial_url
                or fresh_url != initial_url
            ):
                raise UserBrowserExtensionRelayError(
                    "the explicitly authorized USER tab/page changed during managed reference research"
                )
        except Exception as exc:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "ZN could not establish fresh two-source browser research for the desktop task: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )

        digest = hashlib.sha256(release_code.encode("utf-8")).hexdigest()
        research_state = {
            "release_code": release_code,
            "release_code_sha256": digest,
            "release_code_chars": len(release_code),
            "release_code_utf16_units": len(units),
            "sources": sources,
            "authorized_tab_id": fresh_tab_id,
            "authorized_tab_url": fresh_url,
            "initial_observed_at": str(initial.get("observed_at") or ""),
            "fresh_observed_at": str(
                fresh_tab.get("observed_at") or fresh_tab.get("captured_at") or ""
            ),
            "completed_at": utc_now(),
        }
        state.data[self._BROWSER_DESKTOP_RESEARCH_STATE_KEY] = research_state
        self._record_browser_research_evidence(event, state, research_state)
        state.data.pop("local_failure", None)
        state.stage = "native_deliberation"
        state.next_action = "freshly sense the current desktop target for the researched release code"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        if thought is not None:
            known = (
                "two distinct managed-browser reference sources agreed on one release code and the "
                "same authorized USER tab/page was freshly re-observed afterward"
            )
            if known not in thought.known:
                thought.known = (*thought.known, known)
            thought.reason = (
                f"{thought.reason}; browser research established only the value to carry forward, "
                "so desktop target authority must be formed from a new desktop Sense"
            )
            self._persist_enriched_thought(thought)
        return None

    def _deliberation_step(
        self,
        event,
        state: WorkingState,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        request = self._natural_browser_desktop_submit_request(event)
        if request is None:
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        progress = state.data.get(self._DESKTOP_SUBMIT_STATE_KEY)
        if isinstance(progress, dict) and progress.get("typed_verified") is True:
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        research = state.data.get(self._BROWSER_DESKTOP_RESEARCH_STATE_KEY)
        code, error = self._validated_research_code(research)
        if error or code is None:
            state.stage = "native_investigation"
            state.next_action = "rebuild fresh two-source browser research evidence"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        assert isinstance(research, dict)
        source = {
            "text_sha256": str(research["release_code_sha256"]),
            "text_chars": int(research["release_code_chars"]),
        }
        destination, destination_notes = self._observe_focused_destination(source)
        self._record_browser_desktop_destination(
            event,
            state,
            destination,
            destination_notes,
        )
        failure = str(destination.get("failure_reason") or "").strip()
        if failure:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "browser research succeeded, but ZN stopped before desktop input because fresh "
                    "desktop evidence was insufficient: " + failure
                ),
            )

        if destination.get("already_matches") is True:
            return self._mark_browser_desktop_text_progress(
                event,
                state,
                request=request,
                research=research,
                destination=destination,
                typed_at=utc_now(),
                input_sent=False,
            )

        completion_scope = destination.get("completion_scope")
        action_precondition = destination.get("action_precondition")
        if not isinstance(completion_scope, Mapping) or not isinstance(action_precondition, Mapping):
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason="fresh browser-to-desktop grounding lost exact desktop target authority",
            )

        intent = NativeActionIntent(
            intent_id=f"browser-desktop-{uuid.uuid4().hex[:12]}",
            event_id=event.event_id,
            kind="keyboard_text",
            args={},
            expected_outcome={
                "kind": self._BROWSER_DESKTOP_OUTCOME_KIND,
                "release_code_sha256": str(research["release_code_sha256"]),
                "release_code_chars": int(research["release_code_chars"]),
                "release_code_utf16_units": int(research["release_code_utf16_units"]),
                "completion_scope": dict(completion_scope),
                "action_precondition": dict(action_precondition),
            },
            reason=(
                "fresh isolated browser research established one agreed release-code digest and a "
                "separate fresh desktop Sense established one exact focused non-browser Edit"
            ),
            source="resident_choice",
        )
        if self._action_blocked_by_current_evidence(event, state, intent):
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason=(
                    "the exact browser-to-desktop text action remains blocked by unchanged failure "
                    "evidence; ZN will not replay it"
                ),
            )
        self._begin_native_action_cycle(event, state, intent)
        self.store.save_working_state(state)
        if thought is not None:
            action = "fill the freshly bound desktop Edit with the independently researched release code"
            if action not in thought.possible_actions:
                thought.possible_actions = (*thought.possible_actions, action)
            thought.reason = (
                f"{thought.reason}; browser facts determine the value only, while fresh desktop "
                "evidence independently determines where this non-replayable text input may go"
            )
            self._persist_enriched_thought(thought)
        return None

    def _keyboard_text_contract(
        self,
        event,
        intent: NativeActionIntent,
    ) -> tuple[dict[str, Any] | None, str | None]:
        expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        if (
            intent.kind != "keyboard_text"
            or str(expected.get("kind") or "").strip().lower()
            != self._BROWSER_DESKTOP_OUTCOME_KIND
        ):
            return super()._keyboard_text_contract(event, intent)

        research = self.store.get_working_state().data.get(
            self._BROWSER_DESKTOP_RESEARCH_STATE_KEY
        )
        code, error = self._validated_research_code(research)
        if error or code is None:
            return None, error or "fresh managed-reference release code is unavailable"
        assert isinstance(research, dict)
        if (
            str(expected.get("release_code_sha256") or "")
            != str(research.get("release_code_sha256") or "")
            or int(expected.get("release_code_chars") or -1)
            != int(research.get("release_code_chars") or -2)
            or int(expected.get("release_code_utf16_units") or -1)
            != int(research.get("release_code_utf16_units") or -2)
        ):
            return None, "browser research value no longer matches the admitted desktop text intent"

        completion_scope = expected.get("completion_scope")
        action_precondition = expected.get("action_precondition")
        if not isinstance(completion_scope, dict) or not isinstance(action_precondition, dict):
            return None, "browser-to-desktop intent lost its exact focused-target authority"
        synthetic_event = replace(
            event,
            kind=self._UI_EVENT_KIND,
            payload={
                "expected_outcome": {"kind": self._TEXT_OUTCOME_KIND},
                "completion_scope": dict(completion_scope),
                "action_precondition": dict(action_precondition),
                "model_policy": "never",
            },
        )
        transient_intent = NativeActionIntent(
            intent_id=intent.intent_id,
            event_id=intent.event_id,
            kind=intent.kind,
            args={"text": code},
            expected_outcome=intent.expected_outcome,
            reason=intent.reason,
            source=intent.source,
            created_at=intent.created_at,
        )
        return super()._keyboard_text_contract(synthetic_event, transient_intent)

    def _complete_successful_body_action(
        self,
        event,
        state,
        intent: NativeActionIntent,
        *,
        response: str,
        reason: str,
    ):
        request = self._natural_browser_desktop_submit_request(event)
        expected = intent.expected_outcome if isinstance(intent.expected_outcome, dict) else {}
        if (
            request is not None
            and intent.kind == "keyboard_text"
            and str(expected.get("kind") or "").strip().lower()
            == self._BROWSER_DESKTOP_OUTCOME_KIND
        ):
            research = state.data.get(self._BROWSER_DESKTOP_RESEARCH_STATE_KEY)
            code, error = self._validated_research_code(research)
            if error or code is None or not isinstance(research, dict):
                return self._checkpoint_terminal_failure(
                    event,
                    state,
                    reason="verified desktop text entry lost its durable browser research evidence",
                )
            destination = self._destination_from_expected(expected)
            if destination is None:
                return self._checkpoint_terminal_failure(
                    event,
                    state,
                    reason="verified browser-to-desktop text entry lost exact desktop target authority",
                )
            return self._mark_browser_desktop_text_progress(
                event,
                state,
                request=request,
                research=research,
                destination=destination,
                typed_at=utc_now(),
                input_sent=True,
            )
        return super()._complete_successful_body_action(
            event,
            state,
            intent,
            response=response,
            reason=reason,
        )

    def _mark_browser_desktop_text_progress(
        self,
        event,
        state: WorkingState,
        *,
        request: Mapping[str, str],
        research: Mapping[str, Any],
        destination: Mapping[str, Any],
        typed_at: str,
        input_sent: bool,
    ):
        completion_scope = destination.get("completion_scope")
        action_precondition = destination.get("action_precondition")
        if not isinstance(completion_scope, Mapping) or not isinstance(action_precondition, Mapping):
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason="browser-to-desktop progress lost exact foreground process/title authority",
            )
        process_name = str(completion_scope.get("process_name") or "").strip().lower()
        pre_title = str(action_precondition.get("title_equals") or "").strip()
        if not process_name or not pre_title:
            return self._checkpoint_terminal_failure(
                event,
                state,
                reason="browser-to-desktop progress lost exact foreground process/title identity",
            )
        state.data[self._DESKTOP_SUBMIT_STATE_KEY] = {
            "typed_verified": True,
            "typed_at": typed_at,
            "input_sent": bool(input_sent),
            "process_name": process_name,
            "pre_title": pre_title,
            "button_name": str(request["button_name"]),
            "expected_title": str(request["expected_title"]),
            "source_kind": "managed_reference_research",
            "source_text_sha256": str(research.get("release_code_sha256") or ""),
            "source_text_chars": int(research.get("release_code_chars") or 0),
            "source_count": len(research.get("sources") or ()),
        }
        state.stage = "native_investigation"
        state.next_action = "freshly locate the named Button in the current desktop application"
        state.data.pop("local_failure", None)
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _record_browser_research_evidence(
        self,
        event,
        state: WorkingState,
        research: Mapping[str, Any],
    ) -> None:
        investigation = self.investigator.current(event.event_id)
        if investigation is None:
            return
        sources = research.get("sources") if isinstance(research.get("sources"), list) else []
        facts = dict(investigation.facts)
        facts[self._BROWSER_DESKTOP_RESEARCH_FACT_KEY] = {
            "complete": True,
            "release_code_sha256": str(research.get("release_code_sha256") or ""),
            "release_code_chars": int(research.get("release_code_chars") or 0),
            "source_count": len(sources),
            "sources": [
                {
                    "source_url": str(item.get("source_url") or ""),
                    "evidence_url": str(item.get("evidence_url") or ""),
                    "observed_at": str(item.get("observed_at") or ""),
                }
                for item in sources
                if isinstance(item, Mapping)
            ],
            "authorized_tab_id": int(research.get("authorized_tab_id") or 0),
            "authorized_tab_url": str(research.get("authorized_tab_url") or ""),
        }
        evidence = list(investigation.evidence)
        probes = list(investigation.probes)
        probe_keys = list(investigation.probe_keys)
        self._record_probe(
            evidence,
            probes,
            probe_keys,
            key=self._BROWSER_DESKTOP_RESEARCH_FACT_KEY,
            label=self._BROWSER_RESEARCH_PROBE_LABEL,
            notes=[
                f"managed reference agreement: sources={len(sources)} code_chars={int(research.get('release_code_chars') or 0)}",
                "the exact authorized USER tab/page was freshly re-observed after isolated research",
            ],
        )
        investigation.facts = facts
        investigation.evidence = tuple(evidence[-96:])
        investigation.probes = tuple(probes[-32:])
        investigation.probe_keys = tuple(probe_keys[-32:])
        investigation.updated_at = utc_now()
        investigation.rounds += 1
        investigation.next_probe = None
        investigation.unresolved = None
        self.investigator._save(investigation)
        state.data["native_investigation"] = self._investigation_data(investigation)

    def _record_browser_desktop_destination(
        self,
        event,
        state: WorkingState,
        destination: Mapping[str, Any],
        notes: list[str],
    ) -> None:
        investigation = self.investigator.current(event.event_id)
        if investigation is None:
            return
        facts = dict(investigation.facts)
        facts[self._BROWSER_DESKTOP_DESTINATION_FACT_KEY] = dict(destination)
        evidence = list(investigation.evidence)
        probes = list(investigation.probes)
        probe_keys = list(investigation.probe_keys)
        self._record_probe(
            evidence,
            probes,
            probe_keys,
            key=self._BROWSER_DESKTOP_DESTINATION_FACT_KEY,
            label=self._BROWSER_DESKTOP_PROBE_LABEL,
            notes=list(notes),
        )
        investigation.facts = facts
        investigation.evidence = tuple(evidence[-96:])
        investigation.probes = tuple(probes[-32:])
        investigation.probe_keys = tuple(probe_keys[-32:])
        investigation.updated_at = utc_now()
        investigation.rounds += 1
        investigation.next_probe = None
        investigation.unresolved = str(destination.get("failure_reason") or "").strip() or None
        self.investigator._save(investigation)
        state.data["native_investigation"] = self._investigation_data(investigation)

    def _validated_research_code(
        self,
        raw: Any,
    ) -> tuple[str | None, str | None]:
        if not self._research_state_is_complete(raw):
            return None, "managed-reference browser research evidence is incomplete"
        assert isinstance(raw, dict)
        try:
            code, units = KeyboardTextBody.validate_text(str(raw.get("release_code") or ""))
        except ValueError as exc:
            return None, f"researched release code is not safe bounded keyboard text: {exc}"
        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
        if (
            digest != str(raw.get("release_code_sha256") or "")
            or len(code) != int(raw.get("release_code_chars") or -1)
            or len(units) != int(raw.get("release_code_utf16_units") or -1)
        ):
            return None, "durable managed-reference research value failed its digest/length check"
        return code, None

    @staticmethod
    def _research_state_is_complete(raw: Any) -> bool:
        if not isinstance(raw, dict):
            return False
        sources = raw.get("sources")
        return bool(
            str(raw.get("release_code") or "")
            and str(raw.get("release_code_sha256") or "")
            and int(raw.get("release_code_chars") or 0) > 0
            and int(raw.get("release_code_utf16_units") or 0) > 0
            and isinstance(sources, list)
            and len(sources) >= 2
            and int(raw.get("authorized_tab_id") or 0) > 0
            and str(raw.get("authorized_tab_url") or "")
        )

    @staticmethod
    def _bounded_research_sources(raw: Any) -> list[dict[str, str]]:
        if not isinstance(raw, list):
            return []
        bounded: list[dict[str, str]] = []
        for item in raw[:8]:
            if not isinstance(item, Mapping):
                continue
            source_url = str(item.get("source_url") or "").strip()
            evidence_url = str(item.get("evidence_url") or "").strip()
            observed_at = str(item.get("observed_at") or "").strip()
            if not source_url or not evidence_url:
                continue
            bounded.append(
                {
                    "source_url": source_url[:2048],
                    "evidence_url": evidence_url[:2048],
                    "observed_at": observed_at[:120],
                }
            )
        return bounded

    @staticmethod
    def _destination_from_expected(expected: Mapping[str, Any]) -> dict[str, Any] | None:
        completion_scope = expected.get("completion_scope")
        action_precondition = expected.get("action_precondition")
        if not isinstance(completion_scope, Mapping) or not isinstance(action_precondition, Mapping):
            return None
        return {
            "complete": True,
            "completion_scope": dict(completion_scope),
            "action_precondition": dict(action_precondition),
            "already_matches": True,
            "failure_reason": None,
        }
