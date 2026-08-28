from __future__ import annotations

"""On-demand target-local visual evidence owned by the resident service.

This sense is deliberately separate from the persistent background retina
rhythm. A probe captures one bounded region, derives compact local structure,
and discards raw pixels before returning. It does not write nervous memory,
advance the background visual state, or interpret the region through a model.
"""

import hashlib
import math
from dataclasses import dataclass
from typing import Callable

from .models import utc_now


@dataclass(frozen=True, slots=True)
class VisualRegionObservation:
    signature: str
    source: str
    captured_at: str
    screen_width: int
    screen_height: int
    left: int
    top: int
    right: int
    bottom: int
    center_x_fraction: float
    center_y_fraction: float
    width_fraction: float
    height_fraction: float
    mean_luminance: float | None = None
    raw_frame_persisted: bool = False


VisualRegionProbeFn = Callable[
    [float, float, float, float],
    VisualRegionObservation,
]


class NativeVisualRegionSense:
    """Fresh, read-only visual evidence for one explicit screen region."""

    _DEFAULT_WIDTH_FRACTION = 0.08
    _DEFAULT_HEIGHT_FRACTION = 0.08
    _MIN_SIZE_FRACTION = 0.01
    _MAX_SIZE_FRACTION = 0.50

    def __init__(self, *, probe_fn: VisualRegionProbeFn | None = None):
        self.probe_fn = probe_fn or self._probe_primary_screen_region

    def probe(
        self,
        *,
        center_x_fraction: float,
        center_y_fraction: float,
        width_fraction: float = _DEFAULT_WIDTH_FRACTION,
        height_fraction: float = _DEFAULT_HEIGHT_FRACTION,
    ) -> VisualRegionObservation:
        center_x = self._unit_fraction(center_x_fraction, "center_x_fraction")
        center_y = self._unit_fraction(center_y_fraction, "center_y_fraction")
        width = self._size_fraction(width_fraction, "width_fraction")
        height = self._size_fraction(height_fraction, "height_fraction")
        observation = self.probe_fn(center_x, center_y, width, height)
        if not isinstance(observation, VisualRegionObservation):
            raise TypeError("visual region probe must return VisualRegionObservation")
        if not str(observation.signature or "").strip():
            raise ValueError("visual region probe returned an empty signature")
        if observation.raw_frame_persisted:
            raise ValueError("visual region probe must not persist raw frame pixels")
        if observation.right <= observation.left or observation.bottom <= observation.top:
            raise ValueError("visual region probe returned an empty pixel region")
        return observation

    @classmethod
    def _probe_primary_screen_region(
        cls,
        center_x_fraction: float,
        center_y_fraction: float,
        width_fraction: float,
        height_fraction: float,
    ) -> VisualRegionObservation:
        from PIL import Image, ImageGrab, ImageStat

        captured = ImageGrab.grab()
        try:
            screen_width, screen_height = captured.size
            if screen_width <= 0 or screen_height <= 0:
                raise RuntimeError("screen capture returned an empty image")

            left, top, right, bottom = cls._pixel_region(
                screen_width,
                screen_height,
                center_x_fraction=center_x_fraction,
                center_y_fraction=center_y_fraction,
                width_fraction=width_fraction,
                height_fraction=height_fraction,
            )
            cropped = captured.crop((left, top, right, bottom))
            try:
                region = cropped.convert("L")
                try:
                    sample = region.resize((16, 16), Image.Resampling.BILINEAR)
                    try:
                        # Keep enough local structure to detect a target-area change
                        # while suppressing tiny antialiasing/compression noise. Only
                        # this quantized derivative is hashed; raw image bytes are
                        # discarded before the observation leaves this call.
                        quantized = bytes(
                            min(15, max(0, int(value) // 16))
                            for value in sample.getdata()
                        )
                    finally:
                        sample.close()
                    signature = hashlib.sha256(quantized).hexdigest()[:24]
                    mean_luminance = round(
                        float(ImageStat.Stat(region).mean[0]) / 255.0,
                        5,
                    )
                finally:
                    region.close()
            finally:
                cropped.close()
        finally:
            captured.close()

        return VisualRegionObservation(
            signature=signature,
            source="pillow-screen-region",
            captured_at=utc_now(),
            screen_width=int(screen_width),
            screen_height=int(screen_height),
            left=left,
            top=top,
            right=right,
            bottom=bottom,
            center_x_fraction=center_x_fraction,
            center_y_fraction=center_y_fraction,
            width_fraction=width_fraction,
            height_fraction=height_fraction,
            mean_luminance=mean_luminance,
            raw_frame_persisted=False,
        )

    @staticmethod
    def _pixel_region(
        screen_width: int,
        screen_height: int,
        *,
        center_x_fraction: float,
        center_y_fraction: float,
        width_fraction: float,
        height_fraction: float,
    ) -> tuple[int, int, int, int]:
        width = max(1, int(round(screen_width * width_fraction)))
        height = max(1, int(round(screen_height * height_fraction)))
        center_x = int(round(center_x_fraction * max(0, screen_width - 1)))
        center_y = int(round(center_y_fraction * max(0, screen_height - 1)))

        left = center_x - width // 2
        top = center_y - height // 2
        left = max(0, min(left, max(0, screen_width - width)))
        top = max(0, min(top, max(0, screen_height - height)))
        right = min(screen_width, left + width)
        bottom = min(screen_height, top + height)
        if right <= left or bottom <= top:
            raise RuntimeError("visual region collapsed outside the primary screen")
        return left, top, right, bottom

    @staticmethod
    def _unit_fraction(value: float, name: str) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be numeric") from exc
        if not math.isfinite(result) or not 0.0 <= result <= 1.0:
            raise ValueError(f"{name} must be finite and between 0 and 1")
        return round(result, 6)

    @classmethod
    def _size_fraction(cls, value: float, name: str) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be numeric") from exc
        if (
            not math.isfinite(result)
            or result < cls._MIN_SIZE_FRACTION
            or result > cls._MAX_SIZE_FRACTION
        ):
            raise ValueError(
                f"{name} must be finite and between "
                f"{cls._MIN_SIZE_FRACTION} and {cls._MAX_SIZE_FRACTION}"
            )
        return round(result, 6)
