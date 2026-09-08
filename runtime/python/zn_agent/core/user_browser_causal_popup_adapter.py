from __future__ import annotations

"""Task-scoped causal child-tab support for the extension USER browser."""

import hashlib
from typing import Any
from urllib.parse import urlsplit

from .browser import BrowserAction, BrowserEffectEvidence
from .models import utc_now
from .user_browser_extension_adapter import (
    AuthorizedExtensionUserBrowser,
    ExtensionUserBrowserError,
    _ExtensionSession,
)
from .user_browser_extension_relay import UserBrowserExtensionCommandUncertainError


class CausalPopupAuthorizedExtensionUserBrowser(AuthorizedExtensionUserBrowser):
    """Keep root authorization fixed while proving one action-caused child tab.

    The relay authorization and BrowserSessionIdentity always remain rooted in the
    exact user-authorized tab.  A child tab is exposed only as privacy-safe effect
    evidence plus one transient bounded title used by the current Work to interpret
    the requested fact.  It is never inserted into the authorization/session store.
    """

    _CAUSAL_POSTCONDITION = "causal_child_verified_and_returned_to_exact_root"

    def __init__(self, relay) -> None:
        super().__init__(relay)
        self._causal_child_results: dict[str, dict[str, Any]] = {}

    def close(self) -> None:
        self._causal_child_results.clear()
        super().close()

    def causal_child_result(self, task_action_id: str) -> dict[str, Any] | None:
        value = self._causal_child_results.get(str(task_action_id or "").strip())
        return dict(value) if isinstance(value, dict) else None

    def discard_causal_child_result(self, task_action_id: str) -> None:
        self._causal_child_results.pop(str(task_action_id or "").strip(), None)

    def _act_click(
        self,
        session: _ExtensionSession,
        action: BrowserAction,
        current,
        page_id: str,
    ) -> BrowserEffectEvidence:
        if action.expected.get("causal_popup_allowed") is not True:
            return super()._act_click(session, action, current, page_id)

        target = action.target
        if target is None or target.role != "button" or not target.name:
            raise ExtensionUserBrowserError(
                "causal extension CLICK requires one exact native button target"
            )
        expected_url = self._safe_url(action.expected.get("url_equals"))
        if not session.permission.allows_origin(expected_url):
            raise ExtensionUserBrowserError(
                "causal child expected URL is outside the permitted root origin boundary"
            )
        if expected_url == current.url:
            raise ExtensionUserBrowserError(
                "causal child expected URL is already the authorized root URL"
            )
        task_action_id = self._bounded_text(
            action.expected.get("task_action_id"), "task action id", 160
        )
        try:
            command = self._request_for_session(
                session,
                "click_named_button_to_url",
                args={
                    "target_name": target.name,
                    "target_id": target.target_id,
                    "expected_url_before": current.url,
                    "expected_url_after": expected_url,
                    "causal_popup_allowed": True,
                    "task_action_id": task_action_id,
                },
            )
        except UserBrowserExtensionCommandUncertainError as exc:
            session.last_observation.clear()
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=utc_now(),
                success=False,
                page_id=page_id,
                url_before=current.url,
                url_after=current.url,
                target_id=target.target_id,
                data={
                    "provider": self.name,
                    "click_sent": False,
                    "click_may_have_been_sent": True,
                    "command_delivery": "extension_received",
                    "requires_fresh_resense": True,
                    "expected_url_sha256": hashlib.sha256(expected_url.encode("utf-8")).hexdigest(),
                    "expected_origin": self._origin(expected_url),
                    "task_action_id": task_action_id,
                },
                error=(
                    f"{exc}; refusing replay because popup creation may already have occurred"
                ),
            )

        if command.get("success") is not True:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=str(command.get("completed_at") or utc_now()),
                success=False,
                page_id=page_id,
                url_before=current.url,
                url_after=current.url,
                target_id=target.target_id,
                data={"provider": self.name, "click_sent": False},
                error=str(command.get("error") or "extension causal button command failed"),
            )

        result = self._command_result(command, "authorized causal child click")
        authorized_after = self.relay.authorized_tab()
        generation_unchanged = bool(
            authorized_after is not None
            and authorized_after.tab_id == session.tab_id
            and authorized_after.attached_at == session.authorization_attached_at
            and str(command.get("authorization_attached_at") or "")
            == session.authorization_attached_at
        )
        root_authorization_preserved = generation_unchanged
        tab_id = self._tab_id(result)
        if tab_id != session.tab_id:
            raise ExtensionUserBrowserError("causal button result changed root tab identity")
        url_before = self._safe_url(result.get("url_before"))
        root_url_after = self._safe_url(result.get("url_after"))
        result_target = str(result.get("target_id") or "").strip()
        click_sent = result.get("click_sent") is True
        exact_node = result.get("exact_node_continuity") is True
        revalidated = result.get("target_revalidated_before_dispatch") is True
        result_expected = self._safe_url(result.get("expected_url"))
        postcondition = str(result.get("postcondition") or "")

        if click_sent:
            # The pre-click target is never reusable after a tab interruption, even
            # if the command later fails verification.
            session.last_observation.clear()

        if postcondition == "url_equals_after_fresh_semantic_button_click":
            verified = bool(
                click_sent
                and exact_node
                and revalidated
                and result_target == target.target_id
                and url_before == current.url
                and result_expected == expected_url
                and root_url_after == expected_url
            )
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=str(command.get("completed_at") or utc_now()),
                success=verified,
                page_id=page_id,
                url_before=url_before,
                url_after=root_url_after,
                target_id=result_target or target.target_id,
                postcondition=postcondition if verified else "",
                data={
                    "provider": self.name,
                    "click_sent": click_sent,
                    "exact_node_continuity": exact_node,
                    "target_revalidated_before_dispatch": revalidated,
                    "expected_url": result_expected,
                    "authorization_attached_at": session.authorization_attached_at,
                    "causal_popup_attempted": True,
                    "causal_popup_observed": False,
                },
                error=None if verified else (
                    "extension click was sent but neither a verified same-tab result nor a verified causal child was proven"
                ),
            )

        safe_failure_data = {
            "provider": self.name,
            "click_sent": click_sent,
            "exact_node_continuity": exact_node,
            "target_revalidated_before_dispatch": revalidated,
            "expected_url_sha256": hashlib.sha256(expected_url.encode("utf-8")).hexdigest(),
            "expected_origin": self._origin(expected_url),
            "authorization_attached_at": session.authorization_attached_at,
            "task_action_id": task_action_id,
            "causal_popup_attempted": True,
        }
        if postcondition != self._CAUSAL_POSTCONDITION:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=str(command.get("completed_at") or utc_now()),
                success=False,
                page_id=page_id,
                url_before=url_before,
                url_after=root_url_after,
                target_id=result_target or target.target_id,
                data=safe_failure_data,
                error=(
                    str(result.get("verification_error") or "")[:512]
                    or "causal child evidence did not establish the required postcondition"
                ),
            )

        try:
            child_tab_id = self._positive_int(result.get("child_tab_id"), "child tab id")
            opener_tab_id = self._positive_int(result.get("opener_tab_id"), "opener tab id")
            causal_candidate_count = self._nonnegative_int(
                result.get("causal_candidate_count"), "causal candidate count"
            )
            unrelated_created_count = self._nonnegative_int(
                result.get("unrelated_created_count"), "unrelated created count"
            )
            window_open_event_count = self._nonnegative_int(
                result.get("window_open_event_count"), "window-open event count"
            )
            child_url = self._safe_url(result.get("child_url"))
            child_title = self._title(result.get("child_title"))
            child_title_sha = hashlib.sha256(child_title.encode("utf-8")).hexdigest()
            returned_task_action_id = self._bounded_text(
                result.get("task_action_id"), "returned task action id", 160
            )
        except ExtensionUserBrowserError as exc:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=str(command.get("completed_at") or utc_now()),
                success=False,
                page_id=page_id,
                url_before=url_before,
                url_after=root_url_after,
                target_id=result_target or target.target_id,
                data=safe_failure_data,
                error=str(exc),
            )

        verified = bool(
            click_sent
            and exact_node
            and revalidated
            and result_target == target.target_id
            and url_before == current.url
            and root_url_after == current.url
            and result_expected == expected_url
            and returned_task_action_id == task_action_id
            and child_tab_id != session.tab_id
            and opener_tab_id == session.tab_id
            and result.get("opener_matches_root") is True
            and result.get("fresh_child_identity") is True
            and result.get("page_window_open_matches_expected") is True
            and causal_candidate_count == 1
            and window_open_event_count == 1
            and child_url == expected_url
            and result.get("child_authority_task_scoped") is True
            and result.get("child_debugger_detached") is True
            and root_authorization_preserved
            and generation_unchanged
            and result.get("returned_to_exact_root_tab") is True
            and result.get("fresh_root_resense_after_return") is True
            and result.get("root_active_after_return") is True
            and result.get("root_window_focused_after_return") is True
        )
        evidence_data = {
            **safe_failure_data,
            "causal_popup_observed": True,
            "relationship": "causal_child",
            "root_tab_id": session.tab_id,
            "child_tab_id": child_tab_id,
            "opener_tab_id": opener_tab_id,
            "opener_matches_root": result.get("opener_matches_root") is True,
            "fresh_child_identity": result.get("fresh_child_identity") is True,
            "page_window_open_matches_expected": result.get("page_window_open_matches_expected") is True,
            "causal_candidate_count": causal_candidate_count,
            "unrelated_created_count": unrelated_created_count,
            "window_open_event_count": window_open_event_count,
            "expected_child_url_sha256": hashlib.sha256(expected_url.encode("utf-8")).hexdigest(),
            "child_url_sha256": hashlib.sha256(child_url.encode("utf-8")).hexdigest(),
            "child_url_matches_expected": child_url == expected_url,
            "child_origin": self._origin(child_url),
            "child_title_length": len(child_title),
            "child_title_sha256": child_title_sha,
            "child_authority_task_scoped": result.get("child_authority_task_scoped") is True,
            "child_debugger_detached": result.get("child_debugger_detached") is True,
            "root_authorization_preserved": root_authorization_preserved,
            "root_generation_unchanged": generation_unchanged,
            "returned_to_exact_root_tab": result.get("returned_to_exact_root_tab") is True,
            "fresh_root_resense_after_return": result.get("fresh_root_resense_after_return") is True,
            "root_active_after_return": result.get("root_active_after_return") is True,
            "root_window_focused_after_return": result.get("root_window_focused_after_return") is True,
        }
        if verified:
            self._causal_child_results[task_action_id] = {
                "task_action_id": task_action_id,
                "root_tab_id": session.tab_id,
                "child_tab_id": child_tab_id,
                "child_url": child_url,
                "child_title": child_title,
                "authorization_attached_at": session.authorization_attached_at,
                "observed_at": str(command.get("completed_at") or utc_now()),
            }
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=str(command.get("completed_at") or utc_now()),
            success=verified,
            page_id=page_id,
            url_before=url_before,
            url_after=root_url_after,
            target_id=result_target or target.target_id,
            postcondition=self._CAUSAL_POSTCONDITION if verified else "",
            data=evidence_data,
            error=None if verified else (
                "causal child evidence failed exact opener/action/root-return verification; refusing authority transfer"
            ),
        )

    @staticmethod
    def _origin(value: str) -> str:
        parsed = urlsplit(value)
        host = str(parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
        if port is None:
            port = 80 if parsed.scheme.lower() == "http" else 443
        return f"{parsed.scheme.lower()}://{host}:{port}"

    @staticmethod
    def _positive_int(value: Any, label: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ExtensionUserBrowserError(f"extension browser {label} is invalid") from exc
        if parsed <= 0:
            raise ExtensionUserBrowserError(f"extension browser {label} is invalid")
        return parsed
