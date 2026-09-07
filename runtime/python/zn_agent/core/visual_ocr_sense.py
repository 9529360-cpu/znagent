from __future__ import annotations

"""On-demand Windows-native OCR for one explicit local screen region.

This sense is read-only and model-free. Raw pixels are captured and encoded only
in memory, passed to Windows.Media.Ocr, and discarded before the observation is
returned. Nothing is written into the background visual retina or persisted by
this module.
"""

import asyncio
import io
import math
import sys
from dataclasses import dataclass
from typing import Callable

from .models import utc_now
from .visual_region_sense import NativeVisualRegionSense


_MAX_WORDS = 128
_MAX_WORD_TEXT = 256
_MAX_FULL_TEXT = 8192


@dataclass(frozen=True, slots=True)
class LocalOcrProviderWord:
    text: str
    left: float
    top: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class LocalOcrProviderResult:
    language_tag: str
    text: str
    words: tuple[LocalOcrProviderWord, ...]


@dataclass(frozen=True, slots=True)
class VisualOcrWord:
    text: str
    left: int
    top: int
    right: int
    bottom: int


@dataclass(frozen=True, slots=True)
class VisualOcrObservation:
    source: str
    captured_at: str
    language_tag: str
    text: str
    words: tuple[VisualOcrWord, ...]
    screen_width: int
    screen_height: int
    left: int
    top: int
    right: int
    bottom: int
    truncated: bool = False
    raw_frame_persisted: bool = False


OcrProviderFn = Callable[[bytes], LocalOcrProviderResult]
OcrCaptureFn = Callable[[float, float, float, float], tuple[bytes, int, int, int, int, int, int]]


class WindowsLocalOcrSense:
    """Capture and OCR one explicit screen region through Windows.Media.Ocr."""

    _DEFAULT_WIDTH_FRACTION = 0.25
    _DEFAULT_HEIGHT_FRACTION = 0.20

    def __init__(
        self,
        *,
        provider_fn: OcrProviderFn | None = None,
        capture_fn: OcrCaptureFn | None = None,
    ):
        self.provider_fn = provider_fn or self._recognize_png_winrt
        self.capture_fn = capture_fn or self._capture_region_png

    def probe(
        self,
        *,
        center_x_fraction: float,
        center_y_fraction: float,
        width_fraction: float = _DEFAULT_WIDTH_FRACTION,
        height_fraction: float = _DEFAULT_HEIGHT_FRACTION,
    ) -> VisualOcrObservation:
        center_x = NativeVisualRegionSense._unit_fraction(
            center_x_fraction,
            "center_x_fraction",
        )
        center_y = NativeVisualRegionSense._unit_fraction(
            center_y_fraction,
            "center_y_fraction",
        )
        width = NativeVisualRegionSense._size_fraction(
            width_fraction,
            "width_fraction",
        )
        height = NativeVisualRegionSense._size_fraction(
            height_fraction,
            "height_fraction",
        )
        capture = self.capture_fn(center_x, center_y, width, height)
        if not isinstance(capture, tuple) or len(capture) != 7:
            raise TypeError("local OCR capture must return 7-tuple region evidence")
        png_bytes, screen_width, screen_height, left, top, right, bottom = capture
        if not isinstance(png_bytes, bytes) or not png_bytes:
            raise ValueError("local OCR capture returned empty image bytes")
        screen_width = int(screen_width)
        screen_height = int(screen_height)
        left = int(left)
        top = int(top)
        right = int(right)
        bottom = int(bottom)
        if screen_width <= 0 or screen_height <= 0:
            raise ValueError("local OCR capture returned invalid screen dimensions")
        if left < 0 or top < 0 or right > screen_width or bottom > screen_height:
            raise ValueError("local OCR capture returned out-of-bounds region")
        if right <= left or bottom <= top:
            raise ValueError("local OCR capture returned empty region")

        captured_at = utc_now()
        try:
            result = self.provider_fn(png_bytes)
        finally:
            png_bytes = b""
        if not isinstance(result, LocalOcrProviderResult):
            raise TypeError("local OCR provider must return LocalOcrProviderResult")

        words: list[VisualOcrWord] = []
        truncated = len(result.words) > _MAX_WORDS
        region_width = max(1, right - left)
        region_height = max(1, bottom - top)
        for raw in result.words[:_MAX_WORDS]:
            text = str(raw.text or "")[:_MAX_WORD_TEXT]
            if not text:
                continue
            local_left = self._finite_nonnegative(raw.left)
            local_top = self._finite_nonnegative(raw.top)
            local_width = self._finite_nonnegative(raw.width)
            local_height = self._finite_nonnegative(raw.height)
            x1 = max(0, min(region_width, int(round(local_left))))
            y1 = max(0, min(region_height, int(round(local_top))))
            x2 = max(x1, min(region_width, int(round(local_left + local_width))))
            y2 = max(y1, min(region_height, int(round(local_top + local_height))))
            if x2 <= x1 or y2 <= y1:
                continue
            words.append(
                VisualOcrWord(
                    text=text,
                    left=left + x1,
                    top=top + y1,
                    right=left + x2,
                    bottom=top + y2,
                )
            )

        full_text = str(result.text or "")
        if len(full_text) > _MAX_FULL_TEXT:
            full_text = full_text[:_MAX_FULL_TEXT]
            truncated = True
        language_tag = str(result.language_tag or "")[:64]
        return VisualOcrObservation(
            source="windows-media-ocr",
            captured_at=captured_at,
            language_tag=language_tag,
            text=full_text,
            words=tuple(words),
            screen_width=screen_width,
            screen_height=screen_height,
            left=left,
            top=top,
            right=right,
            bottom=bottom,
            truncated=truncated,
            raw_frame_persisted=False,
        )

    @staticmethod
    def _finite_nonnegative(value: float) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("OCR bounding box values must be numeric") from exc
        if not math.isfinite(result) or result < 0.0:
            raise ValueError("OCR bounding box values must be finite and nonnegative")
        return result

    @classmethod
    def _capture_region_png(
        cls,
        center_x_fraction: float,
        center_y_fraction: float,
        width_fraction: float,
        height_fraction: float,
    ) -> tuple[bytes, int, int, int, int, int, int]:
        from PIL import ImageGrab

        captured = ImageGrab.grab()
        try:
            screen_width, screen_height = captured.size
            if screen_width <= 0 or screen_height <= 0:
                raise RuntimeError("screen capture returned an empty image")
            left, top, right, bottom = NativeVisualRegionSense._pixel_region(
                screen_width,
                screen_height,
                center_x_fraction=center_x_fraction,
                center_y_fraction=center_y_fraction,
                width_fraction=width_fraction,
                height_fraction=height_fraction,
            )
            cropped = captured.crop((left, top, right, bottom))
            try:
                rgb = cropped.convert("RGB")
                try:
                    buffer = io.BytesIO()
                    rgb.save(buffer, format="PNG")
                    payload = buffer.getvalue()
                finally:
                    rgb.close()
            finally:
                cropped.close()
        finally:
            captured.close()
        if not payload:
            raise RuntimeError("screen OCR capture produced an empty PNG")
        return payload, int(screen_width), int(screen_height), left, top, right, bottom

    @classmethod
    def _recognize_png_winrt(cls, png_bytes: bytes) -> LocalOcrProviderResult:
        if sys.platform != "win32":
            raise RuntimeError("Windows.Media.Ocr is only available on Windows")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(cls._recognize_png_winrt_async(png_bytes))
        raise RuntimeError(
            "WindowsLocalOcrSense.probe() cannot run inside an active asyncio loop"
        )

    @staticmethod
    async def _recognize_png_winrt_async(png_bytes: bytes) -> LocalOcrProviderResult:
        try:
            from winrt.windows.graphics.imaging import BitmapDecoder
            from winrt.windows.media.ocr import OcrEngine
            from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
        except ImportError as exc:
            raise RuntimeError(
                "Windows native OCR dependencies are not installed"
            ) from exc

        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        try:
            writer.write_bytes(png_bytes)
            await writer.store_async()
            await writer.flush_async()
            writer.detach_stream()
            stream.seek(0)
            decoder = await BitmapDecoder.create_async(stream)
            bitmap = await decoder.get_software_bitmap_async()
            engine = OcrEngine.try_create_from_user_profile_languages()
            if engine is None:
                raise RuntimeError(
                    "Windows has no OCR language available for the current user profile"
                )
            result = await engine.recognize_async(bitmap)
            language = getattr(engine, "recognizer_language", None)
            language_tag = str(getattr(language, "language_tag", "") or "")
            words: list[LocalOcrProviderWord] = []
            for line in tuple(getattr(result, "lines", ()) or ()):
                for word in tuple(getattr(line, "words", ()) or ()):
                    rect = getattr(word, "bounding_rect", None)
                    if rect is None:
                        continue
                    words.append(
                        LocalOcrProviderWord(
                            text=str(getattr(word, "text", "") or ""),
                            left=float(getattr(rect, "x", 0.0) or 0.0),
                            top=float(getattr(rect, "y", 0.0) or 0.0),
                            width=float(getattr(rect, "width", 0.0) or 0.0),
                            height=float(getattr(rect, "height", 0.0) or 0.0),
                        )
                    )
            return LocalOcrProviderResult(
                language_tag=language_tag,
                text=str(getattr(result, "text", "") or ""),
                words=tuple(words),
            )
        finally:
            try:
                writer.close()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
