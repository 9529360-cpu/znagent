from __future__ import annotations

"""Resident closure for authorized-page references researched in managed Chromium."""

import re
from collections import defaultdict
from typing import Any
from urllib.parse import urlsplit

from .action import NativeActionIntent
from .body import BodyActionResult
from .browser import BrowserAction, BrowserActionAuthority, BrowserActionKind, BrowserPermissionContext
from .browser_provider_registry import build_managed_browser_adapter, build_readable_managed_browser_adapter
from .goal_resident import ResidentGoalRuntime
from .user_browser_extension_relay import UserBrowserExtensionRelayError
from .user_browser_extension_resident import UserBrowserExtensionResidentRuntime


_RELEASE_CODE_RE = re.compile(
    r"(?:release\s+code|发布(?:版本)?代码|发行(?:版本)?代码)\s*[:：#-]?\s*([A-Za-z0-9][A-Za-z0-9._-]{2,63})",
    re.IGNORECASE,
)
_RETURN_POLICY_RE = re.compile(
    r"(?:official\s+return\s+policy|return\s+policy|官方退货(?:规则|政策)|退货(?:规则|政策))"
    r"\s*[:：]\s*([^\r\n]{1,500})",
    re.IGNORECASE,
)
_ZH_ORDER_SUBJECT_RE = re.compile(
    r"查(?:一下)?\s*([A-Za-z0-9_.\-\u4e00-\u9fff]{1,80})\s*最近(?:的)?订单"
)
_EN_ORDER_SUBJECT_RE = re.compile(
    r"\b(?:check|look\s+up|find)\s+([A-Za-z0-9_.\-]{1,80})['’s]*\s+(?:recent|latest)\s+orders?\b",
    re.IGNORECASE,
)
_REFERENCE_CUES = ("reference", "release", "registry", "note", "参考", "发布", "发行")
_DETAIL_CUES = ("detail", "release", "record", "version", "详情", "明细", "发布", "版本")
_RETURN_REFERENCE_CUES = (
    "official",
    "return policy",
    "return",
    "policy",
    "returns",
    "官网",
    "官方",
    "退货",
    "规则",
    "政策",
)
_NOTE_INPUT_CUES = ("note", "notes", "remark", "remarks", "备注", "说明")
_NOTE_SAVE_CUES = ("save", "update", "apply", "保存", "更新", "提交")


class UserBrowserManagedResearchResidentRuntime(UserBrowserExtensionResidentRuntime):
    """Research A-page references, then reuse the guarded USER form-submit path."""

    _MANAGED_RESEARCH_STATE_KEY = "resident_user_browser_managed_reference_research"
    _AUTHENTICATED_RETURN_NOTE_STATE_KEY = "resident_user_browser_authenticated_return_note"
    _USER_BROWSER_TASK_CONTEXT_KEY = "resident_user_browser_task_context"
    _USER_BROWSER_TASK_CONTEXT_EVENT_KEY = "_resident_user_browser_task_context"
    _USER_BROWSER_CONTEXT_ACTIONS = frozenset(
        {
            "browser_type_named_text",
            "browser_click_named_button_to_url",
            "browser_fill_named_text_and_click_named_button_to_url",
        }
    )

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.managed_browser = build_managed_browser_adapter()
        self.research_browser = build_readable_managed_browser_adapter()

    @classmethod
    def _natural_managed_reference_search(cls, event) -> bool:
        payload = event.payload or {}
        if payload.get("body_action") or payload.get("native_action"):
            return False
        task = " ".join(str(event.task or "").strip().split())
        if not task or len(task) > 1200:
            return False
        lowered = task.lower()
        has_reference = "reference" in lowered or "参考" in task
        has_code = "release code" in lowered or ("code" in lowered and "release" in lowered) or "代码" in task
        has_return = any(cue in lowered for cue in ("come back", "return", "back on this page")) or "回来" in task or "回到" in task
        has_search = "search" in lowered or "find" in lowered or "搜索" in task or "查找" in task
        return bool(has_reference and has_code and has_return and has_search)

    @classmethod
    def _natural_authenticated_return_note_update(cls, event) -> bool:
        payload = event.payload or {}
        if payload.get("body_action") or payload.get("native_action"):
            return False
        task = " ".join(str(event.task or "").strip().split())
        if not task or len(task) > 1200 or cls._order_subject(task) is None:
            return False
        lowered = task.lower()
        has_official = "official" in lowered or "官网" in task or "官方" in task
        has_return_policy = (
            "return policy" in lowered
            or ("return" in lowered and ("policy" in lowered or "rule" in lowered))
            or "退货规则" in task
            or "退货政策" in task
        )
        has_note = "note" in lowered or "备注" in task
        has_update = any(cue in lowered for cue in ("update", "save")) or "更新" in task or "保存" in task
        has_return_to_page = (
            any(cue in lowered for cue in ("come back", "back on", "return to"))
            or "回来" in task
            or "回到" in task
        )
        return bool(has_official and has_return_policy and has_note and has_update and has_return_to_page)

    @staticmethod
    def _order_subject(task: str) -> str | None:
        normalized = " ".join(str(task or "").strip().split())
        for pattern in (_ZH_ORDER_SUBJECT_RE, _EN_ORDER_SUBJECT_RE):
            match = pattern.search(normalized)
            if match is None:
                continue
            value = " ".join(str(match.group(1) or "").strip().split())
            if value:
                return value[:80]
        return None

    def _orient_step(self, event, state, *, readiness, thought=None):
        if self._natural_managed_reference_search(event) or self._natural_authenticated_return_note_update(event):
            return ResidentGoalRuntime._orient_step(
                self,
                event,
                state,
                readiness=readiness,
                thought=thought,
            )
        return super()._orient_step(
            event,
            state,
            readiness=readiness,
            thought=thought,
        )

    @classmethod
    def _required_capabilities(cls, event) -> tuple[str, ...]:
        payload = event.payload or {}
        if payload.get("required_capabilities") is None and (
            cls._natural_managed_reference_search(event)
            or cls._natural_authenticated_return_note_update(event)
        ):
            return ("browser",)
        return super()._required_capabilities(event)

    def _semantic_lookup_investigation(
        self,
        event,
        state,
        goal: dict[str, str],
        *,
        readiness,
        thought=None,
    ):
        try:
            self._ensure_user_browser_task_context(event, state)
        except Exception as exc:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=f"authorized browser task context was lost before fresh Sense: {type(exc).__name__}: {exc}",
            )
        return super()._semantic_lookup_investigation(
            event,
            state,
            goal,
            readiness=readiness,
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
        try:
            self._ensure_user_browser_task_context(event, state)
        except Exception as exc:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=f"authorized browser task context was lost before action: {type(exc).__name__}: {exc}",
            )
        return super()._semantic_lookup_deliberation(
            event,
            state,
            goal,
            thought=thought,
        )

    def _begin_native_action_cycle(self, event, state, intent):
        context = state.data.get(self._USER_BROWSER_TASK_CONTEXT_KEY)
        if (
            isinstance(context, dict)
            and str(intent.kind or "").strip().lower() in self._USER_BROWSER_CONTEXT_ACTIONS
        ):
            args = dict(intent.args or {})
            args["authorized_tab_id"] = int(context["tab_id"])
            args["authorization_attached_at"] = str(context["attached_at"])
            intent = NativeActionIntent(
                intent_id=intent.intent_id,
                event_id=intent.event_id,
                kind=intent.kind,
                args=args,
                expected_outcome=(
                    dict(intent.expected_outcome)
                    if isinstance(intent.expected_outcome, dict)
                    else intent.expected_outcome
                ),
                reason=intent.reason,
                source=intent.source,
                created_at=intent.created_at,
            )
        return super()._begin_native_action_cycle(event, state, intent)

    def _ensure_user_browser_task_context(self, event, state) -> dict[str, Any]:
        raw = state.data.get(self._USER_BROWSER_TASK_CONTEXT_KEY)
        if not isinstance(raw, dict):
            raw = (event.payload or {}).get(self._USER_BROWSER_TASK_CONTEXT_EVENT_KEY)
        current = self.user_browser_extension.authorized_tab()
        if current is None:
            raise UserBrowserExtensionRelayError(
                "the browser tab explicitly authorized for this task is no longer available"
            )

        if isinstance(raw, dict):
            try:
                expected_tab_id = int(raw.get("tab_id"))
            except (TypeError, ValueError) as exc:
                raise UserBrowserExtensionRelayError(
                    "stored browser task context has invalid tab identity"
                ) from exc
            expected_attached_at = str(raw.get("attached_at") or "").strip()
            expected_origin = str(raw.get("origin") or "").strip()
            if (
                expected_tab_id != current.tab_id
                or not expected_attached_at
                or expected_attached_at != current.attached_at
            ):
                raise UserBrowserExtensionRelayError(
                    "current browser authorization is not the authorization that owns this Work"
                )
            fresh = self.probe_user_browser_extension_tab()
            after = self.user_browser_extension.authorized_tab()
            if (
                after is None
                or after.tab_id != expected_tab_id
                or after.attached_at != expected_attached_at
                or int(fresh.get("tab_id") or 0) != expected_tab_id
            ):
                raise UserBrowserExtensionRelayError(
                    "browser task authorization changed while fresh context evidence was being observed"
                )
            fresh_origin = self._origin_url(str(fresh.get("url") or ""))
            if expected_origin and fresh_origin != expected_origin:
                raise UserBrowserExtensionRelayError(
                    "authorized browser task context left its original origin"
                )
            context = {
                "tab_id": expected_tab_id,
                "attached_at": expected_attached_at,
                "origin": expected_origin or fresh_origin,
                "initial_url": str(raw.get("initial_url") or fresh.get("url") or ""),
            }
        else:
            before_tab_id = current.tab_id
            before_attached_at = current.attached_at
            fresh = self.probe_user_browser_extension_tab()
            after = self.user_browser_extension.authorized_tab()
            if (
                after is None
                or after.tab_id != before_tab_id
                or after.attached_at != before_attached_at
                or int(fresh.get("tab_id") or 0) != before_tab_id
            ):
                raise UserBrowserExtensionRelayError(
                    "browser authorization changed while the Work was binding its task context"
                )
            context = {
                "tab_id": before_tab_id,
                "attached_at": before_attached_at,
                "origin": self._origin_url(str(fresh.get("url") or "")),
                "initial_url": str(fresh.get("url") or ""),
            }

        state.data[self._USER_BROWSER_TASK_CONTEXT_KEY] = dict(context)
        event.payload = dict(event.payload or {})
        event.payload[self._USER_BROWSER_TASK_CONTEXT_EVENT_KEY] = dict(context)
        self.store._save_event(event)
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return context

    def _investigation_step(self, event, state, *, readiness, learning_evidence, thought=None):
        if self._natural_authenticated_return_note_update(event):
            return self._authenticated_return_note_investigation(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )
        if not self._natural_managed_reference_search(event):
            return super()._investigation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )
        try:
            self._ensure_user_browser_task_context(event, state)
        except Exception as exc:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=f"reference research lost its explicitly authorized browser task context: {type(exc).__name__}: {exc}",
            )
        existing = state.data.get(self._MANAGED_RESEARCH_STATE_KEY)
        if isinstance(existing, dict) and existing.get("release_code") and existing.get("search"):
            state.stage = "native_deliberation"
            state.next_action = "submit the researched release code on the freshly re-sensed authorized page"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None
        try:
            initial = self._discover_authorized_reference_context()
            references = self._rank_reference_candidates(initial.get("references"))
            if len(references) < 2:
                raise UserBrowserExtensionRelayError("the authorized page did not expose at least two bounded reference candidates")
            research = self._research_managed_references(references)
            code = str(research["release_code"])
            self._ensure_user_browser_task_context(event, state)
            self._adopt_authorized_extension_browser()
            fresh_search = self._discover_unique_search_form(code)
            fresh_tab = self.probe_user_browser_extension_tab()
            self._ensure_user_browser_task_context(event, state)
        except Exception as exc:
            if self.managed_browser is self._extension_user_browser:
                try:
                    self._restore_browser_after_extension()
                except Exception:
                    pass
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=f"ZN could not complete bounded managed-browser reference research: {type(exc).__name__}: {exc}",
            )

        initial_search = initial.get("search_form") if isinstance(initial.get("search_form"), dict) else {}
        initial_target = str(initial_search.get("textbox_target_id") or "")
        fresh_target = str(fresh_search.get("textbox_target_id") or "")
        initial_title = str(initial.get("title") or "")
        fresh_title = str(fresh_tab.get("title") or "")
        state.data[self._MANAGED_RESEARCH_STATE_KEY] = {
            "release_code": code,
            "sources": research["sources"],
            "initial_authorized_page": {
                "url": str(initial.get("url") or ""),
                "title": initial_title,
                "textbox_target_id": initial_target,
                "observed_at": str(initial.get("observed_at") or ""),
            },
            "fresh_authorized_page": {
                "url": str(fresh_tab.get("url") or ""),
                "title": fresh_title,
                "textbox_target_id": fresh_target,
                "observed_at": str(fresh_tab.get("observed_at") or ""),
            },
            "authorized_page_changed_during_research": bool(
                (initial_target and fresh_target and initial_target != fresh_target) or initial_title != fresh_title
            ),
            "search": fresh_search,
        }
        state.data.pop("local_failure", None)
        if thought is not None:
            known = "two independently observed managed-browser sources agreed on one release code before returning to the authorized user page"
            if known not in thought.known:
                thought.known = (*thought.known, known)
            thought.reason = (
                f"{thought.reason}; ZN preserved the authorized USER tab, investigated references in an ephemeral managed browser, "
                "then freshly re-sensed the exact authorized tab before forming the existing guarded submit movement"
            )
            self._persist_enriched_thought(thought)
        state.stage = "native_deliberation"
        state.next_action = "submit the researched release code through the existing guarded USER browser Body"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _authenticated_return_note_investigation(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        del readiness
        try:
            context = self._ensure_user_browser_task_context(event, state)
        except Exception as exc:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=f"authenticated order-note Work lost its explicitly authorized browser task context: {type(exc).__name__}: {exc}",
            )
        existing = state.data.get(self._AUTHENTICATED_RETURN_NOTE_STATE_KEY)
        if isinstance(existing, dict) and existing.get("policy") and existing.get("note_form"):
            state.stage = "native_deliberation"
            state.next_action = "persist the researched return policy through the freshly grounded authorized-page note form"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        subject = self._order_subject(event.task)
        if subject is None:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason="authenticated order-note Work lost the bounded order subject before any side effect",
            )
        try:
            initial_order = self._observe_authorized_anchor(subject)
            initial = self._discover_authorized_reference_context()
            initial_note = self._discover_unique_note_update_form()
            references = self._rank_return_policy_candidates(initial.get("references"))
            if len(references) != 1:
                raise UserBrowserExtensionRelayError(
                    "the authorized order page did not expose exactly one unambiguous official return-policy reference"
                )
            research = self._research_managed_return_policy(references[0])
            policy = str(research["policy"])
            self._ensure_user_browser_task_context(event, state)
            fresh_note = self._discover_unique_note_update_form()
            fresh_tab = self.probe_user_browser_extension_tab()
            self._ensure_user_browser_task_context(event, state)
        except Exception as exc:
            if self.managed_browser is self._extension_user_browser:
                try:
                    self._restore_browser_after_extension()
                except Exception:
                    pass
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=f"ZN could not complete bounded authenticated order-note research: {type(exc).__name__}: {exc}",
            )

        initial_title = str(initial.get("title") or "")
        fresh_title = str(fresh_tab.get("title") or "")
        initial_target = str(initial_note.get("textbox_target_id") or "")
        fresh_target = str(fresh_note.get("textbox_target_id") or "")
        state.data[self._AUTHENTICATED_RETURN_NOTE_STATE_KEY] = {
            "subject": subject,
            "policy": policy,
            "source": research["source"],
            "initial_order_context": initial_order,
            "initial_authorized_page": {
                "url": str(initial.get("url") or ""),
                "title": initial_title,
                "textbox_target_id": initial_target,
                "textbox_name": str(initial_note.get("textbox_name") or ""),
                "textbox_query_parameter": str(initial_note.get("textbox_query_parameter") or ""),
                "button_target_id": str(initial_note.get("button_target_id") or ""),
                "button_name": str(initial_note.get("button_name") or ""),
                "form_signature": str(initial_note.get("form_signature") or ""),
                "observed_at": str(initial.get("observed_at") or ""),
            },
            "fresh_authorized_page": {
                "url": str(fresh_tab.get("url") or ""),
                "title": fresh_title,
                "textbox_target_id": fresh_target,
                "textbox_name": str(fresh_note.get("textbox_name") or ""),
                "textbox_query_parameter": str(fresh_note.get("textbox_query_parameter") or ""),
                "button_target_id": str(fresh_note.get("button_target_id") or ""),
                "button_name": str(fresh_note.get("button_name") or ""),
                "form_signature": str(fresh_note.get("form_signature") or ""),
                "observed_at": str(fresh_tab.get("observed_at") or ""),
            },
            "authorized_page_changed_during_research": bool(
                (initial_target and fresh_target and initial_target != fresh_target)
                or initial_title != fresh_title
                or str(initial_note.get("textbox_name") or "") != str(fresh_note.get("textbox_name") or "")
                or str(initial_note.get("button_name") or "") != str(fresh_note.get("button_name") or "")
                or str(initial_note.get("form_signature") or "") != str(fresh_note.get("form_signature") or "")
            ),
            "authorization_attached_at": str(context.get("attached_at") or ""),
            "note_form": fresh_note,
        }
        state.data.pop("local_failure", None)
        if thought is not None:
            known = "fresh authorized-tab evidence bound the order subject before public return-policy research"
            if known not in thought.known:
                thought.known = (*thought.known, known)
            thought.reason = (
                f"{thought.reason}; ZN preserved the authenticated USER tab, researched only the unambiguous official return-policy reference in managed Chromium, then freshly grounded the POST note form before any mutation"
            )
            self._persist_enriched_thought(thought)
        state.stage = "native_deliberation"
        state.next_action = "save the researched return policy through the existing guarded USER browser Body"
        self._sync_execution_context(event, state)
        self.store.save_working_state(state)
        return None

    def _deliberation_step(self, event, state, *, readiness, learning_evidence, thought=None):
        if self._natural_authenticated_return_note_update(event):
            return self._authenticated_return_note_deliberation(
                event,
                state,
                thought=thought,
            )
        if not self._natural_managed_reference_search(event):
            return super()._deliberation_step(
                event,
                state,
                readiness=readiness,
                learning_evidence=learning_evidence,
                thought=thought,
            )
        try:
            self._ensure_user_browser_task_context(event, state)
        except Exception as exc:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=f"the explicitly authorized browser task context is no longer available: {type(exc).__name__}: {exc}",
            )
        evidence = state.data.get(self._MANAGED_RESEARCH_STATE_KEY)
        if not isinstance(evidence, dict):
            state.stage = "native_investigation"
            state.next_action = "inspect the authorized page references and investigate them in managed Chromium"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None
        code = str(evidence.get("release_code") or "")
        search = evidence.get("search")
        if not code or not isinstance(search, dict):
            state.stage = "native_investigation"
            state.next_action = "rebuild bounded research evidence"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None
        self._adopt_authorized_extension_browser()
        intent = NativeActionIntent(
            intent_id=f"browser-managed-research-search-{event.event_id}",
            event_id=event.event_id,
            kind=self._BROWSER_FILL_AND_SUBMIT,
            args={
                "url": str(search.get("url") or ""),
                "textbox_name": str(search.get("textbox_name") or ""),
                "text": code,
                "button_name": str(search.get("button_name") or ""),
                "expected_url": str(search.get("expected_url") or ""),
            },
            reason=(
                "two managed-browser sources agreed on the release code and the authorized A page was freshly re-sensed; "
                "reuse the existing guarded USER form movement so target re-observation, postcondition verification and non-replay remain unchanged"
            ),
            source="resident_choice",
        )
        if not self._action_blocked_by_current_evidence(event, state, intent):
            self._begin_native_action_cycle(event, state, intent)
            self.store.save_working_state(state)
            if thought is not None:
                action = "search the freshly re-sensed authorized page for the independently researched release code"
                if action not in thought.possible_actions:
                    thought.possible_actions = (*thought.possible_actions, action)
                self._persist_enriched_thought(thought)
        return None

    def _authenticated_return_note_deliberation(self, event, state, *, thought=None):
        try:
            self._ensure_user_browser_task_context(event, state)
        except Exception as exc:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=f"the authenticated order-note browser context is no longer available: {type(exc).__name__}: {exc}",
            )
        evidence = state.data.get(self._AUTHENTICATED_RETURN_NOTE_STATE_KEY)
        if not isinstance(evidence, dict):
            state.stage = "native_investigation"
            state.next_action = "freshly bind the order, official policy reference, and current note form"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None
        policy = str(evidence.get("policy") or "").strip()
        note_form = evidence.get("note_form")
        if not policy or not isinstance(note_form, dict):
            state.stage = "native_investigation"
            state.next_action = "rebuild bounded return-policy and note-form evidence"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None
        self._adopt_authorized_extension_browser()
        intent = NativeActionIntent(
            intent_id=f"browser-authenticated-return-note-{event.event_id}",
            event_id=event.event_id,
            kind=self._BROWSER_FILL_AND_SUBMIT,
            args={
                "url": str(note_form.get("url") or ""),
                "textbox_name": str(note_form.get("textbox_name") or ""),
                "text": policy,
                "button_name": str(note_form.get("button_name") or ""),
                "expected_url": str(note_form.get("expected_url") or ""),
            },
            reason=(
                "fresh authorized-tab evidence proved one safe empty POST note form after public policy research; reuse the existing guarded USER fill+submit Body so target re-observation, durable side-effect accounting and no-replay remain unchanged"
            ),
            source="resident_choice",
        )
        if not self._action_blocked_by_current_evidence(event, state, intent):
            self._begin_native_action_cycle(event, state, intent)
            self.store.save_working_state(state)
            if thought is not None:
                action = "save the freshly researched official return policy into the freshly grounded order note"
                if action not in thought.possible_actions:
                    thought.possible_actions = (*thought.possible_actions, action)
                self._persist_enriched_thought(thought)
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
        if (
            self._natural_authenticated_return_note_update(event)
            and str(intent.kind or "").strip().lower() == self._BROWSER_FILL_AND_SUBMIT
        ):
            raw_result = state.data.get("native_action_result")
            try:
                result = BodyActionResult(**raw_result) if isinstance(raw_result, dict) else None
            except (TypeError, ValueError):
                result = None
            evidence = state.data.get(self._AUTHENTICATED_RETURN_NOTE_STATE_KEY)
            if (
                result is not None
                and isinstance(evidence, dict)
                and self._form_submit_result_proves_intent(result, intent)
            ):
                subject = str(evidence.get("subject") or "").strip()
                policy = str(evidence.get("policy") or "").strip()
                expected_url = str(intent.args.get("expected_url") or "").strip()
                try:
                    self._ensure_user_browser_task_context(event, state)
                    saved = self._observe_authorized_anchor(subject)
                    if str(saved.get("url") or "") != expected_url:
                        raise UserBrowserExtensionRelayError(
                            "fresh saved-note observation is not on the Body-verified submitted URL"
                        )
                    if policy not in str(saved.get("context") or ""):
                        raise UserBrowserExtensionRelayError(
                            "fresh saved-note observation did not contain the researched official policy text"
                        )
                    evidence = dict(evidence)
                    evidence["saved_verification"] = saved
                    evidence["saved_business_state_verified"] = True
                    state.data[self._AUTHENTICATED_RETURN_NOTE_STATE_KEY] = evidence
                    self._sync_execution_context(event, state)
                    self.store.save_working_state(state)
                except Exception as exc:
                    return self._fail_composite_goal_investigation(
                        event,
                        state,
                        reason=f"the note mutation occurred but fresh saved-state verification failed closed: {type(exc).__name__}: {exc}",
                    )
                response = f"{subject}: {policy}"
                reason = (
                    "ZN completed the authenticated order-note Work only after public managed-browser research, fresh same-authorization note-form grounding, provider-verified guarded submission, and a fresh anchored read proving the saved policy text on the exact submitted page"
                )
        return super()._complete_successful_body_action(
            event,
            state,
            intent,
            response=response,
            reason=reason,
        )

    def _observe_authorized_anchor(self, anchor_text: str) -> dict[str, Any]:
        self._adopt_authorized_extension_browser()
        try:
            return self._extension_user_browser.observe_anchor_context(anchor_text)
        finally:
            self._restore_browser_after_extension()

    def _discover_authorized_reference_context(self) -> dict[str, Any]:
        self._adopt_authorized_extension_browser()
        try:
            authorized = self.user_browser_extension.authorized_tab()
            if authorized is None:
                raise UserBrowserExtensionRelayError("no user browser tab is currently authorized")
            command = self.user_browser_extension.request_command(
                "probe_current_tab",
                args={"discover_reference_context": True},
                timeout_seconds=5.0,
                expected_tab_id=authorized.tab_id,
                expected_attached_at=authorized.attached_at,
            )
            if command.get("success") is not True:
                raise UserBrowserExtensionRelayError(str(command.get("error") or "authorized-page reference discovery failed"))
            result = command.get("result")
            if not isinstance(result, dict):
                raise UserBrowserExtensionRelayError("authorized-page reference discovery returned no structured evidence")
            if int(result.get("tab_id") or 0) != authorized.tab_id:
                raise UserBrowserExtensionRelayError("authorized-page reference discovery changed tab identity")
            result = dict(result)
            result["observed_at"] = str(command.get("completed_at") or "")
            return result
        finally:
            self._restore_browser_after_extension()

    @staticmethod
    def _rank_reference_candidates(raw: Any) -> list[dict[str, str]]:
        if not isinstance(raw, list):
            return []
        ranked: list[tuple[int, int, dict[str, str]]] = []
        seen: set[str] = set()
        for index, item in enumerate(raw[:16]):
            if not isinstance(item, dict):
                continue
            href = str(item.get("href") or "").strip()
            text = " ".join(str(item.get("text") or "").strip().split())
            if not href or not text or href in seen:
                continue
            try:
                parsed = urlsplit(href)
            except ValueError:
                continue
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
                continue
            seen.add(href)
            haystack = f"{text} {parsed.path}".lower()
            score = sum(1 for cue in _REFERENCE_CUES if cue in haystack)
            ranked.append((score, -index, {"href": href, "text": text[:240]}))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in ranked[:6]]

    @staticmethod
    def _rank_return_policy_candidates(raw: Any) -> list[dict[str, str]]:
        if not isinstance(raw, list):
            return []
        ranked: list[tuple[int, int, dict[str, str]]] = []
        seen: set[str] = set()
        for index, item in enumerate(raw[:16]):
            if not isinstance(item, dict):
                continue
            href = str(item.get("href") or "").strip()
            text = " ".join(str(item.get("text") or "").strip().split())
            if not href or not text or href in seen:
                continue
            try:
                parsed = urlsplit(href)
            except ValueError:
                continue
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
                continue
            haystack = f"{text} {parsed.path}".lower()
            score = sum(1 for cue in _RETURN_REFERENCE_CUES if cue in haystack)
            if score <= 0:
                continue
            seen.add(href)
            ranked.append((score, -index, {"href": href, "text": text[:240]}))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        if not ranked:
            return []
        top_score = ranked[0][0]
        return [item[2] for item in ranked if item[0] == top_score]

    def _discover_unique_note_update_form(self) -> dict[str, str]:
        self._adopt_authorized_extension_browser()
        try:
            sense = self._extension_user_browser.observe_semantic_candidates()
            grounded = self._note_update_form_from_sense(sense)
            textbox = self._bind_exact_semantic_target(
                url=grounded["url"],
                name=grounded["textbox_name"],
                role="textbox",
            )
            button = self._bind_exact_semantic_target(
                url=grounded["url"],
                name=grounded["button_name"],
                role="button",
            )
            return {
                **grounded,
                "textbox_target_id": str(textbox.get("target_id") or ""),
                "textbox_observed_at": str(textbox.get("observed_at") or ""),
                "button_target_id": str(button.get("target_id") or ""),
                "button_observed_at": str(button.get("observed_at") or ""),
                "observed_at": str(sense.get("observed_at") or ""),
            }
        finally:
            self._restore_browser_after_extension()

    @classmethod
    def _note_update_form_from_sense(cls, sense: dict[str, Any]) -> dict[str, str]:
        if sense.get("truncated") is True:
            raise UserBrowserExtensionRelayError(
                "authorized-page semantic candidate Sense was truncated, so note-form ambiguity cannot be excluded"
            )
        current_url = str(sense.get("url") or "").strip()
        current_origin = cls._origin_url(current_url)
        candidates = list(sense.get("candidates") or [])
        safe_textboxes: list[tuple[dict[str, Any], str, str, str, bool]] = []
        for item in candidates:
            if not isinstance(item, dict) or str(item.get("role") or "").lower() != "textbox":
                continue
            name = " ".join(str(item.get("name") or "").strip().split())
            if not name:
                continue
            if not (
                item.get("enabled") is True
                and item.get("visible") is True
                and item.get("editable") is True
                and item.get("sensitive") is not True
                and int(item.get("text_length") or 0) == 0
                and str(item.get("form_method") or "").lower() == "post"
                and str(item.get("form_signature") or "").strip()
                and str(item.get("form_action") or "").strip()
            ):
                continue
            action = str(item.get("form_action") or "").strip()
            if cls._origin_url(action) != current_origin:
                continue
            query_parameter = " ".join(str(item.get("query_parameter") or "").strip().split())
            semantic_values = (name.lower(), query_parameter.lower())
            has_note_cue = any(cue in value for value in semantic_values for cue in _NOTE_INPUT_CUES)
            safe_textboxes.append((item, name, action, query_parameter, has_note_cue))

        semantic_textboxes = [candidate for candidate in safe_textboxes if candidate[4]]
        if len(semantic_textboxes) == 1:
            selected_textbox = semantic_textboxes[0]
        elif len(semantic_textboxes) > 1:
            raise UserBrowserExtensionRelayError(
                "fresh authorized page exposed multiple safe POST textboxes with note semantics"
            )
        elif len(safe_textboxes) == 1:
            # Structural fallback is intentionally bounded: it is only valid when
            # the fresh page exposes one safe same-origin empty POST textbox total.
            # No DOM order, screen position, stale target, or model guess resolves ambiguity.
            selected_textbox = safe_textboxes[0]
        else:
            raise UserBrowserExtensionRelayError(
                "fresh authorized page did not expose one uniquely grounded safe empty POST note textbox"
            )

        textbox, textbox_name, form_action, query_parameter, _has_note_cue = selected_textbox
        signature = str(textbox.get("form_signature") or "").strip()
        safe_buttons: list[tuple[dict[str, Any], str, bool]] = []
        for item in candidates:
            if not isinstance(item, dict) or str(item.get("role") or "").lower() != "button":
                continue
            name = " ".join(str(item.get("name") or "").strip().split())
            if not name:
                continue
            if not (
                item.get("enabled") is True
                and item.get("visible") is True
                and item.get("clickable") is True
                and item.get("sensitive") is not True
                and str(item.get("form_method") or "").lower() == "post"
                and str(item.get("form_signature") or "").strip() == signature
                and str(item.get("form_action") or "").strip() == form_action
            ):
                continue
            has_save_cue = any(cue in name.lower() for cue in _NOTE_SAVE_CUES)
            safe_buttons.append((item, name, has_save_cue))

        semantic_buttons = [candidate for candidate in safe_buttons if candidate[2]]
        if len(semantic_buttons) == 1:
            selected_button = semantic_buttons[0]
        elif len(semantic_buttons) > 1:
            raise UserBrowserExtensionRelayError(
                "fresh authorized page exposed multiple safe same-form buttons with save semantics"
            )
        elif len(safe_buttons) == 1:
            # As with the textbox, the fallback is structural only when the
            # current form has exactly one safe clickable POST button.
            selected_button = safe_buttons[0]
        else:
            raise UserBrowserExtensionRelayError(
                "fresh authorized page did not expose one uniquely grounded safe same-form note save button"
            )

        _button, button_name, _has_save_cue = selected_button
        return {
            "url": current_url,
            "textbox_name": textbox_name,
            "textbox_query_parameter": query_parameter,
            "button_name": button_name,
            "form_signature": signature,
            "expected_url": form_action,
        }

    def _research_managed_return_policy(self, reference: dict[str, str]) -> dict[str, Any]:
        browser = self.research_browser
        if not callable(getattr(browser, "read_page", None)):
            raise RuntimeError("readable managed browser adapter is unavailable")
        source_url = str(reference.get("href") or "").strip()
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_private_network=True,
            allowed_origins=(self._origin_url(source_url),),
        )
        session = browser.open_session(permission=permission, headless=True)
        try:
            page = self._navigate_and_read(browser, session.session_id, source_url, permission)
            policy = self._return_policy(page.get("text"))
            if policy is None:
                raise RuntimeError(
                    "managed official-policy page did not expose one bounded return-policy statement"
                )
            return {
                "policy": policy,
                "source": {
                    "source_url": source_url,
                    "evidence_url": str(page.get("url") or source_url),
                    "observed_at": str(page.get("captured_at") or ""),
                },
            }
        finally:
            browser.close_session(session.session_id)

    def _research_managed_references(self, references: list[dict[str, str]]) -> dict[str, Any]:
        browser = self.research_browser
        if not callable(getattr(browser, "read_page", None)):
            raise RuntimeError("readable managed browser adapter is unavailable")
        allowed_origins = tuple(dict.fromkeys(self._origin_url(str(item["href"])) for item in references))
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_private_network=True,
            allowed_origins=allowed_origins,
        )
        session = browser.open_session(permission=permission, headless=True)
        source_evidence: list[dict[str, str]] = []
        codes: dict[str, list[str]] = defaultdict(list)
        try:
            for reference in references:
                source_url = str(reference["href"])
                page = self._navigate_and_read(browser, session.session_id, source_url, permission)
                code = self._release_code(page.get("text"))
                evidence_url = str(page.get("url") or source_url)
                observed_at = str(page.get("captured_at") or "")
                if code is None:
                    for detail in self._detail_candidates(page, source_url):
                        detail_page = self._navigate_and_read(browser, session.session_id, detail, permission)
                        detail_code = self._release_code(detail_page.get("text"))
                        if detail_code is None:
                            continue
                        code = detail_code
                        evidence_url = str(detail_page.get("url") or detail)
                        observed_at = str(detail_page.get("captured_at") or "")
                        break
                if code is None:
                    continue
                source_evidence.append(
                    {
                        "source_url": source_url,
                        "evidence_url": evidence_url,
                        "release_code": code,
                        "observed_at": observed_at,
                    }
                )
                if source_url not in codes[code]:
                    codes[code].append(source_url)
                if len(codes[code]) >= 2:
                    return {"release_code": code, "sources": source_evidence}
            raise RuntimeError("managed reference investigation did not find two distinct sources agreeing on one release code")
        finally:
            browser.close_session(session.session_id)

    @staticmethod
    def _navigate_and_read(browser, session_id: str, url: str, permission: BrowserPermissionContext) -> dict[str, Any]:
        observation = browser.observe(session_id)
        action = BrowserAction.create(
            session_id=session_id,
            kind=BrowserActionKind.NAVIGATE,
            page_id=observation.page_id,
            args={"url": url},
            expected={"url_equals": url},
        )
        authority = BrowserActionAuthority.from_observation(action, observation, permission)
        effect = browser.act(action, authority)
        if not effect.success:
            raise RuntimeError(effect.error or "managed browser navigation failed")
        return browser.read_page(session_id, page_id=effect.page_id)

    @staticmethod
    def _release_code(value: Any) -> str | None:
        matches = [match.group(1).strip() for match in _RELEASE_CODE_RE.finditer(str(value or ""))]
        unique = list(dict.fromkeys(match for match in matches if match))
        return unique[0] if len(unique) == 1 else None

    @staticmethod
    def _return_policy(value: Any) -> str | None:
        matches = [
            " ".join(match.group(1).strip().split())
            for match in _RETURN_POLICY_RE.finditer(str(value or ""))
        ]
        unique = list(dict.fromkeys(match for match in matches if match))
        return unique[0] if len(unique) == 1 else None

    @staticmethod
    def _detail_candidates(page: dict[str, Any], source_url: str) -> list[str]:
        raw = page.get("links")
        if not isinstance(raw, list):
            return []
        origin = UserBrowserManagedResearchResidentRuntime._origin(source_url)
        scored: list[tuple[int, int, str]] = []
        seen: set[str] = set()
        for index, item in enumerate(raw[:24]):
            if not isinstance(item, dict):
                continue
            href = str(item.get("href") or "").strip()
            label = str(item.get("text") or "").strip()
            if not href or href in seen or href == source_url:
                continue
            try:
                if UserBrowserManagedResearchResidentRuntime._origin(href) != origin:
                    continue
                parsed = urlsplit(href)
            except ValueError:
                continue
            seen.add(href)
            haystack = f"{label} {parsed.path}".lower()
            score = sum(1 for cue in _DETAIL_CUES if cue in haystack)
            if score > 0:
                scored.append((score, -index, href))
        scored.sort(reverse=True)
        return [item[2] for item in scored[:4]]

    @staticmethod
    def _origin(value: str) -> tuple[str, str, int | None]:
        parsed = urlsplit(value)
        return (parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port)

    @staticmethod
    def _origin_url(value: str) -> str:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        scheme = parsed.scheme.lower()
        if not host or scheme not in {"http", "https"}:
            raise ValueError("managed reference URL must be HTTP(S)")
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        default = 80 if scheme == "http" else 443
        netloc = host if parsed.port in {None, default} else f"{host}:{parsed.port}"
        return f"{scheme}://{netloc}"