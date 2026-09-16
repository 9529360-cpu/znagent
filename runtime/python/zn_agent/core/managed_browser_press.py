from __future__ import annotations

"""Bounded Enter-key submission for exact managed-browser textbox targets.

This is intentionally not a general keyboard primitive. It admits exactly one
semantic action: press ``Enter`` on a freshly revalidated non-sensitive textbox
whose current text still matches the caller-provided digest/length, then prove
an explicit same-origin URL postcondition from a fresh page observation.
"""

from typing import Any
from urllib.parse import urlsplit

from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
)
from .models import utc_now


class ManagedBrowserPressError(RuntimeError):
    pass


def _origin(value: str) -> tuple[str, str, int | None] | None:
    try:
        parsed = urlsplit(str(value or "").strip())
        scheme = str(parsed.scheme or "").lower()
        host = str(parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if scheme not in {"http", "https"} or not host:
        return None
    if port is None:
        port = 80 if scheme == "http" else 443
    return scheme, host, port


def perform_enter_press(
    owner: Any,
    session: Any,
    action: BrowserAction,
    authority: BrowserActionAuthority,
) -> BrowserEffectEvidence:
    """Press one exact Enter key and verify the explicit fresh URL result."""

    if action.kind is not BrowserActionKind.PRESS:
        raise ManagedBrowserPressError("managed browser press helper received the wrong action kind")
    if action.target is None:
        raise ManagedBrowserPressError("browser press requires a current target")
    if action.target.role != "textbox":
        raise ManagedBrowserPressError(
            "browser press currently requires a semantic textbox target"
        )
    if set(action.args) != {"key"} or action.args.get("key") != "Enter":
        raise ManagedBrowserPressError(
            "browser press first slice permits exactly the Enter key with no modifiers"
        )
    if set(action.expected) != {
        "url_equals",
        "text_length",
        "text_sha256",
    }:
        raise ManagedBrowserPressError(
            "browser Enter submission requires exact URL and current-text postconditions"
        )

    expected_url = str(action.expected.get("url_equals") or "").strip()
    expected_digest = str(action.expected.get("text_sha256") or "").strip().lower()
    expected_length = action.expected.get("text_length")
    if not expected_url:
        raise ManagedBrowserPressError(
            "browser Enter submission requires an explicit expected URL"
        )
    if type(expected_length) is not int or expected_length <= 0:
        raise ManagedBrowserPressError(
            "browser Enter submission requires a positive expected text length"
        )
    if (
        len(expected_digest) != 64
        or any(char not in "0123456789abcdef" for char in expected_digest)
    ):
        raise ManagedBrowserPressError(
            "browser Enter submission requires a SHA-256 text digest"
        )

    owner._validate_authority(session, action, authority)
    owner._require_url_allowed(expected_url, session.permission)

    page_id = action.page_id or action.target.page_id or owner._default_page_id(session)
    page = owner._page(session, page_id)
    binding = owner._revalidate_target_binding(session, page_id, action.target)
    before_url = str(getattr(page, "url", "") or "")
    if before_url == expected_url:
        raise ManagedBrowserPressError(
            "browser Enter expected URL is already observed before dispatch"
        )
    before_origin = _origin(before_url)
    expected_origin = _origin(expected_url)
    if before_origin is None or expected_origin is None or before_origin != expected_origin:
        raise ManagedBrowserPressError(
            "browser Enter submission requires a same-origin expected URL"
        )

    current_text = owner._read_target_text_state(binding.handle)
    current_length = int(current_text.get("text_length") or -1)
    current_digest = str(current_text.get("text_sha256") or "")
    if current_length != expected_length or current_digest != expected_digest:
        raise ManagedBrowserPressError(
            "browser Enter textbox content changed before dispatch"
        )

    try:
        binding.handle.press("Enter")
    except Exception as exc:
        owner._refresh_page_observation_after_failed_mutation(session, page_id)
        raise ManagedBrowserPressError(
            f"managed browser Enter dispatch failed: {type(exc).__name__}: {exc}"
        ) from exc

    observed_at = utc_now()
    try:
        observation = owner._capture(
            session,
            page_id,
            captured_at=observed_at,
        )
        owner._require_url_allowed(observation.url, session.permission)
    except Exception as exc:
        owner._refresh_page_observation_after_failed_mutation(session, page_id)
        raise ManagedBrowserPressError(
            "managed browser Enter postcondition could not be observed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    data = {
        "provider": session.identity.provider,
        "target_revalidated_before_dispatch": True,
        "text_revalidated_before_dispatch": True,
        "press_sent": True,
        "key": "Enter",
        "expected_url": expected_url,
        "expected_text_length": expected_length,
        "expected_text_sha256": expected_digest,
    }
    postcondition = "url_equals_after_fresh_semantic_textbox_enter"
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
            error="browser Enter postcondition did not match observed URL",
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


class PlaywrightBrowserPressMixin:
    """Add the bounded PRESS contract to semantic managed-browser adapters."""

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        if action.kind is not BrowserActionKind.PRESS:
            return super().act(action, authority)
        try:
            session = self._session(action.session_id)
            return perform_enter_press(self, session, action, authority)
        except Exception as exc:
            return self._failure(
                action,
                error=f"{type(exc).__name__}: {exc}",
            )
