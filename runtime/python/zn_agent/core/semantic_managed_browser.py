from __future__ import annotations

"""Bounded semantic target sensing for resident-owned managed Chromium.

Semantic queries are deliberately smaller than a general accessibility query
language. ZN accepts only exact user-supplied names for explicitly supported
roles, keeps the query in the main frame, and fails closed on zero or multiple
matches. Provider locators may compute accessibility names internally, but ZN
never receives page-wide text or a candidate list.
"""

import hashlib
from typing import Any

from .browser import (
    BrowserAction,
    BrowserEffectEvidence,
    BrowserTarget,
    BrowserTargetKind,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from .browser_causal_popup import PlaywrightBrowserCausalPopupMixin
from .browser_scene import PlaywrightBrowserSceneMixin
from .browser_scene_actions import PlaywrightBrowserSceneActionMixin
from .browser_tab_navigation import PlaywrightBrowserTabNavigationMixin
from .managed_browser import (
    ManagedBrowserError,
    PlaywrightManagedBrowser,
    _ManagedTargetBinding,
)
from .models import utc_now


_SEMANTIC_CHECKBOX_EVIDENCE_SCRIPT = r"""
(element) => {
  const connected = Boolean(element && element.isConnected);
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
  return {
    connected,
    visible,
    tag,
    input_type: inputType,
    native_checkbox: tag === "input" && inputType === "checkbox",
  };
}
"""

_SEMANTIC_BUTTON_EVIDENCE_SCRIPT = r"""
(element) => {
  const connected = Boolean(element && element.isConnected);
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
  return {
    connected,
    visible,
    tag,
    native_button: tag === "button",
  };
}
"""

_SEMANTIC_TEXTBOX_EVIDENCE_SCRIPT = r"""
(element) => {
  const connected = Boolean(element && element.isConnected);
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
  const nativeTextbox = tag === "textarea" || (
    tag === "input" && (inputType === "" || inputType === "text")
  );
  return {
    connected,
    visible,
    tag,
    input_type: inputType,
    native_textbox: nativeTextbox,
    is_password: isPassword,
    disabled: Boolean(element && element.disabled),
    read_only: Boolean(element && element.readOnly),
  };
}
"""

_EXACT_NODE_EQUAL_SCRIPT = r"""
(element, other) => Boolean(element && other && element === other)
"""


class SemanticPlaywrightManagedBrowser(
    PlaywrightBrowserSceneMixin,
    PlaywrightBrowserCausalPopupMixin,
    PlaywrightBrowserSceneActionMixin,
    PlaywrightBrowserTabNavigationMixin,
    PlaywrightManagedBrowser,
):
    """Playwright adapter with fail-closed exact targets plus bounded scenes."""

    _SEMANTIC_KINDS = frozenset(
        {
            BrowserTargetQueryKind.ACCESSIBLE_CHECKBOX_NAME,
            BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME,
            BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME,
        }
    )

    def _acquire_target_binding(
        self,
        session: Any,
        page_id: str,
        query: BrowserTargetQuery,
        *,
        observed_at: str,
    ) -> _ManagedTargetBinding:
        if query.kind not in self._SEMANTIC_KINDS:
            return super()._acquire_target_binding(
                session,
                page_id,
                query,
                observed_at=observed_at,
            )
        if query.frame_id != "main":
            raise ManagedBrowserError(
                "managed browser semantic sensing currently supports only the main frame"
            )

        role, evidence_script, label = self._semantic_query_spec(query.kind)
        page = self._page(session, page_id)
        try:
            locator = page.get_by_role(role, name=query.value, exact=True)
            count = int(locator.count())
        except Exception as exc:
            raise ManagedBrowserError(
                f"failed to resolve managed browser semantic {label} target: {type(exc).__name__}: {exc}"
            ) from exc
        if count == 0:
            raise ManagedBrowserError(
                f"managed browser semantic {label} target was not found"
            )
        if count != 1:
            raise ManagedBrowserError(
                f"managed browser semantic {label} target is ambiguous"
            )

        locator = locator.nth(0)
        try:
            if not bool(locator.is_visible()):
                raise ManagedBrowserError(
                    f"managed browser semantic {label} target is not visible"
                )
            if not bool(locator.is_enabled()):
                raise ManagedBrowserError(
                    f"managed browser semantic {label} target is disabled"
                )
            handle = locator.element_handle()
        except ManagedBrowserError:
            raise
        except Exception as exc:
            raise ManagedBrowserError(
                f"failed to inspect managed browser semantic {label} target: {type(exc).__name__}: {exc}"
            ) from exc
        if handle is None:
            raise ManagedBrowserError(
                f"managed browser semantic {label} target has no exact provider node"
            )

        try:
            raw = handle.evaluate(evidence_script)
            evidence = dict(raw or {}) if isinstance(raw, dict) else {}
            if not bool(evidence.get("connected")) or not bool(evidence.get("visible")):
                raise ManagedBrowserError(
                    f"managed browser semantic {label} target is not currently actionable"
                )
            if bool(evidence.get("is_password")):
                raise ManagedBrowserError(
                    "managed browser semantic text target refuses password fields"
                )
            if bool(evidence.get("disabled")):
                raise ManagedBrowserError(
                    f"managed browser semantic {label} target is disabled"
                )
            if bool(evidence.get("read_only")):
                raise ManagedBrowserError(
                    f"managed browser semantic {label} target is read-only"
                )
            if query.kind is BrowserTargetQueryKind.ACCESSIBLE_CHECKBOX_NAME:
                valid_native = bool(evidence.get("native_checkbox"))
                target_kind = BrowserTargetKind.CHECKBOX
                editable = False
            elif query.kind is BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME:
                valid_native = bool(evidence.get("native_button"))
                target_kind = BrowserTargetKind.BUTTON
                editable = False
            else:
                valid_native = bool(evidence.get("native_textbox"))
                target_kind = BrowserTargetKind.TEXTBOX
                try:
                    editable = bool(locator.is_editable())
                except Exception:
                    editable = False
            if not valid_native:
                raise ManagedBrowserError(
                    f"managed browser semantic {label} first slice supports native controls only"
                )
            if target_kind is BrowserTargetKind.TEXTBOX and not editable:
                raise ManagedBrowserError(
                    "managed browser semantic textbox target is not editable"
                )
        except ManagedBrowserError:
            self._safe_dispose_handle(handle)
            raise
        except Exception as exc:
            self._safe_dispose_handle(handle)
            raise ManagedBrowserError(
                f"failed to inspect managed browser semantic {label} evidence: {type(exc).__name__}: {exc}"
            ) from exc

        query_token = hashlib.sha256(
            f"{query.kind.value}\0{query.value}".encode("utf-8")
        ).hexdigest()[:16]
        target = BrowserTarget(
            target_id=f"target-{query_token}-{observed_at}",
            page_id=page_id,
            frame_id="main",
            kind=target_kind,
            observed_at=observed_at,
            selector_hint=f"semantic:{query.kind.value}:{query_token}",
            accessible_name=query.value,
            tag_name=str(evidence.get("tag") or "")[:32],
            input_type=str(evidence.get("input_type") or "")[:32],
            visible=True,
            enabled=True,
            editable=editable,
        )
        return _ManagedTargetBinding(target=target, query=query, handle=handle)

    def _revalidate_target_binding(
        self,
        session: Any,
        page_id: str,
        target: BrowserTarget,
    ) -> _ManagedTargetBinding:
        binding = session.target_bindings.get(page_id)
        if binding is None or binding.target != target:
            raise ManagedBrowserError(
                "managed browser semantic target is stale or no longer current"
            )
        if not str(target.selector_hint or "").startswith("semantic:"):
            return super()._revalidate_target_binding(session, page_id, target)

        fresh = self._acquire_target_binding(
            session,
            page_id,
            binding.query,
            observed_at=target.observed_at,
        )
        try:
            try:
                same_exact_node = bool(
                    binding.handle.evaluate(_EXACT_NODE_EQUAL_SCRIPT, fresh.handle)
                )
            except Exception:
                same_exact_node = False
            if not same_exact_node:
                raise ManagedBrowserError(
                    "managed browser semantic target changed after observation"
                )
            return binding
        finally:
            if fresh.handle is not binding.handle:
                self._safe_dispose_handle(fresh.handle)

    @staticmethod
    def _semantic_query_spec(kind: BrowserTargetQueryKind):
        if kind is BrowserTargetQueryKind.ACCESSIBLE_CHECKBOX_NAME:
            return "checkbox", _SEMANTIC_CHECKBOX_EVIDENCE_SCRIPT, "checkbox"
        if kind is BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME:
            return "button", _SEMANTIC_BUTTON_EVIDENCE_SCRIPT, "button"
        if kind is BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME:
            return "textbox", _SEMANTIC_TEXTBOX_EVIDENCE_SCRIPT, "textbox"
        raise ManagedBrowserError(f"unsupported semantic target query: {kind.value}")

    @staticmethod
    def _safe_dispose_handle(handle: Any) -> None:
        try:
            handle.dispose()
        except Exception:
            pass
