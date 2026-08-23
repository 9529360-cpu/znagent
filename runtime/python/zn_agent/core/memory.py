from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .store import KernelStore


@dataclass(slots=True)
class FactMatch:
    key: str
    value: Any
    matched_by: str


class StructuredMemory:
    """Token-free durable facts.

    This is not a transcript store. Facts are structured records that can be
    queried directly by the resident runtime without injecting them into an LLM
    context. Aliases let UI/skills register stable natural-language lookups.
    """

    def __init__(self, store: KernelStore):
        self.store = store

    def remember(self, key: str, value: Any, *, aliases: tuple[str, ...] = ()) -> None:
        self.store.put_fact(key, value, aliases=aliases)

    def forget(self, key: str) -> None:
        self.store.delete_fact(key)

    def recall(self, query: str) -> FactMatch | None:
        normalized = self._normalize(query)
        if not normalized:
            return None
        for record in self.store.list_facts():
            key_norm = self._normalize(record["key"])
            if normalized == key_norm:
                return FactMatch(record["key"], record["value"], "key")
            for alias in record["aliases"]:
                alias_norm = self._normalize(alias)
                if not alias_norm:
                    continue
                if normalized == alias_norm:
                    return FactMatch(record["key"], record["value"], alias)
        return None

    @staticmethod
    def _normalize(value: str) -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"[\s\-_:/\\]+", " ", text)
        text = re.sub(r"[^\w\u4e00-\u9fff ]+", "", text)
        return " ".join(text.split())
