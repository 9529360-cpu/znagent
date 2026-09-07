from __future__ import annotations

"""BrowserScene-first, local-OCR-only fallback for one explicit viewport region."""

from dataclasses import dataclass
from typing import Any

from .managed_browser import ManagedBrowserError
from .visual_ocr_sense import LocalOcrProviderResult, WindowsLocalOcrSense
from .visual_region_sense import NativeVisualRegionSense


_MAX_ROLE_CHARS = 64
_MAX_NAME_CHARS = 256
_MAX_WORDS = 128
_MAX_WORD_TEXT = 256
_MAX_TEXT = 8192


@dataclass(frozen=True, slots=True)
class BrowserVisualOcrWord:
    text: str
    left: float
    top: float
    right: float
    bottom: float


@dataclass(frozen=True, slots=True)
class BrowserSceneOrVisualObservation:
    session_id: str
    page_id: str
    captured_at: str
    source: str
    semantic_role: str
    semantic_name: str
    semantic_target_id: str = ""
    text: str = ""
    words: tuple[BrowserVisualOcrWord, ...] = ()
    clip_left: float = 0.0
    clip_top: float = 0.0
    clip_right: float = 0.0
    clip_bottom: float = 0.0
    truncated: bool = False
    raw_frame_persisted: bool = False


class PlaywrightBrowserSceneVisualFallbackMixin:
    """Use BrowserScene first; only then OCR one explicit viewport clip locally."""

    def observe_scene_or_local_ocr(
        self,
        session_id: str,
        *,
        semantic_role: str,
        accessible_name: str,
        page_id: str = "",
        center_x_fraction: float,
        center_y_fraction: float,
        width_fraction: float = 0.25,
        height_fraction: float = 0.20,
    ) -> BrowserSceneOrVisualObservation:
        role = " ".join(str(semantic_role or "").strip().split()).lower()
        name = " ".join(str(accessible_name or "").strip().split())
        if not role or len(role) > _MAX_ROLE_CHARS:
            raise ManagedBrowserError("Browser visual fallback semantic role is empty or too long")
        if not name or len(name) > _MAX_NAME_CHARS:
            raise ManagedBrowserError("Browser visual fallback accessible name is empty or too long")
        if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in role + name):
            raise ManagedBrowserError("Browser visual fallback semantic query contains control characters")

        session = self._session(session_id)
        resolved_page_id = page_id or self._default_page_id(session)
        page = self._page(session, resolved_page_id)
        current_url = str(getattr(page, "url", "") or "")
        self._require_url_allowed(current_url, session.permission)

        scene = self.observe_scene(session_id, page_id=resolved_page_id)
        if bool(getattr(scene, "truncated", False)):
            raise ManagedBrowserError(
                "Browser visual fallback refuses to infer semantic absence from a truncated scene"
            )
        matches = [
            target
            for target in tuple(getattr(scene, "targets", ()) or ())
            if str(getattr(target, "role", "") or "").lower() == role
            and str(getattr(target, "accessible_name", "") or "") == name
        ]
        if len(matches) > 1:
            raise ManagedBrowserError(
                "Browser visual fallback semantic query is ambiguous in the current scene"
            )
        if len(matches) == 1:
            target = matches[0]
            return BrowserSceneOrVisualObservation(
                session_id=session.identity.session_id,
                page_id=resolved_page_id,
                captured_at=scene.captured_at,
                source="browser_scene",
                semantic_role=role,
                semantic_name=name,
                semantic_target_id=str(getattr(target, "target_id", "") or ""),
                raw_frame_persisted=False,
            )

        # OCR can expose arbitrary page text. The first fallback slice therefore
        # requires the existing explicit sensitive-field permission rather than
        # silently widening read authority merely because DOM semantics failed.
        if not session.permission.allow_sensitive_fields:
            raise ManagedBrowserError(
                "Browser local OCR fallback requires allow_sensitive_fields in this first slice"
            )

        cx = NativeVisualRegionSense._unit_fraction(
            center_x_fraction,
            "center_x_fraction",
        )
        cy = NativeVisualRegionSense._unit_fraction(
            center_y_fraction,
            "center_y_fraction",
        )
        wf = NativeVisualRegionSense._size_fraction(width_fraction, "width_fraction")
        hf = NativeVisualRegionSense._size_fraction(height_fraction, "height_fraction")

        viewport = getattr(page, "viewport_size", None)
        if not isinstance(viewport, dict):
            raise ManagedBrowserError(
                "Browser local OCR fallback requires a known finite viewport"
            )
        viewport_width = int(viewport.get("width") or 0)
        viewport_height = int(viewport.get("height") or 0)
        if viewport_width <= 0 or viewport_height <= 0:
            raise ManagedBrowserError(
                "Browser local OCR fallback requires positive viewport dimensions"
            )
        left, top, right, bottom = NativeVisualRegionSense._pixel_region(
            viewport_width,
            viewport_height,
            center_x_fraction=cx,
            center_y_fraction=cy,
            width_fraction=wf,
            height_fraction=hf,
        )
        clip = {
            "x": float(left),
            "y": float(top),
            "width": float(right - left),
            "height": float(bottom - top),
        }
        screenshot = getattr(page, "screenshot", None)
        if not callable(screenshot):
            raise ManagedBrowserError("browser provider cannot capture an in-memory viewport clip")
        try:
            png_bytes = screenshot(type="png", clip=clip, scale="css")
        except Exception as exc:
            raise ManagedBrowserError(
                f"Browser local OCR screenshot failed: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(png_bytes, bytes) or not png_bytes:
            raise ManagedBrowserError("browser provider returned an empty OCR screenshot")
        try:
            result = self._browser_local_ocr_provider(png_bytes)
        finally:
            png_bytes = b""
        if not isinstance(result, LocalOcrProviderResult):
            raise ManagedBrowserError("browser local OCR provider returned invalid evidence")

        words: list[BrowserVisualOcrWord] = []
        truncated = len(result.words) > _MAX_WORDS
        clip_width = float(right - left)
        clip_height = float(bottom - top)
        for raw in result.words[:_MAX_WORDS]:
            text = str(raw.text or "")[:_MAX_WORD_TEXT]
            if not text:
                continue
            x1 = max(0.0, min(clip_width, float(raw.left)))
            y1 = max(0.0, min(clip_height, float(raw.top)))
            x2 = max(x1, min(clip_width, float(raw.left + raw.width)))
            y2 = max(y1, min(clip_height, float(raw.top + raw.height)))
            if x2 <= x1 or y2 <= y1:
                continue
            words.append(
                BrowserVisualOcrWord(
                    text=text,
                    left=left + x1,
                    top=top + y1,
                    right=left + x2,
                    bottom=top + y2,
                )
            )
        text = str(result.text or "")
        if len(text) > _MAX_TEXT:
            text = text[:_MAX_TEXT]
            truncated = True
        if not text.strip() and not words:
            raise ManagedBrowserError(
                "Browser local OCR fallback produced no bounded text evidence"
            )
        return BrowserSceneOrVisualObservation(
            session_id=session.identity.session_id,
            page_id=resolved_page_id,
            captured_at=scene.captured_at,
            source="browser_local_ocr",
            semantic_role=role,
            semantic_name=name,
            text=text,
            words=tuple(words),
            clip_left=float(left),
            clip_top=float(top),
            clip_right=float(right),
            clip_bottom=float(bottom),
            truncated=truncated,
            raw_frame_persisted=False,
        )

    @staticmethod
    def _browser_local_ocr_provider(png_bytes: bytes) -> LocalOcrProviderResult:
        return WindowsLocalOcrSense._recognize_png_winrt(png_bytes)
