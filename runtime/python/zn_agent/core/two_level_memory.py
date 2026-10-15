"""KWP-2: two-level memory lifecycle (hot cache + deep store).

Hot cache / deep store are *tiers*, not separate stores. The facts table
remains the sole owner of every fact (CM-1 / GR-1 / GR-2 / M0-1
unchanged): demotion never deletes a fact, it only moves the fact's tier
label from ``hot`` to ``deep``. A demoted fact is still recallable through
the normal :meth:`StructuredMemory.recall` path and through this module's
decode table; it just no longer counts toward the hot cache.

Rules (explicit, executable -- this module is the authority):

- New facts start HOT. Hot capacity is ~100 facts
  (:data:`HOT_CAPACITY`); ``remember`` enforces it immediately.
- Demotion (hot -> deep): when the hot set exceeds capacity, demote the
  coldest hot facts first -- fewest hits, then oldest last hit, then key
  order -- until the hot set fits. Trigger: ``remember`` (automatic) or
  an explicit :meth:`TwoLevelMemory.demote` / :meth:`TwoLevelMemory.rebalance`.
- Promotion (deep -> hot): a deep fact recalled ``promote_after_hits``
  times (default 3, cumulative) is promoted back to hot. Trigger: recall
  through this adapter (:meth:`TwoLevelMemory.recall`,
  :meth:`TwoLevelMemory.recall_deep`, :meth:`TwoLevelMemory.relevant_context`)
  or an explicit :meth:`TwoLevelMemory.promote`. Promotion evicts the
  coldest hot fact when the cache is full (never the just-promoted one).
- Recall after demotion: demoted facts stay in the facts table, so exact
  recall keeps working; the decode table
  (:meth:`TwoLevelMemory.decode_table`) is the index/summary view of the
  deep store -- key, aliases, a ~200-char value summary, updated/demoted
  timestamps -- used to find a deep fact without loading every value.
- Tier metadata lives in one additive sidecar table (``memory_tiers``);
  the facts table's schema and rows are untouched. Facts written before
  KWP-2 have no tier row and count as hot with zero hits (unknown = cold,
  demoted first) until touched.

Nicknames / codenames are ordinary facts, not a second memory system:
``capture_nickname`` stores ``nickname:<name>`` -> ``{"canonical": ...}``
in the facts table, so recall, supersession, consolidation and disband
sweeps keep working on them. :func:`resolve_reference` rewrites known
nicknames in a query to their canonical form before lookup, so a later
``"阿豪说……"`` resolves to the same entity as ``"用户说……"``.

Source: mechanism adapted from anthropics/knowledge-work-plugins
(Apache 2.0); implementation is ZN-owned, fitted to the existing
``StructuredMemory`` API.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .memory import FactMatch, StructuredMemory

#: Target size of the hot cache, in facts (~100 lines of memory).
HOT_CAPACITY = 100

#: Cumulative recalls of a deep fact that trigger automatic promotion.
PROMOTE_AFTER_HITS = 3

#: Tier labels.
TIER_HOT = "hot"
TIER_DEEP = "deep"

#: Facts-table key prefix for nickname/codename mappings.
NICKNAME_PREFIX = "nickname:"

#: Max chars kept in a decode-table summary.
_SUMMARY_CHARS = 200


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _summarize(value: Any) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            text = str(value)
    return " ".join(text.split())[:_SUMMARY_CHARS]


class TwoLevelMemory:
    """Lifecycle adapter over :class:`StructuredMemory`.

    Wraps one ``StructuredMemory``; all fact reads/writes still go through
    it, so supersession, consolidation, response preferences and
    ``bind_cognition_context`` behave exactly as before. This class only
    adds tier labels, capacity enforcement, promotion/demotion, and the
    deep-store decode table.
    """

    def __init__(
        self,
        memory: StructuredMemory,
        *,
        hot_capacity: int = HOT_CAPACITY,
        promote_after_hits: int = PROMOTE_AFTER_HITS,
    ):
        if hot_capacity < 1:
            raise ValueError("hot_capacity must be >= 1")
        if promote_after_hits < 1:
            raise ValueError("promote_after_hits must be >= 1")
        self._memory = memory
        self.hot_capacity = hot_capacity
        self.promote_after_hits = promote_after_hits
        self._ensure_schema()

    # -- schema ---------------------------------------------------------

    def _ensure_schema(self) -> None:
        with self._memory.store._lock:
            self._memory.store._conn.execute(
                "CREATE TABLE IF NOT EXISTS memory_tiers("
                "fact_key TEXT PRIMARY KEY, "
                "tier TEXT NOT NULL, "
                "hits INTEGER NOT NULL DEFAULT 0, "
                "last_hit_at TEXT, "
                "demoted_at TEXT, "
                "summary TEXT NOT NULL DEFAULT '')"
            )
            self._memory.store._conn.commit()

    # -- writes ---------------------------------------------------------

    def remember(self, key: str, value: Any, *, aliases: tuple[str, ...] = ()) -> str:
        """Save a fact; it starts (or stays) hot. Returns the stored key.

        ``StructuredMemory.remember`` may supersede into an existing key;
        the returned key is the key the fact actually landed under.
        """
        self._memory.remember(key, value, aliases=aliases)
        stored = self._resolve_stored_key(str(key or "").strip(), aliases)
        with self._memory.store._lock:
            self._memory.store._conn.execute(
                "INSERT INTO memory_tiers(fact_key, tier, hits, last_hit_at, demoted_at, summary)"
                " VALUES(?, ?, 0, NULL, NULL, ?)"
                " ON CONFLICT(fact_key) DO UPDATE SET summary=excluded.summary",
                (stored, TIER_HOT, _summarize(value)),
            )
            self._memory.store._conn.commit()
        self.enforce_capacity()
        return stored

    def forget(self, key: str) -> None:
        self._memory.forget(key)
        with self._memory.store._lock:
            self._memory.store._conn.execute(
                "DELETE FROM memory_tiers WHERE fact_key=?", (str(key or "").strip(),)
            )
            self._memory.store._conn.commit()

    # -- reads ----------------------------------------------------------

    def recall(self, query: str) -> FactMatch | None:
        """Exact recall (hot or deep); a hit counts toward promotion."""
        match = self._memory.recall(query)
        if match is not None:
            self._record_hit(match.key)
        return match

    def recall_deep(self, key: str) -> Any | None:
        """Recall one demoted fact by exact key. Returns its value or None.

        This is the explicit "recall after demotion" path: it finds the
        fact through the decode table's key, counts as a hit, and
        auto-promotes when the fact reaches the promotion threshold.
        """
        clean = str(key or "").strip()
        if not clean or self.tier_of(clean) != TIER_DEEP:
            return None
        found = next(
            (f for f in self._memory.store.list_facts() if f["key"] == clean),
            None,
        )
        if found is None:
            return None
        self._record_hit(clean)
        return found["value"]

    def relevant_context(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        """Delegate to ``StructuredMemory``; returned facts count as hits."""
        items = self._memory.relevant_context(query, **kwargs)
        for item in items:
            key = str(item.get("key", ""))
            if key:
                self._record_hit(key)
        return items

    # -- tiers ----------------------------------------------------------

    def tier_of(self, key: str) -> str | None:
        """``"hot"`` / ``"deep"`` for a stored fact, else None."""
        clean = str(key or "").strip()
        if not clean:
            return None
        if not any(f["key"] == clean for f in self._memory.store.list_facts()):
            return None
        with self._memory.store._lock:
            row = self._memory.store._conn.execute(
                "SELECT tier FROM memory_tiers WHERE fact_key=?", (clean,)
            ).fetchone()
        return str(row[0]) if row is not None else TIER_HOT

    def hot_keys(self) -> list[str]:
        """Keys in the hot set (facts with no tier row count as hot)."""
        deep = self._deep_keys()
        return sorted(
            f["key"] for f in self._memory.store.list_facts() if f["key"] not in deep
        )

    def deep_keys(self) -> list[str]:
        return sorted(self._deep_keys())

    def decode_table(self) -> list[dict[str, Any]]:
        """Index/summary view of the deep store (the decode table).

        One row per demoted fact: key, aliases, value summary, updated
        and demoted timestamps. Summaries come from the sidecar table;
        aliases and updated_at come from the facts table, so aliases and
        timestamps never go stale on edits that bypass this adapter.
        Summaries refresh on adapter ``remember`` / ``demote``.
        """
        facts = {f["key"]: f for f in self._memory.store.list_facts()}
        rows: list[dict[str, Any]] = []
        with self._memory.store._lock:
            cursor = self._memory.store._conn.execute(
                "SELECT fact_key, demoted_at, summary FROM memory_tiers WHERE tier=?",
                (TIER_DEEP,),
            )
            tier_rows = cursor.fetchall()
        for fact_key, demoted_at, summary in sorted(tier_rows):
            fact = facts.get(str(fact_key))
            if fact is None:
                continue
            rows.append(
                {
                    "key": str(fact_key),
                    "aliases": list(fact["aliases"]),
                    "summary": str(summary or ""),
                    "updated_at": fact["updated_at"],
                    "demoted_at": demoted_at,
                }
            )
        return rows

    def stats(self) -> dict[str, int]:
        hot = len(self.hot_keys())
        deep = len(self.deep_keys())
        return {
            "hot": hot,
            "deep": deep,
            "total": hot + deep,
            "hot_capacity": self.hot_capacity,
        }

    # -- promotion / demotion -------------------------------------------

    def promote(self, key: str) -> bool:
        """Move one fact to hot. Returns False when the fact is missing."""
        clean = str(key or "").strip()
        if self.tier_of(clean) is None:
            return False
        with self._memory.store._lock:
            self._memory.store._conn.execute(
                "INSERT INTO memory_tiers(fact_key, tier, hits, last_hit_at, demoted_at, summary)"
                " VALUES(?, ?, 0, NULL, NULL, '')"
                " ON CONFLICT(fact_key) DO UPDATE SET tier=?, demoted_at=NULL",
                (clean, TIER_HOT, TIER_HOT),
            )
            self._memory.store._conn.commit()
        self.enforce_capacity(keep=clean)
        return True

    def demote(self, key: str) -> bool:
        """Move one fact to deep (never deletes). False when missing."""
        clean = str(key or "").strip()
        if self.tier_of(clean) is None:
            return False
        fact = next(
            (f for f in self._memory.store.list_facts() if f["key"] == clean),
            None,
        )
        with self._memory.store._lock:
            self._memory.store._conn.execute(
                "INSERT INTO memory_tiers(fact_key, tier, hits, last_hit_at, demoted_at, summary)"
                " VALUES(?, ?, 0, NULL, ?, ?)"
                " ON CONFLICT(fact_key) DO UPDATE SET tier=?, demoted_at=excluded.demoted_at,"
                " summary=excluded.summary",
                (
                    clean,
                    TIER_DEEP,
                    _now(),
                    _summarize(fact["value"]) if fact is not None else "",
                    TIER_DEEP,
                ),
            )
            self._memory.store._conn.commit()
        return True

    def enforce_capacity(self, *, keep: str | None = None) -> list[str]:
        """Demote coldest hot facts until the hot set fits. Returns demoted keys."""
        demoted: list[str] = []
        while len(self.hot_keys()) > self.hot_capacity:
            victim = self._coldest_hot_key(except_key=keep)
            if victim is None:
                break
            self.demote(victim)
            demoted.append(victim)
        return demoted

    def rebalance(self) -> list[str]:
        """Explicit capacity pass (same rule as automatic enforcement)."""
        return self.enforce_capacity()

    # -- internals ------------------------------------------------------

    def _deep_keys(self) -> set[str]:
        with self._memory.store._lock:
            cursor = self._memory.store._conn.execute(
                "SELECT fact_key FROM memory_tiers WHERE tier=?", (TIER_DEEP,)
            )
            return {str(row[0]) for row in cursor.fetchall()}

    def _coldest_hot_key(self, *, except_key: str | None) -> str | None:
        hot = [k for k in self.hot_keys() if k != except_key]
        if not hot:
            return None
        with self._memory.store._lock:
            cursor = self._memory.store._conn.execute(
                "SELECT fact_key, hits, last_hit_at FROM memory_tiers"
            )
            meta = {
                str(row[0]): (int(row[1]), str(row[2] or ""))
                for row in cursor.fetchall()
            }
        # Fewest hits, then oldest last hit (never-hit sorts first), then key.
        return min(hot, key=lambda k: (meta.get(k, (0, ""))[0], meta.get(k, (0, ""))[1], k))

    def _record_hit(self, key: str) -> None:
        with self._memory.store._lock:
            cursor = self._memory.store._conn.execute(
                "SELECT hits FROM memory_tiers WHERE fact_key=?", (key,)
            )
            row = cursor.fetchone()
            if row is None:
                self._memory.store._conn.execute(
                    "INSERT INTO memory_tiers(fact_key, tier, hits, last_hit_at, demoted_at, summary)"
                    " VALUES(?, ?, 1, ?, NULL, '')",
                    (key, TIER_HOT, _now()),
                )
                self._memory.store._conn.commit()
                return
            hits = int(row[0]) + 1
            self._memory.store._conn.execute(
                "UPDATE memory_tiers SET hits=?, last_hit_at=? WHERE fact_key=?",
                (hits, _now(), key),
            )
            self._memory.store._conn.commit()
        if self.tier_of(key) == TIER_DEEP and hits >= self.promote_after_hits:
            self.promote(key)

    def _resolve_stored_key(self, key: str, aliases: tuple[str, ...]) -> str:
        """Key the fact landed under (supersession may redirect it)."""
        from .memory import StructuredMemory as _SM

        facts = self._memory.store.list_facts()
        for fact in facts:
            if fact["key"] == key:
                return str(fact["key"])
        wanted = {_SM._normalize(key)}
        wanted.update(_SM._normalize(a) for a in aliases)
        wanted.discard("")
        for fact in facts:
            have = {_SM._normalize(fact["key"])}
            have.update(_SM._normalize(a) for a in fact["aliases"])
            if wanted & have:
                return str(fact["key"])
        return key


# -- nicknames / codenames ----------------------------------------------


def capture_nickname(
    memory: StructuredMemory,
    nickname: str,
    canonical: str,
    *,
    source: str = "",
) -> bool:
    """Record that ``nickname`` refers to ``canonical``. Returns False on bad input.

    Stored as an ordinary fact (``nickname:<name>``), so it survives the
    same recall / consolidation / disband paths as any other fact.
    Re-capturing the same nickname updates its canonical target.
    The write bypasses ``StructuredMemory.remember``'s supersession on
    purpose: nickname keys are identity keys, and supersession would
    merge distinct near-identical nicknames (``阿豪`` vs ``阿豪哥``)
    into one mapping, losing one of them. No aliases are stored, so
    consolidation cannot merge nickname rows either.
    Operates on the underlying ``StructuredMemory`` (nicknames are global,
    not per-specialist; team-scoped adapters reject ``:`` in keys).
    """
    name = str(nickname or "").strip()
    target = str(canonical or "").strip()
    if not name or not target:
        return False
    memory.store.put_fact(
        f"{NICKNAME_PREFIX}{name}",
        {"canonical": target, "source": str(source or "")},
    )
    return True


def resolve_nickname(memory: StructuredMemory, nickname: str) -> str | None:
    """Canonical name for ``nickname``, or None when unknown."""
    name = str(nickname or "").strip()
    if not name:
        return None
    match = memory.recall(f"{NICKNAME_PREFIX}{name}")
    if match is None or not isinstance(match.value, dict):
        return None
    target = match.value.get("canonical")
    return str(target).strip() or None


def list_nicknames(memory: StructuredMemory) -> dict[str, str]:
    """All captured ``{nickname: canonical}`` mappings, sorted by nickname."""
    out: dict[str, str] = {}
    for fact in memory.store.list_facts():
        key = str(fact["key"])
        if not key.startswith(NICKNAME_PREFIX):
            continue
        value = fact["value"]
        if isinstance(value, dict) and str(value.get("canonical") or "").strip():
            out[key[len(NICKNAME_PREFIX):]] = str(value["canonical"]).strip()
    return dict(sorted(out.items()))


def forget_nickname(memory: StructuredMemory, nickname: str) -> bool:
    """Delete one nickname mapping. Returns False when it did not exist."""
    name = str(nickname or "").strip()
    if not name or resolve_nickname(memory, name) is None:
        return False
    memory.forget(f"{NICKNAME_PREFIX}{name}")
    return True


def resolve_reference(memory: StructuredMemory, text: str) -> str:
    """Rewrite known nicknames in ``text`` to their canonical names.

    Longest nickname first so ``"阿豪哥"`` wins over ``"阿豪"`` when both
    are captured. Plain substring replacement: nicknames are matched as
    written, in Chinese or Latin text alike.
    """
    result = str(text or "")
    if not result:
        return result
    for nickname, canonical in sorted(
        list_nicknames(memory).items(), key=lambda item: (-len(item[0]), item[0])
    ):
        if nickname in result:
            result = result.replace(nickname, canonical)
    return result


__all__ = [
    "HOT_CAPACITY",
    "NICKNAME_PREFIX",
    "PROMOTE_AFTER_HITS",
    "TIER_DEEP",
    "TIER_HOT",
    "TwoLevelMemory",
    "capture_nickname",
    "forget_nickname",
    "list_nicknames",
    "resolve_nickname",
    "resolve_reference",
]
