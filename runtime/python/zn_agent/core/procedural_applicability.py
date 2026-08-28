from __future__ import annotations

"""Read-only L3 applicability checks for resident procedural candidates.

A candidate is historical evidence, not present-world authority.  This module
compares its privacy-safe applicability profile with current structured task
context and independently observed Investigation facts.  It deliberately does
not select, construct, or execute a Body action.
"""

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .action import NativeActionIntent, current_text_equals_postcondition
from .git_semantics import current_git_stage_intent_goal
from .models import AgentEvent
from .path_context import canonical_host_path
from .procedural_tendency import CandidateProceduralTendency


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


def _fingerprint_text(value: Any) -> str | None:
    text = str(value or "").strip()
    if text:
        path = Path(text).expanduser()
        if path.is_absolute():
            text = str(canonical_host_path(path))
    return _fingerprint(text) if text else None


def _normalized_expected_kind(value: Any) -> str | None:
    kind = str(value or "").strip().lower()
    if not kind:
        return None
    if kind in {"command", "command_check", "command_succeeds"}:
        return "command"
    return kind


def _current_action_variant(
    action_kind: str,
    args: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> str | None:
    if action_kind == "write_text":
        return "append" if bool(args.get("append", False)) else "replace"
    if _normalized_expected_kind(expected.get("kind")) == "git_path_staged":
        variant = str(expected.get("action_variant") or "").strip().lower()
        return variant or None
    return None


def current_expected_outcome(
    event: AgentEvent,
    intent: NativeActionIntent,
    *,
    facts: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build the transient verification shape relevant to applicability.

    This mirrors the resident's postcondition contract only far enough to compare
    privacy-safe L1/L2 features.  The returned mapping may contain raw current
    task values and therefore must never be persisted as procedural memory.

    A typed Git staging goal is exposed only after ``git_semantics`` proves that
    this exact current command intent was freshly reconstructed from the same
    current repository/path evidence. Historical procedural memory never gets to
    supply a command, path, workdir, or variant through this function.
    """

    current_facts = facts if isinstance(facts, Mapping) else {}
    explicit = event.payload.get("expected_outcome")
    if explicit is not None:
        if not isinstance(explicit, Mapping):
            return {"kind": "unsupported"}
        kind = _normalized_expected_kind(explicit.get("kind"))
        if kind == "git_path_staged":
            goal = current_git_stage_intent_goal(
                event,
                action_kind=intent.kind,
                action_args=intent.args,
                source=intent.source,
                expected_outcome=intent.expected_outcome,
                facts=current_facts,
            )
            if goal is None:
                return {"kind": "unsupported"}
            return {
                "kind": "git_path_staged",
                "path": goal["path"],
                "workdir": goal["root"],
                "action_variant": goal["action_variant"],
                "current_goal_proven": True,
            }
        if kind == "text_equals":
            goal = current_text_equals_postcondition(event)
            if goal is None:
                return {"kind": "unsupported"}
            return {
                "kind": "text_equals",
                "path": goal["path"],
                "action_variant": (
                    "append" if bool(intent.args.get("append", False)) else "replace"
                    if intent.kind == "write_text"
                    else None
                ),
            }
        if kind != "command":
            return {"kind": kind or "unsupported"}
        command = str(explicit.get("command") or "").strip()
        if not command:
            return {"kind": "unsupported"}
        try:
            expected_exit_code = int(explicit.get("exit_code", 0))
        except (TypeError, ValueError):
            return {"kind": "unsupported"}
        workdir = (
            str(explicit.get("workdir") or intent.args.get("workdir") or "").strip()
            or None
        )
        return {
            "kind": "command",
            "command": command,
            "workdir": workdir,
            "expected_exit_code": expected_exit_code,
        }

    raw_goal = intent.expected_outcome
    if isinstance(raw_goal, Mapping) and _normalized_expected_kind(
        raw_goal.get("kind")
    ) == "text_equals":
        path = str(raw_goal.get("path") or "").strip()
        if path:
            return {
                "kind": "text_equals",
                "path": path,
                "action_variant": (
                    "append" if bool(intent.args.get("append", False)) else "replace"
                    if intent.kind == "write_text"
                    else None
                ),
            }

    if intent.kind != "write_text" or bool(intent.args.get("append", False)):
        return None
    path = str(intent.args.get("path") or "").strip()
    if not path:
        return None
    return {
        "kind": "text_equals",
        "path": path,
        "action_variant": "replace",
    }


def current_procedural_applicability_domains(
    event: AgentEvent,
    intent: NativeActionIntent,
    *,
    expected_outcome: Mapping[str, Any] | None,
    current_domains: Iterable[str],
) -> tuple[str, ...]:
    """Return the current domain contract used to compare one current intent.

    Most action families keep the SelfModel/current-caller domain view. The
    bounded Git staging family is narrower: L1 causal evidence is recorded from
    the event's explicit ``required_capabilities`` contract, so a currently
    re-proven resident Git choice must compare against that same representation.
    This prevents harmless parent-domain expansion from changing causal identity
    while keeping the exception tied to exact current Git semantics.
    """

    domains = tuple(str(item) for item in current_domains if str(item).strip())
    expected = expected_outcome if isinstance(expected_outcome, Mapping) else {}
    if (
        intent.kind == "command"
        and intent.source == "resident_choice"
        and _normalized_expected_kind(expected.get("kind")) == "git_path_staged"
        and bool(expected.get("current_goal_proven"))
    ):
        raw = event.payload.get("required_capabilities") or ("general",)
        if isinstance(raw, str):
            value = raw.strip()
            return (value,) if value else ("general",)
        values = tuple(str(item) for item in raw if str(item).strip())
        return values or ("general",)
    return domains


def _observed_path_fingerprints(facts: Mapping[str, Any]) -> set[str]:
    raw = facts.get("paths")
    if not isinstance(raw, list):
        return set()
    observed: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        fingerprint = _fingerprint_text(item.get("path"))
        if fingerprint:
            observed.add(fingerprint)
    return observed


def _observed_git_root_fingerprint(facts: Mapping[str, Any]) -> str | None:
    raw = facts.get("git")
    if not isinstance(raw, Mapping) or raw.get("available") is False:
        return None
    return _fingerprint_text(raw.get("root"))


@dataclass(slots=True, frozen=True)
class ProceduralApplicabilityEvaluation:
    """Privacy-safe evidence that a candidate is supported, mismatched or untested."""

    evaluation_id: str
    tendency_id: str
    status: str
    action_kind: str
    candidate_maturity_state: str
    candidate_reliability: float
    candidate_inhibited: bool
    matched_fields: tuple[str, ...]
    mismatched_fields: tuple[str, ...]
    untested_fields: tuple[str, ...]
    reality_matched_fields: tuple[str, ...]
    context_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in (
            "matched_fields",
            "mismatched_fields",
            "untested_fields",
            "reality_matched_fields",
        ):
            data[key] = list(data[key])
        return data


def evaluate_candidate_applicability(
    candidate: CandidateProceduralTendency,
    *,
    current_domains: Iterable[str],
    action_kind: str | None,
    action_args: Mapping[str, Any] | None,
    expected_outcome: Mapping[str, Any] | None,
    facts: Mapping[str, Any] | None,
) -> ProceduralApplicabilityEvaluation:
    """Compare one candidate with current context and independently observed facts.

    Task/request structure can disqualify a candidate, but it cannot by itself
    prove applicability. ``supported`` requires a stable candidate anchor to be
    independently observed and every compared contract field to be tested.
    Missing current evidence therefore fails closed as ``untested``.
    """

    matched: list[str] = []
    mismatched: list[str] = []
    untested: list[str] = []
    reality_matched: list[str] = []
    current_facts = facts if isinstance(facts, Mapping) else {}
    args = action_args if isinstance(action_args, Mapping) else {}
    expected = expected_outcome if isinstance(expected_outcome, Mapping) else {}
    applicability = dict(candidate.applicability or {})

    if candidate.inhibited:
        mismatched.append("candidate_inhibited")

    current_kind = str(action_kind or "").strip().lower()
    if not current_kind:
        untested.append("action_kind")
    elif current_kind != candidate.action_kind:
        mismatched.append("action_kind")
    else:
        matched.append("action_kind")

    current_variant = _current_action_variant(current_kind, args, expected)
    stable_variant = str(applicability.get("stable_action_variant") or "").strip()
    variant_metadata_present = "action_variant_variants" in applicability
    if candidate.action_kind == "write_text" and variant_metadata_present:
        if not stable_variant:
            untested.append("action_variant")
        elif current_variant != stable_variant:
            mismatched.append("action_variant")
        else:
            matched.append("action_variant")
    elif candidate.expected_kind == "git_path_staged":
        if not bool(expected.get("current_goal_proven")):
            untested.append("git_goal_proven")
        else:
            matched.append("git_goal_proven")
            reality_matched.append("git_goal_proven")
        if not variant_metadata_present or not stable_variant:
            untested.append("action_variant")
        elif current_variant != stable_variant:
            mismatched.append("action_variant")
        else:
            matched.append("action_variant")

    candidate_domains = set(candidate.domain_fingerprints)
    current_domain_fingerprints = {
        _fingerprint(str(item).strip())
        for item in current_domains
        if str(item).strip()
    }
    if not current_domain_fingerprints:
        untested.append("domains")
    elif current_domain_fingerprints != candidate_domains:
        mismatched.append("domains")
    else:
        matched.append("domains")

    current_expected_kind = _normalized_expected_kind(expected.get("kind"))
    if current_expected_kind is None:
        untested.append("expected_kind")
    elif current_expected_kind != candidate.expected_kind:
        mismatched.append("expected_kind")
    else:
        matched.append("expected_kind")

    if candidate.expected_exit_code is not None:
        current_exit = expected.get("expected_exit_code")
        if current_exit is None:
            untested.append("expected_exit_code")
        else:
            try:
                normalized_exit = int(current_exit)
            except (TypeError, ValueError):
                mismatched.append("expected_exit_code")
            else:
                if normalized_exit != candidate.expected_exit_code:
                    mismatched.append("expected_exit_code")
                else:
                    matched.append("expected_exit_code")

    stable_signature = applicability.get("stable_verification_signature_hash")
    current_signature: str | None = None
    if stable_signature:
        command = str(expected.get("command") or "").strip()
        if command:
            workdir = str(expected.get("workdir") or "").strip() or None
            current_signature = _fingerprint(
                {"command": command, "workdir": workdir}
            )
            if current_signature == stable_signature:
                matched.append("verification_signature")
            else:
                mismatched.append("verification_signature")
        else:
            untested.append("verification_signature")

    current_target = str(
        args.get("path") or expected.get("path") or ""
    ).strip()
    current_target_fingerprint = _fingerprint_text(current_target)
    stable_target = applicability.get("stable_target_fingerprint")
    if stable_target:
        if current_target_fingerprint is None:
            untested.append("target_context")
        elif current_target_fingerprint != stable_target:
            mismatched.append("target_context")
        else:
            matched.append("target_context")
            observed_paths = _observed_path_fingerprints(current_facts)
            if current_target_fingerprint in observed_paths:
                matched.append("target_observed")
                reality_matched.append("target_observed")
            else:
                untested.append("target_observed")
    elif int(applicability.get("target_variants") or 0) > 0:
        untested.append("generalized_target")

    current_workdir = str(
        args.get("workdir") or expected.get("workdir") or ""
    ).strip()
    current_workdir_fingerprint = _fingerprint_text(current_workdir)
    stable_workdir = applicability.get("stable_workdir_fingerprint")
    if stable_workdir:
        if current_workdir_fingerprint is None:
            untested.append("workdir_context")
        elif current_workdir_fingerprint != stable_workdir:
            mismatched.append("workdir_context")
        else:
            matched.append("workdir_context")
            observed_git_root = _observed_git_root_fingerprint(current_facts)
            if observed_git_root == current_workdir_fingerprint:
                matched.append("workdir_observed")
                reality_matched.append("workdir_observed")
            else:
                untested.append("workdir_observed")
    elif int(applicability.get("workdir_variants") or 0) > 0:
        untested.append("generalized_workdir")

    if not stable_target and not stable_workdir:
        untested.append("stable_reality_anchor")

    if mismatched:
        status = "mismatch"
    elif reality_matched and not untested:
        status = "supported"
    else:
        status = "untested"

    safe_context = {
        "domains": sorted(current_domain_fingerprints),
        "action_kind": current_kind or None,
        "action_variant": current_variant,
        "expected_kind": current_expected_kind,
        "expected_exit_code": expected.get("expected_exit_code"),
        "target_fingerprint": current_target_fingerprint,
        "workdir_fingerprint": current_workdir_fingerprint,
        "verification_signature_hash": current_signature,
        "git_goal_proven": bool(expected.get("current_goal_proven")),
        "observed_path_fingerprints": sorted(_observed_path_fingerprints(current_facts))[:16],
        "observed_git_root_fingerprint": _observed_git_root_fingerprint(current_facts),
    }
    context_fingerprint = _fingerprint(safe_context)
    evaluation_id = "pa-" + _fingerprint(
        {
            "tendency_id": candidate.tendency_id,
            "status": status,
            "context_fingerprint": context_fingerprint,
            "matched": sorted(set(matched)),
            "mismatched": sorted(set(mismatched)),
            "untested": sorted(set(untested)),
        }
    )[:24]

    return ProceduralApplicabilityEvaluation(
        evaluation_id=evaluation_id,
        tendency_id=candidate.tendency_id,
        status=status,
        action_kind=candidate.action_kind,
        candidate_maturity_state=candidate.maturity_state,
        candidate_reliability=float(candidate.reliability),
        candidate_inhibited=bool(candidate.inhibited),
        matched_fields=tuple(dict.fromkeys(matched))[:16],
        mismatched_fields=tuple(dict.fromkeys(mismatched))[:16],
        untested_fields=tuple(dict.fromkeys(untested))[:16],
        reality_matched_fields=tuple(dict.fromkeys(reality_matched))[:8],
        context_fingerprint=context_fingerprint,
    )
