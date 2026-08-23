from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
    last_source_state: dict[str, dict[str, str]] = field(default_factory=dict)
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
    source_count: int = 0
    new_sources: tuple[str, ...] = ()
    updated_sources: tuple[str, ...] = ()
    removed_sources: tuple[str, ...] = ()
    stable_sources: tuple[str, ...] = ()
    captured_at: str = field(default_factory=utc_now)


class NativeWorldSense:
    """A rate-limited web/world sensory organ for the resident.

    This is deliberately not a research agent and does not ask an LLM what the
    web means. ZN chooses a durable focus, this organ periodically samples the
    outside world through a ZN-owned replaceable web resource, and the resulting
    percept enters the same associative nervous system as vision, action, and
    thought. Meaning and follow-up remain ZN's job.

    Search result order and provider formatting are not treated as world change.
    When structured sources are available, the organ retains a bounded source
    snapshot and compares stable source identity plus content fingerprints. This
    lets later perception distinguish new, updated, removed, and stable sources
    across resident restarts without using a model or naive aggregate text
    equality.
    """

    _TRACKING_QUERY_PREFIXES = ("utm_",)
    _TRACKING_QUERY_KEYS = {
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "ref",
        "ref_src",
    }

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
            summary, features, source_state = self._sensor_snapshot(raw, focus.topic)
            previous_state = dict(focus.last_source_state or {})
            new_keys: tuple[str, ...] = ()
            updated_keys: tuple[str, ...] = ()
            removed_keys: tuple[str, ...] = ()
            stable_keys: tuple[str, ...] = ()

            if source_state:
                new_keys, updated_keys, removed_keys, stable_keys = self._diff_sources(
                    previous_state,
                    source_state,
                )
                digest = self._source_state_hash(source_state)
                changed = bool(new_keys or updated_keys or removed_keys)
                if not previous_state:
                    changed = True
            else:
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
                source_count=len(source_state),
                new_sources=self._source_labels(source_state, new_keys),
                updated_sources=self._source_labels(source_state, updated_keys),
                removed_sources=self._source_labels(previous_state, removed_keys),
                stable_sources=self._source_labels(source_state, stable_keys),
            )
            focus.last_observed_at = observation.captured_at
            focus.last_observation_hash = digest
            if source_state:
                focus.last_source_state = source_state
            focus.last_error = None
            focus.updated_at = observation.captured_at
            self._save_focus(focus)

            delta = {
                "new": list(observation.new_sources),
                "updated": list(observation.updated_sources),
                "removed": list(observation.removed_sources),
                "stable": list(observation.stable_sources),
            }
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
                    "source_count": observation.source_count,
                    "world_delta": delta,
                },
            )
            if previous_state and source_state and changed:
                self._remember_delta(focus, observation, source_state, previous_state)
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

    def _remember_delta(
        self,
        focus: WorldFocus,
        observation: WorldObservation,
        current: dict[str, dict[str, str]],
        previous: dict[str, dict[str, str]],
    ) -> None:
        features = ["world_delta"]
        parts: list[str] = []
        if observation.new_sources:
            features.append("new_source")
            parts.append("new: " + ", ".join(observation.new_sources[:4]))
        if observation.updated_sources:
            features.append("updated_source")
            parts.append("updated: " + ", ".join(observation.updated_sources[:4]))
        if observation.removed_sources:
            features.append("removed_source")
            parts.append("removed: " + ", ".join(observation.removed_sources[:4]))

        involved = {
            *observation.new_sources,
            *observation.updated_sources,
            *observation.removed_sources,
        }
        for state in (current, previous):
            for item in state.values():
                label = self._source_label(item, "")
                domain = str(item.get("domain") or "").strip().lower()
                if label in involved and domain:
                    features.append(f"source_domain:{domain}")

        summary = (
            f"World change about {focus.topic}: "
            + ("; ".join(parts) if parts else "structured sources changed")
        )[:2200]
        self.resident.nervous.perceive(
            "world",
            summary,
            features=(focus.topic, *tuple(dict.fromkeys(features))[:20]),
            source="world_sense",
            salience=0.78,
            valence=0.0,
            arousal=0.58,
            metadata={
                "focus_id": focus.focus_id,
                "observation_id": observation.observation_id,
                "world_change": True,
                "new_sources": list(observation.new_sources),
                "updated_sources": list(observation.updated_sources),
                "removed_sources": list(observation.removed_sources),
            },
        )

    @staticmethod
    def _search(query: str, limit: int) -> str:
        from .web_resource import web_search_json

        return web_search_json(query, limit=limit)

    @classmethod
    def _sensor_snapshot(
        cls,
        raw: str,
        topic: str,
    ) -> tuple[str, tuple[str, ...], dict[str, dict[str, str]]]:
        text = str(raw or "").strip()
        if not text:
            return f"No world observations were returned for {topic}", ("empty",), {}

        try:
            payload = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            compact = " ".join(text.split())[:5000]
            return f"World observation about {topic}: {compact}", ("web",), {}

        items = cls._result_items(payload)
        if not items:
            compact = " ".join(text.split())[:5000]
            return f"World observation about {topic}: {compact}", ("web",), {}

        records: dict[str, dict[str, str]] = {}
        display: dict[str, str] = {}
        features: list[str] = ["web", "structured_world"]
        for item in items[:16]:
            if isinstance(item, str):
                compact = " ".join(item.split())[:900]
                if not compact:
                    continue
                identity = f"text:{hashlib.sha256(compact.lower().encode()).hexdigest()[:20]}"
                fingerprint = hashlib.sha256(compact.encode()).hexdigest()[:24]
                records[identity] = {
                    "fingerprint": fingerprint,
                    "title": compact[:300],
                    "url": "",
                    "domain": "",
                }
                display[identity] = compact
                features.extend(cls._feature_tokens(compact))
                continue
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("name") or "").strip()
            url = cls._canonical_url(
                str(item.get("url") or item.get("href") or "").strip()
            )
            excerpt = str(
                item.get("snippet")
                or item.get("text")
                or item.get("content")
                or item.get("description")
                or ""
            ).strip()
            identity_basis = url or cls._normalize_identity(title)
            if not identity_basis:
                identity_basis = cls._normalize_identity(excerpt[:500])
            if not identity_basis:
                continue
            identity = (
                f"url:{identity_basis}"
                if url
                else f"title:{hashlib.sha256(identity_basis.encode()).hexdigest()[:20]}"
            )
            content = "\n".join(
                part for part in (title, excerpt[:1600], url) if part
            )
            fingerprint = hashlib.sha256(content.encode()).hexdigest()[:24]
            domain = cls._url_domain(url)
            records[identity] = {
                "fingerprint": fingerprint,
                "title": title[:300],
                "url": url[:1200],
                "domain": domain[:200],
            }
            parts = [part for part in (title, excerpt[:600], url) if part]
            display[identity] = " | ".join(parts)[:900]
            if domain:
                features.append(f"source_domain:{domain}")
            if title:
                features.extend(cls._feature_tokens(title))

        if not records:
            compact = " ".join(text.split())[:5000]
            return f"World observation about {topic}: {compact}", ("web",), {}

        lines = [display[key] for key in sorted(records) if display.get(key)]
        summary = f"World observation about {topic}: " + " || ".join(lines)[:5000]
        return summary, tuple(dict.fromkeys(features))[:32], records

    @classmethod
    def _sensor_summary(cls, raw: str, topic: str) -> tuple[str, tuple[str, ...]]:
        summary, features, _state = cls._sensor_snapshot(raw, topic)
        return summary, features

    @staticmethod
    def _diff_sources(
        previous: dict[str, dict[str, str]],
        current: dict[str, dict[str, str]],
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        previous_keys = set(previous)
        current_keys = set(current)
        new_keys = current_keys - previous_keys
        removed_keys = previous_keys - current_keys
        shared = previous_keys & current_keys
        updated_keys = {
            key
            for key in shared
            if str(previous[key].get("fingerprint") or "")
            != str(current[key].get("fingerprint") or "")
        }
        stable_keys = shared - updated_keys
        return (
            tuple(sorted(new_keys)),
            tuple(sorted(updated_keys)),
            tuple(sorted(removed_keys)),
            tuple(sorted(stable_keys)),
        )

    @staticmethod
    def _source_state_hash(state: dict[str, dict[str, str]]) -> str:
        normalized = {
            key: str(value.get("fingerprint") or "")
            for key, value in sorted(state.items())
        }
        return hashlib.sha256(
            json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @classmethod
    def _source_labels(
        cls,
        state: dict[str, dict[str, str]],
        keys: tuple[str, ...],
    ) -> tuple[str, ...]:
        return tuple(cls._source_label(state.get(key) or {}, key) for key in keys)

    @staticmethod
    def _source_label(item: dict[str, str], fallback: str) -> str:
        return str(
            item.get("title")
            or item.get("domain")
            or item.get("url")
            or fallback
        )[:300]

    @classmethod
    def _canonical_url(cls, raw: str) -> str:
        text = str(raw or "").strip()
        if not text:
            return ""
        try:
            parsed = urlsplit(text)
        except ValueError:
            return text[:1200]
        if not parsed.scheme or not parsed.netloc:
            return text[:1200]
        query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in cls._TRACKING_QUERY_KEYS
            and not any(
                key.lower().startswith(prefix)
                for prefix in cls._TRACKING_QUERY_PREFIXES
            )
        ]
        path = parsed.path or "/"
        return urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                path.rstrip("/") or "/",
                urlencode(query, doseq=True),
                "",
            )
        )[:1200]

    @staticmethod
    def _url_domain(url: str) -> str:
        if not url:
            return ""
        try:
            return urlsplit(url).netloc.lower()
        except ValueError:
            return ""

    @staticmethod
    def _normalize_identity(text: str) -> str:
        return " ".join(str(text or "").lower().split())[:1000]

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
        source_state = data.get("last_source_state")
        data["last_source_state"] = (
            {
                str(key): dict(value)
                for key, value in source_state.items()
                if isinstance(value, dict)
            }
            if isinstance(source_state, dict)
            else {}
        )
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
