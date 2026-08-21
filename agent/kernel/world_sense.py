from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable

from .models import utc_now

if TYPE_CHECKING:
    from .intentional_resident import IntentionalResidentRuntime


WebSearchFn = Callable[[str, int], str]


@dataclass(slots=True)
class WorldFocus:
    """A durable part of the outside world ZN has chosen to keep noticing."""

    focus_id: str
    topic: str
    priority: int = 0
    interval_seconds: int = 1800
    enabled: bool = True
    source: str = "self"
    last_observed_at: str | None = None
    last_observation_hash: str | None = None
    last_error: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class WorldObservation:
    observation_id: str
    focus_id: str
    topic: str
    summary: str
    source: str
    result_hash: str
    changed: bool
    captured_at: str = field(default_factory=utc_now)


class NativeWorldSense:
    """A rate-limited web/world sensory organ for the resident.

    This is deliberately not a research agent and does not ask an LLM what the
    web means. ZN chooses a durable focus, this organ periodically samples the
    outside world through the mature Hermes web-search stack, and the resulting
    percept enters the same associative nervous system as vision, action, and
    thought. Meaning and follow-up remain ZN's job.
    """

    def __init__(self, resident: IntentionalResidentRuntime):
        self.resident = resident
        self.store = resident.store
        self._init_schema()

    def follow(
        self,
        topic: str,
        *,
        priority: int = 0,
        interval_seconds: int = 1800,
        source: str = "self",
    ) -> WorldFocus:
        text = str(topic or "").strip()
        if not text:
            raise ValueError("world focus topic must not be empty")
        interval = max(60, int(interval_seconds))
        existing = self._find_topic(text)
        now = utc_now()
        if existing is None:
            focus = WorldFocus(
                focus_id=f"world-{uuid.uuid4().hex[:12]}",
                topic=text,
                priority=int(priority),
                interval_seconds=interval,
                source=str(source or "self").strip() or "self",
                created_at=now,
                updated_at=now,
            )
        else:
            focus = existing
            focus.priority = int(priority)
            focus.interval_seconds = interval
            focus.enabled = True
            focus.source = str(source or focus.source).strip() or focus.source
            focus.updated_at = now
        self._save_focus(focus)
        self.resident.nervous.perceive(
            "world_attention",
            f"I chose to keep noticing changes in: {focus.topic}",
            features=("world_focus", focus.topic),
            source="world_sense",
            salience=min(1.0, 0.52 + max(0, focus.priority) * 0.03),
            valence=0.10,
            arousal=0.34,
            metadata={"focus_id": focus.focus_id},
        )
        return focus

    def unfollow(self, focus_id: str) -> WorldFocus:
        focus = self._require(focus_id)
        focus.enabled = False
        focus.updated_at = utc_now()
        self._save_focus(focus)
        return focus

    def focuses(self, *, enabled_only: bool = True, limit: int = 100) -> list[WorldFocus]:
        query = "SELECT data FROM world_focuses"
        params: list[Any] = []
        if enabled_only:
            query += " WHERE enabled=1"
        query += " ORDER BY priority DESC, updated_at ASC LIMIT ?"
        params.append(max(1, int(limit)))
        with closing(self._connect()) as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._from_raw(json.loads(row["data"])) for row in rows]

    def due_focus(self, *, now: datetime | None = None) -> WorldFocus | None:
        current = now or datetime.now(timezone.utc)
        for focus in self.focuses(enabled_only=True, limit=100):
            if focus.last_observed_at is None:
                return focus
            last = self._parse_time(focus.last_observed_at)
            if last is None:
                return focus
            if current >= last + timedelta(seconds=max(60, focus.interval_seconds)):
                return focus
        return None

    def maybe_observe(
        self,
        *,
        search_fn: WebSearchFn | None = None,
        limit: int = 5,
    ) -> WorldObservation | None:
        focus = self.due_focus()
        if focus is None:
            return None
        return self.observe(focus.focus_id, search_fn=search_fn, limit=limit)

    def observe(
        self,
        focus_id: str,
        *,
        search_fn: WebSearchFn | None = None,
        limit: int = 5,
    ) -> WorldObservation:
        focus = self._require(focus_id)
        if not focus.enabled:
            raise ValueError(f"world focus is disabled: {focus_id}")
        search = search_fn or self._search
        try:
            raw = search(focus.topic, max(1, min(10, int(limit))))
            summary, features = self._sensor_summary(raw, focus.topic)
            digest = hashlib.sha256(summary.encode("utf-8")).hexdigest()
            changed = digest != focus.last_observation_hash
            observation = WorldObservation(
                observation_id=f"obs-{uuid.uuid4().hex[:12]}",
                focus_id=focus.focus_id,
                topic=focus.topic,
                summary=summary,
                source="web",
                result_hash=digest,
                changed=changed,
            )
            focus.last_observed_at = observation.captured_at
            focus.last_observation_hash = digest
            focus.last_error = None
            focus.updated_at = observation.captured_at
            self._save_focus(focus)

            self.resident.perceive_world(
                summary,
                features=(focus.topic, *features),
                source="web",
                salience=0.72 if changed else 0.42,
                valence=0.0,
                arousal=0.52 if changed else 0.24,
                metadata={
                    "focus_id": focus.focus_id,
                    "observation_id": observation.observation_id,
                    "changed": changed,
                },
            )
            return observation
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            focus.last_observed_at = utc_now()
            focus.last_error = message[:1000]
            focus.updated_at = focus.last_observed_at
            self._save_focus(focus)
            self.resident.nervous.perceive(
                "world_sense",
                f"world observation failed for {focus.topic}: {message[:500]}",
                features=(focus.topic, "failure"),
                source="world_sense",
                salience=0.62,
                valence=-0.35,
                arousal=0.58,
                metadata={"focus_id": focus.focus_id},
            )
            raise

    @staticmethod
    def _search(query: str, limit: int) -> str:
        from tools.web_tools import web_search_tool

        return web_search_tool(query, limit=limit)

    @classmethod
    def _sensor_summary(cls, raw: str, topic: str) -> tuple[str, tuple[str, ...]]:
        text = str(raw or "").strip()
        if not text:
            return f"No world observations were returned for {topic}", ("empty",)

        try:
            payload = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            compact = " ".join(text.split())[:5000]
            return f"World observation about {topic}: {compact}", ("web",)

        items = cls._result_items(payload)
        if not items:
            compact = " ".join(text.split())[:5000]
            return f"World observation about {topic}: {compact}", ("web",)

        lines: list[str] = []
        features: list[str] = ["web"]
        for item in items[:8]:
            if isinstance(item, str):
                line = " ".join(item.split())[:700]
                if line:
                    lines.append(line)
                continue
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("name") or "").strip()
            url = str(item.get("url") or item.get("href") or "").strip()
            excerpt = str(
                item.get("snippet")
                or item.get("text")
                or item.get("content")
                or item.get("description")
                or ""
            ).strip()
            parts = [part for part in (title, excerpt[:600], url) if part]
            if parts:
                lines.append(" | ".join(parts)[:900])
            if title:
                features.extend(cls._feature_tokens(title))
        if not lines:
            compact = " ".join(text.split())[:5000]
            return f"World observation about {topic}: {compact}", tuple(features)
        return (
            f"World observation about {topic}: " + " || ".join(lines)[:5000],
            tuple(dict.fromkeys(features))[:24],
        )

    @staticmethod
    def _result_items(payload: Any) -> list[Any]:
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []
        for key in ("results", "data", "items", "documents", "sources"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested = NativeWorldSense._result_items(value)
                if nested:
                    return nested
        return []

    @staticmethod
    def _feature_tokens(text: str) -> list[str]:
        cleaned = " ".join(str(text or "").lower().split())
        return [token.strip(".,:;!?()[]{}") for token in cleaned.split() if len(token) >= 4][:12]

    def _find_topic(self, topic: str) -> WorldFocus | None:
        normalized = " ".join(topic.lower().split())
        for focus in self.focuses(enabled_only=False, limit=500):
            if " ".join(focus.topic.lower().split()) == normalized:
                return focus
        return None

    def _require(self, focus_id: str) -> WorldFocus:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT data FROM world_focuses WHERE focus_id=?",
                (str(focus_id),),
            ).fetchone()
        if not row:
            raise KeyError(f"unknown world focus: {focus_id}")
        return self._from_raw(json.loads(row["data"]))

    def _save_focus(self, focus: WorldFocus) -> None:
        focus.updated_at = utc_now()
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO world_focuses"
                "(focus_id,enabled,priority,updated_at,data) VALUES(?,?,?,?,?)",
                (
                    focus.focus_id,
                    1 if focus.enabled else 0,
                    focus.priority,
                    focus.updated_at,
                    json.dumps(asdict(focus), ensure_ascii=False, separators=(",", ":")),
                ),
            )
            conn.commit()

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS world_focuses(
                    focus_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    priority INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_world_focuses_due
                    ON world_focuses(enabled, priority DESC, updated_at ASC);
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @staticmethod
    def _from_raw(raw: dict[str, Any]) -> WorldFocus:
        data = dict(raw)
        data.setdefault("last_observed_at", None)
        data.setdefault("last_observation_hash", None)
        data.setdefault("last_error", None)
        return WorldFocus(**data)

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
