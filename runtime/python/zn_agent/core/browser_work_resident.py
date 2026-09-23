from __future__ import annotations

"""Resident Work lifecycle for bounded managed-browser navigation and interaction."""

import re
from dataclasses import asdict
from typing import Any
from urllib.parse import urlsplit

from .action import NativeActionIntent
from .browser_work_body import BrowserSideEffectAwareBody
from .recovery_bounded_resident import RecoveryBoundedResidentRuntime
from .browser_provider_registry import build_managed_browser_adapter


_URL_RE = re.compile(r"https?://[^\s<>{}\[\]\"']+", re.IGNORECASE)
_DOM_ID_RE = re.compile(r"(?<![\w-])#([A-Za-z][A-Za-z0-9_:-]{0,127})")
_QUOTED_NAME_RE = re.compile(r'["“]([^"”\r\n]{1,160})["”]')
_NAVIGATION_CUES = (
    "open ",
    "visit ",
    "browse ",
    "navigate ",
    "navigate to ",
    "go to ",
    "load ",
    "打开",
    "访问",
    "浏览",
    "前往",
    "进入",
)
_CHECK_CUES = (
    re.compile(r"\bcheck\b", re.IGNORECASE),
    re.compile(r"\btick\b", re.IGNORECASE),
)
_UNCHECK_CUES = (
    re.compile(r"\buncheck\b", re.IGNORECASE),
    re.compile(r"\buntick\b", re.IGNORECASE),
)
_CLICK_CUES = (
    re.compile(r"\bclick\b", re.IGNORECASE),
    re.compile(r"\bpress\b", re.IGNORECASE),
)
_CHECK_CUES_ZH = ("勾选", "选中")
_UNCHECK_CUES_ZH = ("取消勾选", "取消选中")
_CLICK_CUES_ZH = ("点击", "按下")
_URL_TRAILING_PUNCTUATION = ".,;:!?)]}，。！？；：）】》"


class BrowserWorkResidentRuntime(RecoveryBoundedResidentRuntime):
    """Make bounded managed browsing a real ZN Body path.

    A normal user Work may form one navigation intent directly when its task
    contains exactly one explicit HTTP(S) URL and an unambiguous navigation cue.
    It may also form one deliberately narrow checkbox mutation when the task
    supplies exactly one explicit URL and either one explicit ``#dom-id`` or one
    quoted exact accessible checkbox name plus an unambiguous check/uncheck cue.
    ZN never asks a model to invent a destination, target identity or desired
    boolean state.

    Browser mutations cross the same durable side-effect boundary as navigation.
    Provider dispatch is not accepted blindly: the managed-browser adapter binds
    action authority to a fresh target observation and reports success only after
    re-observing the same exact checkbox node in the requested state. If resident
    persistence is interrupted after dispatch, replay remains blocked rather than
    guessing whether the outside-world mutation happened.
    """

    def _new_managed_browser_adapter(self):
        """Create the capability-routed MANAGED browser owner for this Resident."""
        return build_managed_browser_adapter()

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        # The inherited managed-browser owner is lazy and has not launched a
        # provider during construction. Select the adapter through one overridable
        # capability seam; session pinning still begins only when a session opens.
        self.managed_browser = self._new_managed_browser_adapter()
        self.body = BrowserSideEffectAwareBody(resident=self)

    @staticmethod
    def _explicit_urls(task: str) -> tuple[str, ...]:
        matches: list[str] = []
        for raw in _URL_RE.findall(task):
            candidate = raw.rstrip(_URL_TRAILING_PUNCTUATION)
            if not candidate or candidate in matches:
                continue
            try:
                parsed = urlsplit(candidate)
            except ValueError:
                continue
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
                continue
            if parsed.username is not None or parsed.password is not None:
                continue
            matches.append(candidate)
        return tuple(matches)

    @staticmethod
    def _checkbox_state(text: str) -> bool | None:
        uncheck_requested = any(pattern.search(text) for pattern in _UNCHECK_CUES)
        uncheck_requested = uncheck_requested or any(cue in text for cue in _UNCHECK_CUES_ZH)
        check_text = text
        for cue in _UNCHECK_CUES_ZH:
            check_text = check_text.replace(cue, " ")
        check_requested = any(pattern.search(check_text) for pattern in _CHECK_CUES)
        check_requested = check_requested or any(cue in check_text for cue in _CHECK_CUES_ZH)
        if check_requested == uncheck_requested:
            return None
        return bool(check_requested)

    @staticmethod
    def _button_click_requested(text: str) -> bool:
        return any(pattern.search(text) for pattern in _CLICK_CUES) or any(
            cue in text for cue in _CLICK_CUES_ZH
        )

    @classmethod
    def _looks_like_checkbox_interaction(cls, task: str) -> bool:
        remainder = str(task or "")
        for url in cls._explicit_urls(remainder):
            remainder = remainder.replace(url, " ")
        lowered = remainder.lower()
        has_target_marker = bool(
            "checkbox" in lowered
            or "复选框" in remainder
            or _DOM_ID_RE.search(remainder)
        )
        return bool(has_target_marker and cls._checkbox_state(remainder) is not None)

    @classmethod
    def _looks_like_button_interaction(cls, task: str) -> bool:
        remainder = str(task or "")
        for url in cls._explicit_urls(remainder):
            remainder = remainder.replace(url, " ")
        lowered = remainder.lower()
        has_target_marker = "button" in lowered or "按钮" in remainder
        return bool(has_target_marker and cls._button_click_requested(remainder))

    @classmethod
    def _natural_navigation_url(cls, event) -> str | None:
        payload = event.payload or {}
        if payload.get("body_action") or payload.get("native_action"):
            return None

        task = str(event.task or "").strip()
        lowered = task.lower()
        if not any(cue in lowered for cue in _NAVIGATION_CUES):
            return None
        # A malformed/ambiguous mutation must fail closed rather than silently
        # degrading into a partial navigation-only action. Ordinary phrases such
        # as "open this page to check status" remain navigation.
        if cls._looks_like_checkbox_interaction(task) or cls._looks_like_button_interaction(task):
            return None

        matches = cls._explicit_urls(task)
        return matches[0] if len(matches) == 1 else None

    @classmethod
    def _natural_named_button_request(cls, event) -> tuple[str, str, str] | None:
        payload = event.payload or {}
        if payload.get("body_action") or payload.get("native_action"):
            return None

        task = str(event.task or "").strip()
        urls = cls._explicit_urls(task)
        if len(urls) != 2:
            return None
        start_url, expected_url = urls
        remainder = task
        for url in urls:
            remainder = remainder.replace(url, " ")
        lowered = remainder.lower()
        if "button" not in lowered and "按钮" not in remainder:
            return None
        if not cls._button_click_requested(remainder):
            return None

        names = []
        for match in _QUOTED_NAME_RE.finditer(remainder):
            value = match.group(1).strip()
            if value and value not in names:
                names.append(value)
        if len(names) != 1:
            return None
        return start_url, names[0], expected_url

    @classmethod
    def _natural_named_checkbox_request(cls, event) -> tuple[str, str, bool] | None:
        payload = event.payload or {}
        if payload.get("body_action") or payload.get("native_action"):
            return None

        task = str(event.task or "").strip()
        urls = cls._explicit_urls(task)
        if len(urls) != 1:
            return None
        url = urls[0]
        remainder = task.replace(url, " ")
        lowered = remainder.lower()
        if "checkbox" not in lowered and "复选框" not in remainder:
            return None
        if _DOM_ID_RE.search(remainder):
            return None

        names = []
        for match in _QUOTED_NAME_RE.finditer(remainder):
            value = match.group(1).strip()
            if value and value not in names:
                names.append(value)
        if len(names) != 1:
            return None
        checked = cls._checkbox_state(remainder)
        if checked is None:
            return None
        return url, names[0], checked

    @classmethod
    def _natural_checkbox_request(cls, event) -> tuple[str, str, bool] | None:
        payload = event.payload or {}
        if payload.get("body_action") or payload.get("native_action"):
            return None

        task = str(event.task or "").strip()
        urls = cls._explicit_urls(task)
        if len(urls) != 1:
            return None
        url = urls[0]

        # A URL fragment is navigation identity, not checkbox authority. Remove
        # explicit URL text before accepting one visible ``#dom-id`` token.
        remainder = task.replace(url, " ")
        dom_ids = []
        for match in _DOM_ID_RE.finditer(remainder):
            value = match.group(1)
            if value not in dom_ids:
                dom_ids.append(value)
        if len(dom_ids) != 1:
            return None
        checked = cls._checkbox_state(remainder)
        if checked is None:
            return None
        return url, dom_ids[0], checked

    @classmethod
    def _required_capabilities(cls, event) -> tuple[str, ...]:
        explicit = event.payload.get("required_capabilities")
        if explicit is None and (
            cls._natural_named_button_request(event) is not None
            or cls._natural_named_checkbox_request(event) is not None
            or cls._natural_checkbox_request(event) is not None
            or cls._natural_navigation_url(event) is not None
        ):
            return ("browser",)
        return super()._required_capabilities(event)

    def _deliberation_step(
        self,
        event,
        state,
        *,
        readiness,
        learning_evidence,
        thought=None,
    ):
        named_button = self._natural_named_button_request(event)
        if named_button is not None:
            url, target_name, expected_url = named_button
            intent = NativeActionIntent(
                intent_id=f"browser-named-button-{event.event_id}",
                event_id=event.event_id,
                kind="browser_click_named_button_to_url",
                args={
                    "url": url,
                    "target_name": target_name,
                    "expected_url": expected_url,
                },
                reason=(
                    "the current user Work supplies the exact browser start URL, exact quoted "
                    "accessible button name and explicit destination URL"
                ),
                source="native_deliberation",
            )
            if not self._action_blocked_by_current_evidence(event, state, intent):
                self._begin_native_action_cycle(event, state, intent)
                self.store.save_working_state(state)
                if thought is not None:
                    action = "perform body action: browser_click_named_button_to_url"
                    if action not in thought.possible_actions:
                        thought.possible_actions = (*thought.possible_actions, action)
                    thought.reason = (
                        f"{thought.reason}; the user supplied the exact page, semantic button "
                        "name and destination so ZN does not need a model to invent authority"
                    )
                    self._persist_enriched_thought(thought)
                return None

        named_checkbox = self._natural_named_checkbox_request(event)
        if named_checkbox is not None:
            url, target_name, checked = named_checkbox
            intent = NativeActionIntent(
                intent_id=f"browser-named-checkbox-{event.event_id}",
                event_id=event.event_id,
                kind="browser_set_named_checkbox",
                args={"url": url, "target_name": target_name, "checked": checked},
                reason=(
                    "the current user Work supplies the exact browser destination, exact "
                    "quoted accessible checkbox name and unambiguous requested boolean state"
                ),
                source="native_deliberation",
            )
            if not self._action_blocked_by_current_evidence(event, state, intent):
                self._begin_native_action_cycle(event, state, intent)
                self.store.save_working_state(state)
                if thought is not None:
                    action = "perform body action: browser_set_named_checkbox"
                    if action not in thought.possible_actions:
                        thought.possible_actions = (*thought.possible_actions, action)
                    thought.reason = (
                        f"{thought.reason}; the user supplied the exact page, semantic target "
                        "name and checkbox state so ZN does not need a model to invent authority"
                    )
                    self._persist_enriched_thought(thought)
                return None

        checkbox = self._natural_checkbox_request(event)
        if checkbox is not None:
            url, dom_id, checked = checkbox
            intent = NativeActionIntent(
                intent_id=f"browser-checkbox-{event.event_id}",
                event_id=event.event_id,
                kind="browser_set_checkbox",
                args={"url": url, "dom_id": dom_id, "checked": checked},
                reason=(
                    "the current user Work supplies the exact browser destination, exact "
                    "DOM-id checkbox target and unambiguous requested boolean state"
                ),
                source="native_deliberation",
            )
            if not self._action_blocked_by_current_evidence(event, state, intent):
                self._begin_native_action_cycle(event, state, intent)
                self.store.save_working_state(state)
                if thought is not None:
                    action = "perform body action: browser_set_checkbox"
                    if action not in thought.possible_actions:
                        thought.possible_actions = (*thought.possible_actions, action)
                    thought.reason = (
                        f"{thought.reason}; the user supplied the exact page, target and checkbox "
                        "state so ZN does not need a model to invent interaction authority"
                    )
                    self._persist_enriched_thought(thought)
                return None

        url = self._natural_navigation_url(event)
        if url is not None:
            intent = NativeActionIntent(
                intent_id=f"browser-{event.event_id}",
                event_id=event.event_id,
                kind="browser_navigate",
                args={"url": url, "expected_url": url},
                expected_outcome={"kind": "browser_url_equals", "url": url},
                reason=(
                    "the current user Work contains one explicit HTTP(S) destination "
                    "and an unambiguous navigation request"
                ),
                source="native_deliberation",
            )
            if not self._action_blocked_by_current_evidence(event, state, intent):
                self._begin_native_action_cycle(event, state, intent)
                self.store.save_working_state(state)
                if thought is not None:
                    action = "perform body action: browser_navigate"
                    if action not in thought.possible_actions:
                        thought.possible_actions = (*thought.possible_actions, action)
                    thought.reason = (
                        f"{thought.reason}; the user supplied the exact browser destination "
                        "so ZN does not need a model to invent one"
                    )
                    self._persist_enriched_thought(thought)
                return None

        return super()._deliberation_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    @staticmethod
    def _generic_guarded_side_effect(intent: NativeActionIntent) -> bool:
        if str(intent.kind or "").strip().lower() in {
            "browser_navigate",
            "browser_set_checkbox",
            "browser_set_named_checkbox",
            "browser_click_named_button_to_url",
        }:
            return True
        return RecoveryBoundedResidentRuntime._generic_guarded_side_effect(intent)

    def _verification_contract(
        self,
        event,
        intent: NativeActionIntent,
        *,
        result=None,
    ) -> dict[str, Any] | None:
        if str(intent.kind or "").strip().lower() != "browser_navigate":
            return super()._verification_contract(
                event,
                intent,
                result=result,
            )

        explicit = event.payload.get("expected_outcome")
        if explicit is not None:
            if not isinstance(explicit, dict):
                return super()._verification_contract(
                    event,
                    intent,
                    result=result,
                )
            requested_kind = str(explicit.get("kind") or "").strip().lower()
            if requested_kind != "browser_url_equals":
                return super()._verification_contract(
                    event,
                    intent,
                    result=result,
                )
            expected_url = str(
                explicit.get("url") or explicit.get("expected_url") or ""
            ).strip()
            if not expected_url:
                return {
                    "kind": "unsupported",
                    "requested_kind": "browser_url_equals",
                    "error": "browser_url_equals postcondition requires url",
                    "intent_id": intent.intent_id,
                    "action_signature": self._intent_signature(intent),
                }
        elif isinstance(intent.expected_outcome, dict) and str(
            intent.expected_outcome.get("kind") or ""
        ).strip().lower() == "browser_url_equals":
            expected_url = str(
                intent.expected_outcome.get("url")
                or intent.expected_outcome.get("expected_url")
                or ""
            ).strip()
            if not expected_url:
                return None
        else:
            expected_url = str(intent.args.get("expected_url") or intent.args.get("url") or "").strip()
            if not expected_url:
                return None

        data = getattr(result, "data", None)
        if not isinstance(data, dict):
            return None
        session_id = str(data.get("browser_session_id") or "").strip()
        page_id = str(data.get("page_id") or "").strip()
        if not session_id or not page_id:
            return None
        return {
            "kind": "browser_url_equals",
            "session_id": session_id,
            "page_id": page_id,
            "expected_url": expected_url,
            "intent_id": intent.intent_id,
            "action_signature": self._intent_signature(intent),
        }

    def _native_verification_step(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        raw_contract = state.data.get("native_verification")
        if not isinstance(raw_contract, dict) or str(
            raw_contract.get("kind") or ""
        ).strip().lower() != "browser_url_equals":
            return super()._native_verification_step(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        raw_intent = state.data.get("native_action_intent")
        if not isinstance(raw_intent, dict):
            state.stage = "native_deliberation"
            state.next_action = "reconstruct missing browser postcondition verification"
            self._sync_execution_context(event, state)
            self.store.save_working_state(state)
            return None

        intent = NativeActionIntent.from_dict(raw_intent)
        session_id = str(raw_contract.get("session_id") or "").strip()
        page_id = str(raw_contract.get("page_id") or "").strip()
        expected_url = str(raw_contract.get("expected_url") or "").strip()
        observed = self.body.act(
            "browser_observe",
            event_id=event.event_id,
            session_id=session_id,
            page_id=page_id,
        )
        closed = self.body.act(
            "browser_close",
            event_id=event.event_id,
            session_id=session_id,
        )
        observed_url = str(observed.data.get("url") or "") if observed.success else ""
        verified = bool(
            session_id
            and page_id
            and expected_url
            and observed.success
            and observed_url == expected_url
            and closed.success
        )
        failure = ""
        if not observed.success:
            failure = observed.error or "current browser page could not be observed"
        elif observed_url != expected_url:
            failure = (
                "browser postcondition verification failed: current URL "
                f"{observed_url!r} does not equal requested {expected_url!r}"
            )
        elif not closed.success:
            failure = closed.error or "verified browser session could not be closed"

        verification_result = {
            "verified": verified,
            "kind": "browser_url_equals",
            "session_id": session_id,
            "page_id": page_id,
            "expected_url": expected_url,
            "observed_url": observed_url or None,
            "observation": asdict(observed),
            "cleanup": asdict(closed),
        }
        state.data["native_verification_result"] = verification_result
        self._record_verified_experience(
            event,
            state,
            intent,
            verification_result=verification_result,
        )
        self._sync_execution_context(event, state)

        if verified:
            title = str(observed.data.get("title") or "").strip()
            return self._complete_successful_body_action(
                event,
                state,
                intent,
                response=title or observed_url,
                reason=(
                    "ZN completed managed browser navigation only after independently "
                    "re-observing the requested current URL through its Body"
                ),
            )

        return self._fail_postcondition_verification(
            event,
            state,
            intent,
            failure=failure or "browser postcondition verification failed",
            thought=thought,
        )

    @staticmethod
    def _expected_outcome_summary(raw: dict[str, Any]) -> dict[str, Any]:
        summary = RecoveryBoundedResidentRuntime._expected_outcome_summary(raw)
        if str(raw.get("kind") or "").strip().lower() == "browser_url_equals":
            expected_url = str(raw.get("expected_url") or raw.get("url") or "").strip()
            if expected_url:
                summary["expected_url"] = expected_url[:1000]
        return summary

    @staticmethod
    def _verification_summary(
        raw: dict[str, Any],
        *,
        error: str | None = None,
    ) -> dict[str, Any]:
        summary = RecoveryBoundedResidentRuntime._verification_summary(raw, error=error)
        if str(raw.get("kind") or "").strip().lower() == "browser_url_equals":
            for key in ("expected_url", "observed_url"):
                value = str(raw.get(key) or "").strip()
                if value:
                    summary[key] = value[:1000]
        return summary
