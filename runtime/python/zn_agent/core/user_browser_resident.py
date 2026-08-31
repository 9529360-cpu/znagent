from __future__ import annotations

"""Resident-owned authorization and semantic routing for the user's browser."""

import hashlib
from dataclasses import asdict
from typing import Any

from .action import NativeActionIntent
from .browser import BrowserPermissionContext, BrowserPlane
from .browser_goal_understanding_resident import BrowserGoalUnderstandingResidentRuntime
from .browser_named_goal import browser_named_text_request
from .models import utc_now
from .semantic_managed_browser import SemanticPlaywrightManagedBrowser
from .user_browser import AuthorizedCDPUserBrowser


class UserBrowserBridgeResidentRuntime(BrowserGoalUnderstandingResidentRuntime):
    """Adopt an authorized browser and prefer semantic grounding when available."""

    _SEMANTIC_BROWSER_GOAL_KEY = "resident_user_browser_semantic_goal"

    def authorize_existing_user_browser(self, endpoint: str) -> dict[str, Any]:
        current = self.managed_browser
        self._require_browser_adapter_idle(current)
        replacement = AuthorizedCDPUserBrowser(endpoint=endpoint)
        if getattr(current, "plane", None) is BrowserPlane.USER:
            close = getattr(current, "close", None)
            if callable(close):
                close()
        self.managed_browser = replacement
        return {
            "authorized": True,
            "plane": BrowserPlane.USER.value,
            "provider": replacement.name,
            "profile_scope": "user_existing",
            "endpoint_scope": "loopback_local",
            "browser_ownership": "user",
        }

    def revoke_existing_user_browser(self) -> dict[str, Any]:
        current = self.managed_browser
        was_user = getattr(current, "plane", None) is BrowserPlane.USER
        if was_user:
            self._require_browser_adapter_idle(current)
            close = getattr(current, "close", None)
            if callable(close):
                close()
            self.managed_browser = SemanticPlaywrightManagedBrowser()
        return {
            "authorized": False,
            "revoked": bool(was_user),
            "plane": BrowserPlane.MANAGED.value,
            "browser_ownership": "resident",
        }

    def user_browser_authorization(self) -> dict[str, Any]:
        current = self.managed_browser
        if getattr(current, "plane", None) is BrowserPlane.USER:
            return {
                "authorized": True,
                "plane": BrowserPlane.USER.value,
                "provider": str(getattr(current, "name", "")),
                "profile_scope": "user_existing",
                "endpoint_scope": "loopback_local",
                "browser_ownership": "user",
            }
        return {
            "authorized": False,
            "plane": BrowserPlane.MANAGED.value,
            "browser_ownership": "resident",
        }

    def _browser_named_goal_investigation(
        self,
        event,
        state,
        *,
        readiness,
        thought=None,
    ):
        browser = self.managed_browser
        request = browser_named_text_request(event)
        if request is None or not isinstance(browser, AuthorizedCDPUserBrowser):
            return super()._browser_named_goal_investigation(
                event,
                state,
                readiness=readiness,
                thought=thought,
            )

        permission = BrowserPermissionContext(
            allow_navigation=False,
            allow_page_interaction=True,
            allow_text_entry=True,
        )
        session = None
        try:
            session = browser.open_session(permission=permission, headless=False)
            current = browser.observe(session.session_id)
            observed, text_state = browser.observe_named_text_state(
                session.session_id,
                request["target_name"],
                page_id=current.page_id,
            )
        except Exception as exc:
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "authorized user-browser semantic investigation could not prove the current "
                    f"safe exact-name textbox state: {type(exc).__name__}: {exc}"
                ),
            )
        finally:
            if session is not None:
                try:
                    browser.close_session(session.session_id)
                except Exception:
                    pass

        expected_sha = hashlib.sha256(request["text"].encode("utf-8")).hexdigest()
        text_length = int(text_state["text_length"])
        text_sha = str(text_state["text_sha256"])
        if text_length == len(request["text"]) and text_sha == expected_sha:
            phase = "satisfied"
        elif text_length == 0:
            phase = "needs_text"
        else:
            phase = "blocked"

        state.data[self._SEMANTIC_BROWSER_GOAL_KEY] = {
            "phase": phase,
            "url": observed.url,
            "page_id": observed.page_id,
            "target": asdict(observed.target) if observed.target is not None else None,
            "text_length": text_length,
            "text_sha256": text_sha,
            "expected_text_length": len(request["text"]),
            "expected_text_sha256": expected_sha,
            "observed_at": utc_now(),
        }
        state.data.pop("local_failure", None)

        if thought is not None:
            known = (
                "fresh authorized browser semantic evidence identified the exact named textbox "
                "and a privacy-safe current text digest"
            )
            if known not in thought.known:
                thought.known = (*thought.known, known)
            thought.reason = (
                f"{thought.reason}; authorized USER-plane semantic grounding places the goal "
                f"in phase={phase} without using Windows UIA as the primary path"
            )
            self._persist_enriched_thought(thought)

        if phase == "satisfied":
            return self._complete_goal_from_fresh_investigation(
                event,
                state,
                readiness=readiness,
                response=(
                    f"authorized browser target {request['target_name']!r} contains the requested text"
                ),
                reason=(
                    "ZN completed the user-browser goal only after a fresh authorized semantic "
                    "target observation and privacy-safe text digest proved the final state"
                ),
            )
        if phase == "blocked":
            return self._fail_composite_goal_investigation(
                event,
                state,
                reason=(
                    "the authorized semantic textbox already contains different non-empty text; "
                    "refusing replacement or deletion without broader user authority"
                ),
            )

        state.stage = "native_deliberation"
        state.next_action = "form one semantic USER-plane text movement from fresh browser evidence"
        self._sync_execution_context(event, state)
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
        request = browser_named_text_request(event)
        browser = self.managed_browser
        if request is not None and isinstance(browser, AuthorizedCDPUserBrowser):
            evidence = state.data.get(self._SEMANTIC_BROWSER_GOAL_KEY)
            if not isinstance(evidence, dict) or evidence.get("phase") != "needs_text":
                state.stage = "native_investigation"
                state.next_action = "refresh authorized semantic browser evidence"
                self._sync_execution_context(event, state)
                self.store.save_working_state(state)
                return None
            url = str(evidence.get("url") or "").strip()
            if not url:
                return self._fail_composite_goal_investigation(
                    event,
                    state,
                    reason="authorized semantic browser evidence lost the current page URL",
                )
            intent = NativeActionIntent(
                intent_id=f"user-browser-semantic-text-{event.event_id}",
                event_id=event.event_id,
                kind="browser_type_named_text",
                args={
                    "url": url,
                    "target_name": request["target_name"],
                    "text": request["text"],
                },
                reason=(
                    "fresh authorized semantic evidence proves the current page, exact textbox "
                    "identity and empty text state"
                ),
                source="resident_choice",
            )
            if not self._action_blocked_by_current_evidence(event, state, intent):
                self._begin_native_action_cycle(event, state, intent)
                self.store.save_working_state(state)
                if thought is not None:
                    action = "perform authorized semantic browser text movement"
                    if action not in thought.possible_actions:
                        thought.possible_actions = (*thought.possible_actions, action)
                    thought.reason = (
                        f"{thought.reason}; the next movement reuses the existing verified "
                        "browser_type_named_text Body path and will be re-sensed before completion"
                    )
                    self._persist_enriched_thought(thought)
                return None
            return None

        return super()._deliberation_step(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    @staticmethod
    def _require_browser_adapter_idle(adapter: Any) -> None:
        sessions = getattr(adapter, "_sessions", None)
        if isinstance(sessions, dict) and sessions:
            raise RuntimeError(
                "cannot switch browser ownership while a browser session is active"
            )
