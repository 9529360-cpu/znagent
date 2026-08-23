from __future__ import annotations

"""Bounded L3 influence over already-formed ZN native action intents.

Procedural evidence never supplies Body arguments here. It can only strengthen
an action shape that current ZN-owned event/fact logic has independently formed.
Positive authority remains deliberately narrow: exact non-append text-state
movements and current resident-formed single-path Git staging choices with an
independently provable postcondition.
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

    def rank(self) -> tuple[int, float, int, int, str]:
        return (
            _MATURITY_RANK.get(self.candidate_maturity_state, -1),
            float(self.candidate_reliability),
            int(self.support_count),
            int(self.native_support_count),
            self.tendency_id,
        )


def _eligible_action_shape(
    event: AgentEvent,
    intent: NativeActionIntent,
    *,
    facts: dict[str, object] | None,
) -> bool:
    """Return whether learning may positively bias this already-formed intent.

    Generic commands, append writes, arbitrary explicit Body actions and any
    movement without a resident-owned independent verification contract remain
    excluded. A Git command is eligible only when current typed goal semantics
    and current Investigation facts re-prove the exact resident choice.
    """

    if intent.source == "structured_event":
        return False

    expected = current_expected_outcome(event, intent, facts=facts)
    if not expected:
        return False

    if intent.kind == "write_text":
        return bool(
            not bool(intent.args.get("append", False))
            and str(expected.get("kind") or "") == "text_equals"
            and str(intent.args.get("path") or "").strip()
        )

    if intent.kind == "command" and intent.source == "resident_choice":
        return bool(
            str(expected.get("kind") or "") == "git_path_staged"
            and bool(expected.get("current_goal_proven"))
            and str(expected.get("action_variant") or "")
            in {"git_add", "git_update_index"}
        )

    return False


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
    movement. Applicability mismatch/untested state, candidate-level immaturity,
    inhibition, local event revocation and unsupported action shapes all fail
    closed.
    """

    if not _eligible_action_shape(event, intent, facts=facts):
        return None

    revoked = {str(item) for item in revoked_tendency_ids if str(item)}
    expected = current_expected_outcome(event, intent, facts=facts)
    if expected is None:
        return None

    qualifying: list[ProceduralActionInfluence] = []
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

        qualifying.append(
            ProceduralActionInfluence(
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
        )

    if not qualifying:
        return None
    qualifying.sort(key=lambda item: item.rank(), reverse=True)
    return qualifying[0]


def select_procedurally_influenced_intent(
    event: AgentEvent,
    intents: Iterable[NativeActionIntent],
    *,
    candidates: Iterable[CandidateProceduralTendency],
    current_domains: Iterable[str],
    facts: dict[str, object] | None,
    revoked_tendency_ids: Iterable[str] = (),
) -> tuple[NativeActionIntent | None, ProceduralActionInfluence | None]:
    """Choose only among action intents current ZN cognition already formed.

    With no qualifying influence, the first intent is returned exactly as the
    existing default priority would choose it. A qualifying candidate may only
    reorder those current intents; it never contributes or modifies arguments.
    Ties keep the earlier native intent, so learning does not create arbitrary
    churn among equivalent current choices.
    """

    current = tuple(intents)
    if not current:
        return None, None

    candidate_rows = tuple(candidates)
    revoked = tuple(revoked_tendency_ids)
    best_index: int | None = None
    best_influence: ProceduralActionInfluence | None = None
    for index, intent in enumerate(current):
        influence = strongest_supported_action_influence(
            event,
            intent,
            candidates=candidate_rows,
            current_domains=current_domains,
            facts=facts,
            revoked_tendency_ids=revoked,
        )
        if influence is None:
            continue
        if best_influence is None or influence.rank() > best_influence.rank():
            best_index = index
            best_influence = influence

    if best_index is None or best_influence is None:
        return current[0], None
    return current[best_index], best_influence
