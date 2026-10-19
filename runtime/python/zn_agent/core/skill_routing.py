from __future__ import annotations

"""ZN skill routing with progressive disclosure. ZN-owned.

Mechanism adapted from the Agent Skills open specification (SKILL.md format,
three-stage progressive disclosure) and the Muse skill-routing decision tree
(check skills first, honestly say when none exists). No third-party code is
copied; the mechanism is re-implemented for ZN's file-based skill bundles.

Three disclosure stages, each strictly more expensive than the last:

1. Discovery -- read ONLY the YAML frontmatter (``name`` + ``description``,
   plus ``allowed-tools`` / ``version`` / ``source``) of each skill file.
   The body is never read at this stage: discovery stops reading at the
   closing ``---`` fence, so even a body with invalid UTF-8 cannot break it.
2. Activation -- only for skills that matched the query, read the full
   ``SKILL.md`` body (``< 5,000`` approx. tokens). Unmatched skills' bodies
   are never read.
3. Execution -- only on demand, load one file from ``scripts/``,
   ``references/`` or ``assets/`` via :meth:`SkillRouter.load_execution_asset`.

No match is an explicit, honest result (:class:`RouteResult` with
``no_skill=True`` plus a fallback path), never a fabricated capability.

Intake validation (:func:`validate_skill_file`) enforces the Agent Skills
discipline: ``description`` must say both what the skill does AND when to
use it (a trigger condition), frontmatter must carry an ``allowed-tools``
whitelist, the body must stay under the token budget, scripts must pass a
static runnable-shape check (they are never executed by validation), and an
externally-sourced skill must have a recorded human review before it can be
trusted.

Skills are DATA, not authority, exactly like in ``skills.py``: routing never
grants tool permission, changes Work route policy, requires an action, or
proves task completion.
"""

import math
import re
import stat
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .home import get_zn_home

MAX_SKILL_BODY_TOKENS = 5000
MAX_SKILL_DESCRIPTION_CHARS = 500
_DEFAULT_MAX_SKILLS = 3
_MAX_ROUTE_SKILLS = 10

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SCRIPT_EXTENSIONS = {".py", ".sh", ".js", ".ts", ".mjs", ".cjs"}
_EXECUTION_DIRS = ("scripts", "references", "assets")

_NO_SKILL_FALLBACK = (
    "Proceed without skill-backed capability: use general reasoning for "
    "this request, do not claim a skill was applied, and ask the user for "
    "clarification when the task needs a skill-specific procedure."
)


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[\W_]+", " ", text)
    return " ".join(text.split())


def _cue_occurs(query: str, cue: str) -> bool:
    if not query or not cue:
        return False
    if query == cue:
        return True
    if len(cue) < 2:
        return False
    if re.search(r"[\u4e00-\u9fff]", cue):
        return cue in query
    if re.search(r"[a-z0-9]", cue):
        # Generic one-word cues are not semantic matches; require a phrase
        # or a long-enough token to avoid ambient activation.
        if " " not in cue and len(cue) < 12:
            return False
        return re.search(rf"(?<![a-z0-9_]){re.escape(cue)}(?![a-z0-9_])", query) is not None
    return re.search(rf"(?<!\w){re.escape(cue)}(?!\w)", query) is not None


def approx_tokens(text: str) -> int:
    """Rough token estimate (1 token ~= 4 chars). Budget checks only."""
    return max(1, math.ceil(len(text or "") / 4))


def has_trigger_condition(description: str) -> bool:
    """True when the description says WHEN to use the skill, not just what it does.

    Chinese: ``当……时`` / ``当……使用``. English: ``when ...`` /
    ``use this when ...`` / ``if ... use ...``.
    """
    text = _clean(description)
    if not text:
        return False
    lowered = text.casefold()
    if "当" in text and ("时" in text or "使用" in text):
        return True
    if "when" in lowered:
        return True
    if "use this" in lowered:
        return True
    if "if " in lowered and "use" in lowered:
        return True
    return False


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    try:
        meta = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(meta, dict):
        return {}, text
    return meta, text[end + 4 :].lstrip("\n")


def _read_frontmatter_only(path: Path) -> dict[str, Any]:
    """Parse frontmatter without reading the body.

    Reads the file line by line and stops at the closing ``---`` fence, so
    the body is never loaded during Discovery.
    """
    try:
        with open(path, "rb") as handle:
            first = handle.readline()
            if first.strip() != b"---":
                return {}
            lines: list[bytes] = []
            for line in handle:
                if line.strip() == b"---":
                    break
                lines.append(line)
            else:
                return {}
            try:
                meta = yaml.safe_load(b"".join(lines).decode("utf-8")) or {}
            except (UnicodeError, yaml.YAMLError):
                return {}
    except OSError:
        return {}
    return meta if isinstance(meta, dict) else {}


def _skill_file(directory: Path) -> Path | None:
    """Spec name first (``SKILL.md``), ZN's existing ``skill.md`` as fallback."""
    for name in ("SKILL.md", "skill.md"):
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def _allowed_tools(meta: dict[str, Any]) -> tuple[str, ...] | None:
    raw = meta.get("allowed-tools", meta.get("allowed_tools"))
    if raw is None:
        return None
    if not isinstance(raw, list):
        return None
    tools: list[str] = []
    for item in raw:
        text = _clean(item)
        if not text:
            return None
        tools.append(text)
    return tuple(tools)


@dataclass(frozen=True, slots=True)
class SkillHeader:
    """Discovery-stage view: frontmatter only, no body."""

    name: str
    description: str
    version: str
    path: Path
    allowed_tools: tuple[str, ...] = ()
    source: str = "local"


@dataclass(frozen=True, slots=True)
class SkillMatch:
    header: SkillHeader
    cue: str


def _best_cue_for_header(normalized_query: str, header: SkillHeader) -> str:
    cues = {_normalize(header.name), _normalize(header.description)}
    words = _normalize(header.description).split()
    for width in range(min(4, len(words)), 1, -1):
        for index in range(len(words) - width + 1):
            cues.add(" ".join(words[index : index + width]))
    # Chinese has no word spaces, so a whole description is one
    # "word" and word n-grams can never find a sub-phrase inside it.
    # Add character n-grams (>= 4 chars) for CJK tokens so a phrase
    # like "中文任务管理" can match inside a longer description.
    # Longest-cue-wins keeps this precise.
    for word in words:
        if re.search(r"[\u4e00-\u9fff]", word):
            for length in range(min(8, len(word)), 3, -1):
                for index in range(len(word) - length + 1):
                    cues.add(word[index : index + length])
    best = ""
    for cue in cues:
        if _cue_occurs(normalized_query, cue) and len(cue) > len(best):
            best = cue
    return best


def match_skill_headers(
    headers: list[SkillHeader],
    query: str,
    *,
    max_skills: int = _DEFAULT_MAX_SKILLS,
) -> list[SkillMatch]:
    """Trigger-match pre-built headers (frontmatter only; no body reads).

    Shared by :meth:`SkillRouter.match` (single root) and layered callers
    that match over already-resolved registry winners. Most-specific cue
    wins; name breaks ties for determinism.
    """
    count = max(0, min(_MAX_ROUTE_SKILLS, int(max_skills)))
    normalized = _normalize(query)
    if not count or not normalized:
        return []
    scored: list[tuple[int, str, SkillHeader, str]] = []
    for header in headers:
        cue = _best_cue_for_header(normalized, header)
        if cue:
            scored.append((len(cue), header.name, header, cue))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [SkillMatch(header=header, cue=cue) for _, _, header, cue in scored[:count]]


@dataclass(frozen=True, slots=True)
class ActivatedSkill:
    """Activation-stage view: header + full body + on-demand asset names."""

    header: SkillHeader
    body: str
    token_estimate: int
    scripts: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    assets: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SkillValidation:
    valid: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RouteResult:
    """Routing outcome. ``no_skill`` means: no capability was claimed."""

    query: str
    matched: tuple[ActivatedSkill, ...] = ()
    no_skill: bool = True
    message: str = ""
    fallback: str = _NO_SKILL_FALLBACK
    skipped: tuple[str, ...] = ()


def validate_skill_file(path: Path, *, external: bool | None = None) -> SkillValidation:
    """Intake validation for one skill file. Never executes scripts.

    ``external=None`` auto-detects external origin from frontmatter
    ``source``/``origin == "external"``; external skills additionally require
    a recorded human review (``reviewed: true`` + ``reviewed_by``).
    """
    reasons: list[str] = []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return SkillValidation(False, ("skill file is missing or not valid UTF-8",))
    meta, body = _split_frontmatter(text)
    if not meta:
        reasons.append("missing or unparsable YAML frontmatter")
        return SkillValidation(False, tuple(reasons))

    name = meta.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(_clean(name)):
        reasons.append("frontmatter 'name' is missing or not a valid skill name")

    description = _clean(meta.get("description") or "")
    if not description:
        reasons.append("frontmatter 'description' is missing")
    else:
        if len(description) > MAX_SKILL_DESCRIPTION_CHARS:
            reasons.append("description exceeds 500 characters")
        if not has_trigger_condition(description):
            reasons.append(
                "description states no trigger condition (say when to use it, "
                "e.g. 'when ...' / '当……时')"
            )

    allowed = _allowed_tools(meta)
    if allowed is None:
        reasons.append("frontmatter must carry an 'allowed-tools' whitelist (may be empty)")

    body = body.strip()
    if not body:
        reasons.append("skill body is empty")
    elif approx_tokens(body) >= MAX_SKILL_BODY_TOKENS:
        reasons.append(
            f"skill body exceeds {MAX_SKILL_BODY_TOKENS} approx. tokens "
            f"(~{approx_tokens(body)})"
        )

    scripts_dir = Path(path).parent / "scripts"
    if scripts_dir.is_dir():
        for script in sorted(scripts_dir.rglob("*")):
            if not script.is_file():
                continue
            try:
                is_empty = script.stat().st_size == 0
                executable = bool(script.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
            except OSError:
                reasons.append(f"script {script.name} is unreadable")
                continue
            if is_empty:
                reasons.append(f"script {script.name} is empty")
            elif script.suffix not in _SCRIPT_EXTENSIONS and not executable:
                reasons.append(
                    f"script {script.name} has no recognized script extension "
                    "and is not executable"
                )

    is_external = external
    if is_external is None:
        origin = _clean(meta.get("source") or meta.get("origin") or "local").casefold()
        is_external = origin == "external"
    if is_external:
        if meta.get("reviewed") is not True:
            reasons.append("external skill requires a human review (reviewed: true)")
        if not _clean(meta.get("reviewed_by") or ""):
            reasons.append("external skill requires 'reviewed_by' (who reviewed it)")

    return SkillValidation(valid=not reasons, reasons=tuple(reasons))


class SkillRouter:
    """Progressive-disclosure routing over file-based skill bundles."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else get_zn_home() / "skills"

    # -- Stage 1: Discovery (frontmatter only) ---------------------------

    def discover(self) -> list[SkillHeader]:
        """List skill headers. Never reads any skill body."""
        found: list[SkillHeader] = []
        if not self.root.is_dir():
            return found
        for candidate in sorted(self.root.iterdir()):
            if not candidate.is_dir() or candidate.name.startswith(("_", ".")):
                continue
            skill_file = _skill_file(candidate)
            if skill_file is None:
                continue
            header = self._read_header(skill_file)
            if header is not None:
                found.append(header)
        return found

    def _read_header(self, path: Path) -> SkillHeader | None:
        meta = _read_frontmatter_only(path)
        name = _clean(meta.get("name") or path.parent.name)
        description = _clean(meta.get("description") or "")
        version = _clean(meta.get("version") or "0.1.0")
        if not _NAME_RE.match(name):
            return None
        if not description or len(description) > MAX_SKILL_DESCRIPTION_CHARS:
            return None
        allowed = _allowed_tools(meta)
        return SkillHeader(
            name=name,
            description=description,
            version=version,
            path=path,
            allowed_tools=allowed or (),
            source=_clean(meta.get("source") or meta.get("origin") or "local"),
        )

    # -- Matching (headers only; most specific cue first) -----------------

    def match(self, query: str, *, max_skills: int = _DEFAULT_MAX_SKILLS) -> list[SkillMatch]:
        return match_skill_headers(
            self.discover(), query, max_skills=max_skills
        )

    def _best_cue(self, normalized_query: str, header: SkillHeader) -> str:
        return _best_cue_for_header(normalized_query, header)

    # -- Stage 2: Activation (read body of matched skills only) ----------

    def activate(self, name: str) -> ActivatedSkill | None:
        header = next((item for item in self.discover() if item.name == name), None)
        if header is None:
            return None
        try:
            text = header.path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None
        _, body = _split_frontmatter(text)
        body = body.strip()
        if not body:
            return None
        tokens = approx_tokens(body)
        if tokens >= MAX_SKILL_BODY_TOKENS:
            return None
        skill_dir = header.path.parent
        listings: dict[str, tuple[str, ...]] = {}
        for dirname in _EXECUTION_DIRS:
            subdir = skill_dir / dirname
            if not subdir.is_dir():
                listings[dirname] = ()
                continue
            listings[dirname] = tuple(
                sorted(
                    str(item.relative_to(subdir))
                    for item in subdir.rglob("*")
                    if item.is_file()
                )
            )
        return ActivatedSkill(
            header=header,
            body=body,
            token_estimate=tokens,
            scripts=listings["scripts"],
            references=listings["references"],
            assets=listings["assets"],
        )

    # -- Stage 3: Execution (load one asset on demand) -------------------

    def load_execution_asset(self, name: str, relative: str) -> str | None:
        """Load one file from ``scripts/`` / ``references/`` / ``assets/``.

        Returns None for traversal escapes, files outside the three execution
        directories, missing files, and non-UTF-8 content. Never executes.
        """
        header = next((item for item in self.discover() if item.name == name), None)
        if header is None:
            return None
        parts = Path(relative).parts
        if not parts or Path(relative).is_absolute() or ".." in parts:
            return None
        if parts[0] not in _EXECUTION_DIRS:
            return None
        skill_dir = header.path.parent
        try:
            resolved = (skill_dir / relative).resolve()
            allowed_root = (skill_dir / parts[0]).resolve()
        except OSError:
            return None
        if not resolved.is_relative_to(allowed_root) or not resolved.is_file():
            return None
        try:
            return resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None

    # -- Combined route ---------------------------------------------------

    def route(self, query: str, *, max_skills: int = _DEFAULT_MAX_SKILLS) -> RouteResult:
        query = _clean(query)
        matches = self.match(query, max_skills=max_skills)
        if not matches:
            return RouteResult(
                query=query,
                matched=(),
                no_skill=True,
                message=(
                    "No available skill matched this request. No skill "
                    "capability is claimed."
                ),
                fallback=_NO_SKILL_FALLBACK,
            )
        activated: list[ActivatedSkill] = []
        skipped: list[str] = []
        for item in matches:
            skill = self.activate(item.header.name)
            if skill is None:
                skipped.append(item.header.name)
            else:
                activated.append(skill)
        if not activated:
            return RouteResult(
                query=query,
                matched=(),
                no_skill=True,
                message=(
                    "Skill(s) matched but none could be activated "
                    f"(skipped: {', '.join(skipped)}). No skill capability "
                    "is claimed."
                ),
                fallback=_NO_SKILL_FALLBACK,
                skipped=tuple(skipped),
            )
        names = ", ".join(skill.header.name for skill in activated)
        suffix = f" Skipped (could not activate): {', '.join(skipped)}." if skipped else ""
        return RouteResult(
            query=query,
            matched=tuple(activated),
            no_skill=False,
            message=f"Matched skill(s): {names}.{suffix}",
            fallback=_NO_SKILL_FALLBACK,
            skipped=tuple(skipped),
        )

    # -- Intake ------------------------------------------------------------

    def validate(self, name: str) -> SkillValidation:
        header = next((item for item in self.discover() if item.name == name), None)
        if header is None:
            return SkillValidation(False, (f"no registered skill named '{name}'",))
        return validate_skill_file(header.path)
