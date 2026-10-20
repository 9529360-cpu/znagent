from __future__ import annotations

"""Proactive skill proposals (P1-5).

Gap: P1-3 only saves a skill when the user explicitly says "存成技能".
Tasks that pass the CP-3 completion verdict a second time are the most
worth saving, but nothing ever triggers on them. This module closes that
loop with a human decision still in the middle:

    verified completion -> count this task shape (durable counter)
    -> 2nd verified completion -> build a skill DRAFT (inert)
    -> user-facing proposal in the work thread
    -> user confirms via the existing ``skill_confirm`` flow -> active
    -> user declines/ignores -> the draft stays a draft (never active)

Hard rules:

- The task shape is fingerprinted deterministically (normalized task +
  objective + sorted acceptance criteria): "same task shape" is a hash
  comparison, never a model judgment.
- The counter lives in the kernel DB, so it survives restarts.
- Nothing is ever auto-saved: the proposal only creates a draft; only a
  human ``skill_confirm`` (``SkillOwner``) activates it.
- A fingerprint is proposed at most once: proposed / confirmed / declined
  all suppress re-proposals. A pending unconfirmed draft with the same
  name also suppresses a new proposal ("同名未确认草稿不重复提案").
- The driver never raises into the completion gate: unexpected failures
  degrade to a non-proposing outcome, never a broken acceptance.
"""

import hashlib
import json
import unicodedata
import uuid
from contextlib import closing
from dataclasses import dataclass
from typing import Any

from .models import utc_now
from .skill_ledger import (
    STATUS_ACTIVE,
    STATUS_DRAFT,
    SkillLedger,
    SkillRecord,
    build_skill_draft,
    clean_skill_name,
)

#: Proposal states persisted per task fingerprint.
PROPOSAL_STATE_NONE = "none"
PROPOSAL_STATE_PROPOSED = "proposed"
PROPOSAL_STATE_CONFIRMED = "confirmed"
PROPOSAL_STATE_DECLINED = "declined"

#: Verified completions required before the first proposal.
PROPOSAL_THRESHOLD = 2

_FINGERPRINT_PREFIX = "taskfp:"


def _normalize_shape(value: object) -> str:
    """Normalize one shape component for fingerprinting.

    NFKC + casefold + whitespace collapse, so "汇总 进展" and "汇总进展"
    do not count as the same shape, but full/half-width and case variants
    do not fork the counter either.
    """
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(text.split())


def task_fingerprint(
    *,
    task: str,
    objective: str,
    acceptance_criteria: list[str] | tuple[str, ...] | None,
) -> str:
    """Deterministic fingerprint of one task shape.

    Normalized task + objective + sorted non-empty acceptance criteria,
    hashed with sha256. Two completions share a fingerprint exactly when
    their task shapes match; no model judgment is involved.
    """
    parts = [_normalize_shape(task), _normalize_shape(objective)]
    criteria = sorted(
        {
            _normalize_shape(item)
            for item in (acceptance_criteria or [])
            if _normalize_shape(item)
        }
    )
    parts.extend(criteria)
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:32]
    return f"{_FINGERPRINT_PREFIX}{digest}"


@dataclass(slots=True)
class SkillProposalOutcome:
    """What one verified completion did for skill proposals."""

    fingerprint: str
    verified_count: int
    proposed: bool
    record: SkillRecord | None = None
    user_text: str = ""
    reason: str = ""


class SkillProposalDriver:
    """Count verified completions per task shape; propose a draft on #2.

    Constructed with the kernel store. ``on_verified_completion`` is the
    only entry the completion gates call; ``decline_proposal`` records an
    explicit human decline.
    """

    def __init__(self, *, store: Any) -> None:
        self.store = store
        self.skills = SkillLedger(store)

    # -- main entry ------------------------------------------------------

    def on_verified_completion(
        self,
        *,
        task: str,
        objective: str,
        acceptance_criteria: list[str] | tuple[str, ...] | None,
        response: str,
        thread_id: str,
        event_id: str,
    ) -> SkillProposalOutcome:
        """Record one CP-3 verified completion; propose on the 2nd.

        Never raises: the completion gate must not break because a
        proposal failed.
        """
        try:
            return self._record_and_maybe_propose(
                task=task,
                objective=objective,
                acceptance_criteria=acceptance_criteria,
                response=response,
                thread_id=thread_id,
                event_id=event_id,
            )
        except Exception as exc:
            return SkillProposalOutcome(
                fingerprint="",
                verified_count=0,
                proposed=False,
                reason=(
                    "proposal driver error, completion unaffected "
                    f"(fail-closed): {type(exc).__name__}: {exc}"
                ),
            )

    def _record_and_maybe_propose(
        self,
        *,
        task: str,
        objective: str,
        acceptance_criteria: list[str] | tuple[str, ...] | None,
        response: str,
        thread_id: str,
        event_id: str,
    ) -> SkillProposalOutcome:
        fingerprint = task_fingerprint(
            task=task, objective=objective, acceptance_criteria=acceptance_criteria
        )
        count = self.store.record_verified_task_completion(fingerprint)
        state = self.store.get_skill_proposal_state(fingerprint)
        state_name = str((state or {}).get("proposal_state") or PROPOSAL_STATE_NONE)

        # Lazy refresh: the confirm happens in a later user message through
        # the existing SkillOwner flow, so a "proposed" row whose skill is
        # now active becomes "confirmed" here -- never re-proposed.
        if state_name == PROPOSAL_STATE_PROPOSED:
            skill_id = str((state or {}).get("proposal_skill_id") or "")
            skill = self.skills.get_skill(skill_id) if skill_id else None
            if skill is not None and skill.status == STATUS_ACTIVE:
                self.store.set_skill_proposal_state(
                    fingerprint, state=PROPOSAL_STATE_CONFIRMED, skill_id=skill.skill_id
                )
                state_name = PROPOSAL_STATE_CONFIRMED

        if count < PROPOSAL_THRESHOLD or state_name != PROPOSAL_STATE_NONE:
            return SkillProposalOutcome(
                fingerprint=fingerprint,
                verified_count=count,
                proposed=False,
                reason=(
                    "verified completion counted "
                    f"(#{count} for this task shape); "
                    + (
                        "proposal already handled "
                        f"(state={state_name}), not re-proposed"
                        if state_name != PROPOSAL_STATE_NONE
                        else "proposal triggers on the 2nd verified completion"
                    )
                ),
            )

        # Second verified completion, no prior proposal: build the draft.
        source = {
            "task": str(task or ""),
            "objective": str(objective or ""),
            "acceptance_criteria": [str(item) for item in (acceptance_criteria or [])],
            "response": str(response or ""),
            "event_id": str(event_id or ""),
            "thread_id": str(thread_id or ""),
        }
        base_name = clean_skill_name(build_skill_draft(source).name)
        if not base_name:
            base_name = f"技能-{uuid.uuid4().hex[:6]}"

        # "同名未确认草稿不重复提案": a pending draft with the same name
        # (e.g. hand-made via P1-3, or this fingerprint's own earlier
        # proposal) means the human already has this proposal in front of
        # them -- adopt it as this fingerprint's proposal and do not open
        # a second one.
        pending = self.skills.get_skill_by_name(base_name, status=STATUS_DRAFT)
        if pending is not None:
            self.store.set_skill_proposal_state(
                fingerprint, state=PROPOSAL_STATE_PROPOSED, skill_id=pending.skill_id
            )
            return SkillProposalOutcome(
                fingerprint=fingerprint,
                verified_count=count,
                proposed=False,
                reason=(
                    f"a draft named {base_name!r} is already pending "
                    "confirmation; not re-proposed"
                ),
            )
        # A hand-confirmed active skill with the same name also ends the
        # story: the skill already exists and is referenceable.
        active = self.skills.get_skill_by_name(base_name, status=STATUS_ACTIVE)
        if active is not None:
            self.store.set_skill_proposal_state(
                fingerprint, state=PROPOSAL_STATE_CONFIRMED, skill_id=active.skill_id
            )
            return SkillProposalOutcome(
                fingerprint=fingerprint,
                verified_count=count,
                proposed=False,
                reason=(
                    f"an active skill named {base_name!r} already exists; "
                    "not re-proposed"
                ),
            )

        draft = build_skill_draft(source)
        draft.name = self._unique_name(base_name)
        draft.source_thread_id = str(thread_id or "")
        self.skills.save_draft(draft)
        self.store.set_skill_proposal_state(
            fingerprint, state=PROPOSAL_STATE_PROPOSED, skill_id=draft.skill_id
        )
        return SkillProposalOutcome(
            fingerprint=fingerprint,
            verified_count=count,
            proposed=True,
            record=draft,
            user_text=self._proposal_text(draft, fingerprint=fingerprint),
            reason="2nd verified completion of this task shape; draft proposed",
        )

    # -- decline -----------------------------------------------------------

    def decline_proposal(self, skill_id: str) -> bool:
        """Record an explicit human decline: the draft is deleted and the
        fingerprint is marked declined so it is never re-proposed.

        Returns True when a proposed draft was declined.
        """
        normalized = str(skill_id or "").strip()
        if not normalized:
            return False
        record = self.skills.get_skill(normalized)
        if record is None or record.status != STATUS_DRAFT:
            return False
        fingerprint = self.store.find_proposal_fingerprint_for_skill(normalized)
        self.skills.delete_skill(normalized)
        if fingerprint:
            self.store.set_skill_proposal_state(
                fingerprint, state=PROPOSAL_STATE_DECLINED, skill_id=normalized
            )
        return True

    # -- helpers -----------------------------------------------------------

    def _unique_name(self, base: str) -> str:
        candidate = clean_skill_name(base) or f"技能-{uuid.uuid4().hex[:6]}"
        suffix = 2
        while self.skills.get_skill_by_name(candidate) is not None:
            candidate = clean_skill_name(f"{base}-{suffix}")
            suffix += 1
        return candidate

    @staticmethod
    def _proposal_text(draft: SkillRecord, *, fingerprint: str) -> str:
        rendered = SkillLedger.render_for_cognition(draft)
        return (
            "这类任务你已经是第 2 次验证通过了，要不要把它存成技能？\n"
            f"（任务指纹 {fingerprint}，同形态任务再次完成不会重复打扰你）\n\n"
            f"{rendered}\n\n"
            f"回复「确认保存技能」即可入库，之后团队专员和 /{draft.name} 都能引用；"
            "草稿未确认前不会生效。忽略它就好，不想要也可以直接删掉这条草稿。"
        )


def propose_skill_for_verified_completion(
    *,
    store: Any,
    ledger: Any,
    task: str,
    objective: str,
    acceptance_criteria: list[str] | tuple[str, ...] | None,
    response: str,
    thread_id: str,
    event_id: str,
) -> SkillProposalOutcome:
    """One-call entry for the CP-3 completion gates (P1-5).

    Counts the verified completion for the task shape; on the 2nd
    verified completion saves an inert skill draft and appends the
    proposal text to the work thread. Never raises: the gates that call
    this must not break because a proposal failed.
    """
    try:
        driver = SkillProposalDriver(store=store)
        outcome = driver.on_verified_completion(
            task=task,
            objective=objective,
            acceptance_criteria=acceptance_criteria,
            response=response,
            thread_id=thread_id,
            event_id=event_id,
        )
        if outcome.proposed and outcome.user_text:
            append_proposal_message(
                ledger, thread_id=thread_id, event_id=event_id, text=outcome.user_text
            )
        return outcome
    except Exception as exc:
        return SkillProposalOutcome(
            fingerprint="",
            verified_count=0,
            proposed=False,
            reason=(
                "skill proposal entry error, completion unaffected "
                f"(fail-closed): {type(exc).__name__}: {exc}"
            ),
        )


def append_proposal_message(
    ledger: Any, *, thread_id: str, event_id: str, text: str
) -> bool:
    """Append the proposal text to the work thread (best-effort).

    Returns True when the message row was written. Never raises: the
    callers contain every failure so a surfacing problem cannot break the
    completion gate. The draft itself is already durable, so a lost
    message only loses the nudge, never the proposal.
    """
    normalized_thread = str(thread_id or "").strip()
    normalized_text = str(text or "").strip()
    if not normalized_thread or not normalized_text:
        return False
    try:
        connect = getattr(ledger, "_connect", None)
        lock = getattr(ledger, "_lock", None)
        if not callable(connect):
            return False
        message_id = f"{str(event_id or 'evt').strip() or 'evt'}-skill-proposal"
        row = (
            message_id,
            normalized_thread,
            "zn",
            normalized_text,
            json.dumps(
                {"kind": "skill_proposal", "via": "skill_proposal"},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            utc_now(),
        )
        if lock is not None:
            with lock, closing(connect()) as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO work_messages(
                        message_id, thread_id, role, text, detail_json, created_at
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    row,
                )
                conn.commit()
        else:
            with closing(connect()) as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO work_messages(
                        message_id, thread_id, role, text, detail_json, created_at
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    row,
                )
                conn.commit()
        return True
    except Exception:
        return False


__all__ = [
    "PROPOSAL_STATE_CONFIRMED",
    "PROPOSAL_STATE_DECLINED",
    "PROPOSAL_STATE_NONE",
    "PROPOSAL_STATE_PROPOSED",
    "PROPOSAL_THRESHOLD",
    "SkillProposalDriver",
    "SkillProposalOutcome",
    "append_proposal_message",
    "propose_skill_for_verified_completion",
    "task_fingerprint",
]
