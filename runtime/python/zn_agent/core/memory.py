from __future__ import annotations

import json
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

    def relevant_context(
        self,
        query: str,
        *,
        max_facts: int = 5,
        max_json_chars: int = 6_000,
        max_fact_chars: int = 1_500,
    ) -> list[dict[str, Any]]:
        """Return explicitly saved facts whose key or alias occurs in a task.

        This is a conservative cue lookup, not semantic search: values are never
        searched for matches, and a fact is included only when its saved key or
        alias appears in the current query. The result is suitable for bounded
        cognition context after the caller has checked the Work memory policy.
        """
        normalized_query = self._normalize(query)
        if not normalized_query:
            return []
        max_facts = max(0, min(10, int(max_facts)))
        max_json_chars = max(0, min(12_000, int(max_json_chars)))
        max_fact_chars = max(1, min(3_000, int(max_fact_chars)))
        if not max_facts or not max_json_chars:
            return []

        matches: list[tuple[int, str, dict[str, Any]]] = []
        for record in self.store.list_facts():
            cues = (record["key"], *record["aliases"])
            matched_by = next(
                (
                    cue
                    for cue in cues
                    if (normalized_cue := self._normalize(cue))
                    and self._cue_occurs(normalized_query, normalized_cue)
                ),
                None,
            )
            if matched_by is None:
                continue
            fact = {"key": record["key"], "value": record["value"]}
            encoded = json.dumps(fact, ensure_ascii=False, separators=(",", ":"))
            if len(encoded) > max_fact_chars:
                continue
            matches.append((len(self._normalize(matched_by)), record["key"], fact))

        # Prefer the most specific saved cues; key is a stable tie breaker.
        matches.sort(key=lambda item: (-item[0], item[1]))
        selected: list[dict[str, Any]] = []
        used_chars = 2  # JSON list brackets and separators.
        for _, _, fact in matches:
            encoded = json.dumps(fact, ensure_ascii=False, separators=(",", ":"))
            extra = len(encoded) + (1 if selected else 0)
            if used_chars + extra > max_json_chars:
                continue
            selected.append(fact)
            used_chars += extra
            if len(selected) >= max_facts:
                break
        return selected

    @staticmethod
    def _cue_occurs(query: str, cue: str) -> bool:
        # Latin cues use word boundaries; Chinese cues are matched as phrases
        # because users commonly type them without whitespace segmentation.
        if re.search(r"[\u4e00-\u9fff]", cue):
            return cue in query
        if re.search(r"[a-z0-9]", cue):
            if " " not in cue:
                return query == cue or len(cue) >= 12 and re.search(
                    rf"(?<![\w]){re.escape(cue)}(?![\w])", query
                ) is not None
            return re.search(rf"(?<![\w]){re.escape(cue)}(?![\w])", query) is not None
        return cue in query

    @staticmethod
    def _normalize(value: str) -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"[\s\-_:/\\]+", " ", text)
        text = re.sub(r"[^\w\u4e00-\u9fff ]+", "", text)
        return " ".join(text.split())

