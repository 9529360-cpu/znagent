from __future__ import annotations

"""Bounded single-frame visual decisions for application competence stages.

The visual model is a replaceable cognition resource. It does not own Work,
planning, pointer authority, screen capture, replay, or a tool loop. One call sees
one current screenshot plus one already-selected stage instruction and may only
return TAP, WAIT, or FINISH.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Protocol

from .cognitive_resource import CognitiveIncrement


VisualActionKind = Literal["TAP", "WAIT", "FINISH"]

VISUAL_ACTION_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["TAP", "WAIT", "FINISH"],
        },
        "x_fraction": {
            "type": ["number", "null"],
            "minimum": 0,
            "maximum": 1,
            "description": "TAP x coordinate normalized to the screenshot width; null otherwise.",
        },
        "y_fraction": {
            "type": ["number", "null"],
            "minimum": 0,
            "maximum": 1,
            "description": "TAP y coordinate normalized to the screenshot height; null otherwise.",
        },
    },
    "required": ["action", "x_fraction", "y_fraction"],
    "additionalProperties": False,
}


class ImageCognitiveResource(Protocol):
    def invoke_image(
        self,
        *,
        question: str,
        context: str,
        image_bytes: bytes | bytearray | memoryview,
        mime_type: str = "image/png",
        response_schema: Mapping[str, Any] | None = None,
    ) -> CognitiveIncrement: ...


@dataclass(frozen=True, slots=True)
class VisualActionDecision:
    action: VisualActionKind
    x_fraction: float | None = None
    y_fraction: float | None = None

    def __post_init__(self) -> None:
        action = str(self.action or "").strip().upper()
        if action not in {"TAP", "WAIT", "FINISH"}:
            raise ValueError(f"unsupported visual action: {self.action}")
        object.__setattr__(self, "action", action)

        x = self.x_fraction
        y = self.y_fraction
        if action == "TAP":
            if isinstance(x, bool) or isinstance(y, bool):
                raise ValueError("TAP coordinates must be numeric fractions")
            try:
                x_value = float(x)  # type: ignore[arg-type]
                y_value = float(y)  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:
                raise ValueError("TAP requires x_fraction and y_fraction") from exc
            if not 0.0 <= x_value <= 1.0 or not 0.0 <= y_value <= 1.0:
                raise ValueError("TAP coordinates must be within 0..1")
            object.__setattr__(self, "x_fraction", round(x_value, 6))
            object.__setattr__(self, "y_fraction", round(y_value, 6))
            return

        if x is not None or y is not None:
            raise ValueError(f"{action} must not carry click coordinates")
        object.__setattr__(self, "x_fraction", None)
        object.__setattr__(self, "y_fraction", None)

    def audit(self) -> dict[str, object]:
        return {
            "action": self.action,
            "x_fraction": self.x_fraction,
            "y_fraction": self.y_fraction,
        }


@dataclass(frozen=True, slots=True)
class VisualActionInference:
    decision: VisualActionDecision
    provider: str
    model: str
    finish_reason: str | None = None
    usage: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", str(self.provider or "").strip())
        object.__setattr__(self, "model", str(self.model or "").strip())
        object.__setattr__(self, "usage", dict(self.usage or {}))

    def audit(self) -> dict[str, object]:
        return {
            **self.decision.audit(),
            "provider": self.provider,
            "model": self.model,
            "finish_reason": self.finish_reason,
            "usage": dict(self.usage),
        }


def parse_visual_action_decision(raw: str) -> VisualActionDecision:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("visual action response must not be empty")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("visual action response must be one JSON object") from exc
    if not isinstance(payload, dict):
        raise ValueError("visual action response must be one JSON object")

    allowed = {"action", "x_fraction", "y_fraction"}
    extra = sorted(str(key) for key in payload if key not in allowed)
    missing = sorted(key for key in allowed if key not in payload)
    if extra:
        raise ValueError("visual action response contains unsupported fields: " + ", ".join(extra))
    if missing:
        raise ValueError("visual action response is missing fields: " + ", ".join(missing))

    return VisualActionDecision(
        action=str(payload.get("action") or "").strip().upper(),  # type: ignore[arg-type]
        x_fraction=payload.get("x_fraction"),
        y_fraction=payload.get("y_fraction"),
    )


class GeminiVisualActionReasoner:
    """Use one image-capable Gemini resource for one bounded UI-stage decision."""

    MAX_INSTRUCTION_CHARS = 768
    _SYSTEM_CONTEXT = (
        "You are a bounded Windows application screenshot classifier, not an autonomous agent. "
        "You receive exactly one current screenshot and one already-selected stage instruction. "
        "Choose exactly one action: TAP, WAIT, or FINISH. "
        "TAP only when a visible on-screen target directly advances the current instruction; "
        "return normalized x/y coordinates in [0,1]. "
        "WAIT only when the requested target is not safely actionable because the visible UI is "
        "still transitioning, loading, or showing progress. "
        "FINISH only when the current instruction is already satisfied in the visible screenshot. "
        "Do not plan future steps, do not invent hidden UI state, and do not emit keyboard, shell, "
        "tool, or free-form actions. WAIT and FINISH must use null coordinates."
    )

    def __init__(self, resource: ImageCognitiveResource) -> None:
        self.resource = resource

    def infer(
        self,
        *,
        instruction: str,
        image_bytes: bytes | bytearray | memoryview,
        mime_type: str = "image/png",
        step_index: int | None = None,
    ) -> VisualActionInference:
        stage_instruction = " ".join(str(instruction or "").split()).strip()
        if not stage_instruction:
            raise ValueError("visual stage instruction must not be empty")
        if len(stage_instruction) > self.MAX_INSTRUCTION_CHARS:
            raise ValueError(
                f"visual stage instruction exceeds {self.MAX_INSTRUCTION_CHARS} characters"
            )

        if step_index is not None and (
            isinstance(step_index, bool)
            or not isinstance(step_index, int)
            or step_index < 0
        ):
            raise ValueError("visual stage step_index must be a non-negative integer")

        lines = [f"Current stage instruction: {stage_instruction}"]
        if step_index is not None:
            lines.append(f"Stage index: {step_index}")

        increment = self.resource.invoke_image(
            question="\n".join(lines),
            context=self._SYSTEM_CONTEXT,
            image_bytes=image_bytes,
            mime_type=mime_type,
            response_schema=VISUAL_ACTION_RESPONSE_SCHEMA,
        )
        decision = parse_visual_action_decision(increment.text)
        return VisualActionInference(
            decision=decision,
            provider=increment.provider,
            model=increment.model,
            finish_reason=increment.finish_reason,
            usage=dict(increment.usage or {}),
        )
