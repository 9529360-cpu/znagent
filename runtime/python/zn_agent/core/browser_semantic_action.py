from __future__ import annotations

"""Provider-neutral fresh semantic browser action execution."""

from dataclasses import dataclass
from typing import Any

from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserAdapter,
    BrowserEffectEvidence,
    BrowserObservation,
    BrowserPermissionContext,
    BrowserTargetQuery,
)


@dataclass(frozen=True, slots=True)
class BrowserSemanticActionResult:
    observation: BrowserObservation
    effect: BrowserEffectEvidence
    regrounds: int


def execute_fresh_semantic_action(
    browser: BrowserAdapter,
    *,
    session_id: str,
    permission: BrowserPermissionContext,
    query: BrowserTargetQuery,
    kind: BrowserActionKind,
    page_id: str = "",
    args: dict[str, Any] | None = None,
    expected: dict[str, Any] | None = None,
    expected_url_before: str = "",
    max_regrounds: int = 1,
) -> BrowserSemanticActionResult:
    """Resolve a semantic target at dispatch time with bounded safe re-grounding.

    Providers may request one fresh semantic re-resolve only when they prove the
    previous mutation never crossed the dispatch boundary. Any dispatched or
    uncertain effect is returned immediately and is never replayed here.
    """

    if max_regrounds < 0 or max_regrounds > 3:
        raise ValueError("browser semantic max_regrounds must be between 0 and 3")
    pinned_url = str(expected_url_before or "").strip()

    regrounds = 0
    while True:
        observed = browser.observe_target(
            session_id,
            query,
            page_id=page_id,
        )
        if observed.target is None:
            raise ValueError("browser semantic target observation returned no target")
        if pinned_url and observed.url != pinned_url:
            raise ValueError(
                "browser semantic action page URL changed before dispatch; refusing target transfer"
            )
        action = BrowserAction.create(
            session_id=session_id,
            kind=kind,
            page_id=observed.page_id,
            target=observed.target,
            args=dict(args or {}),
            expected=dict(expected or {}),
        )
        authority = BrowserActionAuthority.from_observation(
            action,
            observed,
            permission,
        )
        effect = browser.act(action, authority)
        if effect.success:
            return BrowserSemanticActionResult(
                observation=observed,
                effect=effect,
                regrounds=regrounds,
            )
        if (
            not effect.allows_fresh_semantic_reground
            or regrounds >= max_regrounds
        ):
            return BrowserSemanticActionResult(
                observation=observed,
                effect=effect,
                regrounds=regrounds,
            )
        regrounds += 1
