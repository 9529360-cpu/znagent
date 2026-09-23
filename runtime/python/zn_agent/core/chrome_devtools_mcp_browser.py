from __future__ import annotations

"""ZN BrowserAdapter over Google's Chrome DevTools MCP.

Chrome DevTools MCP owns browser mechanics. ZN owns permission, action authority,
fresh target binding, URL safety, postcondition verification, and durable Work
acceptance. Provider success is never treated as Root completion.
"""

import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

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
from .browser_select_option import browser_select_option_request
from .models import utc_now
from .stdio_mcp import StdioMcpClient, StdioMcpCommand
from .url_safety import is_safe_url


CHROME_DEVTOOLS_MCP_PACKAGE = "chrome-devtools-mcp"
CHROME_DEVTOOLS_MCP_VERSION = "1.9.0"
CHROME_DEVTOOLS_MCP_PROVIDER = f"chrome-devtools-mcp@{CHROME_DEVTOOLS_MCP_VERSION}"

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
_QUERY_ROLES = {
    BrowserTargetQueryKind.ACCESSIBLE_CHECKBOX_NAME: frozenset({"checkbox"}),
    BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME: frozenset({"button"}),
    BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME: frozenset(
        {"textbox", "searchbox"}
    ),
    BrowserTargetQueryKind.ACCESSIBLE_COMBOBOX_NAME: frozenset({"combobox"}),
}
_NAVIGATION_TYPES = {
    BrowserActionKind.BACK: "back",
    BrowserActionKind.FORWARD: "forward",
    BrowserActionKind.RELOAD: "reload",
}
_MAX_SNAPSHOT_TARGETS = 512
_MAX_READABLE_TEXT = 8192
_MAX_READABLE_LINKS = 24


class ChromeDevToolsMcpBrowserError(RuntimeError):
    pass


class ChromeDevToolsMcpBrowserUnavailable(ChromeDevToolsMcpBrowserError):
    pass


@dataclass(slots=True)
class _Snapshot:
    captured_at: str
    page_id: str
    url: str
    title: str
    nodes: dict[str, dict[str, Any]]


@dataclass(slots=True)
class _Session:
    identity: BrowserSessionIdentity
    permission: BrowserPermissionContext
    client: StdioMcpClient
    default_page_id: str
    last_observation: dict[str, BrowserObservation] = field(default_factory=dict)
    snapshots: dict[str, _Snapshot] = field(default_factory=dict)


def _candidate_roots() -> tuple[Path, ...]:
    rows: list[Path] = []
    explicit = str(os.getenv("ZN_CHROME_DEVTOOLS_MCP_ROOT") or "").strip()
    if explicit:
        rows.append(Path(explicit).expanduser())
    for ancestor in Path(__file__).resolve().parents:
        rows.extend(
            (
                ancestor / "browser-runtimes" / CHROME_DEVTOOLS_MCP_PACKAGE,
                ancestor / CHROME_DEVTOOLS_MCP_PACKAGE,
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
        root / "build" / "src" / "bin" / "chrome-devtools-mcp.js",
    )
    return next((path for path in candidates if path.is_file()), None)


def _require_pinned_server_package(entry: Path) -> Path:
    for parent in entry.parents:
        manifest = parent / "package.json"
        if not manifest.is_file():
            continue
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ChromeDevToolsMcpBrowserUnavailable(
                f"Chrome DevTools MCP package manifest is unreadable: {manifest}"
            ) from exc
        if str(raw.get("name") or "").strip() != CHROME_DEVTOOLS_MCP_PACKAGE:
            continue
        version = str(raw.get("version") or "").strip()
        if version != CHROME_DEVTOOLS_MCP_VERSION:
            raise ChromeDevToolsMcpBrowserUnavailable(
                "Chrome DevTools MCP version mismatch: "
                f"expected {CHROME_DEVTOOLS_MCP_VERSION}, got {version or '<missing>'}"
            )
        return parent
    raise ChromeDevToolsMcpBrowserUnavailable(
        "Chrome DevTools MCP package manifest was not found beside the server entry"
    )


def _chrome_executable() -> Path | None:
    explicit = str(os.getenv("ZN_CHROME_EXECUTABLE") or "").strip()
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if not candidate.is_file():
            raise ChromeDevToolsMcpBrowserUnavailable(
                "ZN_CHROME_EXECUTABLE does not identify a Chrome executable"
            )
        return candidate

    candidates: list[Path] = []
    if os.name == "nt":
        for name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            root = str(os.getenv(name) or "").strip()
            if root:
                candidates.append(
                    Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"
                )
    elif sys.platform == "darwin":
        candidates.append(
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        )
    else:
        for command in ("google-chrome", "google-chrome-stable", "chrome"):
            found = shutil.which(command)
            if found:
                candidates.append(Path(found))
    return next((path.resolve() for path in candidates if path.is_file()), None)


def resolve_chrome_devtools_mcp_command(
    *,
    headless: bool,
    permission: BrowserPermissionContext,
) -> StdioMcpCommand:
    root = entry = None
    for candidate in _candidate_roots():
        found = _server_entry(candidate)
        if found is not None:
            root, entry = candidate, found
            break
    if root is None or entry is None:
        raise ChromeDevToolsMcpBrowserUnavailable(
            "pinned chrome-devtools-mcp runtime is not installed"
        )
    _require_pinned_server_package(entry)

    node = (
        str(os.getenv("ZN_NODE_EXECUTABLE") or "").strip()
        or str(os.getenv("ZN_BROWSER_NODE") or "").strip()
        or shutil.which("node")
    )
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
        "--experimental-structured-content=true",
        "--no-usage-statistics",
        "--no-performance-crux",
        "--category-performance=false",
        "--category-emulation=false",
        "--category-extensions=false",
        "--redact-network-headers=true",
    ]
    browser_executable = _chrome_executable()
    if browser_executable is None:
        raise ChromeDevToolsMcpBrowserUnavailable(
            "Google Chrome is unavailable; keep Playwright as the managed-browser fallback"
        )
    args.extend(("--executable-path", str(browser_executable)))
    if headless:
        args.append("--headless=true")
    for origin in permission.allowed_origins:
        args.append(f"--allowed-url-pattern={origin.rstrip('/')}/*")
    return StdioMcpCommand(argv=tuple(args), cwd=root, env=env)


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
    """Thin provider adapter; all browser mechanics stay upstream."""

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
        self._sessions: dict[str, _Session] = {}

    def open_session(
        self,
        *,
        permission: BrowserPermissionContext | None = None,
        headless: bool = True,
    ) -> BrowserSessionIdentity:
        policy = permission or BrowserPermissionContext()
        if policy.allow_uploads or policy.allow_downloads:
            raise ChromeDevToolsMcpBrowserUnavailable(
                "Chrome DevTools MCP does not own ZN's causal file-transfer contract; "
                "use the Playwright managed-browser provider for this session"
            )
        client = self._client_factory(
            command=self._command_factory(headless=headless, permission=policy),
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
            selected = next((row for row in pages if row["selected"]), pages[0])
            identity = BrowserSessionIdentity.create(
                plane=BrowserPlane.MANAGED,
                provider=self.name,
                browser_name="chrome",
                profile_scope="ephemeral",
            )
            session = _Session(
                identity=identity,
                permission=policy,
                client=client,
                default_page_id=str(selected["id"]),
            )
            self._sessions[identity.session_id] = session
            self._capture(session, session.default_page_id)
            return identity
        except BaseException:
            client.close()
            raise

    def close_session(self, session_id: str) -> None:
        session = self._sessions.pop(str(session_id or "").strip(), None)
        if session is not None:
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
        if query.kind is BrowserTargetQueryKind.DOM_ID:
            raise ChromeDevToolsMcpBrowserError(
                "legacy DOM-id authority is not part of the mature browser provider; "
                "use a fresh semantic target"
            )
        roles = _QUERY_ROLES.get(query.kind)
        if roles is None:
            raise ChromeDevToolsMcpBrowserError(
                f"unsupported semantic query: {query.kind.value}"
            )
        session = self._session(session_id)
        resolved = page_id or session.default_page_id
        snapshot = self._snapshot(session, resolved)
        matches = [
            node
            for node in snapshot.nodes.values()
            if str(node.get("role") or "").casefold() in roles
            and str(node.get("name") or "").strip() == query.value
        ]
        if len(matches) != 1:
            raise ChromeDevToolsMcpBrowserError(
                "semantic target must resolve to exactly one fresh node; "
                f"observed {len(matches)}"
            )
        target = self._target(session, snapshot, matches[0], query)
        observation = BrowserObservation(
            session=session.identity,
            page_id=resolved,
            captured_at=snapshot.captured_at,
            url=snapshot.url,
            title=snapshot.title,
            load_state="observed",
            target=target,
            metadata={"provider": self.name},
        )
        session.last_observation[resolved] = observation
        return observation

    def read_page(self, session_id: str, *, page_id: str = "") -> dict[str, Any]:
        session = self._session(session_id)
        snapshot = self._snapshot(session, page_id or session.default_page_id)
        text: list[str] = []
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
                text.append(name)
            if role == "link" and name and len(links) < _MAX_READABLE_LINKS:
                href = str(node.get("url") or "").strip()
                if href.startswith(("http://", "https://")):
                    links.append({"href": href[:2048], "text": name[:240]})
        return {
            "url": snapshot.url,
            "title": snapshot.title,
            "captured_at": snapshot.captured_at,
            "page_id": snapshot.page_id,
            "text": "\n".join(text)[:_MAX_READABLE_TEXT],
            "links": links,
            "provider": self.name,
            "profile_scope": session.identity.profile_scope,
        }

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        session = self._session(action.session_id)
        try:
            self._validate_authority(session, action, authority)
            if action.kind is BrowserActionKind.NAVIGATE or action.kind in _NAVIGATION_TYPES:
                return self._navigate(session, action)
            if action.kind in {
                BrowserActionKind.OPEN_TAB,
                BrowserActionKind.SWITCH_TAB,
                BrowserActionKind.CLOSE_TAB,
            }:
                return self._tab_action(session, action)
            if action.kind in {
                BrowserActionKind.CLICK,
                BrowserActionKind.FOCUS,
                BrowserActionKind.TYPE_TEXT,
                BrowserActionKind.CHECK,
                BrowserActionKind.UNCHECK,
                BrowserActionKind.SELECT_OPTION,
            }:
                return self._target_action(session, action)
            if action.kind is BrowserActionKind.PRESS:
                return self._press(session, action)
            if action.kind is BrowserActionKind.WAIT:
                return self._wait(session, action)
            return self._failure(
                action,
                f"browser action is not admitted by the mature provider: {action.kind.value}",
            )
        except Exception as exc:
            return self._failure(action, f"{type(exc).__name__}: {exc}")

    def _navigate(self, session: _Session, action: BrowserAction) -> BrowserEffectEvidence:
        page_id = action.page_id or session.default_page_id
        before = self._capture(session, page_id)
        if action.kind is BrowserActionKind.NAVIGATE:
            url = str(action.args.get("url") or "").strip()
            if not url:
                raise ChromeDevToolsMcpBrowserError("navigate requires url")
            self._require_url(url, session.permission)
            arguments = {"pageId": int(page_id), "type": "url", "url": url}
        else:
            arguments = {
                "pageId": int(page_id),
                "type": _NAVIGATION_TYPES[action.kind],
            }
        session.client.call_tool("navigate_page", arguments)
        after = self._capture(session, page_id)
        expected = str(action.expected.get("url_equals") or "").strip()
        success = not expected or after.url == expected
        return self._effect(
            action,
            after,
            success=success,
            url_before=before.url,
            postcondition="safe_current_page_observed" if success else "url_equals",
            error=None if success else "navigation URL postcondition was not observed",
        )

    def _tab_action(self, session: _Session, action: BrowserAction) -> BrowserEffectEvidence:
        before = self._capture(session, session.default_page_id)
        if action.kind is BrowserActionKind.OPEN_TAB:
            url = str(action.args.get("url") or "").strip()
            if not url:
                raise ChromeDevToolsMcpBrowserError("open_tab requires url")
            self._require_url(url, session.permission)
            session.client.call_tool(
                "new_page",
                {"url": url, "background": False},
            )
        elif action.kind is BrowserActionKind.SWITCH_TAB:
            page_id = self._requested_page_id(action)
            session.client.call_tool(
                "select_page",
                {"pageId": int(page_id), "bringToFront": True},
            )
        else:
            page_id = self._requested_page_id(action)
            session.client.call_tool("close_page", {"pageId": int(page_id)})

        pages = self._pages(session.client)
        if not pages:
            raise ChromeDevToolsMcpBrowserError("browser has no observable page")
        selected = next((row for row in pages if row["selected"]), pages[0])
        session.default_page_id = str(selected["id"])
        after = self._capture(session, session.default_page_id)
        return self._effect(
            action,
            after,
            success=True,
            url_before=before.url,
            postcondition="fresh_page_topology_observed",
        )

    def _target_action(self, session: _Session, action: BrowserAction) -> BrowserEffectEvidence:
        target = self._require_target(action)
        page_id = action.page_id or target.page_id
        before = self._capture(session, page_id)
        node = self._revalidate(session, target)
        state_before = self._target_state(session, page_id, target.target_id)

        expected: dict[str, Any] = {}
        if action.kind is BrowserActionKind.FOCUS:
            self._evaluate_uid(
                session,
                page_id,
                target.target_id,
                "(el) => { el.focus(); return document.activeElement === el; }",
            )
            expected["focused"] = True
        elif action.kind is BrowserActionKind.CLICK:
            session.client.call_tool(
                "click",
                {
                    "pageId": int(page_id),
                    "uid": target.target_id,
                    "includeSnapshot": True,
                },
            )
        elif action.kind is BrowserActionKind.TYPE_TEXT:
            text = str(action.args.get("text") or "")
            self._require_safe_text_target(state_before, text)
            expected.update(self._text_fingerprint(text))
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
        elif action.kind in {BrowserActionKind.CHECK, BrowserActionKind.UNCHECK}:
            wanted = action.kind is BrowserActionKind.CHECK
            expected["checked"] = wanted
            if state_before.get("checked") is not wanted:
                session.client.call_tool(
                    "fill",
                    {
                        "pageId": int(page_id),
                        "uid": target.target_id,
                        "value": "true" if wanted else "false",
                        "includeSnapshot": True,
                    },
                )
        elif action.kind is BrowserActionKind.SELECT_OPTION:
            try:
                request = browser_select_option_request(action.args)
            except ValueError as exc:
                raise ChromeDevToolsMcpBrowserError(str(exc)) from exc
            self._require_safe_select_target(state_before)
            choice = self._select_option_choice(
                node,
                mode=request.mode,
                requested=request.requested,
            )
            current = (
                str(state_before.get("selected_value") or "")
                if request.mode == "value"
                else str(state_before.get("selected_text") or "")
            )
            if current == request.requested:
                raise ChromeDevToolsMcpBrowserError(
                    f"select_option requested {request.mode} is already selected before dispatch"
                )
            expected.update(
                {
                    "selection_mode": request.mode,
                    "requested": request.requested,
                    "requested_length": request.length,
                    "requested_sha256": request.sha256,
                    "requested_utf16_units": request.utf16_units,
                    "selected_value": choice["value"],
                    "selected_text": choice["label"],
                }
            )
            session.client.call_tool(
                "fill",
                {
                    "pageId": int(page_id),
                    "uid": target.target_id,
                    "value": choice["label"],
                    "includeSnapshot": True,
                },
            )
        else:
            raise ChromeDevToolsMcpBrowserError(
                f"unsupported browser target action: {action.kind.value}"
            )

        after = self._capture(session, page_id)
        fresh_node = self._snapshot_node(session, page_id, target.target_id)
        fresh_state = (
            self._target_state(session, page_id, target.target_id)
            if fresh_node is not None
            else {}
        )
        success, postcondition, data, error = self._verify_target_postcondition(
            action,
            node_before=node,
            state_before=state_before,
            fresh_node=fresh_node,
            fresh_state=fresh_state,
            expected=expected,
            after=after,
        )
        return self._effect(
            action,
            after,
            success=success,
            url_before=before.url,
            target_id=target.target_id,
            postcondition=postcondition,
            data=data,
            error=error,
        )

    def _verify_target_postcondition(
        self,
        action: BrowserAction,
        *,
        node_before: Mapping[str, Any],
        state_before: Mapping[str, Any],
        fresh_node: Mapping[str, Any] | None,
        fresh_state: Mapping[str, Any],
        expected: Mapping[str, Any],
        after: BrowserObservation,
    ) -> tuple[bool, str, dict[str, Any], str | None]:
        continuity = fresh_node is not None
        data: dict[str, Any] = {
            "target_revalidated_before_dispatch": True,
            "exact_node_continuity": continuity,
        }
        if action.kind is BrowserActionKind.TYPE_TEXT:
            value = str(fresh_state.get("value") or "")
            actual = self._text_fingerprint(value)
            data.update(
                {
                    "input_sent": True,
                    "expected_text_length": expected["length"],
                    "expected_text_sha256": expected["sha256"],
                    "expected_utf16_units": expected["utf16_units"],
                    "text_length_after": actual["length"],
                    "text_sha256_after": actual["sha256"],
                }
            )
            success = continuity and all(
                actual[key] == expected[key] for key in ("length", "sha256")
            )
            return (
                success,
                "same_exact_target_text_equals_requested",
                data,
                None if success else "text postcondition was not independently observed",
            )
        if action.kind in {BrowserActionKind.CHECK, BrowserActionKind.UNCHECK}:
            observed = fresh_state.get("checked")
            data.update(
                {
                    "checked_before": state_before.get("checked"),
                    "checked_after": observed,
                }
            )
            success = continuity and observed is expected["checked"]
            return (
                success,
                "same_exact_target_checked_state",
                data,
                None if success else "checked-state postcondition was not observed",
            )
        if action.kind is BrowserActionKind.SELECT_OPTION:
            observed_value = str(fresh_state.get("selected_value") or "")
            observed_label = str(fresh_state.get("selected_text") or "")
            value_matches = observed_value == str(expected["selected_value"])
            label_matches = observed_label == str(expected["selected_text"])
            mode = str(expected["selection_mode"])
            observed_requested = (
                observed_value if mode == "value" else observed_label
            )
            actual = self._text_fingerprint(observed_requested)
            data.update(
                {
                    "selection_mode": mode,
                    "selection_dispatched": True,
                    "selected_value_matches": value_matches,
                    "selected_label_matches": label_matches,
                    f"selected_{mode}_length_after": actual["length"],
                    f"selected_{mode}_sha256_after": actual["sha256"],
                    f"expected_{mode}_length": int(expected["requested_length"]),
                    f"expected_{mode}_sha256": str(expected["requested_sha256"]),
                    "expected_utf16_units": int(expected["requested_utf16_units"]),
                }
            )
            success = bool(
                continuity
                and value_matches
                and label_matches
                and actual["length"] == int(expected["requested_length"])
                and actual["sha256"] == str(expected["requested_sha256"])
            )
            return (
                success,
                f"same_exact_target_selected_{mode}",
                data,
                None if success else "selected-option postcondition was not observed",
            )
        if action.kind is BrowserActionKind.FOCUS:
            focused = bool(fresh_state.get("focused"))
            data["focused"] = focused
            success = continuity and focused
            return (
                success,
                "same_exact_target_focused",
                data,
                None if success else "focus postcondition was not observed",
            )

        expected_url = str(action.expected.get("url_equals") or "").strip()
        expected_pressed = action.expected.get("aria_pressed")
        success = True
        error = None
        if expected_url and after.url != expected_url:
            success, error = False, "click URL postcondition was not observed"
        if type(expected_pressed) is bool:
            pressed = self._as_bool(
                None if fresh_node is None else fresh_node.get("pressed")
            )
            data["aria_pressed_after"] = pressed
            if pressed is not expected_pressed:
                success, error = False, "pressed-state postcondition was not observed"
        return (
            success,
            "url_equals"
            if expected_url
            else "same_exact_target_aria_pressed"
            if type(expected_pressed) is bool
            else "fresh_post_click_observation",
            data,
            error,
        )

    def _press(self, session: _Session, action: BrowserAction) -> BrowserEffectEvidence:
        page_id = action.page_id or session.default_page_id
        key = str(action.args.get("key") or "").strip()
        if not key:
            raise ChromeDevToolsMcpBrowserError("press requires key")
        before = self._capture(session, page_id)
        if action.target is not None:
            self._revalidate(session, action.target)
            self._evaluate_uid(
                session,
                page_id,
                action.target.target_id,
                "(el) => { el.focus(); return document.activeElement === el; }",
            )
        session.client.call_tool(
            "press_key",
            {"pageId": int(page_id), "key": key, "includeSnapshot": True},
        )
        after = self._capture(session, page_id)
        expected_url = str(action.expected.get("url_equals") or "").strip()
        success = not expected_url or after.url == expected_url
        return self._effect(
            action,
            after,
            success=success,
            url_before=before.url,
            target_id=action.target.target_id if action.target else "",
            postcondition="fresh_post_key_observation",
            data={"key": key},
            error=None if success else "key postcondition was not observed",
        )

    def _wait(self, session: _Session, action: BrowserAction) -> BrowserEffectEvidence:
        page_id = action.page_id or session.default_page_id
        raw = action.args.get("text")
        texts = [raw] if isinstance(raw, str) else raw if isinstance(raw, list) else []
        values = [str(item) for item in texts if str(item)]
        if not values:
            raise ChromeDevToolsMcpBrowserError("wait requires text")
        before = self._capture(session, page_id)
        session.client.call_tool(
            "wait_for",
            {
                "pageId": int(page_id),
                "text": values,
                "timeout": int(action.args.get("timeout_ms") or 15_000),
            },
        )
        after = self._capture(session, page_id)
        return self._effect(
            action,
            after,
            success=True,
            url_before=before.url,
            postcondition="fresh_wait_condition_observed",
        )

    def _capture(self, session: _Session, page_id: str) -> BrowserObservation:
        snapshot = self._snapshot(session, page_id)
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

    def _snapshot(self, session: _Session, page_id: str) -> _Snapshot:
        page = next(
            (row for row in self._pages(session.client) if str(row["id"]) == page_id),
            None,
        )
        if page is None:
            raise ChromeDevToolsMcpBrowserError(f"browser page no longer exists: {page_id}")
        url = str(page["url"])
        if url not in {"", "about:blank"}:
            self._require_url(url, session.permission)
        result = session.client.call_tool(
            "take_snapshot",
            {"pageId": int(page_id)},
        )
        root = self._structured(result).get("snapshot")
        if not isinstance(root, dict):
            raise ChromeDevToolsMcpBrowserError("provider returned no structured snapshot")

        nodes: dict[str, dict[str, Any]] = {}
        stack = [root]
        while stack:
            node = stack.pop()
            if not isinstance(node, dict):
                continue
            uid = str(node.get("id") or "").strip()
            if uid:
                if len(nodes) >= _MAX_SNAPSHOT_TARGETS:
                    raise ChromeDevToolsMcpBrowserError(
                        "browser snapshot exceeded bounded target inventory"
                    )
                nodes[uid] = dict(node)
            children = node.get("children")
            if isinstance(children, list):
                stack.extend(reversed(children))
        snapshot = _Snapshot(
            captured_at=utc_now(),
            page_id=page_id,
            url=url,
            title=str(page["title"]),
            nodes=nodes,
        )
        session.snapshots[page_id] = snapshot
        return snapshot

    def _revalidate(self, session: _Session, target: BrowserTarget) -> dict[str, Any]:
        node = self._snapshot(session, target.page_id).nodes.get(target.target_id)
        if node is None:
            raise ChromeDevToolsMcpBrowserError("browser target is stale")
        if str(node.get("role") or "").casefold() != target.role.casefold():
            raise ChromeDevToolsMcpBrowserError("browser target role changed")
        if str(node.get("name") or "").strip() != target.name:
            raise ChromeDevToolsMcpBrowserError("browser target name changed")
        return node

    def _target_state(
        self,
        session: _Session,
        page_id: str,
        uid: str,
    ) -> dict[str, Any]:
        value = self._evaluate_uid(
            session,
            page_id,
            uid,
            """(el) => {
              const tag = String(el.tagName || '').toLowerCase();
              const type = String(el.getAttribute?.('type') || '').toLowerCase();
              const autocomplete = String(el.getAttribute?.('autocomplete') || '').toLowerCase();
              const sensitive = type === 'password' ||
                /(^|\\s)(current-password|new-password|one-time-code|cc-[^\\s]*)(\\s|$)/.test(autocomplete);
              const rawValue = !sensitive && typeof el.value === 'string' ? el.value : '';
              const selectedOption = tag === 'select' && el.selectedOptions?.length === 1
                ? el.selectedOptions[0]
                : null;
              const selectedText = selectedOption
                ? String(selectedOption.label || '')
                : '';
              const selectedValue = selectedOption
                ? String(selectedOption.value || '')
                : '';
              return {
                connected: Boolean(el.isConnected),
                sensitive,
                disabled: Boolean(el.disabled),
                read_only: Boolean(el.readOnly),
                checked: typeof el.checked === 'boolean' ? el.checked : null,
                focused: document.activeElement === el,
                value: rawValue,
                native_select: tag === 'select',
                multiple: Boolean(el.multiple),
                selected_value: selectedValue,
                selected_text: selectedText,
              };
            }""",
        )
        if not isinstance(value, dict) or not bool(value.get("connected")):
            raise ChromeDevToolsMcpBrowserError("target is no longer connected")
        return value

    def _evaluate_uid(
        self,
        session: _Session,
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
        text = "\n".join(
            str(item.get("text") or "")
            for item in result.get("content", [])
            if isinstance(item, dict) and item.get("type") == "text"
        )
        marker = "Script ran on page and returned:"
        index = text.find(marker)
        if index < 0:
            raise ChromeDevToolsMcpBrowserError(
                "evaluate_script returned no structured value"
            )
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
                "evaluate_script returned invalid JSON"
            ) from exc

    def _validate_authority(
        self,
        session: _Session,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> None:
        page_id = action.page_id or authority.page_id or session.default_page_id
        observed = session.last_observation.get(page_id)
        if observed is None:
            raise ChromeDevToolsMcpBrowserError(
                "browser action has no Resident-owned observation"
            )
        authority.validate_current(action, observed, session.permission)

    def _require_url(
        self,
        url: str,
        permission: BrowserPermissionContext,
    ) -> None:
        value = str(url or "").strip()
        if value == "about:blank":
            return
        if not permission.allows_origin(value):
            raise ChromeDevToolsMcpBrowserError(
                "browser URL left Resident-authorized origin scope"
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
                "browser URL failed Resident URL safety checks"
            )

    def _effect(
        self,
        action: BrowserAction,
        observation: BrowserObservation,
        *,
        success: bool,
        url_before: str,
        postcondition: str,
        target_id: str = "",
        data: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> BrowserEffectEvidence:
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=observation.captured_at,
            success=success,
            page_id=observation.page_id,
            url_before=url_before,
            url_after=observation.url,
            target_id=target_id,
            postcondition=postcondition,
            data={"provider": self.name, **dict(data or {})},
            error=error,
        )

    @staticmethod
    def _target(
        session: _Session,
        snapshot: _Snapshot,
        node: Mapping[str, Any],
        query: BrowserTargetQuery,
    ) -> BrowserTarget:
        return BrowserTarget(
            session_id=session.identity.session_id,
            page_id=snapshot.page_id,
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id=str(node["id"]),
            observed_at=snapshot.captured_at,
            url=snapshot.url,
            frame_id=query.frame_id,
            role=str(node.get("role") or "").casefold()[:128],
            name=str(node.get("name") or "")[:256],
            selector_hint=f"ax:{query.kind.value}:{query.value}"[:512],
        )

    @staticmethod
    def _require_target(action: BrowserAction) -> BrowserTarget:
        if action.target is None:
            raise ChromeDevToolsMcpBrowserError(
                f"{action.kind.value} requires one fresh semantic target"
            )
        return action.target

    @staticmethod
    def _select_option_choice(
        node: Mapping[str, Any],
        *,
        mode: str,
        requested: str,
    ) -> dict[str, str]:
        children = node.get("children")
        rows: list[dict[str, str]] = []
        if isinstance(children, list):
            for child in children:
                if not isinstance(child, Mapping):
                    continue
                if str(child.get("role") or "").casefold() != "option":
                    continue
                label = str(child.get("name") or "")
                value = str(child.get("value") or "")
                if label and value:
                    rows.append({"label": label, "value": value})
        matches = [
            row for row in rows if row[mode] == requested
        ]
        if len(matches) != 1:
            raise ChromeDevToolsMcpBrowserError(
                "select_option must resolve to exactly one fresh native option"
            )
        choice = matches[0]
        if mode == "value":
            same_label = [row for row in rows if row["label"] == choice["label"]]
            if len(same_label) != 1:
                raise ChromeDevToolsMcpBrowserError(
                    "select_option value maps to an ambiguous visible option label"
                )
        return choice

    @staticmethod
    def _require_safe_select_target(state: Mapping[str, Any]) -> None:
        if not bool(state.get("native_select")):
            raise ChromeDevToolsMcpBrowserError(
                "select_option currently requires a native select/combobox target"
            )
        if bool(state.get("disabled")):
            raise ChromeDevToolsMcpBrowserError("select_option target is disabled")
        if bool(state.get("multiple")):
            raise ChromeDevToolsMcpBrowserError(
                "select_option first slice refuses multi-select targets"
            )

    @staticmethod
    def _require_safe_text_target(state: Mapping[str, Any], text: str) -> None:
        if bool(state.get("sensitive")):
            raise ChromeDevToolsMcpBrowserError(
                "sensitive browser fields require user presence"
            )
        if bool(state.get("disabled")) or bool(state.get("read_only")):
            raise ChromeDevToolsMcpBrowserError("browser text target is not writable")
        if len(text.encode("utf-16-le")) // 2 > 512:
            raise ChromeDevToolsMcpBrowserError(
                "browser text exceeds 512 UTF-16 units"
            )

    @staticmethod
    def _text_fingerprint(value: str) -> dict[str, Any]:
        return {
            "length": len(value),
            "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            "utf16_units": len(value.encode("utf-16-le")) // 2,
        }

    @staticmethod
    def _snapshot_node(
        session: _Session,
        page_id: str,
        target_id: str,
    ) -> dict[str, Any] | None:
        snapshot = session.snapshots.get(page_id)
        return None if snapshot is None else snapshot.nodes.get(target_id)

    @staticmethod
    def _structured(result: Mapping[str, Any]) -> dict[str, Any]:
        value = result.get("structuredContent")
        return dict(value) if isinstance(value, dict) else {}

    @classmethod
    def _pages(cls, client: StdioMcpClient) -> list[dict[str, Any]]:
        pages = cls._structured(client.call_tool("list_pages", {})).get("pages")
        if not isinstance(pages, list):
            raise ChromeDevToolsMcpBrowserError(
                "provider returned no structured page list"
            )
        rows: list[dict[str, Any]] = []
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

    def _session(self, session_id: str) -> _Session:
        session = self._sessions.get(str(session_id or "").strip())
        if session is None:
            raise ChromeDevToolsMcpBrowserError("unknown managed-browser session")
        return session

    @staticmethod
    def _requested_page_id(action: BrowserAction) -> str:
        value = str(action.args.get("page_id") or action.page_id or "").strip()
        if not value.isdigit():
            raise ChromeDevToolsMcpBrowserError("browser tab action requires numeric page_id")
        return value

    @staticmethod
    def _as_bool(value: Any) -> bool | None:
        if type(value) is bool:
            return value
        normalized = str(value or "").strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
        return None

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
