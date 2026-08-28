from __future__ import annotations

"""Resident Work lifecycle for bounded managed-browser navigation."""

from dataclasses import asdict
from typing import Any

from .action import NativeActionIntent
from .browser_work_body import BrowserSideEffectAwareBody
from .recovery_bounded_resident import RecoveryBoundedResidentRuntime


class BrowserWorkResidentRuntime(RecoveryBoundedResidentRuntime):
    """Make managed navigation a real ZN Body action, not a parallel RPC feature.

    Only structured ``browser_navigate`` action intent is added here. Completion
    requires a separate current-page observation after provider dispatch. The
    inherited side-effect recovery lifecycle blocks blind replay if navigation
    may have crossed the outside-world boundary before a durable checkpoint.
    """

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.body = BrowserSideEffectAwareBody(resident=self)

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
