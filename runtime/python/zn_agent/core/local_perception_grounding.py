from __future__ import annotations

"""System-native local perception grounding before any model escalation.

Order is resident-owned and explicit:
1. foreground Win32 system facts;
2. UI Automation structural target evidence;
3. bounded local Windows OCR for an explicit region;
4. a model-escalation-required sentinel only.

This module never calls a model and creates no second vision/browser agent.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .automation_element_sense import AutomationElementObservation, NativeAutomationElementSense
from .foreground_window_sense import ForegroundWindowObservation, NativeForegroundWindowSense
from .models import utc_now
from .visual_ocr_sense import VisualOcrObservation, WindowsLocalOcrSense


class LocalGroundingLevel(str, Enum):
    UIA = "uia"
    LOCAL_OCR = "local_ocr"
    MODEL_REQUIRED = "model_required"


@dataclass(frozen=True, slots=True)
class LocalPerceptionGrounding:
    level: LocalGroundingLevel
    captured_at: str
    foreground: ForegroundWindowObservation | None
    automation: AutomationElementObservation | None = None
    ocr: VisualOcrObservation | None = None
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.level is LocalGroundingLevel.UIA and self.automation is None:
            raise ValueError("UIA grounding requires automation evidence")
        if self.level is LocalGroundingLevel.LOCAL_OCR and self.ocr is None:
            raise ValueError("local OCR grounding requires OCR evidence")
        if self.level is LocalGroundingLevel.MODEL_REQUIRED and not self.reasons:
            raise ValueError("model-required grounding requires failure reasons")
        if self.ocr is not None and self.ocr.raw_frame_persisted:
            raise ValueError("local grounding must not retain persisted raw OCR pixels")


class LocalPerceptionGrounder:
    """Ground one explicit screen point with deterministic local senses first."""

    def __init__(
        self,
        *,
        foreground: NativeForegroundWindowSense | None = None,
        automation: NativeAutomationElementSense | None = None,
        ocr: WindowsLocalOcrSense | None = None,
    ):
        self.foreground = foreground or NativeForegroundWindowSense()
        self.automation = automation or NativeAutomationElementSense()
        self.ocr = ocr or WindowsLocalOcrSense()

    def ground_point(
        self,
        *,
        x: int,
        y: int,
        screen_width: int,
        screen_height: int,
        ocr_width_fraction: float = 0.25,
        ocr_height_fraction: float = 0.20,
    ) -> LocalPerceptionGrounding:
        px = int(x)
        py = int(y)
        width = int(screen_width)
        height = int(screen_height)
        if width <= 0 or height <= 0:
            raise ValueError("local perception requires positive screen dimensions")
        if px < 0 or py < 0 or px >= width or py >= height:
            raise ValueError("local perception point must be inside the current screen")

        reasons: list[str] = []
        foreground: ForegroundWindowObservation | None = None
        try:
            foreground = self.foreground.probe()
        except Exception as exc:
            reasons.append(self._reason("foreground", exc))

        try:
            automation = self.automation.probe_at_point(px, py)
        except Exception as exc:
            reasons.append(self._reason("uia", exc))
        else:
            if (
                foreground is not None
                and int(automation.process_id) != int(foreground.process_id)
            ):
                reasons.append("uia: target process does not match current foreground process")
            elif automation.is_offscreen:
                reasons.append("uia: target is offscreen")
            else:
                return LocalPerceptionGrounding(
                    level=LocalGroundingLevel.UIA,
                    captured_at=automation.captured_at,
                    foreground=foreground,
                    automation=automation,
                    reasons=tuple(reasons),
                )

        center_x = round((px + 0.5) / float(width), 6)
        center_y = round((py + 0.5) / float(height), 6)
        try:
            ocr = self.ocr.probe(
                center_x_fraction=center_x,
                center_y_fraction=center_y,
                width_fraction=ocr_width_fraction,
                height_fraction=ocr_height_fraction,
            )
        except Exception as exc:
            reasons.append(self._reason("local_ocr", exc))
        else:
            nonempty_words = tuple(word for word in ocr.words if str(word.text or "").strip())
            if str(ocr.text or "").strip() or nonempty_words:
                return LocalPerceptionGrounding(
                    level=LocalGroundingLevel.LOCAL_OCR,
                    captured_at=ocr.captured_at,
                    foreground=foreground,
                    ocr=ocr,
                    reasons=tuple(reasons),
                )
            reasons.append("local_ocr: no bounded text evidence in requested region")

        return LocalPerceptionGrounding(
            level=LocalGroundingLevel.MODEL_REQUIRED,
            captured_at=utc_now(),
            foreground=foreground,
            reasons=tuple(reasons) or ("local perception produced no usable evidence",),
        )

    @staticmethod
    def _reason(stage: str, exc: Exception) -> str:
        return f"{stage}: {type(exc).__name__}: {exc}"[:500]
