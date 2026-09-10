from __future__ import annotations

"""Transparent procedural-candidate aggregation over verified causal episodes.

This module is deliberately not an action selector or executable skill runtime.
It derives a bounded resident-owned view from ``VerifiedExperience`` records so
repetition, contradiction, maturity and inhibition can be inspected before L3
is allowed to let a tendency influence action.
"""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .verified_experience import VerifiedExperience

_MAX_EVIDENCE_IDS = 8
_MAX_RECENT_VERDICTS = 4
_MATURITY_RANK = {
    "candidate": 0,
    "contested": 1,
    "supported": 2,
    "practiced": 3,
    "inhibited": -1,
}


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _compatibility_profile(experience: VerifiedExperience) -> dict[str, Any]:
    expected = dict(experience.expected_outcome or {})
    result = dict(experience.result_features or {})
    profile = {
        "group_key": str(experience.group_key),
        "domains": list(experience.domains),
        "action_kind": str(experience.action_kind or "unknown"),
        "action_variant": expected.get("action_variant"),
        "expected_kind": str(expected.get("kind") or "unknown"),
        "expected_exit_code": expected.get("expected_exit_code"),
        "effect_class": str(result.get("effect_class") or "unknown"),
        "failure_class": (
            str(result.get("failure_class"))
            if result.get("failure_class") is not None
            else None
        ),
    }
    # Scope only the bounded Git staging competence added by Memory 1.0. This
    # follows namespace-first retrieval without rewriting the identity of older
    # unscoped procedural candidates. The value is already a privacy-safe hash;
    # raw repository paths never enter the candidate.
    project_scope = expected.get("workdir_fingerprint")
    if str(expected.get("kind") or "").strip().lower() == "git_path_staged" and project_scope:
        profile["project_scope_fingerprint"] = project_scope
    return profile


def _stable_anchor(
    experiences: list[VerifiedExperience],
    key: str,
) -> Any | None:
    if not experiences:
        return None
    values = [item.expected_outcome.get(key) for item in experiences]
    if any(value is None for value in values):
        return None
    encoded = {_stable_json(value) for value in values}
    return values[0] if len(encoded) == 1 else None


def _variant_count(experiences: list[VerifiedExperience], key: str) -> int:
    return len(
        {
            _stable_json(value)
            for value in (item.expected_outcome.get(key) for item in experiences)
            if value is not None
        }
    )


def _recent_event_verdicts(
    experiences: list[VerifiedExperience],
) -> tuple[str, ...]:
    latest_by_event: dict[str, VerifiedExperience] = {}
    for item in sorted(
        experiences,
        key=lambda row: (str(row.created_at), str(row.experience_id)),
    ):
        latest_by_event[str(item.event_id)] = item
    latest = sorted(
        latest_by_event.values(),
        key=lambda row: (str(row.created_at), str(row.experience_id)),
        reverse=True,
    )
    return tuple(str(item.verdict) for item in latest[:_MAX_RECENT_VERDICTS])


def _maturity_state(
    *,
    support_count: int,
    contradiction_count: int,
    reliability: float,
    recent_verdicts: tuple[str, ...],
) -> tuple[str, bool]:
    repeated_recent_contradiction = (
        len(recent_verdicts) >= 2
        and recent_verdicts[0] == "contradicted"
        and recent_verdicts[1] == "contradicted"
    )
    inhibited = contradiction_count >= 2 and (
        reliability <= 0.50 or repeated_recent_contradiction
    )
    if inhibited:
        return "inhibited", True
    if contradiction_count > 0 and reliability < 0.80:
        return "contested", False
    if support_count >= 4 and reliability >= 0.80:
        return "practiced", False
    if support_count >= 3 and reliability >= 0.75:
        return "supported", False
    return "candidate", False


@dataclass(slots=True, frozen=True)
class CandidateProceduralTendency:
    """A non-executable tendency supported by repeated verified experience.

    L2 candidates are observational. They carry no raw command/content/path and
    cannot directly move the Body. Reality-gated action influence belongs to L3.
    """

    tendency_id: str
    group_key: str
    action_kind: str
    domain_fingerprints: tuple[str, ...]
    expected_kind: str
    expected_exit_code: int | None
    effect_class: str
    failure_class: str | None
    support_count: int
    contradiction_count: int
    distinct_event_count: int
    native_support_count: int
    assisted_support_count: int
    reliability: float
    maturity_state: str
    inhibited: bool
    applicability: dict[str, Any]
    recent_verdicts: tuple[str, ...]
    supporting_experience_ids: tuple[str, ...]
    contradicting_experience_ids: tuple[str, ...]
    first_seen_at: str
    last_seen_at: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in (
            "domain_fingerprints",
            "recent_verdicts",
            "supporting_experience_ids",
            "contradicting_experience_ids",
        ):
            data[key] = list(data[key])
        return data

    def summary(self) -> dict[str, Any]:
        """Return the bounded status view safe to expose inside resident state."""
        return {
            "tendency_id": self.tendency_id,
            "group_key": self.group_key,
            "action_kind": self.action_kind,
            "support_count": self.support_count,
            "contradiction_count": self.contradiction_count,
            "reliability": self.reliability,
            "maturity_state": self.maturity_state,
            "inhibited": self.inhibited,
            "applicability": dict(self.applicability),
        }


def aggregate_candidate_tendencies(
    experiences: Iterable[VerifiedExperience],
    *,
    minimum_support: int = 2,
    limit: int = 32,
) -> list[CandidateProceduralTendency]:
    """Derive candidate tendencies without creating one from a single success."""

    min_support = max(2, int(minimum_support))
    max_candidates = max(1, min(128, int(limit)))
    buckets: dict[str, list[VerifiedExperience]] = {}
    for experience in experiences:
        profile = _compatibility_profile(experience)
        compatibility_key = _fingerprint(profile)
        buckets.setdefault(compatibility_key, []).append(experience)

    candidates: list[CandidateProceduralTendency] = []
    for compatibility_key, rows in buckets.items():
        ordered = sorted(
            rows,
            key=lambda item: (str(item.created_at), str(item.experience_id)),
        )
        supports = [item for item in ordered if item.verdict == "verified"]
        contradictions = [
            item for item in ordered if item.verdict == "contradicted"
        ]
        support_events = {str(item.event_id) for item in supports}
        contradiction_events = {str(item.event_id) for item in contradictions}
        support_count = len(support_events)
        if support_count < min_support:
            continue

        contradiction_count = len(contradiction_events)
        total_labeled = support_count + contradiction_count
        reliability = (
            support_count / total_labeled if total_labeled > 0 else 0.0
        )
        recent_verdicts = _recent_event_verdicts(ordered)
        maturity_state, inhibited = _maturity_state(
            support_count=support_count,
            contradiction_count=contradiction_count,
            reliability=reliability,
            recent_verdicts=recent_verdicts,
        )

        profile = _compatibility_profile(supports[-1])
        support_sources: dict[str, set[str]] = {}
        for item in supports:
            support_sources.setdefault(str(item.source), set()).add(str(item.event_id))
        native_support_count = len(support_sources.get("native", set()))
        assisted_support_count = len(
            support_events - support_sources.get("native", set())
        )

        applicability = {
            "stable_target_fingerprint": _stable_anchor(
                supports, "target_fingerprint"
            ),
            "stable_workdir_fingerprint": _stable_anchor(
                supports, "workdir_fingerprint"
            ),
            "stable_verification_signature_hash": _stable_anchor(
                supports, "verification_signature_hash"
            ),
            "stable_action_variant": _stable_anchor(supports, "action_variant"),
            "target_variants": _variant_count(supports, "target_fingerprint"),
            "workdir_variants": _variant_count(supports, "workdir_fingerprint"),
            "verification_signature_variants": _variant_count(
                supports, "verification_signature_hash"
            ),
            "action_variant_variants": _variant_count(supports, "action_variant"),
            "goal_variants": len({item.goal_fingerprint for item in supports}),
            "situation_variants": len(
                {item.situation_evidence_fingerprint for item in supports}
            ),
            "action_signature_variants": len(
                {item.action_signature_hash for item in supports
            }),
        }

        candidates.append(
            CandidateProceduralTendency(
                tendency_id="pt-" + compatibility_key[:24],
                group_key=str(profile["group_key"]),
                action_kind=str(profile["action_kind"]),
                domain_fingerprints=tuple(str(item) for item in profile["domains"]),
                expected_kind=str(profile["expected_kind"]),
                expected_exit_code=(
                    int(profile["expected_exit_code"])
                    if profile["expected_exit_code"] is not None
                    else None
                ),
                effect_class=str(profile["effect_class"]),
                failure_class=(
                    str(profile["failure_class"])
                    if profile["failure_class"] is not None
                    else None
                ),
                support_count=support_count,
                contradiction_count=contradiction_count,
                distinct_event_count=len(support_events | contradiction_events),
                native_support_count=native_support_count,
                assisted_support_count=assisted_support_count,
                reliability=round(reliability, 5),
                maturity_state=maturity_state,
                inhibited=inhibited,
                applicability=applicability,
                recent_verdicts=recent_verdicts,
                supporting_experience_ids=tuple(
                    item.experience_id for item in reversed(supports[-_MAX_EVIDENCE_IDS:])
                ),
                contradicting_experience_ids=tuple(
                    item.experience_id
                    for item in reversed(contradictions[-_MAX_EVIDENCE_IDS:])
                ),
                first_seen_at=str(ordered[0].created_at),
                last_seen_at=str(ordered[-1].created_at),
            )
        )

    candidates.sort(
        key=lambda item: (
            item.last_seen_at,
            _MATURITY_RANK.get(item.maturity_state, -2),
            item.support_count,
            item.reliability,
            item.tendency_id,
        ),
        reverse=True,
    )
    return candidates[:max_candidates]
