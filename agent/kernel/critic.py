from __future__ import annotations

from typing import Protocol

from .models import Assessment, Goal, WorkerResult


class Critic(Protocol):
    def assess(self, goal: Goal, result: WorkerResult) -> Assessment: ...


class DefaultCritic:
    """Evidence-first evaluator.

    V1 deliberately avoids asking the same worker model whether its own answer
    was good. Verification evidence dominates when available.
    """

    def assess(self, goal: Goal, result: WorkerResult) -> Assessment:
        reasons: list[str] = []
        if not result.success:
            reasons.append(result.error or "worker reported failure")
            return Assessment(False, 0.0, 0.95, tuple(reasons))

        declared_quality = result.metrics.get("quality")
        try:
            quality = float(declared_quality) if declared_quality is not None else 0.65
        except (TypeError, ValueError):
            quality = 0.65
        quality = max(0.0, min(1.0, quality))

        if result.verification_passed is True:
            reasons.append("fresh verification passed")
            return Assessment(True, max(0.85, quality), 0.95, tuple(reasons))
        if result.verification_passed is False:
            reasons.append("verification failed")
            return Assessment(False, min(0.35, quality), 0.98, tuple(reasons))

        if not result.response.strip():
            reasons.append("worker produced no usable response")
            return Assessment(False, 0.1, 0.9, tuple(reasons))

        reasons.append("accepted without external verification")
        return Assessment(True, quality, 0.6, tuple(reasons))
