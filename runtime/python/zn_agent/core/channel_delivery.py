from __future__ import annotations

"""Durable routing ledger between external channel percepts and resident events.

The resident's existing ``events`` / ``event_outcomes`` tables remain the source
of truth for cognition. This ledger stores only communication routing facts:
which external percept produced a resident event, where its outcome should be
sent, whether delivery completed, and the adapter's last safe poll checkpoint.
"""

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .channel import ChannelEvent, ChannelOutboundMedia
from .models import utc_now


_MAX_MEDIA_NOMINATIONS_PER_EVENT = 8
_MAX_MEDIA_METADATA_CHARS = 4_000


@dataclass(slots=True)
class ChannelRoute:
    source_key: str
    event_id: str
    channel: str
    conversation_id: str
    work_thread_id: str | None = None
    thread_id: str | None = None
    reply_to_message_id: str | None = None
    status: str = "pending"
    delivery_attempts: int = 0
    last_error: str | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass(slots=True)
class ChannelMediaNomination:
    """Durable resident-owned intent to attach one local artifact to a route."""

    nomination_id: str
    event_id: str
    local_path: str
    kind: str = "document"
    file_name: str | None = None
    mime_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


class ChannelDeliveryLedger:
    """Small restart-safe routing ledger stored beside the resident state."""

    def __init__(self, store_path: str | Path):
        self.path = Path(store_path).expanduser()
        self._init_schema()

    @staticmethod
    def source_key(event: ChannelEvent) -> str:
        channel = str(event.channel or "").strip().lower()
        update_id = event.metadata.get("update_id")
        if update_id is not None and str(update_id).strip():
            return f"{channel}:update:{str(update_id).strip()}"
        parts = (
            channel,
            str(event.conversation_id or "").strip(),
            str(event.thread_id or "").strip(),
            str(event.message_id or event.event_id or "").strip(),
            str(event.metadata.get("update_type") or "").strip(),
        )
        return ":".join(parts)

    def route_for_source(self, source_key: str) -> ChannelRoute | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT data FROM channel_delivery_routes WHERE source_key=?",
                (str(source_key),),
            ).fetchone()
        return self._from_row(row) if row else None

    def route_for_event(self, event_id: str) -> ChannelRoute | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT data FROM channel_delivery_routes WHERE event_id=?",
                (str(event_id),),
            ).fetchone()
        return self._from_row(row) if row else None

    def remember(
        self,
        event: ChannelEvent,
        event_id: str,
        *,
        work_thread_id: str | None = None,
    ) -> ChannelRoute:
        source_key = self.source_key(event)
        existing = self.route_for_source(source_key)
        if existing is not None:
            return existing
        now = utc_now()
        route = ChannelRoute(
            source_key=source_key,
            event_id=str(event_id),
            channel=str(event.channel or "").strip().lower(),
            conversation_id=str(event.conversation_id or "").strip(),
            work_thread_id=(str(work_thread_id).strip() if work_thread_id else None),
            thread_id=(str(event.thread_id).strip() if event.thread_id is not None else None),
            reply_to_message_id=(
                str(event.message_id).strip() if event.message_id is not None else None
            ),
            status="pending",
            delivery_attempts=0,
            created_at=now,
            updated_at=now,
        )
        with closing(self._connect()) as conn:
            try:
                conn.execute(
                    "INSERT INTO channel_delivery_routes"
                    "(source_key,event_id,channel,status,updated_at,data) VALUES(?,?,?,?,?,?)",
                    (
                        route.source_key,
                        route.event_id,
                        route.channel,
                        route.status,
                        route.updated_at,
                        self._dump(route),
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                conn.rollback()
                existing = self.route_for_source(source_key)
                if existing is not None:
                    return existing
                raise
        return route

    def pending(self, channel: str, *, limit: int = 200) -> tuple[ChannelRoute, ...]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT data FROM channel_delivery_routes "
                "WHERE channel=? AND status='pending' "
                "ORDER BY updated_at ASC LIMIT ?",
                (str(channel or "").strip().lower(), max(1, int(limit))),
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def mark_delivered(self, event_id: str) -> None:
        route = self.route_for_event(event_id)
        if route is None:
            return
        route.status = "delivered"
        route.last_error = None
        route.updated_at = utc_now()
        self._save(route)

    def mark_delivery_failure(self, event_id: str, error: object) -> None:
        route = self.route_for_event(event_id)
        if route is None:
            return
        route.status = "pending"
        route.delivery_attempts += 1
        route.last_error = f"{type(error).__name__}: {error}"[:1000]
        route.updated_at = utc_now()
        self._save(route)

    def nominate_media(
        self,
        event_id: str,
        local_path: str | Path,
        *,
        kind: str = "document",
        file_name: str | None = None,
        mime_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChannelMediaNomination:
        """Persist an explicit media nomination for one pending channel route.

        This method deliberately does not parse resident response text and does
        not authorize the path. The platform adapter performs authorization at
        the last possible boundary immediately before opening the file.
        """

        route = self.route_for_event(str(event_id or "").strip())
        if route is None:
            raise ValueError("outbound media nomination requires a channel route")
        if route.status != "pending":
            raise ValueError("outbound media nomination requires a pending channel route")
        path = str(local_path or "").strip()
        if not path:
            raise ValueError("outbound media nomination requires local_path")
        if len(path) > 4_096:
            raise ValueError("outbound media nomination local_path is too long")
        normalized_kind = (str(kind or "document").strip().lower() or "document")[:32]
        normalized_metadata = dict(metadata or {})
        try:
            metadata_json = json.dumps(
                normalized_metadata,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("outbound media nomination metadata must be JSON-safe") from exc
        if len(metadata_json) > _MAX_MEDIA_METADATA_CHARS:
            raise ValueError("outbound media nomination metadata is too large")
        identity = hashlib.sha256(
            f"{route.event_id}\x00{path}\x00{normalized_kind}".encode(
                "utf-8", errors="replace"
            )
        ).hexdigest()[:20]
        nomination = ChannelMediaNomination(
            nomination_id=f"media-{identity}",
            event_id=route.event_id,
            local_path=path,
            kind=normalized_kind,
            file_name=(
                str(file_name).strip()[:255] if file_name is not None else None
            ),
            mime_type=(
                str(mime_type).strip()[:255] if mime_type is not None else None
            ),
            metadata=normalized_metadata,
            created_at=utc_now(),
        )
        with closing(self._connect()) as conn:
            existing = conn.execute(
                "SELECT 1 FROM channel_media_nominations WHERE nomination_id=?",
                (nomination.nomination_id,),
            ).fetchone()
            count = conn.execute(
                "SELECT COUNT(*) AS count FROM channel_media_nominations WHERE event_id=?",
                (nomination.event_id,),
            ).fetchone()
            if existing is None and int(count["count"] if count else 0) >= _MAX_MEDIA_NOMINATIONS_PER_EVENT:
                raise ValueError("outbound media nomination limit reached for event")
            conn.execute(
                "INSERT OR REPLACE INTO channel_media_nominations"
                "(nomination_id,event_id,created_at,data) VALUES(?,?,?,?)",
                (
                    nomination.nomination_id,
                    nomination.event_id,
                    nomination.created_at,
                    json.dumps(
                        asdict(nomination),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                ),
            )
            conn.commit()
        return nomination

    def media_for_event(self, event_id: str) -> tuple[ChannelOutboundMedia, ...]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT data FROM channel_media_nominations "
                "WHERE event_id=? ORDER BY created_at ASC, nomination_id ASC LIMIT ?",
                (
                    str(event_id or "").strip(),
                    _MAX_MEDIA_NOMINATIONS_PER_EVENT,
                ),
            ).fetchall()
        media: list[ChannelOutboundMedia] = []
        for row in rows:
            raw = json.loads(row["data"])
            media.append(
                ChannelOutboundMedia(
                    nomination_id=str(raw["nomination_id"]),
                    local_path=str(raw["local_path"]),
                    kind=str(raw.get("kind") or "document"),
                    file_name=(
                        str(raw["file_name"])
                        if raw.get("file_name") is not None
                        else None
                    ),
                    mime_type=(
                        str(raw["mime_type"]) if raw.get("mime_type") is not None else None
                    ),
                    metadata=dict(raw.get("metadata") or {}),
                )
            )
        return tuple(media)

    def load_checkpoint(self, channel: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT data FROM channel_poll_checkpoints WHERE channel=?",
                (str(channel or "").strip().lower(),),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["data"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def save_checkpoint(self, channel: str, checkpoint: dict[str, Any]) -> None:
        name = str(channel or "").strip().lower()
        if not name:
            raise ValueError("channel checkpoint requires channel name")
        payload = dict(checkpoint or {})
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO channel_poll_checkpoints(channel,updated_at,data) "
                "VALUES(?,?,?)",
                (
                    name,
                    utc_now(),
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            conn.commit()

    def counts(self, channel: str) -> dict[str, int]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT status,COUNT(*) AS count FROM channel_delivery_routes "
                "WHERE channel=? GROUP BY status",
                (str(channel or "").strip().lower(),),
            ).fetchall()
        result = {"pending": 0, "delivered": 0}
        for row in rows:
            result[str(row["status"])] = int(row["count"])
        return result

    def _save(self, route: ChannelRoute) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE channel_delivery_routes SET status=?,updated_at=?,data=? "
                "WHERE source_key=?",
                (
                    route.status,
                    route.updated_at,
                    self._dump(route),
                    route.source_key,
                ),
            )
            conn.commit()

    @staticmethod
    def _dump(route: ChannelRoute) -> str:
        return json.dumps(asdict(route), ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ChannelRoute:
        return ChannelRoute(**json.loads(row["data"]))

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS channel_delivery_routes(
                    source_key TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    channel TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_channel_delivery_pending
                    ON channel_delivery_routes(channel,status,updated_at);
                CREATE TABLE IF NOT EXISTS channel_poll_checkpoints(
                    channel TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS channel_media_nominations(
                    nomination_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_channel_media_event
                    ON channel_media_nominations(event_id,created_at);
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn
