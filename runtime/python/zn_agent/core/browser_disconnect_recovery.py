from __future__ import annotations

"""Recover a managed browser session after a provider disconnect.

NEXT-PHASE §6 "recovery after browser drift or restart" gap: when the
provider connection drops, the loop session used to be dead with no recovery
path. Recovery here is exactly three moves:

1. reopen a session through the same provider,
2. re-navigate to the last verified URL pin,
3. re-observe (and, when a target query was in flight, re-resolve it).

Dispatched side-effect actions are never replayed: recovery dispatches one
and only one action, a NAVIGATE to the pinned URL, and it never touches any
previously dispatched action id. After recovery the caller decides the next
step from the fresh session; each loop action's own preconditions (pinned
URL, fresh target observation) determine which steps need re-walking.

Recovery failure raises explicitly. A half-recovered session is never
returned; recovery never pretends it succeeded.
"""

from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
    BrowserProviderDisconnectedError,
    BrowserSessionOwner,
    BrowserTargetQuery,
)
from .models import utc_now

__all__ = [
    "BrowserSessionRecoveryError",
    "RecoveredBrowserSession",
    "is_provider_disconnect",
    "recover_browser_session_after_disconnect",
]


class BrowserSessionRecoveryError(RuntimeError):
    """Explicit browser session recovery failure; never a fake success."""


# Transport/session-gone message fragments recognized as a disconnect when a
# provider did not raise the explicit BrowserProviderDisconnectedError. Kept
# deliberately narrow: a slow page or a validation error must never be
# mistaken for a dead provider.
_DISCONNECT_MESSAGE_FRAGMENTS = (
    "has been closed",
    "connection closed",
    "connection lost",
    "connection reset",
    "target crashed",
    "browser disconnected",
    "transport disconnected",
    "unknown managed browser session",
    "session not found",
    "no such session",
)


def is_provider_disconnect(exc: BaseException) -> bool:
    """Return True when *exc* proves the provider connection/session is gone.

    The explicit BrowserProviderDisconnectedError and transport-level
    ConnectionError are always disconnects. Anything else is only a
    disconnect when its message matches a narrow session-gone fragment, so a
    validation failure (e.g. "browser navigation requires url") or a slow
    page never triggers a session rebuild.
    """
    if isinstance(exc, BrowserProviderDisconnectedError):
        return True
    if isinstance(exc, ConnectionError):
        return True
    message = str(exc or "").strip().lower()
    if not message:
        return False
    return any(fragment in message for fragment in _DISCONNECT_MESSAGE_FRAGMENTS)


@dataclass(frozen=True, slots=True)
class RecoveredBrowserSession:
    """A rebuilt browser session after a provider disconnect.

    ``session`` has the same shape as the browser loop session mapping
    (``session_id`` / ``url`` / ``page_id`` / ``last_observation``) plus
    recovery metadata, so loop callers can keep using it directly.
    ``dispatched_side_effect_action_ids`` is carried over untouched: those
    actions were already dispatched before the disconnect and must not be
    proposed again by the caller.
    """

    session: dict[str, Any]
    previous_session_id: str
    recovered_url: str
    target_reresolved: bool
    target_reresolve_detail: str = ""
    dispatched_side_effect_action_ids: tuple[str, ...] = ()


def _require_pin_url(session: Mapping[str, Any]) -> str:
    raw = session.get("url")
    url = str(raw or "").strip()
    if not url:
        raise BrowserSessionRecoveryError(
            "browser session recovery refused: the loop session carries no last "
            "verified URL pin to rebuild from"
        )
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise BrowserSessionRecoveryError(
            f"browser session recovery refused: last verified URL pin is not a "
            f"usable http(s) URL: {url!r}"
        )
    return url


def _normalize_pin_url(url: str) -> str:
    # Trailing-slash-insensitive so a provider that reports
    # "https://example.test/form/" still matches the pin
    # "https://example.test/form".
    return str(url or "").strip().rstrip("/")


def _close_quietly(provider: Any, session_id: str) -> None:
    session_id = str(session_id or "").strip()
    if not session_id or provider is None:
        return
    try:
        provider.close_session(session_id)
    except Exception:
        return


def _dispatch_navigate_only(provider: Any, action: BrowserAction, authority: Any) -> Any:
    # Structural guarantee: recovery rebuilds with re-navigation only. Any
    # future edit that tries to route a side-effect action through recovery
    # fails loudly here instead of silently replaying it.
    if action.kind is not BrowserActionKind.NAVIGATE:
        raise BrowserSessionRecoveryError(
            "browser session recovery refused to dispatch a non-navigation "
            f"action during rebuild: {action.kind.value}"
        )
    return provider.act(action, authority)


def _observation_summary(observation: Any) -> dict[str, str]:
    return {
        "url": str(getattr(observation, "url", "") or ""),
        "title": str(getattr(observation, "title", "") or ""),
        "load_state": str(getattr(observation, "load_state", "") or ""),
        "page_id": str(getattr(observation, "page_id", "") or ""),
    }


def recover_browser_session_after_disconnect(
    provider: Any,
    *,
    session: Mapping[str, Any],
    permission: BrowserPermissionContext,
    headless: bool = True,
    owner: BrowserSessionOwner | None = None,
    target_query: BrowserTargetQuery | None = None,
    dispatched_side_effect_action_ids: Iterable[str] = (),
) -> RecoveredBrowserSession:
    """Rebuild a dead provider session from the last verified URL pin.

    Reopen + re-navigate to the pin + fresh re-observe. Dispatches exactly
    one NAVIGATE action; previously dispatched side-effect action ids are
    carried into the recovered session untouched and never re-dispatched.
    Raises BrowserSessionRecoveryError on any failure; never returns a
    half-recovered session.
    """
    previous = dict(session or {})
    pinned_url = _require_pin_url(previous)
    if not permission.allows_action(BrowserActionKind.NAVIGATE):
        raise BrowserSessionRecoveryError(
            "browser session recovery refused: the permission does not allow navigation"
        )
    if not permission.allows_origin(pinned_url):
        raise BrowserSessionRecoveryError(
            "browser session recovery refused: the permission does not allow "
            f"the pinned origin {pinned_url!r}"
        )
    dispatched = tuple(
        str(action_id)
        for action_id in (dispatched_side_effect_action_ids or ())
        if str(action_id).strip()
    )
    previous_session_id = str(previous.get("session_id") or "").strip()

    # The old session is dead; close it best-effort so a leaked provider
    # handle does not linger. Never raises.
    _close_quietly(provider, previous_session_id)

    try:
        # The recovered session keeps the original session's owner: it is the
        # same Work/intent continuing, not a new anonymous session.
        identity = provider.open_session(
            permission=permission, headless=headless, owner=owner
        )
    except Exception as exc:
        raise BrowserSessionRecoveryError(
            "browser session recovery failed: the provider could not reopen a "
            f"session: {type(exc).__name__}: {exc}"
        ) from exc
    new_session_id = str(getattr(identity, "session_id", "") or "").strip()
    if not new_session_id:
        _close_quietly(provider, new_session_id)
        raise BrowserSessionRecoveryError(
            "browser session recovery failed: the provider returned a session "
            "without a session id"
        )

    try:
        pre = provider.observe(new_session_id)
        page_id = str(getattr(pre, "page_id", "") or "")
        action = BrowserAction.create(
            session_id=new_session_id,
            kind=BrowserActionKind.NAVIGATE,
            page_id=page_id,
            args={"url": pinned_url},
            expected={"url_equals": pinned_url},
        )
        authority = BrowserActionAuthority.from_observation(action, pre, permission)
        effect = _dispatch_navigate_only(provider, action, authority)
        if not effect.success:
            raise BrowserSessionRecoveryError(
                "browser session recovery failed: re-navigation to the last "
                f"verified URL did not verify: {effect.error or 'unknown error'}"
            )
        if _normalize_pin_url(str(effect.url_after or "")) != _normalize_pin_url(pinned_url):
            raise BrowserSessionRecoveryError(
                "browser session recovery failed: re-navigation landed on "
                f"{str(effect.url_after or '')!r}, expected the last verified "
                f"URL {pinned_url!r}"
            )
        post = provider.observe(new_session_id)
    except BrowserSessionRecoveryError:
        _close_quietly(provider, new_session_id)
        raise
    except Exception as exc:
        _close_quietly(provider, new_session_id)
        raise BrowserSessionRecoveryError(
            "browser session recovery failed during rebuild: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    summary = _observation_summary(post)
    if _normalize_pin_url(summary["url"]) != _normalize_pin_url(pinned_url):
        _close_quietly(provider, new_session_id)
        raise BrowserSessionRecoveryError(
            "browser session recovery failed: fresh observation URL "
            f"{summary['url']!r} does not match the last verified URL {pinned_url!r}"
        )

    # Re-resolve the in-flight target query against the rebuilt page. This is
    # best-effort evidence: a target that no longer exists is for the caller's
    # action preconditions to judge, not a reason to declare the session dead.
    target_reresolved = False
    target_detail = "no target query was in flight"
    if target_query is not None:
        try:
            provider.observe_target(
                new_session_id,
                target_query,
                page_id=summary["page_id"],
            )
            target_reresolved = True
            target_detail = (
                f"target re-resolved on the rebuilt page "
                f"({target_query.kind.value}={target_query.value!r})"
            )
        except Exception as exc:
            target_detail = (
                f"target could not be re-resolved on the rebuilt page "
                f"({target_query.kind.value}={target_query.value!r}): "
                f"{type(exc).__name__}: {exc}"
            )

    recovered: dict[str, Any] = {
        "session_id": new_session_id,
        "url": summary["url"],
        "page_id": summary["page_id"],
        "last_observation": summary,
        "recovered_from_disconnect": True,
        "recovered_at": utc_now(),
        "previous_session_id": previous_session_id,
        "target_reresolved": target_reresolved,
        "target_reresolve_detail": target_detail,
        "dispatched_side_effect_action_ids": dispatched,
    }
    # Multi-page retention context (M-10) survives the rebuild: the pin, not
    # the dead provider handle, is the continuity anchor.
    carried = previous.get("multipage_context")
    if carried:
        recovered["multipage_context"] = carried

    return RecoveredBrowserSession(
        session=recovered,
        previous_session_id=previous_session_id,
        recovered_url=summary["url"],
        target_reresolved=target_reresolved,
        target_reresolve_detail=target_detail,
        dispatched_side_effect_action_ids=dispatched,
    )
