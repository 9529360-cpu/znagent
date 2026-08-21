from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Callable

from .models import utc_now

if TYPE_CHECKING:
    from .intentional_resident import IntentionalResidentRuntime


@dataclass(frozen=True, slots=True)
class VisualFrame:
    """A compact retina sample. Raw pixels never leave the capture call."""

    frame_hash: str
    width: int
    height: int
    source: str = "primary-screen"
    captured_at: str = field(default_factory=utc_now)
    region_signatures: tuple[str, ...] = ()
    grid_columns: int = 0
    grid_rows: int = 0
    mean_luminance: float | None = None


@dataclass(frozen=True, slots=True)
class VisualObservation:
    frame_hash: str
    previous_frame_hash: str | None
    width: int
    height: int
    source: str
    changed: bool
    captured_at: str
    changed_region_indices: tuple[int, ...] = ()
    change_ratio: float = 0.0
    change_scale: str = "none"
    luminance_delta: float | None = None


@dataclass(slots=True)
class VisualSenseState:
    sensor_id: str = "host-screen"
    enabled: bool = True
    interval_seconds: float = 5.0
    last_frame_hash: str | None = None
    last_region_signatures: tuple[str, ...] = ()
    last_grid_columns: int = 0
    last_grid_rows: int = 0
    last_mean_luminance: float | None = None
    last_sampled_at: str | None = None
    last_change_at: str | None = None
    last_error: str | None = None
    sample_count: int = 0
    change_count: int = 0


VisualCaptureFn = Callable[[], VisualFrame]


class NativeVisualSense:
    """Resident-owned low-level screen-change sense.

    The sensor lives with the resident service rather than the Electron face.
    Raw screenshot pixels are discarded inside the capture call. The resident
    retains only compact visual structure: a frame fingerprint, quantized coarse
    region signatures, screen dimensions and aggregate luminance. This gives
    native Thought something richer than a binary "screen changed" signal while
    keeping image interpretation local and model-free.
    """

    _GRID_COLUMNS = 4
    _GRID_ROWS = 3

    def __init__(
        self,
        resident: IntentionalResidentRuntime,
        *,
        capture_fn: VisualCaptureFn | None = None,
        interval_seconds: float = 5.0,
    ):
        self.resident = resident
        self.store = resident.store
        self.capture_fn = capture_fn or self._capture_primary_screen
        self.interval_seconds = max(0.1, float(interval_seconds))
        self._init_schema()
        state = self._load_state()
        if state is None:
            state = VisualSenseState(interval_seconds=self.interval_seconds)
        else:
            state.interval_seconds = self.interval_seconds
        self._save_state(state)

    def status(self) -> VisualSenseState:
        state = self._load_state()
        if state is None:
            state = VisualSenseState(interval_seconds=self.interval_seconds)
            self._save_state(state)
        return state

    def due(self, *, now: datetime | None = None) -> bool:
        state = self.status()
        if not state.enabled:
            return False
        last = self._parse_time(state.last_sampled_at)
        if last is None:
            return True
        current = now or datetime.now(timezone.utc)
        return current >= last + timedelta(seconds=state.interval_seconds)

    def maybe_sample(self) -> VisualObservation | None:
        if not self.due():
            return None
        return self.sample()

    def sample(self) -> VisualObservation | None:
        state = self.status()
        if not state.enabled:
            return None
        sampled_at = utc_now()
        try:
            frame = self.capture_fn()
            digest = str(frame.frame_hash or "").strip()
            if not digest:
                raise ValueError("visual capture returned an empty frame hash")
            width = max(1, int(frame.width))
            height = max(1, int(frame.height))
            captured_at = str(frame.captured_at or sampled_at)
            source = str(frame.source or "host-screen").strip() or "host-screen"
            regions = tuple(
                str(item).strip()
                for item in tuple(frame.region_signatures or ())
                if str(item).strip()
            )
            columns = max(0, int(frame.grid_columns or 0))
            rows = max(0, int(frame.grid_rows or 0))
            if regions and columns * rows != len(regions):
                columns = 0
                rows = 0
            luminance = self._unit_optional(frame.mean_luminance)
        except Exception as exc:
            state.last_sampled_at = sampled_at
            state.last_error = f"{type(exc).__name__}: {exc}"[:1000]
            state.sample_count += 1
            self._save_state(state)
            return None

        previous_hash = state.last_frame_hash
        previous_regions = tuple(state.last_region_signatures or ())
        structured_comparison = bool(
            regions
            and previous_regions
            and len(regions) == len(previous_regions)
            and columns > 0
            and rows > 0
            and columns == state.last_grid_columns
            and rows == state.last_grid_rows
        )
        if structured_comparison:
            changed_regions = tuple(
                index
                for index, (before, after) in enumerate(zip(previous_regions, regions))
                if before != after
            )
            changed = bool(changed_regions)
            change_ratio = len(changed_regions) / len(regions)
        else:
            changed_regions = ()
            changed = previous_hash != digest
            change_ratio = 1.0 if changed and previous_hash is not None else 0.0

        initial = previous_hash is None
        if initial:
            changed = True
            change_ratio = 1.0
            changed_regions = tuple(range(len(regions))) if regions else ()
        change_scale = self._change_scale(
            initial=initial,
            changed=changed,
            change_ratio=change_ratio,
        )
        luminance_delta = (
            round(luminance - state.last_mean_luminance, 5)
            if luminance is not None and state.last_mean_luminance is not None
            else None
        )

        state.last_frame_hash = digest
        state.last_region_signatures = regions
        state.last_grid_columns = columns
        state.last_grid_rows = rows
        state.last_mean_luminance = luminance
        state.last_sampled_at = captured_at
        state.last_error = None
        state.sample_count += 1
        if changed:
            state.last_change_at = captured_at
            state.change_count += 1
        self._save_state(state)

        observation = VisualObservation(
            frame_hash=digest,
            previous_frame_hash=previous_hash,
            width=width,
            height=height,
            source=source,
            changed=changed,
            captured_at=captured_at,
            changed_region_indices=changed_regions,
            change_ratio=round(change_ratio, 5),
            change_scale=change_scale,
            luminance_delta=luminance_delta,
        )
        if not changed:
            return observation

        visual_areas = self._visual_areas(changed_regions, columns, rows)
        luminance_direction = self._luminance_direction(luminance_delta)
        region_count = len(regions)
        changed_count = len(changed_regions)
        if initial:
            summary = f"host screen became visible through resident vision ({width}x{height})"
        elif structured_comparison:
            summary = (
                f"host screen changed through resident vision ({width}x{height}); "
                f"{change_scale} change across {changed_count}/{region_count} coarse regions"
            )
        else:
            summary = f"host screen changed through resident vision ({width}x{height})"

        features = [
            "screen",
            "initial-frame" if initial else "changed",
            f"size:{width}x{height}",
            f"capture:{source}",
            f"visual_change:{change_scale}",
        ]
        features.extend(f"visual_area:{area}" for area in visual_areas)
        if luminance_direction:
            features.append(f"luminance:{luminance_direction}")

        self.resident.perceive_visual(
            summary,
            features=tuple(features),
            source="resident-retina",
            salience=self._change_salience(initial, change_ratio),
            valence=0.0,
            arousal=self._change_arousal(initial, change_ratio),
            metadata={
                "frame_hash": digest,
                "previous_frame_hash": previous_hash,
                "width": width,
                "height": height,
                "capture_source": source,
                "captured_at": captured_at,
                "raw_frame_persisted": False,
                "structured_regions": region_count,
                "changed_region_indices": list(changed_regions),
                "changed_region_count": changed_count,
                "change_ratio": round(change_ratio, 5),
                "change_scale": change_scale,
                "visual_areas": list(visual_areas),
                "mean_luminance": luminance,
                "luminance_delta": luminance_delta,
            },
        )
        return observation

    def set_enabled(self, enabled: bool) -> VisualSenseState:
        state = self.status()
        state.enabled = bool(enabled)
        self._save_state(state)
        return state

    @classmethod
    def _capture_primary_screen(cls) -> VisualFrame:
        # Pillow already ships with the resident environment. Import lazily so
        # headless/service startup does not require an active display merely to
        # construct ZN's visual organ.
        from PIL import Image, ImageGrab, ImageStat

        captured = ImageGrab.grab()
        try:
            width, height = captured.size
            if width <= 0 or height <= 0:
                raise RuntimeError("screen capture returned an empty image")
            compact = captured.convert("RGB")
            try:
                max_width = 384
                if compact.width > max_width:
                    ratio = max_width / compact.width
                    target = (max_width, max(1, round(compact.height * ratio)))
                    compact.thumbnail(target, Image.Resampling.BILINEAR)

                digest = hashlib.sha256()
                digest.update(f"{compact.width}x{compact.height}:".encode("ascii"))
                digest.update(compact.tobytes())

                grayscale = compact.convert("L")
                try:
                    region_signatures = cls._region_signatures(grayscale, Image)
                    mean_luminance = round(
                        float(ImageStat.Stat(grayscale).mean[0]) / 255.0,
                        5,
                    )
                finally:
                    grayscale.close()

                return VisualFrame(
                    frame_hash=digest.hexdigest(),
                    width=compact.width,
                    height=compact.height,
                    source="pillow-screen",
                    region_signatures=region_signatures,
                    grid_columns=cls._GRID_COLUMNS,
                    grid_rows=cls._GRID_ROWS,
                    mean_luminance=mean_luminance,
                )
            finally:
                compact.close()
        finally:
            captured.close()

    @classmethod
    def _region_signatures(cls, grayscale, image_module) -> tuple[str, ...]:
        signatures: list[str] = []
        width, height = grayscale.size
        for row in range(cls._GRID_ROWS):
            top = round(row * height / cls._GRID_ROWS)
            bottom = round((row + 1) * height / cls._GRID_ROWS)
            for column in range(cls._GRID_COLUMNS):
                left = round(column * width / cls._GRID_COLUMNS)
                right = round((column + 1) * width / cls._GRID_COLUMNS)
                tile = grayscale.crop((left, top, max(left + 1, right), max(top + 1, bottom)))
                try:
                    sample = tile.resize((4, 4), image_module.Resampling.BILINEAR)
                    try:
                        # Quantization makes the retina robust to tiny antialiasing,
                        # cursor shimmer and compression noise while preserving broad
                        # local layout change. The values are derived locally and raw
                        # image bytes are still discarded immediately.
                        quantized = bytes(
                            min(7, max(0, int(value) // 32))
                            for value in sample.getdata()
                        )
                    finally:
                        sample.close()
                finally:
                    tile.close()
                signatures.append(hashlib.sha256(quantized).hexdigest()[:12])
        return tuple(signatures)

    @staticmethod
    def _change_scale(*, initial: bool, changed: bool, change_ratio: float) -> str:
        if initial:
            return "initial"
        if not changed:
            return "none"
        if change_ratio <= 0.25:
            return "local"
        if change_ratio <= 0.67:
            return "broad"
        return "global"

    @staticmethod
    def _change_salience(initial: bool, ratio: float) -> float:
        if initial:
            return 0.34
        return min(0.74, 0.38 + 0.34 * max(0.0, min(1.0, ratio)))

    @staticmethod
    def _change_arousal(initial: bool, ratio: float) -> float:
        if initial:
            return 0.22
        return min(0.68, 0.26 + 0.34 * max(0.0, min(1.0, ratio)))

    @staticmethod
    def _luminance_direction(delta: float | None) -> str | None:
        if delta is None:
            return None
        if delta >= 0.08:
            return "brighter"
        if delta <= -0.08:
            return "darker"
        return "stable"

    @staticmethod
    def _visual_areas(
        indices: tuple[int, ...],
        columns: int,
        rows: int,
    ) -> tuple[str, ...]:
        if not indices or columns <= 0 or rows <= 0:
            return ()
        areas: list[str] = []
        for index in indices:
            row = index // columns
            column = index % columns
            vertical = (
                "top"
                if row < rows / 3
                else "bottom"
                if row >= (2 * rows) / 3
                else "middle"
            )
            horizontal = (
                "left"
                if column < columns / 3
                else "right"
                if column >= (2 * columns) / 3
                else "center"
            )
            areas.append(f"{vertical}-{horizontal}")
        return tuple(dict.fromkeys(areas))[:6]

    @staticmethod
    def _unit_optional(value: float | None) -> float | None:
        if value is None:
            return None
        try:
            return round(max(0.0, min(1.0, float(value))), 5)
        except (TypeError, ValueError):
            return None

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS visual_sense_state(
                    sensor_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _load_state(self) -> VisualSenseState | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT data FROM visual_sense_state WHERE sensor_id=?",
                ("host-screen",),
            ).fetchone()
        if row is None:
            return None
        raw = json.loads(row["data"])
        raw.setdefault("enabled", True)
        raw.setdefault("interval_seconds", self.interval_seconds)
        raw.setdefault("last_frame_hash", None)
        raw["last_region_signatures"] = tuple(raw.get("last_region_signatures") or ())
        raw.setdefault("last_grid_columns", 0)
        raw.setdefault("last_grid_rows", 0)
        raw.setdefault("last_mean_luminance", None)
        raw.setdefault("last_sampled_at", None)
        raw.setdefault("last_change_at", None)
        raw.setdefault("last_error", None)
        raw.setdefault("sample_count", 0)
        raw.setdefault("change_count", 0)
        return VisualSenseState(**raw)

    def _save_state(self, state: VisualSenseState) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO visual_sense_state(sensor_id,data) VALUES(?,?)",
                (
                    state.sensor_id,
                    json.dumps(asdict(state), ensure_ascii=False, separators=(",", ":")),
                ),
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @staticmethod
    def _parse_time(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError):
            return None
