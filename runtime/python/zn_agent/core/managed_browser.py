from __future__ import annotations

"""Local managed-browser adapter behind ZN-owned browser contracts.

Playwright is an implementation resource, not the browser control plane. The
adapter defaults to an ephemeral Chromium context, blocks service workers so
request routing remains authoritative, checks every HTTP(S) request and
WebSocket endpoint through ZN URL safety, and returns resident-owned effect
evidence after actions instead of treating provider dispatch as completion.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

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


class ManagedBrowserError(RuntimeError):
    pass


class ManagedBrowserUnavailable(ManagedBrowserError):
    pass


UrlChecker = Callable[..., bool]

_MAX_MANAGED_TEXT_UTF16_UNITS = 512
_MAX_OBSERVED_TEXT_CHARS = 4096

_TARGET_HANDLE_BUNDLE_SCRIPT = r"""
(domId) => {
  const matches = Array.from(document.querySelectorAll("[id]")).filter(
    (element) => element.id === domId
  );
  return {
    count: matches.length,
    node: matches.length === 1 ? matches[0] : null,
  };
}
"""

_TARGET_HANDLE_EVIDENCE_SCRIPT = r"""
(element, domId) => {
  const matches = Array.from(document.querySelectorAll("[id]")).filter(
    (candidate) => candidate.id === domId
  );
  const connected = Boolean(element && element.isConnected);
  const current = Boolean(
    connected &&
    matches.length === 1 &&
    matches[0] === element &&
    element.id === domId
  );
  const style = connected ? window.getComputedStyle(element) : null;
  const rect = connected ? element.getBoundingClientRect() : null;
  const visible = Boolean(
    connected &&
    !element.hidden &&
    style &&
    style.display !== "none" &&
    style.visibility !== "hidden" &&
    rect &&
    rect.width > 0 &&
    rect.height > 0
  );

  const tag = String(element && element.tagName || "").toLowerCase().slice(0, 32);
  const inputType = String(element && element.getAttribute("type") || "")
    .trim()
    .toLowerCase()
    .slice(0, 32);
  const isPassword = tag === "input" && inputType === "password";

  let role = String(element && element.getAttribute("role") || "")
    .trim()
    .toLowerCase()
    .slice(0, 64);
  if (!role) {
    if (tag === "textarea") {
      role = "textbox";
    } else if (tag === "select") {
      role = "combobox";
    } else if (tag === "button") {
      role = "button";
    } else if (tag === "a" && element.hasAttribute("href")) {
      role = "link";
    } else if (tag === "input") {
      if (inputType === "checkbox") {
        role = "checkbox";
      } else if (inputType === "radio") {
        role = "radio";
      } else if (inputType === "button" || inputType === "submit" || inputType === "reset") {
        role = "button";
      } else if (inputType !== "hidden") {
        role = "textbox";
      }
    }
  }

  let name = "";
  if (!isPassword && element) {
    const ariaLabel = String(element.getAttribute("aria-label") || "").trim();
    if (ariaLabel) {
      name = ariaLabel;
    } else if (element.labels && element.labels.length) {
      name = Array.from(element.labels)
        .map((label) => String(label.innerText || "").trim())
        .filter(Boolean)
        .join(" ");
    } else {
      name = String(element.getAttribute("title") || "").trim();
    }
  }

  return {
    count: matches.length,
    current,
    connected,
    visible,
    dom_id: String(element && element.id || "").slice(0, 256),
    tag,
    role: role.slice(0, 64),
    name: name.slice(0, 160),
    input_type: inputType,
    is_password: isPassword,
  };
}
"""

_EXACT_NODE_EQUAL_SCRIPT = r"""
(element, other) => Boolean(element && other && element === other)
"""

_TARGET_FOCUS_STATE_SCRIPT = r"""
(element) => Boolean(
  element && element.isConnected && document.activeElement === element
)
"""

_TARGET_ARIA_PRESSED_SCRIPT = r"""
(element) => {
  if (!element || !element.isConnected) {
    return null;
  }
  const value = String(element.getAttribute("aria-pressed") || "")
    .trim()
    .toLowerCase();
  if (value === "true") {
    return true;
  }
  if (value === "false") {
    return false;
  }
  return null;
}
"""

_TARGET_TEXT_STATE_SCRIPT = r"""
(element) => {
  const connected = Boolean(element && element.isConnected);
  const tag = String(element && element.tagName || "").toLowerCase();
  const inputType = String(element && element.getAttribute("type") || "")
    .trim()
    .toLowerCase();
  const isPassword = tag === "input" && inputType === "password";
  const supported = Boolean(
    tag === "textarea" ||
    (tag === "input" && (inputType === "" || inputType === "text"))
  );
  const disabled = Boolean(element && element.disabled);
  const readOnly = Boolean(element && element.readOnly);
  let value = null;
  if (connected && supported && !isPassword) {
    value = String(element.value || "");
  }
  return {
    connected,
    supported,
    disabled,
    read_only: readOnly,
    is_password: isPassword,
    value,
  };
}
"""


@dataclass(slots=True)
class _ManagedTargetBinding:
    target: BrowserTarget
    query: BrowserTargetQuery
    handle: Any


@dataclass(slots=True)
class _ManagedSession:
    identity: BrowserSessionIdentity
    permission: BrowserPermissionContext
    playwright: Any
    browser: Any
    context: Any
    pages: dict[str, Any] = field(default_factory=dict)
    last_observation: dict[str, BrowserObservation] = field(default_factory=dict)
    target_bindings: dict[str, _ManagedTargetBinding] = field(default_factory=dict)


class PlaywrightManagedBrowser:
    """ZN-owned local managed browser using Playwright Chromium as one adapter."""

    name = "playwright-chromium"
    plane = BrowserPlane.MANAGED

    def __init__(
        self,
        *,
        playwright_factory: Callable[[], Any] | None = None,
        url_checker: UrlChecker = is_safe_url,
        navigation_timeout_ms: int = 30_000,
        action_timeout_ms: int = 15_000,
    ):
        self._playwright_factory = playwright_factory
        self._url_checker = url_checker
        self.navigation_timeout_ms = max(1_000, int(navigation_timeout_ms))
        self.action_timeout_ms = max(1_000, int(action_timeout_ms))
        self._sessions: dict[str, _ManagedSession] = {}

    def open_session(
        self,
        *,
        permission: BrowserPermissionContext | None = None,
        headless: bool = True,
    ) -> BrowserSessionIdentity:
        policy = permission or BrowserPermissionContext()
        if policy.allow_downloads or policy.allow_uploads:
            raise ManagedBrowserError(
                "managed-browser downloads/uploads require explicit file authority and are not enabled in this slice"
            )
        factory = self._playwright_factory or self._default_playwright_factory
        playwright = None
        browser = None
        context = None
        try:
            playwright = factory().start()
            browser = playwright.chromium.launch(headless=bool(headless))
            identity = BrowserSessionIdentity.create(
                plane=BrowserPlane.MANAGED,
                provider=self.name,
                browser_name="chromium",
                browser_version=str(getattr(browser, "version", "") or ""),
                profile_scope="ephemeral",
            )
            context = browser.new_context(
                accept_downloads=False,
                service_workers="block",
            )
            context.set_default_navigation_timeout(self.navigation_timeout_ms)
            context.set_default_timeout(self.action_timeout_ms)
            session = _ManagedSession(
                identity=identity,
                permission=policy,
                playwright=playwright,
                browser=browser,
                context=context,
            )
            self._install_network_boundary(session)
            page = context.new_page()
            page_id = self._register_page(session, page)
            self._sessions[identity.session_id] = session
            self._capture(session, page_id)
            return identity
        except ManagedBrowserError:
            self._best_effort_close(context, browser, playwright)
            raise
        except Exception as exc:
            self._best_effort_close(context, browser, playwright)
            if self._playwright_factory is None and self._looks_like_missing_playwright(exc):
                raise ManagedBrowserUnavailable(
                    "local managed browser is unavailable; install the ZN browser optional dependency and Chromium runtime"
                ) from exc
            raise ManagedBrowserError(f"failed to open local managed browser: {type(exc).__name__}: {exc}") from exc

    def close_session(self, session_id: str) -> None:
        session = self._sessions.pop(str(session_id or "").strip(), None)
        if session is None:
            return
        self._dispose_all_target_bindings(session)
        self._best_effort_close(session.context, session.browser, session.playwright)

    def close(self) -> None:
        for session_id in tuple(self._sessions):
            self.close_session(session_id)

    def observe(self, session_id: str, *, page_id: str = "") -> BrowserObservation:
        session = self._session(session_id)
        resolved_page_id = page_id or self._default_page_id(session)
        return self._capture(session, resolved_page_id)

    def observe_target(
        self,
        session_id: str,
        query: BrowserTargetQuery,
        *,
        page_id: str = "",
    ) -> BrowserObservation:
        session = self._session(session_id)
        resolved_page_id = page_id or self._default_page_id(session)
        captured_at = utc_now()
        binding = self._acquire_target_binding(
            session,
            resolved_page_id,
            query,
            observed_at=captured_at,
        )
        try:
            return self._capture(
                session,
                resolved_page_id,
                target=binding.target,
                captured_at=captured_at,
                target_binding=binding,
            )
        except Exception:
            self._dispose_target_binding(binding)
            raise

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        session = self._session(action.session_id)
        try:
            self._validate_authority(session, action, authority)
            if action.kind is BrowserActionKind.NAVIGATE:
                return self._navigate(session, action, authority)
            if action.kind is BrowserActionKind.FOCUS:
                return self._focus(session, action)
            if action.kind is BrowserActionKind.CLICK:
                return self._click(session, action)
            if action.kind is BrowserActionKind.TYPE_TEXT:
                return self._type_text(session, action)
            return self._failure(
                action,
                error=f"managed browser action is not implemented yet: {action.kind.value}",
            )
        except Exception as exc:
            return self._failure(
                action,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _navigate(
        self,
        session: _ManagedSession,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        if not authority.permission.allow_navigation:
            raise ManagedBrowserError("browser navigation is not permitted")
        raw_url = str(action.args.get("url") or "").strip()
        if not raw_url:
            raise ManagedBrowserError("browser navigation requires url")
        self._require_url_allowed(raw_url, session.permission)

        page_id = action.page_id or authority.page_id or self._default_page_id(session)
        page = self._page(session, page_id)
        before = str(getattr(page, "url", "") or "")
        page.goto(raw_url, wait_until="domcontentloaded")
        observation = self._capture(session, page_id)
        self._require_url_allowed(observation.url, session.permission)

        expected_url = str(action.expected.get("url_equals") or "").strip()
        if expected_url and observation.url != expected_url:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=observation.captured_at,
                success=False,
                page_id=page_id,
                url_before=before,
                url_after=observation.url,
                postcondition="url_equals",
                error="browser navigation postcondition did not match observed URL",
            )

        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=observation.captured_at,
            success=True,
            page_id=page_id,
            url_before=before,
            url_after=observation.url,
            postcondition="safe_current_page_observed",
            data={
                "title": observation.title,
                "load_state": observation.load_state,
                "provider": session.identity.provider,
            },
        )

    def _focus(
        self,
        session: _ManagedSession,
        action: BrowserAction,
    ) -> BrowserEffectEvidence:
        if action.target is None:
            raise ManagedBrowserError("browser focus requires a current target")
        page_id = action.page_id or action.target.page_id or self._default_page_id(session)
        page = self._page(session, page_id)
        binding = self._revalidate_target_binding(session, page_id, action.target)
        before_url = str(getattr(page, "url", "") or "")

        try:
            binding.handle.focus()
        except Exception as exc:
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            raise ManagedBrowserError(
                f"managed browser focus dispatch failed: {type(exc).__name__}: {exc}"
            ) from exc

        post_captured_at = utc_now()
        try:
            fresh_binding = self._acquire_target_binding(
                session,
                page_id,
                binding.query,
                observed_at=post_captured_at,
            )
        except Exception as exc:
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            raise ManagedBrowserError(
                f"managed browser focus target could not be re-observed: {exc}"
            ) from exc

        try:
            same_exact_node = bool(
                binding.handle.evaluate(_EXACT_NODE_EQUAL_SCRIPT, fresh_binding.handle)
            )
        except Exception:
            same_exact_node = False
        try:
            focused = bool(fresh_binding.handle.evaluate(_TARGET_FOCUS_STATE_SCRIPT))
        except Exception:
            focused = False

        try:
            post_observation = self._capture(
                session,
                page_id,
                target=fresh_binding.target,
                captured_at=post_captured_at,
                target_binding=fresh_binding,
            )
        except Exception:
            self._dispose_target_binding(fresh_binding)
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            raise

        after_url = post_observation.url
        post_target = post_observation.target
        if post_target is None:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=post_observation.captured_at,
                success=False,
                page_id=page_id,
                url_before=before_url,
                url_after=after_url,
                target_id=action.target.target_id,
                postcondition="same_exact_target_focused",
                error="browser focus postcondition lost the current target",
            )

        if not same_exact_node:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=post_observation.captured_at,
                success=False,
                page_id=page_id,
                url_before=before_url,
                url_after=after_url,
                target_id=post_target.target_id,
                postcondition="same_exact_target_focused",
                data={
                    "provider": session.identity.provider,
                    "exact_node_continuity": False,
                    "focused": focused,
                },
                error="browser focus postcondition observed a replaced target node",
            )

        if post_target.target_id != action.target.target_id:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=post_observation.captured_at,
                success=False,
                page_id=page_id,
                url_before=before_url,
                url_after=after_url,
                target_id=post_target.target_id,
                postcondition="same_exact_target_focused",
                data={
                    "provider": session.identity.provider,
                    "exact_node_continuity": True,
                    "focused": focused,
                },
                error="browser focus postcondition observed changed target identity",
            )

        if not focused:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=post_observation.captured_at,
                success=False,
                page_id=page_id,
                url_before=before_url,
                url_after=after_url,
                target_id=post_target.target_id,
                postcondition="same_exact_target_focused",
                data={
                    "provider": session.identity.provider,
                    "exact_node_continuity": True,
                    "focused": False,
                },
                error="browser focus postcondition was not observed",
            )

        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=post_observation.captured_at,
            success=True,
            page_id=page_id,
            url_before=before_url,
            url_after=after_url,
            target_id=post_target.target_id,
            postcondition="same_exact_target_focused",
            data={
                "provider": session.identity.provider,
                "exact_node_continuity": True,
                "focused": True,
            },
        )

    def _click(
        self,
        session: _ManagedSession,
        action: BrowserAction,
    ) -> BrowserEffectEvidence:
        if action.target is None:
            raise ManagedBrowserError("browser click requires a current target")
        expected_pressed = action.expected.get("aria_pressed")
        if type(expected_pressed) is not bool:
            raise ManagedBrowserError(
                "generic browser click is not implemented; verified toggle click requires explicit boolean expected aria_pressed postcondition"
            )

        page_id = action.page_id or action.target.page_id or self._default_page_id(session)
        page = self._page(session, page_id)
        binding = self._revalidate_target_binding(session, page_id, action.target)
        before_url = str(getattr(page, "url", "") or "")
        try:
            pressed_before = binding.handle.evaluate(_TARGET_ARIA_PRESSED_SCRIPT)
        except Exception as exc:
            raise ManagedBrowserError(
                f"browser click precondition could not be observed: {type(exc).__name__}: {exc}"
            ) from exc
        if type(pressed_before) is not bool:
            raise ManagedBrowserError(
                "browser click currently requires a target with boolean aria-pressed state"
            )
        if pressed_before is expected_pressed:
            raise ManagedBrowserError(
                "browser click expected aria_pressed state is already observed before dispatch"
            )

        try:
            binding.handle.click()
        except Exception as exc:
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            raise ManagedBrowserError(
                f"managed browser click dispatch failed: {type(exc).__name__}: {exc}"
            ) from exc

        post_captured_at = utc_now()
        try:
            fresh_binding = self._acquire_target_binding(
                session,
                page_id,
                binding.query,
                observed_at=post_captured_at,
            )
        except Exception as exc:
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            raise ManagedBrowserError(
                f"managed browser click target could not be re-observed: {exc}"
            ) from exc

        try:
            same_exact_node = bool(
                binding.handle.evaluate(_EXACT_NODE_EQUAL_SCRIPT, fresh_binding.handle)
            )
        except Exception:
            same_exact_node = False
        try:
            pressed_after = fresh_binding.handle.evaluate(_TARGET_ARIA_PRESSED_SCRIPT)
        except Exception:
            pressed_after = None

        try:
            post_observation = self._capture(
                session,
                page_id,
                target=fresh_binding.target,
                captured_at=post_captured_at,
                target_binding=fresh_binding,
            )
        except Exception:
            self._dispose_target_binding(fresh_binding)
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            raise

        after_url = post_observation.url
        post_target = post_observation.target
        data = {
            "provider": session.identity.provider,
            "exact_node_continuity": same_exact_node,
            "aria_pressed_before": pressed_before,
            "aria_pressed_after": pressed_after,
        }
        if post_target is None:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=post_observation.captured_at,
                success=False,
                page_id=page_id,
                url_before=before_url,
                url_after=after_url,
                target_id=action.target.target_id,
                postcondition="same_exact_target_aria_pressed",
                data=data,
                error="browser click postcondition lost the current target",
            )
        if not same_exact_node:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=post_observation.captured_at,
                success=False,
                page_id=page_id,
                url_before=before_url,
                url_after=after_url,
                target_id=post_target.target_id,
                postcondition="same_exact_target_aria_pressed",
                data=data,
                error="browser click postcondition observed a replaced target node",
            )
        if post_target.target_id != action.target.target_id:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=post_observation.captured_at,
                success=False,
                page_id=page_id,
                url_before=before_url,
                url_after=after_url,
                target_id=post_target.target_id,
                postcondition="same_exact_target_aria_pressed",
                data=data,
                error="browser click postcondition observed changed target identity",
            )
        if type(pressed_after) is not bool or pressed_after is not expected_pressed:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=post_observation.captured_at,
                success=False,
                page_id=page_id,
                url_before=before_url,
                url_after=after_url,
                target_id=post_target.target_id,
                postcondition="same_exact_target_aria_pressed",
                data=data,
                error="browser click postcondition was not observed",
            )

        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=post_observation.captured_at,
            success=True,
            page_id=page_id,
            url_before=before_url,
            url_after=after_url,
            target_id=post_target.target_id,
            postcondition="same_exact_target_aria_pressed",
            data=data,
        )

    def _type_text(
        self,
        session: _ManagedSession,
        action: BrowserAction,
    ) -> BrowserEffectEvidence:
        if action.target is None:
            raise ManagedBrowserError("browser type_text requires a current target")
        if action.target.role != "textbox":
            raise ManagedBrowserError(
                "browser type_text currently requires a textbox target"
            )
        text, expected = self._validate_managed_text(action.args.get("text"))

        page_id = action.page_id or action.target.page_id or self._default_page_id(session)
        page = self._page(session, page_id)
        binding = self._revalidate_target_binding(session, page_id, action.target)
        before_url = str(getattr(page, "url", "") or "")
        before_state = self._read_target_text_state(binding.handle)
        if int(before_state["text_length"]) != 0:
            raise ManagedBrowserError(
                "browser type_text first slice refuses a non-empty current text target"
            )

        try:
            binding.handle.fill(text)
        except Exception as exc:
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            raise ManagedBrowserError(
                f"managed browser type_text dispatch failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            text = ""

        post_captured_at = utc_now()
        try:
            fresh_binding = self._acquire_target_binding(
                session,
                page_id,
                binding.query,
                observed_at=post_captured_at,
            )
        except Exception as exc:
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            raise ManagedBrowserError(
                f"managed browser type_text target could not be re-observed: {exc}"
            ) from exc

        try:
            same_exact_node = bool(
                binding.handle.evaluate(_EXACT_NODE_EQUAL_SCRIPT, fresh_binding.handle)
            )
        except Exception:
            same_exact_node = False
        try:
            after_state = self._read_target_text_state(fresh_binding.handle)
        except Exception as exc:
            self._dispose_target_binding(fresh_binding)
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            raise ManagedBrowserError(
                f"browser type_text postcondition could not be observed: {exc}"
            ) from exc

        try:
            post_observation = self._capture(
                session,
                page_id,
                target=fresh_binding.target,
                captured_at=post_captured_at,
                target_binding=fresh_binding,
            )
        except Exception:
            self._dispose_target_binding(fresh_binding)
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            raise

        after_url = post_observation.url
        post_target = post_observation.target
        data = {
            "provider": session.identity.provider,
            "exact_node_continuity": same_exact_node,
            "input_sent": True,
            "text_length_before": before_state["text_length"],
            "text_sha256_before": before_state["text_sha256"],
            "text_length_after": after_state["text_length"],
            "text_sha256_after": after_state["text_sha256"],
            "expected_text_length": expected["text_length"],
            "expected_text_sha256": expected["text_sha256"],
            "expected_utf16_units": expected["utf16_units"],
        }
        if post_target is None:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=post_observation.captured_at,
                success=False,
                page_id=page_id,
                url_before=before_url,
                url_after=after_url,
                target_id=action.target.target_id,
                postcondition="same_exact_target_text_equals_requested",
                data=data,
                error="browser type_text postcondition lost the current target",
            )
        if not same_exact_node:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=post_observation.captured_at,
                success=False,
                page_id=page_id,
                url_before=before_url,
                url_after=after_url,
                target_id=post_target.target_id,
                postcondition="same_exact_target_text_equals_requested",
                data=data,
                error="browser type_text postcondition observed a replaced target node",
            )
        if post_target.target_id != action.target.target_id:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=post_observation.captured_at,
                success=False,
                page_id=page_id,
                url_before=before_url,
                url_after=after_url,
                target_id=post_target.target_id,
                postcondition="same_exact_target_text_equals_requested",
                data=data,
                error="browser type_text postcondition observed changed target identity",
            )
        if (
            int(after_state["text_length"]) != int(expected["text_length"])
            or str(after_state["text_sha256"]) != str(expected["text_sha256"])
        ):
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=post_observation.captured_at,
                success=False,
                page_id=page_id,
                url_before=before_url,
                url_after=after_url,
                target_id=post_target.target_id,
                postcondition="same_exact_target_text_equals_requested",
                data=data,
                error="browser type_text postcondition was not observed",
            )

        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=post_observation.captured_at,
            success=True,
            page_id=page_id,
            url_before=before_url,
            url_after=after_url,
            target_id=post_target.target_id,
            postcondition="same_exact_target_text_equals_requested",
            data=data,
        )

    @staticmethod
    def _validate_managed_text(value: Any) -> tuple[str, dict[str, Any]]:
        if not isinstance(value, str):
            raise ManagedBrowserError(
                "browser type_text requires an explicit string text argument"
            )
        text = value
        if not text:
            raise ManagedBrowserError("browser type_text text must not be empty")
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in text):
            raise ManagedBrowserError(
                "browser type_text currently accepts text characters only; control keys are unsupported"
            )
        try:
            encoded = text.encode("utf-16-le")
        except UnicodeEncodeError as exc:
            raise ManagedBrowserError(
                "browser type_text contains an invalid Unicode scalar sequence"
            ) from exc
        units = len(encoded) // 2
        if units <= 0 or units > _MAX_MANAGED_TEXT_UTF16_UNITS:
            raise ManagedBrowserError(
                f"browser type_text is limited to {_MAX_MANAGED_TEXT_UTF16_UNITS} UTF-16 code units"
            )
        return text, {
            "text_length": len(text),
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "utf16_units": units,
        }

    @staticmethod
    def _read_target_text_state(handle: Any) -> dict[str, Any]:
        try:
            raw = handle.evaluate(_TARGET_TEXT_STATE_SCRIPT)
        except Exception as exc:
            raise ManagedBrowserError(
                f"managed browser text state provider failed: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise ManagedBrowserError("managed browser text state provider returned invalid evidence")
        if not bool(raw.get("connected")):
            raise ManagedBrowserError("managed browser text target is detached")
        if bool(raw.get("is_password")):
            raise ManagedBrowserError(
                "managed browser type_text first slice refuses password targets"
            )
        if not bool(raw.get("supported")):
            raise ManagedBrowserError(
                "managed browser type_text currently supports only input[type=text] and textarea targets"
            )
        if bool(raw.get("disabled")):
            raise ManagedBrowserError("managed browser type_text target is disabled")
        if bool(raw.get("read_only")):
            raise ManagedBrowserError("managed browser type_text target is read-only")
        value = raw.get("value")
        if not isinstance(value, str):
            raise ManagedBrowserError("managed browser text state value is unavailable")
        if len(value) > _MAX_OBSERVED_TEXT_CHARS:
            raise ManagedBrowserError(
                f"managed browser text state exceeds the {_MAX_OBSERVED_TEXT_CHARS}-character evidence bound"
            )
        state = {
            "text_length": len(value),
            "text_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        }
        value = ""
        return state

    def _capture(
        self,
        session: _ManagedSession,
        page_id: str,
        *,
        target: BrowserTarget | None = None,
        captured_at: str | None = None,
        target_binding: _ManagedTargetBinding | None = None,
    ) -> BrowserObservation:
        if (target is None) != (target_binding is None):
            raise ManagedBrowserError(
                "managed browser observation target and provider binding must move together"
            )
        if target_binding is not None and target_binding.target != target:
            raise ManagedBrowserError(
                "managed browser provider binding does not match target evidence"
            )

        page = self._page(session, page_id)
        url = str(getattr(page, "url", "") or "")
        title = str(page.title() or "")
        try:
            load_state = str(page.evaluate("document.readyState") or "unknown")
        except Exception:
            load_state = "unknown"
        viewport_raw = getattr(page, "viewport_size", None)
        viewport = None
        if isinstance(viewport_raw, dict):
            width = int(viewport_raw.get("width") or 0)
            height = int(viewport_raw.get("height") or 0)
            if width > 0 and height > 0:
                viewport = (width, height)
        observation = BrowserObservation(
            session=session.identity,
            page_id=page_id,
            captured_at=captured_at or utc_now(),
            url=url,
            title=title[:1024],
            load_state=load_state[:64],
            target=target,
            viewport=viewport,
            metadata={
                "provider": session.identity.provider,
                "page_count": len(session.pages),
                "service_workers": "blocked",
                "profile_scope": session.identity.profile_scope,
            },
        )
        self._replace_target_binding(session, page_id, target_binding)
        session.last_observation[page_id] = observation
        return observation

    def _acquire_target_binding(
        self,
        session: _ManagedSession,
        page_id: str,
        query: BrowserTargetQuery,
        *,
        observed_at: str,
    ) -> _ManagedTargetBinding:
        if query.frame_id != "main":
            raise ManagedBrowserError(
                "managed browser target sensing currently supports only the main frame"
            )
        if query.kind is not BrowserTargetQueryKind.DOM_ID:
            raise ManagedBrowserError(
                f"managed browser target query is not implemented: {query.kind.value}"
            )

        page = self._page(session, page_id)
        bundle = None
        count_handle = None
        node_handle = None
        keep_node_handle = False
        try:
            bundle = page.evaluate_handle(_TARGET_HANDLE_BUNDLE_SCRIPT, query.value)
            count_handle = bundle.get_property("count")
            try:
                count = int(count_handle.json_value() or 0)
            except (TypeError, ValueError) as exc:
                raise ManagedBrowserError(
                    "managed browser target provider returned invalid match count"
                ) from exc
            if count == 0:
                raise ManagedBrowserError("managed browser target was not found")
            if count != 1:
                raise ManagedBrowserError("managed browser target is ambiguous")

            node_handle = bundle.get_property("node")
            element = node_handle.as_element()
            if element is None:
                raise ManagedBrowserError(
                    "managed browser target changed while provider evidence was acquired"
                )
            raw = element.evaluate(_TARGET_HANDLE_EVIDENCE_SCRIPT, query.value)
            target = self._target_from_evidence(
                session,
                page_id,
                query,
                raw,
                observed_at=observed_at,
            )
            keep_node_handle = True
            return _ManagedTargetBinding(
                target=target,
                query=query,
                handle=element,
            )
        except ManagedBrowserError:
            raise
        except Exception as exc:
            raise ManagedBrowserError(
                f"failed to observe managed browser target: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            self._best_effort_dispose_handle(count_handle)
            self._best_effort_dispose_handle(bundle)
            if node_handle is not None and not keep_node_handle:
                self._best_effort_dispose_handle(node_handle)

    def _target_from_evidence(
        self,
        session: _ManagedSession,
        page_id: str,
        query: BrowserTargetQuery,
        raw: Any,
        *,
        observed_at: str,
    ) -> BrowserTarget:
        if not isinstance(raw, dict):
            raise ManagedBrowserError("managed browser target provider returned invalid evidence")
        try:
            count = int(raw.get("count") or 0)
        except (TypeError, ValueError) as exc:
            raise ManagedBrowserError(
                "managed browser target provider returned invalid match count"
            ) from exc
        if count == 0:
            raise ManagedBrowserError("managed browser target was not found")
        if count != 1:
            raise ManagedBrowserError("managed browser target is ambiguous")
        if not bool(raw.get("connected")):
            raise ManagedBrowserError("managed browser target is detached")
        if not bool(raw.get("current")):
            raise ManagedBrowserError("managed browser target identity changed while sensing")
        if not bool(raw.get("visible")):
            raise ManagedBrowserError("managed browser target is not visible")

        dom_id = str(raw.get("dom_id") or "")
        if dom_id != query.value:
            raise ManagedBrowserError("managed browser target identity changed while sensing")
        is_password = bool(raw.get("is_password"))
        if is_password and not session.permission.allow_sensitive_fields:
            raise ManagedBrowserError(
                "managed browser sensitive target requires explicit sensitive-field permission"
            )

        tag = str(raw.get("tag") or "")[:32]
        role = str(raw.get("role") or "")[:64]
        name = "" if is_password else str(raw.get("name") or "")[:160]
        input_type = str(raw.get("input_type") or "")[:32]
        page = self._page(session, page_id)
        current_url = str(getattr(page, "url", "") or "")
        identity_material = "\x1f".join(
            (
                session.identity.session_id,
                page_id,
                query.frame_id,
                current_url,
                dom_id,
                tag,
                role,
                input_type,
            )
        )
        target_id = "dom-" + hashlib.sha256(
            identity_material.encode("utf-8")
        ).hexdigest()[:24]

        return BrowserTarget(
            session_id=session.identity.session_id,
            page_id=page_id,
            kind=BrowserTargetKind.ELEMENT,
            target_id=target_id,
            observed_at=observed_at,
            url=current_url,
            frame_id=query.frame_id,
            role=role,
            name=name,
            selector_hint=f"dom_id:{dom_id}",
        )

    def _revalidate_target_binding(
        self,
        session: _ManagedSession,
        page_id: str,
        target: BrowserTarget,
    ) -> _ManagedTargetBinding:
        binding = session.target_bindings.get(page_id)
        if binding is None:
            raise ManagedBrowserError(
                "browser target action requires provider evidence for the current target observation"
            )
        if binding.target != target:
            raise ManagedBrowserError(
                "browser target provider evidence does not match the current action target"
            )
        try:
            raw = binding.handle.evaluate(
                _TARGET_HANDLE_EVIDENCE_SCRIPT,
                binding.query.value,
            )
            current = self._target_from_evidence(
                session,
                page_id,
                binding.query,
                raw,
                observed_at=target.observed_at,
            )
        except Exception as exc:
            raise ManagedBrowserError(
                f"browser target changed before dispatch: {exc}"
            ) from exc
        if current.target_id != target.target_id:
            raise ManagedBrowserError("browser target changed before dispatch")
        return binding

    def _validate_authority(
        self,
        session: _ManagedSession,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> None:
        page_id = action.page_id or authority.page_id or self._default_page_id(session)
        observed = session.last_observation.get(page_id)
        if observed is None:
            raise ManagedBrowserError("browser action requires a current page observation")
        try:
            authority.validate_current(action, observed, session.permission)
        except ValueError as exc:
            raise ManagedBrowserError(str(exc)) from exc

    def _refresh_page_observation_after_failed_mutation(
        self,
        session: _ManagedSession,
        page_id: str,
    ) -> None:
        self._invalidate_target_binding(session, page_id)
        try:
            self._capture(session, page_id)
        except Exception:
            session.last_observation.pop(page_id, None)

    def _replace_target_binding(
        self,
        session: _ManagedSession,
        page_id: str,
        binding: _ManagedTargetBinding | None,
    ) -> None:
        previous = session.target_bindings.pop(page_id, None)
        if previous is not None and (binding is None or previous.handle is not binding.handle):
            self._dispose_target_binding(previous)
        if binding is not None:
            session.target_bindings[page_id] = binding

    def _invalidate_target_binding(self, session: _ManagedSession, page_id: str) -> None:
        self._replace_target_binding(session, page_id, None)

    def _dispose_all_target_bindings(self, session: _ManagedSession) -> None:
        for binding in tuple(session.target_bindings.values()):
            self._dispose_target_binding(binding)
        session.target_bindings.clear()

    def _dispose_target_binding(self, binding: _ManagedTargetBinding) -> None:
        self._best_effort_dispose_handle(binding.handle)

    def _install_network_boundary(self, session: _ManagedSession) -> None:
        def handle_route(route: Any) -> None:
            url = str(route.request.url or "")
            if self._url_allowed(url, session.permission):
                route.continue_()
            else:
                route.abort(error_code="blockedbyclient")

        def handle_websocket(ws: Any) -> None:
            if self._websocket_url_allowed(str(ws.url or ""), session.permission):
                ws.connect_to_server()
            else:
                ws.close(code=1008, reason="blocked by ZN browser network policy")

        session.context.route("**/*", handle_route)
        route_web_socket = getattr(session.context, "route_web_socket", None)
        if callable(route_web_socket):
            route_web_socket("**/*", handle_websocket)

    def _require_url_allowed(
        self,
        url: str,
        permission: BrowserPermissionContext,
    ) -> None:
        if not self._url_allowed(url, permission):
            raise ManagedBrowserError("browser URL is outside the permitted network boundary")

    def _url_allowed(self, url: str, permission: BrowserPermissionContext) -> bool:
        text = str(url or "").strip()
        if text == "about:blank":
            return True
        if not permission.allows_origin(text):
            return False
        try:
            return bool(
                self._url_checker(
                    text,
                    allow_private=permission.allow_private_network,
                )
            )
        except Exception:
            return False

    def _websocket_url_allowed(
        self,
        url: str,
        permission: BrowserPermissionContext,
    ) -> bool:
        http_url = _websocket_to_http_url(url)
        return bool(http_url and self._url_allowed(http_url, permission))

    def _register_page(self, session: _ManagedSession, page: Any) -> str:
        for existing_id, existing_page in session.pages.items():
            if existing_page is page:
                return existing_id
        page_id = f"page-{len(session.pages) + 1}-{id(page):x}"
        session.pages[page_id] = page
        return page_id

    def _default_page_id(self, session: _ManagedSession) -> str:
        if not session.pages:
            raise ManagedBrowserError("managed browser session has no page")
        return next(iter(session.pages))

    def _page(self, session: _ManagedSession, page_id: str) -> Any:
        page = session.pages.get(str(page_id or ""))
        if page is None:
            raise ManagedBrowserError("unknown managed browser page")
        if bool(getattr(page, "is_closed", lambda: False)()):
            raise ManagedBrowserError("managed browser page is closed")
        return page

    def _session(self, session_id: str) -> _ManagedSession:
        session = self._sessions.get(str(session_id or "").strip())
        if session is None:
            raise ManagedBrowserError("unknown managed browser session")
        return session

    @staticmethod
    def _failure(action: BrowserAction, *, error: str) -> BrowserEffectEvidence:
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=False,
            page_id=action.page_id,
            target_id=action.target.target_id if action.target is not None else "",
            error=str(error or "managed browser action failed")[:2000],
        )

    @staticmethod
    def _default_playwright_factory() -> Any:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ManagedBrowserUnavailable(
                "Playwright is not installed; install znagent[browser]"
            ) from exc
        return sync_playwright()

    @staticmethod
    def _looks_like_missing_playwright(exc: Exception) -> bool:
        text = f"{type(exc).__name__}: {exc}".lower()
        return "executable doesn't exist" in text or "playwright" in text and "install" in text

    @staticmethod
    def _best_effort_dispose_handle(handle: Any) -> None:
        if handle is None:
            return
        try:
            handle.dispose()
        except Exception:
            pass

    @staticmethod
    def _best_effort_close(context: Any, browser: Any, playwright: Any) -> None:
        for resource, method in (
            (context, "close"),
            (browser, "close"),
            (playwright, "stop"),
        ):
            if resource is None:
                continue
            try:
                getattr(resource, method)()
            except Exception:
                pass


def _websocket_to_http_url(value: str) -> str:
    try:
        parsed = urlsplit(str(value or "").strip())
    except (TypeError, ValueError):
        return ""
    scheme = str(parsed.scheme or "").lower()
    if scheme not in {"ws", "wss"}:
        return ""
    replacement = "http" if scheme == "ws" else "https"
    return urlunsplit((replacement, parsed.netloc, parsed.path, parsed.query, parsed.fragment))
