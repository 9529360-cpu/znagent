from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .adaptive_nervous_system import RealityAwareNervousSystem
from .intention_formation import (
    NativeIntentionCandidate,
    NativeIntentionFormation,
    SituatedIntentionalResidentRuntime,
)

if TYPE_CHECKING:
    from .life import BodyState, SituationModel
    from .nervous_system import NeuralActivation


class TransferAwareSituatedResidentRuntime(SituatedIntentionalResidentRuntime):
    """Situated resident whose Will cautiously reuses corrected experience."""

    _TRANSFER_MIN_GAIN = 0.04

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.nervous = RealityAwareNervousSystem(self.store)
        self.intention_formation = NativeIntentionFormation(
            self.nervous,
            resident=self,
        )

    @staticmethod
    def _transfer_gain(activation: NeuralActivation) -> float:
        try:
            value = float(getattr(activation, "transfer_gain", 0.0))
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, value))

    def _transfer_context_support(
        self,
        candidate: NativeIntentionCandidate,
        *,
        situation: SituationModel | None,
        body: BodyState | None,
    ) -> tuple[bool, str]:
        expectation = candidate.payload.get("schema_expectation")
        if not isinstance(expectation, dict):
            return False, "candidate has no structured relation"
        family = self._norm_relation_part(expectation.get("family"))
        value = self._norm_relation_part(expectation.get("value"))
        if not family or not value:
            return False, "candidate relation is incomplete"

        if body is not None:
            if family == "system" and self._norm_relation_part(body.system) == value:
                return True, f"body:system:{value}"
            if family == "architecture" and self._norm_relation_part(body.architecture) == value:
                return True, f"body:architecture:{value}"
            if family == "disk_state":
                ratio = float(body.disk_free_ratio)
                observed = "low" if ratio < 0.10 else "constrained" if ratio < 0.20 else "healthy"
                if observed == value:
                    return True, f"body:disk_state:{value}"

        if situation is not None:
            signals = [
                *(str(item) for item in tuple(situation.body_signals or ())),
                *(str(item) for item in tuple(situation.changes or ())),
            ]
            if situation.recent_outcome:
                signals.append(str(situation.recent_outcome))
            label = f"{family}:{value}"
            equals = f"{family}={value}"
            for signal in signals[:24]:
                normalized = self._norm_signal(signal)
                if label in normalized or equals in normalized:
                    return True, f"situation:{label}"
        return False, f"current Situation does not support {family}:{value}"

    @staticmethod
    def _norm_relation_part(raw) -> str:
        text = str(raw or "").strip().lower().replace(" ", "_")
        return re.sub(r"[^a-z0-9_+./-]+", "", text)[:120]

    @staticmethod
    def _norm_signal(raw) -> str:
        text = re.sub(r"\s+", "_", str(raw or "").strip().lower())
        return re.sub(r"[^a-z0-9_+./:=-]+", "", text)[:1000]
