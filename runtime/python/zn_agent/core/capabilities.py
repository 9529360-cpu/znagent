from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .models import AgentEvent, CapabilityResult, WorkingState


class LocalCapability(Protocol):
    name: str
    priority: int

    def match(self, event: AgentEvent) -> float: ...

    def execute(self, event: AgentEvent, state: WorkingState) -> CapabilityResult: ...


@dataclass(slots=True)
class CallableCapability:
    """Small zero-token capability backed by normal program code.

    The matcher is deliberately deterministic. Learned procedures can later be
    compiled into capabilities of this shape instead of being replayed as long
    prompt text on every task.
    """

    name: str
    matcher: Callable[[AgentEvent], float]
    handler: Callable[[AgentEvent, WorkingState], CapabilityResult]
    priority: int = 0

    def match(self, event: AgentEvent) -> float:
        try:
            return max(0.0, min(1.0, float(self.matcher(event))))
        except Exception:
            return 0.0

    def execute(self, event: AgentEvent, state: WorkingState) -> CapabilityResult:
        return self.handler(event, state)


class ExactTaskCapability(CallableCapability):
    """Convenience capability for stable commands/intents learned by the agent."""

    def __init__(
        self,
        *,
        name: str,
        triggers: tuple[str, ...],
        handler: Callable[[AgentEvent, WorkingState], CapabilityResult],
        priority: int = 0,
    ):
        normalized = {self._normalize(item) for item in triggers if item.strip()}

        def matcher(event: AgentEvent) -> float:
            return 1.0 if self._normalize(event.task) in normalized else 0.0

        super().__init__(name=name, matcher=matcher, handler=handler, priority=priority)

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(str(value or "").strip().lower().split())


class CapabilityRegistry:
    def __init__(self, *, match_threshold: float = 0.75):
        self.match_threshold = max(0.0, min(1.0, float(match_threshold)))
        self._capabilities: dict[str, LocalCapability] = {}

    def register(self, capability: LocalCapability) -> None:
        name = str(capability.name or "").strip()
        if not name:
            raise ValueError("capability name must not be empty")
        self._capabilities[name] = capability

    def unregister(self, name: str) -> None:
        self._capabilities.pop(name, None)

    def resolve(self, event: AgentEvent) -> tuple[LocalCapability, float] | None:
        ranked: list[tuple[float, int, str, LocalCapability]] = []
        for capability in self._capabilities.values():
            score = capability.match(event)
            if score < self.match_threshold:
                continue
            ranked.append((score, int(getattr(capability, "priority", 0)), capability.name, capability))
        if not ranked:
            return None
        ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        score, _priority, _name, capability = ranked[0]
        return capability, score

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._capabilities))
