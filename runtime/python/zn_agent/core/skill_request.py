from __future__ import annotations

"""Parse skill commands from a user's free-text message at work_start ingress.

Pure functions, no I/O -- the daemon calls these the same way it calls
``parse_team_request``: a user sentence becomes durable ingress metadata
instead of vanishing into the generic agent loop.

Conservative by design:
- "存成技能" only counts as a save request when the user is *asking* to
  save ("把刚才的任务存成技能"), not asking how ("怎么把任务存成技能").
- A bare "/name" with nothing after it is not a skill reference: there is
  no task left to run with the skill.
- A bare "确认" is handled by the owner (single pending draft in the same
  thread), not here -- this module only recognizes explicit confirm
  phrases, so a stray "确认" to something else never confirms a skill.
"""

import re
from typing import Any

#: Save-as-skill phrases, longest first.
_SAVE_PHRASES = (
    "保存成技能",
    "存成技能",
    "保存为技能",
    "存为技能",
    "save as a skill",
    "save as skill",
)

#: Explicit confirm phrases (bare "确认" is owner-level, see above).
_CONFIRM_PHRASES = (
    "确认保存技能",
    "确认存成技能",
    "确认保存",
    "确认入库",
    "confirm save skill",
    "confirm skill",
)

#: "how do I ..." markers that turn a save phrase into a question, not a command.
_HOW_MARKERS = ("怎么", "如何", "怎样", "how to", "how do", "how can")

#: Name hints: "存成技能，命名为X" / "save as skill, call it X".
_NAME_HINT_PATTERNS = (
    r"(?:命名为|名字叫|名称为|叫)\s*([^\s，。,；;：:、/]{1,64})",
    r"(?:name it|call it)\s*([^\s,.!?:;/]{1,64})",
)

_REFERENCE_RE = re.compile(r"^\s*/([^\s/]{1,64})\s+(.+?)\s*$")


def parse_skill_save_request(task: str) -> dict[str, Any] | None:
    """Parse "save this task as a skill" from free text; None when not a save ask.

    Examples that parse:
    - "把刚才的任务存成技能" -> {"name_hint": None}
    - "存成技能，命名为周报汇总" -> {"name_hint": "周报汇总"}

    Examples that return None:
    - "技能怎么存" (a how-to question, not a command)
    - "帮我写个脚本" (no save phrase)
    """
    if not task or not str(task).strip():
        return None
    text = str(task)
    lowered = text.lower()
    if any(marker in lowered for marker in _HOW_MARKERS):
        return None
    if not any(phrase.lower() in lowered for phrase in _SAVE_PHRASES):
        return None
    name_hint: str | None = None
    for pattern in _NAME_HINT_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            name_hint = match.group(1).strip("，。,；;：:、.!? ")
            break
    return {"name_hint": name_hint}


def parse_skill_reference(task: str) -> dict[str, Any] | None:
    """Parse a leading "/skill-name <task>" reference; None when not one.

    Examples that parse:
    - "/周报汇总 帮我汇总昨天的进展" -> name "周报汇总", remainder "帮我汇总昨天的进展"

    Examples that return None:
    - "/周报汇总" (no task left to run)
    - "帮我写个脚本" (no leading slash)
    """
    if not task or not str(task).strip():
        return None
    match = _REFERENCE_RE.match(str(task))
    if not match:
        return None
    name = match.group(1).strip()
    remainder = match.group(2).strip()
    if not name or not remainder:
        return None
    return {"name": name, "remainder": remainder}


def parse_skill_confirm(task: str) -> bool:
    """True when the message explicitly confirms saving a skill.

    Bare "确认" is intentionally NOT matched here -- the owner only treats
    it as a confirm when exactly one draft is pending in the same thread.
    """
    if not task or not str(task).strip():
        return False
    lowered = str(task).lower()
    return any(phrase.lower() in lowered for phrase in _CONFIRM_PHRASES)


__all__ = ["parse_skill_save_request", "parse_skill_reference", "parse_skill_confirm"]
