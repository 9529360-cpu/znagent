from __future__ import annotations

"""Bounded L3 influence over already-formed ZN native action intents.

Procedural evidence never supplies Body arguments here.  It can only strengthen
an action shape that current ZN-owned event/fact logic has independently formed.
The first slice is deliberately narrow: only exact, non-append text-state
movements with an automatic independent postcondition are eligible.
"""

from dataclasses import asdict, dataclass
from typing import Iterable

from .action import NativeActionIntent
from .models import AgentEvent
from .procedural_applicability import (
    current_expected_outcome,
    evaluate_candidate_applicability,
)
from .procedural_tendency import CandidateProceduralTendency

_MATURITY_RANK = {
    "supported": 1,
    "practiced": 2,
}


@dataclass(slots=True, frozen=True)
class ProceduralActionInfluence:
    """Privacy-safe proof that one existing intent received procedural bias."""

    tendency_id: str
    evaluation_id: str
    action_kind: str
    candidate_maturity_state: str
    candidate_reliability: float
    support_count: int
    native_support_count: int
    context_fingerprint: str
    reality_matched_fields: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["reality_matched_fields"] = list(self.reality_matched_fields)
        return data


def _eligible_action_shape(
    event: AgentEvent,
    intent: NativeActionIntent,
) -> bool:
    """Return whether learning may positively bias this already-formed intent.

    The first action-influence slice intentionally excludes generic commands,
    append writes, arbitrary explicit Body actions and any movement without a
    resident-owned independent verification contract.
    """

    if intent.source == "structured_event":
        return False
    if intent.kind != "write_text":
        return False
    if bool(intent.args.get("append", False)):
        return False
    expected = current_expected_outcome(event, intent)
    return bool(
        expected
        and str(expected.get("kind") or "") == "text_equals"
        and str(intent.args.get("path") or "").strip()
    )


def strongest_supported_action_influence(
    event: AgentEvent,
    intent: NativeActionIntent,
    *,
    candidates: Iterable[CandidateProceduralTendency],
    current_domains: Iterable[str],
    facts: dict[str, object] | None,
    revoked_tendency_ids: Iterable[str] = (),
) -> ProceduralActionInfluence | None:
    """Return the strongest safe positive influence for one current intent.

    ``None`` means procedural memory has zero positive authority over this
    movement.  Applicability mismatch/untested state, candidate-level immaturity,
    inhibition, local event revocation and unsupported action shapes all fail
    closed.
    """

    if not _eligible_action_shape(event, intent):
        return None

    revoked = {str(item) for item in revoked_tendency_ids if str(item)}
    expected = current_expected_outcome(event, intent)
    if expected is None:
        return None

    qualifying: list[tuple[tuple[int, float, int, int, str], ProceduralActionInfluence]] = []
    for candidate in candidates:
        if candidate.action_kind != intent.kind:
            continue
        if candidate.tendency_id in revoked:
            continue
        maturity_rank = _MATURITY_RANK.get(candidate.maturity_state)
        if maturity_rank is None or candidate.inhibited:
            continue
        if float(candidate.reliability) < 0.75:
            continue

        evaluation = evaluate_candidate_applicability(
            candidate,
            current_domains=current_domains,
            action_kind=intent.kind,
            action_args=intent.args,
            expected_outcome=expected,
            facts=facts,
        )
        if evaluation.status != "supported" or evaluation.candidate_inhibited:
            continue

        influence = ProceduralActionInfluence(
            tendency_id=candidate.tendency_id,
            evaluation_id=evaluation.evaluation_id,
            action_kind=intent.kind,
            candidate_maturity_state=candidate.maturity_state,
            candidate_reliability=float(candidate.reliability),
            support_count=int(candidate.support_count),
            native_support_count=int(candidate.native_support_count),
            context_fingerprint=evaluation.context_fingerprint,
            reality_matched_fields=evaluation.reality_matched_fields,
        )
        rank = (
            maturity_rank,
            float(candidate.reliability),
            int(candidate.support_count),
            int(candidate.native_support_count),
            candidate.tendency_id,
        )
        qualifying.append((rank, influence))

    if not qualifying:
        return None
    qualifying.sort(key=lambda item: item[0], reverse=True)
    return qualifying[0][1]
