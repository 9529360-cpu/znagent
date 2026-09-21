from __future__ import annotations

"""Unified foreground desktop scene for ZN.

The scene composes one ZN-owned screenshot, bounded semantic UI Automation
controls, and optional visual-grounding candidates without creating another
agent loop or action authority. UIA remains preferred; visual evidence is a
fallback/augmentation surface.
"""

import ctypes
import hashlib
import json
import math
import os
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from .automation_named_control_sense import (
    NamedAutomationControlObservation,
    NativeNamedAutomationControlSense,
)
from .home import get_zn_home
from .models import utc_now
from .windows_screen_capture import (
    ScreenCaptureArtifact,
    capture_primary_screen_artifact,
    inspect_screen_capture_artifact,
)


DESKTOP_SCENE_SCHEMA_VERSION = 1
DESKTOP_SCENE_MAX_TARGETS = 96
DESKTOP_SCENE_MAX_VISUAL_TARGETS = 64
DESKTOP_SCENE_IOU_MERGE_THRESHOLD = 0.10
DESKTOP_SCENE_UIA_CONTROL_TYPES = (
    "button",
    "checkbox",
    "combo_box",
    "edit",
    "list_item",
    "menu_item",
    "radio_button",
    "tab_item",
    "tree_item",
    "data_item",
)
_MAX_TARGET_NAME_CHARS = 160
_MAX_AUTOMATION_ID_CHARS = 256
_MAX_ROLE_CHARS = 64
_MAX_PROVIDER_ID_CHARS = 96
_MAX_DEGRADED_REASONS = 16


class DesktopSceneError(RuntimeError):
    """The current desktop could not produce one coherent bounded scene."""


@dataclass(frozen=True, slots=True)
class DesktopSceneRect:
    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self) -> None:
        values = tuple(
            float(value) for value in (self.left, self.top, self.right, self.bottom)
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("desktop scene rectangle must contain finite coordinates")
        if values[2] <= values[0] or values[3] <= values[1]:
            raise ValueError("desktop scene rectangle must have positive area")
        object.__setattr__(self, "left", values[0])
        object.__setattr__(self, "top", values[1])
        object.__setattr__(self, "right", values[2])
        object.__setattr__(self, "bottom", values[3])

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2.0

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2.0

    def audit(self) -> dict[str, float]:
        return {
            "left": round(self.left, 3),
            "top": round(self.top, 3),
            "right": round(self.right, 3),
            "bottom": round(self.bottom, 3),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DesktopSceneRect":
        return cls(
            left=float(value.get("left")),
            top=float(value.get("top")),
            right=float(value.get("right")),
            bottom=float(value.get("bottom")),
        )


@dataclass(frozen=True, slots=True)
class DesktopSceneForeground:
    application_id: str
    process_name: str
    class_name: str
    identity_sha256: str
    window_rect: DesktopSceneRect

    def __post_init__(self) -> None:
        application_id = str(self.application_id or "").strip()
        process_name = str(self.process_name or "").strip()
        digest = str(self.identity_sha256 or "").strip().lower()
        if not application_id:
            raise ValueError("desktop scene foreground application_id must not be empty")
        if not process_name:
            raise ValueError("desktop scene foreground process_name must not be empty")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("desktop scene foreground identity_sha256 must be SHA-256")
        object.__setattr__(self, "application_id", application_id)
        object.__setattr__(self, "process_name", process_name[:260])
        object.__setattr__(self, "class_name", str(self.class_name or "")[:160])
        object.__setattr__(self, "identity_sha256", digest)

    def audit(self) -> dict[str, Any]:
        return {
            "application_id": self.application_id,
            "process_name": self.process_name,
            "class_name": self.class_name,
            "identity_sha256": self.identity_sha256,
            "window_rect": self.window_rect.audit(),
        }


@dataclass(frozen=True, slots=True)
class DesktopSceneScreenshot:
    local_path: str
    width: int
    height: int
    size_bytes: int
    sha256: str
    source: str

    def __post_init__(self) -> None:
        local_path = str(self.local_path or "").strip()
        width = int(self.width)
        height = int(self.height)
        size_bytes = int(self.size_bytes)
        digest = str(self.sha256 or "").strip().lower()
        if not local_path:
            raise ValueError("desktop scene screenshot path must not be empty")
        if width <= 0 or height <= 0 or size_bytes <= 0:
            raise ValueError("desktop scene screenshot metadata must be positive")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("desktop scene screenshot sha256 must be SHA-256")
        object.__setattr__(self, "local_path", local_path)
        object.__setattr__(self, "width", width)
        object.__setattr__(self, "height", height)
        object.__setattr__(self, "size_bytes", size_bytes)
        object.__setattr__(self, "sha256", digest)
        object.__setattr__(self, "source", str(self.source or "").strip() or "primary_screen")

    def audit(self) -> dict[str, Any]:
        return {
            "local_path": self.local_path,
            "width": self.width,
            "height": self.height,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class DesktopVisualGroundingCandidate:
    role: str
    name: str
    rect: DesktopSceneRect
    confidence: float
    provider_id: str
    editable: bool | None = None
    enabled: bool | None = None

    def __post_init__(self) -> None:
        role = _clean(self.role).lower().replace(" ", "_")
        name = _clean(self.name)
        provider_id = _clean(self.provider_id)
        confidence = float(self.confidence)
        if not role and not name:
            raise ValueError("visual grounding candidate requires role or name")
        if len(role) > _MAX_ROLE_CHARS or len(name) > _MAX_TARGET_NAME_CHARS:
            raise ValueError("visual grounding candidate exceeds bounded label length")
        if not provider_id or len(provider_id) > _MAX_PROVIDER_ID_CHARS:
            raise ValueError("visual grounding provider_id is invalid")
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise ValueError("visual grounding confidence must be within 0..1")
        if self.editable is not None and not isinstance(self.editable, bool):
            raise TypeError("visual grounding editable must be boolean or None")
        if self.enabled is not None and not isinstance(self.enabled, bool):
            raise TypeError("visual grounding enabled must be boolean or None")
        object.__setattr__(self, "role", role[:_MAX_ROLE_CHARS])
        object.__setattr__(self, "name", name[:_MAX_TARGET_NAME_CHARS])
        object.__setattr__(self, "provider_id", provider_id[:_MAX_PROVIDER_ID_CHARS])
        object.__setattr__(self, "confidence", confidence)


@dataclass(frozen=True, slots=True)
class DesktopSceneTarget:
    target_id: str
    source: str
    role: str
    accessible_name: str
    automation_id: str
    rect: DesktopSceneRect
    center_x_fraction: float
    center_y_fraction: float
    enabled: bool | None
    editable: bool | None
    focused: bool | None
    supported_patterns: tuple[str, ...] = ()
    visual_confidence: float | None = None
    provenance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        target_id = str(self.target_id or "").strip()
        source = str(self.source or "").strip().lower()
        role = _clean(self.role).lower().replace(" ", "_")
        accessible_name = _clean(self.accessible_name)
        automation_id = str(self.automation_id or "").strip()
        if target_id and not target_id.startswith("desktop-target-"):
            raise ValueError("desktop scene target_id is invalid")
        if source not in {"uia", "visual", "hybrid"}:
            raise ValueError("desktop scene target source must be uia, visual or hybrid")
        if not role or len(role) > _MAX_ROLE_CHARS:
            raise ValueError("desktop scene target role is invalid")
        if len(accessible_name) > _MAX_TARGET_NAME_CHARS:
            raise ValueError("desktop scene target accessible_name is too long")
        if len(automation_id) > _MAX_AUTOMATION_ID_CHARS:
            raise ValueError("desktop scene target automation_id is too long")
        x = float(self.center_x_fraction)
        y = float(self.center_y_fraction)
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise ValueError("desktop scene target center fractions must be within 0..1")
        confidence = self.visual_confidence
        if confidence is not None:
            confidence = float(confidence)
            if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
                raise ValueError("desktop scene visual confidence must be within 0..1")
        object.__setattr__(self, "target_id", target_id)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "accessible_name", accessible_name)
        object.__setattr__(self, "automation_id", automation_id)
        object.__setattr__(self, "center_x_fraction", round(x, 6))
        object.__setattr__(self, "center_y_fraction", round(y, 6))
        object.__setattr__(
            self,
            "supported_patterns",
            tuple(dict.fromkeys(str(item) for item in self.supported_patterns if str(item))),
        )
        object.__setattr__(self, "visual_confidence", confidence)
        object.__setattr__(
            self,
            "provenance",
            tuple(dict.fromkeys(str(item) for item in self.provenance if str(item))),
        )

    def audit(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "source": self.source,
            "role": self.role,
            "accessible_name": self.accessible_name,
            "automation_id": self.automation_id,
            "rect": self.rect.audit(),
            "center_x_fraction": self.center_x_fraction,
            "center_y_fraction": self.center_y_fraction,
            "enabled": self.enabled,
            "editable": self.editable,
            "focused": self.focused,
            "supported_patterns": list(self.supported_patterns),
            "visual_confidence": self.visual_confidence,
            "provenance": list(self.provenance),
        }


@dataclass(frozen=True, slots=True)
class DesktopScene:
    scene_id: str
    captured_at: str
    foreground: DesktopSceneForeground
    screenshot: DesktopSceneScreenshot
    targets: tuple[DesktopSceneTarget, ...]
    grounding_mode: str
    providers: tuple[str, ...]
    truncated: bool = False
    degraded_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        scene_id = str(self.scene_id or "").strip()
        if not scene_id.startswith("desktop-scene-"):
            raise ValueError("desktop scene_id is invalid")
        if self.grounding_mode not in {
            "hybrid",
            "uia_only",
            "visual_only",
            "screenshot_only",
        }:
            raise ValueError("desktop scene grounding_mode is invalid")
        if len(self.targets) > DESKTOP_SCENE_MAX_TARGETS:
            raise ValueError("desktop scene exceeds bounded target count")
        object.__setattr__(self, "scene_id", scene_id)
        object.__setattr__(self, "captured_at", str(self.captured_at or "").strip())
        object.__setattr__(
            self,
            "providers",
            tuple(dict.fromkeys(str(item) for item in self.providers if str(item))),
        )
        object.__setattr__(
            self,
            "degraded_reasons",
            _bounded_reasons(self.degraded_reasons),
        )

    @property
    def uia_target_count(self) -> int:
        return sum(target.source in {"uia", "hybrid"} for target in self.targets)

    @property
    def visual_target_count(self) -> int:
        return sum(target.source in {"visual", "hybrid"} for target in self.targets)

    def audit(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "captured_at": self.captured_at,
            "foreground": self.foreground.audit(),
            "screenshot": self.screenshot.audit(),
            "targets": [target.audit() for target in self.targets],
            "grounding_mode": self.grounding_mode,
            "providers": list(self.providers),
            "truncated": bool(self.truncated),
            "degraded_reasons": list(self.degraded_reasons),
            "uia_target_count": self.uia_target_count,
            "visual_target_count": self.visual_target_count,
        }


@dataclass(frozen=True, slots=True)
class DesktopSceneForegroundBinding:
    """Transient native identity used only while one scene is being captured."""

    application_id: str
    process_id: int
    process_name: str
    window_handle: int
    class_name: str = ""

    def __post_init__(self) -> None:
        application_id = str(self.application_id or "").strip()
        process_id = int(self.process_id)
        process_name = str(self.process_name or "").strip()
        window_handle = int(self.window_handle)
        if not application_id or process_id <= 0 or not process_name or window_handle <= 0:
            raise ValueError(
                "desktop scene foreground binding requires exact app/process/window identity"
            )
        object.__setattr__(self, "application_id", application_id)
        object.__setattr__(self, "process_id", process_id)
        object.__setattr__(self, "process_name", process_name)
        object.__setattr__(self, "window_handle", window_handle)
        object.__setattr__(self, "class_name", str(self.class_name or "")[:160])

    @property
    def identity_sha256(self) -> str:
        payload = "\x1f".join(
            (
                self.application_id,
                str(self.process_id),
                self.process_name.casefold(),
                str(self.window_handle),
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def same_identity(self, other: "DesktopSceneForegroundBinding") -> bool:
        return (
            self.application_id == other.application_id
            and self.process_id == other.process_id
            and self.process_name.casefold() == other.process_name.casefold()
            and self.window_handle == other.window_handle
        )


class DesktopVisualGroundingProvider(Protocol):
    provider_id: str

    def availability(self) -> tuple[bool, str]:
        ...

    def detect(
        self,
        screenshot: DesktopSceneScreenshot,
        *,
        window_rect: DesktopSceneRect,
        max_targets: int,
    ) -> tuple[DesktopVisualGroundingCandidate, ...]:
        ...


class UnavailableDesktopVisualGroundingProvider:
    provider_id = "none"

    def availability(self) -> tuple[bool, str]:
        return False, "no desktop visual-grounding provider is configured"

    def detect(
        self,
        screenshot: DesktopSceneScreenshot,
        *,
        window_rect: DesktopSceneRect,
        max_targets: int,
    ) -> tuple[DesktopVisualGroundingCandidate, ...]:
        return ()


ForegroundProbeFn = Callable[[], DesktopSceneForegroundBinding]
WindowRectFn = Callable[[int, int], DesktopSceneRect]
CaptureFn = Callable[[str], ScreenCaptureArtifact]


class NativeDesktopSceneBuilder:
    """Compose current screenshot/UIA/optional visual grounding into one scene."""

    def __init__(
        self,
        *,
        automation_sense: NativeNamedAutomationControlSense | None = None,
        visual_provider: DesktopVisualGroundingProvider | None = None,
        capture_fn: CaptureFn | None = None,
        window_rect_fn: WindowRectFn | None = None,
        home: str | Path | None = None,
        iou_threshold: float = DESKTOP_SCENE_IOU_MERGE_THRESHOLD,
        max_targets: int = DESKTOP_SCENE_MAX_TARGETS,
    ) -> None:
        threshold = float(iou_threshold)
        if not 0.0 < threshold <= 1.0:
            raise ValueError("desktop scene IoU threshold must be within (0,1]")
        target_limit = int(max_targets)
        if not 1 <= target_limit <= DESKTOP_SCENE_MAX_TARGETS:
            raise ValueError("desktop scene max_targets is outside the bounded contract")
        self.automation_sense = automation_sense or NativeNamedAutomationControlSense()
        self.visual_provider = visual_provider or UnavailableDesktopVisualGroundingProvider()
        self.home = Path(home).expanduser() if home is not None else None
        self.capture_fn = capture_fn or self._capture
        self.window_rect_fn = window_rect_fn or _native_window_rect
        self.iou_threshold = threshold
        self.max_targets = target_limit

    def capture(
        self,
        *,
        event_id: str,
        foreground: DesktopSceneForegroundBinding,
        foreground_probe: ForegroundProbeFn,
    ) -> tuple[DesktopScene, str]:
        normalized_event = str(event_id or "").strip()
        if not normalized_event:
            raise ValueError("desktop scene capture requires a stable event_id")

        artifact = self.capture_fn(normalized_event)
        screenshot = _screenshot_from_artifact(artifact)
        screen_rect = DesktopSceneRect(
            0.0,
            0.0,
            float(screenshot.width),
            float(screenshot.height),
        )
        raw_window_rect = self.window_rect_fn(
            foreground.window_handle,
            foreground.process_id,
        )
        window_rect = _intersection(raw_window_rect, screen_rect)
        if window_rect is None:
            raise DesktopSceneError(
                "foreground window does not intersect the captured primary screen"
            )

        uia_targets, uia_truncated, uia_reasons = self._uia_targets(
            foreground,
            screenshot=screenshot,
            window_rect=window_rect,
        )
        (
            visual_targets,
            visual_truncated,
            visual_reasons,
            visual_provider_id,
            visual_available,
        ) = self._visual_targets(
            screenshot,
            window_rect=window_rect,
        )

        fresh_foreground = foreground_probe()
        if not foreground.same_identity(fresh_foreground):
            raise DesktopSceneError(
                "foreground app/process/window identity changed during desktop scene capture"
            )

        captured_at = utc_now()
        public_foreground = DesktopSceneForeground(
            application_id=foreground.application_id,
            process_name=foreground.process_name,
            class_name=foreground.class_name,
            identity_sha256=foreground.identity_sha256,
            window_rect=window_rect,
        )
        merged, merge_truncated = merge_desktop_scene_targets(
            uia_targets,
            visual_targets,
            iou_threshold=self.iou_threshold,
            max_targets=self.max_targets,
        )

        providers = ["windows_uia"]
        if visual_available:
            providers.append(visual_provider_id)
        grounding_mode = _grounding_mode(merged)
        degraded = _bounded_reasons((*uia_reasons, *visual_reasons))
        scene_id = _scene_id(captured_at, public_foreground, screenshot)
        targets = tuple(
            _assign_target_id(scene_id, target, index)
            for index, target in enumerate(merged)
        )
        scene = DesktopScene(
            scene_id=scene_id,
            captured_at=captured_at,
            foreground=public_foreground,
            screenshot=screenshot,
            targets=targets,
            grounding_mode=grounding_mode,
            providers=tuple(dict.fromkeys(providers)),
            truncated=bool(uia_truncated or visual_truncated or merge_truncated),
            degraded_reasons=degraded,
        )
        scene_path = save_desktop_scene_artifact(
            normalized_event,
            scene,
            home=self.home,
        )
        return scene, str(scene_path)

    def artifact_path(self, event_id: str) -> Path:
        return desktop_scene_artifact_path(event_id, home=self.home)

    def _capture(self, event_id: str) -> ScreenCaptureArtifact:
        return capture_primary_screen_artifact(
            desktop_scene_capture_event_id(event_id),
            home=self.home,
        )

    def _uia_targets(
        self,
        foreground: DesktopSceneForegroundBinding,
        *,
        screenshot: DesktopSceneScreenshot,
        window_rect: DesktopSceneRect,
    ) -> tuple[tuple[DesktopSceneTarget, ...], bool, tuple[str, ...]]:
        rows: list[DesktopSceneTarget] = []
        reasons: list[str] = []
        truncated = False
        for control_type in DESKTOP_SCENE_UIA_CONTROL_TYPES:
            if len(rows) >= self.max_targets:
                truncated = True
                break
            per_type_limit = min(24, self.max_targets - len(rows))
            try:
                scene_list = getattr(
                    self.automation_sense,
                    "list_scene_controls",
                    None,
                )
                if callable(scene_list):
                    observations = scene_list(
                        process_id=foreground.process_id,
                        process_name=foreground.process_name,
                        control_type=control_type,
                        max_candidates=per_type_limit,
                    )
                    if len(observations) >= per_type_limit:
                        truncated = True
                else:
                    observations = self.automation_sense.list_controls(
                        process_id=foreground.process_id,
                        process_name=foreground.process_name,
                        control_type=control_type,
                    )
            except Exception as exc:
                reasons.append(f"uia:{control_type}:{type(exc).__name__}")
                continue
            for observation in observations:
                if len(rows) >= self.max_targets:
                    truncated = True
                    break
                target = _uia_target(
                    observation,
                    control_type=control_type,
                    screenshot_width=screenshot.width,
                    screenshot_height=screenshot.height,
                    window_rect=window_rect,
                )
                if target is not None:
                    rows.append(target)
        return tuple(rows), truncated, _bounded_reasons(reasons)

    def _visual_targets(
        self,
        screenshot: DesktopSceneScreenshot,
        *,
        window_rect: DesktopSceneRect,
    ) -> tuple[
        tuple[DesktopSceneTarget, ...],
        bool,
        tuple[str, ...],
        str,
        bool,
    ]:
        provider_id = _clean(getattr(self.visual_provider, "provider_id", "")) or "visual"
        try:
            available, reason = self.visual_provider.availability()
        except Exception as exc:
            return (
                (),
                False,
                (f"visual:availability:{type(exc).__name__}",),
                provider_id,
                False,
            )
        if not available:
            unavailable = f"visual:{reason}" if reason else "visual:unavailable"
            return (), False, (unavailable,), provider_id, False

        limit = min(self.max_targets, DESKTOP_SCENE_MAX_VISUAL_TARGETS)
        try:
            candidates = self.visual_provider.detect(
                screenshot,
                window_rect=window_rect,
                max_targets=limit,
            )
        except Exception as exc:
            return (
                (),
                False,
                (f"visual:detect:{type(exc).__name__}",),
                provider_id,
                True,
            )

        if not isinstance(candidates, tuple):
            return (
                (),
                False,
                ("visual:provider_contract_invalid",),
                provider_id,
                True,
            )
        truncated = len(candidates) > limit
        rows: list[DesktopSceneTarget] = []
        screen_rect = DesktopSceneRect(
            0.0,
            0.0,
            float(screenshot.width),
            float(screenshot.height),
        )
        for candidate in candidates[:limit]:
            if not isinstance(candidate, DesktopVisualGroundingCandidate):
                continue
            if candidate.provider_id != provider_id:
                continue
            clipped = _intersection(candidate.rect, screen_rect)
            if clipped is None or _intersection(clipped, window_rect) is None:
                continue
            if not _point_inside(window_rect, clipped.center_x, clipped.center_y):
                continue
            rows.append(
                DesktopSceneTarget(
                    target_id="",
                    source="visual",
                    role=candidate.role or "visual_target",
                    accessible_name=candidate.name,
                    automation_id="",
                    rect=clipped,
                    center_x_fraction=clipped.center_x / float(screenshot.width),
                    center_y_fraction=clipped.center_y / float(screenshot.height),
                    enabled=candidate.enabled,
                    editable=candidate.editable,
                    focused=None,
                    supported_patterns=(),
                    visual_confidence=candidate.confidence,
                    provenance=(f"visual:{provider_id}",),
                )
            )
        return tuple(rows), truncated, (), provider_id, True


def merge_desktop_scene_targets(
    uia_targets: Sequence[DesktopSceneTarget],
    visual_targets: Sequence[DesktopSceneTarget],
    *,
    iou_threshold: float = DESKTOP_SCENE_IOU_MERGE_THRESHOLD,
    max_targets: int = DESKTOP_SCENE_MAX_TARGETS,
) -> tuple[tuple[DesktopSceneTarget, ...], bool]:
    """Merge overlapping visual candidates into preferred semantic UIA targets."""

    threshold = float(iou_threshold)
    if not 0.0 < threshold <= 1.0:
        raise ValueError("desktop scene IoU threshold must be within (0,1]")
    limit = max(1, min(int(max_targets), DESKTOP_SCENE_MAX_TARGETS))
    merged = list(uia_targets[:limit])
    truncated = len(uia_targets) > limit
    consumed_uia: set[int] = set()

    for visual in visual_targets:
        best_index = -1
        best_iou = 0.0
        for index, semantic in enumerate(merged):
            if index in consumed_uia or semantic.source not in {"uia", "hybrid"}:
                continue
            overlap = desktop_scene_iou(semantic.rect, visual.rect)
            if overlap >= threshold and overlap > best_iou:
                best_index = index
                best_iou = overlap
        if best_index >= 0:
            semantic = merged[best_index]
            consumed_uia.add(best_index)
            merged[best_index] = replace(
                semantic,
                source="hybrid",
                visual_confidence=visual.visual_confidence,
                provenance=tuple(
                    dict.fromkeys((*semantic.provenance, *visual.provenance))
                ),
            )
            continue
        if len(merged) >= limit:
            truncated = True
            continue
        merged.append(visual)

    return tuple(merged), truncated


def desktop_scene_iou(left: DesktopSceneRect, right: DesktopSceneRect) -> float:
    intersection = _intersection(left, right)
    if intersection is None:
        return 0.0
    intersection_area = intersection.width * intersection.height
    union_area = left.width * left.height + right.width * right.height - intersection_area
    return 0.0 if union_area <= 0 else intersection_area / union_area


def desktop_scene_capture_event_id(event_id: str) -> str:
    normalized = str(event_id or "").strip()
    if not normalized:
        raise ValueError("desktop scene capture requires a stable event_id")
    return f"desktop-scene:{normalized}"


def desktop_scene_artifact_root(home: str | Path | None = None) -> Path:
    root = Path(home).expanduser() if home is not None else get_zn_home()
    return root / "artifacts" / "desktop-scenes"


def desktop_scene_artifact_path(
    event_id: str,
    *,
    home: str | Path | None = None,
) -> Path:
    normalized = str(event_id or "").strip()
    if not normalized:
        raise ValueError("desktop scene artifact requires a stable event_id")
    digest = hashlib.sha256(
        f"windows.desktop.scene.capture:{normalized}".encode("utf-8")
    ).hexdigest()[:24]
    return desktop_scene_artifact_root(home) / f"scene-{digest}.json"


def save_desktop_scene_artifact(
    event_id: str,
    scene: DesktopScene,
    *,
    home: str | Path | None = None,
) -> Path:
    target = desktop_scene_artifact_path(event_id, home=home)
    target.parent.mkdir(parents=True, exist_ok=True)
    scene_data = scene.audit()
    canonical = _canonical_json(scene_data)
    payload = {
        "schema_version": DESKTOP_SCENE_SCHEMA_VERSION,
        "event_id_sha256": hashlib.sha256(
            str(event_id).strip().encode("utf-8")
        ).hexdigest(),
        "scene_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "scene": scene_data,
    }
    temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        os.replace(temp, target)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
    return target


def load_desktop_scene_artifact(
    event_id: str,
    *,
    home: str | Path | None = None,
) -> DesktopScene:
    target = desktop_scene_artifact_path(event_id, home=home)
    root = desktop_scene_artifact_root(home).resolve(strict=False)
    path = target.expanduser().resolve(strict=True)
    if root not in path.parents:
        raise DesktopSceneError("desktop scene artifact escaped the ZN scene root")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise DesktopSceneError(
            f"desktop scene artifact could not be decoded: {type(exc).__name__}"
        ) from exc
    if not isinstance(payload, dict):
        raise DesktopSceneError("desktop scene artifact payload is invalid")
    if int(payload.get("schema_version") or 0) != DESKTOP_SCENE_SCHEMA_VERSION:
        raise DesktopSceneError("desktop scene artifact schema version is unsupported")
    expected_event = hashlib.sha256(
        str(event_id or "").strip().encode("utf-8")
    ).hexdigest()
    if payload.get("event_id_sha256") != expected_event:
        raise DesktopSceneError("desktop scene artifact event identity mismatch")
    raw_scene = payload.get("scene")
    if not isinstance(raw_scene, dict):
        raise DesktopSceneError("desktop scene artifact lacks scene data")
    canonical = _canonical_json(raw_scene)
    if payload.get("scene_sha256") != hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest():
        raise DesktopSceneError("desktop scene artifact metadata digest mismatch")

    scene = _scene_from_mapping(raw_scene)
    inspected = inspect_screen_capture_artifact(
        scene.screenshot.local_path,
        home=home,
    )
    for key in ("local_path", "width", "height", "size_bytes", "sha256"):
        if str(inspected.get(key)) != str(scene.screenshot.audit().get(key)):
            raise DesktopSceneError(
                f"desktop scene screenshot readback mismatch: {key}"
            )
    if scene.scene_id != _scene_id(
        scene.captured_at,
        scene.foreground,
        scene.screenshot,
    ):
        raise DesktopSceneError("desktop scene identity digest mismatch")
    for index, target_row in enumerate(scene.targets):
        if target_row.target_id != _target_id(scene.scene_id, target_row, index):
            raise DesktopSceneError("desktop scene target identity digest mismatch")
    return scene


def inspect_desktop_scene_artifact(
    event_id: str,
    *,
    home: str | Path | None = None,
) -> dict[str, Any]:
    scene = load_desktop_scene_artifact(event_id, home=home)
    return {
        "scene_artifact_path": str(
            desktop_scene_artifact_path(event_id, home=home).resolve()
        ),
        "scene_id": scene.scene_id,
        "grounding_mode": scene.grounding_mode,
        "target_count": len(scene.targets),
        "uia_target_count": scene.uia_target_count,
        "visual_target_count": scene.visual_target_count,
        "truncated": scene.truncated,
        "foreground": scene.foreground.audit(),
        "screenshot": scene.screenshot.audit(),
        "scene": scene.audit(),
    }


def _scene_from_mapping(value: Mapping[str, Any]) -> DesktopScene:
    foreground_raw = value.get("foreground")
    screenshot_raw = value.get("screenshot")
    targets_raw = value.get("targets")
    if not isinstance(foreground_raw, Mapping) or not isinstance(
        screenshot_raw, Mapping
    ):
        raise DesktopSceneError(
            "desktop scene artifact foreground/screenshot is invalid"
        )
    if not isinstance(targets_raw, list) or len(targets_raw) > DESKTOP_SCENE_MAX_TARGETS:
        raise DesktopSceneError("desktop scene artifact targets exceed bounded contract")
    window_rect_raw = foreground_raw.get("window_rect")
    if not isinstance(window_rect_raw, Mapping):
        raise DesktopSceneError("desktop scene foreground window_rect is invalid")
    foreground = DesktopSceneForeground(
        application_id=str(foreground_raw.get("application_id") or ""),
        process_name=str(foreground_raw.get("process_name") or ""),
        class_name=str(foreground_raw.get("class_name") or ""),
        identity_sha256=str(foreground_raw.get("identity_sha256") or ""),
        window_rect=DesktopSceneRect.from_mapping(window_rect_raw),
    )
    screenshot = DesktopSceneScreenshot(
        local_path=str(screenshot_raw.get("local_path") or ""),
        width=int(screenshot_raw.get("width") or 0),
        height=int(screenshot_raw.get("height") or 0),
        size_bytes=int(screenshot_raw.get("size_bytes") or 0),
        sha256=str(screenshot_raw.get("sha256") or ""),
        source=str(screenshot_raw.get("source") or ""),
    )
    targets: list[DesktopSceneTarget] = []
    for raw in targets_raw:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("rect"), Mapping):
            raise DesktopSceneError("desktop scene target artifact row is invalid")
        targets.append(
            DesktopSceneTarget(
                target_id=str(raw.get("target_id") or ""),
                source=str(raw.get("source") or ""),
                role=str(raw.get("role") or ""),
                accessible_name=str(raw.get("accessible_name") or ""),
                automation_id=str(raw.get("automation_id") or ""),
                rect=DesktopSceneRect.from_mapping(raw["rect"]),
                center_x_fraction=float(raw.get("center_x_fraction") or 0.0),
                center_y_fraction=float(raw.get("center_y_fraction") or 0.0),
                enabled=(
                    raw.get("enabled")
                    if isinstance(raw.get("enabled"), bool)
                    else None
                ),
                editable=(
                    raw.get("editable")
                    if isinstance(raw.get("editable"), bool)
                    else None
                ),
                focused=(
                    raw.get("focused")
                    if isinstance(raw.get("focused"), bool)
                    else None
                ),
                supported_patterns=tuple(raw.get("supported_patterns") or ()),
                visual_confidence=(
                    float(raw["visual_confidence"])
                    if raw.get("visual_confidence") is not None
                    else None
                ),
                provenance=tuple(raw.get("provenance") or ()),
            )
        )
    return DesktopScene(
        scene_id=str(value.get("scene_id") or ""),
        captured_at=str(value.get("captured_at") or ""),
        foreground=foreground,
        screenshot=screenshot,
        targets=tuple(targets),
        grounding_mode=str(value.get("grounding_mode") or ""),
        providers=tuple(value.get("providers") or ()),
        truncated=bool(value.get("truncated")),
        degraded_reasons=tuple(value.get("degraded_reasons") or ()),
    )


def _uia_target(
    observation: NamedAutomationControlObservation,
    *,
    control_type: str,
    screenshot_width: int,
    screenshot_height: int,
    window_rect: DesktopSceneRect,
) -> DesktopSceneTarget | None:
    if not isinstance(observation, NamedAutomationControlObservation):
        return None
    try:
        rect = DesktopSceneRect(
            observation.left,
            observation.top,
            observation.right,
            observation.bottom,
        )
    except (TypeError, ValueError):
        return None
    screen_rect = DesktopSceneRect(
        0.0,
        0.0,
        float(screenshot_width),
        float(screenshot_height),
    )
    clipped = _intersection(rect, screen_rect)
    if clipped is None:
        return None
    clipped = _intersection(clipped, window_rect)
    if clipped is None:
        return None
    editable = bool(
        control_type == "edit"
        and observation.is_value_pattern_available
        and observation.value_is_read_only is not True
        and observation.is_keyboard_focusable
        and not observation.is_password
    )
    return DesktopSceneTarget(
        target_id="",
        source="uia",
        role=control_type,
        accessible_name=observation.name,
        automation_id=observation.automation_id,
        rect=clipped,
        center_x_fraction=clipped.center_x / float(screenshot_width),
        center_y_fraction=clipped.center_y / float(screenshot_height),
        enabled=observation.is_enabled,
        editable=editable,
        focused=observation.has_keyboard_focus,
        supported_patterns=observation.supported_patterns,
        visual_confidence=None,
        provenance=("windows_uia",),
    )


def _screenshot_from_artifact(
    artifact: ScreenCaptureArtifact,
) -> DesktopSceneScreenshot:
    return DesktopSceneScreenshot(
        local_path=artifact.local_path,
        width=artifact.width,
        height=artifact.height,
        size_bytes=artifact.size_bytes,
        sha256=artifact.sha256,
        source=artifact.source,
    )


def _grounding_mode(targets: Sequence[DesktopSceneTarget]) -> str:
    has_uia = any(target.source in {"uia", "hybrid"} for target in targets)
    has_visual = any(target.source in {"visual", "hybrid"} for target in targets)
    if has_uia and has_visual:
        return "hybrid"
    if has_uia:
        return "uia_only"
    if has_visual:
        return "visual_only"
    return "screenshot_only"


def _scene_seed(
    captured_at: str,
    foreground: DesktopSceneForeground,
    screenshot: DesktopSceneScreenshot,
) -> str:
    return "\x1f".join(
        (
            captured_at,
            foreground.application_id,
            foreground.identity_sha256,
            screenshot.sha256,
            str(screenshot.width),
            str(screenshot.height),
        )
    )


def _scene_id(
    captured_at: str,
    foreground: DesktopSceneForeground,
    screenshot: DesktopSceneScreenshot,
) -> str:
    return "desktop-scene-" + hashlib.sha256(
        _scene_seed(captured_at, foreground, screenshot).encode("utf-8")
    ).hexdigest()[:24]


def _assign_target_id(
    scene_id: str,
    target: DesktopSceneTarget,
    index: int,
) -> DesktopSceneTarget:
    return replace(
        target,
        target_id=_target_id(scene_id, target, index),
    )


def _target_id(
    scene_id: str,
    target: DesktopSceneTarget,
    index: int,
) -> str:
    material = "\x1f".join(
        (
            scene_id,
            str(index),
            target.source,
            target.role,
            target.accessible_name,
            target.automation_id,
            f"{target.rect.left:.3f}",
            f"{target.rect.top:.3f}",
            f"{target.rect.right:.3f}",
            f"{target.rect.bottom:.3f}",
        )
    )
    return "desktop-target-" + hashlib.sha256(
        material.encode("utf-8")
    ).hexdigest()[:24]


def _intersection(
    left: DesktopSceneRect,
    right: DesktopSceneRect,
) -> DesktopSceneRect | None:
    x1 = max(left.left, right.left)
    y1 = max(left.top, right.top)
    x2 = min(left.right, right.right)
    y2 = min(left.bottom, right.bottom)
    if x2 <= x1 or y2 <= y1:
        return None
    return DesktopSceneRect(x1, y1, x2, y2)


def _point_inside(rect: DesktopSceneRect, x: float, y: float) -> bool:
    return (
        rect.left <= float(x) <= rect.right
        and rect.top <= float(y) <= rect.bottom
    )


def _bounded_reasons(values: Sequence[str]) -> tuple[str, ...]:
    rows = tuple(
        dict.fromkeys(
            _clean(value)[:240]
            for value in values
            if _clean(value)
        )
    )
    return rows[:_MAX_DEGRADED_REASONS]


def _clean(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _native_window_rect(hwnd: int, expected_pid: int) -> DesktopSceneRect:
    if os.name != "nt":
        raise DesktopSceneError(
            "desktop scene window geometry is available only on Windows"
        )
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowRect.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.RECT),
    ]
    user32.GetWindowRect.restype = wintypes.BOOL

    current = int(user32.GetForegroundWindow() or 0)
    if current != int(hwnd):
        raise DesktopSceneError(
            "foreground window changed before desktop scene geometry read"
        )
    pid = wintypes.DWORD(0)
    thread_id = int(
        user32.GetWindowThreadProcessId(current, ctypes.byref(pid))
    )
    if thread_id <= 0 or int(pid.value) != int(expected_pid):
        raise DesktopSceneError(
            "foreground process changed before desktop scene geometry read"
        )
    rect = wintypes.RECT()
    if not user32.GetWindowRect(current, ctypes.byref(rect)):
        raise DesktopSceneError(
            "Windows GetWindowRect failed for foreground scene window"
        )
    return DesktopSceneRect(
        float(rect.left),
        float(rect.top),
        float(rect.right),
        float(rect.bottom),
    )
