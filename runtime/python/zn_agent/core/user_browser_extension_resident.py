from __future__ import annotations

"""Resident composition for explicit current-tab browser-extension authorization."""

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

from .action import NativeActionIntent
from .body import BodyActionResult
from .browser import (
    BrowserPermissionContext,
    BrowserPlane,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from .browser_goal_understanding_resident import (
    _extract_json_object,
    browser_semantic_lookup_goal,
)
from .user_browser_extension_adapter import AuthorizedExtensionUserBrowser
from .user_browser_extension_relay import (
    ResidentUserBrowserExtensionRelay,
    UserBrowserExtensionRelayError,
)
from .user_browser_resident import UserBrowserBridgeResidentRuntime


_EN_SEARCH_THIS_PAGE_RE = re.compile(
    r"^\s*(?:search|find)\s+(?:this|the\s+current)\s+(?:page|site)\s+for\s+(.+?)\s*[.!?]?\s*$",
    re.IGNORECASE,
)
_EN_SEARCH_FOR_ON_PAGE_RE = re.compile(
    r"^\s*(?:search|find)\s+for\s+(.+?)\s+(?:on|in)\s+(?:this|the\s+current)\s+(?:page|site)\s*[.!?]?\s*$",
    re.IGNORECASE,
)
_ZH_SEARCH_THIS_PAGE_RE = re.compile(
    r"^\s*(?:在)?(?:这个|当前)(?:页面|网页|网站)(?:里|中|上)?\s*(?:搜索|查找|搜一下|查一下)\s*[：:]?\s*(.+?)\s*[。！？!?]?\s*$"
)


class UserBrowserExtensionResidentRuntime(UserBrowserBridgeResidentRuntime):
    """Own the loopback authorization surface used by the ZN browser extension."""

    _NATURAL_SEARCH_STATE_KEY = "resident_user_browser_natural_search"
    _SEMANTIC_LOOKUP_STATE_KEY = "resident_user_browser_semantic_lookup"
    _MAX_SEMANTIC_REGROUNDS = 3

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        # ResidentService starts/stops this resource only while this runtime owns
        # the single-instance resident lease. Merely constructing a runtime must
        # never seize the fixed browser-extension port.
        self.user_browser_extension = ResidentUserBrowserExtensionRelay()
        self._extension_user_browser = AuthorizedExtensionUserBrowser(
            self.user_browser_extension
        )
        self._browser_before_extension = None

    def status(self) -> dict[str, Any]:
        data = super().status()
        data["user_browser_extension"] = self.user_browser_extension.status()
        return data

    def user_browser_extension_status(self) -> dict[str, Any]:
        return self.user_browser_extension.status()

    def user_browser_authorization(self) -> dict[str, Any]:
        authorized = self.user_browser_extension.authorized_tab()
        if authorized is not None:
            return {
                "authorized": True,
                "plane": BrowserPlane.USER.value,
                "provider": self._extension_user_browser.name,
                "profile_scope": "user_existing",
                "endpoint_scope": "loopback_extension_relay",
                "browser_ownership": "user",
                "authorization_scope": "explicit_current_tab",
                "tab_id": authorized.tab_id,
            }
        return super().user_browser_authorization()

    def probe_user_browser_extension_tab(self) -> dict[str, Any]:
        """Ask the installed extension for fresh identity of the exact authorized tab."""

        authorized = self.user_browser_extension.authorized_tab()
        if authorized is None:
            raise UserBrowserExtensionRelayError("no user browser tab is currently authorized")
        command = self.user_browser_extension.request_command(
            "probe_current_tab",
            timeout_seconds=5.0,
        )
        if command.get("success") is not True:
            raise UserBrowserExtensionRelayError(
                str(command.get("error") or "authorized browser tab probe failed")
            )
        result = command.get("result")
        if not isinstance(result, dict):
            raise UserBrowserExtensionRelayError(
                "authorized browser tab probe did not return structured evidence"
            )
        try:
            tab_id = int(result.get("tab_id"))
        except (TypeError, ValueError) as exc:
            raise UserBrowserExtensionRelayError(
                "authorized browser tab probe returned invalid tab identity"
            ) from exc
        if tab_id != authorized.tab_id:
            raise UserBrowserExtensionRelayError(
                "authorized browser tab probe returned evidence for a different tab"
            )
        url = str(result.get("url") or "").strip()
        try:
            parsed = urlsplit(url)
        except ValueError as exc:
            raise UserBrowserExtensionRelayError(
                "authorized browser tab probe returned an invalid URL"
            ) from exc
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise UserBrowserExtensionRelayError(
                "authorized browser tab probe left the permitted HTTP(S) page boundary"
            )
        title = str(result.get("title") or "").strip()
        if len(title) > 512:
            raise UserBrowserExtensionRelayError(
                "authorized browser tab probe returned an oversized title"
            )
        return {
            "authorized": True,
            "tab_id": tab_id,
            "url": url,
            "title": title,
            "observed_at": str(command.get("completed_at") or ""),
            "source": "zn_browser_extension",
        }

    def revoke_user_browser_extension_tab(self, tab_id: int | None = None) -> dict[str, Any]:
        result = self.user_browser_extension.revoke(tab_id=tab_id)
        self._restore_browser_after_extension()
        return result

    @classmethod
    def _natural_current_page_search(cls, event) -> str | None:
        payload = event.payload or {}
        if payload.get("body_action") or payload.get("native_action"):
            return None
        task = str(event.task or "")
        matches = []
        for pattern in (
            _EN_SEARCH_THIS_PAGE_RE,
            _EN_SEARCH_FOR_ON_PAGE_RE,
            _ZH_SEARCH_THIS_PAGE_RE,
        ):
            match = pattern.fullmatch(task)
            if match is not None:
                matches.append(match.group(1))
        if len(matches) != 1:
            return None
        query = str(matches[0] or "").strip()
        if len(query) >= 2 and query[0] in {'"', "'", "“"} and query[-1] in {'"', "'", "”"}:
            query = query[1:-1].strip()
        if not query or len(query) > 512:
            return None
        if any(ord(char) < 32 or ord(char) == 127 for char in query):
            return None
        return query

    @classmethod
    def _required_capabilities(cls, event) -> tuple[str, ...]:
        payload = event.payload or {}
        if payload.get("required_capabilities") is None and (
            browser_semantic_lookup_goal(event) is not None
            or cls._natural_current_page_search(event) is not None
        ):
            return ("browser",)
        return super()._required_capabilities(event)

    def _investigation_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        semantic_goal = browser_semantic_lookup_goal(event)
        if semantic_goal is not None:
            return self._semantic_lookup_investigation(
                event,
                state,
                semantic_goal,
                readiness=readiness,
                thought=thought,
            )

        query = self._natural_current_page_search(event)
        if query is None:
            return super()._investigation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )

        if self.user_browser_extension.authorized_tab() is None:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "this-page search requires one current browser tab explicitly authorized "
                    "through the ZN browser bridge"
                ),
            )
        self._adopt_authorized_extension_browser()
        try:
            evidence = self._discover_unique_search_form(query)
        except Exception as exc:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "ZN could not identify one unique safe search form on the current authorized "
                    f"page: {type(exc).__name__}: {exc}"
                ),
            )

        state.data[self._NATURAL_SEARCH_STATE_KEY] = evidence
        state.data.pop("local_failure", None)
        if thought is not None:
            known = (
                "fresh authorized-page evidence identified one unique empty native search field, "
                "its submit button, and a same-origin GET result route"
            )
            if known not in thought.known:
                thought.known = (*thought.known, known)
            thought.reason = (
                f"{thought.reason}; ZN grounded the user's ordinary search request in the current "
                "authorized page without asking for a URL, DOM id, coordinate, or control name"
            )
            self._persist_enriched_thought(thought)

        state.stage = "native_deliberation"
        state.next_action = "form the current-page search movement from fresh semantic evidence"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _semantic_lookup_investigation(
        self,
        event,
        state,
        goal: dict[str, str],
        *,
        readiness,
        thought=None,
    ):
        if self.user_browser_extension.authorized_tab() is None:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "the semantic browser task requires the user to explicitly authorize one "
                    "current tab; ZN will not attach to or substitute another tab"
                ),
            )
        self._adopt_authorized_extension_browser()
        raw = state.data.get(self._SEMANTIC_LOOKUP_STATE_KEY)
        semantic = dict(raw) if isinstance(raw, dict) else {"phase": "ground_input", "regrounds": 0}
        phase = str(semantic.get("phase") or "ground_input")

        if phase == "ground_input":
            try:
                sense = self._extension_user_browser.observe_semantic_candidates()
                grounded = self._ground_semantic_input(event, goal, sense)
            except Exception as exc:
                return self._fail_composite_goal_investigation(
                    event,
                    state,
                    reason=(
                        "fresh authorized-tab semantic input grounding failed closed before any "
                        f"browser input: {type(exc).__name__}: {exc}"
                    ),
                )
            semantic.update(grounded)
            semantic["phase"] = "input_grounded"
            state.data[self._SEMANTIC_LOOKUP_STATE_KEY] = semantic
            state.data.pop("local_failure", None)
            state.stage = "native_deliberation"
            state.next_action = (
                "revalidate the exact grounded textbox against the current authorized tab before "
                "one bounded text movement"
            )
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            self._note_semantic_thought(
                thought,
                "fresh bounded authorized-tab candidates grounded one safe business input; exact browser identity remains Resident-owned",
            )
            return None

        if phase == "ground_button":
            try:
                sense = self._extension_user_browser.observe_semantic_candidates()
                grounded = self._ground_semantic_button(event, goal, sense)
            except Exception as exc:
                return self._fail_composite_goal_investigation(
                    event,
                    state,
                    reason=(
                        "fresh authorized-tab semantic submit grounding failed closed before any "
                        f"click: {type(exc).__name__}: {exc}"
                    ),
                )
            semantic.update(grounded)
            semantic["phase"] = "button_grounded"
            state.data[self._SEMANTIC_LOOKUP_STATE_KEY] = semantic
            state.data.pop("local_failure", None)
            state.stage = "native_deliberation"
            state.next_action = (
                "revalidate the exact grounded button against the current authorized tab before "
                "one bounded click"
            )
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            self._note_semantic_thought(
                thought,
                "fresh post-input Sense grounded one same-form safe submit operation; no pre-input button evidence was reused",
            )
            return None

        if phase == "verify_result":
            try:
                observed = self._extension_user_browser.observe_anchor_context(goal["subject_value"])
                expected_url = str(semantic.get("expected_url") or "").strip()
                if not expected_url or observed["url"] != expected_url:
                    raise UserBrowserExtensionRelayError(
                        "fresh result observation is not on the Resident-verified submitted URL"
                    )
                result_text = self._interpret_semantic_result(event, goal, observed["context"])
            except Exception as exc:
                return self._fail_composite_goal_investigation(
                    event,
                    state,
                    reason=(
                        "fresh authorized-tab result verification did not prove the requested "
                        f"business fact: {type(exc).__name__}: {exc}"
                    ),
                )
            return self._complete_goal_from_fresh_investigation(
                event,
                state,
                readiness=readiness,
                response=result_text,
                reason=(
                    "ZN completed the browser goal only after provider-verified text entry, a "
                    "freshly re-grounded exact submit action, final URL verification, and a fresh "
                    "anchored result observation from the same explicitly authorized tab"
                ),
            )

        if phase in {"input_grounded", "button_grounded"}:
            state.stage = "native_deliberation"
            state.next_action = "revalidate fresh browser authority before the next bounded movement"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        return self._fail_composite_goal_investigation(
            event,
            state,
            reason="semantic browser task lost its bounded investigation phase; no side effect attempted",
        )

    def _ground_semantic_input(
        self,
        event,
        goal: dict[str, str],
        sense: dict[str, Any],
    ) -> dict[str, Any]:
        if sense.get("truncated") is True:
            raise UserBrowserExtensionRelayError(
                "semantic candidate Sense was truncated, so hidden ambiguity cannot be excluded"
            )
        candidates = list(sense.get("candidates") or [])
        projected = [
            {
                "role": item.get("role"),
                "name": item.get("name"),
                "enabled": item.get("enabled") is True,
                "visible": item.get("visible") is True,
                "editable": item.get("editable") is True,
                "sensitive": item.get("sensitive") is True,
            }
            for item in candidates
        ]
        selected_name = self._select_semantic_candidate(
            event,
            purpose="browser_semantic_input_grounding_only",
            question=(
                "Choose only among these freshly observed browser controls. Select the one safe "
                "textbox that best represents the user's business subject identifier. Return "
                'exactly {"status":"selected","name":"ONE OBSERVED NAME"} only when one '
                "choice is clearly best; otherwise return {\"status\":\"ambiguous\"}. Never "
                "return an index, selector, DOM id, tab identity, authority, action or completion. "
                f"User task: {event.task}\nSubject semantics: {goal['subject_semantics']}\n"
                f"Fresh candidates: {json.dumps(projected, ensure_ascii=False)}"
            ),
            candidates=candidates,
            required_role="textbox",
            require_editable=True,
        )
        candidate = self._unique_candidate(candidates, selected_name, "textbox")
        self._require_safe_textbox_candidate(candidate)
        if int(candidate.get("text_length") or 0) != 0:
            raise UserBrowserExtensionRelayError(
                "the selected business input already contains text; autonomous replacement is outside this task authority"
            )
        current_url = self._normal_http_url(sense.get("url"), "semantic candidate page")
        form_action, parameter, signature = self._safe_get_form(candidate, current_url)
        exact = self._bind_exact_semantic_target(
            url=current_url,
            name=selected_name,
            role="textbox",
        )
        return {
            "url": current_url,
            "input_name": selected_name,
            "input_target_id": exact["target_id"],
            "input_observed_at": exact["observed_at"],
            "form_action": form_action,
            "query_parameter": parameter,
            "form_signature": signature,
        }

    def _ground_semantic_button(
        self,
        event,
        goal: dict[str, str],
        sense: dict[str, Any],
    ) -> dict[str, Any]:
        if sense.get("truncated") is True:
            raise UserBrowserExtensionRelayError(
                "semantic candidate Sense was truncated, so hidden ambiguity cannot be excluded"
            )
        candidates = list(sense.get("candidates") or [])
        expected_sha = hashlib.sha256(goal["subject_value"].encode("utf-8")).hexdigest()
        populated_inputs = [
            item
            for item in candidates
            if item.get("role") == "textbox"
            and item.get("sensitive") is not True
            and int(item.get("text_length") or -1) == len(goal["subject_value"])
            and str(item.get("text_sha256") or "") == expected_sha
        ]
        if len(populated_inputs) != 1:
            raise UserBrowserExtensionRelayError(
                "fresh post-input Sense did not prove exactly one safe textbox containing the requested subject"
            )
        textbox = populated_inputs[0]
        current_url = self._normal_http_url(sense.get("url"), "semantic candidate page")
        form_action, parameter, signature = self._safe_get_form(textbox, current_url)
        buttons = [
            item
            for item in candidates
            if item.get("role") == "button"
            and item.get("enabled") is True
            and item.get("visible") is True
            and item.get("clickable") is True
            and item.get("sensitive") is not True
            and str(item.get("form_signature") or "") == signature
        ]
        projected = [
            {
                "role": "button",
                "name": item.get("name"),
                "enabled": True,
                "visible": True,
                "clickable": True,
            }
            for item in buttons
        ]
        selected_name = self._select_semantic_candidate(
            event,
            purpose="browser_semantic_button_grounding_only",
            question=(
                "Choose only among these freshly observed buttons from the same form as the "
                "verified business input. Select the button that best performs the user's desired "
                "lookup operation. Return exactly "
                '{"status":"selected","name":"ONE OBSERVED NAME"} only when one choice is '
                "clearly best; otherwise return {\"status\":\"ambiguous\"}. Never return an "
                "index, selector, DOM id, tab identity, authority, action or completion. "
                f"User task: {event.task}\nOperation: {goal['operation']}\n"
                f"Fresh same-form buttons: {json.dumps(projected, ensure_ascii=False)}"
            ),
            candidates=buttons,
            required_role="button",
            require_editable=False,
        )
        button = self._unique_candidate(buttons, selected_name, "button")
        if not (
            button.get("enabled") is True
            and button.get("visible") is True
            and button.get("clickable") is True
            and button.get("sensitive") is not True
        ):
            raise UserBrowserExtensionRelayError("selected semantic button is not currently safe")
        if str(button.get("form_signature") or "") != signature:
            raise UserBrowserExtensionRelayError(
                "selected semantic button is not from the freshly verified input form"
            )
        button_action = self._normal_http_url(button.get("form_action"), "semantic button form action")
        if button_action != form_action:
            raise UserBrowserExtensionRelayError(
                "semantic input and button no longer share the same verified form action"
            )
        expected_url = self._expected_get_url(form_action, parameter, goal["subject_value"])
        exact = self._bind_exact_semantic_target(
            url=current_url,
            name=selected_name,
            role="button",
        )
        return {
            "url": current_url,
            "button_name": selected_name,
            "button_target_id": exact["target_id"],
            "button_observed_at": exact["observed_at"],
            "form_action": form_action,
            "query_parameter": parameter,
            "form_signature": signature,
            "expected_url": expected_url,
        }

    def _deliberation_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        semantic_goal = browser_semantic_lookup_goal(event)
        if semantic_goal is not None:
            return self._semantic_lookup_deliberation(
                event,
                state,
                semantic_goal,
                thought=thought,
            )

        natural_query = self._natural_current_page_search(event)
        if natural_query is not None:
            if self.user_browser_extension.authorized_tab() is None:
                return self._fail_composite_goal_investigation(
                    event,
                    state,
                    reason="the explicitly authorized current browser tab is no longer available",
                )
            self._adopt_authorized_extension_browser()
            evidence = state.data.get(self._NATURAL_SEARCH_STATE_KEY)
            if not isinstance(evidence, dict):
                state.stage = "native_investigation"
                state.next_action = "re-observe the current page and identify its search form"
                self._sync_execution_context(event, state)
                self.store.save_working_state(state)
                return None
            intent = NativeActionIntent(
                intent_id=f"browser-natural-search-{event.event_id}",
                event_id=event.event_id,
                kind=self._BROWSER_FILL_AND_SUBMIT,
                args={
                    "url": str(evidence.get("url") or ""),
                    "textbox_name": str(evidence.get("textbox_name") or ""),
                    "text": natural_query,
                    "button_name": str(evidence.get("button_name") or ""),
                    "expected_url": str(evidence.get("expected_url") or ""),
                },
                reason=(
                    "fresh authorized-page discovery proved one unique empty safe GET search form; "
                    "the existing guarded form Body will re-observe each target and final page"
                ),
                source="resident_choice",
            )
            if not self._action_blocked_by_current_evidence(event, state, intent):
                self._begin_native_action_cycle(event, state, intent)
                self.store.save_working_state(state)
                if thought is not None:
                    action = "search the current authorized page through the existing browser Body"
                    if action not in thought.possible_actions:
                        thought.possible_actions = (*thought.possible_actions, action)
                    thought.reason = (
                        f"{thought.reason}; the next movement uses the existing guarded form path "
                        "so text entry, fresh button observation, click, final observation and "
                        "restart non-replay remain resident-owned"
                    )
                    self._persist_enriched_thought(thought)
                return None
            return None

        # Explicit form-submit Work is already resident-owned and guarded. When the
        # user has authorized one current extension tab, run that same mature Body
        # movement against the USER adapter rather than silently falling back to a
        # managed browser. The USER Body path will freshly require the current URL
        # to equal the supplied start URL and will not navigate to it.
        if self._natural_form_submit_request(event) is not None:
            if self.user_browser_extension.authorized_tab() is not None:
                self._adopt_authorized_extension_browser()
            elif self.managed_browser is self._extension_user_browser:
                self._restore_browser_after_extension()
        return super()._deliberation_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    def _semantic_lookup_deliberation(
        self,
        event,
        state,
        goal: dict[str, str],
        *,
        thought=None,
    ):
        if self.user_browser_extension.authorized_tab() is None:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "the explicitly authorized browser tab was revoked or closed before the next "
                    "semantic movement; ZN will not transfer authority to another tab"
                ),
            )
        self._adopt_authorized_extension_browser()
        raw = state.data.get(self._SEMANTIC_LOOKUP_STATE_KEY)
        if not isinstance(raw, dict):
            state.stage = "native_investigation"
            state.next_action = "freshly ground the semantic browser goal"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None
        semantic = dict(raw)
        phase = str(semantic.get("phase") or "")

        if phase == "input_grounded":
            if not self._semantic_binding_is_fresh(semantic, role="textbox"):
                return self._request_semantic_reground(
                    event,
                    state,
                    semantic,
                    phase="ground_input",
                    reason="the previously grounded textbox identity or semantic name is no longer current",
                )
            intent = NativeActionIntent(
                intent_id=f"browser-semantic-input-{event.event_id}",
                event_id=event.event_id,
                kind="browser_type_named_text",
                args={
                    "url": str(semantic.get("url") or ""),
                    "target_name": str(semantic.get("input_name") or ""),
                    "text": goal["subject_value"],
                },
                reason=(
                    "fresh revalidation proved the current exact authorized-tab textbox still "
                    "matches the Resident-grounded safe semantic candidate"
                ),
                source="resident_choice",
            )
            if not self._action_blocked_by_current_evidence(event, state, intent):
                self._begin_native_action_cycle(event, state, intent)
                self.store.save_working_state(state)
                self._note_semantic_thought(
                    thought,
                    "Resident revalidated exact current textbox authority and chose one bounded text movement",
                )
            return None

        if phase == "button_grounded":
            if not self._semantic_binding_is_fresh(semantic, role="button"):
                return self._request_semantic_reground(
                    event,
                    state,
                    semantic,
                    phase="ground_button",
                    reason="the previously grounded submit button identity or semantic name is no longer current",
                )
            intent = NativeActionIntent(
                intent_id=f"browser-semantic-submit-{event.event_id}",
                event_id=event.event_id,
                kind="browser_click_named_button_to_url",
                args={
                    "url": str(semantic.get("url") or ""),
                    "target_name": str(semantic.get("button_name") or ""),
                    "expected_url": str(semantic.get("expected_url") or ""),
                },
                reason=(
                    "fresh revalidation proved the current exact authorized-tab button still "
                    "matches the post-input semantic grounding"
                ),
                source="resident_choice",
            )
            if not self._action_blocked_by_current_evidence(event, state, intent):
                self._begin_native_action_cycle(event, state, intent)
                self.store.save_working_state(state)
                self._note_semantic_thought(
                    thought,
                    "Resident revalidated exact current button authority and chose one bounded submit movement",
                )
            return None

        state.stage = "native_investigation"
        state.next_action = "freshly sense the authorized tab before deciding the next semantic movement"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _complete_successful_body_action(
        self,
        event,
        state,
        intent,
        *,
        response: str,
        reason: str,
    ):
        goal = browser_semantic_lookup_goal(event)
        if goal is None:
            return super()._complete_successful_body_action(
                event,
                state,
                intent,
                response=response,
                reason=reason,
            )
        raw_semantic = state.data.get(self._SEMANTIC_LOOKUP_STATE_KEY)
        semantic = dict(raw_semantic) if isinstance(raw_semantic, dict) else {}
        raw_result = state.data.get("native_action_result")
        try:
            result = BodyActionResult(**raw_result) if isinstance(raw_result, dict) else None
        except (TypeError, ValueError):
            result = None
        kind = str(intent.kind or "").strip().lower()

        if kind == "browser_type_named_text" and result is not None:
            data = dict(result.data or {})
            expected_sha = hashlib.sha256(goal["subject_value"].encode("utf-8")).hexdigest()
            if not (
                result.success
                and data.get("postcondition") == "same_exact_target_text_equals_requested"
                and data.get("input_sent") is True
                and data.get("exact_node_continuity") is True
                and int(data.get("expected_text_length") or -1) == len(goal["subject_value"])
                and str(data.get("expected_text_sha256") or "") == expected_sha
                and int(data.get("text_length_after") or -1) == len(goal["subject_value"])
                and str(data.get("text_sha256_after") or "") == expected_sha
            ):
                return super()._complete_successful_body_action(
                    event,
                    state,
                    intent,
                    response=response,
                    reason=reason,
                )
            semantic["phase"] = "ground_button"
            state.data[self._SEMANTIC_LOOKUP_STATE_KEY] = semantic
            self._record_semantic_progress(state, kind, "browser_semantic_input_provider_verified")
            self._reset_investigation_after_goal_substep(event, state, intent)
            state.stage = "native_investigation"
            state.next_action = (
                "freshly re-sense the authorized page after text entry; do not reuse any button "
                "evidence from before the side effect"
            )
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        if kind == "browser_click_named_button_to_url" and result is not None:
            data = dict(result.data or {})
            expected_url = str(semantic.get("expected_url") or "")
            if not (
                result.success
                and data.get("postcondition") == "url_equals_after_fresh_semantic_button_click"
                and data.get("target_revalidated_before_dispatch") is True
                and str(data.get("observed_url") or "") == expected_url
            ):
                return super()._complete_successful_body_action(
                    event,
                    state,
                    intent,
                    response=response,
                    reason=reason,
                )
            semantic["phase"] = "verify_result"
            state.data[self._SEMANTIC_LOOKUP_STATE_KEY] = semantic
            self._record_semantic_progress(state, kind, "browser_semantic_submit_provider_verified")
            self._reset_investigation_after_goal_substep(event, state, intent)
            state.stage = "native_investigation"
            state.next_action = (
                "freshly observe the authorized result page and verify the requested business fact"
            )
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        return super()._complete_successful_body_action(
            event,
            state,
            intent,
            response=response,
            reason=reason,
        )

    def _select_semantic_candidate(
        self,
        event,
        *,
        purpose: str,
        question: str,
        candidates: list[dict[str, Any]],
        required_role: str,
        require_editable: bool,
    ) -> str:
        decision = self.budget.decide(
            event,
            memory_hit=False,
            local_capability_available=False,
        )
        if not decision.use_model:
            raise UserBrowserExtensionRelayError(
                "semantic candidate comparison requires bounded language understanding and model use is disabled"
            )
        normalized_question = question.strip()
        input_sha256 = hashlib.sha256(normalized_question.encode("utf-8")).hexdigest()
        result = self.kernel.run_goal(
            normalized_question,
            required_capabilities=("language_understanding",),
            priority=event.priority,
            metadata={
                "resident_event_id": event.event_id,
                "purpose": purpose,
                "input_sha256": input_sha256,
            },
            max_attempts_override=1,
            goal_id=f"goal-{purpose}-{event.event_id}-{input_sha256[:16]}",
        )
        self._add_semantic_model_invocations(event, self._model_invocations(result))
        if not (result.worker_result.success and result.assessment.success):
            raise UserBrowserExtensionRelayError("bounded semantic candidate comparison failed")
        value = _extract_json_object(result.worker_result.response)
        if value is None or set(value).difference({"status", "name"}):
            raise UserBrowserExtensionRelayError("bounded semantic candidate comparison returned invalid schema")
        if str(value.get("status") or "").strip().lower() != "selected":
            raise UserBrowserExtensionRelayError("fresh semantic candidates are ambiguous")
        name = " ".join(str(value.get("name") or "").strip().split())
        matching = [
            item
            for item in candidates
            if str(item.get("name") or "") == name
            and str(item.get("role") or "").lower() == required_role
        ]
        if len(matching) != 1:
            raise UserBrowserExtensionRelayError(
                "semantic selection did not identify exactly one freshly observed candidate"
            )
        candidate = matching[0]
        if candidate.get("enabled") is not True or candidate.get("visible") is not True:
            raise UserBrowserExtensionRelayError("selected semantic candidate is not currently usable")
        if candidate.get("sensitive") is True:
            raise UserBrowserExtensionRelayError(
                "sensitive credential or payment candidate is not eligible for semantic grounding"
            )
        if require_editable and candidate.get("editable") is not True:
            raise UserBrowserExtensionRelayError("selected semantic textbox is not safely editable")
        return name

    def _interpret_semantic_result(
        self,
        event,
        goal: dict[str, str],
        context: str,
    ) -> str:
        decision = self.budget.decide(
            event,
            memory_hit=False,
            local_capability_available=False,
        )
        if not decision.use_model:
            raise UserBrowserExtensionRelayError(
                "business result interpretation requires bounded language understanding and model use is disabled"
            )
        result = self.kernel.run_goal(
            (
                "Read only this freshly observed bounded result context and extract the business "
                "fact the user requested. Return exactly "
                '{"status":"verified","result":"EXACT SUBSTRING FROM CONTEXT"} only if the '
                "requested fact is explicit; otherwise return {\"status\":\"not_verified\"}. "
                "The result must be copied verbatim from the context. Never infer missing facts, "
                "claim actions, authority or completion. "
                f"Desired result: {goal['desired_result']}\nFresh context: {context}"
            ),
            required_capabilities=("language_understanding",),
            priority=event.priority,
            metadata={
                "resident_event_id": event.event_id,
                "purpose": "browser_semantic_result_interpretation_only",
            },
            max_attempts_override=1,
            goal_id=f"goal-browser-semantic-result-{event.event_id}",
        )
        self._add_semantic_model_invocations(event, self._model_invocations(result))
        if not (result.worker_result.success and result.assessment.success):
            raise UserBrowserExtensionRelayError("bounded business result interpretation failed")
        value = _extract_json_object(result.worker_result.response)
        if value is None or set(value).difference({"status", "result"}):
            raise UserBrowserExtensionRelayError("bounded business result interpretation returned invalid schema")
        if str(value.get("status") or "").strip().lower() != "verified":
            raise UserBrowserExtensionRelayError("fresh result context did not verify the requested fact")
        fact = " ".join(str(value.get("result") or "").strip().split())
        normalized_context = " ".join(str(context or "").strip().split())
        if not fact or fact not in normalized_context:
            raise UserBrowserExtensionRelayError(
                "bounded cognition attempted to return a result not literally present in fresh evidence"
            )
        return f"{goal['subject_value']}: {fact}"

    def _bind_exact_semantic_target(self, *, url: str, name: str, role: str) -> dict[str, str]:
        if self.user_browser_extension.authorized_tab() is None:
            raise UserBrowserExtensionRelayError("the explicitly authorized browser tab is gone")
        permission = BrowserPermissionContext(
            allow_navigation=False,
            allow_page_interaction=True,
            allow_text_entry=role == "textbox",
            allowed_origins=(url,),
        )
        session = None
        try:
            session = self._extension_user_browser.open_session(
                permission=permission,
                headless=False,
            )
            current = self._extension_user_browser.observe(session.session_id)
            if current.url != url:
                raise UserBrowserExtensionRelayError(
                    "authorized tab page changed while binding semantic target"
                )
            query_kind = (
                BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME
                if role == "textbox"
                else BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME
            )
            observed = self._extension_user_browser.observe_target(
                session.session_id,
                BrowserTargetQuery(kind=query_kind, value=name),
                page_id=current.page_id,
            )
            target = observed.target
            if target is None or target.role != role or target.name != name:
                raise UserBrowserExtensionRelayError(
                    "semantic target could not be rebound to one exact current browser node"
                )
            return {
                "target_id": target.target_id,
                "observed_at": target.observed_at,
                "url": observed.url,
                "name": target.name,
            }
        finally:
            if session is not None:
                try:
                    self._extension_user_browser.close_session(session.session_id)
                except Exception:
                    pass

    def _semantic_binding_is_fresh(self, semantic: dict[str, Any], *, role: str) -> bool:
        if self.user_browser_extension.authorized_tab() is None:
            return False
        prefix = "input" if role == "textbox" else "button"
        url = str(semantic.get("url") or "").strip()
        name = str(semantic.get(f"{prefix}_name") or "").strip()
        target_id = str(semantic.get(f"{prefix}_target_id") or "").strip()
        if not url or not name or not target_id:
            return False
        try:
            exact = self._bind_exact_semantic_target(url=url, name=name, role=role)
        except Exception:
            return False
        return exact["target_id"] == target_id and exact["url"] == url

    def _request_semantic_reground(
        self,
        event,
        state,
        semantic: dict[str, Any],
        *,
        phase: str,
        reason: str,
    ):
        regrounds = int(semantic.get("regrounds") or 0) + 1
        if regrounds > self._MAX_SEMANTIC_REGROUNDS:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "browser reality kept changing across bounded semantic re-ground attempts; "
                    "ZN stopped before causing an ungrounded side effect"
                ),
            )
        semantic["regrounds"] = regrounds
        semantic["phase"] = phase
        state.data[self._SEMANTIC_LOOKUP_STATE_KEY] = semantic
        state.stage = "native_investigation"
        state.next_action = f"freshly re-sense and re-ground because {reason}"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    @staticmethod
    def _unique_candidate(
        candidates: list[dict[str, Any]],
        name: str,
        role: str,
    ) -> dict[str, Any]:
        matches = [
            item
            for item in candidates
            if str(item.get("name") or "") == name
            and str(item.get("role") or "").lower() == role
        ]
        if len(matches) != 1:
            raise UserBrowserExtensionRelayError(
                "semantic candidate is ambiguous in the current authorized page"
            )
        return matches[0]

    @staticmethod
    def _require_safe_textbox_candidate(candidate: dict[str, Any]) -> None:
        if not (
            candidate.get("enabled") is True
            and candidate.get("visible") is True
            and candidate.get("editable") is True
            and candidate.get("sensitive") is not True
        ):
            raise UserBrowserExtensionRelayError(
                "semantic textbox candidate is disabled, hidden, read-only or sensitive"
            )

    def _safe_get_form(
        self,
        candidate: dict[str, Any],
        current_url: str,
    ) -> tuple[str, str, str]:
        if str(candidate.get("form_method") or "").lower() != "get":
            raise UserBrowserExtensionRelayError(
                "semantic lookup currently permits only a safe GET form"
            )
        action = self._normal_http_url(candidate.get("form_action"), "semantic form action")
        if self._origin(action) != self._origin(current_url):
            raise UserBrowserExtensionRelayError(
                "semantic lookup form action leaves the explicitly authorized page origin"
            )
        parsed = urlsplit(action)
        if parsed.query or parsed.fragment:
            raise UserBrowserExtensionRelayError(
                "semantic lookup currently requires a GET form action without preset query or fragment"
            )
        parameter = self._bounded_label(candidate.get("query_parameter"), "query parameter", 128)
        signature = self._bounded_label(candidate.get("form_signature"), "form signature", 64)
        if len(signature) != 64 or any(char not in "0123456789abcdef" for char in signature.lower()):
            raise UserBrowserExtensionRelayError("semantic form signature is invalid")
        return action, parameter, signature.lower()

    @staticmethod
    def _expected_get_url(action_url: str, parameter: str, value: str) -> str:
        action = urlsplit(action_url)
        return urlunsplit(
            (action.scheme, action.netloc, action.path, urlencode([(parameter, value)]), "")
        )

    def _add_semantic_model_invocations(self, event, count: int) -> None:
        if count <= 0:
            return
        event.payload = dict(event.payload or {})
        raw = event.payload.get("_resident_goal_understanding")
        metadata = dict(raw) if isinstance(raw, dict) else {}
        metadata["model_invocations"] = max(0, int(metadata.get("model_invocations") or 0)) + int(count)
        event.payload["_resident_goal_understanding"] = metadata
        self.store._save_event(event)

    def _record_semantic_progress(self, state, action_kind: str, verification_kind: str) -> None:
        latest = state.data.get("latest_verified_experience")
        experience_id = (
            str(latest.get("experience_id") or "").strip()
            if isinstance(latest, dict)
            else ""
        )
        raw = state.data.get(self._RESIDENT_GOAL_PROGRESS_KEY)
        progress = list(raw) if isinstance(raw, list) else []
        progress.append(
            {
                "action_kind": action_kind,
                "verification_kind": verification_kind,
                "experience_id": experience_id or None,
            }
        )
        state.data[self._RESIDENT_GOAL_PROGRESS_KEY] = progress[-self._MAX_RESIDENT_GOAL_PROGRESS :]

    def _note_semantic_thought(self, thought, text: str) -> None:
        if thought is None:
            return
        if text not in thought.known:
            thought.known = (*thought.known, text)
        thought.reason = f"{thought.reason}; semantic browser investigation changed facts, not user authority"
        self._persist_enriched_thought(thought)

    def _discover_unique_search_form(self, query: str) -> dict[str, Any]:
        authorized = self.user_browser_extension.authorized_tab()
        if authorized is None:
            raise UserBrowserExtensionRelayError("no user browser tab is currently authorized")
        command = self.user_browser_extension.request_command(
            "probe_current_tab",
            args={"discover_unique_search_form": True},
            timeout_seconds=5.0,
        )
        if command.get("success") is not True:
            raise UserBrowserExtensionRelayError(
                str(command.get("error") or "authorized browser search-form discovery failed")
            )
        result = command.get("result")
        if not isinstance(result, dict):
            raise UserBrowserExtensionRelayError(
                "authorized browser search-form discovery returned no structured evidence"
            )
        try:
            tab_id = int(result.get("tab_id"))
        except (TypeError, ValueError) as exc:
            raise UserBrowserExtensionRelayError(
                "authorized browser search-form discovery returned invalid tab identity"
            ) from exc
        if tab_id != authorized.tab_id:
            raise UserBrowserExtensionRelayError(
                "authorized browser search-form discovery changed tab identity"
            )

        current_url = self._normal_http_url(result.get("url"), "current page")
        action_url = self._normal_http_url(result.get("form_action"), "search form action")
        if self._origin(current_url) != self._origin(action_url):
            raise UserBrowserExtensionRelayError(
                "autonomous search form action left the current page origin"
            )
        action = urlsplit(action_url)
        if action.query or action.fragment:
            raise UserBrowserExtensionRelayError(
                "autonomous search currently requires a GET form action without preset query or fragment"
            )
        if str(result.get("form_method") or "").strip().lower() != "get":
            raise UserBrowserExtensionRelayError(
                "autonomous current-page search requires a safe GET form"
            )

        parameter = self._bounded_label(result.get("query_parameter"), "query parameter", 128)
        textbox_name = self._bounded_label(result.get("textbox_name"), "search textbox name", 160)
        button_name = self._bounded_label(result.get("button_name"), "search button name", 160)
        textbox_target_id = self._bounded_label(
            result.get("textbox_target_id"), "search textbox identity", 256
        )
        button_target_id = self._bounded_label(
            result.get("button_target_id"), "search button identity", 256
        )
        expected_url = urlunsplit(
            (action.scheme, action.netloc, action.path, urlencode([(parameter, query)]), "")
        )
        if expected_url == current_url:
            raise UserBrowserExtensionRelayError(
                "autonomous search expected result is already the current page"
            )
        return {
            "url": current_url,
            "textbox_name": textbox_name,
            "textbox_target_id": textbox_target_id,
            "button_name": button_name,
            "button_target_id": button_target_id,
            "expected_url": expected_url,
            "query_parameter": parameter,
            "observed_at": str(command.get("completed_at") or ""),
            "source": "zn_browser_extension_search_discovery",
        }

    def _browser_named_goal_investigation(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        if self.user_browser_extension.authorized_tab() is not None:
            self._adopt_authorized_extension_browser()
        elif self.managed_browser is self._extension_user_browser:
            self._restore_browser_after_extension()
        return super()._browser_named_goal_investigation(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    @staticmethod
    def _normal_http_url(value: Any, label: str) -> str:
        url = str(value or "").strip()
        try:
            parsed = urlsplit(url)
        except ValueError as exc:
            raise UserBrowserExtensionRelayError(f"{label} URL is invalid") from exc
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise UserBrowserExtensionRelayError(f"{label} is not an HTTP(S) URL")
        return url

    @staticmethod
    def _origin(value: str) -> tuple[str, str, int | None]:
        parsed = urlsplit(value)
        try:
            port = parsed.port
        except ValueError as exc:
            raise UserBrowserExtensionRelayError("browser URL has an invalid port") from exc
        return parsed.scheme.lower(), str(parsed.hostname or "").lower(), port

    @staticmethod
    def _bounded_label(value: Any, label: str, limit: int) -> str:
        text = str(value or "").strip()
        if not text or len(text) > limit:
            raise UserBrowserExtensionRelayError(f"{label} is invalid")
        if any(ord(char) < 32 or ord(char) == 127 for char in text):
            raise UserBrowserExtensionRelayError(f"{label} contains control characters")
        return text

    def _adopt_authorized_extension_browser(self) -> None:
        if self.managed_browser is self._extension_user_browser:
            return
        self._require_browser_adapter_idle(self.managed_browser)
        self._browser_before_extension = self.managed_browser
        self.managed_browser = self._extension_user_browser

    def _restore_browser_after_extension(self) -> None:
        if self.managed_browser is not self._extension_user_browser:
            self._browser_before_extension = None
            return
        self._require_browser_adapter_idle(self._extension_user_browser)
        self._extension_user_browser.close()
        previous = self._browser_before_extension
        self._browser_before_extension = None
        if previous is not None:
            self.managed_browser = previous
