from __future__ import annotations

"""BrowserAdapter for one tab explicitly authorized through the ZN extension."""

import hashlib
from dataclasses import dataclass, field
from typing import Any

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
from .user_browser_extension_relay import (
    ResidentUserBrowserExtensionRelay,
    UserBrowserExtensionCommandUncertainError,
    UserBrowserExtensionRelayError,
)


class ExtensionUserBrowserError(RuntimeError):
    pass


@dataclass(slots=True)
class _ExtensionSession:
    identity: BrowserSessionIdentity
    permission: BrowserPermissionContext
    tab_id: int
    last_observation: dict[str, BrowserObservation] = field(default_factory=dict)


class AuthorizedExtensionUserBrowser:
    """Expose the already-attached extension tab through ZN Browser contracts.

    The extension owns only the transport into the browser tab. Resident still
    owns BrowserPermissionContext, fresh target authority, action identity and
    completion judgment. The adapter deliberately exposes only exact named native
    textboxes and buttons needed by selected real user tasks.
    """

    name = "zn-extension-user-browser"
    plane = BrowserPlane.USER

    def __init__(self, relay: ResidentUserBrowserExtensionRelay):
        self.relay = relay
        self._sessions: dict[str, _ExtensionSession] = {}

    def open_session(
        self,
        *,
        permission: BrowserPermissionContext | None = None,
        headless: bool = False,
    ) -> BrowserSessionIdentity:
        del headless
        policy = permission or BrowserPermissionContext()
        if policy.allow_navigation:
            raise ExtensionUserBrowserError(
                "extension user-browser slice does not grant direct navigation authority"
            )
        if policy.allow_downloads or policy.allow_uploads:
            raise ExtensionUserBrowserError(
                "extension user-browser downloads/uploads require separate file authority"
            )
        authorized = self.relay.authorized_tab()
        if authorized is None:
            raise ExtensionUserBrowserError("no extension browser tab is currently authorized")
        identity = BrowserSessionIdentity.create(
            plane=BrowserPlane.USER,
            provider=self.name,
            browser_name="chromium",
            profile_scope="user_existing",
        )
        self._sessions[identity.session_id] = _ExtensionSession(
            identity=identity,
            permission=policy,
            tab_id=authorized.tab_id,
        )
        return identity

    def close_session(self, session_id: str) -> None:
        self._sessions.pop(str(session_id or "").strip(), None)

    def close(self) -> None:
        self._sessions.clear()

    def observe(self, session_id: str, *, page_id: str = "") -> BrowserObservation:
        session = self._session(session_id)
        command = self._request("probe_current_tab")
        result = self._command_result(command, "authorized browser tab probe")
        tab_id = self._tab_id(result)
        if tab_id != session.tab_id:
            raise ExtensionUserBrowserError("extension browser observation changed tab identity")
        url = self._safe_url(result.get("url"))
        if not session.permission.allows_origin(url):
            raise ExtensionUserBrowserError(
                "extension browser current page is outside the permitted origin boundary"
            )
        title = self._title(result.get("title"))
        resolved_page = page_id or f"extension-tab-{tab_id}"
        observation = BrowserObservation(
            session=session.identity,
            page_id=resolved_page,
            captured_at=utc_now(),
            url=url,
            title=title,
            load_state="complete",
            metadata={
                "attachment": "authorized_extension_tab",
                "transport": "chrome_debugger",
            },
        )
        session.last_observation[resolved_page] = observation
        return observation

    def observe_target(
        self,
        session_id: str,
        query: BrowserTargetQuery,
        *,
        page_id: str = "",
    ) -> BrowserObservation:
        if query.kind is BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME:
            command_kind = "observe_named_textbox"
            label = "textbox"
        elif query.kind is BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME:
            command_kind = "observe_named_button"
            label = "button"
        else:
            raise ExtensionUserBrowserError(
                "extension user-browser slice supports only exact accessible textbox and button names"
            )

        session = self._session(session_id)
        command = self._request(command_kind, args={"target_name": query.value})
        result = self._command_result(command, f"authorized browser {label} observation")
        tab_id = self._tab_id(result)
        if tab_id != session.tab_id:
            raise ExtensionUserBrowserError(
                f"extension {label} observation changed tab identity"
            )
        url = self._safe_url(result.get("url"))
        if not session.permission.allows_origin(url):
            raise ExtensionUserBrowserError(
                f"extension {label} observation is outside the permitted origin boundary"
            )
        name = str(result.get("name") or "")
        if name != query.value:
            raise ExtensionUserBrowserError(
                f"extension {label} observation did not preserve the exact requested accessible name"
            )
        source_role = str(result.get("role") or "").strip().lower()
        if label == "textbox":
            if source_role not in {"textbox", "searchbox"}:
                raise ExtensionUserBrowserError(
                    "extension textbox observation did not resolve a supported textbox role"
                )
            role = "textbox"
        else:
            if source_role != "button":
                raise ExtensionUserBrowserError(
                    "extension button observation did not resolve a button role"
                )
            role = "button"
        target_id = str(result.get("target_id") or "").strip()
        if not target_id or len(target_id) > 256:
            raise ExtensionUserBrowserError(
                f"extension {label} observation returned invalid target identity"
            )
        resolved_page = page_id or f"extension-tab-{tab_id}"
        observed_at = utc_now()
        target = BrowserTarget(
            session_id=session.identity.session_id,
            page_id=resolved_page,
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id=target_id,
            observed_at=observed_at,
            url=url,
            frame_id="main",
            role=role,
            name=name,
            selector_hint=f"extension_accessible_{source_role}_name:exact",
        )
        metadata: dict[str, Any] = {
            "attachment": "authorized_extension_tab",
            "transport": "chrome_debugger_accessibility",
            "source_role": source_role,
        }
        if label == "textbox":
            metadata.update(
                {
                    "text_length": self._nonnegative_int(
                        result.get("text_length"), "text length"
                    ),
                    "text_sha256": self._digest(
                        result.get("text_sha256"), "text digest"
                    ),
                }
            )
        observation = BrowserObservation(
            session=session.identity,
            page_id=resolved_page,
            captured_at=observed_at,
            url=url,
            title=self._title(result.get("title")),
            load_state="complete",
            target=target,
            metadata=metadata,
        )
        session.last_observation[resolved_page] = observation
        return observation

    def observe_named_text_state(
        self,
        session_id: str,
        target_name: str,
        *,
        page_id: str = "",
    ):
        observed = self.observe_target(
            session_id,
            BrowserTargetQuery(
                kind=BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME,
                value=str(target_name or "").strip(),
            ),
            page_id=page_id,
        )
        return observed, {
            "text_length": int(observed.metadata["text_length"]),
            "text_sha256": str(observed.metadata["text_sha256"]),
        }

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        session = self._session(action.session_id)
        page_id = action.page_id or (
            action.target.page_id if action.target is not None else ""
        )
        current = session.last_observation.get(page_id)
        if current is None:
            raise ExtensionUserBrowserError(
                "extension browser action has no fresh resident-owned target observation"
            )
        authority.validate_current(action, current, session.permission)
        if action.kind is BrowserActionKind.TYPE_TEXT:
            return self._act_type_text(session, action, current, page_id)
        if action.kind is BrowserActionKind.CLICK:
            return self._act_click(session, action, current, page_id)
        raise ExtensionUserBrowserError(
            "extension user-browser slice supports only TYPE_TEXT and exact button CLICK mutations"
        )

    def _act_type_text(
        self,
        session: _ExtensionSession,
        action: BrowserAction,
        current: BrowserObservation,
        page_id: str,
    ) -> BrowserEffectEvidence:
        target = action.target
        if target is None or target.role != "textbox" or not target.name:
            raise ExtensionUserBrowserError(
                "extension TYPE_TEXT requires one exact textbox target"
            )
        text = action.args.get("text")
        if not isinstance(text, str) or not text:
            raise ExtensionUserBrowserError(
                "extension TYPE_TEXT requires non-empty string text"
            )

        expected_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        try:
            command = self._request(
                "type_named_textbox",
                args={
                    "target_name": target.name,
                    "target_id": target.target_id,
                    "expected_url": current.url,
                    "text": text,
                },
            )
        except UserBrowserExtensionCommandUncertainError as exc:
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
                    "input_sent": False,
                    "input_may_have_been_sent": True,
                    "command_delivery": "extension_received",
                    "requires_fresh_resense": True,
                    "expected_text_length": len(text),
                    "expected_text_sha256": expected_sha,
                },
                error=(
                    f"{exc}; refusing replay until a fresh browser observation proves the "
                    "current target state"
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
                data={"provider": self.name, "input_sent": False},
                error=str(command.get("error") or "extension textbox command failed"),
            )
        result = self._command_result(command, "authorized browser textbox mutation")
        tab_id = self._tab_id(result)
        if tab_id != session.tab_id:
            raise ExtensionUserBrowserError(
                "extension textbox mutation changed tab identity"
            )
        url_before = self._safe_url(result.get("url_before"))
        url_after = self._safe_url(result.get("url_after"))
        result_target = str(result.get("target_id") or "").strip()
        input_sent = result.get("input_sent") is True
        exact_node = result.get("exact_node_continuity") is True
        after_length = self._nonnegative_int(
            result.get("text_length_after"), "final text length"
        )
        after_sha = self._digest(result.get("text_sha256_after"), "final text digest")
        expected_length = self._nonnegative_int(
            result.get("expected_text_length"), "expected text length"
        )
        expected_result_sha = self._digest(
            result.get("expected_text_sha256"), "expected text digest"
        )
        verified = bool(
            input_sent
            and exact_node
            and result_target == target.target_id
            and url_before == current.url
            and url_after == current.url
            and expected_length == len(text)
            and expected_result_sha == expected_sha
            and after_length == len(text)
            and after_sha == expected_sha
            and str(result.get("postcondition") or "")
            == "same_exact_target_text_equals_requested"
        )
        evidence_data = {
            "provider": self.name,
            "exact_node_continuity": exact_node,
            "input_sent": input_sent,
            "text_length_before": self._nonnegative_int(
                result.get("text_length_before"), "initial text length"
            ),
            "text_sha256_before": self._digest(
                result.get("text_sha256_before"), "initial text digest"
            ),
            "text_length_after": after_length,
            "text_sha256_after": after_sha,
            "expected_text_length": expected_length,
            "expected_text_sha256": expected_result_sha,
            "expected_utf16_units": self._nonnegative_int(
                result.get("expected_utf16_units"), "expected UTF-16 units"
            ),
        }
        if not verified:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=str(command.get("completed_at") or utc_now()),
                success=False,
                page_id=page_id,
                url_before=url_before,
                url_after=url_after,
                target_id=result_target or target.target_id,
                data=evidence_data,
                error=(
                    "extension browser text input was dispatched but fresh exact-node digest "
                    "evidence did not prove the requested final state; refusing replay"
                    if input_sent
                    else "extension browser text input did not execute"
                ),
            )
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=str(command.get("completed_at") or utc_now()),
            success=True,
            page_id=page_id,
            url_before=url_before,
            url_after=url_after,
            target_id=result_target,
            postcondition="same_exact_target_text_equals_requested",
            data=evidence_data,
        )

    def _act_click(
        self,
        session: _ExtensionSession,
        action: BrowserAction,
        current: BrowserObservation,
        page_id: str,
    ) -> BrowserEffectEvidence:
        target = action.target
        if target is None or target.role != "button" or not target.name:
            raise ExtensionUserBrowserError(
                "extension CLICK requires one exact native button target"
            )
        expected_url = self._safe_url(action.expected.get("url_equals"))
        if not session.permission.allows_origin(expected_url):
            raise ExtensionUserBrowserError(
                "extension button expected URL is outside the permitted origin boundary"
            )
        if expected_url == current.url:
            raise ExtensionUserBrowserError(
                "extension button expected URL is already observed before dispatch"
            )
        try:
            command = self._request(
                "click_named_button_to_url",
                args={
                    "target_name": target.name,
                    "target_id": target.target_id,
                    "expected_url_before": current.url,
                    "expected_url_after": expected_url,
                },
            )
        except UserBrowserExtensionCommandUncertainError as exc:
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
                    "expected_url": expected_url,
                },
                error=(
                    f"{exc}; refusing replay until a fresh browser observation proves the "
                    "post-click page state"
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
                error=str(command.get("error") or "extension button command failed"),
            )
        result = self._command_result(command, "authorized browser button click")
        tab_id = self._tab_id(result)
        if tab_id != session.tab_id:
            raise ExtensionUserBrowserError("extension button click changed tab identity")
        url_before = self._safe_url(result.get("url_before"))
        url_after = self._safe_url(result.get("url_after"))
        result_target = str(result.get("target_id") or "").strip()
        click_sent = result.get("click_sent") is True
        exact_node = result.get("exact_node_continuity") is True
        revalidated = result.get("target_revalidated_before_dispatch") is True
        result_expected = self._safe_url(result.get("expected_url"))
        verified = bool(
            click_sent
            and exact_node
            and revalidated
            and result_target == target.target_id
            and url_before == current.url
            and result_expected == expected_url
            and url_after == expected_url
            and str(result.get("postcondition") or "")
            == "url_equals_after_fresh_semantic_button_click"
        )
        evidence_data = {
            "provider": self.name,
            "click_sent": click_sent,
            "exact_node_continuity": exact_node,
            "target_revalidated_before_dispatch": revalidated,
            "expected_url": result_expected,
        }
        if not verified:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=str(command.get("completed_at") or utc_now()),
                success=False,
                page_id=page_id,
                url_before=url_before,
                url_after=url_after,
                target_id=result_target or target.target_id,
                postcondition="url_equals_after_fresh_semantic_button_click",
                data=evidence_data,
                error=(
                    "extension browser button click was dispatched but fresh URL evidence did not "
                    "prove the requested final page; refusing replay"
                    if click_sent
                    else "extension browser button click did not execute"
                ),
            )
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=str(command.get("completed_at") or utc_now()),
            success=True,
            page_id=page_id,
            url_before=url_before,
            url_after=url_after,
            target_id=result_target,
            postcondition="url_equals_after_fresh_semantic_button_click",
            data=evidence_data,
        )

    def _session(self, session_id: str) -> _ExtensionSession:
        session = self._sessions.get(str(session_id or "").strip())
        if session is None:
            raise ExtensionUserBrowserError("unknown extension user-browser session")
        return session

    def _request(self, kind: str, *, args: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return self.relay.request_command(kind, args=args, timeout_seconds=5.0)
        except UserBrowserExtensionCommandUncertainError:
            raise
        except (ValueError, UserBrowserExtensionRelayError) as exc:
            raise ExtensionUserBrowserError(str(exc)) from exc

    @staticmethod
    def _command_result(command: dict[str, Any], label: str) -> dict[str, Any]:
        if command.get("success") is not True:
            raise ExtensionUserBrowserError(str(command.get("error") or f"{label} failed"))
        result = command.get("result")
        if not isinstance(result, dict):
            raise ExtensionUserBrowserError(f"{label} did not return structured evidence")
        return result

    @staticmethod
    def _tab_id(result: dict[str, Any]) -> int:
        try:
            tab_id = int(result.get("tab_id"))
        except (TypeError, ValueError) as exc:
            raise ExtensionUserBrowserError(
                "extension browser result has invalid tab identity"
            ) from exc
        if tab_id <= 0:
            raise ExtensionUserBrowserError(
                "extension browser result has invalid tab identity"
            )
        return tab_id

    @staticmethod
    def _safe_url(value: Any) -> str:
        raw = str(value or "").strip()
        from urllib.parse import urlsplit

        try:
            parsed = urlsplit(raw)
        except ValueError as exc:
            raise ExtensionUserBrowserError(
                "extension browser result has invalid URL"
            ) from exc
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ExtensionUserBrowserError(
                "extension browser left the permitted HTTP(S) boundary"
            )
        return raw

    @staticmethod
    def _title(value: Any) -> str:
        title = str(value or "").strip()
        if len(title) > 512:
            raise ExtensionUserBrowserError("extension browser title is too long")
        return title

    @staticmethod
    def _nonnegative_int(value: Any, label: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ExtensionUserBrowserError(f"extension browser {label} is invalid") from exc
        if parsed < 0:
            raise ExtensionUserBrowserError(f"extension browser {label} is invalid")
        return parsed

    @staticmethod
    def _digest(value: Any, label: str) -> str:
        digest = str(value or "").strip().lower()
        if len(digest) != 64 or any(
            char not in "0123456789abcdef" for char in digest
        ):
            raise ExtensionUserBrowserError(f"extension browser {label} is invalid")
        return digest
