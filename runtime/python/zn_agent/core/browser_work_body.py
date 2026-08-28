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

    @classmethod
    def _requires_guard(cls, kind: str, args: dict[str, Any]) -> bool:
        if kind == cls._BROWSER_NAVIGATE:
            return True
        return super()._requires_guard(kind, args)

    def _dispatch(self, action: BodyAction, started: str) -> BodyActionResult:
        if action.kind == self._BROWSER_NAVIGATE:
            return self._browser_navigate(action, started)
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
