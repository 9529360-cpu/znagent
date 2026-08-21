from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .nervous_system import NeuralTrace


def _unit_float(raw: Any) -> float:
    try:
        value = float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))


def active_schema_relations(trace: NeuralTrace) -> tuple[dict[str, Any], ...]:
    """Return current usable schema relations, not superseded predictions.

    Reconsolidation keeps contested relations for historical continuity. They
    should not keep steering current attention or Will merely because they were
    once strong. Reality-supported replacements remain in the same schema and
    are ranked ahead of unresolved emerging structure.
    """
    profile = trace.metadata.get("prediction_profile")
    if not isinstance(profile, dict):
        return ()
    active: list[dict[str, Any]] = []
    for raw in profile.get("relations") or ():
        if not isinstance(raw, dict):
            continue
        family = str(raw.get("family") or "").strip().lower()
        value = str(raw.get("value") or "").strip().lower()
        status = str(raw.get("status") or "expected").strip().lower()
        if not family or not value or status == "contested":
            continue
        confidence = _unit_float(raw.get("confidence"))
        support = _unit_float(raw.get("support_ratio"))
        if confidence < 0.35 and support < 0.45 and not raw.get("anchor"):
            continue
        item = dict(raw)
        item["family"] = family
        item["value"] = value
        item["status"] = status
        item["confidence"] = confidence
        item["support_ratio"] = support
        active.append(item)
    active.sort(
        key=lambda item: (
            bool(item.get("stabilized_from_prediction_error")),
            str(item.get("status") or "") == "expected",
            _unit_float(item.get("confidence")),
            _unit_float(item.get("support_ratio")),
            bool(item.get("anchor")),
        ),
        reverse=True,
    )
    return tuple(active[:12])


def schema_reality_score(trace: NeuralTrace) -> float:
    """How strongly current lived reality should let this schema steer thought."""
    profile = trace.metadata.get("prediction_profile")
    if not isinstance(profile, dict):
        return 0.0
    relations = active_schema_relations(trace)
    if not relations:
        return 0.0
    prediction_confidence = _unit_float(
        trace.metadata.get("prediction_confidence")
    )
    stable = [
        item for item in relations
        if bool(item.get("stabilized_from_prediction_error"))
    ]
    emerging = [
        item for item in relations
        if str(item.get("status") or "") == "emerging"
    ]
    contested = sum(
        1
        for item in profile.get("relations") or ()
        if isinstance(item, dict)
        and str(item.get("status") or "") == "contested"
    )
    top = relations[0]
    score = (
        0.34 * prediction_confidence
        + 0.28 * _unit_float(top.get("confidence"))
        + 0.20 * _unit_float(top.get("support_ratio"))
        + 0.12 * min(1.0, len(stable) / 2.0)
        + 0.06 * min(1.0, len(relations) / 4.0)
    )
    if stable:
        score += 0.12
    if emerging and not stable:
        score += 0.04
    score -= min(0.16, contested * 0.04)
    return max(0.0, min(1.0, score))


def schema_attention_focus(trace: NeuralTrace) -> str:
    """Surface the schema's current reality-facing structure to idle Thought."""
    relations = active_schema_relations(trace)
    if not relations:
        return trace.summary
    labels = [
        f"{item['family']}:{item['value']}"
        for item in relations[:4]
    ]
    stabilized = any(
        bool(item.get("stabilized_from_prediction_error"))
        for item in relations[:4]
    )
    marker = "reality-updated" if stabilized else "current"
    return f"{trace.summary[:360]} [{marker} relations: {', '.join(labels)}]"


def relation_reality_bonus(trace: NeuralTrace, family: str, value: str) -> float:
    """Score one candidate relation by how it was changed by lived reality."""
    target = (str(family or "").strip().lower(), str(value or "").strip().lower())
    for item in active_schema_relations(trace):
        if (item.get("family"), item.get("value")) != target:
            continue
        bonus = 0.0
        status = str(item.get("status") or "expected")
        if status == "emerging":
            bonus += 0.08
        elif status == "expected":
            bonus += 0.05
        if item.get("formed_from_prediction_error"):
            bonus += 0.06
        if item.get("stabilized_from_prediction_error"):
            bonus += 0.14
        bonus += 0.06 * _unit_float(item.get("confidence"))
        return min(0.30, bonus)
    return 0.0
