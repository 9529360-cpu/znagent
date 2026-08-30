from __future__ import annotations

"""Resident Work lifecycle for bounded managed-browser navigation."""

import re
from dataclasses import asdict
from typing import Any
from urllib.parse import urlsplit

from .action import NativeActionIntent
from .browser_work_body import BrowserSideEffectAwareBody
from .recovery_bounded_resident import RecoveryBoundedResidentRuntime


_URL_RE = re.compile(r"https?://[^\s<>{}\[\]\"']+", re.IGNORECASE)
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
_URL_TRAILING_PUNCTUATION = ".,;:!?)]}，。！？；：）】》"


class BrowserWorkResidentRuntime(RecoveryBoundedResidentRuntime):
    """Make managed navigation a real ZN Body action, not a parallel RPC feature.

    A normal user Work may form one navigation intent directly when its task
    contains exactly one explicit HTTP(S) URL and an unambiguous navigation cue.
    ZN never invents a destination from prose or model output. Completion still
    requires a separate current-page observation after provider dispatch, and
    the inherited side-effect recovery lifecycle blocks blind replay if
    navigation may have crossed the outside-world boundary before a durable
    checkpoint.
    """

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.body = BrowserSideEffectAwareBody(resident=self)

    @staticmethod
    def _natural_navigation_url(event) -> str | None:
        payload = event.payload or {}
        if payload.get("body_action") or payload.get("native_action"):
            return None

        task = str(event.task or "").strip()
        lowered = task.lower()
        if not any(cue in lowered for cue in _NAVIGATION_CUES):
            return None

        matches = []
        for raw in _URL_RE.findall(task):
            candidate = raw.rstrip(_URL_TRAILING_PUNCTUATION)
            if candidate and candidate not in matches:
                matches.append(candidate)
        if len(matches) != 1:
            return None

        candidate = matches[0]
        try:
            parsed = urlsplit(candidate)
        except ValueError:
            return None
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        return candidate

    @classmethod
    def _required_capabilities(cls, event) -> tuple[str, ...]:
        explicit = event.payload.get("required_capabilities")
        if explicit is None and cls._natural_navigation_url(event) is not None:
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
        if str(intent.kind or "").strip().lower() == "browser_navigate":
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
