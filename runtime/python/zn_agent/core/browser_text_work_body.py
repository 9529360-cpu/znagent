from __future__ import annotations

"""Privacy-bounded browser text entry owned by the resident Body."""

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
from .browser_work_body import BrowserSideEffectAwareBody
from .models import utc_now


class BrowserTextWorkBody(BrowserSideEffectAwareBody):
    """Type explicit non-secret text into one exact semantic textbox.

    Managed-browser work may navigate to the user-supplied URL first. An authorized
    USER-plane browser is different: ZN must preserve the user's existing session
    and current page, so it requires the freshly observed current URL to already
    equal the requested URL and never navigates/reloads on the user's behalf in
    this text-entry slice.

    The browser provider enforces an empty, writable, non-password native text
    control, exact-node continuity, and a length+digest postcondition. This layer
    supplies resident ownership, durable side-effect guarding, session lifecycle,
    and a durable-action redaction boundary for the plaintext input.
    """

    _BROWSER_TYPE_NAMED_TEXT = "browser_type_named_text"
    _MAX_TEXT_UTF16_UNITS = 512

    @classmethod
    def _requires_guard(cls, kind: str, args: dict[str, Any]) -> bool:
        if kind == cls._BROWSER_TYPE_NAMED_TEXT:
            return True
        return super()._requires_guard(kind, args)

    def _record(self, action: BodyAction, result: BodyActionResult) -> None:
        if action.kind == self._BROWSER_TYPE_NAMED_TEXT and "text" in action.args:
            safe_args = dict(action.args)
            raw_text = safe_args.pop("text")
            safe_args["text_redacted"] = True
            safe_args["text_chars"] = len(str(raw_text))
            action = BodyAction(
                action_id=action.action_id,
                kind=action.kind,
                args=safe_args,
                event_id=action.event_id,
                created_at=action.created_at,
            )
        super()._record(action, result)

    def _dispatch(self, action: BodyAction, started: str) -> BodyActionResult:
        if action.kind == self._BROWSER_TYPE_NAMED_TEXT:
            return self._browser_type_named_text(action, started)
        return super()._dispatch(action, started)

    @classmethod
    def _validated_text(cls, value: Any) -> tuple[str, int]:
        if not isinstance(value, str) or not value:
            raise ValueError("browser_type_named_text requires non-empty string text")
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
            raise ValueError("browser_type_named_text text contains control characters")
        try:
            units = len(value.encode("utf-16-le")) // 2
        except UnicodeEncodeError as exc:
            raise ValueError(
                "browser_type_named_text contains an invalid Unicode scalar sequence"
            ) from exc
        if units <= 0 or units > cls._MAX_TEXT_UTF16_UNITS:
            raise ValueError(
                f"browser_type_named_text is limited to {cls._MAX_TEXT_UTF16_UNITS} UTF-16 code units"
            )
        return value, units

    def _browser_type_named_text(
        self,
        action: BodyAction,
        started: str,
    ) -> BodyActionResult:
        browser = self._browser()
        url = str(action.args.get("url") or "").strip()
        target_name = str(action.args.get("target_name") or "").strip()
        text, utf16_units = self._validated_text(action.args.get("text"))
        if not url:
            raise ValueError("browser_type_named_text requires url")
        if not target_name:
            raise ValueError("browser_type_named_text requires target_name")
        if len(target_name) > 160:
            raise ValueError("browser_type_named_text target_name is too long")
        if any(ord(char) < 32 or ord(char) == 127 for char in target_name):
            raise ValueError("browser_type_named_text target_name contains control characters")

        user_plane = getattr(browser, "plane", None) is BrowserPlane.USER
        permission = BrowserPermissionContext(
            allow_navigation=not user_plane,
            allow_page_interaction=True,
            allow_text_entry=True,
            allow_private_network=bool(action.args.get("allow_private_network", False)),
            allowed_origins=(url,),
        )
        session = None
        closed = False
        try:
            session = browser.open_session(permission=permission, headless=not user_plane)
            initial = browser.observe(session.session_id)
            current_page_id = initial.page_id
            current_url = initial.url
            navigation_provider = session.provider

            if session.plane is BrowserPlane.USER:
                if initial.url != url:
                    browser.close_session(session.session_id)
                    closed = True
                    return BodyActionResult(
                        action_id=action.action_id,
                        kind=action.kind,
                        success=False,
                        data={
                            "requested_url": url,
                            "current_url": initial.url,
                            "browser_plane": BrowserPlane.USER.value,
                            "input_sent": False,
                            "closed": True,
                        },
                        error=(
                            "authorized user browser is not currently on the requested URL; "
                            "ZN did not navigate or send input"
                        ),
                        event_id=action.event_id,
                        started_at=started,
                        completed_at=utc_now(),
                    )
            else:
                navigate = BrowserAction.create(
                    session_id=session.session_id,
                    kind=BrowserActionKind.NAVIGATE,
                    page_id=initial.page_id,
                    args={"url": url},
                    expected={"url_equals": url},
                )
                navigate_authority = BrowserActionAuthority.from_observation(
                    navigate,
                    initial,
                    permission,
                )
                navigation_evidence = browser.act(navigate, navigate_authority)
                if not navigation_evidence.success:
                    browser.close_session(session.session_id)
                    closed = True
                    return BodyActionResult(
                        action_id=action.action_id,
                        kind=action.kind,
                        success=False,
                        data={
                            "browser_evidence": asdict(navigation_evidence),
                            "closed": True,
                        },
                        error=navigation_evidence.error or "managed browser navigation failed",
                        event_id=action.event_id,
                        started_at=started,
                        completed_at=utc_now(),
                    )
                current_page_id = navigation_evidence.page_id
                current_url = navigation_evidence.url_after
                navigation_provider = str(
                    navigation_evidence.data.get("provider") or session.provider
                )

            observed = browser.observe_target(
                session.session_id,
                BrowserTargetQuery(
                    kind=BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME,
                    value=target_name,
                ),
                page_id=current_page_id,
            )
            if observed.target is None or observed.target.role != "textbox":
                raise ValueError(
                    "browser_type_named_text requires a visible writable textbox target"
                )

            mutation = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.TYPE_TEXT,
                page_id=observed.page_id,
                target=observed.target,
                args={"text": text},
            )
            mutation_authority = BrowserActionAuthority.from_observation(
                mutation,
                observed,
                permission,
            )
            mutation_evidence = browser.act(mutation, mutation_authority)
            text = ""
            if not mutation_evidence.success:
                browser.close_session(session.session_id)
                closed = True
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=False,
                    data={
                        "url": current_url,
                        "target_id": observed.target.target_id,
                        "target_role": observed.target.role,
                        "target_name": observed.target.name,
                        "browser_evidence": asdict(mutation_evidence),
                        "closed": True,
                    },
                    error=mutation_evidence.error or "browser text entry failed",
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )

            browser.close_session(session.session_id)
            closed = True
            evidence_data = dict(mutation_evidence.data or {})
            return BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=True,
                output=f'typed {int(evidence_data.get("expected_text_length") or 0)} characters into textbox "{target_name}"',
                data={
                    "url": mutation_evidence.url_after or current_url,
                    "page_id": mutation_evidence.page_id,
                    "target_id": mutation_evidence.target_id,
                    "target_role": observed.target.role,
                    "target_name": observed.target.name,
                    "selector_hint": observed.target.selector_hint,
                    "provider": str(
                        evidence_data.get("provider")
                        or navigation_provider
                        or session.provider
                    ),
                    "browser_plane": session.plane.value,
                    "postcondition": mutation_evidence.postcondition,
                    "exact_node_continuity": bool(
                        evidence_data.get("exact_node_continuity")
                    ),
                    "input_sent": bool(evidence_data.get("input_sent")),
                    "expected_text_length": int(
                        evidence_data.get("expected_text_length") or 0
                    ),
                    "expected_text_sha256": str(
                        evidence_data.get("expected_text_sha256") or ""
                    ),
                    "expected_utf16_units": int(
                        evidence_data.get("expected_utf16_units") or utf16_units
                    ),
                    "text_length_after": int(
                        evidence_data.get("text_length_after") or 0
                    ),
                    "text_sha256_after": str(
                        evidence_data.get("text_sha256_after") or ""
                    ),
                    "browser_evidence": asdict(mutation_evidence),
                    "closed": True,
                },
                event_id=action.event_id,
                started_at=started,
                completed_at=utc_now(),
            )
        except BaseException:
            text = ""
            if session is not None and not closed:
                try:
                    browser.close_session(session.session_id)
                except Exception:
                    pass
            raise
