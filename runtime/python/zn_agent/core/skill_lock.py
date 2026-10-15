from __future__ import annotations

"""Skill version locking: lockfile + pin + external-plugin SHA pins.

ZN skills used to have no version concept: a bundle under
``$ZN_HOME/skills/<name>/`` could be overwritten silently, and there was
no record of which version was installed. This module adds the lockfile
mechanism (adapted from the lockfile + pin idea, implemented in ZN-owned
code -- no upstream code copied):

``skills.lock.json`` (in the skills root) records one entry per skill::

    {"version": 1, "skills": {"<name>": {
        "version": "1.2.0",          # frontmatter version for local bundles
        "sha": "abc...",             # full 40-hex git SHA for external plugins
        "content_sha256": "…",       # hash of the installed skill.md text
        "pinned": true,              # pin: refuse any overwriting change
        "kind": "local" | "external",
        "source": "git+https://…",   # external plugins only
        "updated_at": "…",
    }}}

Rules:

- A pinned skill refuses any overwrite whose content differs from the
  locked content (``SkillLockedError``); the file is left untouched.
  Re-writing byte-identical content is allowed (idempotent, not a change).
  Unpinning is an explicit act (``unpin``), never implied by a write.
- An unpinned skill may be updated normally; the lockfile entry is
  refreshed to the new version / content hash.
- External plugins are pinned to a full 40-hex git SHA. The nightly
  check (``check_plugin_updates``) asks a caller-supplied fetcher for
  each plugin's latest SHA; one plugin's fetch failure is recorded as
  ``failed`` and never blocks the remaining plugins (failure isolation).
  ``plan_upgrades`` turns the check into one upgrade plan per
  update-available plugin, so each upgrade lands in its own PR.

The lockfile is DATA, not authority: it never grants permission or
proves completion. A malformed lockfile fails closed (``ValueError``)
instead of silently behaving as unlocked.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

LOCKFILE_NAME = "skills.lock.json"
LOCKFILE_VERSION = 1

#: A pinned skill may only be overwritten by an explicit unpin first.
PINNED = True

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class SkillLockedError(ValueError):
    """A pinned skill refused an overwriting change."""


def content_sha256(text: str) -> str:
    """Content hash used to tell a real change from an identical rewrite."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


@dataclass(slots=True)
class LockEntry:
    """One lockfile entry: skill name -> version / SHA / pin state."""

    name: str
    version: str = ""
    sha: str = ""
    content_sha256: str = ""
    pinned: bool = False
    kind: str = "local"  # "local" (file bundle) or "external" (git plugin)
    source: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "sha": self.sha,
            "content_sha256": self.content_sha256,
            "pinned": bool(self.pinned),
            "kind": self.kind,
            "source": self.source,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> "LockEntry":
        raw = dict(data or {})
        return cls(
            name=name,
            version=_clean(raw.get("version")),
            sha=_clean(raw.get("sha")),
            content_sha256=_clean(raw.get("content_sha256")),
            pinned=bool(raw.get("pinned")),
            kind=_clean(raw.get("kind") or "local"),
            source=_clean(raw.get("source")),
            updated_at=_clean(raw.get("updated_at")),
        )


@dataclass(slots=True)
class PluginUpdateCheck:
    """One plugin's nightly-check outcome. ``failed`` never blocks others."""

    name: str
    source: str
    locked_sha: str
    latest_sha: str = ""
    status: str = "up-to-date"  # up-to-date | update-available | failed
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "locked_sha": self.locked_sha,
            "latest_sha": self.latest_sha,
            "status": self.status,
            "error": self.error,
        }


@dataclass(slots=True)
class PluginUpgradePlan:
    """One upgrade = one PR. A failed check never produces a plan."""

    name: str
    source: str
    from_sha: str
    to_sha: str
    branch: str = ""
    title: str = ""

    def __post_init__(self) -> None:
        if not self.branch:
            self.branch = f"work/skill-plugin-bump-{self.name}-{self.to_sha[:7]}"
        if not self.title:
            self.title = f"Skill plugin: bump {self.name} to {self.to_sha[:7]}"


class SkillLock:
    """Read / write / enforce the skills lockfile in a skills root."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.path = self.root / LOCKFILE_NAME
        self.entries: dict[str, LockEntry] = {}
        self._load()

    # -- persistence ------------------------------------------------------

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"malformed skill lockfile {self.path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"malformed skill lockfile {self.path}: top level must be an object")
        if raw.get("version") != LOCKFILE_VERSION:
            raise ValueError(
                f"unsupported skill lockfile version: {raw.get('version')!r} "
                f"(expected {LOCKFILE_VERSION})"
            )
        skills = raw.get("skills") or {}
        if not isinstance(skills, dict):
            raise ValueError(f"malformed skill lockfile {self.path}: 'skills' must be an object")
        for name, data in skills.items():
            if not isinstance(data, dict):
                raise ValueError(f"malformed skill lockfile {self.path}: entry {name!r} must be an object")
            self.entries[str(name)] = LockEntry.from_dict(str(name), data)

    def save(self) -> Path:
        """Persist the lockfile. Sorted keys keep diffs reviewable."""
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": LOCKFILE_VERSION,
            "skills": {
                name: self.entries[name].to_dict()
                for name in sorted(self.entries)
            },
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return self.path

    # -- queries ------------------------------------------------------------

    def entry_for(self, name: str) -> LockEntry | None:
        return self.entries.get(_clean(name))

    def is_pinned(self, name: str) -> bool:
        entry = self.entry_for(name)
        return bool(entry and entry.pinned)

    def external_plugins(self) -> list[LockEntry]:
        """External (git) plugins, sorted by name for stable iteration."""
        return sorted(
            (entry for entry in self.entries.values() if entry.kind == "external"),
            key=lambda entry: entry.name,
        )

    # -- pin / record ---------------------------------------------------------

    def pin(
        self,
        name: str,
        *,
        version: str = "",
        sha: str = "",
        content_sha256: str = "",
        kind: str = "local",
        source: str = "",
    ) -> LockEntry:
        """Pin a skill: later overwriting changes are refused until unpinned."""
        clean_name = _clean(name)
        if not _NAME_RE.match(clean_name):
            raise ValueError(f"invalid skill name for pin: {name!r}")
        if kind not in ("local", "external"):
            raise ValueError(f"lock kind must be 'local' or 'external', got {kind!r}")
        clean_sha = _clean(sha)
        if kind == "external":
            if not _SHA_RE.match(clean_sha):
                raise ValueError(
                    f"external plugin {clean_name!r} must pin a full 40-hex git SHA, "
                    f"got {sha!r}"
                )
            if not _clean(source):
                raise ValueError(f"external plugin {clean_name!r} must record its git source")
        entry = LockEntry(
            name=clean_name,
            version=_clean(version),
            sha=clean_sha,
            content_sha256=_clean(content_sha256),
            pinned=True,
            kind=kind,
            source=_clean(source),
            updated_at=_utc_now(),
        )
        self.entries[clean_name] = entry
        return entry

    def unpin(self, name: str) -> LockEntry | None:
        """Explicitly lift a pin. The entry stays, now updatable."""
        entry = self.entry_for(name)
        if entry is None:
            return None
        entry.pinned = False
        entry.updated_at = _utc_now()
        return entry

    def record(
        self,
        name: str,
        *,
        version: str = "",
        sha: str = "",
        content_sha256: str = "",
        kind: str = "local",
        source: str = "",
    ) -> LockEntry:
        """Record an (unpinned) install/update. Refuses to overwrite a pin."""
        clean_name = _clean(name)
        existing = self.entry_for(clean_name)
        if existing is not None and existing.pinned:
            raise SkillLockedError(
                f"skill {clean_name!r} is pinned (version={existing.version!r}, "
                f"sha={existing.sha!r}); unpin it explicitly before updating"
            )
        entry = LockEntry(
            name=clean_name,
            version=_clean(version),
            sha=_clean(sha),
            content_sha256=_clean(content_sha256),
            pinned=False,
            kind=kind,
            source=_clean(source),
            updated_at=_utc_now(),
        )
        self.entries[clean_name] = entry
        return entry

    # -- enforcement ----------------------------------------------------------

    def check_write(
        self,
        name: str,
        *,
        new_text: str,
        new_version: str = "",
        new_sha: str = "",
    ) -> None:
        """Refuse an overwriting change to a pinned skill; no-op otherwise.

        Identical content is not a change: re-writing the same bytes is
        allowed so idempotent installs do not trip the pin. Any other
        write to a pinned skill raises ``SkillLockedError`` and the
        caller must leave the file untouched.
        """
        entry = self.entry_for(name)
        if entry is None or not entry.pinned:
            return
        new_hash = content_sha256(new_text)
        if entry.content_sha256 and new_hash == entry.content_sha256:
            return
        if (
            entry.content_sha256 == ""
            and _clean(new_version) == entry.version
            and _clean(new_sha) == entry.sha
            and (entry.version or entry.sha)
        ):
            return
        raise SkillLockedError(
            f"skill {_clean(name)!r} is pinned (version={entry.version!r}, "
            f"sha={entry.sha!r}); refusing overwrite -- unpin it explicitly "
            "first if the change is intended"
        )


def check_plugin_updates(
    lock: SkillLock,
    *,
    fetcher: Callable[[str], str],
) -> list[PluginUpdateCheck]:
    """Nightly check: latest SHA per external plugin, failure-isolated.

    ``fetcher(source)`` returns the plugin repo's latest commit SHA.
    A fetcher exception for one plugin records ``failed`` for that
    plugin only; every other plugin is still checked.
    """
    results: list[PluginUpdateCheck] = []
    for entry in lock.external_plugins():
        check = PluginUpdateCheck(
            name=entry.name, source=entry.source, locked_sha=entry.sha
        )
        try:
            latest = _clean(fetcher(entry.source))
        except Exception as exc:  # noqa: BLE001 -- isolation: record, continue
            check.status = "failed"
            check.error = str(exc) or exc.__class__.__name__
            results.append(check)
            continue
        if not _SHA_RE.match(latest):
            check.status = "failed"
            check.error = f"fetcher returned a non-SHA value: {latest!r}"
            results.append(check)
            continue
        check.latest_sha = latest
        check.status = "update-available" if latest != entry.sha else "up-to-date"
        results.append(check)
    return results


def plan_upgrades(checks: list[PluginUpdateCheck]) -> list[PluginUpgradePlan]:
    """One upgrade plan per update-available plugin; failures get none."""
    return [
        PluginUpgradePlan(
            name=check.name,
            source=check.source,
            from_sha=check.locked_sha,
            to_sha=check.latest_sha,
        )
        for check in checks
        if check.status == "update-available"
    ]


__all__ = [
    "LOCKFILE_NAME",
    "LOCKFILE_VERSION",
    "PINNED",
    "LockEntry",
    "PluginUpdateCheck",
    "PluginUpgradePlan",
    "SkillLock",
    "SkillLockedError",
    "check_plugin_updates",
    "content_sha256",
    "plan_upgrades",
]
