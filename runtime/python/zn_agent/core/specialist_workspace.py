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

Pure stdlib. No imports from other ZN modules: callers pass duck-typed
team / specialist objects, which keeps ``project_team`` I/O-free.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SOUL_FILENAME = "SOUL.md"
IDENTITY_FILENAME = "IDENTITY.md"
MEMORY_FILENAME = "MEMORY.md"
CONFIG_FILENAME = "agent.json"
SKILLS_DIRNAME = "skills"

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


def specialist_prompt_for(team: Any, specialist: Any) -> str:
    """Prompt text for a specialist, re-read from its files each call.

    When the team has no ``workspace_root``, the workspace directory is
    missing, the files are empty, or anything fails to load, this falls
    back to the specialist's built-in ``prompt_fragment`` so dispatch
    never breaks on a workspace problem.
    """
    fallback = getattr(specialist, "prompt_fragment", "") or ""
    root = getattr(team, "workspace_root", None)
    if not root:
        return fallback
    try:
        workspace = load_specialist_workspace(root, str(specialist.name))
    except (OSError, ValueError):
        return fallback
    rendered = build_specialist_prompt(workspace)
    return rendered or fallback


__all__ = [
    "CONFIG_FILENAME",
    "IDENTITY_FILENAME",
    "MEMORY_FILENAME",
    "SKILLS_DIRNAME",
    "SOUL_FILENAME",
    "SpecialistWorkspace",
    "append_memory",
    "build_specialist_prompt",
    "load_specialist_workspace",
    "materialize_specialist_workspace",
    "materialize_team_workspaces",
    "specialist_prompt_for",
    "validate_specialist_id",
    "workspace_dir",
]
