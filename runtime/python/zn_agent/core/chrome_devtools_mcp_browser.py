from __future__ import annotations

"""Managed browser adapter backed by Google's Chrome DevTools MCP runtime.

The upstream project owns Chrome automation mechanics. ZN keeps the durable
session/action/authority/effect contracts and independently re-observes browser
state before accepting side effects. Provider success is never Root completion.
"""

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

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
from .stdio_mcp import StdioMcpClient, StdioMcpCommand
from .url_safety import is_safe_url


CHROME_DEVTOOLS_MCP_PACKAGE = "chrome-devtools-mcp"
CHROME_DEVTOOLS_MCP_VERSION = "1.9.0"
CHROME_DEVTOOLS_MCP_PROVIDER = "chrome-devtools-mcp"

_REQUIRED_TOOLS = (
    "list_pages",
    "take_snapshot",
    "navigate_page",
    "new_page",
    "select_page",
    "close_page",
    "click",
    "fill",
    "press_key",
    "wait_for",
    "evaluate_script",
)
_ROLE_QUERY = {
    BrowserTargetQueryKind.ACCESSIBLE_CHECKBOX_NAME: "checkbox",
    BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME: "button",
    BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME: "textbox",
}
_MAX_SNAPSHOT_TARGETS = 512
_MAX_READABLE_TEXT = 8192
_MAX_READABLE_LINKS = 24


class ChromeDevToolsMcpBrowserError(RuntimeError):
    pass


class ChromeDevToolsMcpBrowserUnavailable(ChromeDevToolsMcpBrowserError):
    pass


@dataclass(slots=True)
class _ChromeSnapshot:
    captured_at: str
    page_id: str
    url: str
    title: str
    root: dict[str, Any]
    nodes: dict[str, dict[str, Any]]


@dataclass(slots=True)
class _ChromeSession:
    identity: BrowserSessionIdentity
    permission: BrowserPermissionContext
    client: StdioMcpClient
    default_page_id: str
    last_observation: dict[str, BrowserObservation] = field(default_factory=dict)
    snapshots: dict[str, _ChromeSnapshot] = field(default_factory=dict)


def _candidate_server_roots() -> tuple[Path, ...]:
    rows: list[Path] = []
    explicit = str(os.getenv("ZN_CHROME_DEVTOOLS_MCP_ROOT") or "").strip()
    if explicit:
        rows.append(Path(explicit).expanduser())
    for ancestor in Path(__file__).resolve().parents:
        rows.extend(
            (
                ancestor / "chrome-devtools-mcp",
                ancestor / "browser-runtimes" / "chrome-devtools-mcp",
                ancestor / "node_modules",
            )
        )
    return tuple(dict.fromkeys(path.resolve() for path in rows))


def _server_entry(root: Path) -> Path | None:
    candidates = (
        root
        / "node_modules"
        / CHROME_DEVTOOLS_MCP_PACKAGE
        / "build"
        / "src"
        / "bin"
        / "chrome-devtools-mcp.js",
        root
        / CHROME_DEVTOOLS_MCP_PACKAGE
        / "build"
        / "src"
        / "bin"
        / "chrome-devtools-mcp.js",
        root
        / "build"
        / "src"
        / "bin"
        / "chrome-devtools-mcp.js",
    )
    return next((path for path in candidates if path.is_file()), None)


def resolve_chrome_devtools_mcp_command(
    *,
    headless: bool,
    permission: BrowserPermissionContext,
) -> StdioMcpCommand:
    entry = None
    root = None
    for candidate in _candidate_server_roots():
        found = _server_entry(candidate)
        if found is not None:
            root = candidate
            entry = found
            break
    if entry is None or root is None:
        raise ChromeDevToolsMcpBrowserUnavailable(
            "pinned chrome-devtools-mcp runtime is not installed"
        )

    node = str(os.getenv("ZN_BROWSER_NODE") or "").strip() or shutil.which("node")
    env: dict[str, str] = {
        "CI": "true",
        "CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS": "1",
        "CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS": "1",
    }
    if node:
        executable = str(node)
    else:
        desktop = str(os.getenv("ZN_DESKTOP_EXECUTABLE") or "").strip()
        if not desktop or not Path(desktop).is_file():
            raise ChromeDevToolsMcpBrowserUnavailable(
                "chrome-devtools-mcp needs Node or the packaged Electron host"
            )
        executable = desktop
        env["ELECTRON_RUN_AS_NODE"] = "1"

    args = [
        executable,
        str(entry),
        "--isolated=true",
        "--page-id-routing=true",
        "--no-usage-statistics",
        "--no-performance-crux",
        "--category-performance=false",
        "--category-emulation=false",
        "--category-extensions=false",
        "--redact-network-headers=true",
    ]
    if headless:
        args.append("--headless=true")
    for origin in permission.allowed_origins:
        args.append(f"--allowed-url-pattern={origin.rstrip('/')}/*")
    return StdioMcpCommand(
        argv=tuple(args),
        cwd=root,
        env=env,
    )


def chrome_devtools_mcp_available() -> bool:
    try:
        resolve_chrome_devtools_mcp_command(
            headless=True,
            permission=BrowserPermissionContext(),
        )
    except Exception:
        return False
    return True


class ChromeDevToolsMcpManagedBrowser:
    """ZN BrowserAdapter over a pinned, replaceable Chrome DevTools MCP sidecar."""

    name = CHROME_DEVTOOLS_MCP_PROVIDER
    plane = BrowserPlane.MANAGED

    def __init__(
        self,
        *,
        client_factory=StdioMcpClient,
        command_factory=resolve_chrome_devtools_mcp_command,
        url_checker=is_safe_url,
    ) -> None:
        self._client_factory = client_factory
        self._command_factory = command_factory
        self._url_checker = url_checker
        self._sessions: dict[str, _ChromeSession] = {}

    def open_session(
        self,
        *,
        permission: BrowserPermissionContext | None = None,
        headless: bool = True,
    ) -> BrowserSessionIdentity:
        policy = permission or BrowserPermissionContext()
        command = self._command_factory(
            headless=headless,
            permission=policy,
        )
        client = self._client_factory(
            command=command,
            expected_server_names=(),
            required_tools=_REQUIRED_TOOLS,
            timeout_seconds=45.0,
        )
        try:
            client.start()
            pages = self._pages(client)
            if not pages:
                raise ChromeDevToolsMcpBrowserError(
                    "Chrome DevTools MCP returned no browser page"
                )
            selected = next(
                (item for item in pages if bool(item.get("selected"))),
                pages[0],
            )
            page_id = str(int(selected["id"]))
            identity = BrowserSessionIdentity.create(
                plane=BrowserPlane.MANAGED,
                provider=self.name,
                browser_name="chrome",
                browser_version="",
                profile_scope="ephemeral",
            )
            session = _ChromeSession(
                identity=identity,
                permission=policy,
                client=client,
                default_page_id=page_id,
            )
            self._sessions[identity.session_id] = session
            self._capture(session, page_id)
            return identity
        except BaseException:
            client.close()
            raise

    def close_session(self, session_id: str) -> None:
        session = self._sessions.pop(str(session_id or "").strip(), None)
        if session is None:
            return
        session.client.close()

    def close(self) -> None:
        for session_id in tuple(self._sessions):
            self.close_session(session_id)

    def observe(self, session_id: str, *, page_id: str = "") -> BrowserObservation:
        session = self._session(session_id)
        return self._capture(session, page_id or session.default_page_id)

    def observe_target(
        self,
        session_id: str,
        query: BrowserTargetQuery,
        *,
        page_id: str = "",
    ) -> BrowserObservation:
        session = self._session(session_id)
        resolved = page_id or session.default_page_id
        if query.kind is BrowserTargetQueryKind.DOM_ID:
            return self._observe_dom_id(session, resolved, query)
        expected_role = _ROLE_QUERY.get(query.kind)
        if expected_role is None:
            raise ChromeDevToolsMcpBrowserError(
                f"unsupported Chrome MCP target query: {query.kind.value}"
            )
        snapshot = self._fresh_snapshot(session, resolved)
        matches = [
            node
            for node in snapshot.nodes.values()
            if str(node.get("role") or "").casefold() == expected_role
            and str(node.get("name") or "").strip() == query.value
        ]
        if len(matches) != 1:
            raise ChromeDevToolsMcpBrowserError(
                "semantic browser target must resolve to exactly one current node; "
                f"got {len(matches)} for {expected_role} {query.value!r}"
            )
        node = matches[0]
        target = self._target_from_node(
            session,
            snapshot,
            node,
            selector_hint=f"ax:{expected_role}:{query.value}",
        )
        observation = BrowserObservation(
            session=session.identity,
            page_id=resolved,
            captured_at=snapshot.captured_at,
            url=snapshot.url,
            title=snapshot.title,
            load_state="observed",
            target=target,
            metadata={"provider": self.name, "snapshot_uid": target.target_id},
        )
        session.last_observation[resolved] = observation
        return observation

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        session = self._session(action.session_id)
        try:
            self._validate_authority(session, action, authority)
            if action.kind in {
                BrowserActionKind.NAVIGATE,
                BrowserActionKind.BACK,
                BrowserActionKind.FORWARD,
                BrowserActionKind.RELOAD,
            }:
                return self._navigate(session, action)
            if action.kind is BrowserActionKind.OPEN_TAB:
                return self._open_tab(session, action)
            if action.kind is BrowserActionKind.SWITCH_TAB:
                return self._switch_tab(session, action)
            if action.kind is BrowserActionKind.CLOSE_TAB:
                return self._close_tab(session, action)
            if action.kind is BrowserActionKind.FOCUS:
                return self._focus(session, action)
            if action.kind is BrowserActionKind.CLICK:
                return self._click(session, action)
            if action.kind is BrowserActionKind.TYPE_TEXT:
                return self._fill(session, action)
            if action.kind is BrowserActionKind.PRESS:
                return self._press(session, action)
            if action.kind in {
                BrowserActionKind.CHECK,
                BrowserActionKind.UNCHECK,
            }:
                return self._check(session, action)
            if action.kind is BrowserActionKind.SELECT_OPTION:
                return self._select(session, action)
            if action.kind is BrowserActionKind.WAIT:
                return self._wait(session, action)
            return self._failure(
                action,
                f"Chrome DevTools MCP action is not admitted yet: {action.kind.value}",
            )
        except Exception as exc:
            return self._failure(action, f"{type(exc).__name__}: {exc}")

    def read_page(self, session_id: str, *, page_id: str = "") -> dict[str, Any]:
        """Return bounded semantic page evidence without provider-specific DOM code."""

        session = self._session(session_id)
        resolved = page_id or session.default_page_id
        snapshot = self._fresh_snapshot(session, resolved)
        text_parts: list[str] = []
        links: list[dict[str, str]] = []
        for node in snapshot.nodes.values():
            role = str(node.get("role") or "").casefold()
            name = " ".join(str(node.get("name") or "").split())
            if name and role in {
                "statictext",
                "heading",
                "paragraph",
                "text",
                "link",
                "listitem",
                "cell",
            }:
                text_parts.append(name)
            if role == "link" and name and len(links) < _MAX_READABLE_LINKS:
                url = str(node.get("url") or "").strip()
                if url.startswith(("http://", "https://")):
                    links.append({"href": url[:2048], "text": name[:240]})
        text = "\n".join(text_parts)[:_MAX_READABLE_TEXT]
        return {
            "url": snapshot.url,
            "title": snapshot.title,
            "captured_at": snapshot.captured_at,
            "page_id": resolved,
            "text": text,
            "links": links,
            "provider": self.name,
            "profile_scope": session.identity.profile_scope,
        }

    def _navigate(
        self,
        session: _ChromeSession,
        action: BrowserAction,
    ) -> BrowserEffectEvidence:
        page_id = action.page_id or session.default_page_id
        before = self._capture(session, page_id)
        args: dict[str, Any] = {"pageId": int(page_id)}
        if action.kind is BrowserActionKind.NAVIGATE:
            url = str(action.args.get("url") or "").strip()
            if not url:
                raise ChromeDevToolsMcpBrowserError("browser navigation requires url")
            self._require_url_allowed(url, session.permission)
            args.update({"type": "url", "url": url})
        elif action.kind is BrowserActionKind.BACK:
            args["type"] = "back"
        elif action.kind is BrowserActionKind.FORWARD:
            args["type"] = "forward"
        else:
            args["type"] = "reload"
        session.client.call_tool("navigate_page", args)
        after = self._capture(session, page_id)
        self._require_url_allowed(after.url, session.permission)
        expected = str(action.expected.get("url_equals") or "").strip()
        success = not expected or after.url == expected
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=after.captured_at,
            success=success,
            page_id=page_id,
            url_before=before.url,
            url_after=after.url,
            postcondition="url_equals" if expected else "fresh_page_observed",
            data={"provider": self.name, "title": after.title, "load_state": after.load_state},
            error=None if success else "browser navigation postcondition did not match observed URL",
        )

    def _open_tab(self, session: _ChromeSession, action: BrowserAction) -> BrowserEffectEvidence:
        url = str(action.args.get("url") or "").strip()
        if not url:
            raise ChromeDevToolsMcpBrowserError("browser open_tab requires url")
        self._require_url_allowed(url, session.permission)
        before = self._capture(session, session.default_page_id)
        result = self._structured(
            session.client.call_tool("new_page", {"url": url, "background": False})
        )
        pages = result.get("pages")
        page_id = ""
        if isinstance(pages, list):
            selected = next(
                (item for item in pages if isinstance(item, dict) and item.get("selected")),
                None,
            )
            if isinstance(selected, dict):
                page_id = str(int(selected["id"]))
        if not page_id:
            current = self._pages(session.client)
            selected = next((item for item in current if item.get("selected")), current[-1])
            page_id = str(int(selected["id"]))
        session.default_page_id = page_id
        after = self._capture(session, page_id)
        self._require_url_allowed(after.url, session.permission)
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=after.captured_at,
            success=True,
            page_id=page_id,
            url_before=before.url,
            url_after=after.url,
            postcondition="fresh_new_page_observed",
            data={"provider": self.name},
        )

    def _switch_tab(self, session: _ChromeSession, action: BrowserAction) -> BrowserEffectEvidence:
        page_id = str(action.args.get("page_id") or action.page_id or "").strip()
        if not page_id.isdigit():
            raise ChromeDevToolsMcpBrowserError("browser switch_tab requires numeric page_id")
        before = self._capture(session, session.default_page_id)
        session.client.call_tool(
            "select_page",
            {"pageId": int(page_id), "bringToFront": True},
        )
        session.default_page_id = page_id
        after = self._capture(session, page_id)
        self._require_url_allowed(after.url, session.permission)
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=after.captured_at,
            success=True,
            page_id=page_id,
            url_before=before.url,
            url_after=after.url,
            postcondition="fresh_selected_page_observed",
            data={"provider": self.name},
        )

    def _close_tab(self, session: _ChromeSession, action: BrowserAction) -> BrowserEffectEvidence:
        page_id = str(action.args.get("page_id") or action.page_id or "").strip()
        if not page_id.isdigit():
            raise ChromeDevToolsMcpBrowserError("browser close_tab requires numeric page_id")
        before = self._capture(session, page_id)
        session.client.call_tool("close_page", {"pageId": int(page_id)})
        pages = self._pages(session.client)
        if not pages:
            raise ChromeDevToolsMcpBrowserError("browser close_tab left no observable page")
        selected = next((item for item in pages if item.get("selected")), pages[0])
        session.default_page_id = str(int(selected["id"]))
        after = self._capture(session, session.default_page_id)
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=after.captured_at,
            success=True,
            page_id=after.page_id,
            url_before=before.url,
            url_after=after.url,
            postcondition="closed_page_absent_from_fresh_page_list",
            data={"provider": self.name, "closed_page_id": page_id},
        )

    def _focus(self, session: _ChromeSession, action: BrowserAction) -> BrowserEffectEvidence:
        target = self._require_target(action)
        page_id = action.page_id or target.page_id
        before = self._capture(session, page_id)
        self._revalidate_target(session, target)
        result = self._evaluate_uid(
            session,
            page_id,
            target.target_id,
            "(el) => { el.focus(); return document.activeElement === el; }",
        )
        after = self._capture(session, page_id)
        current = self._snapshot_node(session, page_id, target.target_id)
        success = bool(result) and current is not None
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=after.captured_at,
            success=success,
            page_id=page_id,
            url_before=before.url,
            url_after=after.url,
            target_id=target.target_id,
            postcondition="same_exact_target_focused",
            data={"provider": self.name, "exact_node_continuity": current is not None, "focused": bool(result)},
            error=None if success else "browser focus postcondition was not observed",
        )

    def _click(self, session: _ChromeSession, action: BrowserAction) -> BrowserEffectEvidence:
        target = self._require_target(action)
        page_id = action.page_id or target.page_id
        before = self._capture(session, page_id)
        self._revalidate_target(session, target)
        session.client.call_tool(
            "click",
            {"pageId": int(page_id), "uid": target.target_id, "includeSnapshot": True},
        )
        after = self._capture(session, page_id)
        expected_url = str(action.expected.get("url_equals") or "").strip()
        expected_pressed = action.expected.get("aria_pressed")
        node = self._snapshot_node(session, page_id, target.target_id)
        success = True
        reason = ""
        if expected_url and after.url != expected_url:
            success = False
            reason = "browser click URL postcondition was not observed"
        if type(expected_pressed) is bool:
            observed_pressed = None if node is None else node.get("pressed")
            if observed_pressed is not expected_pressed:
                success = False
                reason = "browser click pressed-state postcondition was not observed"
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=after.captured_at,
            success=success,
            page_id=page_id,
            url_before=before.url,
            url_after=after.url,
            target_id=target.target_id,
            postcondition=(
                "url_equals"
                if expected_url
                else "same_exact_target_aria_pressed"
                if type(expected_pressed) is bool
                else "fresh_post_click_observation"
            ),
            data={
                "provider": self.name,
                "target_revalidated_before_dispatch": True,
                "exact_node_continuity": node is not None,
                "aria_pressed_after": None if node is None else node.get("pressed"),
            },
            error=None if success else reason,
        )

    def _fill(self, session: _ChromeSession, action: BrowserAction) -> BrowserEffectEvidence:
        target = self._require_target(action)
        if target.role not in {"textbox", "searchbox", "combobox"}:
            raise ChromeDevToolsMcpBrowserError("browser type_text requires editable target")
        text = str(action.args.get("text") or "")
        units = len(text.encode("utf-16-le")) // 2
        if units > 512:
            raise ChromeDevToolsMcpBrowserError("browser text exceeds 512 UTF-16 units")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        length = len(text)
        page_id = action.page_id or target.page_id
        before = self._capture(session, page_id)
        self._revalidate_target(session, target)
        session.client.call_tool(
            "fill",
            {
                "pageId": int(page_id),
                "uid": target.target_id,
                "value": text,
                "includeSnapshot": True,
            },
        )
        text = ""
        after = self._capture(session, page_id)
        node = self._snapshot_node(session, page_id, target.target_id)
        value = "" if node is None else str(node.get("value") or "")
        after_digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        success = node is not None and len(value) == length and after_digest == digest
        data = {
            "provider": self.name,
            "target_revalidated_before_dispatch": True,
            "exact_node_continuity": node is not None,
            "input_sent": True,
            "expected_text_length": length,
            "expected_text_sha256": digest,
            "expected_utf16_units": units,
            "text_length_after": len(value),
            "text_sha256_after": after_digest,
        }
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=after.captured_at,
            success=success,
            page_id=page_id,
            url_before=before.url,
            url_after=after.url,
            target_id=target.target_id,
            postcondition="same_exact_target_text_equals_requested",
            data=data,
            error=None if success else "browser text postcondition was not independently proven",
        )

    def _press(self, session: _ChromeSession, action: BrowserAction) -> BrowserEffectEvidence:
        page_id = action.page_id or session.default_page_id
        key = str(action.args.get("key") or "").strip()
        if not key:
            raise ChromeDevToolsMcpBrowserError("browser press requires key")
        before = self._capture(session, page_id)
        if action.target is not None:
            self._revalidate_target(session, action.target)
            self._evaluate_uid(
                session,
                page_id,
                action.target.target_id,
                "(el) => { el.focus(); return document.activeElement === el; }",
            )
        session.client.call_tool("press_key", {"pageId": int(page_id), "key": key})
        after = self._capture(session, page_id)
        expected_url = str(action.expected.get("url_equals") or "").strip()
        success = not expected_url or after.url == expected_url
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=after.captured_at,
            success=success,
            page_id=page_id,
            url_before=before.url,
            url_after=after.url,
            target_id=action.target.target_id if action.target else "",
            postcondition="fresh_post_key_observation",
            data={"provider": self.name, "key": key, "target_revalidated_before_dispatch": action.target is not None},
            error=None if success else "browser key postcondition was not observed",
        )

    def _check(self, session: _ChromeSession, action: BrowserAction) -> BrowserEffectEvidence:
        target = self._require_target(action)
        if target.role != "checkbox":
            raise ChromeDevToolsMcpBrowserError("browser check requires checkbox target")
        wanted = action.kind is BrowserActionKind.CHECK
        page_id = action.page_id or target.page_id
        before = self._capture(session, page_id)
        node_before = self._revalidate_target(session, target)
        if node_before.get("checked") is wanted:
            raise ChromeDevToolsMcpBrowserError("checkbox already has requested state")
        session.client.call_tool(
            "fill",
            {
                "pageId": int(page_id),
                "uid": target.target_id,
                "value": "true" if wanted else "false",
                "includeSnapshot": True,
            },
        )
        after = self._capture(session, page_id)
        node = self._snapshot_node(session, page_id, target.target_id)
        observed = None if node is None else node.get("checked")
        success = node is not None and observed is wanted
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=after.captured_at,
            success=success,
            page_id=page_id,
            url_before=before.url,
            url_after=after.url,
            target_id=target.target_id,
            postcondition="same_exact_target_checked_state",
            data={
                "provider": self.name,
                "exact_node_continuity": node is not None,
                "checked_before": node_before.get("checked"),
                "checked_after": observed,
            },
            error=None if success else "browser checkbox postcondition was not observed",
        )

    def _select(self, session: _ChromeSession, action: BrowserAction) -> BrowserEffectEvidence:
        target = self._require_target(action)
        value = str(action.args.get("value") or "")
        page_id = action.page_id or target.page_id
        before = self._capture(session, page_id)
        self._revalidate_target(session, target)
        session.client.call_tool(
            "fill",
            {
                "pageId": int(page_id),
                "uid": target.target_id,
                "value": value,
                "includeSnapshot": True,
            },
        )
        after = self._capture(session, page_id)
        node = self._snapshot_node(session, page_id, target.target_id)
        actual = "" if node is None else str(node.get("value") or "")
        expected_digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        actual_digest = hashlib.sha256(actual.encode("utf-8")).hexdigest()
        success = node is not None and actual == value
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=after.captured_at,
            success=success,
            page_id=page_id,
            url_before=before.url,
            url_after=after.url,
            target_id=target.target_id,
            postcondition="same_exact_target_selected_value",
            data={
                "provider": self.name,
                "exact_node_continuity": node is not None,
                "selection_dispatched": True,
                "expected_value_length": len(value),
                "expected_value_sha256": expected_digest,
                "expected_utf16_units": len(value.encode("utf-16-le")) // 2,
                "selected_value_length_after": len(actual),
                "selected_value_sha256_after": actual_digest,
            },
            error=None if success else "browser selected value postcondition was not observed",
        )

    def _wait(self, session: _ChromeSession, action: BrowserAction) -> BrowserEffectEvidence:
        page_id = action.page_id or session.default_page_id
        texts = action.args.get("text")
        if isinstance(texts, str):
            values = [texts]
        elif isinstance(texts, list):
            values = [str(item) for item in texts if str(item)]
        else:
            values = []
        if not values:
            raise ChromeDevToolsMcpBrowserError("browser wait requires text")
        before = self._capture(session, page_id)
        session.client.call_tool(
            "wait_for",
            {"pageId": int(page_id), "text": values, "timeout": int(action.args.get("timeout_ms") or 15000)},
        )
        after = self._capture(session, page_id)
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=after.captured_at,
            success=True,
            page_id=page_id,
            url_before=before.url,
            url_after=after.url,
            postcondition="fresh_wait_condition_observed",
            data={"provider": self.name, "texts": values[:8]},
        )

    def _capture(self, session: _ChromeSession, page_id: str) -> BrowserObservation:
        snapshot = self._fresh_snapshot(session, page_id)
        observation = BrowserObservation(
            session=session.identity,
            page_id=page_id,
            captured_at=snapshot.captured_at,
            url=snapshot.url,
            title=snapshot.title,
            load_state="observed",
            metadata={"provider": self.name},
        )
        session.last_observation[page_id] = observation
        return observation

    def _fresh_snapshot(self, session: _ChromeSession, page_id: str) -> _ChromeSnapshot:
        pages = self._pages(session.client)
        row = next((item for item in pages if str(item.get("id")) == page_id), None)
        if row is None:
            raise ChromeDevToolsMcpBrowserError(f"browser page no longer exists: {page_id}")
        url = str(row.get("url") or "")
        title = str(row.get("title") or "")
        if url not in {"", "about:blank"}:
            self._require_url_allowed(url, session.permission)
        result = self._structured(
            session.client.call_tool("take_snapshot", {"pageId": int(page_id)})
        )
        root = result.get("snapshot")
        if not isinstance(root, dict):
            raise ChromeDevToolsMcpBrowserError("Chrome MCP returned no structured snapshot")
        nodes: dict[str, dict[str, Any]] = {}
        stack = [root]
        while stack and len(nodes) < _MAX_SNAPSHOT_TARGETS:
            node = stack.pop()
            if not isinstance(node, dict):
                continue
            uid = str(node.get("id") or "").strip()
            if uid:
                nodes[uid] = dict(node)
            children = node.get("children")
            if isinstance(children, list):
                stack.extend(reversed(children))
        snapshot = _ChromeSnapshot(
            captured_at=utc_now(),
            page_id=page_id,
            url=url,
            title=title,
            root=dict(root),
            nodes=nodes,
        )
        session.snapshots[page_id] = snapshot
        return snapshot

    def _observe_dom_id(
        self,
        session: _ChromeSession,
        page_id: str,
        query: BrowserTargetQuery,
    ) -> BrowserObservation:
        dom_id = query.value
        token = hashlib.sha256(
            f"{session.identity.session_id}:{page_id}:{dom_id}:{utc_now()}".encode()
        ).hexdigest()[:20]
        expression = json.dumps(dom_id)
        marker = json.dumps(token)
        fn = f"""() => {{
          const matches = Array.from(document.querySelectorAll('[id]')).filter(
            el => el.id === {expression}
          );
          if (matches.length !== 1) return {{count: matches.length}};
          const el = matches[0];
          globalThis.__znBrowserRefs ??= new Map();
          globalThis.__znBrowserRefs.set({marker}, el);
          const tag = String(el.tagName || '').toLowerCase();
          const type = String(el.getAttribute('type') || '').toLowerCase();
          let role = String(el.getAttribute('role') || '').toLowerCase();
          if (!role) {{
            if (tag === 'button') role = 'button';
            else if (tag === 'select') role = 'combobox';
            else if (tag === 'textarea') role = 'textbox';
            else if (tag === 'input' && type === 'checkbox') role = 'checkbox';
            else if (tag === 'input' && type !== 'hidden') role = 'textbox';
          }}
          return {{
            count: 1,
            role,
            name: String(el.getAttribute('aria-label') || el.getAttribute('title') || '').slice(0, 160)
          }};
        }}"""
        raw = self._evaluate(session, page_id, fn)
        if not isinstance(raw, dict) or int(raw.get("count") or 0) != 1:
            count = raw.get("count") if isinstance(raw, dict) else "invalid"
            raise ChromeDevToolsMcpBrowserError(
                f"DOM id target must resolve to exactly one current node; got {count}"
            )
        base = self._fresh_snapshot(session, page_id)
        target = BrowserTarget(
            session_id=session.identity.session_id,
            page_id=page_id,
            kind=BrowserTargetKind.ELEMENT,
            target_id=f"domref:{token}:{dom_id}",
            observed_at=base.captured_at,
            url=base.url,
            frame_id=query.frame_id,
            role=str(raw.get("role") or "")[:128],
            name=str(raw.get("name") or "")[:256],
            selector_hint=f"dom_id:{dom_id}",
        )
        observation = BrowserObservation(
            session=session.identity,
            page_id=page_id,
            captured_at=base.captured_at,
            url=base.url,
            title=base.title,
            load_state="observed",
            target=target,
            metadata={"provider": self.name, "legacy_dom_id_compat": True},
        )
        session.last_observation[page_id] = observation
        return observation

    def _revalidate_target(
        self,
        session: _ChromeSession,
        target: BrowserTarget,
    ) -> dict[str, Any]:
        if target.target_id.startswith("domref:"):
            _, token, dom_id = target.target_id.split(":", 2)
            token_js = json.dumps(token)
            dom_js = json.dumps(dom_id)
            result = self._evaluate(
                session,
                target.page_id,
                f"""() => {{
                  const prior = globalThis.__znBrowserRefs?.get({token_js});
                  const current = document.getElementById({dom_js});
                  return Boolean(prior && current && prior === current && current.isConnected);
                }}""",
            )
            if result is not True:
                raise ChromeDevToolsMcpBrowserError(
                    "legacy DOM target changed before dispatch"
                )
            return {"id": target.target_id, "role": target.role, "name": target.name}
        snapshot = self._fresh_snapshot(session, target.page_id)
        node = snapshot.nodes.get(target.target_id)
        if node is None:
            raise ChromeDevToolsMcpBrowserError("browser target is stale")
        if str(node.get("role") or "").casefold() != target.role.casefold():
            raise ChromeDevToolsMcpBrowserError("browser target role changed before dispatch")
        if str(node.get("name") or "").strip() != target.name:
            raise ChromeDevToolsMcpBrowserError("browser target name changed before dispatch")
        return node

    def _validate_authority(
        self,
        session: _ChromeSession,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> None:
        page_id = action.page_id or authority.page_id or session.default_page_id
        observed = session.last_observation.get(page_id)
        if observed is None:
            raise ChromeDevToolsMcpBrowserError("browser action has no resident observation")
        authority.validate_current(action, observed, session.permission)

    def _target_from_node(
        self,
        session: _ChromeSession,
        snapshot: _ChromeSnapshot,
        node: Mapping[str, Any],
        *,
        selector_hint: str,
    ) -> BrowserTarget:
        uid = str(node.get("id") or "").strip()
        if not uid:
            raise ChromeDevToolsMcpBrowserError("snapshot target has no uid")
        return BrowserTarget(
            session_id=session.identity.session_id,
            page_id=snapshot.page_id,
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id=uid,
            observed_at=snapshot.captured_at,
            url=snapshot.url,
            frame_id="main",
            role=str(node.get("role") or "")[:128].casefold(),
            name=str(node.get("name") or "")[:256],
            selector_hint=selector_hint[:512],
        )

    def _snapshot_node(
        self,
        session: _ChromeSession,
        page_id: str,
        target_id: str,
    ) -> dict[str, Any] | None:
        snapshot = session.snapshots.get(page_id)
        if snapshot is None:
            return None
        return snapshot.nodes.get(target_id)

    def _evaluate_uid(
        self,
        session: _ChromeSession,
        page_id: str,
        uid: str,
        function: str,
    ) -> Any:
        result = session.client.call_tool(
            "evaluate_script",
            {
                "pageId": int(page_id),
                "function": function,
                "args": [uid],
                "waitForStableDom": False,
            },
        )
        return self._parse_evaluate_result(result)

    def _evaluate(self, session: _ChromeSession, page_id: str, function: str) -> Any:
        result = session.client.call_tool(
            "evaluate_script",
            {
                "pageId": int(page_id),
                "function": function,
                "waitForStableDom": False,
            },
        )
        return self._parse_evaluate_result(result)

    @staticmethod
    def _parse_evaluate_result(result: Mapping[str, Any]) -> Any:
        content = result.get("content")
        if not isinstance(content, list):
            raise ChromeDevToolsMcpBrowserError("evaluate_script returned no text content")
        text = "\n".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
        marker = "Script ran on page and returned:"
        index = text.find(marker)
        if index < 0:
            raise ChromeDevToolsMcpBrowserError("evaluate_script returned no JSON result")
        payload = text[index + len(marker) :].strip()
        fence = chr(96) * 3
        if payload.startswith(fence + "json"):
            payload = payload[len(fence) + 4 :].strip()
        if payload.endswith(fence):
            payload = payload[: -len(fence)].strip()
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ChromeDevToolsMcpBrowserError(
                "evaluate_script returned invalid JSON result"
            ) from exc

    @staticmethod
    def _structured(result: Mapping[str, Any]) -> dict[str, Any]:
        value = result.get("structuredContent")
        return dict(value) if isinstance(value, dict) else {}

    @classmethod
    def _pages(cls, client: StdioMcpClient) -> list[dict[str, Any]]:
        result = cls._structured(client.call_tool("list_pages", {}))
        pages = result.get("pages")
        if not isinstance(pages, list):
            raise ChromeDevToolsMcpBrowserError("Chrome MCP returned no structured page list")
        rows = []
        for item in pages:
            if not isinstance(item, dict):
                continue
            try:
                page_id = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            rows.append(
                {
                    "id": page_id,
                    "url": str(item.get("url") or ""),
                    "title": str(item.get("title") or ""),
                    "selected": bool(item.get("selected")),
                }
            )
        return rows

    def _session(self, session_id: str) -> _ChromeSession:
        session = self._sessions.get(str(session_id or "").strip())
        if session is None:
            raise ChromeDevToolsMcpBrowserError("unknown managed-browser session")
        return session

    @staticmethod
    def _require_target(action: BrowserAction) -> BrowserTarget:
        if action.target is None:
            raise ChromeDevToolsMcpBrowserError(
                f"browser {action.kind.value} requires a current target"
            )
        return action.target

    @staticmethod
    def _failure(action: BrowserAction, error: str) -> BrowserEffectEvidence:
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=False,
            page_id=action.page_id,
            target_id=action.target.target_id if action.target else "",
            error=error,
        )

    def _require_url_allowed(
        self,
        url: str,
        permission: BrowserPermissionContext,
    ) -> None:
        value = str(url or "").strip()
        if value == "about:blank":
            return
        if not permission.allows_origin(value):
            raise ChromeDevToolsMcpBrowserError(
                "browser URL left the resident-authorized origin scope"
            )
        try:
            safe = bool(
                self._url_checker(
                    value,
                    allow_private=permission.allow_private_network,
                )
            )
        except Exception:
            safe = False
        if not safe:
            raise ChromeDevToolsMcpBrowserError(
                "browser URL failed resident URL safety checks"
            )
