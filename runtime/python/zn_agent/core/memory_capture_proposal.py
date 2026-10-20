from __future__ import annotations

"""Rule-based memory-capture proposals (P1-4).

Gap (IMPLEMENTATION-STATUS): "Saving/inference of preferences from arbitrary
chat is not implemented" -- memory only grows through manual ``remember`` and
goes stale. Automatic writing is unsafe, so this module adds a product closure
layer with a human decision in the middle:

    Work completes -> at most 1 candidate fact (deterministic rules, no model
    call, no token spend) -> approval card (``memory_capture``)
    -> approved -> written through the existing ``remember`` path
    -> denied/expired/ignored -> never written.

Privacy (P1-4 scope): candidate generation reuses the CM-3 privacy choke
(``strip_tags``). If the choke changes the raw candidate text in ANY way
(secret pattern, ``<private>`` block, PEM block, overlong field), the
candidate is dropped entirely -- a secret is never proposed, not even in
redacted form. The facts table is untouched: capture writes go through the
existing ``remember`` (which chokes again and runs supersession/dedup).

Hard rules:

- At most one candidate per completed Work; no signal -> ``no_candidate``,
  never a card. A second completion with the same fact reuses the remembered
  proposal instead of opening a second card.
- Fail-closed everywhere: no approval path -> ``blocked`` proposal (never
  silent); a write happens only on a recorded approval, via ``remember``.
- The driver never raises into the Work finalize path: unexpected internal
  failures degrade to a fail-closed ``blocked`` proposal, and a poll that
  cannot reach the approval store leaves the last known status for the next
  finalize to retry. (``poll_proposal`` itself may raise on storage errors,
  per the M-13 "a broken approval store must surface as an error" contract;
  the entry points contain that error.)
- Proposals are advisory data for the human: they describe one candidate
  fact and a pending decision. They never grant permission or prove anything.
"""

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .privacy_choke import strip_tags

#: Approval kind for a memory-capture candidate (registered in APPROVAL_KINDS).
APPROVAL_KIND_MEMORY_CAPTURE = "memory_capture"

#: Proposal statuses.
PROPOSAL_STATUS_NO_CANDIDATE = "no_candidate"
PROPOSAL_STATUS_BLOCKED = "blocked"
PROPOSAL_STATUS_PROPOSED = "proposed"
PROPOSAL_STATUS_APPROVED = "approved"
PROPOSAL_STATUS_WRITTEN = "written"
PROPOSAL_STATUS_DENIED = "denied"
PROPOSAL_STATUS_SUPPRESSED_SECRET = "suppressed_secret"

#: Statuses after which a fact key is never re-proposed.
_TERMINAL_STATUSES = frozenset(
    {
        PROPOSAL_STATUS_WRITTEN,
        PROPOSAL_STATUS_DENIED,
        PROPOSAL_STATUS_BLOCKED,
        PROPOSAL_STATUS_SUPPRESSED_SECRET,
    }
)

#: Deterministic preference signals. Deliberately narrow: an explicit
#: "remember this / from now on / I prefer" style statement in the run's own
#: text. Noise like "注意安全" must not become a candidate.
_PREFERENCE_SIGNAL_RE = re.compile(
    r"记住|请记住|以后|从今往后|今后|下次|偏好|我喜欢|我不喜欢|我习惯|"
    r"\bremember\b|\bprefer(?:s|red)?\b|\bfrom now on\b|\bkeep in mind\b|"
    r"\bmy preference\b|\bnote this\b",
    re.IGNORECASE,
)

_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;\n]+")

_MIN_SENTENCE_CHARS = 6
_MAX_SENTENCE_CHARS = 300
_MAX_ALIAS_CHARS = 24
_FACT_KEY_PREFIX = "memory_capture:"


def _clean(value: object, *, limit: int = 0) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit] if limit > 0 else text


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(text or "") if part.strip()]


def _choke_clean(text: str) -> bool:
    """True when the privacy choke leaves the text completely untouched."""
    try:
        return strip_tags(text) == text
    except Exception:
        # Fail closed: an unreadable text is never proposed.
        return False


@dataclass
class MemoryCaptureCandidate:
    """One deterministic candidate fact extracted from a completed Work."""

    fact_key: str
    fact_text: str
    alias: str
    source_task: str
    source_thread_id: str
    source_event_id: str


def extract_memory_capture_candidate(
    task: str,
    response: str,
    reason: str,
    *,
    thread_id: str = "",
    event_id: str = "",
) -> MemoryCaptureCandidate | None:
    """Extract at most one candidate fact from a completed Work's own text.

    The first sentence (task, then response, then reason) carrying a
    preference signal becomes the candidate. Returns None when no sentence
    carries a signal, or when the privacy choke changes the candidate text
    in any way -- a secret is never proposed.
    """
    task = _clean(task)
    for text in (task, response, reason):
        for sentence in _sentences(text or ""):
            if not (_MIN_SENTENCE_CHARS <= len(sentence) <= _MAX_SENTENCE_CHARS):
                continue
            if not _PREFERENCE_SIGNAL_RE.search(sentence):
                continue
            if not _choke_clean(sentence):
                # Secret-shaped content (or a <private> block): never propose.
                return None
            normalized = _clean(sentence.casefold())
            digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]
            fact_key = f"{_FACT_KEY_PREFIX}{digest}"
            alias = _clean(sentence, limit=_MAX_ALIAS_CHARS)
            # Provenance must not smuggle secrets into the proposal either:
            # a task that is not choke-clean is recorded without its text.
            source_task = task if task and _choke_clean(task) else ""
            return MemoryCaptureCandidate(
                fact_key=fact_key,
                fact_text=sentence,
                alias=alias if len(alias) >= 4 else "",
                source_task=source_task,
                source_thread_id=_clean(thread_id, limit=128),
                source_event_id=_clean(event_id, limit=128),
            )
    return None


@dataclass
class MemoryCaptureProposal:
    """One proposal lifecycle: candidate -> card -> (approval) -> remember."""

    proposal_id: str
    candidate: MemoryCaptureCandidate | None
    status: str = PROPOSAL_STATUS_NO_CANDIDATE
    approval_request_id: str | None = None
    block_reason: str = ""


def _new_proposal_id() -> str:
    return f"memcap-{uuid.uuid4().hex[:16]}"


def _candidate_value(candidate: MemoryCaptureCandidate) -> dict[str, Any]:
    return {
        "text": candidate.fact_text,
        "via": "memory_capture_proposal",
        "source": {
            "task": candidate.source_task,
            "thread_id": candidate.source_thread_id,
            "event_id": candidate.source_event_id,
        },
    }


def open_memory_capture_approval(
    store: Any, proposal: MemoryCaptureProposal
) -> MemoryCaptureProposal:
    """Raise the ``memory_capture`` approval card. Fail closed.

    A proposal without a candidate never opens a card. A proposal that
    already reached a decision is left untouched -- re-opening must never
    clobber a recorded decision. No approval path -> ``blocked``.
    """
    candidate = proposal.candidate
    if candidate is None:
        proposal.status = PROPOSAL_STATUS_NO_CANDIDATE
        proposal.block_reason = "no candidate fact in this Work"
        return proposal
    if proposal.status == PROPOSAL_STATUS_SUPPRESSED_SECRET:
        return proposal
    if proposal.approval_request_id and proposal.status == PROPOSAL_STATUS_PROPOSED:
        return proposal
    if proposal.status not in (PROPOSAL_STATUS_NO_CANDIDATE,):
        # Already decided or proposed: do not clobber.
        return proposal
    requester = getattr(store, "request_approval", None)
    if not callable(requester):
        proposal.status = PROPOSAL_STATUS_BLOCKED
        proposal.block_reason = "no approval path available (fail-closed)"
        return proposal
    try:
        request = requester(
            action_kind=APPROVAL_KIND_MEMORY_CAPTURE,
            target=candidate.fact_key,
            scope=f"memory-capture:{proposal.proposal_id}",
            value_text=_clean(candidate.fact_text, limit=1000),
            source="resident",
            event_id=candidate.source_event_id,
        )
    except Exception as exc:
        proposal.status = PROPOSAL_STATUS_BLOCKED
        proposal.block_reason = (
            f"approval card creation failed: {type(exc).__name__}: {exc}"
        )
        return proposal
    proposal.approval_request_id = _clean(getattr(request, "request_id", "")) or None
    if not proposal.approval_request_id:
        proposal.status = PROPOSAL_STATUS_BLOCKED
        proposal.block_reason = "approval store returned no request id"
        return proposal
    proposal.status = PROPOSAL_STATUS_PROPOSED
    proposal.block_reason = ""
    return proposal


def poll_memory_capture_approval(store: Any, proposal: MemoryCaptureProposal) -> MemoryCaptureProposal:
    """Poll the card: approved -> may write; denied/expired -> explicit block.

    Storage errors propagate: a broken approval store must surface as an
    error, never as an eternal "still pending".
    """
    if proposal.status != PROPOSAL_STATUS_PROPOSED:
        return proposal
    request_id = proposal.approval_request_id or ""
    getter = getattr(store, "get_request", None)
    if not request_id or not callable(getter):
        return proposal
    expirer = getattr(store, "expire_overdue", None)
    if callable(expirer):
        expirer()
    request = getter(request_id)
    if request is None:
        return proposal
    status = _clean(getattr(request, "status", ""))
    if status in ("approved", "approved_once"):
        proposal.status = PROPOSAL_STATUS_APPROVED
    elif status in ("denied", "expired"):
        # Explicit block: nothing is written, the candidate stays recorded.
        proposal.status = PROPOSAL_STATUS_DENIED
        proposal.block_reason = ""
    return proposal


class MemoryCaptureDriver:
    """Propose-at-completion driver for memory capture (P1-4).

    Constructed with the resident memory (``remember``/``recall``) and the
    approval card store (may be None -> every proposal fail-closes to
    ``blocked``). One driver instance remembers proposals so a repeated
    completion with the same fact never opens a second card, and later
    finalizes poll pending cards: approved -> ``remember``; denied/expired
    -> never written.
    """

    def __init__(
        self,
        *,
        memory: Any | None = None,
        approval_store: Any | None = None,
    ) -> None:
        self.memory = memory
        self.approval_store = approval_store
        # Normalized fact key -> remembered proposal (dedupe + poll state).
        self._proposals: dict[str, MemoryCaptureProposal] = {}

    # -- core: propose -> open card --------------------------------------

    def propose_from_completion(
        self,
        *,
        task: str,
        response: str,
        reason: str,
        thread_id: str = "",
        event_id: str = "",
    ) -> MemoryCaptureProposal:
        """Build at most one candidate and open its approval card.

        Idempotent per fact key: a repeat returns the remembered proposal
        (after one poll: approved -> write attempted; denied -> explicit
        block). Never raises: unexpected failures degrade to a fail-closed
        ``blocked`` proposal.
        """
        try:
            candidate = extract_memory_capture_candidate(
                task, response, reason, thread_id=thread_id, event_id=event_id
            )
        except Exception as exc:
            proposal = MemoryCaptureProposal(proposal_id=_new_proposal_id(), candidate=None)
            proposal.status = PROPOSAL_STATUS_BLOCKED
            proposal.block_reason = f"candidate extraction error (fail-closed): {type(exc).__name__}"
            return proposal
        if candidate is None:
            return MemoryCaptureProposal(proposal_id=_new_proposal_id(), candidate=None)
        existing = self._proposals.get(candidate.fact_key)
        if existing is not None:
            if existing.status not in _TERMINAL_STATUSES:
                try:
                    self.poll_proposal(existing)
                except Exception:
                    # Last known status stands; the next finalize retries.
                    pass
            return existing
        proposal = MemoryCaptureProposal(proposal_id=_new_proposal_id(), candidate=candidate)
        try:
            open_memory_capture_approval(self.approval_store, proposal)
        except Exception as exc:
            proposal.status = PROPOSAL_STATUS_BLOCKED
            proposal.block_reason = f"proposal error (fail-closed): {type(exc).__name__}"
        self._proposals[candidate.fact_key] = proposal
        return proposal

    # -- poll + write -------------------------------------------------------

    def poll_proposal(self, proposal: MemoryCaptureProposal) -> MemoryCaptureProposal:
        """Poll one proposal; approved -> write through ``remember``.

        Storage errors propagate (a broken approval store must surface as
        an error, never as an eternal "still pending"); the Work-finalize
        entry point contains them. A denied/expired card means the fact is
        NEVER written.
        """
        if proposal is None or proposal.status != PROPOSAL_STATUS_PROPOSED:
            return proposal
        poll_memory_capture_approval(self.approval_store, proposal)
        if proposal.status == PROPOSAL_STATUS_APPROVED:
            self._write(proposal)
        return proposal

    def poll_pending(self) -> list[MemoryCaptureProposal]:
        """Poll every remembered non-terminal proposal once."""
        results: list[MemoryCaptureProposal] = []
        for proposal in list(self._proposals.values()):
            if proposal.status in _TERMINAL_STATUSES | {PROPOSAL_STATUS_APPROVED}:
                results.append(proposal)
                continue
            try:
                results.append(self.poll_proposal(proposal))
            except Exception:
                # Last known status stands; the next finalize retries.
                results.append(proposal)
        return results

    def _write(self, proposal: MemoryCaptureProposal) -> None:
        candidate = proposal.candidate
        if candidate is None or self.memory is None:
            # No memory available: keep the approval and retry on the next
            # poll instead of losing a recorded human decision.
            proposal.block_reason = "no memory available for write; will retry"
            return
        try:
            aliases = (candidate.alias,) if candidate.alias else ()
            self.memory.remember(candidate.fact_key, _candidate_value(candidate), aliases=aliases)
        except Exception as exc:
            # remember() is transactional; a failure keeps the approval and
            # retries on the next poll instead of silently dropping it.
            proposal.block_reason = f"remember failed: {type(exc).__name__}"
            return
        proposal.status = PROPOSAL_STATUS_WRITTEN
        proposal.block_reason = ""

    # -- Work-finalize entry point -------------------------------------------

    def on_work_completed(
        self,
        *,
        task: str,
        response: str,
        reason: str,
        thread_id: str = "",
        event_id: str = "",
    ) -> None:
        """Work finalize hook: propose the completion's candidate, then poll.

        Called from ``ResidentWorkLedger`` finalization. Never raises into
        the finalize path.
        """
        try:
            self.propose_from_completion(
                task=task,
                response=response,
                reason=reason,
                thread_id=thread_id,
                event_id=event_id,
            )
            self.poll_pending()
        except Exception:
            return


def build_memory_capture_driver(
    *,
    store: Any | None = None,
    memory: Any | None = None,
) -> MemoryCaptureDriver:
    """Production wiring for the driver.

    The approval card store is built from the kernel store's path (the same
    pattern routine/daemon use); when no store path is reachable the driver
    is still returned and every proposal fail-closes to ``blocked``.
    """
    approval_store = None
    path = getattr(store, "path", None)
    if path:
        try:
            from .approval_cards import ApprovalCardStore

            approval_store = ApprovalCardStore(str(path))
        except Exception:
            approval_store = None
    return MemoryCaptureDriver(memory=memory, approval_store=approval_store)


__all__ = [
    "APPROVAL_KIND_MEMORY_CAPTURE",
    "PROPOSAL_STATUS_APPROVED",
    "PROPOSAL_STATUS_BLOCKED",
    "PROPOSAL_STATUS_DENIED",
    "PROPOSAL_STATUS_NO_CANDIDATE",
    "PROPOSAL_STATUS_PROPOSED",
    "PROPOSAL_STATUS_SUPPRESSED_SECRET",
    "PROPOSAL_STATUS_WRITTEN",
    "MemoryCaptureCandidate",
    "MemoryCaptureDriver",
    "MemoryCaptureProposal",
    "build_memory_capture_driver",
    "extract_memory_capture_candidate",
    "open_memory_capture_approval",
    "poll_memory_capture_approval",
]
