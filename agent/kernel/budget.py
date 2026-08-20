from __future__ import annotations

from dataclasses import dataclass

from .models import AgentEvent, CognitiveDecision


@dataclass(slots=True)
class CognitiveBudgetManager:
    """Deterministic System-1/System-2 gate.

    Normal tasks get at most one model call. A second call is reserved for
    explicitly high-risk/uncertain work. Callers can also mark an event as
    model_policy='never' to guarantee zero model usage.
    """

    normal_model_calls: int = 1
    high_risk_model_calls: int = 2
    high_risk_threshold: float = 0.8

    def decide(
        self,
        event: AgentEvent,
        *,
        memory_hit: bool = False,
        local_capability_available: bool = False,
    ) -> CognitiveDecision:
        if memory_hit:
            return CognitiveDecision(False, 0, "structured memory can answer without a model")
        if local_capability_available:
            return CognitiveDecision(False, 0, "a registered local capability can execute the task")

        policy = str(event.payload.get("model_policy") or "on_demand").strip().lower()
        if policy in {"never", "off", "local_only"}:
            return CognitiveDecision(False, 0, f"model use disabled by policy '{policy}'")

        risk = self._unit(event.payload.get("risk", 0.0))
        uncertainty = self._unit(event.payload.get("uncertainty", 0.0))
        novelty = self._unit(event.payload.get("novelty", 0.5))
        high_stakes = max(risk, uncertainty) >= self.high_risk_threshold

        if policy in {"force", "always"}:
            calls = self.high_risk_model_calls if high_stakes else self.normal_model_calls
            return CognitiveDecision(True, max(1, calls), "model explicitly requested")

        if high_stakes:
            return CognitiveDecision(
                True,
                max(1, self.high_risk_model_calls),
                "System 1 has no solution and risk/uncertainty justifies an escalation budget",
            )

        reason = "System 1 has no solution; use one bounded System 2 call"
        if novelty < 0.2:
            reason += " despite low novelty because no compiled capability exists yet"
        return CognitiveDecision(True, max(1, self.normal_model_calls), reason)

    @staticmethod
    def _unit(value: object) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0
