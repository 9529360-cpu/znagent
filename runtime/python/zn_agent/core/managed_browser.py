from __future__ import annotations

"""Local managed-browser adapter behind ZN-owned browser contracts.

Playwright is an implementation resource, not the browser control plane. The
adapter defaults to an ephemeral Chromium context, blocks service workers so
request routing remains authoritative, checks every HTTP(S) request and
WebSocket endpoint through ZN URL safety, and returns resident-owned effect
evidence after actions instead of treating provider dispatch as completion.
"""

import hashlib
import logging
import math
import os
import time
from collections import deque
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
    BrowserTargetStaleError,
    BrowserTargetQueryKind,
)
from .managed_browser_select import perform_select_option
from .models import utc_now
from .privacy_choke import redact_for_egress
from .url_safety import is_safe_url


_LOG = logging.getLogger(__name__)


# Managed session idle TTL cleanup (P2-10; ZN.md §4.5 "bounded persistence and
# cleanup for managed sessions"). A managed session whose last activity is
# older than the TTL is closed automatically by an opportunistic sweep. The
# sweep runs on the managed entry points (throttled) and is also callable
# directly through close_idle_sessions(). It only ever touches sessions owned
# by this managed adapter; user-browser planes are never involved.
_DEFAULT_SESSION_IDLE_TTL_SECONDS = 30 * 60
_SESSION_IDLE_TTL_ENV_VAR = "ZN_MANAGED_BROWSER_SESSION_IDLE_TTL_SECONDS"
_AUTO_SWEEP_MIN_INTERVAL_SECONDS = 60.0
# Bounded in-memory journal of managed session lifecycle events ("explicit" and
# "idle_ttl" closures). Oldest entries are dropped first so the journal itself
# stays bounded; read it through session_events().
_MAX_SESSION_EVENTS = 500


def _resolve_session_idle_ttl(value: float | None) -> float:
    """Resolve the idle TTL in seconds; zero or negative disables the sweep."""
    if value is not None:
        parsed = _parse_nonnegative_float(value)
        if parsed is not None:
            return parsed
        return float(_DEFAULT_SESSION_IDLE_TTL_SECONDS)
    parsed = _parse_nonnegative_float(
        str(os.environ.get(_SESSION_IDLE_TTL_ENV_VAR) or "").strip()
    )
    if parsed is not None:
        return parsed
    return float(_DEFAULT_SESSION_IDLE_TTL_SECONDS)


def _parse_nonnegative_float(value: Any) -> float | None:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


class ManagedBrowserError(RuntimeError):
    pass


class ManagedBrowserUnavailable(ManagedBrowserError):
    pass


UrlChecker = Callable[..., bool]

_MAX_MANAGED_TEXT_UTF16_UNITS = 512
_MAX_OBSERVED_TEXT_CHARS = 4096

# Console / page error observation (P2-9). Bounded per page so a chatty page
# cannot grow session state without limit; each entry's text is truncated
# and run through the privacy choke single point before it is stored.
_MAX_CONSOLE_ERRORS_PER_PAGE = 20
_MAX_CONSOLE_ERROR_TEXT_CHARS = 1024
_MAX_CONSOLE_ERROR_RECENT_IN_OBSERVATION = 5

# Network observation (Q2). Only failed requests (``requestfailed``) and
# error responses (status >= 400) are recorded; successful traffic is never
# stored. Query strings and fragments are stripped from stored URLs before
# the privacy choke single point runs, mirroring the console-error path.
_MAX_NETWORK_FAILURES_PER_PAGE = 20
_MAX_NETWORK_URL_CHARS = 512
_MAX_NETWORK_ERROR_TEXT_CHARS = 256
_MAX_NETWORK_FAILURES_RECENT_IN_OBSERVATION = 5
_NETWORK_ERROR_STATUS_MIN = 400

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

_TARGET_CHECKED_STATE_SCRIPT = r"""
(element) => {
  const connected = Boolean(element && element.isConnected);
  const tag = String(element && element.tagName || "").toLowerCase();
  const inputType = String(element && element.getAttribute("type") || "")
    .trim()
    .toLowerCase();
  const supported = Boolean(
    tag === "input" && (inputType === "checkbox" || inputType === "radio")
  );
  return {
    connected,
    supported,
    disabled: Boolean(element && element.disabled),
    checked: connected && supported ? Boolean(element.checked) : null,
  };
}
"""

_SLIDER_VALUE_SCRIPT = r"""
(element) => {
  const connected = Boolean(element && element.isConnected);
  const tag = String(element && element.tagName || "").toLowerCase();
  const inputType = String(element && element.getAttribute("type") || "")
    .trim()
    .toLowerCase();
  const supported = Boolean(tag === "input" && inputType === "range");
  const attrNum = (name, dflt) => {
    const raw = element ? element.getAttribute(name) : null;
    const n = raw === null || raw === "" ? NaN : Number(raw);
    return Number.isFinite(n) ? n : dflt;
  };
  const sliderMin = attrNum("min", 0);
  const sliderMax = attrNum("max", 100);
  const sliderStep = attrNum("step", 1);
  const current = element ? Number(element.value) : NaN;
  const sliderValue = Number.isFinite(current)
    ? current
    : (sliderMin + sliderMax) / 2;
  return {
    connected,
    supported,
    disabled: Boolean(element && element.disabled),
    native_slider: supported,
    slider_min: sliderMin,
    slider_max: sliderMax,
    slider_step: sliderStep,
    slider_value: Number.isFinite(sliderValue) ? sliderValue : null,
  };
}
"""

_SLIDER_SET_VALUE_SCRIPT = r"""
(element, requested) => {
  if (!element || !element.isConnected) {
    return { slider_set_ok: false, slider_set_reason: "detached" };
  }
  const tag = String(element.tagName || "").toLowerCase();
  const inputType = String(element.getAttribute("type") || "")
    .trim()
    .toLowerCase();
  const nativeSlider = Boolean(tag === "input" && inputType === "range");
  if (!nativeSlider) {
    return { slider_set_ok: false, slider_set_reason: "unsupported" };
  }
  const value = Number(requested);
  if (!Number.isFinite(value)) {
    return { slider_set_ok: false, slider_set_reason: "not_a_number" };
  }
  element.value = String(value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
  return { slider_set_ok: true, slider_assigned: element.value };
}
"""

_SLIDER_VALUE_EPSILON = 1e-9


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
    default_page_id: str = ""
    next_page_sequence: int = 1
    last_observation: dict[str, BrowserObservation] = field(default_factory=dict)
    target_bindings: dict[str, _ManagedTargetBinding] = field(default_factory=dict)
    # JavaScript dialog state, keyed by page_id. Each entry is a dict with:
    #   "live": the provider dialog object while a JS dialog is open, else None
    #   "snapshot": {"type","message","default_value","opened_at","auto_dismissed","handled"}
    #   "auto_dismiss_count": number of beforeunload dialogs auto-dismissed on the page
    #   "last_auto_dismissed": snapshot of the most recent auto-dismissed dialog
    dialog_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Console / page error state, keyed by page_id. Each entry is a dict with:
    #   "entries": bounded list (oldest dropped first) of
    #     {"kind","type","text","captured_at"}; text is redacted + truncated
    #   "total_count": number of console errors / pageerrors seen on the page
    #   "dropped_count": entries dropped because the per-page bound was hit
    console_error_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Network failure state, keyed by page_id. Each entry is a dict with:
    #   "entries": bounded list (oldest dropped first) of
    #     {"kind","method","url","status","error","resource_type",
    #      "captured_at"}; url is query/fragment-stripped, redacted and
    #     truncated. Only failed requests and error responses are recorded.
    #   "total_count": number of network failures seen on the page
    #   "dropped_count": entries dropped because the per-page bound was hit
    network_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Monotonic timestamp of the last observe / observe_target / act on this
    # session (set at open). Drives the idle TTL sweep. Monotonic, not wall
    # clock, so a clock adjustment can neither keep a leaked session alive nor
    # kill a live one.
    last_activity_monotonic: float = field(default_factory=time.monotonic)


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
        session_idle_ttl_seconds: float | None = None,
        session_event_callback: Callable[[dict[str, Any]], None] | None = None,
    ):
        self._playwright_factory = playwright_factory
        self._url_checker = url_checker
        self.navigation_timeout_ms = max(1_000, int(navigation_timeout_ms))
        self.action_timeout_ms = max(1_000, int(action_timeout_ms))
        # Idle TTL (seconds) after which an unused managed session is closed
        # automatically. None resolves to the
        # ZN_MANAGED_BROWSER_SESSION_IDLE_TTL_SECONDS env var, falling back to
        # 30 minutes. Zero or negative disables automatic idle cleanup.
        self.session_idle_ttl_seconds = _resolve_session_idle_ttl(
            session_idle_ttl_seconds
        )
        # Optional sink for session lifecycle events (TTL closes included);
        # never allowed to break the adapter if it raises.
        self._session_event_callback = session_event_callback
        self._sessions: dict[str, _ManagedSession] = {}
        self._session_events: deque[dict[str, Any]] = deque(
            maxlen=_MAX_SESSION_EVENTS
        )
        self._last_auto_sweep_monotonic = 0.0

    def open_session(
        self,
        *,
        permission: BrowserPermissionContext | None = None,
        headless: bool = True,
    ) -> BrowserSessionIdentity:
        # Reclaim leaked sessions before launching a new browser.
        self._maybe_auto_sweep_idle_sessions()
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
        self._close_session_resources(session, reason="explicit")

    def close_idle_sessions(
        self,
        *,
        now: float | None = None,
        ttl_seconds: float | None = None,
    ) -> list[str]:
        """Close managed sessions idle longer than the TTL.

        Returns the closed session ids in sweep order. Active sessions are
        untouched; a disabled TTL (<= 0) closes nothing. Every auto-close is
        written to the session event journal.
        """
        ttl = (
            self.session_idle_ttl_seconds
            if ttl_seconds is None
            else _resolve_session_idle_ttl(ttl_seconds)
        )
        if ttl <= 0:
            return []
        reference = time.monotonic() if now is None else float(now)
        closed: list[str] = []
        for session_id, session in tuple(self._sessions.items()):
            idle_seconds = reference - float(session.last_activity_monotonic)
            if idle_seconds > ttl:
                self._sessions.pop(session_id, None)
                self._close_session_resources(
                    session,
                    reason="idle_ttl",
                    idle_seconds=idle_seconds,
                    ttl_seconds=ttl,
                )
                closed.append(session_id)
        return closed

    def session_events(self) -> tuple[dict[str, Any], ...]:
        """Bounded journal of managed session lifecycle events, oldest first."""
        return tuple(dict(entry) for entry in self._session_events)

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
            if action.kind is BrowserActionKind.SELECT_OPTION:
                return perform_select_option(self, session, action)
            if action.kind is BrowserActionKind.CHECK:
                return self._check(session, action)
            if action.kind is BrowserActionKind.UNCHECK:
                return self._uncheck(session, action)
            if action.kind is BrowserActionKind.SET_SLIDER_VALUE:
                return self._set_slider_value(session, action)
            if action.kind is BrowserActionKind.DIALOG_ACCEPT:
                return self._dialog_respond(session, action, accept=True)
            if action.kind is BrowserActionKind.DIALOG_DISMISS:
                return self._dialog_respond(session, action, accept=False)
            return self._failure(
                action,
                error=f"managed browser action is not implemented yet: {action.kind.value}",
            )
        except BrowserTargetStaleError as exc:
            return self._failure(
                action,
                error=f"{type(exc).__name__}: {exc}",
                data={
                    "dispatch_state": "not_started",
                    "requires_fresh_resense": True,
                },
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
        try:
            page.goto(raw_url, wait_until="domcontentloaded")
        except Exception as exc:
            # Navigation failures usually surface as network errors
            # (DNS, refused, timeout); the observer already recorded them,
            # so attach the bounded summary to the failure evidence.
            return self._failure(
                action,
                error=f"browser navigation failed: {type(exc).__name__}: {exc}",
                data={
                    "url_before": before,
                    "url": raw_url,
                    "network": self._network_snapshot(session, page_id),
                },
            )
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

    def _check(
        self,
        session: _ManagedSession,
        action: BrowserAction,
    ) -> BrowserEffectEvidence:
        if action.target is None:
            raise ManagedBrowserError("browser check requires a current target")
        if action.target.role not in ("checkbox", "radio"):
            raise ManagedBrowserError(
                "browser check currently requires a native checkbox or radio target"
            )

        page_id = action.page_id or action.target.page_id or self._default_page_id(session)
        page = self._page(session, page_id)
        binding = self._revalidate_target_binding(session, page_id, action.target)
        before_url = str(getattr(page, "url", "") or "")
        checked_before = self._read_target_checked_state(binding.handle)
        if checked_before:
            raise ManagedBrowserError(
                "browser check target is already checked before dispatch"
            )

        try:
            binding.handle.check()
        except Exception as exc:
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            raise ManagedBrowserError(
                f"managed browser check dispatch failed: {type(exc).__name__}: {exc}"
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
                f"managed browser check target could not be re-observed: {exc}"
            ) from exc

        try:
            same_exact_node = bool(
                binding.handle.evaluate(_EXACT_NODE_EQUAL_SCRIPT, fresh_binding.handle)
            )
        except Exception:
            same_exact_node = False
        try:
            checked_after = self._read_target_checked_state(fresh_binding.handle)
        except Exception as exc:
            self._dispose_target_binding(fresh_binding)
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            raise ManagedBrowserError(
                f"browser check postcondition could not be observed: {exc}"
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
            "checked_before": checked_before,
            "checked_after": checked_after,
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
                postcondition="same_exact_target_checked",
                data=data,
                error="browser check postcondition lost the current target",
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
                postcondition="same_exact_target_checked",
                data=data,
                error="browser check postcondition observed a replaced target node",
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
                postcondition="same_exact_target_checked",
                data=data,
                error="browser check postcondition observed changed target identity",
            )
        if not checked_after:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=post_observation.captured_at,
                success=False,
                page_id=page_id,
                url_before=before_url,
                url_after=after_url,
                target_id=post_target.target_id,
                postcondition="same_exact_target_checked",
                data=data,
                error="browser check postcondition was not observed",
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
            postcondition="same_exact_target_checked",
            data=data,
        )

    def _uncheck(
        self,
        session: _ManagedSession,
        action: BrowserAction,
    ) -> BrowserEffectEvidence:
        if action.target is None:
            raise ManagedBrowserError("browser uncheck requires a current target")
        if action.target.role != "checkbox":
            raise ManagedBrowserError(
                "browser uncheck currently requires a native checkbox target"
            )

        page_id = action.page_id or action.target.page_id or self._default_page_id(session)
        page = self._page(session, page_id)
        binding = self._revalidate_target_binding(session, page_id, action.target)
        before_url = str(getattr(page, "url", "") or "")
        checked_before = self._read_target_checked_state(binding.handle)
        if not checked_before:
            raise ManagedBrowserError(
                "browser uncheck target is already unchecked before dispatch"
            )

        try:
            binding.handle.uncheck()
        except Exception as exc:
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            raise ManagedBrowserError(
                f"managed browser uncheck dispatch failed: {type(exc).__name__}: {exc}"
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
                f"managed browser uncheck target could not be re-observed: {exc}"
            ) from exc

        try:
            same_exact_node = bool(
                binding.handle.evaluate(_EXACT_NODE_EQUAL_SCRIPT, fresh_binding.handle)
            )
        except Exception:
            same_exact_node = False
        try:
            checked_after = self._read_target_checked_state(fresh_binding.handle)
        except Exception as exc:
            self._dispose_target_binding(fresh_binding)
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            raise ManagedBrowserError(
                f"browser uncheck postcondition could not be observed: {exc}"
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
            "checked_before": checked_before,
            "checked_after": checked_after,
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
                postcondition="same_exact_target_unchecked",
                data=data,
                error="browser uncheck postcondition lost the current target",
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
                postcondition="same_exact_target_unchecked",
                data=data,
                error="browser uncheck postcondition observed a replaced target node",
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
                postcondition="same_exact_target_unchecked",
                data=data,
                error="browser uncheck postcondition observed changed target identity",
            )
        if checked_after:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=post_observation.captured_at,
                success=False,
                page_id=page_id,
                url_before=before_url,
                url_after=after_url,
                target_id=post_target.target_id,
                postcondition="same_exact_target_unchecked",
                data=data,
                error="browser uncheck postcondition was not observed",
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
            postcondition="same_exact_target_unchecked",
            data=data,
        )

    def _set_slider_value(
        self,
        session: _ManagedSession,
        action: BrowserAction,
    ) -> BrowserEffectEvidence:
        """Set a native range slider to a requested value, then read it back.

        The only slider mutation ZN offers. The requested value is clamped
        into the observed [min, max] bounds before dispatch; step alignment
        stays the caller's responsibility. The postcondition requires the
        read-back value to match the clamped request on the same exact DOM
        node -- anything else is reported as a failed postcondition, never
        silently accepted. Drags, keyboard nudges, or any other slider
        interaction are explicitly not offered.
        """
        if action.target is None:
            raise ManagedBrowserError("browser set_slider_value requires a current target")
        if action.target.role != "slider":
            raise ManagedBrowserError(
                "browser set_slider_value currently requires a native slider target"
            )
        requested = self._validate_slider_value_arg(action.args.get("value"))

        page_id = action.page_id or action.target.page_id or self._default_page_id(session)
        page = self._page(session, page_id)
        binding = self._revalidate_target_binding(session, page_id, action.target)
        before_url = str(getattr(page, "url", "") or "")
        before_state = self._read_target_slider_state(binding.handle)
        slider_min = before_state["min"]
        slider_max = before_state["max"]
        lo, hi = (slider_min, slider_max) if slider_min <= slider_max else (slider_max, slider_min)
        clamped = min(max(requested, lo), hi)
        if math.isclose(
            before_state["value"], clamped, rel_tol=0.0, abs_tol=_SLIDER_VALUE_EPSILON
        ):
            raise ManagedBrowserError(
                "browser set_slider_value target is already at the requested value before dispatch"
            )

        try:
            dispatch_raw = binding.handle.evaluate(_SLIDER_SET_VALUE_SCRIPT, clamped)
        except Exception as exc:
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            raise ManagedBrowserError(
                f"managed browser set_slider_value dispatch failed: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(dispatch_raw, dict) or not bool(
            dispatch_raw.get("slider_set_ok")
        ):
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            raise ManagedBrowserError(
                "managed browser set_slider_value dispatch was not acknowledged by the page: "
                f"{dispatch_raw.get('slider_set_reason') if isinstance(dispatch_raw, dict) else '?'}"
            )

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
                f"managed browser set_slider_value target could not be re-observed: {exc}"
            ) from exc

        try:
            same_exact_node = bool(
                binding.handle.evaluate(_EXACT_NODE_EQUAL_SCRIPT, fresh_binding.handle)
            )
        except Exception:
            same_exact_node = False
        try:
            after_state = self._read_target_slider_state(fresh_binding.handle)
        except Exception as exc:
            self._dispose_target_binding(fresh_binding)
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            raise ManagedBrowserError(
                f"browser set_slider_value postcondition could not be observed: {exc}"
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
            "value_before": before_state["value"],
            "value_requested": clamped,
            "value_after": after_state["value"],
            "slider_min": slider_min,
            "slider_max": slider_max,
            "slider_step": before_state["step"],
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
                postcondition="same_exact_target_slider_value_set",
                data=data,
                error="browser set_slider_value postcondition lost the current target",
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
                postcondition="same_exact_target_slider_value_set",
                data=data,
                error="browser set_slider_value postcondition observed a replaced target node",
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
                postcondition="same_exact_target_slider_value_set",
                data=data,
                error="browser set_slider_value postcondition observed changed target identity",
            )
        if not math.isclose(
            after_state["value"], clamped, rel_tol=0.0, abs_tol=_SLIDER_VALUE_EPSILON
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
                postcondition="same_exact_target_slider_value_set",
                data=data,
                error="browser set_slider_value postcondition was not observed",
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
            postcondition="same_exact_target_slider_value_set",
            data=data,
        )

    def _dialog_respond(
        self,
        session: _ManagedSession,
        action: BrowserAction,
        *,
        accept: bool,
    ) -> BrowserEffectEvidence:
        """Explicitly accept or dismiss an open JavaScript dialog.

        Safety lines: prompt text is never auto-filled (an explicit prompt_text
        argument is rejected, not silently used); beforeunload dialogs are
        auto-dismissed on arrival so navigation can never hang waiting on them.
        """
        if action.args.get("prompt_text") is not None:
            return self._failure(
                action,
                error="managed browser never auto-fills prompt text; "
                "dialog accept/dismiss takes no text argument",
                data={"dispatch_state": "not_started", "requires_fresh_resense": True},
            )
        page_id = action.page_id or self._default_page_id(session)
        page = self._page(session, page_id)
        entry = session.dialog_state.get(page_id)
        dialog = entry.get("live") if entry else None
        if dialog is None:
            return self._failure(
                action,
                error="no JavaScript dialog is open on this page",
                data={"dispatch_state": "not_started", "requires_fresh_resense": True},
            )
        snapshot = dict(entry.get("snapshot") or {})
        dialog_type = str(snapshot.get("type") or "unknown")
        url_before = str(getattr(page, "url", "") or "")
        prompt_value_used: str | None = None
        try:
            if accept:
                if dialog_type == "prompt":
                    # Playwright accepts a prompt with its default value when no
                    # prompt text is passed; we never inject our own text.
                    dialog.accept()
                    prompt_value_used = "default"
                else:
                    dialog.accept()
            else:
                dialog.dismiss()
        except Exception as exc:
            entry["live"] = None
            entry["snapshot"] = None
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            return self._failure(
                action,
                error=f"managed browser dialog respond dispatch failed: {type(exc).__name__}: {exc}",
            )
        entry["live"] = None
        handled = "accept" if accept else "dismiss"
        snapshot["handled"] = handled
        snapshot["handled_at"] = utc_now()
        entry["snapshot"] = None

        post_observation = self._capture(session, page_id)
        after_url = post_observation.url
        dialog_after = post_observation.metadata.get("dialog")
        postcondition = "dialog_closed" if accept else "dialog_dismissed"
        data: dict[str, Any] = {
            "provider": session.identity.provider,
            "dialog_type": dialog_type,
            "dialog_handled": handled,
        }
        if snapshot.get("message"):
            data["dialog_message"] = snapshot["message"]
        if prompt_value_used is not None:
            data["prompt_value_used"] = prompt_value_used
        data["url_after"] = after_url
        if dialog_after is not None:
            # A new dialog opened while handling the previous one; it is now
            # recorded in dialog_state and observable through the next capture.
            data["dialog_reopened"] = True
            data["reopened_dialog_type"] = str(dialog_after.get("type") or "unknown")
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=post_observation.captured_at,
            success=True,
            page_id=page_id,
            url_before=url_before,
            url_after=after_url,
            target_id=action.target.target_id if action.target is not None else "",
            postcondition=postcondition,
            data=data,
        )

    def _install_dialog_observer(
        self,
        session: _ManagedSession,
        page_id: str,
        page: Any,
    ) -> None:
        """Record JavaScript dialogs opened on a page so they stay observable.

        beforeunload dialogs are dismissed immediately on arrival: they would
        otherwise block navigation indefinitely. Everything else is recorded and
        handled only through explicit dialog_accept/dialog_dismiss actions.
        """
        entry = session.dialog_state.setdefault(
            page_id,
            {
                "live": None,
                "snapshot": None,
                "auto_dismiss_count": 0,
                "last_auto_dismissed": None,
            },
        )

        def handle_dialog(dialog: Any) -> None:
            snapshot = {
                "type": str(getattr(dialog, "type", "") or "unknown"),
                "message": str(getattr(dialog, "message", "") or "")[:1024],
                "default_value": str(getattr(dialog, "default_value", "") or "")[:1024],
                "opened_at": utc_now(),
                "auto_dismissed": False,
            }
            if snapshot["type"] == "beforeunload":
                # Never hang on navigation-blocking dialogs: dismiss cancels the
                # pending navigation and keeps the page usable.
                try:
                    dialog.dismiss()
                except Exception:
                    pass
                snapshot["auto_dismissed"] = True
                snapshot["handled"] = "dismiss"
                snapshot["handled_at"] = utc_now()
                entry["live"] = None
                entry["snapshot"] = None
                entry["auto_dismiss_count"] = int(entry.get("auto_dismiss_count") or 0) + 1
                entry["last_auto_dismissed"] = snapshot
                return
            entry["live"] = dialog
            entry["snapshot"] = snapshot

        on = getattr(page, "on", None)
        if callable(on):
            try:
                on("dialog", handle_dialog)
            except Exception:
                pass

    @staticmethod
    def _open_dialog_snapshot(session: _ManagedSession, page_id: str) -> dict[str, Any] | None:
        entry = session.dialog_state.get(page_id)
        if not entry or entry.get("live") is None:
            return None
        snapshot = dict(entry.get("snapshot") or {})
        return {
            "type": str(snapshot.get("type") or "unknown"),
            "message": str(snapshot.get("message") or "")[:1024],
            "default_value": str(snapshot.get("default_value") or "")[:1024],
            "opened_at": str(snapshot.get("opened_at") or ""),
        }

    def _install_console_error_observer(
        self,
        session: _ManagedSession,
        page_id: str,
        page: Any,
    ) -> None:
        """Record console errors and uncaught page exceptions (pageerror).

        Observation only: this never changes the page or adds new action
        kinds. Only ``console`` messages with type ``error`` and ``pageerror``
        events are recorded; warnings and info are ignored. Each entry is
        redacted through the privacy choke single point and truncated before
        storage, and the per-page list is bounded (oldest entries are
        dropped first, with a counter). Handlers must never propagate into
        the provider: every callback is fail-closed and logs instead.
        """
        state = session.console_error_state.setdefault(
            page_id,
            {"entries": [], "total_count": 0, "dropped_count": 0},
        )

        def record_error(kind: str, error_type: str, raw_text: Any) -> None:
            try:
                scrubbed = redact_for_egress(str(raw_text or ""))
                text = str(scrubbed)[:_MAX_CONSOLE_ERROR_TEXT_CHARS]
                entries = state.setdefault("entries", [])
                entries.append(
                    {
                        "kind": kind,
                        "type": str(error_type or "unknown"),
                        "text": text,
                        "captured_at": utc_now(),
                    }
                )
                state["total_count"] = int(state.get("total_count") or 0) + 1
                while len(entries) > _MAX_CONSOLE_ERRORS_PER_PAGE:
                    entries.pop(0)
                    state["dropped_count"] = int(state.get("dropped_count") or 0) + 1
            except Exception:
                _LOG.warning(
                    "managed browser console error record failed for page %s",
                    page_id,
                    exc_info=True,
                )

        def handle_console(message: Any) -> None:
            try:
                message_type = str(getattr(message, "type", "") or "unknown")
                if message_type.lower() != "error":
                    return
                text_getter = getattr(message, "text", None)
                text = (
                    text_getter()
                    if callable(text_getter)
                    else str(text_getter or "")
                )
                record_error("console", message_type, text)
            except Exception:
                _LOG.warning(
                    "managed browser console event handler failed for page %s",
                    page_id,
                    exc_info=True,
                )

        def handle_pageerror(error: Any) -> None:
            try:
                stack = getattr(error, "stack", None)
                text = stack if isinstance(stack, str) and stack else str(error)
                record_error("pageerror", "pageerror", text)
            except Exception:
                _LOG.warning(
                    "managed browser pageerror handler failed for page %s",
                    page_id,
                    exc_info=True,
                )

        on = getattr(page, "on", None)
        if not callable(on):
            _LOG.warning(
                "managed browser page has no event subscription; "
                "console error observation disabled for page %s",
                page_id,
            )
            return
        for event, handler in (
            ("console", handle_console),
            ("pageerror", handle_pageerror),
        ):
            try:
                on(event, handler)
            except Exception:
                _LOG.warning(
                    "managed browser could not subscribe %s events on page %s",
                    event,
                    page_id,
                    exc_info=True,
                )

    @staticmethod
    def _console_error_snapshot(
        session: _ManagedSession, page_id: str
    ) -> dict[str, Any]:
        """Bounded error summary for one page's observation metadata."""
        state = session.console_error_state.get(page_id) or {}
        entries = list(state.get("entries") or [])
        return {
            "total_count": int(state.get("total_count") or 0),
            "kept_count": len(entries),
            "dropped_count": int(state.get("dropped_count") or 0),
            "recent": [
                dict(entry)
                for entry in entries[-_MAX_CONSOLE_ERROR_RECENT_IN_OBSERVATION:]
            ],
        }

    @staticmethod
    def _sanitize_network_url(raw_url: Any) -> str:
        """Desensitize a request URL for the network observation.

        Query strings and fragments are stripped entirely (they carry no
        debugging value and routinely contain tokens/keys); the remainder
        goes through the privacy choke single point -- the same mechanism
        #570 used for console errors -- to scrub tokens embedded in the
        path or userinfo. Never raises: fail closed to an empty URL.
        """
        try:
            text = str(raw_url or "").strip()
            if not text:
                return ""
            parts = urlsplit(text)
            stripped = parts._replace(query="", fragment="")
            url = stripped.geturl()
            scrubbed = str(redact_for_egress(url))
            return scrubbed[:_MAX_NETWORK_URL_CHARS]
        except Exception:
            _LOG.warning(
                "managed browser network URL sanitizer failed; failing closed to empty URL",
                exc_info=True,
            )
            return ""

    def _install_network_observer(
        self,
        session: _ManagedSession,
        page_id: str,
        page: Any,
    ) -> None:
        """Record failed requests and error responses for this page.

        Observation only: this never changes the page or adds new action
        kinds. ``requestfailed`` events and ``response`` events with a
        status >= 400 are recorded, with desensitized URLs, bounded per
        page (oldest dropped first, with a counter). Handlers are
        fail-closed and never propagate into the provider.
        """
        state = session.network_state.setdefault(
            page_id,
            {"entries": [], "total_count": 0, "dropped_count": 0},
        )

        def record_failure(
            *,
            kind: str,
            request: Any,
            status: int | None,
            error: str,
        ) -> None:
            try:
                url = self._sanitize_network_url(getattr(request, "url", ""))
                method = str(getattr(request, "method", "") or "unknown")[:16]
                resource_type = str(
                    getattr(request, "resource_type", "") or "unknown"
                )[:32]
                entries = state.setdefault("entries", [])
                entries.append(
                    {
                        "kind": kind,
                        "method": method,
                        "url": url,
                        "status": status,
                        "error": str(error or "unknown")[:_MAX_NETWORK_ERROR_TEXT_CHARS],
                        "resource_type": resource_type,
                        "captured_at": utc_now(),
                    }
                )
                state["total_count"] = int(state.get("total_count") or 0) + 1
                while len(entries) > _MAX_NETWORK_FAILURES_PER_PAGE:
                    entries.pop(0)
                    state["dropped_count"] = int(state.get("dropped_count") or 0) + 1
            except Exception:
                _LOG.warning(
                    "managed browser network failure record failed for page %s",
                    page_id,
                    exc_info=True,
                )

        def handle_request_failed(request: Any) -> None:
            try:
                failure = getattr(request, "failure", None)
                error = (
                    str(failure)
                    if not callable(failure)
                    else str(failure() or "")
                )
                record_failure(
                    kind="requestfailed",
                    request=request,
                    status=None,
                    error=error,
                )
            except Exception:
                _LOG.warning(
                    "managed browser requestfailed handler failed for page %s",
                    page_id,
                    exc_info=True,
                )

        def handle_response(response: Any) -> None:
            try:
                status_getter = getattr(response, "status", None)
                status = (
                    int(status_getter())
                    if callable(status_getter)
                    else int(status_getter or 0)
                )
                if status < _NETWORK_ERROR_STATUS_MIN:
                    return
                request = getattr(response, "request", None)
                record_failure(
                    kind="response_error",
                    request=request,
                    status=status,
                    error=f"http_status_{status}",
                )
            except Exception:
                _LOG.warning(
                    "managed browser response handler failed for page %s",
                    page_id,
                    exc_info=True,
                )

        on = getattr(page, "on", None)
        if not callable(on):
            _LOG.warning(
                "managed browser page has no event subscription; "
                "network observation disabled for page %s",
                page_id,
            )
            return
        for event, handler in (
            ("requestfailed", handle_request_failed),
            ("response", handle_response),
        ):
            try:
                on(event, handler)
            except Exception:
                _LOG.warning(
                    "managed browser could not subscribe %s events on page %s",
                    event,
                    page_id,
                    exc_info=True,
                )

    @staticmethod
    def _network_snapshot(session: _ManagedSession, page_id: str) -> dict[str, Any]:
        """Bounded network failure summary for one page's observation."""
        state = session.network_state.get(page_id) or {}
        entries = list(state.get("entries") or [])
        return {
            "total_count": int(state.get("total_count") or 0),
            "kept_count": len(entries),
            "dropped_count": int(state.get("dropped_count") or 0),
            "failed_requests": [
                dict(entry)
                for entry in entries[-_MAX_NETWORK_FAILURES_RECENT_IN_OBSERVATION:]
            ],
        }

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

    @staticmethod
    def _read_target_checked_state(handle: Any) -> bool:
        try:
            raw = handle.evaluate(_TARGET_CHECKED_STATE_SCRIPT)
        except Exception as exc:
            raise ManagedBrowserError(
                f"managed browser checkable state provider failed: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise ManagedBrowserError(
                "managed browser checkable state provider returned invalid evidence"
            )
        if not bool(raw.get("connected")):
            raise ManagedBrowserError("managed browser checkable target is detached")
        if not bool(raw.get("supported")):
            raise ManagedBrowserError(
                "managed browser check mutation currently supports only native input[type=checkbox] and input[type=radio] targets"
            )
        if bool(raw.get("disabled")):
            raise ManagedBrowserError("managed browser checkable target is disabled")
        checked = raw.get("checked")
        if type(checked) is not bool:
            raise ManagedBrowserError(
                "managed browser checkable checked state is unavailable"
            )
        return checked

    @staticmethod
    def _read_target_slider_state(handle: Any) -> dict[str, float]:
        """Read a native range input's bounds and current value from the page."""
        try:
            raw = handle.evaluate(_SLIDER_VALUE_SCRIPT)
        except Exception as exc:
            raise ManagedBrowserError(
                f"managed browser slider state provider failed: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise ManagedBrowserError(
                "managed browser slider state provider returned invalid evidence"
            )
        if not bool(raw.get("connected")):
            raise ManagedBrowserError("managed browser slider target is detached")
        if not bool(raw.get("supported")):
            raise ManagedBrowserError(
                "managed browser slider mutation currently supports only native input[type=range] targets"
            )
        if bool(raw.get("disabled")):
            raise ManagedBrowserError("managed browser slider target is disabled")

        def _finite(key: str, default: float) -> float:
            value = raw.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return default
            number = float(value)
            return number if math.isfinite(number) else default

        value = raw.get("slider_value")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ManagedBrowserError(
                "managed browser slider value is unavailable"
            )
        return {
            "min": _finite("slider_min", 0.0),
            "max": _finite("slider_max", 100.0),
            "step": _finite("slider_step", 1.0),
            "value": float(value),
        }

    @staticmethod
    def _validate_slider_value_arg(raw: Any) -> float:
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ManagedBrowserError(
                "browser set_slider_value requires a numeric args.value"
            ) from exc
        if not math.isfinite(value):
            raise ManagedBrowserError(
                "browser set_slider_value requires a finite numeric args.value"
            )
        return value

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
            network=self._network_snapshot(session, page_id),
            metadata={
                "provider": session.identity.provider,
                "page_count": len(session.pages),
                "page_ids": list(session.pages),
                "default_page_id": session.default_page_id,
                "service_workers": "blocked",
                "profile_scope": session.identity.profile_scope,
                "dialog": self._open_dialog_snapshot(session, page_id),
                "console_errors": self._console_error_snapshot(session, page_id),
                "dialog_auto_dismiss_count": int(
                    (session.dialog_state.get(page_id) or {}).get(
                        "auto_dismiss_count"
                    )
                    or 0
                ),
                "last_auto_dismissed_dialog": (
                    session.dialog_state.get(page_id) or {}
                ).get("last_auto_dismissed"),
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
            raise BrowserTargetStaleError(
                f"browser target changed before dispatch: {exc}"
            ) from exc
        if current.target_id != target.target_id:
            raise BrowserTargetStaleError("browser target changed before dispatch")
        return binding

    def _validate_authority(
        self,
        session: _ManagedSession,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> None:
        self._reconcile_pages(session)
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
        page_id = f"page-{session.next_page_sequence}"
        session.next_page_sequence += 1
        session.pages[page_id] = page
        if not session.default_page_id:
            session.default_page_id = page_id
        self._install_dialog_observer(session, page_id, page)
        self._install_console_error_observer(session, page_id, page)
        self._install_network_observer(session, page_id, page)
        return page_id

    def _reconcile_pages(self, session: _ManagedSession) -> None:
        provider_pages = self._provider_pages(session)
        provider_is_authoritative = provider_pages is not None
        if provider_pages is None:
            candidates = tuple(session.pages.values())
        else:
            candidates = tuple(
                page for page in provider_pages if not self._page_is_closed(page)
            )

        for page_id, page in tuple(session.pages.items()):
            missing_from_provider = provider_is_authoritative and not any(
                page is candidate for candidate in candidates
            )
            if self._page_is_closed(page) or missing_from_provider:
                self._evict_page(session, page_id)

        for page in candidates:
            if not self._page_is_closed(page):
                self._register_page(session, page)

        if session.default_page_id not in session.pages:
            session.default_page_id = next(iter(session.pages), "")

    @staticmethod
    def _provider_pages(session: _ManagedSession) -> tuple[Any, ...] | None:
        try:
            raw = getattr(session.context, "pages", None)
            if raw is None:
                return None
            if callable(raw):
                raw = raw()
            return tuple(raw)
        except Exception as exc:
            raise ManagedBrowserError(
                f"managed browser page registry could not be observed: {type(exc).__name__}: {exc}"
            ) from exc

    @staticmethod
    def _page_is_closed(page: Any) -> bool:
        try:
            return bool(getattr(page, "is_closed", lambda: False)())
        except Exception:
            return True

    def _evict_page(self, session: _ManagedSession, page_id: str) -> None:
        self._invalidate_target_binding(session, page_id)
        session.last_observation.pop(page_id, None)
        session.dialog_state.pop(page_id, None)
        session.console_error_state.pop(page_id, None)
        session.network_state.pop(page_id, None)
        session.pages.pop(page_id, None)
        if session.default_page_id == page_id:
            session.default_page_id = ""

    def _default_page_id(self, session: _ManagedSession) -> str:
        self._reconcile_pages(session)
        if not session.default_page_id:
            raise ManagedBrowserError("managed browser session has no page")
        return session.default_page_id

    def _page(self, session: _ManagedSession, page_id: str) -> Any:
        self._reconcile_pages(session)
        resolved_page_id = str(page_id or "")
        page = session.pages.get(resolved_page_id)
        if page is None:
            raise ManagedBrowserError("unknown managed browser page")
        if self._page_is_closed(page):
            self._evict_page(session, resolved_page_id)
            raise ManagedBrowserError("managed browser page is closed")
        return page

    def _session(self, session_id: str) -> _ManagedSession:
        self._maybe_auto_sweep_idle_sessions()
        session = self._sessions.get(str(session_id or "").strip())
        if session is None:
            raise ManagedBrowserError("unknown managed browser session")
        session.last_activity_monotonic = time.monotonic()
        return session

    def _close_session_resources(
        self,
        session: _ManagedSession,
        *,
        reason: str,
        idle_seconds: float = 0.0,
        ttl_seconds: float = 0.0,
    ) -> None:
        self._dispose_all_target_bindings(session)
        self._best_effort_close(session.context, session.browser, session.playwright)
        self._record_session_event(
            session,
            reason=reason,
            idle_seconds=idle_seconds,
            ttl_seconds=ttl_seconds,
        )

    def _record_session_event(
        self,
        session: _ManagedSession,
        *,
        reason: str,
        idle_seconds: float,
        ttl_seconds: float,
    ) -> None:
        event = {
            "event": "browser_session_closed",
            "reason": reason,
            "session_id": session.identity.session_id,
            "provider": self.name,
            "plane": BrowserPlane.MANAGED.value,
            "idle_seconds": round(float(idle_seconds), 3),
            "ttl_seconds": float(ttl_seconds) if reason == "idle_ttl" else None,
            "closed_at": utc_now(),
        }
        self._session_events.append(event)
        _LOG.info(
            "managed browser session closed: reason=%s session_id=%s idle_seconds=%.1f",
            reason,
            session.identity.session_id,
            idle_seconds,
        )
        callback = self._session_event_callback
        if callback is None:
            return
        try:
            callback(dict(event))
        except Exception:
            _LOG.exception("managed browser session event callback failed")

    def _maybe_auto_sweep_idle_sessions(self) -> None:
        """Opportunistic TTL sweep on the managed entry points.

        Throttled so the request path stays cheap; never allowed to fail
        loudly because cleanup must not break observe/act/open.
        """
        try:
            ttl = self.session_idle_ttl_seconds
            if ttl <= 0 or not self._sessions:
                return
            now = time.monotonic()
            if (
                now - self._last_auto_sweep_monotonic
                < _AUTO_SWEEP_MIN_INTERVAL_SECONDS
            ):
                return
            self._last_auto_sweep_monotonic = now
            self.close_idle_sessions(now=now, ttl_seconds=ttl)
        except Exception:
            _LOG.exception("managed browser idle session auto-sweep failed")

    @staticmethod
    def _failure(
        action: BrowserAction,
        *,
        error: str,
        data: dict[str, Any] | None = None,
    ) -> BrowserEffectEvidence:
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=utc_now(),
            success=False,
            page_id=action.page_id,
            target_id=action.target.target_id if action.target is not None else "",
            data=dict(data or {}),
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
