from __future__ import annotations

"""Bounded semantic target sensing for resident-owned managed Chromium.

The first semantic slice is intentionally smaller than a general accessibility
query language: one exact accessible name, one native checkbox role, main frame
only. Provider locators may compute the accessibility name internally, but ZN
never receives page-wide text or a candidate list. Zero or multiple exact matches
fail closed before any interaction authority can be formed.
"""

import hashlib
from typing import Any

from .browser import (
    BrowserTarget,
    BrowserTargetKind,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from .managed_browser import (
    ManagedBrowserError,
    PlaywrightManagedBrowser,
    _ManagedTargetBinding,
)


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

_EXACT_NODE_EQUAL_SCRIPT = r"""
(element, other) => Boolean(element && other && element === other)
"""


class SemanticPlaywrightManagedBrowser(PlaywrightManagedBrowser):
    """Playwright adapter with one fail-closed accessible checkbox query."""

    def _acquire_target_binding(
        self,
        session: Any,
        page_id: str,
        query: BrowserTargetQuery,
        *,
        observed_at: str,
    ) -> _ManagedTargetBinding:
        if query.kind is not BrowserTargetQueryKind.ACCESSIBLE_CHECKBOX_NAME:
            return super()._acquire_target_binding(
                session,
                page_id,
                query,
                observed_at=observed_at,
            )
        if query.frame_id != "main":
            raise ManagedBrowserError(
                "managed browser semantic checkbox sensing currently supports only the main frame"
            )

        page = self._page(session, page_id)
        try:
            locator = page.get_by_role("checkbox", name=query.value, exact=True)
            count = int(locator.count())
        except Exception as exc:
            raise ManagedBrowserError(
                f"failed to resolve managed browser semantic checkbox target: {type(exc).__name__}: {exc}"
            ) from exc
        if count == 0:
            raise ManagedBrowserError("managed browser semantic checkbox target was not found")
        if count != 1:
            raise ManagedBrowserError("managed browser semantic checkbox target is ambiguous")

        element = None
        keep_element = False
        try:
            element = locator.element_handle()
            if element is None:
                raise ManagedBrowserError(
                    "managed browser semantic checkbox target changed while provider evidence was acquired"
                )
            raw = element.evaluate(_SEMANTIC_CHECKBOX_EVIDENCE_SCRIPT)
            self._validate_semantic_checkbox_evidence(raw)
            current_url = str(getattr(page, "url", "") or "")
            target = self._semantic_checkbox_target(
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
                f"failed to observe managed browser semantic checkbox target: {type(exc).__name__}: {exc}"
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
        if (
            binding is None
            or binding.query.kind is not BrowserTargetQueryKind.ACCESSIBLE_CHECKBOX_NAME
        ):
            return super()._revalidate_target_binding(session, page_id, target)
        if binding.target != target:
            raise ManagedBrowserError(
                "browser semantic target provider evidence does not match the current action target"
            )

        page = self._page(session, page_id)
        fresh = None
        try:
            locator = page.get_by_role(
                "checkbox",
                name=binding.query.value,
                exact=True,
            )
            count = int(locator.count())
            if count != 1:
                if count == 0:
                    raise ManagedBrowserError(
                        "browser semantic checkbox target changed before dispatch: target was not found"
                    )
                raise ManagedBrowserError(
                    "browser semantic checkbox target changed before dispatch: target is ambiguous"
                )
            fresh = locator.element_handle()
            if fresh is None:
                raise ManagedBrowserError(
                    "browser semantic checkbox target changed before dispatch"
                )
            raw = fresh.evaluate(_SEMANTIC_CHECKBOX_EVIDENCE_SCRIPT)
            self._validate_semantic_checkbox_evidence(raw)
            same_exact_node = bool(
                binding.handle.evaluate(_EXACT_NODE_EQUAL_SCRIPT, fresh)
            )
            if not same_exact_node:
                raise ManagedBrowserError(
                    "browser semantic checkbox target changed before dispatch"
                )
        except ManagedBrowserError:
            raise
        except Exception as exc:
            raise ManagedBrowserError(
                f"browser semantic checkbox target changed before dispatch: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            if fresh is not None:
                self._best_effort_dispose_handle(fresh)
        return binding

    @staticmethod
    def _validate_semantic_checkbox_evidence(raw: Any) -> None:
        if not isinstance(raw, dict):
            raise ManagedBrowserError(
                "managed browser semantic checkbox provider returned invalid evidence"
            )
        if not bool(raw.get("connected")):
            raise ManagedBrowserError("managed browser semantic checkbox target is detached")
        if not bool(raw.get("visible")):
            raise ManagedBrowserError("managed browser semantic checkbox target is not visible")
        if not bool(raw.get("native_checkbox")):
            raise ManagedBrowserError(
                "managed browser semantic checkbox Work currently supports only native input[type=checkbox] targets"
            )

    @staticmethod
    def _semantic_checkbox_target(
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
        identity_material = "\x1f".join(
            (
                session.identity.session_id,
                page_id,
                query.frame_id,
                current_url,
                query.kind.value,
                query.value,
                tag,
                "checkbox",
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
            role="checkbox",
            name=query.value,
            selector_hint="accessible_checkbox_name:exact",
        )
