from __future__ import annotations

"""ZN Skill evals — deterministic Tier 1 + Tier 2 checks (AS-4). ZN-owned.

Two eval tiers, both deterministic and zero-token (no model calls, no
network, no wall-clock input). They are READ-ONLY checks: they never
modify a skill file, never change ``SkillStore`` / ``SkillRouter``
runtime behaviour, and never alter ranking results.

Tier 1 — structural validation of one skill file. Reuses the two existing
validators instead of inventing a third structure check:

- :func:`skill_checklist.check_skill_file` (KWP-1 + AS-2 writing rules:
  quoted trigger phrase, description ceilings, line budget, bypass
  language, progressive-disclosure layers);
- :func:`skill_routing.validate_skill_file` (intake: trigger condition,
  ``allowed-tools`` whitelist, body token budget, script shape, external
  review).

On top of those, Tier 1 adds the two structural checks the validators do
not cover: the body must have at least one markdown section heading
(``章节``), and every local markdown link must resolve to a file inside
the skill directory. External (``http(s)``) links are never fetched —
deterministic means no network — they are reported as unchecked, never
as failures.

Description ceilings keep the layered semantics fixed by the checklist
(``docs/ZN-SKILL-WRITING-CHECKLIST.md`` §0): ``>1024`` characters is a
violation; ``(500, 1024]`` is a WARNING (the skill passes the checklist
but ``SkillStore`` / ``SkillRouter`` will drop it until shortened). The
runtime cap is intentionally NOT loosened. To keep that semantics,
Tier 1 maps the routing intake's ``description exceeds 500 characters``
reason to a warning instead of a violation — the checklist validator
already reports the same fact as a runtime-cap warning, so the intake
reason is dropped, not duplicated. Every other intake reason stays a
violation.

Tier 2 — trigger validation through the REAL router
(:class:`skill_routing.SkillRouter`, no toy ranking):

- Positive: each quoted trigger phrase from a skill's description must
  route that skill into the router's top-k AND activate it (``route()``
  returns it with ``no_skill=False``). A quoted phrase is the author's
  own declared trigger, so this is an end-to-end check of
  discovery -> cue matching -> activation, not a tautology on a fake
  scorer.
- Negative (generic): a fixed list of clearly unrelated tasks must match
  no skill. A match means the skill's description cues are over-broad.
  The list assumes the repo holds no skill about those topics (cooking,
  travel, gardening, ...); if such a skill ever lands, extend the list.
- Negative (cross-skill): a positive query for skill A must not match
  skill B. When B matches via the SAME quoted trigger phrase, that is a
  genuine trigger collision and is a violation. When B matches via a
  different (partially overlapping) cue, it is an ambiguity warning:
  the router legitimately returns several skills, and failing the build
  on any overlap would forbid related skills outright.
- Collision: pairwise description comparison. Sharing the same quoted
  trigger phrase is a violation (the trigger cannot tell the skills
  apart). Word-set Jaccard similarity >= :data:`COLLISION_JACCARD`
  is a warning. This is a LEXICAL heuristic: it catches copy-paste
  descriptions, not paraphrase-level semantic similarity (that would
  need embeddings or a model, which Tier 2 deliberately does not use).

``passed`` means "no violations". Warnings never block, but the author
must disposition each one (fix it or record in the PR why it is
acceptable) — the same contract as the checklist validator.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .skill_checklist import check_skill_file
from .skill_routing import SkillHeader, SkillRouter, validate_skill_file

#: Word-set Jaccard at or above this value counts as a description
#: collision warning (lexical heuristic, see module docstring).
COLLISION_JACCARD = 0.6
#: Default top-k for trigger checks (matches the router's default).
DEFAULT_TOP_K = 3
#: Fixed generic-negative queries: clearly unrelated tasks. See module
#: docstring for the assumption behind this list.
GENERIC_NEGATIVES: tuple[str, ...] = (
    "bake a chocolate cake from scratch",
    "book a flight to Paris next Friday",
    "water the garden plants this evening",
    "write a birthday poem for my grandmother",
    "change the oil in my car",
)

#: A quoted trigger phrase: "..." / "..." / "..." with at least 2 chars,
#: or a multi-word '...' phrase. Mirrors the checklist's quoted-phrase
#: rule so Tier 2 derives positives from exactly what Tier 1 requires.
_QUOTED_PHRASE_RE = re.compile(
    r'["\u201c\u201d]([^"\u201d]{2,})["\u201d]|\'([^\']*\s[^\']*)\''
)
#: Markdown links: [text](target) and ![alt](target).
_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
#: ATX section heading.
_HEADING_RE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)
#: Routing intake reason for an over-long description. Demoted to a
#: warning in Tier 1 (see module docstring); matched by substring.
_INTAKE_DESCRIPTION_TOO_LONG = "description exceeds 500 characters"

_SKILL_FILENAMES = ("SKILL.md", "skill.md")
_SKIP_DIRS = {".git", "node_modules", ".ci", "__pycache__", ".venv", "venv"}


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_words(text: str) -> set[str]:
    return set(_clean(text).casefold().split())


def extract_quoted_phrases(description: str) -> tuple[str, ...]:
    """Quoted trigger phrases in a description, deduplicated in order."""
    seen: list[str] = []
    for match in _QUOTED_PHRASE_RE.finditer(description or ""):
        phrase = _clean(match.group(1) or match.group(2) or "")
        if phrase and phrase not in seen:
            seen.append(phrase)
    return tuple(seen)


def find_skill_files(root: Path) -> list[Path]:
    """All skill files under ``root``, sorted, skipping VCS/venv dirs.

    A skill file is ``SKILL.md`` or ``skill.md`` in any directory.
    Deterministic: directory walk order is sorted at every level.
    """
    root = Path(root)
    found: list[Path] = []
    if not root.is_dir():
        return found
    for directory, dirnames, filenames in sorted_walk(root):
        for filename in sorted(filenames):
            if filename in _SKILL_FILENAMES:
                found.append(directory / filename)
    return sorted(found)


def sorted_walk(root: Path):
    """``os.walk`` with sorted dir order (deterministic).

    Skips VCS/venv/cache directories and hidden directories: skill
    bundles never live there, and the router ignores hidden/underscore
    directories too.
    """
    import os

    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in _SKIP_DIRS and not name.startswith((".", "_"))
        )
        yield Path(directory), dirnames, filenames


def _read_frontmatter(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    try:
        meta = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return {}
    return meta if isinstance(meta, dict) else {}


def _split_body(text: str) -> str:
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end < 0:
        return text
    return text[end + 4 :].lstrip("\n")


def _check_links(skill_path: Path, body: str) -> list[str]:
    """Local markdown links must resolve inside the skill directory."""
    violations: list[str] = []
    skill_dir = skill_path.parent
    try:
        resolved_dir = skill_dir.resolve()
    except OSError:
        return ["skill directory cannot be resolved"]
    for target in _LINK_RE.findall(body):
        if not target:
            continue
        lowered = target.casefold()
        if lowered.startswith(("http://", "https://", "mailto:", "#")):
            continue  # External links are never fetched; not failures.
        if target.startswith("/"):
            violations.append(f"absolute link target is not allowed: {target}")
            continue
        candidate = skill_dir / target
        try:
            resolved = candidate.resolve()
        except OSError:
            violations.append(f"link target cannot be resolved: {target}")
            continue
        if not resolved.is_relative_to(resolved_dir):
            violations.append(
                f"link target escapes the skill directory: {target}"
            )
        elif not resolved.is_file():
            violations.append(f"broken link: {target} (no such file)")
    return violations


# --------------------------------------------------------------------------
# Tier 1
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Tier1Result:
    """Tier 1 outcome for one skill file."""

    path: str
    skill_name: str
    passed: bool
    violations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def eval_tier1_file(path: Path) -> Tier1Result:
    """Tier 1 structural eval for one skill file on disk."""
    path = Path(path)
    meta = _read_frontmatter(path)
    skill_name = _clean(meta.get("name") or path.parent.name)

    violations: list[str] = []
    warnings: list[str] = []

    checklist = check_skill_file(path)
    violations.extend(f"checklist: {item}" for item in checklist.violations)
    warnings.extend(f"checklist: {item}" for item in checklist.warnings)

    intake = validate_skill_file(path)
    for reason in intake.reasons:
        if _INTAKE_DESCRIPTION_TOO_LONG in reason:
            # Layered ceilings (see module docstring): the checklist
            # already warns about the runtime cap; do not double-report
            # and do not promote it to a violation.
            continue
        violations.append(f"intake: {reason}")

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        text = ""
    if text:
        body = _split_body(text)
        if not _HEADING_RE.search(body):
            violations.append("sections: body has no markdown section heading")
        violations.extend(f"links: {item}" for item in _check_links(path, body))

    return Tier1Result(
        path=str(path),
        skill_name=skill_name,
        passed=not violations,
        violations=tuple(violations),
        warnings=tuple(warnings),
    )


def eval_tier1_files(paths: list[Path]) -> list[Tier1Result]:
    """Tier 1 eval for an explicit list of skill files (sorted input)."""
    return [eval_tier1_file(path) for path in sorted(Path(p) for p in paths)]


def eval_tier1_root(skills_root: Path) -> list[Tier1Result]:
    """Tier 1 eval for every skill file under ``skills_root``."""
    return eval_tier1_files(find_skill_files(skills_root))


# --------------------------------------------------------------------------
# Tier 2
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TriggerCheck:
    """One trigger query outcome."""

    skill_name: str
    query: str
    kind: str  # positive | generic-negative | cross-negative
    passed: bool
    matched_names: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Collision:
    """One description-collision finding between two skills."""

    skill_a: str
    skill_b: str
    severity: str  # violation | warning
    reason: str


@dataclass(frozen=True, slots=True)
class Tier2Result:
    """Tier 2 outcome for a whole skills root."""

    passed: bool
    checks: tuple[TriggerCheck, ...] = ()
    collisions: tuple[Collision, ...] = ()
    warnings: tuple[str, ...] = ()


def eval_description_collisions(
    headers: list[SkillHeader],
) -> list[Collision]:
    """Pairwise description-collision findings (deterministic order)."""
    ordered = sorted(headers, key=lambda header: header.name)
    collisions: list[Collision] = []
    for index, first in enumerate(ordered):
        for second in ordered[index + 1 :]:
            shared = set(extract_quoted_phrases(first.description)) & set(
                extract_quoted_phrases(second.description)
            )
            if shared:
                phrase = sorted(shared)[0]
                collisions.append(
                    Collision(
                        skill_a=first.name,
                        skill_b=second.name,
                        severity="violation",
                        reason=(
                            "shared quoted trigger phrase "
                            f"'{phrase}': the trigger cannot tell the "
                            "skills apart"
                        ),
                    )
                )
                continue
            words_a = _normalize_words(first.description)
            words_b = _normalize_words(second.description)
            union = words_a | words_b
            if not union:
                continue
            similarity = len(words_a & words_b) / len(union)
            if similarity >= COLLISION_JACCARD:
                collisions.append(
                    Collision(
                        skill_a=first.name,
                        skill_b=second.name,
                        severity="warning",
                        reason=(
                            "description word-set Jaccard "
                            f"{similarity:.2f} >= {COLLISION_JACCARD}: "
                            "descriptions are near-identical (lexical "
                            "heuristic; paraphrases may still slip past)"
                        ),
                    )
                )
    return collisions


def eval_tier2_router(
    router: SkillRouter,
    *,
    top_k: int = DEFAULT_TOP_K,
    generic_negatives: tuple[str, ...] = GENERIC_NEGATIVES,
) -> Tier2Result:
    """Tier 2 trigger eval over the skills a router discovers."""
    headers = router.discover()
    checks: list[TriggerCheck] = []
    warnings: list[str] = []
    violations = 0
    if not headers:
        return Tier2Result(
            passed=True,
            checks=(),
            collisions=(),
            warnings=("no skills discovered by the router; nothing to trigger-check",),
        )

    for header in sorted(headers, key=lambda item: item.name):
        positives = extract_quoted_phrases(header.description)
        if not positives:
            warnings.append(
                f"{header.name}: no quoted trigger phrase in description, "
                "so no positive trigger query can be derived (Tier 1 "
                "already flags this as a violation)"
            )
            continue
        for query in positives:
            matches = router.match(query, max_skills=top_k)
            matched_names = tuple(match.header.name for match in matches)
            route = router.route(query, max_skills=top_k)
            activated_names = tuple(
                skill.header.name for skill in route.matched
            )
            self_hit = header.name in matched_names
            self_activated = header.name in activated_names
            if self_hit and self_activated:
                checks.append(
                    TriggerCheck(
                        skill_name=header.name,
                        query=query,
                        kind="positive",
                        passed=True,
                        matched_names=matched_names,
                        detail="routed into top-k and activated",
                    )
                )
            else:
                violations += 1
                checks.append(
                    TriggerCheck(
                        skill_name=header.name,
                        query=query,
                        kind="positive",
                        passed=False,
                        matched_names=matched_names,
                        detail=(
                            "positive trigger query did not route this "
                            f"skill into top-{top_k}"
                            + (
                                " (matched but not activated)"
                                if self_hit
                                else ""
                            )
                        ),
                    )
                )
            # Cross-skill negatives: this skill's own trigger must not
            # pull in another skill via the SAME quoted phrase (that is
            # a collision); a partial-cue overlap is an ambiguity
            # warning, not a failure. Compare quoted phrases directly:
            # the router's matched cue is capped at 4-word n-grams, so
            # a shared phrase longer than that would never show up as
            # an equal cue.
            headers_by_name = {item.name: item for item in headers}
            own_phrases = {
                " ".join(phrase.casefold().split()) for phrase in positives
            }
            for match in matches:
                if match.header.name == header.name:
                    continue
                other = headers_by_name.get(match.header.name)
                other_phrases = (
                    {
                        " ".join(phrase.casefold().split())
                        for phrase in extract_quoted_phrases(other.description)
                    }
                    if other is not None
                    else set()
                )
                if own_phrases & other_phrases:
                    violations += 1
                    checks.append(
                        TriggerCheck(
                            skill_name=header.name,
                            query=query,
                            kind="cross-negative",
                            passed=False,
                            matched_names=matched_names,
                            detail=(
                                f"positive query also matched "
                                f"{match.header.name} via the same "
                                "quoted trigger phrase (collision)"
                            ),
                        )
                    )
                else:
                    checks.append(
                        TriggerCheck(
                            skill_name=header.name,
                            query=query,
                            kind="cross-negative",
                            passed=True,
                            matched_names=matched_names,
                            detail=(
                                f"positive query also matched "
                                f"{match.header.name} via a partial cue "
                                f"('{match.cue}'); ambiguous trigger, "
                                "sharpen descriptions"
                            ),
                        )
                    )

    for query in generic_negatives:
        matches = router.match(query, max_skills=top_k)
        matched_names = tuple(match.header.name for match in matches)
        if matched_names:
            violations += 1
            checks.append(
                TriggerCheck(
                    skill_name="",
                    query=query,
                    kind="generic-negative",
                    passed=False,
                    matched_names=matched_names,
                    detail=(
                        "unrelated query matched skill(s); description "
                        "trigger cues are over-broad"
                    ),
                )
            )
        else:
            checks.append(
                TriggerCheck(
                    skill_name="",
                    query=query,
                    kind="generic-negative",
                    passed=True,
                    matched_names=(),
                    detail="no skill matched",
                )
            )

    collisions = eval_description_collisions(headers)
    violations += sum(1 for item in collisions if item.severity == "violation")
    return Tier2Result(
        passed=violations == 0,
        checks=tuple(checks),
        collisions=tuple(collisions),
        warnings=tuple(warnings),
    )


def eval_tier2_root(
    skills_root: Path, *, top_k: int = DEFAULT_TOP_K
) -> Tier2Result:
    """Tier 2 trigger eval for a skills root, plus discoverability."""
    router = SkillRouter(skills_root)
    result = eval_tier2_router(router, top_k=top_k)
    discovered = {header.name for header in router.discover()}
    warnings = list(result.warnings)
    for path in find_skill_files(skills_root):
        meta = _read_frontmatter(path)
        name = _clean(meta.get("name") or path.parent.name)
        if name and name not in discovered:
            warnings.append(
                f"{name}: present on disk but not discoverable by the "
                "router (invalid name or description over the 500-char "
                "runtime cap); Tier 1 reports the cause"
            )
    return Tier2Result(
        passed=result.passed,
        checks=result.checks,
        collisions=result.collisions,
        warnings=tuple(warnings),
    )


# --------------------------------------------------------------------------
# Combined report
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvalReport:
    """Combined Tier 1 + Tier 2 outcome for a skills root."""

    passed: bool
    tier1: tuple[Tier1Result, ...] = ()
    tier2: Tier2Result = field(default_factory=lambda: Tier2Result(passed=True))

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "tier1": [
                {
                    "path": item.path,
                    "skill_name": item.skill_name,
                    "passed": item.passed,
                    "violations": list(item.violations),
                    "warnings": list(item.warnings),
                }
                for item in self.tier1
            ],
            "tier2": {
                "passed": self.tier2.passed,
                "checks": [
                    {
                        "skill_name": item.skill_name,
                        "query": item.query,
                        "kind": item.kind,
                        "passed": item.passed,
                        "matched_names": list(item.matched_names),
                        "detail": item.detail,
                    }
                    for item in self.tier2.checks
                ],
                "collisions": [
                    {
                        "skill_a": item.skill_a,
                        "skill_b": item.skill_b,
                        "severity": item.severity,
                        "reason": item.reason,
                    }
                    for item in self.tier2.collisions
                ],
                "warnings": list(self.tier2.warnings),
            },
        }


def eval_skills_root(skills_root: Path, *, top_k: int = DEFAULT_TOP_K) -> EvalReport:
    """Run Tier 1 + Tier 2 over one skills root (deterministic)."""
    tier1 = eval_tier1_root(skills_root)
    tier2 = eval_tier2_root(skills_root, top_k=top_k)
    return EvalReport(
        passed=all(item.passed for item in tier1) and tier2.passed,
        tier1=tuple(tier1),
        tier2=tier2,
    )


__all__ = [
    "COLLISION_JACCARD",
    "DEFAULT_TOP_K",
    "GENERIC_NEGATIVES",
    "Collision",
    "EvalReport",
    "Tier1Result",
    "Tier2Result",
    "TriggerCheck",
    "eval_description_collisions",
    "eval_skills_root",
    "eval_tier1_file",
    "eval_tier1_files",
    "eval_tier1_root",
    "eval_tier2_root",
    "eval_tier2_router",
    "extract_quoted_phrases",
    "find_skill_files",
]
