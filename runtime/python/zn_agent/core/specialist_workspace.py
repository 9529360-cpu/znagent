from __future__ import annotations

"""Specialist file workspaces: one directory per specialist, files as source
of truth.

A team specialist used to live only as a ``prompt_fragment`` string baked
into code (see ``project_team.ROLE_TEMPLATES``): changing a specialist's
persona meant changing code. A file workspace gives each specialist a
visible, editable form::

    agents/<specialist-name>/
        SOUL.md        persona: how the specialist behaves
        IDENTITY.md    who the specialist is (name, role, title)
        MEMORY.md      long-term memory, one fact per line
        agent.json     config (role key, responsibilities, model override)
        skills/        specialist-private skills

Rules:

- Files are the source of truth; the prompt is only a rendering of them.
  Every dispatch re-reads the files, so editing ``SOUL.md`` takes effect on
  the next dispatch -- no restart, no cached persona.
- ``materialize_*`` never overwrites existing files: re-materializing a
  workspace keeps the specialist's edits.
- Dispatch never breaks on a bad workspace: ``specialist_prompt_for``
  falls back to the built-in ``prompt_fragment`` when the workspace is
  missing, empty, or unreadable.
- Specialist ids are directory names, so path traversal is rejected.
- No secrets here: a workspace must never contain credentials. Keys live
  in the credential store, never in these files.

Two-stage Rules (CUR-1): injection is NOT activation. A prompt that lists
many specialists (or rules) must not pay a fixed token tax for every full
persona. The resident layer carries only
:func:`build_specialist_resident_summary` — a capped summary, a trigger
description (when this specialist applies), and ``globs`` from
``agent.json`` scoping which file types the specialist applies to. The
full persona is loaded on demand via
``specialist_prompt_for(..., stage="full")`` (the default: a real dispatch
needs the full persona). ``stage="resident"`` renders the short form.
Over-cap summaries are truncated at build time (``truncated: True``) and
rejected by :func:`validate_resident_summary`.

Pure stdlib. No imports from other ZN modules: callers pass duck-typed
team / specialist objects, which keeps ``project_team`` I/O-free.
"""

import fnmatch
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

SOUL_FILENAME = "SOUL.md"
IDENTITY_FILENAME = "IDENTITY.md"
MEMORY_FILENAME = "MEMORY.md"
CONFIG_FILENAME = "agent.json"
SKILLS_DIRNAME = "skills"

#: Resident-layer cap (CUR-1, mirrors skills.MAX_RESIDENT_SUMMARY_CHARS):
#: a summary or trigger longer than this is truncated at build time and
#: rejected at validation time.
MAX_RESIDENT_SUMMARY_CHARS = 280

#: Keys the workspace config may carry. Unknown keys are kept as-is on
#: load (forward compatible) but only these are rendered into the prompt.
_CONFIG_PROMPT_KEYS = ("role_key", "role_title", "responsibilities", "model")


@dataclass(frozen=True, slots=True)
class SpecialistWorkspace:
    """A specialist's files, loaded from its workspace directory."""

    specialist_id: str
    root: str
    soul: str = ""
    identity: str = ""
    memory_text: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    skill_files: tuple[str, ...] = ()


def validate_specialist_id(specialist_id: str) -> str:
    """Return the id if it is safe to use as a directory name."""
    if not isinstance(specialist_id, str) or not specialist_id.strip():
        raise ValueError("specialist id must be a non-empty string")
    if specialist_id in (".", ".."):
        raise ValueError(f"unsafe specialist id: {specialist_id!r}")
    if any(ch in specialist_id for ch in ("/", "\\", ":", "\x00")):
        raise ValueError(f"unsafe specialist id: {specialist_id!r}")
    return specialist_id


def workspace_dir(root: str | Path, specialist_id: str) -> Path:
    """Directory holding one specialist's files."""
    return Path(root) / validate_specialist_id(specialist_id)


def _write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.write_text(content, encoding="utf-8")


def _read_if_present(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def materialize_specialist_workspace(root: str | Path, specialist: Any) -> Path:
    """Create a specialist's workspace files from its built-in definition.

    Existing files are left untouched, so re-materializing never clobbers
    hand edits. Returns the workspace directory.
    """
    directory = workspace_dir(root, str(specialist.name))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / SKILLS_DIRNAME).mkdir(exist_ok=True)

    responsibilities = tuple(getattr(specialist, "responsibilities", ()) or ())
    _write_if_missing(
        directory / SOUL_FILENAME,
        f"# SOUL\n\n{getattr(specialist, 'prompt_fragment', '') or ''}\n",
    )
    identity_lines = [
        "# IDENTITY",
        "",
        f"Name: {specialist.name}",
        f"Role: {getattr(specialist, 'role_key', '')}",
        f"Title: {getattr(specialist, 'role_title', '')}",
    ]
    if responsibilities:
        identity_lines.append("")
        identity_lines.append("Responsibilities:")
        identity_lines.extend(f"- {item}" for item in responsibilities)
    identity_lines.append("")
    _write_if_missing(directory / IDENTITY_FILENAME, "\n".join(identity_lines))
    _write_if_missing(
        directory / MEMORY_FILENAME,
        "# MEMORY\n\n<!-- Long-term memory: one fact per line. -->\n",
    )
    config = {
        "role_key": getattr(specialist, "role_key", ""),
        "role_title": getattr(specialist, "role_title", ""),
        "responsibilities": list(responsibilities),
        "memory_namespace": getattr(specialist, "memory_namespace", ""),
    }
    _write_if_missing(
        directory / CONFIG_FILENAME,
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
    )
    return directory


def materialize_team_workspaces(root: str | Path, team: Any) -> list[Path]:
    """Materialize a workspace for every member of ``team``."""
    return [
        materialize_specialist_workspace(root, member)
        for member in getattr(team, "members", ())
    ]


def load_specialist_workspace(root: str | Path, specialist_id: str) -> SpecialistWorkspace:
    """Load one specialist's files. Raises FileNotFoundError when the
    directory is missing, ValueError on malformed ``agent.json``."""
    directory = workspace_dir(root, specialist_id)
    if not directory.is_dir():
        raise FileNotFoundError(f"specialist workspace not found: {directory}")

    config: dict[str, Any] = {}
    config_path = directory / CONFIG_FILENAME
    if config_path.exists():
        try:
            parsed = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed {CONFIG_FILENAME} in {directory}: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"{CONFIG_FILENAME} in {directory} must be a JSON object")
        config = parsed

    skills_dir = directory / SKILLS_DIRNAME
    skill_files: tuple[str, ...] = ()
    if skills_dir.is_dir():
        skill_files = tuple(
            sorted(
                path.relative_to(skills_dir).as_posix()
                for path in skills_dir.rglob("*")
                if path.is_file()
            )
        )

    return SpecialistWorkspace(
        specialist_id=validate_specialist_id(specialist_id),
        root=str(directory),
        soul=_read_if_present(directory / SOUL_FILENAME),
        identity=_read_if_present(directory / IDENTITY_FILENAME),
        memory_text=_read_if_present(directory / MEMORY_FILENAME),
        config=config,
        skill_files=skill_files,
    )


def build_specialist_prompt(workspace: SpecialistWorkspace) -> str:
    """Render a specialist's files into the system-prompt text.

    Empty sections are skipped; a workspace with no content renders to
    ``""`` so callers can fall back to the built-in prompt fragment.
    """
    sections: list[str] = []
    if workspace.identity.strip():
        sections.append(f"# IDENTITY\n\n{workspace.identity.strip()}")
    if workspace.soul.strip():
        sections.append(f"# SOUL\n\n{workspace.soul.strip()}")
    if workspace.memory_text.strip():
        sections.append(f"# MEMORY\n\n{workspace.memory_text.strip()}")
    rendered_config: list[str] = []
    for key in _CONFIG_PROMPT_KEYS:
        value = workspace.config.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            rendered_config.append(f"{key}: {', '.join(str(item) for item in value)}")
        else:
            rendered_config.append(f"{key}: {value}")
    if rendered_config:
        sections.append("# CONFIG\n\n" + "\n".join(rendered_config))
    return "\n\n".join(sections)


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _first_paragraph(text: str) -> str:
    """First non-heading, non-empty paragraph of ``text``."""
    for block in str(text or "").split("\n\n"):
        stripped = block.strip()
        if not stripped:
            continue
        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        lines = [line for line in lines if not line.startswith("#")]
        if lines:
            return " ".join(lines)
    return ""


def _first_sentence(text: str) -> str:
    """First sentence of ``text``.

    An ASCII ender (``.``/``!``/``?``) only counts when followed by a
    space or the end of the string, so dots inside ``TASKS.md`` or
    ``e.g.`` do not cut the sentence early.
    """
    cleaned = _clean_text(text)
    for index, char in enumerate(cleaned):
        if char in "。！？\n":
            head = cleaned[:index].strip()
            if head:
                return head
        elif char in ".!?":
            nxt = cleaned[index + 1] if index + 1 < len(cleaned) else ""
            if nxt in ("", " ", "\t"):
                head = cleaned[:index].strip()
                if head:
                    return head
    return cleaned


def _cap_entry_text(text: str) -> tuple[str, bool]:
    cleaned = _clean_text(text)
    if len(cleaned) <= MAX_RESIDENT_SUMMARY_CHARS:
        return cleaned, False
    return cleaned[: MAX_RESIDENT_SUMMARY_CHARS - 1].rstrip() + "…", True


def _is_absolute_pattern(pattern: str) -> bool:
    """Platform-independent absolute-path check for a glob pattern.

    ``Path.is_absolute()`` is platform-dependent: on Windows,
    ``Path('/abs/path').is_absolute()`` is False (no drive letter), so a
    POSIX absolute pattern would slip through as a glob on Windows.
    Check both POSIX and Windows semantics so the same frontmatter is
    rejected on every platform. A leading ``\\`` (Windows rooted path)
    and a drive prefix (``C:...``) are absolute on Windows even though
    ``PureWindowsPath.is_absolute()`` reports them as not absolute.
    """
    if pattern.startswith(("/", "\\")):
        return True
    if len(pattern) >= 2 and pattern[1] == ":" and pattern[0].isalpha():
        return True
    return PurePosixPath(pattern).is_absolute() or PureWindowsPath(
        pattern
    ).is_absolute()


def _parse_globs(value: object) -> tuple[str, ...]:
    """Valid ``globs`` patterns from config; invalid entries dropped."""
    if not isinstance(value, list):
        return ()
    patterns: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        pattern = item.strip()
        if not pattern or "\x00" in pattern or ".." in pattern:
            continue
        if _is_absolute_pattern(pattern):
            continue
        patterns.append(pattern)
    return tuple(patterns)


def rule_applies_to_path(globs: tuple[str, ...] | list[str], path: str | Path) -> bool:
    """True when a rule with ``globs`` applies to ``path``.

    Empty globs mean "applies everywhere". Otherwise the pattern is matched
    against both the file name (``*.py``) and the full posix path
    (``src/**/*.py``).
    """
    patterns = list(globs or ())
    if not patterns:
        return True
    if not path:
        return False
    text = str(path)
    name = Path(text).name
    posix = Path(text).as_posix()
    return any(
        fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(posix, pattern)
        for pattern in patterns
    )


def build_specialist_resident_summary(workspace: SpecialistWorkspace) -> dict[str, Any]:
    """Resident-stage entry for one specialist: summary + trigger + globs.

    Summary is the first paragraph of SOUL (first sentence when the
    paragraph is long), capped. Trigger is the config ``trigger`` when
    set, else the role title + responsibilities from IDENTITY/config.
    The full SOUL / MEMORY text is never in the resident entry.
    """
    summary, summary_cut = _cap_entry_text(
        _first_sentence(_first_paragraph(workspace.soul))
    )
    trigger_source = _clean_text(workspace.config.get("trigger") or "")
    if not trigger_source:
        parts = [
            _clean_text(workspace.config.get("role_title") or ""),
            _clean_text(workspace.config.get("role_key") or ""),
        ]
        responsibilities = workspace.config.get("responsibilities")
        if isinstance(responsibilities, list):
            parts.extend(_clean_text(item) for item in responsibilities)
        trigger_source = "; ".join(part for part in parts if part)
    trigger, trigger_cut = _cap_entry_text(trigger_source)
    return {
        "specialist_id": workspace.specialist_id,
        "summary": summary,
        "trigger": trigger,
        "globs": list(_parse_globs(workspace.config.get("globs"))),
        "truncated": summary_cut or trigger_cut,
    }


def validate_resident_summary(entry: dict[str, Any]) -> None:
    """Reject a resident summary whose summary/trigger exceeds the cap."""
    if not isinstance(entry, dict):
        raise ValueError("resident summary must be a dict")
    for key in ("summary", "trigger"):
        value = entry.get(key)
        if not isinstance(value, str):
            raise ValueError(f"resident summary {key!r} must be a string")
        if len(value) > MAX_RESIDENT_SUMMARY_CHARS:
            raise ValueError(
                f"resident summary {key!r} exceeds "
                f"{MAX_RESIDENT_SUMMARY_CHARS} chars ({len(value)})"
            )


def append_memory(root: str | Path, specialist_id: str, text: str) -> Path:
    """Append one dated fact to a specialist's ``MEMORY.md`` (memory on disk).

    The workspace directory must already exist; the memory file is created
    with a header when missing. Returns the memory file path.
    """
    if not text or not text.strip():
        raise ValueError("memory text must not be empty")
    directory = workspace_dir(root, specialist_id)
    if not directory.is_dir():
        raise FileNotFoundError(f"specialist workspace not found: {directory}")
    memory_path = directory / MEMORY_FILENAME
    _write_if_missing(
        memory_path, "# MEMORY\n\n<!-- Long-term memory: one fact per line. -->\n"
    )
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with memory_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n- [{stamp}] {text.strip()}\n")
    return memory_path


def specialist_prompt_for(team: Any, specialist: Any, *, stage: str = "full") -> str:
    """Prompt text for a specialist, re-read from its files each call.

    ``stage="full"`` (default): the full rendered persona, for a real
    dispatch. ``stage="resident"``: the short two-stage form — summary +
    trigger + globs + an activation hint, never the full SOUL / MEMORY
    text — for prompt layers that list many specialists. Any other stage
    raises ValueError.

    When the team has no ``workspace_root``, the workspace directory is
    missing, the files are empty, or anything fails to load, this falls
    back to the specialist's built-in ``prompt_fragment`` so dispatch
    never breaks on a workspace problem.
    """
    if stage not in ("full", "resident"):
        raise ValueError(f"unknown prompt stage: {stage!r} (want 'full' or 'resident')")
    fallback = getattr(specialist, "prompt_fragment", "") or ""
    root = getattr(team, "workspace_root", None)
    if not root:
        return fallback
    try:
        workspace = load_specialist_workspace(root, str(specialist.name))
    except (OSError, ValueError):
        return fallback
    if stage == "resident":
        summary = build_specialist_resident_summary(workspace)
        validate_resident_summary(summary)
        lines = [
            f"# {workspace.specialist_id} (resident rule)",
            "",
            f"Summary: {summary['summary']}",
            f"Trigger: {summary['trigger']}",
        ]
        if summary["globs"]:
            lines.append(f"Globs: {', '.join(summary['globs'])}")
        lines.append(
            "Activation: call specialist_prompt_for(team, specialist, "
            "stage='full') to load the full persona on demand."
        )
        return "\n".join(lines)
    rendered = build_specialist_prompt(workspace)
    return rendered or fallback


__all__ = [
    "CONFIG_FILENAME",
    "IDENTITY_FILENAME",
    "MAX_RESIDENT_SUMMARY_CHARS",
    "MEMORY_FILENAME",
    "SKILLS_DIRNAME",
    "SOUL_FILENAME",
    "SpecialistWorkspace",
    "append_memory",
    "build_specialist_prompt",
    "build_specialist_resident_summary",
    "load_specialist_workspace",
    "materialize_specialist_workspace",
    "materialize_team_workspaces",
    "rule_applies_to_path",
    "specialist_prompt_for",
    "validate_resident_summary",
    "validate_specialist_id",
    "workspace_dir",
]
