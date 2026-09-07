from __future__ import annotations

"""Authority-bound mutations for exact BrowserScene targets."""

import hashlib
from dataclasses import replace
from typing import Any
from urllib.parse import urlsplit

from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
    BrowserObservation,
)
from .managed_browser import ManagedBrowserError


_SCENE_PREFIX = "browser_scene:"
_SCENE_ACTIONS = frozenset(
    {
        BrowserActionKind.FOCUS,
        BrowserActionKind.TYPE_TEXT,
        BrowserActionKind.CHECK,
        BrowserActionKind.UNCHECK,
        BrowserActionKind.CLICK,
    }
)
_TEXT_ROLES = frozenset({"textbox", "searchbox", "textarea"})
_CHECK_ROLES = frozenset({"checkbox", "radio"})
_NAV_ROLES = frozenset({"link", "button"})
_MAX_TEXT_EVIDENCE = 32768

_FOCUS_SCRIPT = """
(element) => Boolean(element && element.isConnected && element.ownerDocument &&
                     element.ownerDocument.activeElement === element)
"""
_CHECK_SCRIPT = """
(element) => {
  if (!element || !element.isConnected) return {connected: false};
  const tag = String(element.tagName || '').toLowerCase();
  const type = String(element.getAttribute?.('type') || '').toLowerCase();
  const supported = tag === 'input' && (type === 'checkbox' || type === 'radio');
  return {connected: true, supported, type, disabled: Boolean(element.disabled),
          checked: supported ? Boolean(element.checked) : null};
}
"""
_TEXT_SCRIPT = """
(element) => {
  if (!element || !element.isConnected) return {connected: false};
  const tag = String(element.tagName || '').toLowerCase();
  const type = String(element.getAttribute?.('type') || '').toLowerCase();
  const sensitive = tag === 'input' && type === 'password';
  const supported = tag === 'textarea' ||
    (tag === 'input' && (type === '' || type === 'text' || type === 'search'));
  return {connected: true, supported, sensitive, disabled: Boolean(element.disabled),
          read_only: Boolean(element.readOnly),
          value: supported && typeof element.value === 'string' ? element.value : ''};
}
"""


class PlaywrightBrowserSceneActionMixin:
    """Bridge current BrowserScene truth into the existing action control plane."""

    def observe_scene_target(
        self,
        session_id: str,
        target_id: str,
        *,
        page_id: str = "",
    ) -> BrowserObservation:
        session = self._session(session_id)
        binding = self._scene_binding(session, target_id, page_id=page_id)
        if binding.scene_target.sensitive and not session.permission.allow_sensitive_fields:
            raise ManagedBrowserError("BrowserScene action target is sensitive and not authorized")
        self._scene_revalidate_binding(session, binding)
        page = self._page(session, binding.page_id)
        before_url = str(getattr(page, "url", "") or "")
        self._require_url_allowed(before_url, session.permission)

        # Deliberately call the provider capture seam so USER-plane metadata survives.
        # A targetless capture clears only the legacy managed binding; do not call
        # _invalidate_target_binding(), whose current MRO also destroys BrowserScene.
        captured = self._capture(session, binding.page_id)
        if captured.url != before_url:
            raise ManagedBrowserError("BrowserScene target page changed during authority observation")
        self._scene_revalidate_binding(session, binding)

        target = replace(binding.target, observed_at=captured.captured_at, url=captured.url)
        binding.target = target
        metadata = dict(captured.metadata)
        metadata.update(
            grounding="browser_scene",
            scene_target_role=binding.scene_target.role,
            scene_frame_id=binding.scene_target.frame_id,
        )
        observed = replace(captured, target=target, metadata=metadata)
        session.last_observation[binding.page_id] = observed
        return observed

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        if not self._is_scene_action(action):
            return super().act(action, authority)
        if action.kind not in _SCENE_ACTIONS:
            return self._failure(action, error=f"ManagedBrowserError: unsupported BrowserScene action: {action.kind.value}")

        session = self._session(action.session_id)
        try:
            self._validate_scene_shape(action)
            self._validate_authority(session, action, authority)
            assert action.target is not None
            binding = self._scene_binding(
                session,
                action.target.target_id,
                page_id=action.page_id or action.target.page_id,
                expected_target=action.target,
            )
            self._scene_revalidate_binding(session, binding)
            if action.kind is BrowserActionKind.FOCUS:
                return self._focus(session, action, binding)
            if action.kind is BrowserActionKind.TYPE_TEXT:
                return self._type_text(session, action, binding)
            if action.kind is BrowserActionKind.CHECK:
                return self._check(session, action, binding, requested=True)
            if action.kind is BrowserActionKind.UNCHECK:
                return self._check(session, action, binding, requested=False)
            return self._navigation_click(session, action, authority, binding)
        except Exception as exc:
            return self._failure(action, error=f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _is_scene_action(action: BrowserAction) -> bool:
        return bool(action.target and str(action.target.selector_hint or "").startswith(_SCENE_PREFIX))

    def _validate_scene_shape(self, action: BrowserAction) -> None:
        if action.target is None:
            raise ManagedBrowserError("BrowserScene action requires an exact target")
        if action.kind is BrowserActionKind.FOCUS:
            self._exact_keys(action.args, set(), "FOCUS args")
            self._exact_keys(action.expected, set(), "FOCUS expected")
        elif action.kind is BrowserActionKind.TYPE_TEXT:
            self._exact_keys(action.args, {"text"}, "TYPE_TEXT args")
            self._exact_keys(action.expected, set(), "TYPE_TEXT expected")
            text, _ = self._validate_managed_text(action.args.get("text"))
            text = ""
        elif action.kind in {BrowserActionKind.CHECK, BrowserActionKind.UNCHECK}:
            self._exact_keys(action.args, set(), f"{action.kind.value} args")
            self._exact_keys(action.expected, set(), f"{action.kind.value} expected")
        elif action.kind is BrowserActionKind.CLICK:
            self._exact_keys(action.args, set(), "CLICK args")
            self._exact_keys(action.expected, {"url_equals"}, "CLICK expected")
            self._http_url(action.expected.get("url_equals"), "CLICK expected.url_equals")
        else:
            raise ManagedBrowserError(f"unsupported BrowserScene action: {action.kind.value}")

    @staticmethod
    def _exact_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
        actual = set(value)
        if actual == allowed:
            return
        unexpected = sorted(actual - allowed)
        missing = sorted(allowed - actual)
        details = []
        if unexpected:
            details.append("unexpected=" + ",".join(unexpected))
        if missing:
            details.append("missing=" + ",".join(missing))
        raise ManagedBrowserError(f"{label} must use only its declared schema ({'; '.join(details)})")

    @staticmethod
    def _http_url(raw: Any, label: str) -> str:
        if not isinstance(raw, str) or not raw.strip():
            raise ManagedBrowserError(f"{label} must be a non-empty HTTP(S) URL string")
        url = raw.strip()
        try:
            parsed = urlsplit(url)
        except ValueError as exc:
            raise ManagedBrowserError(f"{label} must be an HTTP(S) URL") from exc
        if str(parsed.scheme or "").lower() not in {"http", "https"} or not parsed.hostname:
            raise ManagedBrowserError(f"{label} must be an HTTP(S) URL")
        return url

    def _scene_binding(
        self,
        session: Any,
        target_id: str,
        *,
        page_id: str = "",
        expected_target: Any = None,
    ) -> Any:
        resolved_page_id = str(page_id or "").strip() or self._default_page_id(session)
        page_state = self._scene_state(session).page_scenes.get(resolved_page_id)
        if page_state is None:
            raise ManagedBrowserError("BrowserScene action requires a fresh scene for the target page")
        binding = page_state.bindings.get(str(target_id or "").strip())
        if binding is None:
            raise ManagedBrowserError("BrowserScene action target is stale or unknown")
        if expected_target is not None and binding.target != expected_target:
            raise ManagedBrowserError("BrowserScene action target evidence changed before dispatch")
        return binding

    def _focus(self, session: Any, action: BrowserAction, binding: Any) -> BrowserEffectEvidence:
        page, before_url, pages = self._pre_dispatch(session, binding)
        dispatched = False
        try:
            binding.handle.focus()
            dispatched = True
            self._scene_revalidate_binding(session, binding)
            if not bool(binding.handle.evaluate(_FOCUS_SCRIPT)):
                raise ManagedBrowserError("BrowserScene focus postcondition was not observed")
            self._unchanged_url(page, before_url, "focus")
            self._no_fresh_page(session, pages)
        except Exception:
            if dispatched:
                self._dispatched_failure(session, binding.page_id)
            raise
        observed = self._finish_same_page(session, binding.page_id, before_url)
        return self._evidence(action, observed, before_url, binding, "same_scene_target_focused", {"focused": True})

    def _type_text(self, session: Any, action: BrowserAction, binding: Any) -> BrowserEffectEvidence:
        if binding.scene_target.role not in _TEXT_ROLES or binding.scene_target.sensitive:
            raise ManagedBrowserError("BrowserScene type_text requires a non-sensitive textbox/searchbox/textarea")
        text, expected = self._validate_managed_text(action.args.get("text"))
        before = self._text_state(binding.handle)
        if before["text_length"] != 0:
            text = ""
            raise ManagedBrowserError("BrowserScene type_text first slice refuses a non-empty target")
        page, before_url, pages = self._pre_dispatch(session, binding)
        dispatched = False
        try:
            binding.handle.fill(text)
            dispatched = True
            text = ""
            self._scene_revalidate_binding(session, binding)
            after = self._text_state(binding.handle)
            self._unchanged_url(page, before_url, "type_text")
            self._no_fresh_page(session, pages)
            if after["text_length"] != expected["text_length"] or after["text_sha256"] != expected["text_sha256"]:
                raise ManagedBrowserError("BrowserScene type_text postcondition was not observed")
        except Exception:
            text = ""
            if dispatched:
                self._dispatched_failure(session, binding.page_id)
            raise
        observed = self._finish_same_page(session, binding.page_id, before_url)
        return self._evidence(
            action,
            observed,
            before_url,
            binding,
            "same_scene_target_text_equals_requested",
            {
                "text_length_before": before["text_length"],
                "text_sha256_before": before["text_sha256"],
                "text_length_after": after["text_length"],
                "text_sha256_after": after["text_sha256"],
                "expected_text_length": expected["text_length"],
                "expected_text_sha256": expected["text_sha256"],
            },
        )

    def _check(self, session: Any, action: BrowserAction, binding: Any, *, requested: bool) -> BrowserEffectEvidence:
        role = binding.scene_target.role
        if role not in _CHECK_ROLES:
            raise ManagedBrowserError("BrowserScene check/uncheck requires checkbox or radio")
        if role == "radio" and not requested:
            raise ManagedBrowserError("BrowserScene refuses to uncheck a radio target")
        before = self._checked_state(binding.handle)
        if before is requested:
            raise ManagedBrowserError("BrowserScene checked postcondition is already observed before dispatch")
        page, before_url, pages = self._pre_dispatch(session, binding)
        dispatched = False
        try:
            (binding.handle.check if requested else binding.handle.uncheck)()
            dispatched = True
            self._scene_revalidate_binding(session, binding)
            after = self._checked_state(binding.handle)
            self._unchanged_url(page, before_url, "checked-state")
            self._no_fresh_page(session, pages)
            if after is not requested:
                raise ManagedBrowserError("BrowserScene checked-state postcondition was not observed")
        except Exception:
            if dispatched:
                self._dispatched_failure(session, binding.page_id)
            raise
        observed = self._finish_same_page(session, binding.page_id, before_url)
        return self._evidence(
            action,
            observed,
            before_url,
            binding,
            "same_scene_target_checked" if requested else "same_scene_target_unchecked",
            {"checked_before": before, "checked_after": after},
        )

    def _navigation_click(self, session: Any, action: BrowserAction, authority: BrowserActionAuthority, binding: Any) -> BrowserEffectEvidence:
        if binding.scene_target.role not in _NAV_ROLES:
            raise ManagedBrowserError("BrowserScene navigation click currently supports link/button targets")
        if not authority.permission.allow_page_interaction:
            raise ManagedBrowserError("BrowserScene navigation click requires page-interaction permission")
        if not authority.permission.allow_navigation:
            raise ManagedBrowserError("BrowserScene navigation click requires navigation permission")
        expected_url = self._http_url(action.expected.get("url_equals"), "CLICK expected.url_equals")
        self._require_url_allowed(expected_url, session.permission)
        page, before_url, pages = self._pre_dispatch(session, binding)
        if before_url == expected_url:
            raise ManagedBrowserError("BrowserScene click expected URL is already observed before dispatch")
        dispatched = False
        try:
            binding.handle.click()
            dispatched = True
            self._no_fresh_page(session, pages)
            wait_for_url = getattr(page, "wait_for_url", None)
            if not callable(wait_for_url):
                raise ManagedBrowserError("BrowserScene navigation provider cannot wait for explicit URL completion")
            wait_for_url(expected_url, wait_until="domcontentloaded", timeout=self.navigation_timeout_ms)
            self._no_fresh_page(session, pages)
        except Exception:
            if dispatched:
                self._dispatched_failure(session, binding.page_id)
            raise
        self._scene_invalidate_page(session.identity.session_id, binding.page_id)
        observed = self._capture(session, binding.page_id)
        self._require_url_allowed(observed.url, session.permission)
        self._no_fresh_page(session, pages)
        if observed.url != expected_url:
            raise ManagedBrowserError("BrowserScene navigation click postcondition did not match observed URL")
        return self._evidence(
            action,
            observed,
            before_url,
            binding,
            "url_equals_after_exact_scene_target_click",
            {"expected_url": expected_url},
        )

    def _pre_dispatch(self, session: Any, binding: Any) -> tuple[Any, str, tuple[Any, ...]]:
        self._scene_revalidate_binding(session, binding)
        page = self._page(session, binding.page_id)
        before_url = str(getattr(page, "url", "") or "")
        self._require_url_allowed(before_url, session.permission)
        return page, before_url, self._scene_action_provider_pages(session)

    def _finish_same_page(self, session: Any, page_id: str, before_url: str) -> BrowserObservation:
        self._scene_invalidate_page(session.identity.session_id, page_id)
        observed = self._capture(session, page_id)
        self._require_url_allowed(observed.url, session.permission)
        if observed.url != before_url:
            raise ManagedBrowserError("BrowserScene mutation changed the top-level URL")
        return observed

    def _dispatched_failure(self, session: Any, page_id: str) -> None:
        self._scene_invalidate_page(session.identity.session_id, page_id)
        try:
            self._capture(session, page_id)
        except Exception:
            session.last_observation.pop(page_id, None)

    @staticmethod
    def _unchanged_url(page: Any, before_url: str, label: str) -> None:
        if str(getattr(page, "url", "") or "") != before_url:
            raise ManagedBrowserError(f"BrowserScene {label} unexpectedly changed the top-level URL")

    def _scene_action_provider_pages(self, session: Any) -> tuple[Any, ...]:
        raw = getattr(session.context, "pages", ())
        if callable(raw):
            raw = raw()
        return tuple(page for page in tuple(raw or ()) if not self._page_is_closed(page))

    def _no_fresh_page(self, session: Any, before: tuple[Any, ...]) -> None:
        current = self._scene_action_provider_pages(session)
        if any(not any(page is old for old in before) for page in current):
            raise ManagedBrowserError("unexpected fresh page observed")

    @staticmethod
    def _checked_state(handle: Any) -> bool:
        raw = handle.evaluate(_CHECK_SCRIPT)
        if not isinstance(raw, dict) or not bool(raw.get("connected")):
            raise ManagedBrowserError("BrowserScene checked target is detached")
        if not bool(raw.get("supported")):
            raise ManagedBrowserError("BrowserScene checked-state mutation supports native checkbox/radio only")
        if bool(raw.get("disabled")):
            raise ManagedBrowserError("BrowserScene checked target is disabled")
        checked = raw.get("checked")
        if type(checked) is not bool:
            raise ManagedBrowserError("BrowserScene checked state is unavailable")
        return checked

    @staticmethod
    def _text_state(handle: Any) -> dict[str, Any]:
        raw = handle.evaluate(_TEXT_SCRIPT)
        if not isinstance(raw, dict) or not bool(raw.get("connected")):
            raise ManagedBrowserError("BrowserScene text target is detached")
        if bool(raw.get("sensitive")):
            raise ManagedBrowserError("BrowserScene type_text first slice refuses password/sensitive targets")
        if not bool(raw.get("supported")):
            raise ManagedBrowserError("BrowserScene text mutation supports input[type=text/search] and textarea only")
        if bool(raw.get("disabled")) or bool(raw.get("read_only")):
            raise ManagedBrowserError("BrowserScene text target is disabled or read-only")
        value = raw.get("value")
        if not isinstance(value, str) or len(value) > _MAX_TEXT_EVIDENCE:
            raise ManagedBrowserError("BrowserScene text value is unavailable or outside the evidence bound")
        result = {"text_length": len(value), "text_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest()}
        value = ""
        return result

    @staticmethod
    def _evidence(
        action: BrowserAction,
        observed: BrowserObservation,
        before_url: str,
        binding: Any,
        postcondition: str,
        data: dict[str, Any],
    ) -> BrowserEffectEvidence:
        payload = {
            "provider": observed.session.provider,
            "role": binding.scene_target.role,
            "frame_id": binding.scene_target.frame_id,
            "target_revalidated_before_dispatch": True,
            **data,
        }
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=observed.captured_at,
            success=True,
            page_id=observed.page_id,
            url_before=before_url,
            url_after=observed.url,
            target_id=action.target.target_id if action.target else "",
            postcondition=postcondition,
            data=payload,
        )
