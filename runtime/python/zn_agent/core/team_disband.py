from __future__ import annotations

import re

"""P3-8: execute ``DisbandPlan`` for real in the resident loop.

Before this slice, ``DisbandPlan`` only *computed* the deletion scope --
nothing ever deleted anything. This module is the executor: given a
team id, it deletes every scope item (plan tasks, team journal, team
memory, project-thread content) against the real ledger + memory, then
re-reads each scope and only reports success when the verification
passes. The resident delivers the returned checklist as the disband
event's final response, so the owner can check it afterwards.

Deletion shape (why the thread row survives):

* The project thread's *content* is deleted: all WorkItems except the
  disband event's own Root, all messages except the disband request,
  all artifact rows, all work_run rows except the disband event's.
* The thread *row* itself survives as the checklist carrier. Deleting
  it would destroy the only channel that delivers the cleanup
  checklist (``work.py`` finalizes an event by appending its response
  to the thread). After disband the thread holds the disband request
  + the checklist (+ the one activity note the work layer appends on
  finalize) -- nothing else.
* The work_plan_state counter row is intentionally kept: it is a
  thread-level version counter, not team content, and the disband
  event's own completion still reads it.
* Workspace files and browser logins are NEVER touched: they are the
  user's own state on their own computer. The checklist always carries
  ``SHARED_FILES_REMINDER`` so the owner knows to clean them by hand.

Failure semantics: validation (unknown thread / no team state) raises
*before* deleting anything. Verification runs *before* memory deletion,
so a failed verification leaves the spec + plan map in memory and a
re-issued disband can retry with full evidence. The user's disband
instruction is the confirmation -- no second prompt, ever.
"""

from dataclasses import dataclass
from typing import Any

from .project_team import (
    SHARED_FILES_REMINDER,
    assemble_team,
    team_journal_role_prefix,
    team_memory_prefix,
)
from .team_memory import delete_team_memory, team_shared_memory
from .team_runner import TeamRunner
from .team_timeline import parse_team_role
from .team_work_owner import TEAM_SPEC_KEY

# Verb-first / 把-form disband phrasings. Noun-first statements ("团队解散了",
# "他们团队解散了") are NOT instructions and must not match: the verb has to
# come first ("解散团队") or ride a 把-form ("把团队解散").
_DISBAND_PHRASES = (
    "解散这支团队",
    "解散这个团队",
    "解散团队",
    "解散掉团队",
    "把这支团队解散",
    "把这个团队解散",
    "把团队解散",
    "把这支团队删掉",
    "把这个团队删掉",
    "把团队删掉",
    "删除这支团队",
    "删除这个团队",
    "删除团队",
    "删掉团队",
    "disband the team",
    "disband this team",
    "delete the team",
    "dissolve the team",
    "remove the team",
)

#: Negation guard: "不要解散团队" / "别把团队解散" must NEVER disband.
#: Disbanding is irreversible, so a negation anywhere near the verb wins.
_NEGATION_RE = re.compile(r"不要|别把|别解散|禁止解散|勿解散")


@dataclass(frozen=True, slots=True)
class DisbandRequest:
    """A user's explicit instruction to disband the team in this thread."""

    text: str = ""


def parse_disband_request(task: str) -> DisbandRequest | None:
    """Parse an explicit disband instruction; None when not a disband ask.

    Conservative by design, mirroring ``parse_team_request``: only an
    explicit instruction matches. Bare "解散" (could be a meeting),
    noun-first statements ("团队解散了"), and plain tasks return None.
    """
    if not task or not str(task).strip():
        return None
    lowered = str(task).lower()
    if _NEGATION_RE.search(lowered):
        return None
    for phrase in _DISBAND_PHRASES:
        if phrase in lowered:
            return DisbandRequest(text=str(task).strip())
    return None


def handles_disband(event: Any) -> bool:
    """True when the event carries a daemon-parsed disband request."""
    payload = getattr(event, "payload", None)
    if not isinstance(payload, dict):
        return False
    request = payload.get("disband_request")
    if not isinstance(request, dict):
        return False
    return bool(str(request.get("team_id") or "").strip())


def find_team_id_in_messages(messages: Any) -> str | None:
    """The team id behind a thread's journal, newest first. None if no team."""
    for message in reversed(list(messages or [])):
        parsed = parse_team_role(getattr(message, "role", None))
        if parsed is not None:
            return parsed[0]
    return None
