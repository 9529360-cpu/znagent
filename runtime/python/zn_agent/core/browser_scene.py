from __future__ import annotations

"""Browser Body V2 semantic scene plus tab/window sensing.

This module extends the existing Playwright-backed Browser Body. It deliberately
keeps Playwright/CDP as replaceable provider machinery: ZN owns bounded scenes,
target identity, stale-target rejection and privacy-aware current-world evidence.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urlsplit

from .browser import BrowserPlane, BrowserTarget, BrowserTargetKind
from .managed_browser import ManagedBrowserError
from .models import utc_now


_MAX_SCENE_TARGETS = 64
_MAX_TARGETS_PER_ROLE = 16
_MAX_SCENE_NAME = 256
_MAX_FRAME_URL = 2048
_MAX_TAB_TITLE = 1024
_SCENE_ROLES = (
    "link",
    "button",
    "textbox",
    "searchbox",
    "checkbox",
    "radio",
    "combobox",
    "option",
    "menu",
    "menuitem",
    "tab",
    "heading",
    "table",
    "row",
    "cell",
    "dialog",
    "form",
    "list",
    "listitem",
)
_TEXT_SCENE_ROLES = frozenset({"textbox", "searchbox", "textarea"})

_ELEMENT_STATE_SCRIPT = r"""
(element) => {
  if (!element || !element.isConnected) return { connected: false };
  const tag = String(element.tagName || "").toLowerCase();
  const inputType = String(element.getAttribute?.("type") || "").toLowerCase();
  const autocomplete = String(element.getAttribute?.("autocomplete") || "").toLowerCase();
  const sensitive = inputType === "password" ||
    /(^|\s)(current-password|new-password|one-time-code|cc-[^\s]*)(\s|$)/.test(autocomplete);
  const value = typeof element.value === "string" ? element.value : "";
  let href = "";
  try { href = tag === "a" && element.href ? new URL(element.href, location.href).href : ""; } catch {}
  return {
    connected: true,
    tag,
    input_type: inputType,
    sensitive,
    disabled: Boolean(element.disabled),
    read_only: Boolean(element.readOnly),
    checked: typeof element.checked === "boolean" ? element.checked : null,
    selected: typeof element.selected === "boolean" ? element.selected :
      (element.getAttribute?.("aria-selected") === "true" ? true :
        (element.getAttribute?.("aria-selected") === "false" ? false : null)),
    value_length: Array.from(value).length,
    href: href.slice(0, 2048),
  };
}
"""

_EXACT_NODE_EQUAL_SCRIPT = r"""
(element, other) => Boolean(element && other && element === other)
"""


@dataclass(frozen=True, slots=True)
class BrowserFrameScene:
    frame_id: str
    parent_frame_id: str
    url: str
    name: str
    is_main: bool
    observable: bool
    blocked_reason: str = ""


@dataclass(frozen=True, slots=True)
class BrowserSceneTarget:
    target_id: str
    frame_id: str
    role: str
    accessible_name: str
    visible: bool
    enabled: bool
    editable: bool
    checked: bool | None = None
    selected: bool | None = None
    sensitive: bool = False
    tag: str = ""
    href: str = ""


@dataclass(frozen=True, slots=True)
class BrowserScene:
    scene_id: str
    session_id: str
    page_id: str
    captured_at: str
    url: str
    title: str
    frames: tuple[BrowserFrameScene, ...]
    targets: tuple[BrowserSceneTarget, ...]
    truncated: bool = False
    redacted_target_count: int = 0


@dataclass(frozen=True, slots=True)
class BrowserTabScene:
    page_id: str
    url: str
    title: str
    window_id: str
    ownership: str
    is_visible_tab: bool
    is_foreground: bool
    in_authority_scope: bool


@dataclass(frozen=True, slots=True)
class BrowserWindowScene:
    window_id: str
    tab_page_ids: tuple[str, ...]
    is_foreground: bool


@dataclass(frozen=True, slots=True)
class BrowserWorkspaceScene:
    session_id: str
    captured_at: str
    windows: tuple[BrowserWindowScene, ...]
    tabs: tuple[BrowserTabScene, ...]
    foreground_known: bool
    window_topology_known: bool
    foreground_page_id: str = ""


@dataclass(slots=True)
class _SceneBinding:
    target: BrowserTarget
    scene_target: BrowserSceneTarget
    locator: Any
    handle: Any
    frame: Any
    frame_url: str
    query_role: str
    page_id: str


@dataclass(slots=True)
class _PageSceneState:
    scene: BrowserScene
    bindings: dict[str, _SceneBinding] = field(default_factory=dict)


@dataclass(slots=True)
class _BrowserSceneState:
    next_frame_sequence: int = 1
    frame_ids: dict[int, str] = field(default_factory=dict)
    page_ownership: dict[str, str] = field(default_factory=dict)
    page_scenes: dict[str, _PageSceneState] = field(default_factory=dict)


class PlaywrightBrowserSceneMixin:
    """Add bounded BrowserScene and tab/window truth to Playwright adapters.

    This layer senses only. It grants no action authority and creates no second
    browser-agent control plane. Existing exact-name mutations stay unchanged
    while callers gain a structured, privacy-aware scene for grounding.
    """

    def close_session(self, session_id: str) -> None:
        self._scene_dispose_session(str(session_id or "").strip())
        super().close_session(session_id)

    def _invalidate_target_binding(self, session: Any, page_id: str) -> None:
        self._scene_invalidate_page(session.identity.session_id, page_id)
        super()._invalidate_target_binding(session, page_id)

    def _dispose_all_target_bindings(self, session: Any) -> None:
        self._scene_dispose_session(session.identity.session_id)
        super()._dispose_all_target_bindings(session)

    def observe_browser_workspace(self, session_id: str) -> BrowserWorkspaceScene:
        session = self._session(session_id)
        self._reconcile_pages(session)
        state = self._scene_state(session)
        self._scene_register_page_ownership(session, state)
        captured_at = utc_now()

        rows: list[dict[str, Any]] = []
        visible_page_ids: list[str] = []
        for page_id, page in session.pages.items():
            if self._page_is_closed(page):
                continue
            url = str(getattr(page, "url", "") or "")
            in_scope = self._url_allowed(url, session.permission)
            title = ""
            if in_scope:
                try:
                    title = str(page.title() or "")[:_MAX_TAB_TITLE]
                except Exception:
                    title = ""
            visible = False
            try:
                visible = str(page.evaluate("document.visibilityState") or "").lower() == "visible"
            except Exception:
                visible = False
            if visible:
                visible_page_ids.append(page_id)
            rows.append(
                {
                    "page_id": page_id,
                    "url": url if in_scope else "",
                    "title": title,
                    "in_scope": in_scope,
                    "visible": visible,
                    "window_id": self._scene_window_id(session, page),
                    "ownership": state.page_ownership.get(
                        page_id, self._scene_default_ownership(session)
                    ),
                }
            )

        foreground_known = len(visible_page_ids) == 1
        foreground_page_id = visible_page_ids[0] if foreground_known else ""
        tabs = tuple(
            BrowserTabScene(
                page_id=row["page_id"],
                url=row["url"],
                title=row["title"],
                window_id=row["window_id"],
                ownership=row["ownership"],
                is_visible_tab=bool(row["visible"]),
                is_foreground=bool(
                    foreground_known and row["page_id"] == foreground_page_id
                ),
                in_authority_scope=bool(row["in_scope"]),
            )
            for row in rows
        )
        window_topology_known = bool(tabs) and all(bool(tab.window_id) for tab in tabs)
        grouped: dict[str, list[str]] = {}
        for tab in tabs:
            if tab.window_id:
                grouped.setdefault(tab.window_id, []).append(tab.page_id)
        windows = tuple(
            BrowserWindowScene(
                window_id=window_id,
                tab_page_ids=tuple(page_ids),
                is_foreground=bool(
                    foreground_known and foreground_page_id in page_ids
                ),
            )
            for window_id, page_ids in grouped.items()
        )
        return BrowserWorkspaceScene(
            session_id=session.identity.session_id,
            captured_at=captured_at,
            windows=windows,
            tabs=tabs,
            foreground_known=foreground_known,
            window_topology_known=window_topology_known,
            foreground_page_id=foreground_page_id,
        )

    def observe_scene(
        self,
        session_id: str,
        *,
        page_id: str = "",
        max_targets: int = _MAX_SCENE_TARGETS,
    ) -> BrowserScene:
        session = self._session(session_id)
        resolved_page_id = page_id or self._default_page_id(session)
        page = self._page(session, resolved_page_id)
        current_url = str(getattr(page, "url", "") or "")
        self._require_url_allowed(current_url, session.permission)
        target_limit = max(1, min(int(max_targets), _MAX_SCENE_TARGETS))
        captured_at = utc_now()
        state = self._scene_state(session)
        self._scene_register_page_ownership(session, state)
        self._scene_invalidate_page(session.identity.session_id, resolved_page_id)

        frames: list[BrowserFrameScene] = []
        targets: list[BrowserSceneTarget] = []
        bindings: dict[str, _SceneBinding] = {}
        redacted = 0
        truncated = False

        page_frames = tuple(getattr(page, "frames", ()) or ())
        if not page_frames:
            main = getattr(page, "main_frame", None)
            page_frames = (main,) if main is not None else ()
        frame_ids = self._scene_frame_ids(state, page_frames)
        scene_seed = "\x1f".join(
            (session.identity.session_id, resolved_page_id, current_url, captured_at)
        )
        scene_id = "scene-" + hashlib.sha256(scene_seed.encode("utf-8")).hexdigest()[:20]

        for frame in page_frames:
            if frame is None:
                continue
            frame_id = frame_ids[id(frame)]
            parent = getattr(frame, "parent_frame", None)
            parent_id = frame_ids.get(id(parent), "") if parent is not None else ""
            frame_url = str(getattr(frame, "url", "") or "")[:_MAX_FRAME_URL]
            frame_name = str(getattr(frame, "name", "") or "")[:160]
            is_main = frame is getattr(page, "main_frame", None) or parent is None
            same_origin = is_main or self._scene_same_origin(current_url, frame_url)
            in_scope = self._url_allowed(frame_url or "about:blank", session.permission)
            observable = bool(in_scope and same_origin)
            if not same_origin:
                blocked_reason = "cross-origin frame is fail-closed for semantic BrowserScene"
            elif not in_scope:
                blocked_reason = "frame URL is outside browser authority"
            else:
                blocked_reason = ""
            frames.append(
                BrowserFrameScene(
                    frame_id=frame_id,
                    parent_frame_id=parent_id,
                    url=frame_url if observable else "",
                    name=frame_name if observable else "",
                    is_main=is_main,
                    observable=observable,
                    blocked_reason=blocked_reason,
                )
            )
            if not observable:
                continue

            try:
                for query_role in _SCENE_ROLES:
                    if len(targets) >= target_limit:
                        truncated = True
                        break
                    locator = frame.get_by_role(query_role)
                    count = int(locator.count())
                    for index in range(min(count, _MAX_TARGETS_PER_ROLE)):
                        if len(targets) >= target_limit:
                            truncated = True
                            break
                        item = locator.nth(index)
                        try:
                            if not bool(item.is_visible()):
                                continue
                        except Exception:
                            continue
                        handle = item.element_handle()
                        if handle is None:
                            continue
                        keep = False
                        try:
                            raw = handle.evaluate(_ELEMENT_STATE_SCRIPT)
                            if not isinstance(raw, dict) or not bool(raw.get("connected")):
                                continue
                            sensitive = bool(raw.get("sensitive"))
                            role, accessible_name = self._scene_accessible_identity(
                                item, query_role
                            )
                            tag = str(raw.get("tag") or "")[:32]
                            if query_role == "textbox" and tag == "textarea":
                                role = "textarea"
                            elif query_role == "textbox" and role == "searchbox":
                                role = "searchbox"
                            elif role not in _SCENE_ROLES:
                                role = query_role
                            if sensitive and not session.permission.allow_sensitive_fields:
                                accessible_name = ""
                                redacted += 1
                            enabled = not bool(raw.get("disabled"))
                            try:
                                enabled = bool(item.is_enabled())
                            except Exception:
                                pass
                            editable = False
                            if role in _TEXT_SCENE_ROLES:
                                editable = (
                                    enabled
                                    and not bool(raw.get("read_only"))
                                    and not sensitive
                                )
                                try:
                                    editable = bool(item.is_editable()) and not sensitive
                                except Exception:
                                    pass
                            checked = (
                                raw.get("checked")
                                if type(raw.get("checked")) is bool
                                else None
                            )
                            selected = (
                                raw.get("selected")
                                if type(raw.get("selected")) is bool
                                else None
                            )
                            target_material = "\x1f".join(
                                (
                                    scene_id,
                                    frame_id,
                                    frame_url,
                                    role,
                                    accessible_name,
                                    str(index),
                                    tag,
                                )
                            )
                            target_id = "scene-target-" + hashlib.sha256(
                                target_material.encode("utf-8")
                            ).hexdigest()[:24]
                            scene_target = BrowserSceneTarget(
                                target_id=target_id,
                                frame_id=frame_id,
                                role=role,
                                accessible_name=accessible_name[:_MAX_SCENE_NAME],
                                visible=True,
                                enabled=enabled,
                                editable=editable,
                                checked=checked,
                                selected=selected,
                                sensitive=sensitive,
                                tag=tag,
                                href=str(raw.get("href") or "")[:_MAX_FRAME_URL],
                            )
                            browser_role = (
                                "textbox" if role in _TEXT_SCENE_ROLES else role
                            )
                            target = BrowserTarget(
                                session_id=session.identity.session_id,
                                page_id=resolved_page_id,
                                kind=BrowserTargetKind.ACCESSIBILITY_NODE,
                                target_id=target_id,
                                observed_at=captured_at,
                                url=current_url,
                                frame_id=frame_id,
                                role=browser_role,
                                name=accessible_name[:_MAX_SCENE_NAME],
                                selector_hint=f"browser_scene:{role}",
                            )
                            targets.append(scene_target)
                            bindings[target_id] = _SceneBinding(
                                target=target,
                                scene_target=scene_target,
                                locator=item,
                                handle=handle,
                                frame=frame,
                                frame_url=frame_url,
                                query_role=query_role,
                                page_id=resolved_page_id,
                            )
                            keep = True
                        finally:
                            if not keep:
                                self._best_effort_dispose_handle(handle)
                    if count > _MAX_TARGETS_PER_ROLE:
                        truncated = True
                if len(targets) >= target_limit:
                    truncated = True
            except Exception as exc:
                for index, info in enumerate(frames):
                    if info.frame_id == frame_id:
                        frames[index] = replace(
                            info,
                            observable=False,
                            blocked_reason=(
                                "frame became inaccessible: "
                                f"{type(exc).__name__}"
                            ),
                        )
                        break
                for target_id, binding in tuple(bindings.items()):
                    if binding.target.frame_id == frame_id:
                        self._best_effort_dispose_handle(binding.handle)
                        bindings.pop(target_id, None)
                targets = [target for target in targets if target.frame_id != frame_id]

        try:
            title = str(page.title() or "")[:_MAX_TAB_TITLE]
        except Exception:
            title = ""
        scene = BrowserScene(
            scene_id=scene_id,
            session_id=session.identity.session_id,
            page_id=resolved_page_id,
            captured_at=captured_at,
            url=current_url,
            title=title,
            frames=tuple(frames),
            targets=tuple(targets),
            truncated=truncated,
            redacted_target_count=redacted,
        )
        state.page_scenes[resolved_page_id] = _PageSceneState(
            scene=scene,
            bindings=bindings,
        )
        return scene

    def validate_scene_target(
        self,
        session_id: str,
        target_id: str,
        *,
        page_id: str = "",
    ) -> BrowserSceneTarget:
        """Revalidate a current scene target without granting action authority."""

        session = self._session(session_id)
        state = self._scene_state(session)
        resolved_page_id = page_id or self._default_page_id(session)
        page_state = state.page_scenes.get(resolved_page_id)
        if page_state is None:
            raise ManagedBrowserError(
                "browser scene target requires a fresh BrowserScene"
            )
        binding = page_state.bindings.get(str(target_id or "").strip())
        if binding is None:
            raise ManagedBrowserError("browser scene target is stale or unknown")
        if binding.scene_target.sensitive and not session.permission.allow_sensitive_fields:
            raise ManagedBrowserError(
                "browser scene target is sensitive and not authorized"
            )
        self._scene_revalidate_binding(session, binding)
        return binding.scene_target

    def _scene_revalidate_binding(self, session: Any, binding: _SceneBinding) -> None:
        page = self._page(session, binding.page_id)
        if str(getattr(page, "url", "") or "") != binding.target.url:
            raise ManagedBrowserError("browser scene target page changed")
        frames = tuple(getattr(page, "frames", ()) or ())
        if not any(frame is binding.frame for frame in frames):
            raise ManagedBrowserError("browser scene target frame is detached")
        current_frame_url = str(getattr(binding.frame, "url", "") or "")
        if current_frame_url != binding.frame_url:
            raise ManagedBrowserError("browser scene target frame navigated")
        if not self._scene_same_origin(binding.target.url, current_frame_url):
            raise ManagedBrowserError(
                "browser scene target frame crossed an origin boundary"
            )
        if not self._url_allowed(current_frame_url or "about:blank", session.permission):
            raise ManagedBrowserError(
                "browser scene target frame left the permitted origin boundary"
            )
        fresh = None
        try:
            if not bool(binding.locator.is_visible()):
                raise ManagedBrowserError("browser scene target is no longer visible")
            fresh = binding.locator.element_handle()
            if fresh is None:
                raise ManagedBrowserError("browser scene target is detached")
            try:
                same = bool(
                    binding.handle.evaluate(_EXACT_NODE_EQUAL_SCRIPT, fresh)
                )
            except Exception as exc:
                raise ManagedBrowserError(
                    "browser scene target is stale because retained provider evidence is no longer usable"
                ) from exc
            if not same:
                raise ManagedBrowserError(
                    "browser scene target became stale after page change"
                )
            role, accessible_name = self._scene_accessible_identity(
                binding.locator, binding.query_role
            )
            tag = str(
                fresh.evaluate(
                    "element => String(element.tagName || '').toLowerCase()"
                )
                or ""
            )
            expected_role = binding.scene_target.role
            if binding.query_role == "textbox" and tag == "textarea":
                role = "textarea"
            elif binding.query_role == "textbox" and role == "searchbox":
                role = "searchbox"
            elif role not in _SCENE_ROLES:
                role = binding.query_role
            if role != expected_role:
                raise ManagedBrowserError(
                    "browser scene target semantic role changed"
                )
            if (
                not binding.scene_target.sensitive
                and accessible_name[:_MAX_SCENE_NAME]
                != binding.scene_target.accessible_name
            ):
                raise ManagedBrowserError(
                    "browser scene target accessible name changed"
                )
        finally:
            if fresh is not None and fresh is not binding.handle:
                self._best_effort_dispose_handle(fresh)

    @staticmethod
    def _scene_accessible_identity(
        locator: Any,
        fallback_role: str,
    ) -> tuple[str, str]:
        try:
            try:
                snapshot = str(locator.aria_snapshot(mode="ai", depth=0) or "")
            except TypeError:
                snapshot = str(locator.aria_snapshot() or "")
        except Exception as exc:
            raise ManagedBrowserError(
                "browser accessibility snapshot failed: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        for raw_line in snapshot.splitlines():
            line = raw_line.strip()
            if not line.startswith("-"):
                continue
            payload = line[1:].strip()
            match = re.match(
                r'^([a-zA-Z0-9_-]+)(?:\s+"((?:\\.|[^"])*)")?',
                payload,
            )
            if not match:
                continue
            role = str(match.group(1) or fallback_role).lower()
            encoded_name = match.group(2)
            if encoded_name is None:
                return role, ""
            try:
                name = json.loads(f'"{encoded_name}"')
            except Exception:
                name = encoded_name.replace('\\"', '"').replace('\\\\', '\\')
            return role, str(name)[:_MAX_SCENE_NAME]
        return fallback_role, ""

    def _scene_frame_ids(
        self,
        state: _BrowserSceneState,
        frames: tuple[Any, ...],
    ) -> dict[int, str]:
        live_ids = {id(frame) for frame in frames if frame is not None}
        for object_id in tuple(state.frame_ids):
            if object_id not in live_ids:
                state.frame_ids.pop(object_id, None)
        for frame in frames:
            if frame is None:
                continue
            object_id = id(frame)
            if object_id not in state.frame_ids:
                state.frame_ids[object_id] = f"frame-{state.next_frame_sequence}"
                state.next_frame_sequence += 1
        return dict(state.frame_ids)

    @staticmethod
    def _scene_same_origin(left: str, right: str) -> bool:
        try:
            a = urlsplit(str(left or "").strip())
            b = urlsplit(str(right or "").strip())
            if a.scheme not in {"http", "https"} or b.scheme not in {"http", "https"}:
                return False

            def port(parsed: Any) -> int:
                if parsed.port is not None:
                    return int(parsed.port)
                return 443 if parsed.scheme == "https" else 80

            return (
                a.scheme.lower(),
                str(a.hostname or "").lower(),
                port(a),
            ) == (
                b.scheme.lower(),
                str(b.hostname or "").lower(),
                port(b),
            )
        except (TypeError, ValueError):
            return False

    def _scene_window_id(self, session: Any, page: Any) -> str:
        try:
            create_cdp = getattr(session.context, "new_cdp_session", None)
            if not callable(create_cdp):
                return ""
            cdp = create_cdp(page)
            try:
                raw = cdp.send("Browser.getWindowForTarget")
                window_id = int(raw.get("windowId") or 0) if isinstance(raw, dict) else 0
                return f"window-{window_id}" if window_id > 0 else ""
            finally:
                detach = getattr(cdp, "detach", None)
                if callable(detach):
                    detach()
        except Exception:
            return ""

    def _scene_state(self, session: Any) -> _BrowserSceneState:
        store = getattr(self, "_browser_scene_states", None)
        if store is None:
            store = {}
            setattr(self, "_browser_scene_states", store)
        state = store.get(session.identity.session_id)
        if state is None:
            state = _BrowserSceneState()
            store[session.identity.session_id] = state
        return state

    def _scene_register_page_ownership(
        self,
        session: Any,
        state: _BrowserSceneState,
    ) -> None:
        default = self._scene_default_ownership(session)
        live_page_ids = set(session.pages)
        for page_id in live_page_ids:
            state.page_ownership.setdefault(page_id, default)
        for page_id in tuple(state.page_ownership):
            if page_id not in live_page_ids:
                state.page_ownership.pop(page_id, None)
                self._scene_invalidate_page(session.identity.session_id, page_id)

    @staticmethod
    def _scene_default_ownership(session: Any) -> str:
        return "user_existing" if session.identity.plane is BrowserPlane.USER else "zn_created"

    def _scene_invalidate_page(self, session_id: str, page_id: str) -> None:
        store = getattr(self, "_browser_scene_states", None)
        if not isinstance(store, dict):
            return
        state = store.get(session_id)
        if state is None:
            return
        page_state = state.page_scenes.pop(page_id, None)
        if page_state is None:
            return
        for binding in page_state.bindings.values():
            self._best_effort_dispose_handle(binding.handle)

    def _scene_dispose_session(self, session_id: str) -> None:
        store = getattr(self, "_browser_scene_states", None)
        if not isinstance(store, dict):
            return
        state = store.pop(session_id, None)
        if state is None:
            return
        for page_state in state.page_scenes.values():
            for binding in page_state.bindings.values():
                self._best_effort_dispose_handle(binding.handle)
