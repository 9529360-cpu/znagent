from __future__ import annotations

"""Skill usage stats: lightweight body-load accounting for file-based skills.

T2 (skill reference feedback loop): the "save skill" upstream is fully
wired (matching, gap proposals, re-verification), but nobody measures
whether a saved skill is ever actually *used*. ``skill_ledger.py`` only
scores selection. This module closes the last leg: at the two points
where a skill body actually flows into use, record ``usage_count`` and
``last_used``, and expose a read-only query surface for zero-hit /
long-dormant skills.

Recording points (both in ``skills.py``):

- ``SkillStore.activate_skill``: explicit on-demand activation (the CUR-1
  two-stage activation stage). One record per successful activation.
- ``SkillStore.bind_cognition_context(..., include_bodies=True)``: the
  legacy full-body injection. One record per skill whose body actually
  ends up in the bound context (truncated-away bodies do not count).

Resident-summary matches do NOT count: the resident layer never carries
bodies (CUR-1), so a summary match is not a body use. Matching for gap
detection (``detect_skill_gap``) is not a use either.

Persistence reuses the lockfile store shape (``skill_lock.py``): a small
versioned JSON sidecar ``skills.usage.json`` in the skills root, sorted
keys for reviewable diffs, atomic replace on write. It is DATA, not
authority: a malformed usage file is tolerated (stats restart from
empty) instead of failing the cognition path -- observability must
never break the main flow, and recording is wrapped in
``contextlib.suppress(OSError)`` at the call site for the same reason.

No auto-delete: the query surface is read-only; pruning a dormant
skill still needs human confirmation.
"""

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import utc_now

USAGE_FILE_NAME = "skills.usage.json"
USAGE_FILE_VERSION = 1


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


@dataclass(slots=True)
class SkillUsage:
    """Usage stats for one skill name: body-load count + last load time."""

    name: str
    usage_count: int = 0
    #: ISO timestamp from ``models.utc_now()``; "" means never loaded.
    last_used: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "usage_count": max(0, int(self.usage_count)),
            "last_used": self.last_used,
        }

    @classmethod
    def from_dict(cls, name: str, data: Any) -> "SkillUsage":
        raw = data if isinstance(data, dict) else {}
        count = raw.get("usage_count")
        try:
            count = int(count)
        except (TypeError, ValueError):
            count = 0
        last_used = raw.get("last_used")
        return cls(
            name=name,
            usage_count=max(0, count),
            last_used=str(last_used) if isinstance(last_used, str) else "",
        )

    @property
    def never_used(self) -> bool:
        """True when the body was never loaded (the zero-hit case)."""
        return self.usage_count <= 0


def _parse_used_at(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class SkillUsageStore:
    """Read / write the per-skill usage sidecar in a skills root."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.path = self.root / USAGE_FILE_NAME
        self.entries: dict[str, SkillUsage] = {}
        self._load()

    # -- persistence ------------------------------------------------------

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            # Observability data, not authority: tolerate a corrupt file and
            # restart stats from empty instead of failing the cognition path.
            return
        if not isinstance(raw, dict):
            return
        if raw.get("version") not in (None, USAGE_FILE_VERSION):
            # Unknown version: leave the file untouched on disk; the next
            # record overwrites it with the current version.
            return
        skills = raw.get("skills")
        if not isinstance(skills, dict):
            return
        for name, data in skills.items():
            clean_name = str(name)
            self.entries[clean_name] = SkillUsage.from_dict(clean_name, data)

    def save(self) -> Path:
        """Persist the usage file atomically. Sorted keys keep diffs reviewable."""
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": USAGE_FILE_VERSION,
            "skills": {
                name: self.entries[name].to_dict() for name in sorted(self.entries)
            },
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.root), prefix=USAGE_FILE_NAME + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.replace(tmp_name, self.path)
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise
        return self.path

    # -- recording --------------------------------------------------------

    def record_use(self, name: str, *, used_at: str | None = None) -> SkillUsage:
        """Record one body load of ``name``: count + 1, stamp last_used, save."""
        clean_name = _clean(name)
        if not clean_name:
            raise ValueError("skill usage requires a non-empty skill name")
        entry = self.entries.get(clean_name)
        if entry is None:
            entry = SkillUsage(name=clean_name)
            self.entries[clean_name] = entry
        entry.usage_count += 1
        entry.last_used = (
            used_at if isinstance(used_at, str) and used_at else utc_now()
        )
        self.save()
        return entry

    def record_uses(self, names: Iterable[str]) -> None:
        """Batch record: one disk write for a whole bind, not one per skill."""
        stamped: list[SkillUsage] = []
        for name in names:
            clean_name = _clean(name)
            if not clean_name:
                continue
            entry = self.entries.get(clean_name)
            if entry is None:
                entry = SkillUsage(name=clean_name)
                self.entries[clean_name] = entry
            entry.usage_count += 1
            stamped.append(entry)
        if not stamped:
            return
        for entry in stamped:
            entry.last_used = utc_now()
        self.save()

    # -- queries ------------------------------------------------------------

    def stats_for(self, name: str) -> SkillUsage | None:
        return self.entries.get(_clean(name))

    def all_stats(self) -> list[SkillUsage]:
        """Every recorded name, sorted by name."""
        return [self.entries[name] for name in sorted(self.entries)]

    def dormant_since(self, name: str, *, dormant_days: int) -> bool:
        """True when ``name`` never loaded, or last load is older than the threshold.

        Read-only: pure predicate over the loaded entries.
        """
        entry = self.stats_for(name)
        if entry is None or entry.never_used:
            return True
        days = max(1, int(dormant_days))
        parsed = _parse_used_at(entry.last_used)
        if parsed is None:
            return True
        now = datetime.now(timezone.utc)
        return (now - parsed).total_seconds() > days * 86400


__all__ = [
    "USAGE_FILE_NAME",
    "USAGE_FILE_VERSION",
    "SkillUsage",
    "SkillUsageStore",
]
