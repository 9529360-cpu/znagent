from __future__ import annotations

"""Parse a user's free-text request into a team-assembly request.

Pure function, no I/O: the daemon calls this at ``work_start`` ingress so a
user sentence like "给 XX 项目组个团队" becomes a durable ``team_request``
payload instead of vanishing into the generic agent loop.

Conservative by design: a team is only assembled when the user *explicitly*
asks for one (assembly verb + project). Passing mentions of a team
("我们团队明天开会"), plain tasks ("帮我写个脚本"), and requests with no
project left after stripping the assembly phrasing all return ``None`` --
they keep the normal Work path.
"""

import re
from dataclasses import dataclass

from .project_team import ROLE_TEMPLATES

#: Roles used when the user names no roles. Research -> design -> build ->
#: test, matching the default plan chain in ``assemble_team``.
DEFAULT_ROLE_KEYS: tuple[str, ...] = (
    "researcher",
    "architect",
    "developer",
    "tester",
)

#: Assembly verbs, longest first so "组建一个团队" matches before "组".
_ASSEMBLY_PHRASES = (
    "组建一个团队",
    "组建团队",
    "组一个团队",
    "组个团队",
    "组团队",
    "assemble a team",
    "build a team",
    "form a team",
    "create a team",
    "put together a team",
    "set up a team",
)

#: Role keywords -> role key. A keyword only counts with an explicit
#: role-requesting context ("带一个测试", "with a designer") -- otherwise
#: "做一个测试项目" (a project *about* testing) would wrongly match tester.
_ROLE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("researcher", ("调研", "研究", "research")),
    ("architect", ("架构", "设计", "architect", "design")),
    ("developer", ("开发", "实现", "编码", "develop", "build", "coding", "implement")),
    ("tester", ("测试", "test", "qa", "验收")),
)

#: English profession nouns are unambiguous role words on their own
#: ("a tester", "two developers") -- unlike "test"/"design"/"build",
#: which can describe the project itself.
_ROLE_NOUNS: dict[str, str] = {
    "researcher": "researcher",
    "architect": "architect",
    "developer": "developer",
    "tester": "tester",
    "designer": "architect",
}

#: Verbs/phrases that turn a following keyword into a role request.
_ROLE_CONTEXT_VERBS = (
    "带",
    "要",
    "需要",
    "找",
    "请",
    "安排",
    "加上",
    "包括",
    "包含",
    "含",
    "配",
    "with",
    "including",
    "include",
    "add",
    "plus",
    "need",
    "needs",
    "hire",
)


@dataclass(frozen=True, slots=True)
class TeamRequest:
    """A parsed "assemble a team" request: project + ordered role keys.

    ``workspace_root`` is the specialists' file-workspace root
    (``agents/<name>/`` per member, see ``specialist_workspace``). The
    pure text parse cannot know it -- it stays None here. The daemon
    threads the field through the ``team_request`` payload, and the
    owner derives the product-path default (``<attached workspace>/agents``)
    when no explicit root is given.
    """

    project_title: str
    role_keys: tuple[str, ...]
    workspace_root: str | None = None


def _strip_assembly_phrase(task: str) -> str | None:
    """Remove the assembly phrase; None when the task asks for no team."""
    lowered = task.lower()
    for phrase in _ASSEMBLY_PHRASES:
        idx = lowered.find(phrase.lower())
        if idx < 0:
            continue
        remainder = (task[:idx] + " " + task[idx + len(phrase):]).strip()
        return remainder
    return None


def _match_roles(task: str) -> tuple[str, ...]:
    """Role keys the user explicitly asked for, in canonical plan order."""
    matched: list[str] = []
    context = "|".join(re.escape(verb) for verb in _ROLE_CONTEXT_VERBS)
    for role_key, keywords in _ROLE_KEYWORDS:
        found = False
        for keyword in keywords:
            # "带一个测试" / "with a designer": a role-requesting verb
            # within a few chars before the keyword.
            if re.search(
                rf"(?:{context})[^，。,；;,.]{{0,8}}?{re.escape(keyword)}",
                task,
                flags=re.IGNORECASE,
            ):
                found = True
                break
        if not found:
            # Bare English profession nouns ("a tester", "two developers").
            noun = _ROLE_NOUNS.get(role_key)
            if noun and re.search(
                rf"\b{re.escape(noun)}s?\b", task, flags=re.IGNORECASE
            ):
                found = True
        if found:
            matched.append(role_key)
    # Canonical plan order, not mention order: the plan chain is
    # research -> design -> build -> test regardless of how the user listed them.
    order = {key: index for index, key in enumerate(ROLE_TEMPLATES)}
    matched.sort(key=lambda key: order.get(key, len(order)))
    return tuple(matched)


def _strip_role_clauses(text: str) -> str:
    """Remove role-requesting clauses from the project title.

    "做记账 App，带一个测试" -> "做记账 App"; "the billing app with a
    designer" -> "the billing app". The roles themselves are already
    captured by ``_match_roles``; leaving the clause in the title would
    make the project name read like a staffing request.
    """
    text = re.sub(
        r"[，,；;]?\s*(?:带|要|需要|找|请|安排|加上|包括|包含|含|配)[^，。,；;]*[，,；;]?",
        "",
        text,
    )
    text = re.sub(
        r"\s*(?:with|including|include|add|plus|need|needs|hire)\s+[^,.]*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text


def _clean_project_title(remainder: str) -> str | None:
    """Project title from the text left after stripping the assembly phrase."""
    text = _strip_role_clauses(remainder.strip())
    # Drop leading prepositions / fillers left behind by the strip.
    text = re.sub(r"^(?:给|为|帮我|请|帮|for|to)\s*", "", text)
    # "assemble a team to build the dashboard" -> project "the dashboard".
    text = re.sub(
        r"^(?:build|develop|create|make|implement|work\s+on)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Drop trailing fillers.
    text = re.sub(r"(?:吧|一下|一下吧|嘛|啊|哦|呢|please|pls)[。！!？?、，,；;]*$", "", text)
    text = re.sub(r"\s+", " ", text).strip("，。,；;：:、 \t")
    if not text or len(text) > 120:
        return None
    return text


def parse_team_request(task: str) -> TeamRequest | None:
    """Parse "assemble a team for X" from free text; None when not a team ask.

    Examples that parse:
    - "给 XX 项目组个团队" -> project "XX 项目", default roles
    - "组建一个团队做记账 App，带一个测试" -> project "做记账 App", roles incl. tester
    - "assemble a team for the billing app with a designer"
      -> project "the billing app", roles incl. architect

    Examples that return None:
    - "帮我写个脚本" (no assembly verb)
    - "我们团队明天开会" (mention, no assembly verb)
    - "组个团队" (no project left)
    """
    if not task or not str(task).strip():
        return None
    remainder = _strip_assembly_phrase(str(task))
    if remainder is None:
        return None
    project = _clean_project_title(remainder)
    if project is None:
        return None
    roles = _match_roles(str(task))
    return TeamRequest(
        project_title=project,
        role_keys=roles or DEFAULT_ROLE_KEYS,
    )


__all__ = ["DEFAULT_ROLE_KEYS", "TeamRequest", "parse_team_request"]
