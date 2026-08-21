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


@dataclass(frozen=True, slots=True)
class VisualObservation:
    frame_hash: str
    previous_frame_hash: str | None
    width: int
    height: int
    source: str
    changed: bool
    captured_at: str


@dataclass(slots=True)
class VisualSenseState:
    sensor_id: str = "host-screen"
    enabled: bool = True
    interval_seconds: float = 5.0
    last_frame_hash: str | None = None
    last_sampled_at: str | None = None
    last_change_at: str | None = None
    last_error: str | None = None
    sample_count: int = 0
    change_count: int = 0


VisualCaptureFn = Callable[[], VisualFrame]


class NativeVisualSense:
    """Resident-owned low-level screen-change sense.

    The sensor lives with the resident service rather than the Electron face.
    It keeps only a downsampled frame fingerprint and compact metadata. Raw
    screenshot pixels are discarded inside the capture call and are never
    persisted or sent to an external model by this organ.
    """

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
        except Exception as exc:
            state.last_sampled_at = sampled_at
            state.last_error = f"{type(exc).__name__}: {exc}"[:1000]
            state.sample_count += 1
            self._save_state(state)
            return None

        previous = state.last_frame_hash
        changed = previous != digest
        state.last_frame_hash = digest
        state.last_sampled_at = captured_at
        state.last_error = None
        state.sample_count += 1
        if changed:
            state.last_change_at = captured_at
            state.change_count += 1
        self._save_state(state)

        observation = VisualObservation(
            frame_hash=digest,
            previous_frame_hash=previous,
            width=width,
            height=height,
            source=source,
            changed=changed,
            captured_at=captured_at,
        )
        if not changed:
            return observation

        initial = previous is None
        self.resident.perceive_visual(
            (
                f"host screen became visible through resident vision ({width}x{height})"
                if initial
                else f"host screen changed through resident vision ({width}x{height})"
            ),
            features=(
                "screen",
                "initial-frame" if initial else "changed",
                f"size:{width}x{height}",
                f"capture:{source}",
            ),
            source="resident-retina",
            salience=0.34 if initial else 0.46,
            valence=0.0,
            arousal=0.22 if initial else 0.34,
            metadata={
                "frame_hash": digest,
                "previous_frame_hash": previous,
                "width": width,
                "height": height,
                "capture_source": source,
                "captured_at": captured_at,
                "raw_frame_persisted": False,
            },
        )
        return observation

    def set_enabled(self, enabled: bool) -> VisualSenseState:
        state = self.status()
        state.enabled = bool(enabled)
        self._save_state(state)
        return state

    @staticmethod
    def _capture_primary_screen() -> VisualFrame:
        # Pillow already ships with the resident environment. Import lazily so
        # headless/service startup does not require an active display merely to
        # construct ZN's visual organ.
        from PIL import Image, ImageGrab

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
                return VisualFrame(
                    frame_hash=digest.hexdigest(),
                    width=compact.width,
                    height=compact.height,
                    source="pillow-screen",
                )
            finally:
                compact.close()
        finally:
            captured.close()

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
