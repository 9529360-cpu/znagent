from __future__ import annotations

"""Durable routing ledger between external channel percepts and resident events.

The resident's existing ``events`` / ``event_outcomes`` tables remain the source
of truth for cognition. This ledger stores only communication routing facts:
which external percept produced a resident event, where its outcome should be
sent, and whether that delivery has completed.
"""

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .channel import ChannelEvent
from .models import utc_now


@dataclass(slots=True)
class ChannelRoute:
    source_key: str
    event_id: str
    channel: str
    conversation_id: str
    thread_id: str | None = None
    reply_to_message_id: str | None = None
    status: str = "pending"
    delivery_attempts: int = 0
    last_error: str | None = None
    created_at: str = ""
    updated_at: str = ""


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

    def remember(self, event: ChannelEvent, event_id: str) -> ChannelRoute:
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
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn
