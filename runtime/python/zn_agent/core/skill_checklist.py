from __future__ import annotations

"""ZN Skill writing checklist — mechanical checks (KWP-1 + AS-2). ZN-owned.

This module checks a skill draft against the mechanical rules of the ZN
Skill Writing Checklist (``docs/ZN-SKILL-WRITING-CHECKLIST.md``). It is
advisory for authors: it is NOT wired into skill discovery or routing, so
it changes no runtime behaviour. ``SkillStore`` / ``SkillRouter`` keep
their own intake rules (see the checklist doc for how the two validators
relate).

Two description limits coexist, on purpose:

- Checklist ceiling (AS-2): description <= 1024 characters. Breach is a
  violation.
- ZN runtime cap: ``SkillStore`` / ``SkillRouter`` drop any skill whose
  description exceeds 500 characters. A description in (500, 1024] passes
  the checklist but gets a warning: it will not load in ZN until shortened.
  The runtime cap is intentionally NOT loosened here.

Rules split into violations (mechanical, blocking) and warnings (style /
heuristic, human judges). Style rules that cannot be decided reliably by
machine — third-person voice, imperative mood — are warnings with an
explicit heuristic, and the checklist doc gives examples plus a human
judgment method. Never treat a green validator run as proof that a skill
is well written; the human checks in the doc still apply.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

#: AS-2 checklist ceiling for the frontmatter description.
MAX_CHECKLIST_DESCRIPTION_CHARS = 1024
#: ZN runtime cap enforced by SkillStore / SkillRouter. Stricter than the
#: checklist ceiling; a description above this loads nowhere in ZN.
ZN_RUNTIME_MAX_DESCRIPTION_CHARS = 500
#: AS-2: the whole skill file must stay under 500 lines.
MAX_SKILL_LINES = 500
#: Bodies longer than this need a layer-3 References section / directory;
#: shorter bodies may carry their detail inline.
SHORT_BODY_LINES = 120
#: Prose lines longer than this get a long-sentence style warning.
LONG_SENTENCE_WORDS = 25

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
#: A quoted trigger phrase: "..." / "..." / "..." with at least 2 chars,
#: or a multi-word '...' phrase (single-quoted phrases must contain a
#: space so apostrophes like "don't" never count as trigger phrases).
_QUOTED_PHRASE_RE = re.compile(
    r'["\u201c\u201d][^"\u201d]{2,}["\u201d]|\'[^\']*\s[^\']*\''
)
#: Negation guards: a bypass pattern on a line that also carries one of
#: these is a prohibition ("Do not bypass ..."), not an instruction.
_NEGATION_RE = re.compile(
    r"\b(do not|never|don'?t|must not|cannot)\b|禁止|不许|不得|不要|切勿",
    re.IGNORECASE,
)
#: Bypass / circumvention instructions. Matched line by line; a line that
#: also matches _NEGATION_RE is skipped (it forbids the bypass).
_BYPASS_PATTERNS = (
    re.compile(
        r"\b(bypass|circumvent|work\s+around|go\s+around)\b.{0,40}"
        r"\b(check|guard|approval|validation|test|gate|review|policy)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(disable|turn\s+off|switch\s+off|skip|ignore|suppress)\b.{0,40}"
        r"\b(the\s+)?(approval|check|guard|validation|test|gate|review)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(delete|remove)\b.{0,30}\b(the\s+)?(test|assertion|check)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(mark|report|label)\b.{0,30}\b(as\s+)?(passed|passing|green|success)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(do\s+not|don'?t|never)\s+run\b.{0,30}\b(the\s+)?(tests?|checks?|validation)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(hardcode|hard-code|fake|fabricate|stub\s+out)\b.{0,40}"
        r"\b(pass|success|green|result)\b",
        re.IGNORECASE,
    ),
    # Chinese bypass instructions.
    re.compile(r"(绕过|跳过|规避|禁用|关闭|关掉).{0,10}(测试|检查|审批|校验|门禁|审查)"),
    re.compile(r"(删除|删掉|去掉).{0,10}(测试|断言|检查)"),
    re.compile(r"(假装|谎称|伪造).{0,10}(通过|成功|已完成)"),
    re.compile(r"(不用|不要|不必).{0,10}(跑|执行|运行).{0,10}(测试|检查)"),
)
#: Instructions that claim authority over the system prompt. Always a
#: violation, even without a negation guard elsewhere in the file.
_AUTHORITY_PATTERNS = (
    re.compile(
        r"\b(ignore|disregard|override|forget)\b.{0,30}"
        r"\b(system|previous|earlier|original)\b.{0,20}\binstructions?\b",
        re.IGNORECASE,
    ),
    re.compile(r"(忽略|无视|推翻).{0,10}(系统|之前|原有).{0,10}(指令|提示词)"),
)
_FIRST_PERSON_START_RE = re.compile(r"^(i|we|my|our)\b", re.IGNORECASE)


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


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


def _is_prose_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith(("#", "-", "*", ">", "|", "```", "1.", "2.", "3.")):
        return False
    if re.match(r"^\d+[.)]\s", stripped):
        return False
    if stripped.startswith(("[", "(", "`")):
        return False
    return True


@dataclass(frozen=True, slots=True)
class ChecklistResult:
    """Outcome of :func:`check_skill_writing`.

    ``passed`` is True only when there are no violations. Warnings never
    block, but the author must disposition each one (fix it or record in
    the PR why it is acceptable). ``layers`` reports which of the three
    progressive-disclosure layers were found.
    """

    passed: bool
    violations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    layers: dict[str, bool] = field(default_factory=dict)


def check_skill_writing(
    text: str, *, skill_dir: Path | None = None
) -> ChecklistResult:
    """Check one skill file's text against the mechanical checklist rules."""
    violations: list[str] = []
    warnings: list[str] = []

    lines = text.splitlines()
    if len(lines) >= MAX_SKILL_LINES:
        violations.append(
            f"skill file has {len(lines)} lines, must stay under "
            f"{MAX_SKILL_LINES} lines (AS-2)"
        )

    meta, body = _split_frontmatter(text)
    if not meta:
        violations.append("missing or unparsable YAML frontmatter")
        return ChecklistResult(
            passed=False,
            violations=tuple(violations),
            warnings=tuple(warnings),
            layers={"layer1_description": False, "layer2_body": False, "layer3_references": False},
        )

    name = _clean(meta.get("name") or "")
    if not name or not _NAME_RE.match(name):
        violations.append("frontmatter 'name' is missing or not a valid skill name")

    description = _clean(meta.get("description") or "")
    if not description:
        violations.append("frontmatter 'description' is missing")
    else:
        if len(description) > MAX_CHECKLIST_DESCRIPTION_CHARS:
            violations.append(
                f"description has {len(description)} characters, must stay "
                f"within {MAX_CHECKLIST_DESCRIPTION_CHARS} (AS-2)"
            )
        elif len(description) > ZN_RUNTIME_MAX_DESCRIPTION_CHARS:
            warnings.append(
                f"description has {len(description)} characters: passes the "
                f"checklist ceiling ({MAX_CHECKLIST_DESCRIPTION_CHARS}) but "
                f"exceeds the ZN runtime cap "
                f"({ZN_RUNTIME_MAX_DESCRIPTION_CHARS}); SkillStore / "
                "SkillRouter will drop this skill until it is shortened"
            )
        if not _QUOTED_PHRASE_RE.search(description):
            violations.append(
                "description has no quoted trigger phrase (KWP-1): put the "
                'exact trigger words in quotes, e.g. "fix flaky test"'
            )
        if _FIRST_PERSON_START_RE.match(description) or description.startswith(
            ("我", "咱们", "我们")
        ):
            warnings.append(
                "description starts in first person; use third person "
                "(describe the skill, not the author)"
            )

    body = body.strip()
    if not body:
        violations.append("skill body is empty")

    # Layer 3: a References section in the body, or a references/ directory.
    has_references_section = bool(
        re.search(r"^#{1,3}\s+references\b", body, re.IGNORECASE | re.MULTILINE)
    )
    has_references_dir = False
    if skill_dir is not None:
        references_dir = Path(skill_dir) / "references"
        has_references_dir = references_dir.is_dir() and any(
            item.is_file() for item in references_dir.iterdir()
        )
    layer3 = has_references_section or has_references_dir
    body_lines = body.splitlines()
    if body and len(body_lines) > SHORT_BODY_LINES and not layer3:
        warnings.append(
            f"body has {len(body_lines)} lines but no layer-3 References "
            f"section or references/ directory; move detail that does not "
            f"fit inline into references/ (progressive disclosure, KWP-1)"
        )

    # Bypass / authority language, line by line.
    for line in body_lines:
        stripped = line.strip()
        if not stripped:
            continue
        for pattern in _AUTHORITY_PATTERNS:
            if pattern.search(stripped):
                violations.append(
                    f"red-flag authority claim (AS-2): {stripped[:120]}"
                )
                break
        else:
            if _NEGATION_RE.search(stripped):
                continue
            for pattern in _BYPASS_PATTERNS:
                if pattern.search(stripped):
                    violations.append(
                        "bypass instruction (AS-2, write the procedure not "
                        f"the workaround): {stripped[:120]}"
                    )
                    break

    # Style heuristics (warnings only): long prose lines, first-person body.
    long_lines = sum(
        1
        for line in body_lines
        if _is_prose_line(line) and len(line.split()) > LONG_SENTENCE_WORDS
    )
    if long_lines:
        warnings.append(
            f"{long_lines} prose line(s) exceed {LONG_SENTENCE_WORDS} words; "
            "keep body sentences short and imperative (KWP-1)"
        )
    first_person_lines = sum(
        1
        for line in body_lines
        if _is_prose_line(line) and _FIRST_PERSON_START_RE.match(line.strip())
    )
    if first_person_lines:
        warnings.append(
            f"{first_person_lines} body line(s) start in first person; "
            "prefer imperative mood ('Run ...', 'Check ...')"
        )

    layers = {
        "layer1_description": bool(description),
        "layer2_body": bool(body),
        "layer3_references": layer3,
    }
    return ChecklistResult(
        passed=not violations,
        violations=tuple(violations),
        warnings=tuple(warnings),
        layers=layers,
    )


def check_skill_file(path: Path) -> ChecklistResult:
    """Check one skill file on disk (references/ dir resolved from parent)."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ChecklistResult(
            passed=False,
            violations=("skill file is missing or not valid UTF-8",),
            layers={
                "layer1_description": False,
                "layer2_body": False,
                "layer3_references": False,
            },
        )
    return check_skill_writing(text, skill_dir=path.parent)


__all__ = [
    "MAX_CHECKLIST_DESCRIPTION_CHARS",
    "ZN_RUNTIME_MAX_DESCRIPTION_CHARS",
    "MAX_SKILL_LINES",
    "ChecklistResult",
    "check_skill_file",
    "check_skill_writing",
]
