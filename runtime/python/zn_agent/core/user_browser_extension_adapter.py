from __future__ import annotations

"""ZN BrowserAdapter over the explicitly authorized extension tab.

The extension is only a replaceable sensing/action resource. Session identity,
permissions, fresh action authority and effect evidence remain ZN-owned.
"""

from dataclasses import dataclass
from typing import Any, Callable

from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
    BrowserObservation,
    BrowserPermissionContext,
    BrowserPlane,
    BrowserSessionIdentity,
    BrowserTarget,
    BrowserTargetKind,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from .models import utc_now
from .url_safety import is_safe_url
from .user_browser_extension_relay import ResidentUserBrowserExtensionRelay


class ExtensionUserBrowserError(RuntimeError):
    pass


UrlChecker = Callable[..., bool]


@dataclass(slots=True)
class _ExtensionSession:
    identity: BrowserSessionIdentity
    permission: BrowserPermissionContext
    tab_id: int
    page_id: str
    last_observation: BrowserObservation | None = None


class AuthorizedExtensionUserBrowser:
    """Use only the current tab the user explicitly attached through ZN."""

    name = "zn-extension-cdp"
    plane = BrowserPlane.USER

    def __init__(
        self,
        relay: ResidentUserBrowserExtensionRelay,
        *,
        url_checker: UrlChecker = is_safe_url,
        command_timeout: float = 15.0,
    ):
        self.relay = relay
        self._url_checker = url_checker
        self.command_timeout = max(1.0, min(60.0, float(command_timeout)))
        self._sessions: dict[str, _ExtensionSession] = {}

    def open_session(
        self,
        *,
        permission: BrowserPermissionContext | None = None,
        headless: bool = False,
    ) -> BrowserSessionIdentity:
        del headless
        policy = permission or BrowserPermissionContext()
        if policy.allow_downloads or policy.allow_uploads:
            raise ExtensionUserBrowserError(
                "extension user-browser downloads/uploads require separate file authority"
            )
        tab = self.relay.authorized_tab()
        if tab is None:
            raise ExtensionUserBrowserError(
                "no browser tab is currently authorized through the ZN extension"
            )
        identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.USER,
            provider=self.name,
            browser_name="chromium",
            profile_scope="user_existing",
        )
        session = _ExtensionSession(
            identity=identity,
            permission=policy,
            tab_id=tab.tab_id,
            page_id=f"user-tab-{tab.tab_id}",
        )
        self._sessions[identity.session_id] = session
        return identity

    def close_session(self, session_id: str) -> None:
        self._sessions.pop(str(session_id or "").strip(), None)

    def close(self) -> None:
        self._sessions.clear()

    def observe(self, session_id: str, *, page_id: str = "") -> BrowserObservation:
        session = self._session(session_id)
        self._require_page_id(session, page_id)
        current = self._require_current_tab(session)
        raw = self.relay.request(
            "observe_page",
            {},
            timeout=self.command_timeout,
        )
        url = str(raw.get("url") or "").strip()
        self._require_url_allowed(url, session.permission)
        if url != current.url:
            # Authorization reports the URL at attach/reannounce time. A command
            # observation is fresher, but a drift here means the tab changed since
            # the authority was granted; stop and require a new explicit attach.
            raise ExtensionUserBrowserError(
                "authorized browser tab URL changed; re-authorize the current page before acting"
            )
        observed = BrowserObservation(
            session=session.identity,
            page_id=session.page_id,
            captured_at=utc_now(),
            url=url,
            title=str(raw.get("title") or "")[:512],
            load_state=str(raw.get("load_state") or "")[:32],
            metadata={
                "provider": self.name,
                "profile_scope": "user_existing",
                "attachment": "explicit_extension_tab",
                "tab_id": session.tab_id,
                "network_policy": "ZN observation/action scope enforced",
            },
        )
        session.last_observation = observed
        return observed

    def observe_target(
        self,
        session_id: str,
        query: BrowserTargetQuery,
        *,
        page_id: str = "",
    ) -> BrowserObservation:
        if query.kind is not BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME:
            raise ExtensionUserBrowserError(
                "extension user-browser first slice supports exact accessible textbox names only"
            )
        observed, _state = self.observe_named_text_state(
            session_id,
            query.value,
            page_id=page_id,
        )
        return observed

    def observe_named_text_state(
        self,
        session_id: str,
        target_name: str,
        *,
        page_id: str = "",
    ):
        session = self._session(session_id)
        self._require_page_id(session, page_id)
        current = self._require_current_tab(session)
        name = str(target_name or "").strip()
        if not name or len(name) > 256:
            raise ValueError("exact textbox name is invalid")
        raw = self.relay.request(
            "observe_named_textbox",
            {"target_name": name},
            timeout=self.command_timeout,
        )
        url = str(raw.get("url") or "").strip()
        self._require_url_allowed(url, session.permission)
        if url != current.url:
            raise ExtensionUserBrowserError(
                "authorized browser tab URL changed; re-authorize the current page before acting"
            )
        backend_node_id = self._backend_node_id(raw.get("backend_node_id"))
        captured_at = utc_now()
        target = BrowserTarget(
            session_id=session.identity.session_id,
            page_id=session.page_id,
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id=f"backend:{backend_node_id}",
            observed_at=captured_at,
            url=url,
            frame_id="main",
            role="textbox",
            name=name,
            selector_hint="accessible_textbox_name:exact",
        )
        observed = BrowserObservation(
            session=session.identity,
            page_id=session.page_id,
            captured_at=captured_at,
            url=url,
            title=str(raw.get("title") or "")[:512],
            load_state=str(raw.get("load_state") or "")[:32],
            target=target,
            metadata={
                "provider": self.name,
                "profile_scope": "user_existing",
                "attachment": "explicit_extension_tab",
                "tab_id": session.tab_id,
                "backend_node_id": backend_node_id,
            },
        )
        session.last_observation = observed
        return observed, {
            "text_length": int(raw.get("text_length") or 0),
            "text_sha256": str(raw.get("text_sha256") or ""),
        }

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        session = self._session(action.session_id)
        current = session.last_observation
        if current is None:
            raise ExtensionUserBrowserError(
                "browser action requires a fresh extension observation"
            )
        authority.validate_current(action, current, session.permission)
        self._require_current_tab(session)
        if action.kind is not BrowserActionKind.TYPE_TEXT:
            raise ExtensionUserBrowserError(
                "extension user-browser first slice permits TYPE_TEXT only"
            )
        target = action.target
        if target is None or target.role != "textbox":
            raise ExtensionUserBrowserError("text entry requires a fresh textbox target")
        text = action.args.get("text")
        if not isinstance(text, str) or not text:
            raise ValueError("browser text entry requires non-empty string text")
        backend_node_id = self._target_backend_node_id(target.target_id)
        raw = self.relay.request(
            "type_named_textbox",
            {
                "target_name": target.name,
                "text": text,
                "expected_backend_node_id": backend_node_id,
            },
            timeout=self.command_timeout,
        )
        before = str(raw.get("url_before") or "").strip()
        after = str(raw.get("url_after") or "").strip()
        if before != current.url or after != current.url:
            raise ExtensionUserBrowserError(
                "authorized browser URL changed during text entry; refusing completion"
            )
        if self._backend_node_id(raw.get("backend_node_id")) != backend_node_id:
            raise ExtensionUserBrowserError(
                "extension text result belongs to a different browser node"
            )
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=True,
            page_id=session.page_id,
            url_before=before,
            url_after=after,
            target_id=target.target_id,
            postcondition="same_exact_target_text_equals_requested",
            data={
                "provider": self.name,
                "exact_node_continuity": bool(raw.get("exact_node_continuity")),
                "input_sent": bool(raw.get("input_sent")),
                "text_length_before": int(raw.get("text_length_before") or 0),
                "text_sha256_before": str(raw.get("text_sha256_before") or ""),
                "text_length_after": int(raw.get("text_length_after") or 0),
                "text_sha256_after": str(raw.get("text_sha256_after") or ""),
                "expected_text_length": int(raw.get("expected_text_length") or 0),
                "expected_text_sha256": str(raw.get("expected_text_sha256") or ""),
                "expected_utf16_units": int(raw.get("expected_utf16_units") or 0),
            },
        )

    def _session(self, session_id: str) -> _ExtensionSession:
        normalized = str(session_id or "").strip()
        session = self._sessions.get(normalized)
        if session is None:
            raise ExtensionUserBrowserError("browser session does not exist")
        return session

    def _require_current_tab(self, session: _ExtensionSession):
        tab = self.relay.authorized_tab()
        if tab is None or tab.tab_id != session.tab_id:
            raise ExtensionUserBrowserError(
                "browser extension authorization changed during the session"
            )
        return tab

    @staticmethod
    def _require_page_id(session: _ExtensionSession, page_id: str) -> None:
        normalized = str(page_id or "").strip()
        if normalized and normalized != session.page_id:
            raise ExtensionUserBrowserError("browser page identity changed")

    def _require_url_allowed(
        self,
        url: str,
        permission: BrowserPermissionContext,
    ) -> None:
        if not permission.allows_origin(url):
            raise ExtensionUserBrowserError(
                "authorized browser page is outside the permitted origin boundary"
            )
        if not self._url_checker(url, allow_private=permission.allow_private_network):
            raise ExtensionUserBrowserError(
                "authorized browser page is outside the permitted network boundary"
            )

    @staticmethod
    def _backend_node_id(value: Any) -> int:
        try:
            normalized = int(value)
        except (TypeError, ValueError) as exc:
            raise ExtensionUserBrowserError(
                "browser target lacks a valid backend node identity"
            ) from exc
        if normalized <= 0:
            raise ExtensionUserBrowserError(
                "browser target lacks a valid backend node identity"
            )
        return normalized

    @classmethod
    def _target_backend_node_id(cls, target_id: str) -> int:
        prefix, separator, raw = str(target_id or "").partition(":")
        if prefix != "backend" or separator != ":":
            raise ExtensionUserBrowserError("browser target identity is not extension-backed")
        return cls._backend_node_id(raw)
