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
    BrowserPlane,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from .browser_text_work_body import BrowserTextWorkBody
from .models import utc_now


class BrowserFormSubmitBody(BrowserTextWorkBody):
    """Fill one exact textbox and submit through one bounded semantic action.

    The established path clicks one exact button. A second deliberately narrow
    MANAGED-browser path may instead press exactly ``Enter`` on the same exact
    textbox when the user supplied that interaction explicitly. Both paths keep
    the typed state and submission inside one ephemeral browser session and
    require an explicit same-origin final URL. Plaintext input is redacted from
    durable Body history; only bounded digest and length evidence survive outside
    the user-authored Work event.
    """

    _BROWSER_FILL_AND_SUBMIT = "browser_fill_named_text_and_click_named_button_to_url"
    _BROWSER_FILL_AND_PRESS_ENTER = "browser_fill_named_text_and_press_enter_to_url"

    @classmethod
    def _requires_guard(cls, kind: str, args: dict[str, Any]) -> bool:
        if kind in {cls._BROWSER_FILL_AND_SUBMIT, cls._BROWSER_FILL_AND_PRESS_ENTER}:
            return True
        return super()._requires_guard(kind, args)

    def _record(self, action: BodyAction, result: BodyActionResult) -> None:
        if (
            action.kind in {self._BROWSER_FILL_AND_SUBMIT, self._BROWSER_FILL_AND_PRESS_ENTER}
            and "text" in action.args
        ):
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
        if action.kind == self._BROWSER_FILL_AND_PRESS_ENTER:
            return self._browser_fill_and_press_enter(action, started)
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
        navigation_evidence = None
        try:
            session = self._open_session_for_body_action(
                browser,
                action,
                permission,
                user_plane=user_plane,
                headless=not user_plane,
            )
            initial = browser.observe(session.session_id)
            if user_plane:
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
                            "closed": True,
                        },
                        error=(
                            "authorized user browser current page does not match the explicitly "
                            "requested start URL; refusing navigation or mutation"
                        ),
                        event_id=action.event_id,
                        started_at=started,
                        completed_at=utc_now(),
                    )
                start_observation = initial
                start_url = initial.url
            else:
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
                start_observation = browser.observe(
                    session.session_id,
                    page_id=navigation_evidence.page_id,
                )
                start_url = navigation_evidence.url_after

            textbox_observation = browser.observe_target(
                session.session_id,
                BrowserTargetQuery(
                    kind=BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME,
                    value=textbox_name,
                ),
                page_id=start_observation.page_id,
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
                    error=text_evidence.error or "browser text entry failed",
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
                    error="browser text postcondition was not independently proven",
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
                page_id=text_evidence.page_id or start_observation.page_id,
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
                    error=submit_evidence.error or "browser form submission failed",
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
                        "browser form submission postcondition did not match the explicitly "
                        "requested URL"
                    ),
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )

            browser.close_session(session.session_id)
            closed = True
            navigation_provider = (
                str(navigation_evidence.data.get("provider") or "")
                if navigation_evidence is not None
                else ""
            )
            return BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=True,
                output=verified.url,
                data={
                    "url": start_url,
                    "expected_url": expected_url,
                    "observed_url": verified.url,
                    "page_id": verified.page_id,
                    "browser_plane": session.plane.value,
                    "navigation_performed": navigation_evidence is not None,
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
                    "authorization_attached_at": str(
                        submit_evidence.data.get("authorization_attached_at")
                        or text_data.get("authorization_attached_at")
                        or ""
                    ),
                    "provider": str(
                        submit_evidence.data.get("provider")
                        or text_data.get("provider")
                        or navigation_provider
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

    def _browser_fill_and_press_enter(
        self,
        action: BodyAction,
        started: str,
    ) -> BodyActionResult:
        browser = self._browser()
        if getattr(browser, "plane", None) is BrowserPlane.USER:
            raise ValueError(
                "browser_fill_named_text_and_press_enter_to_url is MANAGED-browser only"
            )

        url = str(action.args.get("url") or "").strip()
        expected_url = str(action.args.get("expected_url") or "").strip()
        textbox_name = self._validated_target_name(
            action.args.get("textbox_name"), field="textbox_name"
        )
        text, utf16_units = self._validated_text(action.args.get("text"))
        requested_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        requested_length = len(text)
        if not url or not expected_url:
            raise ValueError(
                "browser_fill_named_text_and_press_enter_to_url requires url and expected_url"
            )
        if not self._same_origin(url, expected_url):
            raise ValueError(
                "browser_fill_named_text_and_press_enter_to_url currently requires same-origin expected_url"
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
        text_for_cleanup = text
        try:
            session = self._open_session_for_body_action(
                browser,
                action,
                permission,
                user_plane=False,
                headless=True,
            )
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

            start_observation = browser.observe(
                session.session_id,
                page_id=navigation_evidence.page_id,
            )
            textbox_observation = browser.observe_target(
                session.session_id,
                BrowserTargetQuery(
                    kind=BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME,
                    value=textbox_name,
                ),
                page_id=start_observation.page_id,
            )
            if (
                textbox_observation.target is None
                or textbox_observation.target.role != "textbox"
            ):
                raise ValueError(
                    "browser_fill_named_text_and_press_enter_to_url requires a visible writable textbox target"
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
                    error=text_evidence.error or "browser text entry failed",
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )

            text_data = dict(text_evidence.data or {})
            if (
                not bool(text_data.get("exact_node_continuity"))
                or not bool(text_data.get("input_sent"))
                or text_evidence.postcondition
                != "same_exact_target_text_equals_requested"
                or int(text_data.get("expected_text_length") or -1) != requested_length
                or str(text_data.get("expected_text_sha256") or "") != requested_digest
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
                    error="browser text postcondition was not independently proven",
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )

            press_observation = browser.observe_target(
                session.session_id,
                BrowserTargetQuery(
                    kind=BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME,
                    value=textbox_name,
                ),
                page_id=text_evidence.page_id or start_observation.page_id,
            )
            if (
                press_observation.target is None
                or press_observation.target.role != "textbox"
            ):
                raise ValueError(
                    "browser Enter submission lost the exact textbox before dispatch"
                )

            press = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.PRESS,
                page_id=press_observation.page_id,
                target=press_observation.target,
                args={"key": "Enter"},
                expected={
                    "url_equals": expected_url,
                    "text_length": requested_length,
                    "text_sha256": requested_digest,
                },
            )
            press_authority = BrowserActionAuthority.from_observation(
                press, press_observation, permission
            )
            submit_evidence = browser.act(press, press_authority)
            if not submit_evidence.success:
                browser.close_session(session.session_id)
                closed = True
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=False,
                    data={
                        "textbox_name": textbox_name,
                        "expected_url": expected_url,
                        "text_evidence": asdict(text_evidence),
                        "submit_evidence": asdict(submit_evidence),
                        "closed": True,
                    },
                    error=submit_evidence.error or "browser Enter form submission failed",
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
                        "expected_url": expected_url,
                        "observed_url": verified.url,
                        "text_evidence": asdict(text_evidence),
                        "submit_evidence": asdict(submit_evidence),
                        "closed": True,
                    },
                    error=(
                        "browser Enter form submission postcondition did not match the "
                        "explicitly requested URL"
                    ),
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )

            browser.close_session(session.session_id)
            closed = True
            submit_data = dict(submit_evidence.data or {})
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
                    "browser_plane": session.plane.value,
                    "navigation_performed": True,
                    "textbox_target_id": press_observation.target.target_id,
                    "textbox_name": press_observation.target.name,
                    "submit_key": "Enter",
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
                    "textbox_revalidated_before_enter": bool(
                        submit_data.get("target_revalidated_before_dispatch")
                    ),
                    "text_revalidated_before_enter": bool(
                        submit_data.get("text_revalidated_before_dispatch")
                    ),
                    "enter_dispatched": bool(submit_data.get("press_sent")),
                    "provider": str(
                        submit_data.get("provider")
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
            text_for_cleanup = ""
            if session is not None and not closed:
                try:
                    browser.close_session(session.session_id)
                except Exception:
                    pass
            raise
