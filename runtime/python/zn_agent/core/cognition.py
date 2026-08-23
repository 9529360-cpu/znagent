from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from .models import utc_now


@dataclass(slots=True)
class CognitiveIncrement:
    """A bounded piece of cognition ZN borrowed and now owns as input.

    External model output is not the resident's identity, Thought, or action.
    It is an increment that returns to ZN after an impasse so ZN can integrate
    it into its own state before deciding what to do next.
    """

    increment_id: str
    event_id: str
    impasse_id: str | None
    source: str
    question: str
    content: str
    quality: float = 0.0
    confidence: float = 0.0
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CognitiveIncrement":
        return cls(**dict(raw))

    @classmethod
    def create(
        cls,
        *,
        event_id: str,
        impasse_id: str | None,
        source: str,
        question: str,
        content: str,
        quality: float = 0.0,
        confidence: float = 0.0,
    ) -> "CognitiveIncrement":
        return cls(
            increment_id=f"inc-{uuid.uuid4().hex[:12]}",
            event_id=event_id,
            impasse_id=impasse_id,
            source=str(source or "external"),
            question=str(question or ""),
            content=str(content or ""),
            quality=max(0.0, min(1.0, float(quality))),
            confidence=max(0.0, min(1.0, float(confidence))),
        )
