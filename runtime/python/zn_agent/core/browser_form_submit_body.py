from __future__ import annotations

"""Bounded same-session semantic form submission owned by the resident Body."""

import hashlib
from dataclasses import asdict
from typing import Any

from .body import BodyAction, BodyActionResult
from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from .browser_text_work_body import BrowserTextWorkBody
from .models import utc_now


class BrowserFormSubmitBody(BrowserTextWorkBody):
    """Fill one exact textbox, click one exact button, and prove the final URL.

    This is deliberately a single guarded Body movement. The textbox and button
    are both rebound from fresh semantic observations in one ephemeral managed
    browser session, so the typed state is not lost to a second navigation.
    Plaintext input is redacted from durable Body history; only bounded digest and
    length evidence survive outside the user-authored Work event.
    """

    _BROWSER_FILL_AND_SUBMIT = "browser_fill_named_text_and_click_named_button_to_url"

    @classmethod
    def _requires_guard(cls, kind: str, args: dict[str, Any]) -> bool:
        if kind == cls._BROWSER_FILL_AND_SUBMIT:
            return True
        return super()._requires_guard(kind, args)

    def _record(self, action: BodyAction, result: BodyActionResult) -> None:
        if action.kind == self._BROWSER_FILL_AND_SUBMIT and "text" in action.args:
            safe_args = dict(action.args)
            raw_text = safe_args.pop("text")
            redacted_aliases: list[str] = []
            for alias in ("content", "input", "data", "value"):
                if alias in safe_args and safe_args.get(alias) == raw_text:
                    safe_args.pop(alias)
                    redacted_aliases.append(alias)
            safe_args["text_redacted"] = True
            safe_args["text_chars"] = len(str(raw_text))
            if redacted_aliases:
                safe_args["text_aliases_redacted"] = redacted_aliases
            action = BodyAction(
                action_id=action.action_id,
                kind=action.kind,
                args=safe_args,
                event_id=action.event_id,
                created_at=action.created_at,
            )
        super()._record(action, result)

    def _dispatch(self, action: BodyAction, started: str) -> BodyActionResult:
        if action.kind == self._BROWSER_FILL_AND_SUBMIT:
            return self._browser_fill_and_submit(action, started)
        return super()._dispatch(action, started)

    @staticmethod
    def _validated_target_name(value: Any, *, field: str) -> str:
        target_name = str(value or "").strip()
        if not target_name:
            raise ValueError(f"{field} must not be empty")
        if len(target_name) > 160:
            raise ValueError(f"{field} is too long")
        if any(ord(char) < 32 or ord(char) == 127 for char in target_name):
            raise ValueError(f"{field} contains control characters")
        return target_name

    def _browser_fill_and_submit(
        self,
        action: BodyAction,
        started: str,
    ) -> BodyActionResult:
        browser = self._browser()
        url = str(action.args.get("url") or "").strip()
        expected_url = str(action.args.get("expected_url") or "").strip()
        textbox_name = self._validated_target_name(
            action.args.get("textbox_name"), field="textbox_name"
        )
        button_name = self._validated_target_name(
            action.args.get("button_name"), field="button_name"
        )
        text, utf16_units = self._validated_text(action.args.get("text"))
        requested_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        requested_length = len(text)
        if not url or not expected_url:
            raise ValueError(
                "browser_fill_named_text_and_click_named_button_to_url requires url and expected_url"
            )
        if not self._same_origin(url, expected_url):
            raise ValueError(
                "browser_fill_named_text_and_click_named_button_to_url currently requires same-origin expected_url"
            )

        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_page_interaction=True,
            allow_text_entry=True,
            allow_private_network=bool(action.args.get("allow_private_network", False)),
            allowed_origins=(url,),
        )
        session = None
        closed = False
        try:
            session = browser.open_session(permission=permission, headless=True)
            initial = browser.observe(session.session_id)
            navigate = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.NAVIGATE,
                page_id=initial.page_id,
                args={"url": url},
                expected={"url_equals": url},
            )
            navigate_authority = BrowserActionAuthority.from_observation(
                navigate, initial, permission
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

            textbox_observation = browser.observe_target(
                session.session_id,
                BrowserTargetQuery(
                    kind=BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME,
                    value=textbox_name,
                ),
                page_id=navigation_evidence.page_id,
            )
            if (
                textbox_observation.target is None
                or textbox_observation.target.role != "textbox"
            ):
                raise ValueError(
                    "browser_fill_named_text_and_click_named_button_to_url requires a visible writable textbox target"
                )

            type_action = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.TYPE_TEXT,
                page_id=textbox_observation.page_id,
                target=textbox_observation.target,
                args={"text": text},
            )
            type_authority = BrowserActionAuthority.from_observation(
                type_action, textbox_observation, permission
            )
            text_evidence = browser.act(type_action, type_authority)
            text = ""
            if not text_evidence.success:
                browser.close_session(session.session_id)
                closed = True
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=False,
                    data={
                        "textbox_name": textbox_name,
                        "text_evidence": asdict(text_evidence),
                        "closed": True,
                    },
                    error=text_evidence.error or "managed browser text entry failed",
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )

            text_data = dict(text_evidence.data or {})
            expected_digest = str(text_data.get("expected_text_sha256") or "")
            expected_length = int(text_data.get("expected_text_length") or 0)
            if (
                not bool(text_data.get("exact_node_continuity"))
                or not bool(text_data.get("input_sent"))
                or text_evidence.postcondition
                != "same_exact_target_text_equals_requested"
                or expected_length != requested_length
                or expected_digest != requested_digest
                or int(text_data.get("expected_utf16_units") or -1) != utf16_units
                or int(text_data.get("text_length_after") or -1) != requested_length
                or str(text_data.get("text_sha256_after") or "") != requested_digest
            ):
                browser.close_session(session.session_id)
                closed = True
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=False,
                    data={
                        "textbox_name": textbox_name,
                        "text_evidence": asdict(text_evidence),
                        "closed": True,
                    },
                    error="managed browser text postcondition was not independently proven",
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )

            button_observation = browser.observe_target(
                session.session_id,
                BrowserTargetQuery(
                    kind=BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME,
                    value=button_name,
                ),
                page_id=text_evidence.page_id or navigation_evidence.page_id,
            )
            if (
                button_observation.target is None
                or button_observation.target.role != "button"
            ):
                raise ValueError(
                    "browser_fill_named_text_and_click_named_button_to_url requires a visible button target"
                )

            click = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.CLICK,
                page_id=button_observation.page_id,
                target=button_observation.target,
                expected={"url_equals": expected_url},
            )
            click_authority = BrowserActionAuthority.from_observation(
                click, button_observation, permission
            )
            submit_evidence = browser.act(click, click_authority)
            if not submit_evidence.success:
                browser.close_session(session.session_id)
                closed = True
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=False,
                    data={
                        "textbox_name": textbox_name,
                        "button_name": button_name,
                        "expected_url": expected_url,
                        "text_evidence": asdict(text_evidence),
                        "submit_evidence": asdict(submit_evidence),
                        "closed": True,
                    },
                    error=submit_evidence.error or "managed browser form submission failed",
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )

            verified = browser.observe(
                session.session_id,
                page_id=submit_evidence.page_id,
            )
            if verified.url != expected_url:
                browser.close_session(session.session_id)
                closed = True
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=False,
                    data={
                        "textbox_name": textbox_name,
                        "button_name": button_name,
                        "expected_url": expected_url,
                        "observed_url": verified.url,
                        "text_evidence": asdict(text_evidence),
                        "submit_evidence": asdict(submit_evidence),
                        "closed": True,
                    },
                    error=(
                        "managed browser form submission postcondition did not match "
                        "the explicitly requested URL"
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
                    "url": navigation_evidence.url_after,
                    "expected_url": expected_url,
                    "observed_url": verified.url,
                    "page_id": verified.page_id,
                    "textbox_target_id": textbox_observation.target.target_id,
                    "textbox_name": textbox_observation.target.name,
                    "button_target_id": button_observation.target.target_id,
                    "button_name": button_observation.target.name,
                    "expected_text_length": requested_length,
                    "expected_text_sha256": requested_digest,
                    "expected_utf16_units": utf16_units,
                    "text_length_after": int(text_data.get("text_length_after") or 0),
                    "text_sha256_after": str(text_data.get("text_sha256_after") or ""),
                    "text_postcondition": text_evidence.postcondition,
                    "text_exact_node_continuity": bool(
                        text_data.get("exact_node_continuity")
                    ),
                    "submit_postcondition": submit_evidence.postcondition,
                    "button_revalidated_before_dispatch": bool(
                        submit_evidence.data.get("target_revalidated_before_dispatch")
                    ),
                    "provider": str(
                        submit_evidence.data.get("provider")
                        or text_data.get("provider")
                        or navigation_evidence.data.get("provider")
                        or session.provider
                    ),
                    "text_evidence": asdict(text_evidence),
                    "submit_evidence": asdict(submit_evidence),
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
