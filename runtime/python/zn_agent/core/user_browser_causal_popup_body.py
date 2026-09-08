from __future__ import annotations

"""Install one bounded causal USER child-tab movement on the existing Body."""

from dataclasses import asdict
from typing import Any

from .body import BodyAction, BodyActionResult
from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
    BrowserPlane,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from .models import utc_now


_BROWSER_CLICK_NAMED_BUTTON = "browser_click_named_button_to_url"
_CAUSAL_POSTCONDITION = "causal_child_verified_and_returned_to_exact_root"
_INSTALL_MARKER = "_zn_user_browser_causal_popup_dispatch_installed"


def install_user_browser_causal_popup_body(body) -> None:
    """Decorate the one existing Body dispatch seam, preserving Body identity/history."""
    if getattr(body, _INSTALL_MARKER, False):
        return
    original_dispatch = body._dispatch

    def dispatch(action: BodyAction, started: str) -> BodyActionResult:
        if (
            action.kind == _BROWSER_CLICK_NAMED_BUTTON
            and action.args.get("causal_popup_allowed") is True
        ):
            return _causal_click_dispatch(body, action, started)
        return original_dispatch(action, started)

    body._dispatch = dispatch
    setattr(body, _INSTALL_MARKER, True)


def _bounded_label(value: Any, *, field: str, limit: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > limit:
        raise ValueError(f"{field} is invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError(f"{field} contains control characters")
    return text


def _causal_click_dispatch(body, action: BodyAction, started: str) -> BodyActionResult:
    browser = body._browser()
    if getattr(browser, "plane", None) is not BrowserPlane.USER:
        raise ValueError(
            "causal child-tab authority is only defined for the authorized USER browser"
        )

    url = str(action.args.get("url") or "").strip()
    expected_url = str(action.args.get("expected_url") or "").strip()
    target_name = _bounded_label(
        action.args.get("target_name"), field="target_name", limit=160
    )
    if not url or not expected_url:
        raise ValueError("causal browser button click requires url and expected_url")
    if not body._same_origin(url, expected_url):
        raise ValueError("causal child URL must remain inside the authorized root origin")

    permission = BrowserPermissionContext(
        allow_navigation=False,
        allow_page_interaction=True,
        allow_private_network=bool(action.args.get("allow_private_network", False)),
        allowed_origins=(url,),
    )
    session = None
    closed = False
    try:
        session = body._open_session_for_body_action(
            browser,
            action,
            permission,
            user_plane=True,
            headless=False,
        )
        initial = browser.observe(session.session_id)
        if initial.url != url:
            browser.close_session(session.session_id)
            closed = True
            return BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=False,
                data={
                    "expected_start_url": url,
                    "observed_start_url": initial.url,
                    "browser_plane": BrowserPlane.USER.value,
                    "click_sent": False,
                    "closed": True,
                },
                error=(
                    "authorized root tab changed before causal popup click; "
                    "refusing navigation or authority transfer"
                ),
                event_id=action.event_id,
                started_at=started,
                completed_at=utc_now(),
            )

        observed = browser.observe_target(
            session.session_id,
            BrowserTargetQuery(
                kind=BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME,
                value=target_name,
            ),
            page_id=initial.page_id,
        )
        if observed.target is None or observed.target.role != "button":
            raise ValueError("causal browser click requires one visible exact button target")

        click = BrowserAction.create(
            session_id=session.session_id,
            kind=BrowserActionKind.CLICK,
            page_id=observed.page_id,
            target=observed.target,
            expected={
                "url_equals": expected_url,
                "causal_popup_allowed": True,
                "task_action_id": action.action_id,
            },
        )
        authority = BrowserActionAuthority.from_observation(click, observed, permission)
        evidence = browser.act(click, authority)
        if not evidence.success:
            browser.close_session(session.session_id)
            closed = True
            return BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=False,
                data={
                    "target_id": observed.target.target_id,
                    "browser_evidence": asdict(evidence),
                    "closed": True,
                },
                error=evidence.error or "causal browser button click failed",
                event_id=action.event_id,
                started_at=started,
                completed_at=utc_now(),
            )

        if evidence.postcondition == "url_equals_after_fresh_semantic_button_click":
            verified = browser.observe(session.session_id, page_id=evidence.page_id)
            if verified.url != expected_url:
                browser.close_session(session.session_id)
                closed = True
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=False,
                    data={
                        "expected_url": expected_url,
                        "observed_url": verified.url,
                        "browser_evidence": asdict(evidence),
                        "closed": True,
                    },
                    error=(
                        "same-tab fallback did not survive an independent fresh root observation"
                    ),
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )
            browser.close_session(session.session_id)
            closed = True
            return BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=True,
                output=verified.url,
                data={
                    "url": url,
                    "expected_url": expected_url,
                    "observed_url": verified.url,
                    "page_id": verified.page_id,
                    "browser_plane": BrowserPlane.USER.value,
                    "navigation_performed": False,
                    "target_id": evidence.target_id,
                    "target_role": observed.target.role,
                    "target_name": observed.target.name,
                    "provider": str(evidence.data.get("provider") or session.provider),
                    "postcondition": evidence.postcondition,
                    "target_revalidated_before_dispatch": bool(
                        evidence.data.get("target_revalidated_before_dispatch")
                    ),
                    "authorization_attached_at": str(
                        evidence.data.get("authorization_attached_at") or ""
                    ),
                    "browser_evidence": asdict(evidence),
                    "closed": True,
                },
                event_id=action.event_id,
                started_at=started,
                completed_at=utc_now(),
            )

        if evidence.postcondition != _CAUSAL_POSTCONDITION:
            raise ValueError("causal child click returned an unsupported completion contract")

        fresh_root = browser.observe(session.session_id, page_id=evidence.page_id)
        data = dict(evidence.data or {})
        root_ok = bool(
            fresh_root.page_id == initial.page_id
            and fresh_root.url == url
            and data.get("root_authorization_preserved") is True
            and data.get("root_generation_unchanged") is True
            and data.get("returned_to_exact_root_tab") is True
            and data.get("fresh_root_resense_after_return") is True
            and data.get("child_authority_task_scoped") is True
            and data.get("child_debugger_detached") is True
            and data.get("child_url_matches_expected") is True
        )
        if not root_ok:
            browser.close_session(session.session_id)
            closed = True
            return BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=False,
                data={
                    "expected_root_url": url,
                    "observed_root_url": fresh_root.url,
                    "browser_evidence": asdict(evidence),
                    "closed": True,
                },
                error="fresh root re-sense did not preserve the exact Work authorization context",
                event_id=action.event_id,
                started_at=started,
                completed_at=utc_now(),
            )

        browser.close_session(session.session_id)
        closed = True
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            output="causal child verified and exact root restored",
            data={
                "url": url,
                "child_url_matches_expected": True,
                "child_origin": data.get("child_origin"),
                "expected_child_url_sha256": data.get("expected_child_url_sha256"),
                "child_url_sha256": data.get("child_url_sha256"),
                "root_observed_url": fresh_root.url,
                "page_id": fresh_root.page_id,
                "browser_plane": BrowserPlane.USER.value,
                "navigation_performed": False,
                "target_id": evidence.target_id,
                "target_role": observed.target.role,
                "target_name": observed.target.name,
                "provider": str(data.get("provider") or session.provider),
                "postcondition": _CAUSAL_POSTCONDITION,
                "target_revalidated_before_dispatch": bool(
                    data.get("target_revalidated_before_dispatch")
                ),
                "authorization_attached_at": str(
                    data.get("authorization_attached_at") or ""
                ),
                "causal_action_id": action.action_id,
                "relationship": "causal_child",
                "root_tab_id": data.get("root_tab_id"),
                "child_tab_id": data.get("child_tab_id"),
                "opener_matches_root": data.get("opener_matches_root") is True,
                "fresh_child_identity": data.get("fresh_child_identity") is True,
                "page_window_open_matches_expected": (
                    data.get("page_window_open_matches_expected") is True
                ),
                "causal_candidate_count": data.get("causal_candidate_count"),
                "unrelated_created_count": data.get("unrelated_created_count"),
                "child_authority_task_scoped": data.get("child_authority_task_scoped") is True,
                "child_debugger_detached": data.get("child_debugger_detached") is True,
                "root_authorization_preserved": data.get("root_authorization_preserved") is True,
                "root_generation_unchanged": data.get("root_generation_unchanged") is True,
                "returned_to_exact_root_tab": data.get("returned_to_exact_root_tab") is True,
                "fresh_root_resense_after_return": True,
                "root_active_after_return": data.get("root_active_after_return") is True,
                "root_window_focused_after_return": (
                    data.get("root_window_focused_after_return") is True
                ),
                "child_title_length": data.get("child_title_length"),
                "child_title_sha256": data.get("child_title_sha256"),
                "browser_evidence": asdict(evidence),
                "closed": True,
            },
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )
    except BaseException:
        if session is not None and not closed:
            try:
                browser.close_session(session.session_id)
            except Exception:
                pass
        raise
