from __future__ import annotations

"""Model-led Work loop proposals for browser semantic actions.

The generic Action Fabric loop owns the proposal/completion envelopes, the
bounded step budget and the completion-evidence rules. This module adds the
browser half of that loop without touching the browser provider: every step
runs through :func:`browser_semantic_action.execute_fresh_semantic_action`
(fresh observation + URL pin + no replay of a dispatched side effect) and is
followed by an independent fresh post-step observation.

Permission is never model-supplied. The caller (event payload or a
resident-owned attribute) provides one
:class:`~zn_agent.core.browser.BrowserPermissionContext`; the model only
proposes targets and action arguments. Every dispatch re-checks that
context through :class:`BrowserActionAuthority`, exactly as the existing
browser Body paths do.
"""

import uuid
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit

from .action_execution import (
    ActionDescriptor,
    ActionExecution,
    ActionObservation,
    ActionRequest,
    ActionVerification,
)
from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserEffectEvidence,
    BrowserPermissionContext,
    BrowserTargetQuery,
    BrowserTargetQueryKind,
)
from .browser_semantic_action import execute_fresh_semantic_action
from .models import utc_now


@dataclass(frozen=True, slots=True)
class BrowserLoopActionSpec:
    action_id: str
    kind: BrowserActionKind | None
    query_kind: BrowserTargetQueryKind | None
    effect_class: str
    description: str
    required_args: tuple[str, ...] = ()
    optional_args: tuple[str, ...] = ()


BROWSER_LOOP_ACTIONS: tuple[BrowserLoopActionSpec, ...] = (
    BrowserLoopActionSpec(
        action_id="browser.navigate",
        kind=BrowserActionKind.NAVIGATE,
        query_kind=None,
        effect_class="potential_side_effect",
        description="Open a browser session (or reuse the loop session) and navigate to one explicit URL.",
        required_args=("url",),
        optional_args=("expected_url",),
    ),
    BrowserLoopActionSpec(
        action_id="browser.observe",
        kind=None,
        query_kind=None,
        effect_class="read_only",
        description="Freshly observe the current loop browser page (URL, title, load state). No dispatch.",
        required_args=(),
        optional_args=(),
    ),
    BrowserLoopActionSpec(
        action_id="browser.semantic_click",
        kind=BrowserActionKind.CLICK,
        query_kind=BrowserTargetQueryKind.ACCESSIBLE_BUTTON_NAME,
        effect_class="potential_side_effect",
        description="Click one button found by exact accessible name on the currently pinned page.",
        required_args=("target_name",),
        optional_args=("expected_url_after",),
    ),
    BrowserLoopActionSpec(
        action_id="browser.semantic_type_text",
        kind=BrowserActionKind.TYPE_TEXT,
        query_kind=BrowserTargetQueryKind.ACCESSIBLE_TEXTBOX_NAME,
        effect_class="potential_side_effect",
        description="Type text into one textbox found by exact accessible name on the currently pinned page.",
        required_args=("target_name", "text"),
        optional_args=("expected_url_after",),
    ),
    BrowserLoopActionSpec(
        action_id="browser.semantic_check",
        kind=BrowserActionKind.CHECK,
        query_kind=BrowserTargetQueryKind.ACCESSIBLE_CHECKBOX_NAME,
        effect_class="potential_side_effect",
        description="Check one checkbox found by exact accessible name on the currently pinned page.",
        required_args=("target_name",),
        optional_args=("expected_url_after",),
    ),
    BrowserLoopActionSpec(
        action_id="browser.semantic_uncheck",
        kind=BrowserActionKind.UNCHECK,
        query_kind=BrowserTargetQueryKind.ACCESSIBLE_CHECKBOX_NAME,
        effect_class="potential_side_effect",
        description="Uncheck one checkbox found by exact accessible name on the currently pinned page.",
        required_args=("target_name",),
        optional_args=("expected_url_after",),
    ),
    BrowserLoopActionSpec(
        action_id="browser.semantic_select_option",
        kind=BrowserActionKind.SELECT_OPTION,
        query_kind=BrowserTargetQueryKind.ACCESSIBLE_COMBOBOX_NAME,
        effect_class="potential_side_effect",
        description="Select exactly one option (by visible label or by value, not both) in one combobox found by exact accessible name on the currently pinned page.",
        required_args=("target_name",),
        optional_args=("label", "value", "expected_url_after"),
    ),
)

_BROWSER_LOOP_SPECS = {spec.action_id: spec for spec in BROWSER_LOOP_ACTIONS}

_PERMISSION_BOOL_KEYS = (
    "allow_navigation",
    "allow_page_interaction",
    "allow_text_entry",
    "allow_downloads",
    "allow_uploads",
    "allow_clipboard",
    "allow_sensitive_fields",
    "allow_private_network",
)

_MAX_TARGET_NAME = 160
_MAX_TEXT = 4000
_MAX_URL = 2048


def browser_loop_spec(action_id: str) -> BrowserLoopActionSpec | None:
    return _BROWSER_LOOP_SPECS.get(str(action_id or "").strip())


def browser_loop_catalog() -> list[dict[str, Any]]:
    """Cognition-context rows in the same shape as Action Fabric rows."""
    rows: list[dict[str, Any]] = []
    for spec in BROWSER_LOOP_ACTIONS:
        properties: dict[str, Any] = {}
        for name in spec.required_args:
            properties[name] = {"type": "string"}
        for name in spec.optional_args:
            properties[name] = {"type": "string"}
        rows.append(
            {
                "action_id": spec.action_id,
                "provider": "zn.browser",
                "description": spec.description,
                "arguments_schema": {
                    "type": "object",
                    "required": list(spec.required_args),
                    "properties": properties,
                    "additionalProperties": False,
                },
                "effect_class": spec.effect_class,
                "preconditions": (
                    ["browser session is open (propose browser.navigate first)"]
                    if spec.kind is not None and spec.action_id != "browser.navigate"
                    else ["browser permission context is provided by the caller"]
                ),
                "verification": ["fresh post-step page observation", "URL pin check"],
            }
        )
    return rows


def parse_browser_permission(raw: Any) -> BrowserPermissionContext | None:
    """Build a caller-owned permission context from an event-payload dict.

    Returns None when no permission was supplied. Unknown keys are ignored;
    malformed values fail closed with ValueError instead of widening access.
    """
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("browser_permission must be an object")
    kwargs: dict[str, Any] = {}
    for key in _PERMISSION_BOOL_KEYS:
        if key in raw:
            value = raw.get(key)
            if type(value) is not bool:
                raise ValueError(f"browser_permission.{key} must be a boolean")
            kwargs[key] = value
    if "allowed_origins" in raw:
        origins = raw.get("allowed_origins")
        if not isinstance(origins, (list, tuple)) or not all(
            isinstance(item, str) for item in origins
        ):
            raise ValueError("browser_permission.allowed_origins must be a list of strings")
        kwargs["allowed_origins"] = tuple(origins)
    return BrowserPermissionContext(**kwargs)


@dataclass(frozen=True, slots=True)
class BrowserLoopStepResult:
    execution: ActionExecution
    session: dict[str, Any]


def _require_http_url(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"browser loop {label} must be a string URL")
    url = value.strip()
    if not url or len(url) > _MAX_URL:
        raise ValueError(f"browser loop {label} must be a non-empty URL")
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"browser loop {label} must be an http(s) URL")
    return url


def _require_clean_string(value: Any, *, label: str, max_len: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"browser loop {label} must be a string")
    text = value.strip() if label != "text" else value
    if not text:
        raise ValueError(f"browser loop {label} must not be empty")
    if len(text) > max_len:
        raise ValueError(f"browser loop {label} is too long")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError(f"browser loop {label} contains control characters")
    return text


def validate_browser_loop_arguments(
    spec: BrowserLoopActionSpec,
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize one model proposal; unknown arguments are rejected."""
    if not isinstance(arguments, Mapping):
        raise ValueError("browser loop arguments must be an object")
    allowed = set(spec.required_args) | set(spec.optional_args)
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        raise ValueError(
            f"browser loop {spec.action_id} rejects unknown arguments: {', '.join(unknown)}"
        )
    normalized: dict[str, Any] = {}
    for name in spec.required_args:
        if name not in arguments:
            raise ValueError(f"browser loop {spec.action_id} requires {name}")
    if "url" in spec.required_args or "url" in spec.optional_args:
        if "url" in arguments:
            normalized["url"] = _require_http_url(arguments.get("url"), label="url")
    if "expected_url" in arguments:
        normalized["expected_url"] = _require_http_url(
            arguments.get("expected_url"), label="expected_url"
        )
    if "expected_url_after" in arguments:
        normalized["expected_url_after"] = _require_http_url(
            arguments.get("expected_url_after"), label="expected_url_after"
        )
    if "target_name" in arguments:
        normalized["target_name"] = _require_clean_string(
            arguments.get("target_name"), label="target_name", max_len=_MAX_TARGET_NAME
        )
    if "text" in arguments:
        if not isinstance(arguments.get("text"), str) or not arguments.get("text"):
            raise ValueError("browser loop browser.semantic_type_text requires non-empty text")
        if len(str(arguments.get("text"))) > _MAX_TEXT:
            raise ValueError("browser loop text is too long")
        normalized["text"] = str(arguments.get("text"))
    if spec.action_id == "browser.semantic_select_option":
        has_label = "label" in arguments
        has_value = "value" in arguments
        if has_label == has_value:
            raise ValueError(
                "browser loop browser.semantic_select_option requires exactly one of label/value"
            )
        key = "label" if has_label else "value"
        normalized[key] = _require_clean_string(
            arguments.get(key), label=key, max_len=256
        )
    return normalized


def _observation_summary(observation: Any) -> dict[str, Any]:
    return {
        "url": str(getattr(observation, "url", "") or ""),
        "title": str(getattr(observation, "title", "") or ""),
        "load_state": str(getattr(observation, "load_state", "") or ""),
        "page_id": str(getattr(observation, "page_id", "") or ""),
    }


def _session_from_observation(session_id: str, observation: Any) -> dict[str, Any]:
    summary = _observation_summary(observation)
    return {
        "session_id": str(session_id),
        "url": summary["url"],
        "page_id": summary["page_id"],
        "last_observation": summary,
    }


def _build_execution(
    *,
    spec: BrowserLoopActionSpec,
    arguments: Mapping[str, Any],
    success: bool,
    reason: str,
    evidence: Mapping[str, Any],
    observation_data: Mapping[str, Any],
    error: str | None = None,
) -> ActionExecution:
    verification = ActionVerification(
        status="verified" if success else "failed",
        reason=reason,
        evidence=dict(evidence),
    )
    request = ActionRequest(spec.action_id, dict(arguments))
    descriptor = ActionDescriptor(
        action_id=spec.action_id,
        provider="zn.browser",
        description=spec.description,
        effect_class=spec.effect_class,  # type: ignore[arg-type]
    )
    return ActionExecution(
        execution_id=f"browser-{uuid.uuid4().hex[:12]}",
        request=request,
        descriptor=descriptor,
        status="verified" if success else "failed",
        verification=verification,
        observations=(
            ActionObservation(
                action_id=spec.action_id,
                source="browser_post_verification",
                data=dict(observation_data),
            ),
        ),
        error=None if success else (error or reason),
    )


def _failed_step(
    *,
    spec: BrowserLoopActionSpec,
    arguments: Mapping[str, Any],
    session: Mapping[str, Any],
    reason: str,
    evidence: Mapping[str, Any] | None = None,
    observation_data: Mapping[str, Any] | None = None,
) -> BrowserLoopStepResult:
    return BrowserLoopStepResult(
        execution=_build_execution(
            spec=spec,
            arguments=arguments,
            success=False,
            reason=reason,
            evidence=dict(evidence or {}),
            observation_data=dict(observation_data or {}),
            error=reason,
        ),
        session=dict(session),
    )


def close_browser_loop_session(provider: Any, session: Mapping[str, Any]) -> None:
    """Best-effort close of a loop browser session; never raises."""
    session_id = str(session.get("session_id") or "").strip()
    if not session_id or provider is None:
        return
    try:
        provider.close_session(session_id)
    except Exception:
        return


def execute_browser_loop_step(
    provider: Any,
    *,
    session: Mapping[str, Any] | None,
    permission: BrowserPermissionContext,
    action_id: str,
    arguments: Mapping[str, Any],
) -> BrowserLoopStepResult:
    """Execute one validated browser proposal with post-step verification.

    Single-shot: a dispatched or uncertain effect is never re-dispatched.
    On URL drift (before dispatch or at post-step verification) the step
    fails, the session pin is refreshed from the fresh observation, and the
    caller must decide again from fresh state instead of continuing blindly.
    """
    spec = browser_loop_spec(action_id)
    if spec is None:
        raise ValueError(f"unknown browser loop action: {action_id}")
    normalized = validate_browser_loop_arguments(spec, arguments)
    current = dict(session or {})
    session_id = str(current.get("session_id") or "").strip()

    try:
        if spec.action_id == "browser.navigate":
            return _execute_navigate(
                provider,
                spec=spec,
                normalized=normalized,
                permission=permission,
                session=current,
                session_id=session_id,
            )
        if spec.action_id == "browser.observe":
            return _execute_observe(
                provider,
                spec=spec,
                normalized=normalized,
                permission=permission,
                session=current,
                session_id=session_id,
            )
        return _execute_semantic(
            provider,
            spec=spec,
            normalized=normalized,
            permission=permission,
            session=current,
            session_id=session_id,
        )
    except Exception as exc:
        # An unexpected provider failure is a failed step, never a reason to
        # re-dispatch the same proposal.
        return _failed_step(
            spec=spec,
            arguments=normalized,
            session=current,
            reason=f"browser loop step failed: {type(exc).__name__}: {exc}",
        )


def _open_session(provider: Any, *, permission: BrowserPermissionContext) -> Any:
    return provider.open_session(permission=permission, headless=True)


def _execute_navigate(
    provider: Any,
    *,
    spec: BrowserLoopActionSpec,
    normalized: Mapping[str, Any],
    permission: BrowserPermissionContext,
    session: Mapping[str, Any],
    session_id: str,
) -> BrowserLoopStepResult:
    url = str(normalized["url"])
    expected_url = str(normalized.get("expected_url") or url)
    if not permission.allows_action(BrowserActionKind.NAVIGATE):
        return _failed_step(
            spec=spec,
            arguments=normalized,
            session=session,
            reason="browser permission does not allow navigation",
        )
    if not permission.allows_origin(url):
        return _failed_step(
            spec=spec,
            arguments=normalized,
            session=session,
            reason="browser permission does not allow the requested navigation origin",
        )
    try:
        if session_id:
            try:
                pre = provider.observe(session_id)
                page_id = str(pre.page_id or "")
            except Exception as exc:
                return _failed_step(
                    spec=spec,
                    arguments=normalized,
                    session=session,
                    reason=f"browser loop could not re-observe the existing session before navigation: {type(exc).__name__}: {exc}",
                )
        else:
            opened = _open_session(provider, permission=permission)
            session_id = str(opened.session_id)
            pre = provider.observe(session_id)
            page_id = str(pre.page_id or "")
        action = BrowserAction.create(
            session_id=session_id,
            kind=BrowserActionKind.NAVIGATE,
            page_id=page_id,
            args={"url": url},
            expected={"url_equals": expected_url},
        )
        authority = BrowserActionAuthority.from_observation(action, pre, permission)
        evidence = provider.act(action, authority)
    except Exception as exc:
        return _failed_step(
            spec=spec,
            arguments=normalized,
            session=session,
            reason=f"browser navigation dispatch failed: {type(exc).__name__}: {exc}",
        )
    if not evidence.success:
        return _failed_step(
            spec=spec,
            arguments=normalized,
            session=session,
            reason=evidence.error or "browser navigation failed",
            evidence={"browser_effect": _effect_dict(evidence)},
        )
    try:
        post = provider.observe(session_id)
    except Exception as exc:
        return _failed_step(
            spec=spec,
            arguments=normalized,
            session=session,
            reason=f"browser post-step verification observe failed after navigation: {type(exc).__name__}: {exc}",
            evidence={"browser_effect": _effect_dict(evidence)},
        )
    fresh_session = _session_from_observation(session_id, post)
    if str(post.url or "") != expected_url:
        return _failed_step(
            spec=spec,
            arguments=normalized,
            session=fresh_session,
            reason=(
                "browser post-step verification failed: observed URL "
                f"{str(post.url or '')!r} != expected URL {expected_url!r} after navigation"
            ),
            evidence={"browser_effect": _effect_dict(evidence)},
            observation_data=_observation_summary(post),
        )
    return BrowserLoopStepResult(
        execution=_build_execution(
            spec=spec,
            arguments=normalized,
            success=True,
            reason="browser navigation verified by fresh post-step observation",
            evidence={
                "browser_effect": _effect_dict(evidence),
                "post_verification": _observation_summary(post),
            },
            observation_data=_observation_summary(post),
        ),
        session=fresh_session,
    )


def _execute_observe(
    provider: Any,
    *,
    spec: BrowserLoopActionSpec,
    normalized: Mapping[str, Any],
    permission: BrowserPermissionContext,
    session: Mapping[str, Any],
    session_id: str,
) -> BrowserLoopStepResult:
    try:
        if not session_id:
            opened = _open_session(provider, permission=permission)
            session_id = str(opened.session_id)
        observed = provider.observe(session_id)
    except Exception as exc:
        return _failed_step(
            spec=spec,
            arguments=normalized,
            session=session,
            reason=f"browser observe failed: {type(exc).__name__}: {exc}",
        )
    fresh_session = _session_from_observation(session_id, observed)
    return BrowserLoopStepResult(
        execution=_build_execution(
            spec=spec,
            arguments=normalized,
            success=True,
            reason="browser page freshly observed",
            evidence={"post_verification": _observation_summary(observed)},
            observation_data=_observation_summary(observed),
        ),
        session=fresh_session,
    )


def _execute_semantic(
    provider: Any,
    *,
    spec: BrowserLoopActionSpec,
    normalized: Mapping[str, Any],
    permission: BrowserPermissionContext,
    session: Mapping[str, Any],
    session_id: str,
) -> BrowserLoopStepResult:
    assert spec.kind is not None and spec.query_kind is not None
    if not session_id:
        return _failed_step(
            spec=spec,
            arguments=normalized,
            session=session,
            reason="browser semantic action requires an open loop session; propose browser.navigate first",
        )
    pinned_url = str(session.get("url") or "").strip()
    if not pinned_url:
        return _failed_step(
            spec=spec,
            arguments=normalized,
            session=session,
            reason="browser semantic action requires a pinned URL from a verified navigation or observation",
        )
    if not permission.allows_action(spec.kind):
        return _failed_step(
            spec=spec,
            arguments=normalized,
            session=session,
            reason=f"browser permission does not allow {spec.kind.value}",
        )
    expected_url_after = str(normalized.get("expected_url_after") or pinned_url)
    if not permission.allows_origin(expected_url_after):
        return _failed_step(
            spec=spec,
            arguments=normalized,
            session=session,
            reason="browser permission does not allow the expected post-action origin",
        )
    provider_args: dict[str, Any] = {}
    if spec.action_id == "browser.semantic_type_text":
        provider_args = {"text": str(normalized["text"])}
    elif spec.action_id == "browser.semantic_select_option":
        if "label" in normalized:
            provider_args = {"label": str(normalized["label"])}
        else:
            provider_args = {"value": str(normalized["value"])}
    query = BrowserTargetQuery(
        kind=spec.query_kind,
        value=str(normalized["target_name"]),
    )
    try:
        result = execute_fresh_semantic_action(
            provider,
            session_id=session_id,
            permission=permission,
            query=query,
            kind=spec.kind,
            page_id=str(session.get("page_id") or ""),
            args=provider_args,
            expected_url_before=pinned_url,
        )
    except ValueError as exc:
        message = str(exc)
        if "URL changed before dispatch" in message:
            try:
                fresh = provider.observe(session_id)
            except Exception as observe_exc:
                return _failed_step(
                    spec=spec,
                    arguments=normalized,
                    session=session,
                    reason=(
                        "browser URL drifted before dispatch and the fresh "
                        f"re-observation also failed: {type(observe_exc).__name__}: {observe_exc}"
                    ),
                )
            fresh_session = _session_from_observation(session_id, fresh)
            return _failed_step(
                spec=spec,
                arguments=normalized,
                session=fresh_session,
                reason=(
                    "browser URL drifted before dispatch; refusing target transfer. "
                    f"Pinned URL refreshed to fresh observation {str(fresh.url or '')!r}; "
                    "decide again from the fresh state."
                ),
                observation_data=_observation_summary(fresh),
            )
        return _failed_step(
            spec=spec,
            arguments=normalized,
            session=session,
            reason=f"browser semantic action failed before dispatch: {message}",
        )
    effect = result.effect
    if not effect.success:
        # A dispatched or uncertain effect is never replayed: the failure is
        # returned as-is, with the provider evidence, and the loop moves on.
        return _failed_step(
            spec=spec,
            arguments=normalized,
            session=session,
            reason=effect.error or f"browser semantic action failed: {spec.action_id}",
            evidence={
                "browser_effect": _effect_dict(effect),
                "regrounds": result.regrounds,
            },
            observation_data=_observation_summary(result.observation),
        )
    try:
        post = provider.observe(session_id)
    except Exception as exc:
        return _failed_step(
            spec=spec,
            arguments=normalized,
            session=session,
            reason=f"browser post-step verification observe failed: {type(exc).__name__}: {exc}",
            evidence={"browser_effect": _effect_dict(effect), "regrounds": result.regrounds},
            observation_data=_observation_summary(result.observation),
        )
    fresh_session = _session_from_observation(session_id, post)
    if str(post.url or "") != expected_url_after:
        return _failed_step(
            spec=spec,
            arguments=normalized,
            session=fresh_session,
            reason=(
                "browser post-step verification failed: URL drifted after dispatch: "
                f"observed {str(post.url or '')!r} != expected {expected_url_after!r}; "
                "pinned URL refreshed to the fresh observation; decide again from the fresh state."
            ),
            evidence={"browser_effect": _effect_dict(effect), "regrounds": result.regrounds},
            observation_data=_observation_summary(post),
        )
    return BrowserLoopStepResult(
        execution=_build_execution(
            spec=spec,
            arguments=normalized,
            success=True,
            reason="browser semantic action verified by fresh post-step observation",
            evidence={
                "browser_effect": _effect_dict(effect),
                "regrounds": result.regrounds,
                "post_verification": _observation_summary(post),
            },
            observation_data=_observation_summary(post),
        ),
        session=fresh_session,
    )


def _effect_dict(effect: BrowserEffectEvidence) -> dict[str, Any]:
    return {
        "action_id": str(effect.action_id or ""),
        "success": bool(effect.success),
        "page_id": str(effect.page_id or ""),
        "url_before": str(effect.url_before or ""),
        "url_after": str(effect.url_after or ""),
        "target_id": str(effect.target_id or ""),
        "postcondition": str(effect.postcondition or ""),
        "error": effect.error,
        "data": dict(effect.data or {}),
    }
