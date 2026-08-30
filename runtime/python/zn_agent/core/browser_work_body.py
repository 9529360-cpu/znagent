from __future__ import annotations

"""Work-facing browser Body movements with durable replay boundaries."""

from dataclasses import asdict
from typing import Any

from .atomic_overwrite_namespace_recovery_resident import AtomicOverwriteNamespaceAwareBody
from .body import BodyAction, BodyActionResult
from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from .models import utc_now


class BrowserSideEffectAwareBody(AtomicOverwriteNamespaceAwareBody):
    """Extend ZN's mature Body with one bounded managed-browser product path.

    The base deliberately remains the current final overwrite-aware Body rather
    than an earlier SideEffectAwareBody layer. That preserves atomic overwrite,
    namespace recovery, keyboard/pointer, and generic side-effect protocols while
    adding browser navigation as another guarded outside-world movement.
    """

    _BROWSER_NAVIGATE = "browser_navigate"
    _BROWSER_NAVIGATE_FOCUS = "browser_navigate_focus"

    @classmethod
    def _requires_guard(cls, kind: str, args: dict[str, Any]) -> bool:
        if kind in {cls._BROWSER_NAVIGATE, cls._BROWSER_NAVIGATE_FOCUS}:
            return True
        return super()._requires_guard(kind, args)

    def _dispatch(self, action: BodyAction, started: str) -> BodyActionResult:
        if action.kind == self._BROWSER_NAVIGATE:
            return self._browser_navigate(action, started)
        if action.kind == self._BROWSER_NAVIGATE_FOCUS:
            return self._browser_navigate_focus(action, started)
        if action.kind == "browser_observe":
            return self._browser_observe(action, started)
        if action.kind == "browser_close":
            return self._browser_close(action, started)
        return super()._dispatch(action, started)

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

    def _browser_navigate_focus(self, action: BodyAction, started: str) -> BodyActionResult:
        browser = self._browser()
        url = str(action.args.get("url") or "").strip()
        dom_id = str(action.args.get("dom_id") or "").strip()
        if not url or not dom_id:
            raise ValueError("browser_navigate_focus requires url and dom_id")

        permission = BrowserPermissionContext(
            allow_navigation=True,
            allow_page_interaction=True,
            allow_private_network=bool(action.args.get("allow_private_network", False)),
            allowed_origins=(url,),
        )
        session = None
        try:
            session = browser.open_session(permission=permission, headless=True)
            initial = browser.observe(session.session_id)
            navigation = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.NAVIGATE,
                page_id=initial.page_id,
                args={"url": url},
                expected={"url_equals": url},
            )
            navigation_evidence = browser.act(
                navigation,
                BrowserActionAuthority.from_observation(navigation, initial, permission),
            )
            if not navigation_evidence.success:
                browser.close_session(session.session_id)
                return self._failed_composite_action(
                    action,
                    started,
                    navigation_evidence.error or "managed browser navigation failed",
                    browser_evidence=asdict(navigation_evidence),
                )

            target_observation = browser.observe_target(
                session.session_id,
                BrowserTargetQuery(kind=BrowserTargetQueryKind.DOM_ID, value=dom_id),
                page_id=navigation_evidence.page_id,
            )
            focus = BrowserAction.create(
                session_id=session.session_id,
                kind=BrowserActionKind.FOCUS,
                page_id=target_observation.page_id,
                target=target_observation.target,
            )
            focus_evidence = browser.act(
                focus,
                BrowserActionAuthority.from_observation(
                    focus, target_observation, permission
                ),
            )
            if not focus_evidence.success:
                browser.close_session(session.session_id)
                return self._failed_composite_action(
                    action,
                    started,
                    focus_evidence.error or "managed browser focus failed",
                    browser_evidence=asdict(navigation_evidence),
                    focus_evidence=asdict(focus_evidence),
                )

            target = target_observation.target
            if target is None:
                raise RuntimeError("managed browser focus lost target observation")
            return BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=True,
                output=focus_evidence.target_id,
                data={
                    "browser_session_id": session.session_id,
                    "page_id": focus_evidence.page_id,
                    "url_after": focus_evidence.url_after,
                    "target_id": focus_evidence.target_id,
                    "target_role": target.role,
                    "target_name": target.name,
                    "browser_evidence": asdict(navigation_evidence),
                    "focus_evidence": asdict(focus_evidence),
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

    @staticmethod
    def _failed_composite_action(
        action: BodyAction, started: str, error: str, **data: Any
    ) -> BodyActionResult:
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=False,
            data=data,
            error=error,
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

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
