from __future__ import annotations

"""Resident-owned admission policy for flat delegated Work.

This module deliberately does not create WorkItems or WorkerRuns. It answers the
narrow question of whether the current Root goal explicitly asks ZN to coordinate
a bounded multi-phase plan that the existing delegated-work substrate can
actually represent. Materialization remains owned by the Resident/Work ledger.

The policy is intentionally conservative. Ambiguity falls back to the direct
Resident path rather than manufacturing workers merely to demonstrate
multi-agent behavior. A later model-assisted decomposition proposal can feed a
structured candidate into this boundary, but the Resident must still validate
and admit it before any WorkerRun exists.
"""

from dataclasses import dataclass
import re
from typing import Iterable

from .steerable_work import WorkItem


_PHASE_MARKERS: dict[str, tuple[str, ...]] = {
    "research": ("调研", "研究", "research"),
    "coding": ("开发", "实现", "做出", "build", "implement", "develop"),
    "review": ("review", "评审", "审查", "复核", "验证"),
}

# Negation is evaluated near the phase marker rather than over the whole prompt.
# That makes requests such as “不要调研，也不要 review，直接实现” unambiguous:
# research/review are negative intents while implementation is positive.
_NEGATION_PREFIXES = (
    "不要",
    "不用",
    "无需",
    "不需要",
    "别",
    "禁止",
    "跳过",
    "skip",
    "without",
    "no ",
    "do not ",
    "don't ",
    "dont ",
)
_NEGATION_SUFFIXES = ("不要做", "不做", "省略", "跳过")

# Current delegated execution is a flat, deliberately narrow V1 sequence. The
# admission boundary therefore requires an explicit staged/coordinated goal,
# not merely three unrelated words somewhere in a long prompt.
_SEQUENCE_CUES = (
    "然后",
    "再",
    "最后",
    "之后",
    "先",
    "then",
    "after",
    "finally",
    "followed by",
)


@dataclass(frozen=True, slots=True)
class DelegatedPlanDecision:
    admitted: bool
    phases: tuple[str, ...]
    reason: str
    plan_version: int

    @property
    def worker_count(self) -> int:
        return len(self.phases) if self.admitted else 0


class BoundedDelegationPlanner:
    """Conservative Resident-side planner for the existing flat worker V1."""

    @classmethod
    def decide(cls, root: WorkItem) -> DelegatedPlanDecision:
        text = cls._normalize(root.objective)
        if not text:
            return cls._deny(root, "Root objective is empty")

        intents = {
            phase: cls._phase_intent(text, markers)
            for phase, markers in _PHASE_MARKERS.items()
        }
        positive = tuple(phase for phase in ("research", "coding", "review") if intents[phase] is True)
        negative = tuple(phase for phase in ("research", "coding", "review") if intents[phase] is False)

        if negative:
            return cls._deny(
                root,
                "explicitly denied delegated phase(s): " + ", ".join(negative),
            )

        # The current execution substrate can faithfully represent the verified
        # E2E-29 research -> coding -> review sequence. Until a structured
        # variable-phase plan is materialized, fail closed for partial/ambiguous
        # combinations rather than silently adding phases the user did not ask
        # for.
        if positive != ("research", "coding", "review"):
            return cls._deny(root, "goal does not request the complete bounded flat-worker sequence")

        if not any(cue in text for cue in _SEQUENCE_CUES):
            return cls._deny(root, "goal lacks an explicit staged coordination cue")

        return DelegatedPlanDecision(
            admitted=True,
            phases=positive,
            reason="Root explicitly requests the supported staged research/coding/review collaboration",
            plan_version=int(root.plan_version),
        )

    @staticmethod
    def _normalize(value: object) -> str:
        return " ".join(str(value or "").casefold().split())

    @classmethod
    def _phase_intent(cls, text: str, markers: Iterable[str]) -> bool | None:
        occurrences: list[tuple[int, int]] = []
        for marker in markers:
            start = 0
            while True:
                index = text.find(marker, start)
                if index < 0:
                    break
                occurrences.append((index, index + len(marker)))
                start = index + max(1, len(marker))
        if not occurrences:
            return None

        positive = False
        negative = False
        for begin, end in occurrences:
            # Keep the scope intentionally local. Chinese negation tends to be
            # adjacent; English forms need a slightly wider prefix window.
            prefix = text[max(0, begin - 18):begin]
            suffix = text[end:min(len(text), end + 8)]
            prefix = re.sub(r"[，,。.;；:：!?！？]", " ", prefix)
            is_negative = any(prefix.rstrip().endswith(item.rstrip()) for item in _NEGATION_PREFIXES)
            is_negative = is_negative or any(suffix.lstrip().startswith(item) for item in _NEGATION_SUFFIXES)
            if is_negative:
                negative = True
            else:
                positive = True

        # Any explicit denial wins for that phase. This is intentionally
        # fail-closed for contradictory prompts such as “不要 review…最后 review”.
        if negative:
            return False
        if positive:
            return True
        return None

    @staticmethod
    def _deny(root: WorkItem, reason: str) -> DelegatedPlanDecision:
        return DelegatedPlanDecision(
            admitted=False,
            phases=(),
            reason=reason,
            plan_version=int(root.plan_version),
        )
