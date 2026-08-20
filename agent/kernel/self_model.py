from __future__ import annotations

from .models import Assessment, CapabilityEstimate
from .store import KernelStore


class SelfModel:
    """Evidence-backed capability model for the persistent agent."""

    def __init__(self, store: KernelStore):
        self.store = store

    @staticmethod
    def route_capability_key(route_id: str, capability: str) -> str:
        return f"route:{route_id}:{capability}"

    def get(self, capability: str, default: float = 0.5) -> CapabilityEstimate:
        return self.store.get_capability(capability) or CapabilityEstimate(
            name=capability, score=default
        )

    def route_score(self, route_id: str, capability: str, prior: float) -> float:
        estimate = self.store.get_capability(
            self.route_capability_key(route_id, capability)
        )
        if estimate is None or estimate.evidence_count == 0:
            return max(0.0, min(1.0, prior))
        learned_weight = estimate.confidence
        return (estimate.score * learned_weight) + (prior * (1.0 - learned_weight))

    def learn(self, route_id: str, capabilities: tuple[str, ...], assessment: Assessment) -> None:
        sample = max(0.0, min(1.0, assessment.quality))
        if not assessment.success:
            sample = min(sample, 0.35)
        for capability in capabilities or ("general",):
            self._update(capability, sample)
            self._update(self.route_capability_key(route_id, capability), sample)

    def _update(self, name: str, sample: float) -> CapabilityEstimate:
        current = self.store.get_capability(name) or CapabilityEstimate(name=name)
        old_n = current.evidence_count
        current.score = ((current.score * old_n) + sample) / (old_n + 1)
        current.evidence_count = old_n + 1
        current.confidence = min(0.99, current.evidence_count / (current.evidence_count + 3.0))
        self.store.save_capability(current)
        return current

    def weakest(self, limit: int = 5) -> list[CapabilityEstimate]:
        estimates = [
            e for e in self.store.list_capabilities() if not e.name.startswith("route:")
        ]
        estimates.sort(key=lambda e: (e.score, -e.evidence_count, e.name))
        return estimates[: max(1, limit)]
