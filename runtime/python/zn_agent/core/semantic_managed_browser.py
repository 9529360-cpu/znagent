from __future__ import annotations

"""Bounded semantic target sensing for resident-owned managed Chromium.

Semantic queries are deliberately smaller than a general accessibility query
language. ZN accepts only exact user-supplied names for explicitly supported
roles, keeps the query in the main frame, and fails closed on zero or multiple
matches. Provider locators may compute accessibility names internally, but ZN
never receives page-wide text or a candidate list.

Supported roles: checkbox, button, textbox, combobox, link, radio, slider,
switch, tab, menuitem.
Link targets additionally support verified navigation clicks; radio targets
support verified check (select); slider targets are perceivable and support
only the verified set_slider_value mutation (set, then read the value back on
the same exact node). Any slider interaction that cannot be verified this way
-- drags, keyboard nudges -- is explicitly not offered.
Switch targets support verified check/uncheck with the same exact-node
read-back as checkbox targets (role=switch elements; non-input switches are
read through aria-checked). Tab targets support verified select: click with
expected aria_selected true, then aria-selected is read back on the same
exact node; tabs without a boolean aria-selected state are refused.
Menuitem targets are precisely perceivable but clicking is explicitly not
offered: no generic verified postcondition exists for menu activation.
"""

import hashlib
from typing import Any

from .browser import (
    BrowserAction,
    BrowserEffectEvidence,
    BrowserTarget,
    BrowserTargetKind,
    BrowserTargetQuery,
    BrowserTargetStaleError,
    BrowserTargetQueryKind,
)
from .browser_causal_popup import PlaywrightBrowserCausalPopupMixin
from .browser_scene import PlaywrightBrowserSceneMixin
from .browser_scene_actions import PlaywrightBrowserSceneActionMixin
from .browser_scene_command import PlaywrightBrowserSceneCommandMixin
from .browser_scene_controls import PlaywrightBrowserSceneControlMixin
from .browser_scene_file_transfer import PlaywrightBrowserSceneFileTransferMixin
from .browser_scene_table import PlaywrightBrowserSceneTableMixin
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

_SEMANTIC_COMBOBOX_EVIDENCE_SCRIPT = r"""
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
    native_combobox: tag === "select",
    disabled: Boolean(element && element.disabled),
    multiple: Boolean(element && element.multiple),
  };
}
"""

_SEMANTIC_LINK_EVIDENCE_SCRIPT = r"""
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
  const href = String(element && element.getAttribute("href") || "").slice(0, 256);
  return {
    connected,
    visible,
    tag,
    href,
    native_link: tag === "a" && href !== "",
  };
}
"""

_SEMANTIC_RADIO_EVIDENCE_SCRIPT = r"""
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
    native_radio: tag === "input" && inputType === "radio",
    disabled: Boolean(element && element.disabled),
  };
}
"""

_SEMANTIC_SLIDER_EVIDENCE_SCRIPT = r"""
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
  const nativeSlider = tag === "input" && inputType === "range";
  const attrNum = (name, dflt) => {
    const raw = element ? element.getAttribute(name) : null;
    const n = raw === null || raw === "" ? NaN : Number(raw);
    return Number.isFinite(n) ? n : dflt;
  };
  const current = element ? Number(element.value) : NaN;
  return {
    connected,
    visible,
    tag,
    input_type: inputType,
    native_slider: nativeSlider,
    disabled: Boolean(element && element.disabled),
    slider_min: attrNum("min", 0),
    slider_max: attrNum("max", 100),
    slider_step: attrNum("step", 1),
    slider_value: Number.isFinite(current) ? current : null,
  };
}
"""

_SEMANTIC_SWITCH_EVIDENCE_SCRIPT = r"""
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
  const roleAttr = String(element && element.getAttribute("role") || "")
    .trim()
    .toLowerCase()
    .slice(0, 32);
  return {
    connected,
    visible,
    tag,
    input_type: inputType,
    role_attr: roleAttr,
    native_switch: roleAttr === "switch",
    disabled: Boolean(element && element.disabled),
  };
}
"""

_SEMANTIC_TAB_EVIDENCE_SCRIPT = r"""
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
  const roleAttr = String(element && element.getAttribute("role") || "")
    .trim()
    .toLowerCase()
    .slice(0, 32);
  return {
    connected,
    visible,
    tag,
    input_type: inputType,
    role_attr: roleAttr,
    native_tab: roleAttr === "tab",
    disabled: Boolean(element && element.disabled),
  };
}
"""

_SEMANTIC_MENUITEM_EVIDENCE_SCRIPT = r"""
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
  const roleAttr = String(element && element.getAttribute("role") || "")
    .trim()
    .toLowerCase()
    .slice(0, 32);
  return {
    connected,
    visible,
    tag,
    input_type: inputType,
    role_attr: roleAttr,
    native_menuitem: roleAttr === "menuitem",
    disabled: Boolean(element && element.disabled),
  };
}
"""

_EXACT_NODE_EQUAL_SCRIPT = r"""
(element, other) => Boolean(element && other && element === other)
"""

_TAB_ARIA_SELECTED_SCRIPT = r"""
(element) => {
  if (!element || !element.isConnected) {
    return null;
  }
  const value = String(element.getAttribute("aria-selected") || "")
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


class SemanticPlaywrightManagedBrowser(
    PlaywrightBrowserSceneMixin,
    PlaywrightBrowserSceneTableMixin,
    PlaywrightBrowserCausalPopupMixin,
    PlaywrightBrowserSceneFileTransferMixin,
    PlaywrightBrowserSceneCommandMixin,
    PlaywrightBrowserSceneControlMixin,
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
            BrowserTargetQueryKind.ACCESSIBLE_COMBOBOX_NAME,
            BrowserTargetQueryKind.ACCESSIBLE_LINK_NAME,
            BrowserTargetQueryKind.ACCESSIBLE_RADIO_NAME,
            BrowserTargetQueryKind.ACCESSIBLE_SLIDER_NAME,
            BrowserTargetQueryKind.ACCESSIBLE_SWITCH_NAME,
            BrowserTargetQueryKind.ACCESSIBLE_TAB_NAME,
            BrowserTargetQueryKind.ACCESSIBLE_MENUITEM_NAME,
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

        element = None
        keep_element = False
        try:
            element = locator.element_handle()
            if element is None:
                raise ManagedBrowserError(
                    f"managed browser semantic {label} target changed while provider evidence was acquired"
                )
            raw = element.evaluate(evidence_script)
            self._validate_semantic_evidence(query.kind, raw)
            current_url = str(getattr(page, "url", "") or "")
            target = self._semantic_target(
                session,
                page_id,
                query,
                raw,
                current_url=current_url,
                observed_at=observed_at,
            )
            keep_element = True
            return _ManagedTargetBinding(target=target, query=query, handle=element)
        except ManagedBrowserError:
            raise
        except Exception as exc:
            raise ManagedBrowserError(
                f"failed to observe managed browser semantic {label} target: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            if element is not None and not keep_element:
                self._best_effort_dispose_handle(element)

    def _revalidate_target_binding(
        self,
        session: Any,
        page_id: str,
        target: BrowserTarget,
    ) -> _ManagedTargetBinding:
        binding = session.target_bindings.get(page_id)
        if binding is None or binding.query.kind not in self._SEMANTIC_KINDS:
            return super()._revalidate_target_binding(session, page_id, target)
        if binding.target != target:
            raise ManagedBrowserError(
                "browser semantic target provider evidence does not match the current action target"
            )

        role, evidence_script, label = self._semantic_query_spec(binding.query.kind)
        page = self._page(session, page_id)
        fresh = None
        try:
            locator = page.get_by_role(
                role,
                name=binding.query.value,
                exact=True,
            )
            count = int(locator.count())
            if count != 1:
                if count == 0:
                    raise BrowserTargetStaleError(
                        f"browser semantic {label} target changed before dispatch: target was not found"
                    )
                raise BrowserTargetStaleError(
                    f"browser semantic {label} target changed before dispatch: target is ambiguous"
                )
            fresh = locator.element_handle()
            if fresh is None:
                raise BrowserTargetStaleError(
                    f"browser semantic {label} target changed before dispatch"
                )
            raw = fresh.evaluate(evidence_script)
            self._validate_semantic_evidence(binding.query.kind, raw)
            same_exact_node = bool(
                binding.handle.evaluate(_EXACT_NODE_EQUAL_SCRIPT, fresh)
            )
            if not same_exact_node:
                raise BrowserTargetStaleError(
                    f"browser semantic {label} target changed before dispatch"
                )
        except BrowserTargetStaleError:
            raise
        except ManagedBrowserError:
            raise
        except Exception as exc:
            raise BrowserTargetStaleError(
                f"browser semantic {label} target changed before dispatch: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            if fresh is not None:
                self._best_effort_dispose_handle(fresh)
        return binding

    def _click(self, session: Any, action: BrowserAction) -> BrowserEffectEvidence:
        """Allow verified navigation clicks and verified tab selects in addition to base toggle clicks."""

        if "aria_selected" in action.expected:
            expected_selected = action.expected.get("aria_selected")
            if expected_selected is not True:
                raise ManagedBrowserError(
                    "browser tab select currently requires expected aria_selected true"
                )
            return self._verified_tab_select_click(session, action)
        expected_url = str(action.expected.get("url_equals") or "").strip()
        if not expected_url:
            return super()._click(session, action)
        if action.target is None:
            raise ManagedBrowserError("browser navigation click requires a current target")
        if action.target.role not in ("button", "link"):
            raise ManagedBrowserError(
                "browser navigation click currently requires a semantic button or link target"
            )
        postcondition = (
            "url_equals_after_fresh_semantic_link_click"
            if action.target.role == "link"
            else "url_equals_after_fresh_semantic_button_click"
        )
        self._require_url_allowed(expected_url, session.permission)

        page_id = action.page_id or action.target.page_id or self._default_page_id(session)
        page = self._page(session, page_id)
        binding = self._revalidate_target_binding(session, page_id, action.target)
        before_url = str(getattr(page, "url", "") or "")
        if before_url == expected_url:
            raise ManagedBrowserError(
                "browser navigation click expected URL is already observed before dispatch"
            )

        try:
            binding.handle.click()
        except Exception as exc:
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            raise ManagedBrowserError(
                f"managed browser navigation click dispatch failed: {type(exc).__name__}: {exc}"
            ) from exc

        observed_at = utc_now()
        try:
            observation = self._capture(
                session,
                page_id,
                captured_at=observed_at,
            )
            self._require_url_allowed(observation.url, session.permission)
        except Exception as exc:
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            raise ManagedBrowserError(
                f"managed browser navigation click postcondition could not be observed: {type(exc).__name__}: {exc}"
            ) from exc

        data = {
            "provider": session.identity.provider,
            "target_revalidated_before_dispatch": True,
            "expected_url": expected_url,
        }
        if observation.url != expected_url:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=observation.captured_at,
                success=False,
                page_id=page_id,
                url_before=before_url,
                url_after=observation.url,
                target_id=action.target.target_id,
                postcondition=postcondition,
                data=data,
                error="browser navigation click postcondition did not match observed URL",
            )
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=observation.captured_at,
            success=True,
            page_id=page_id,
            url_before=before_url,
            url_after=observation.url,
            target_id=action.target.target_id,
            postcondition=postcondition,
            data=data,
        )

    @staticmethod
    def _read_tab_selected_state(handle: Any) -> bool:
        try:
            raw = handle.evaluate(_TAB_ARIA_SELECTED_SCRIPT)
        except Exception as exc:
            raise ManagedBrowserError(
                f"managed browser tab selected state provider failed: {type(exc).__name__}: {exc}"
            ) from exc
        if type(raw) is not bool:
            raise ManagedBrowserError(
                "managed browser tab select currently requires a tab with boolean aria-selected state"
            )
        return raw

    def _verified_tab_select_click(
        self,
        session: Any,
        action: BrowserAction,
    ) -> BrowserEffectEvidence:
        """Click a semantic tab and verify aria-selected flipped on the same exact node."""
        if action.target is None:
            raise ManagedBrowserError("browser tab select requires a current target")
        if action.target.role != "tab":
            raise ManagedBrowserError(
                "browser tab select currently requires a semantic tab target"
            )

        page_id = action.page_id or action.target.page_id or self._default_page_id(session)
        page = self._page(session, page_id)
        binding = self._revalidate_target_binding(session, page_id, action.target)
        before_url = str(getattr(page, "url", "") or "")
        selected_before = self._read_tab_selected_state(binding.handle)
        if selected_before:
            raise ManagedBrowserError(
                "browser tab select target is already selected before dispatch"
            )

        try:
            binding.handle.click()
        except Exception as exc:
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            raise ManagedBrowserError(
                f"managed browser tab select dispatch failed: {type(exc).__name__}: {exc}"
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
                f"managed browser tab select target could not be re-observed: {exc}"
            ) from exc

        try:
            same_exact_node = bool(
                binding.handle.evaluate(_EXACT_NODE_EQUAL_SCRIPT, fresh_binding.handle)
            )
        except Exception:
            same_exact_node = False
        try:
            selected_after = self._read_tab_selected_state(fresh_binding.handle)
        except Exception as exc:
            self._dispose_target_binding(fresh_binding)
            self._refresh_page_observation_after_failed_mutation(session, page_id)
            raise ManagedBrowserError(
                f"browser tab select postcondition could not be observed: {exc}"
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
        postcondition = "same_exact_target_tab_selected"
        data = {
            "provider": session.identity.provider,
            "exact_node_continuity": same_exact_node,
            "selected_before": selected_before,
            "selected_after": selected_after,
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
                postcondition=postcondition,
                data=data,
                error="browser tab select postcondition lost the current target",
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
                postcondition=postcondition,
                data=data,
                error="browser tab select postcondition observed a replaced target node",
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
                postcondition=postcondition,
                data=data,
                error="browser tab select postcondition observed changed target identity",
            )
        if not selected_after:
            return BrowserEffectEvidence(
                action_id=action.action_id,
                session_id=action.session_id,
                observed_at=post_observation.captured_at,
                success=False,
                page_id=page_id,
                url_before=before_url,
                url_after=after_url,
                target_id=post_target.target_id,
                postcondition=postcondition,
                data=data,
                error="browser tab select postcondition was not observed",
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
            postcondition=postcondition,
            data=data,
        )

    @staticmethod
    def _semantic_query_spec(kind: BrowserTargetQueryKind) -> tuple[str, str, str]:
        if kind is BrowserTargetQueryKind.ACCESSIBLE_CHECKBOX_NAME:
            return "checkbox", _SEMANTIC_CHECKBOX_EVIDENCE_SCRIPT, "checkbox"
        if kind is BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME:
            return "button", _SEMANTIC_BUTTON_EVIDENCE_SCRIPT, "button"
        if kind is BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME:
            return "textbox", _SEMANTIC_TEXTBOX_EVIDENCE_SCRIPT, "textbox"
        if kind is BrowserTargetQueryKind.ACCESSIBLE_COMBOBOX_NAME:
            return "combobox", _SEMANTIC_COMBOBOX_EVIDENCE_SCRIPT, "combobox"
        if kind is BrowserTargetQueryKind.ACCESSIBLE_LINK_NAME:
            return "link", _SEMANTIC_LINK_EVIDENCE_SCRIPT, "link"
        if kind is BrowserTargetQueryKind.ACCESSIBLE_RADIO_NAME:
            return "radio", _SEMANTIC_RADIO_EVIDENCE_SCRIPT, "radio"
        if kind is BrowserTargetQueryKind.ACCESSIBLE_SLIDER_NAME:
            return "slider", _SEMANTIC_SLIDER_EVIDENCE_SCRIPT, "slider"
        if kind is BrowserTargetQueryKind.ACCESSIBLE_SWITCH_NAME:
            return "switch", _SEMANTIC_SWITCH_EVIDENCE_SCRIPT, "switch"
        if kind is BrowserTargetQueryKind.ACCESSIBLE_TAB_NAME:
            return "tab", _SEMANTIC_TAB_EVIDENCE_SCRIPT, "tab"
        if kind is BrowserTargetQueryKind.ACCESSIBLE_MENUITEM_NAME:
            return "menuitem", _SEMANTIC_MENUITEM_EVIDENCE_SCRIPT, "menuitem"
        raise ManagedBrowserError(f"unsupported semantic target query: {kind.value}")

    @staticmethod
    def _validate_semantic_evidence(kind: BrowserTargetQueryKind, raw: Any) -> None:
        if not isinstance(raw, dict):
            raise ManagedBrowserError(
                "managed browser semantic provider returned invalid evidence"
            )
        if not bool(raw.get("connected")):
            raise ManagedBrowserError("managed browser semantic target is detached")
        if not bool(raw.get("visible")):
            raise ManagedBrowserError("managed browser semantic target is not visible")
        if kind is BrowserTargetQueryKind.ACCESSIBLE_CHECKBOX_NAME:
            if not bool(raw.get("native_checkbox")):
                raise ManagedBrowserError(
                    "managed browser semantic checkbox Work currently supports only native input[type=checkbox] targets"
                )
            return
        if kind is BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME:
            if not bool(raw.get("native_button")):
                raise ManagedBrowserError(
                    "managed browser semantic button Work currently supports only native button targets"
                )
            return
        if kind is BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME:
            if bool(raw.get("is_password")):
                raise ManagedBrowserError(
                    "managed browser semantic textbox Work refuses password targets"
                )
            if not bool(raw.get("native_textbox")):
                raise ManagedBrowserError(
                    "managed browser semantic textbox Work currently supports only default/text input and textarea targets"
                )
            if bool(raw.get("disabled")):
                raise ManagedBrowserError("managed browser semantic textbox target is disabled")
            if bool(raw.get("read_only")):
                raise ManagedBrowserError("managed browser semantic textbox target is read-only")
            return
        if kind is BrowserTargetQueryKind.ACCESSIBLE_COMBOBOX_NAME:
            if not bool(raw.get("native_combobox")):
                raise ManagedBrowserError(
                    "managed browser semantic combobox Work currently supports only native select targets"
                )
            if bool(raw.get("disabled")):
                raise ManagedBrowserError("managed browser semantic combobox target is disabled")
            if bool(raw.get("multiple")):
                raise ManagedBrowserError(
                    "managed browser semantic combobox Work refuses multi-select targets"
                )
            return
        if kind is BrowserTargetQueryKind.ACCESSIBLE_LINK_NAME:
            if not bool(raw.get("native_link")):
                raise ManagedBrowserError(
                    "managed browser semantic link Work currently supports only native anchor link targets"
                )
            return
        if kind is BrowserTargetQueryKind.ACCESSIBLE_RADIO_NAME:
            if not bool(raw.get("native_radio")):
                raise ManagedBrowserError(
                    "managed browser semantic radio Work currently supports only native input[type=radio] targets"
                )
            if bool(raw.get("disabled")):
                raise ManagedBrowserError("managed browser semantic radio target is disabled")
            return
        if kind is BrowserTargetQueryKind.ACCESSIBLE_SLIDER_NAME:
            if not bool(raw.get("native_slider")):
                raise ManagedBrowserError(
                    "managed browser semantic slider Work currently supports only native input[type=range] targets"
                )
            if bool(raw.get("disabled")):
                raise ManagedBrowserError("managed browser semantic slider target is disabled")
            return
        if kind is BrowserTargetQueryKind.ACCESSIBLE_SWITCH_NAME:
            if not bool(raw.get("native_switch")):
                raise ManagedBrowserError(
                    "managed browser semantic switch Work currently supports only role=switch targets"
                )
            if bool(raw.get("disabled")):
                raise ManagedBrowserError("managed browser semantic switch target is disabled")
            return
        if kind is BrowserTargetQueryKind.ACCESSIBLE_TAB_NAME:
            if not bool(raw.get("native_tab")):
                raise ManagedBrowserError(
                    "managed browser semantic tab Work currently supports only role=tab targets"
                )
            if bool(raw.get("disabled")):
                raise ManagedBrowserError("managed browser semantic tab target is disabled")
            return
        if kind is BrowserTargetQueryKind.ACCESSIBLE_MENUITEM_NAME:
            if not bool(raw.get("native_menuitem")):
                raise ManagedBrowserError(
                    "managed browser semantic menuitem Work currently supports only role=menuitem targets"
                )
            if bool(raw.get("disabled")):
                raise ManagedBrowserError("managed browser semantic menuitem target is disabled")
            return
        raise ManagedBrowserError(f"unsupported semantic target query: {kind.value}")

    @staticmethod
    def _semantic_target(
        session: Any,
        page_id: str,
        query: BrowserTargetQuery,
        raw: dict[str, Any],
        *,
        current_url: str,
        observed_at: str,
    ) -> BrowserTarget:
        tag = str(raw.get("tag") or "")[:32]
        input_type = str(raw.get("input_type") or "")[:32]
        if query.kind is BrowserTargetQueryKind.ACCESSIBLE_CHECKBOX_NAME:
            role = "checkbox"
            selector_hint = "accessible_checkbox_name:exact"
        elif query.kind is BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME:
            role = "button"
            selector_hint = "accessible_button_name:exact"
        elif query.kind is BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME:
            role = "textbox"
            selector_hint = "accessible_textbox_name:exact"
        elif query.kind is BrowserTargetQueryKind.ACCESSIBLE_COMBOBOX_NAME:
            role = "combobox"
            selector_hint = "accessible_combobox_name:exact"
        elif query.kind is BrowserTargetQueryKind.ACCESSIBLE_LINK_NAME:
            role = "link"
            selector_hint = "accessible_link_name:exact"
        elif query.kind is BrowserTargetQueryKind.ACCESSIBLE_RADIO_NAME:
            role = "radio"
            selector_hint = "accessible_radio_name:exact"
        elif query.kind is BrowserTargetQueryKind.ACCESSIBLE_SLIDER_NAME:
            role = "slider"
            selector_hint = "accessible_slider_name:exact"
        elif query.kind is BrowserTargetQueryKind.ACCESSIBLE_SWITCH_NAME:
            role = "switch"
            selector_hint = "accessible_switch_name:exact"
        elif query.kind is BrowserTargetQueryKind.ACCESSIBLE_TAB_NAME:
            role = "tab"
            selector_hint = "accessible_tab_name:exact"
        elif query.kind is BrowserTargetQueryKind.ACCESSIBLE_MENUITEM_NAME:
            role = "menuitem"
            selector_hint = "accessible_menuitem_name:exact"
        else:
            raise ManagedBrowserError(
                f"unsupported semantic target query: {query.kind.value}"
            )
        identity_material = "\x1f".join(
            (
                session.identity.session_id,
                page_id,
                query.frame_id,
                current_url,
                query.kind.value,
                query.value,
                tag,
                role,
                input_type,
            )
        )
        target_id = "a11y-" + hashlib.sha256(
            identity_material.encode("utf-8")
        ).hexdigest()[:24]
        return BrowserTarget(
            session_id=session.identity.session_id,
            page_id=page_id,
            kind=BrowserTargetKind.ACCESSIBILITY_NODE,
            target_id=target_id,
            observed_at=observed_at,
            url=current_url,
            frame_id=query.frame_id,
            role=role,
            name=query.value,
            selector_hint=selector_hint,
        )
