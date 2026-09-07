from __future__ import annotations

"""Conservative natural-language intake for durable Work route policy.

This module does not choose a model and does not own authorization. It only
recognizes narrow, explicit user restrictions and turns them into the existing
ModelRouter policy vocabulary. Ambiguous language returns no policy rather than
silently broadening or inventing user intent.
"""

import re
from typing import Any

from .router import ModelRouter


_PROVIDER_ALIASES: tuple[tuple[str, str], ...] = (
    (r"\bopenai\b", "openai"),
    (r"\bgpt(?:[-\s]?\d[\w.-]*)?\b", "openai"),
    (r"\banthropic\b", "anthropic"),
    (r"\bclaude\b", "anthropic"),
    (r"\bgemini\b", "gemini"),
    (r"\bgoogle\b", "gemini"),
)
_LOCAL_MARKERS = (
    "本地模型",
    "本地大模型",
    "本机模型",
    "local model",
    "local models",
    "on-device model",
    "on device model",
)
_ONLY_MARKERS = (
    "只能",
    "只允许",
    "仅允许",
    "只可以",
    "only allow",
    "only use",
    "only share with",
    "only send to",
)
_EXCLUDE_OTHERS_MARKERS = (
    "其他模型不要接触",
    "其它模型不要接触",
    "别的模型不要接触",
    "不要给其他模型",
    "不要给其它模型",
    "no other model",
    "no other models",
    "do not share with other models",
    "do not send to other models",
)


def _providers_in(text: str) -> list[str]:
    providers: list[str] = []
    for pattern, provider in _PROVIDER_ALIASES:
        if re.search(pattern, text, flags=re.IGNORECASE) and provider not in providers:
            providers.append(provider)
    return providers


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def infer_thread_route_policy(text: str) -> dict[str, Any] | None:
    """Infer only explicit model/privacy restrictions from one user message.

    Supported narrow forms include:
    - "这个项目只能给本地模型和 GPT 看，其他模型不要接触。"
    - "这个项目只允许本地模型。"
    - "不要让 Claude 接触这个项目。"

    Ordinary model preferences ("GPT 更好") are intentionally ignored.
    """

    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return None

    providers = _providers_in(normalized)
    allow_local = _contains_any(normalized, _LOCAL_MARKERS)
    exclusive = _contains_any(normalized, _ONLY_MARKERS) or _contains_any(
        normalized, _EXCLUDE_OTHERS_MARKERS
    )

    if exclusive and (providers or allow_local):
        if allow_local and not providers:
            lowered = normalized.casefold()
            # "local and <unknown model>" is not the same as local-only. When an
            # exclusive phrase contains a conjunction but no recognized provider,
            # keep it ambiguous rather than silently dropping the unknown model.
            if "和" in normalized or "以及" in normalized or " and " in lowered:
                return None
            return {"data_classification": "local_only"}
        policy: dict[str, Any] = {"allowed_providers": providers}
        if allow_local:
            policy["allow_local"] = True
        return policy

    denied: list[str] = []
    lowered = normalized.casefold()
    denial_markers = (
        "不要给",
        "不要让",
        "不要接触",
        "禁止",
        "do not send",
        "do not share",
        "must not",
    )
    if any(marker.casefold() in lowered for marker in denial_markers):
        for provider in providers:
            aliases = {
                "openai": ("openai", "gpt"),
                "anthropic": ("anthropic", "claude"),
                "gemini": ("gemini", "google"),
            }[provider]
            if any(alias in lowered for alias in aliases):
                denied.append(provider)
    if denied:
        return {"denied_providers": denied}
    return None


def merge_route_policy(base: object, overlay: object) -> dict[str, Any]:
    """Merge only policies accepted by ModelRouter's single validator.

    This helper owns neither route selection nor authorization. It reuses the
    ModelRouter syntax boundary before durable WorkThread persistence so a
    structurally-valid mapping with invalid field values cannot poison the
    thread across restart.

    Provider allowlists are replacement semantics, not additive history. When a
    newer explicit provider allowlist omits ``allow_local``, any older local
    exception is removed; otherwise a user changing "local + GPT only" to
    "GPT only" would silently leave local routes eligible. Denials and unrelated
    policy dimensions continue to merge conservatively.
    """

    if base is None:
        base_map: dict[str, Any] = {}
    elif isinstance(base, dict):
        base_map = dict(base)
    else:
        raise ValueError("persisted Work route_policy must be an object")

    ModelRouter.validate_route_policy(base_map)
    if overlay is None:
        return base_map
    if not isinstance(overlay, dict):
        raise ValueError("explicit Work route_policy must be an object")

    merged = dict(base_map)
    if "allowed_providers" in overlay and "allow_local" not in overlay:
        merged.pop("allow_local", None)
    merged.update(overlay)
    ModelRouter.validate_route_policy(merged)
    return merged


def bind_work_event_route_policy(
    ledger,
    thread,
    *,
    task: str,
    event_payload: dict[str, Any],
) -> object:
    """Bind one WorkThread policy before its ResidentEvent can reach cognition.

    Work owns project continuity, so policy is inferred/validated/persisted here
    while the ingress event is still local and no provider can have received it.
    The same effective policy is copied onto the durable ResidentEvent payload as
    an explicit boundary value. Kernel may consume that event-level copy when a
    specialized cognition path bypasses the normal CognitionRequest builder, but
    Kernel never reads WorkThread state or infers user language itself.

    Non-object explicit policy is deliberately copied through without durable
    persistence so ModelRouter rejects it fail-closed. Mapping-shaped policy is
    validated by ModelRouter's single syntax boundary before WorkThread save.
    """

    if not isinstance(event_payload, dict):
        raise ValueError("Work event payload must be an object")
    if thread is None:
        raise RuntimeError("Work route policy lost its durable WorkThread")

    persisted: object = thread.metadata.get("route_policy")
    inferred = infer_thread_route_policy(str(task or ""))
    classification = event_payload.get("data_classification")
    explicit = event_payload.get("route_policy")

    durable_overlay: object = dict(inferred or {})
    if classification is not None:
        durable_overlay = merge_route_policy(
            durable_overlay,
            {"data_classification": classification},
        )
    if isinstance(explicit, dict):
        durable_overlay = merge_route_policy(durable_overlay, explicit)

    if durable_overlay:
        durable = merge_route_policy(persisted, durable_overlay)
        metadata = dict(thread.metadata)
        metadata["route_policy"] = durable
        thread.metadata = metadata
        from .models import utc_now

        thread.updated_at = utc_now()
        ledger._save_thread(thread)
        persisted = durable
    elif persisted is not None:
        # Validate inherited durable truth before it is copied onto a new event.
        persisted = merge_route_policy(persisted, None)

    if explicit is not None and not isinstance(explicit, dict):
        route_policy: object = explicit
    else:
        route_policy = persisted

    if route_policy is not None:
        event_payload["route_policy"] = route_policy
    return route_policy
