from __future__ import annotations

"""Verified stateless BrowserScene command clicks with fresh absence evidence.

Playwright owns provider click/actionability mechanics. ZN owns command routing,
exact retained target identity, same-page authority, fresh world-state proof,
privacy-safe evidence, and fail-closed scene/topology semantics.
"""

import hashlib
from typing import Any

from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
)
from .managed_browser import ManagedBrowserError
from .models import utc_now


_SCENE_PREFIX = "browser_scene:"
_COMMAND_KEY = "target_absent_equals"
_TRIGGER_ROLES = frozenset({"button", "menuitem"})
_MAX_ROLE = 64
_MAX_NAME = 256
_POSTCONDITION = "exact_semantic_target_absent_in_fresh_scene_after_command_click"

_TRIGGER_STATE_SCRIPT = r"""
(element) => {
  const attr = (name) => String(
    element && element.getAttribute ? (element.getAttribute(name) || "") : ""
  ).trim().toLowerCase();
  return {
    connected: Boolean(element && element.isConnected),
    aria_pressed: attr("aria-pressed"),
    aria_expanded: attr("aria-expanded"),
    aria_haspopup: attr("aria-haspopup"),
  };
}
"""

_HISTORY_MARKER_SCRIPT = r"""
() => {
  const current = globalThis.navigation && globalThis.navigation.currentEntry
    ? globalThis.navigation.currentEntry
    : null;
  return {
    length: Number(globalThis.history && globalThis.history.length || 0),
    entry_key: String(current && current.key || ""),
    entry_id: String(current && current.id || ""),
  };
}
"""


class PlaywrightBrowserSceneCommandMixin:
    """Execute one exact same-page command only after fresh disappearance proof."""

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence:
        if not self._scene_command_is_action(action):
            return super().act(action, authority)

        session = self._session(action.session_id)
        try:
            descriptor = self._scene_command_validate_shape(action)
            self._validate_authority(session, action, authority)
            if not authority.permission.allow_page_interaction:
                raise ManagedBrowserError(
                    "BrowserScene stateless command requires page-interaction permission"
                )

            assert action.target is not None
            binding = self._scene_action_binding(
                session,
                action.target.target_id,
                page_id=action.page_id or action.target.page_id,
                expected_target=action.target,
            )
            # First exact-node proof before evaluating the broader precondition.
            # A second proof happens at the last possible point before click.
            self._scene_revalidate_binding(session, binding)
            return self._scene_command_click(
                session,
                action,
                binding,
                descriptor=descriptor,
            )
        except ManagedBrowserError as exc:
            return self._failure(action, error=f"ManagedBrowserError: {exc}")
        except Exception as exc:
            # Arbitrary provider exception text can contain user-visible labels.
            # Keep failures bounded to their type and this ZN-owned contract.
            return self._failure(
                action,
                error=(
                    f"{type(exc).__name__}: "
                    "BrowserScene stateless command pre-dispatch verification failed"
                ),
            )

    @staticmethod
    def _scene_command_is_action(action: BrowserAction) -> bool:
        return bool(
            action.kind is BrowserActionKind.CLICK
            and action.target is not None
            and str(action.target.selector_hint or "").startswith(_SCENE_PREFIX)
            and _COMMAND_KEY in action.expected
        )

    def _scene_command_validate_shape(
        self,
        action: BrowserAction,
    ) -> tuple[str, str]:
        if action.target is None:
            raise ManagedBrowserError(
                "BrowserScene stateless command requires an exact current trigger"
            )
        self._scene_action_exact_keys(action.args, set(), "CLICK args")
        self._scene_action_exact_keys(
            action.expected,
            {_COMMAND_KEY},
            "CLICK expected",
        )

        descriptor = action.expected.get(_COMMAND_KEY)
        if not isinstance(descriptor, dict):
            raise ManagedBrowserError(
                "target_absent_equals must be an object with only role and accessible_name"
            )
        self._scene_action_exact_keys(
            descriptor,
            {"role", "accessible_name"},
            "CLICK expected.target_absent_equals",
        )
        role = self._scene_command_exact_text(
            descriptor.get("role"),
            label="target_absent_equals.role",
            max_length=_MAX_ROLE,
        )
        name = self._scene_command_exact_text(
            descriptor.get("accessible_name"),
            label="target_absent_equals.accessible_name",
            max_length=_MAX_NAME,
        )
        return role, name

    @staticmethod
    def _scene_command_exact_text(
        raw: Any,
        *,
        label: str,
        max_length: int,
    ) -> str:
        if not isinstance(raw, str) or not raw:
            raise ManagedBrowserError(f"{label} must be a non-empty string")
        if raw != raw.strip():
            raise ManagedBrowserError(
                f"{label} must not contain leading or trailing whitespace"
            )
        if len(raw) > max_length:
            raise ManagedBrowserError(f"{label} exceeds the bounded semantic length")
        if any(ord(char) < 32 or ord(char) == 127 for char in raw):
            raise ManagedBrowserError(f"{label} contains control characters")
        return raw

    def _scene_command_click(
        self,
        session: Any,
        action: BrowserAction,
        binding: Any,
        *,
        descriptor: tuple[str, str],
    ) -> BrowserEffectEvidence:
        completion_role, completion_name = descriptor
        trigger_role = str(binding.scene_target.role or "")
        if trigger_role not in _TRIGGER_ROLES:
            raise ManagedBrowserError(
                "BrowserScene stateless command supports button/menuitem triggers only"
            )
        if bool(getattr(binding.scene_target, "sensitive", False)) and not (
            session.permission.allow_sensitive_fields
        ):
            raise ManagedBrowserError(
                "BrowserScene stateless command trigger is sensitive and not authorized"
            )
        if str(getattr(binding.scene_target, "href", "") or ""):
            raise ManagedBrowserError(
                "BrowserScene stateless command refuses link-backed command triggers"
            )
        if not bool(getattr(binding.scene_target, "enabled", True)):
            raise ManagedBrowserError(
                "BrowserScene stateless command trigger is disabled"
            )
        self._scene_command_require_stateless_trigger(binding)

        page_state = self._scene_state(session).page_scenes.get(binding.page_id)
        if page_state is None:
            raise ManagedBrowserError(
                "BrowserScene stateless command requires a current BrowserScene"
            )
        before_scene = page_state.scene
        if bool(getattr(before_scene, "truncated", False)):
            raise ManagedBrowserError(
                "BrowserScene stateless command requires a non-truncated current scene"
            )
        if str(getattr(before_scene, "page_id", binding.page_id) or "") != binding.page_id:
            raise ManagedBrowserError(
                "BrowserScene stateless command scene/page identity is inconsistent"
            )

        before_matches = self._scene_command_matches(
            before_scene,
            completion_role,
            completion_name,
            allow_sensitive_fields=session.permission.allow_sensitive_fields,
        )
        if len(before_matches) == 0:
            raise ManagedBrowserError(
                "BrowserScene stateless command completion target is already absent"
            )
        if len(before_matches) != 1:
            raise ManagedBrowserError(
                "BrowserScene stateless command completion target is ambiguous"
            )

        page = self._page(session, binding.page_id)
        before_url = str(getattr(page, "url", "") or "")
        self._require_url_allowed(before_url, session.permission)
        if str(getattr(before_scene, "url", before_url) or "") != before_url:
            raise ManagedBrowserError(
                "BrowserScene stateless command current scene URL is stale"
            )

        provider_pages_before = self._scene_action_provider_pages(session)
        default_before = str(session.default_page_id or "")
        history_before = self._scene_command_history_marker(page)

        # The completion target came from the current scene. Revalidate its retained
        # binding when available, but never re-locate it by role/name for dispatch.
        completion_target = before_matches[0]
        completion_binding = page_state.bindings.get(
            str(getattr(completion_target, "target_id", "") or "")
        )
        if completion_binding is not None:
            self._scene_revalidate_binding(session, completion_binding)

        # Last possible exact-node revalidation. No semantic lookup, scene scan,
        # provider wait, or other mutable operation occurs between this and click.
        self._scene_revalidate_binding(session, binding)

        dispatched = False
        fresh_scene: Any | None = None
        after_count: int | None = None
        fresh_pages: tuple[Any, ...] = ()
        new_page_ids: tuple[str, ...] = ()
        topology_unchanged = False
        try:
            # Treat the provider call as possibly dispatched once entered. If it
            # raises after delivering the click, we still invalidate old authority.
            dispatched = True
            binding.handle.click()

            # Mutation invalidates the old BrowserScene immediately. Nothing below
            # can restore that scene or reuse its bindings as authority.
            self._scene_invalidate_page(
                session.identity.session_id,
                binding.page_id,
            )

            fresh_pages, new_page_ids = self._scene_command_topology_delta(
                session,
                provider_pages_before,
            )
            self._scene_command_require_same_topology(
                session,
                provider_pages_before,
                default_before=default_before,
                fresh_pages=fresh_pages,
            )
            topology_unchanged = True
            self._scene_command_require_same_page(
                session,
                page,
                binding.page_id,
                before_url,
                history_before,
            )

            try:
                fresh_scene = self.observe_scene(
                    session.identity.session_id,
                    page_id=binding.page_id,
                )
            except ManagedBrowserError:
                raise
            except Exception as exc:
                raise ManagedBrowserError(
                    "BrowserScene stateless command fresh scene acquisition failed: "
                    f"{type(exc).__name__}"
                ) from exc

            if bool(getattr(fresh_scene, "truncated", False)):
                raise ManagedBrowserError(
                    "BrowserScene stateless command cannot prove absence from a truncated fresh scene"
                )
            self._scene_command_require_same_topology(
                session,
                provider_pages_before,
                default_before=default_before,
            )
            self._scene_command_require_same_page(
                session,
                page,
                binding.page_id,
                before_url,
                history_before,
            )

            after_matches = self._scene_command_matches(
                fresh_scene,
                completion_role,
                completion_name,
                allow_sensitive_fields=session.permission.allow_sensitive_fields,
            )
            after_count = len(after_matches)
            if after_count != 0:
                raise ManagedBrowserError(
                    "BrowserScene stateless command completion target remained present"
                )
        except Exception as exc:
            if dispatched:
                # Re-read the provider topology at the failure boundary. This keeps
                # failure evidence truthful even if a page appeared while the fresh
                # BrowserScene itself was being acquired. The command never claims,
                # closes, switches, or registers such a page.
                try:
                    fresh_pages, new_page_ids = self._scene_command_topology_delta(
                        session,
                        provider_pages_before,
                    )
                    self._scene_command_require_same_topology(
                        session,
                        provider_pages_before,
                        default_before=default_before,
                        fresh_pages=fresh_pages,
                    )
                    topology_unchanged = True
                except Exception:
                    topology_unchanged = False
                # Refresh only the lower-level observation if possible. This helper
                # invalidates the scene again; it never restores the pre-click scene.
                self._scene_action_dispatched_failure(session, binding.page_id)
            error = self._scene_command_safe_error(exc, stage="post-dispatch")
            return self._scene_command_evidence(
                session,
                action,
                binding,
                completion_role=completion_role,
                completion_name=completion_name,
                before_url=before_url,
                page=page,
                before_count=1,
                after_count=after_count,
                new_page_ids=new_page_ids,
                new_page_count=len(fresh_pages),
                default_before=default_before,
                topology_unchanged=topology_unchanged,
                success=False,
                error=error,
                observed_at=(
                    str(getattr(fresh_scene, "captured_at", "") or "")
                    if fresh_scene is not None
                    else ""
                ),
            )

        assert fresh_scene is not None
        return self._scene_command_evidence(
            session,
            action,
            binding,
            completion_role=completion_role,
            completion_name=completion_name,
            before_url=before_url,
            page=page,
            before_count=1,
            after_count=0,
            new_page_ids=(),
            new_page_count=0,
            default_before=default_before,
            topology_unchanged=True,
            success=True,
            error=None,
            observed_at=str(fresh_scene.captured_at),
        )

    @staticmethod
    def _scene_command_matches(
        scene: Any,
        role: str,
        accessible_name: str,
        *,
        allow_sensitive_fields: bool,
    ) -> tuple[Any, ...]:
        return tuple(
            target
            for target in tuple(getattr(scene, "targets", ()) or ())
            if str(getattr(target, "role", "") or "") == role
            and str(getattr(target, "accessible_name", "") or "") == accessible_name
            and (
                allow_sensitive_fields
                or not bool(getattr(target, "sensitive", False))
            )
        )

    @staticmethod
    def _scene_command_name_evidence(value: str) -> dict[str, Any]:
        return {
            "name_length": len(value),
            "name_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        }

    @staticmethod
    def _scene_command_require_stateless_trigger(binding: Any) -> None:
        raw = binding.handle.evaluate(_TRIGGER_STATE_SCRIPT)
        if not isinstance(raw, dict) or not bool(raw.get("connected")):
            raise ManagedBrowserError(
                "BrowserScene stateless command trigger is detached"
            )
        if str(raw.get("aria_pressed") or ""):
            raise ManagedBrowserError(
                "BrowserScene stateless command refuses toggle-button semantics"
            )
        if str(raw.get("aria_expanded") or ""):
            raise ManagedBrowserError(
                "BrowserScene stateless command refuses expanded/collapsed control semantics"
            )
        haspopup = str(raw.get("aria_haspopup") or "")
        if haspopup and haspopup != "false":
            raise ManagedBrowserError(
                "BrowserScene stateless command refuses popup/menu/dialog opener semantics"
            )

    @staticmethod
    def _scene_command_history_marker(page: Any) -> tuple[int, str, str]:
        try:
            raw = page.evaluate(_HISTORY_MARKER_SCRIPT)
        except Exception as exc:
            raise ManagedBrowserError(
                "BrowserScene stateless command cannot observe the current history marker"
            ) from exc
        if not isinstance(raw, dict):
            raise ManagedBrowserError(
                "BrowserScene stateless command provider returned an invalid history marker"
            )
        try:
            length = int(raw.get("length"))
        except (TypeError, ValueError) as exc:
            raise ManagedBrowserError(
                "BrowserScene stateless command provider returned an invalid history length"
            ) from exc
        if length < 0:
            raise ManagedBrowserError(
                "BrowserScene stateless command provider returned an invalid history length"
            )
        return (
            length,
            str(raw.get("entry_key") or ""),
            str(raw.get("entry_id") or ""),
        )

    def _scene_command_require_same_page(
        self,
        session: Any,
        page: Any,
        page_id: str,
        before_url: str,
        history_before: tuple[int, str, str],
    ) -> None:
        if page_id not in session.pages or session.pages.get(page_id) is not page:
            raise ManagedBrowserError(
                "BrowserScene stateless command exact page identity changed"
            )
        current_url = str(getattr(page, "url", "") or "")
        self._require_url_allowed(current_url, session.permission)
        if current_url != before_url:
            raise ManagedBrowserError(
                "BrowserScene stateless command changed the top-level URL"
            )
        history_after = self._scene_command_history_marker(page)
        if history_after != history_before:
            raise ManagedBrowserError(
                "BrowserScene stateless command changed browser history state"
            )

    def _scene_command_topology_delta(
        self,
        session: Any,
        before: tuple[Any, ...],
    ) -> tuple[tuple[Any, ...], tuple[str, ...]]:
        current = self._scene_action_provider_pages(session)
        fresh = tuple(
            page
            for page in current
            if not any(page is old for old in before)
        )
        known_ids: list[str] = []
        for page in fresh:
            for page_id, registered in session.pages.items():
                if registered is page:
                    known_ids.append(page_id)
                    break
        return fresh, tuple(known_ids)

    def _scene_command_require_same_topology(
        self,
        session: Any,
        before: tuple[Any, ...],
        *,
        default_before: str,
        fresh_pages: tuple[Any, ...] | None = None,
    ) -> None:
        current = self._scene_action_provider_pages(session)
        if fresh_pages is None:
            fresh_pages = tuple(
                page
                for page in current
                if not any(page is old for old in before)
            )
        missing = tuple(
            page
            for page in before
            if not any(page is now for now in current)
        )
        if fresh_pages or missing or len(current) != len(before):
            raise ManagedBrowserError(
                "BrowserScene stateless command changed top-level page topology"
            )
        if str(session.default_page_id or "") != default_before:
            raise ManagedBrowserError(
                "BrowserScene stateless command changed the session default page"
            )

    @staticmethod
    def _scene_command_safe_error(exc: Exception, *, stage: str) -> str:
        if isinstance(exc, ManagedBrowserError):
            return f"ManagedBrowserError: {exc}"
        return (
            f"{type(exc).__name__}: "
            f"BrowserScene stateless command {stage} verification failed"
        )

    def _scene_command_evidence(
        self,
        session: Any,
        action: BrowserAction,
        binding: Any,
        *,
        completion_role: str,
        completion_name: str,
        before_url: str,
        page: Any,
        before_count: int,
        after_count: int | None,
        new_page_ids: tuple[str, ...],
        new_page_count: int,
        default_before: str,
        topology_unchanged: bool,
        success: bool,
        error: str | None,
        observed_at: str,
    ) -> BrowserEffectEvidence:
        candidate_url = str(getattr(page, "url", "") or "")
        url_after = (
            candidate_url
            if self._url_allowed(candidate_url, session.permission)
            else ""
        )
        payload = {
            "provider": session.identity.provider,
            "role": str(binding.scene_target.role or ""),
            "frame_id": str(binding.scene_target.frame_id or ""),
            "absent_target_role": completion_role,
            **self._scene_command_name_evidence(completion_name),
            "matching_target_count_before": before_count,
            "matching_target_count_after": after_count,
            "target_revalidated_before_dispatch": True,
            "dispatch_count": 1,
            "new_page_ids": list(new_page_ids),
            "new_page_count": int(new_page_count),
            "fresh_pages_unclaimed": bool(new_page_count),
            "default_page_id_before": default_before,
            "default_page_id_after": str(session.default_page_id or ""),
            "page_topology_unchanged": bool(topology_unchanged),
        }
        return BrowserEffectEvidence(
            action_id=action.action_id,
            session_id=action.session_id,
            observed_at=observed_at or utc_now(),
            success=success,
            page_id=binding.page_id,
            url_before=before_url,
            url_after=url_after,
            target_id=action.target.target_id if action.target else "",
            postcondition=_POSTCONDITION,
            data=payload,
            error=error,
        )
