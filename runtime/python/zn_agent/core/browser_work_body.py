from __future__ import annotations

"""Work-facing browser Body movements with durable replay boundaries."""

from dataclasses import asdict
from typing import Any
from urllib.parse import urlsplit

from .atomic_overwrite_namespace_recovery_resident import AtomicOverwriteNamespaceAwareBody
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


class BrowserSideEffectAwareBody(AtomicOverwriteNamespaceAwareBody):
    """Extend ZN's mature Body with bounded managed-browser product paths.

    The base deliberately remains the current final overwrite-aware Body rather
    than an earlier SideEffectAwareBody layer. That preserves atomic overwrite,
    namespace recovery, keyboard/pointer, and generic side-effect protocols while
    adding browser movements behind the same durable outside-world replay guard.
    """

    _BROWSER_NAVIGATE = "browser_navigate"
    _BROWSER_SET_CHECKBOX = "browser_set_checkbox"
    _BROWSER_SET_NAMED_CHECKBOX = "browser_set_named_checkbox"
    _BROWSER_CLICK_NAMED_BUTTON_TO_URL = "browser_click_named_button_to_url"

    @classmethod
    def _requires_guard(cls, kind: str, args: dict[str, Any]) -> bool:
        if kind in {
            cls._BROWSER_NAVIGATE,
            cls._BROWSER_SET_CHECKBOX,
            cls._BROWSER_SET_NAMED_CHECKBOX,
            cls._BROWSER_CLICK_NAMED_BUTTON_TO_URL,
        }:
            return True
        return super()._requires_guard(kind, args)

    def _dispatch(self, action: BodyAction, started: str) -> BodyActionResult:
        if action.kind == self._BROWSER_NAVIGATE:
            return self._browser_navigate(action, started)
        if action.kind == self._BROWSER_SET_CHECKBOX:
            return self._browser_set_checkbox(action, started)
        if action.kind == self._BROWSER_SET_NAMED_CHECKBOX:
            return self._browser_set_named_checkbox(action, started)
        if action.kind == self._BROWSER_CLICK_NAMED_BUTTON_TO_URL:
            return self._browser_click_named_button_to_url(action, started)
        if action.kind == "browser_observe":
            return self._browser_observe(action, started)
        if action.kind == "browser_close":
            return self._browser_close(action, started)
        return super()._dispatch(action, started)

    @staticmethod
    def _open_session_for_body_action(
        browser,
        action: BodyAction,
        permission: BrowserPermissionContext,
        *,
        user_plane: bool,
        headless: bool,
    ):
        if user_plane:
            expected_tab_id = action.args.get("authorized_tab_id")
            expected_attached_at = str(
                action.args.get("authorization_attached_at") or ""
            ).strip()
            if expected_tab_id is not None or expected_attached_at:
                if expected_tab_id is None or not expected_attached_at:
                    raise ValueError(
                        "USER browser task context requires both authorized_tab_id and authorization_attached_at"
                    )
                opener = getattr(browser, "open_session_for_authorization", None)
                if not callable(opener):
                    raise ValueError(
                        "current USER browser adapter cannot bind the Resident task authorization context"
                    )
                return opener(
                    permission=permission,
                    headless=headless,
                    expected_tab_id=int(expected_tab_id),
                    expected_attached_at=expected_attached_at,
                )
        return browser.open_session(permission=permission, headless=headless)

    @staticmethod
    def _open_session_for_target_query(
        browser,
        permission: BrowserPermissionContext,
        query_kind: BrowserTargetQueryKind,
        *,
        headless: bool,
    ):
        opener = getattr(browser, "open_session_for_requirements", None)
        if callable(opener):
            return opener(
                permission=permission,
                headless=headless,
                required_target_queries=(query_kind,),
            )
        return browser.open_session(permission=permission, headless=headless)

    def _browser_navigate(self, action: BodyAction, started: str) -> BodyActionResult:
        browser = self._browser()
        url = str(action.args.get("url") or "").strip()
        if not url:
            raise ValueError("browser_navigate requires url")

        expected_url = str(action.args.get("expected_url") or url).strip()
        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_private_network=bool(action.args.get("allow_private_network", False)),
            allowed_origins=(url,),
        )
        session = None
        try:
            session = browser.open_session(permission=permission, headless=True)
            observation = browser.observe(session.session_id)
            browser_action = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.NAVIGATE,
                page_id=observation.page_id,
                args={"url": url},
                expected={"url_equals": expected_url},
            )
            authority = BrowserActionAuthority.from_observation(
                browser_action,
                observation,
                permission,
            )
            evidence = browser.act(browser_action, authority)
            if not evidence.success:
                browser.close_session(session.session_id)
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=False,
                    data={
                        "browser_session_id": session.session_id,
                        "browser_evidence": asdict(evidence),
                    },
                    error=evidence.error or "managed browser navigation failed",
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )

            return BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=True,
                output=evidence.url_after,
                data={
                    "browser_session_id": session.session_id,
                    "page_id": evidence.page_id,
                    "url_before": evidence.url_before,
                    "url_after": evidence.url_after,
                    "title": str(evidence.data.get("title") or ""),
                    "load_state": str(evidence.data.get("load_state") or ""),
                    "provider": str(evidence.data.get("provider") or session.provider),
                    "browser_evidence": asdict(evidence),
                },
                event_id=action.event_id,
                started_at=started,
                completed_at=utc_now(),
            )
        except BaseException:
            if session is not None:
                try:
                    browser.close_session(session.session_id)
                except Exception:
                    pass
            raise

    def _browser_set_checkbox(self, action: BodyAction, started: str) -> BodyActionResult:
        """Navigate to one explicit page and set one explicit DOM-id checkbox."""

        dom_id = str(action.args.get("dom_id") or "").strip()
        if not dom_id:
            raise ValueError("browser_set_checkbox requires dom_id")
        return self._browser_set_checkbox_target(
            action,
            started,
            query=BrowserTargetQuery(
                kind=BrowserTargetQueryKind.DOM_ID,
                value=dom_id,
            ),
            target_label=f"#{dom_id}",
        )

    def _browser_set_named_checkbox(
        self,
        action: BodyAction,
        started: str,
    ) -> BodyActionResult:
        """Set one exact accessible-name checkbox without technical DOM authority."""

        target_name = str(action.args.get("target_name") or "").strip()
        if not target_name:
            raise ValueError("browser_set_named_checkbox requires target_name")
        if len(target_name) > 160:
            raise ValueError("browser_set_named_checkbox target_name is too long")
        if any(ord(char) < 32 or ord(char) == 127 for char in target_name):
            raise ValueError("browser_set_named_checkbox target_name contains control characters")
        return self._browser_set_checkbox_target(
            action,
            started,
            query=BrowserTargetQuery(
                kind=BrowserTargetQueryKind.ACCESSIBLE_CHECKBOX_NAME,
                value=target_name,
            ),
            target_label=f'"{target_name}"',
        )

    def _browser_set_checkbox_target(
        self,
        action: BodyAction,
        started: str,
        *,
        query: BrowserTargetQuery,
        target_label: str,
    ) -> BodyActionResult:
        """Navigate, freshly bind one checkbox target, mutate, prove, and close."""

        browser = self._browser()
        url = str(action.args.get("url") or "").strip()
        checked = action.args.get("checked")
        if not url:
            raise ValueError(f"{action.kind} requires url")
        if type(checked) is not bool:
            raise ValueError(f"{action.kind} requires boolean checked")

        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_page_interaction=True,
            allow_private_network=bool(action.args.get("allow_private_network", False)),
            allowed_origins=(url,),
        )
        session = None
        closed = False
        try:
            session = self._open_session_for_target_query(
                browser,
                permission,
                query.kind,
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

            observed = browser.observe_target(
                session.session_id,
                query,
                page_id=navigation_evidence.page_id,
            )
            if observed.target is None or observed.target.role != "checkbox":
                raise ValueError(f"{action.kind} requires a visible checkbox target")

            mutation = BrowserAction.create(
                session_id=session.session_id,
                kind=(BrowserActionKind.CHECK if checked else BrowserActionKind.UNCHECK),
                page_id=observed.page_id,
                target=observed.target,
            )
            mutation_authority = BrowserActionAuthority.from_observation(
                mutation,
                observed,
                permission,
            )
            mutation_evidence = browser.act(mutation, mutation_authority)
            if not mutation_evidence.success:
                browser.close_session(session.session_id)
                closed = True
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=False,
                    data={
                        "url": navigation_evidence.url_after,
                        "target_id": observed.target.target_id,
                        "target_role": observed.target.role,
                        "target_name": observed.target.name,
                        "checked": checked,
                        "browser_evidence": asdict(mutation_evidence),
                        "closed": True,
                    },
                    error=mutation_evidence.error or "managed browser checkbox mutation failed",
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )

            browser.close_session(session.session_id)
            closed = True
            state = "checked" if checked else "unchecked"
            return BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=True,
                output=f"checkbox {target_label} is {state}",
                data={
                    "url": mutation_evidence.url_after or navigation_evidence.url_after,
                    "page_id": mutation_evidence.page_id,
                    "target_id": mutation_evidence.target_id,
                    "target_role": observed.target.role,
                    "target_name": observed.target.name,
                    "selector_hint": observed.target.selector_hint,
                    "checked": checked,
                    "provider": str(
                        mutation_evidence.data.get("provider")
                        or navigation_evidence.data.get("provider")
                        or session.provider
                    ),
                    "postcondition": mutation_evidence.postcondition,
                    "exact_node_continuity": bool(
                        mutation_evidence.data.get("exact_node_continuity")
                    ),
                    "browser_evidence": asdict(mutation_evidence),
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

    def _browser_click_named_button_to_url(
        self,
        action: BodyAction,
        started: str,
    ) -> BodyActionResult:
        """Click one exact semantic button and independently verify same-origin URL.

        Managed browser sessions may navigate to ``url`` before the click. USER-plane
        sessions are different: the already-authorized exact tab must freshly be on
        ``url`` and ZN never navigates or transfers authority before dispatch.
        """

        browser = self._browser()
        url = str(action.args.get("url") or "").strip()
        expected_url = str(action.args.get("expected_url") or "").strip()
        target_name = str(action.args.get("target_name") or "").strip()
        if not url or not expected_url:
            raise ValueError("browser_click_named_button_to_url requires url and expected_url")
        if not target_name:
            raise ValueError("browser_click_named_button_to_url requires target_name")
        if len(target_name) > 160:
            raise ValueError("browser_click_named_button_to_url target_name is too long")
        if any(ord(char) < 32 or ord(char) == 127 for char in target_name):
            raise ValueError(
                "browser_click_named_button_to_url target_name contains control characters"
            )
        if not self._same_origin(url, expected_url):
            raise ValueError(
                "browser_click_named_button_to_url currently requires same-origin expected_url"
            )

        user_plane = getattr(browser, "plane", None) is BrowserPlane.USER
        permission = BrowserPermissionContext(
            allow_navigation=not user_plane,
            allow_page_interaction=True,
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
                            "click_sent": False,
                            "closed": True,
                        },
                        error=(
                            "authorized user browser current page changed before button click; "
                            "refusing navigation, authority transfer or click"
                        ),
                        event_id=action.event_id,
                        started_at=started,
                        completed_at=utc_now(),
                    )
                current = initial
                start_url = initial.url
                navigation_provider = session.provider
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
                current = browser.observe(
                    session.session_id,
                    page_id=navigation_evidence.page_id,
                )
                start_url = navigation_evidence.url_after
                navigation_provider = str(
                    navigation_evidence.data.get("provider") or session.provider
                )

            observed = browser.observe_target(
                session.session_id,
                BrowserTargetQuery(
                    kind=BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME,
                    value=target_name,
                ),
                page_id=current.page_id,
            )
            if observed.target is None or observed.target.role != "button":
                raise ValueError(
                    "browser_click_named_button_to_url requires a visible button target"
                )

            click = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.CLICK,
                page_id=observed.page_id,
                target=observed.target,
                expected={"url_equals": expected_url},
            )
            click_authority = BrowserActionAuthority.from_observation(
                click,
                observed,
                permission,
            )
            click_evidence = browser.act(click, click_authority)
            if not click_evidence.success:
                browser.close_session(session.session_id)
                closed = True
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=False,
                    data={
                        "target_id": observed.target.target_id,
                        "target_name": observed.target.name,
                        "expected_url": expected_url,
                        "browser_evidence": asdict(click_evidence),
                        "closed": True,
                    },
                    error=click_evidence.error or "browser button click failed",
                    event_id=action.event_id,
                    started_at=started,
                    completed_at=utc_now(),
                )

            verified = browser.observe(
                session.session_id,
                page_id=click_evidence.page_id,
            )
            if verified.url != expected_url:
                browser.close_session(session.session_id)
                closed = True
                return BodyActionResult(
                    action_id=action.action_id,
                    kind=action.kind,
                    success=False,
                    data={
                        "target_id": observed.target.target_id,
                        "target_name": observed.target.name,
                        "expected_url": expected_url,
                        "observed_url": verified.url,
                        "browser_evidence": asdict(click_evidence),
                        "closed": True,
                    },
                    error=(
                        "browser button postcondition verification did not match the freshly "
                        "derived expected URL"
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
                    "url": start_url,
                    "expected_url": expected_url,
                    "observed_url": verified.url,
                    "page_id": verified.page_id,
                    "browser_plane": session.plane.value,
                    "navigation_performed": navigation_evidence is not None,
                    "target_id": click_evidence.target_id,
                    "target_role": observed.target.role,
                    "target_name": observed.target.name,
                    "selector_hint": observed.target.selector_hint,
                    "provider": str(
                        click_evidence.data.get("provider")
                        or navigation_provider
                        or session.provider
                    ),
                    "postcondition": click_evidence.postcondition,
                    "target_revalidated_before_dispatch": bool(
                        click_evidence.data.get("target_revalidated_before_dispatch")
                    ),
                    "authorization_attached_at": str(
                        click_evidence.data.get("authorization_attached_at") or ""
                    ),
                    "browser_evidence": asdict(click_evidence),
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

    @staticmethod
    def _same_origin(left: str, right: str) -> bool:
        def normalized(value: str) -> tuple[str, str, int | None] | None:
            try:
                parsed = urlsplit(value)
                scheme = str(parsed.scheme or "").lower()
                host = str(parsed.hostname or "").lower().rstrip(".")
                port = parsed.port
            except (TypeError, ValueError):
                return None
            if scheme not in {"http", "https"} or not host:
                return None
            if port is None:
                port = 80 if scheme == "http" else 443
            return scheme, host, port

        return normalized(left) is not None and normalized(left) == normalized(right)

    def _browser_observe(self, action: BodyAction, started: str) -> BodyActionResult:
        browser = self._browser()
        session_id = str(action.args.get("session_id") or "").strip()
        if not session_id:
            raise ValueError("browser_observe requires session_id")
        page_id = str(action.args.get("page_id") or "").strip()
        observation = browser.observe(session_id, page_id=page_id)
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            output=observation.url,
            data={
                "browser_session_id": observation.session.session_id,
                "page_id": observation.page_id,
                "url": observation.url,
                "title": observation.title,
                "load_state": observation.load_state,
                "captured_at": observation.captured_at,
                "provider": observation.session.provider,
            },
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

    def _browser_close(self, action: BodyAction, started: str) -> BodyActionResult:
        session_id = str(action.args.get("session_id") or "").strip()
        if not session_id:
            raise ValueError("browser_close requires session_id")
        self._browser().close_session(session_id)
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            output=session_id,
            data={"browser_session_id": session_id, "closed": True},
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

    def _browser(self):
        if self.resident is None:
            raise RuntimeError("browser Body requires a resident owner")
        browser = getattr(self.resident, "managed_browser", None)
        if browser is None:
            raise RuntimeError("resident has no managed browser")
        return browser