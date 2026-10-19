from __future__ import annotations

"""Skill-gap auto-trigger driver for the Work cognition loop (M-15, self-drive).

M-13 built the full mechanism: gap detection (``SkillStore.detect_skill_gap``),
candidate matching from already-approved plugin sources, the ``skill_acquire``
approval card, and install-only-after-approval. This module is the product
closure layer on top of that mechanism: a driver that the Work cognition loop
invokes when skill binding finds no skill for a non-empty task, and that the
team path invokes when no confirmed skill covers a specialist objective.

Flow per gap (reuses ``skill_gap.*`` verbatim; nothing is re-implemented):

    detect (SkillStore.detect_skill_gap / detect_skill_gap_from_matches)
    -> approved_plugin_entries(SkillLock)
    -> match_candidates -> build_proposal -> open_gap_approval
    on later binds:
    -> poll_gap_approval (approved -> install_approved_skill;
       denied/expired -> explicit block)

Hard rules:

- One proposal per normalized query per driver instance: a gap that is
  already proposed, blocked, denied or installed is never re-proposed and
  never opens a second card.
- Fail-closed everywhere: no approval path -> ``blocked`` proposal (never
  silent); ``install_approved_skill`` still only runs on a recorded
  approval, exactly as M-13 specified.
- The driver never raises into the cognition loop: unexpected internal
  failures degrade to a fail-closed ``blocked`` proposal, and a poll that
  cannot reach the approval store leaves the last known status for retry.
  (``poll_proposal`` itself may raise on storage errors, per M-13's
  "a broken approval store must surface as an error" contract; the
  cognition-loop entry points contain that error.)
- Proposals are advisory data for cognition: they describe a missing
  capability and a pending human decision. They never grant tool
  permission, change route policy, or prove completion -- same posture as
  the skill bundles themselves.
"""

from pathlib import Path
from typing import Any

from .skill_gap import (
    GAP_STATUS_APPROVED,
    GAP_STATUS_BLOCKED,
    GAP_STATUS_DENIED,
    GAP_STATUS_INSTALL_FAILED,
    GAP_STATUS_INSTALLED,
    GAP_STATUS_NO_CANDIDATE,
    GAP_STATUS_PROPOSED,
    SkillGap,
    SkillGapProposal,
    approved_plugin_entries,
    build_proposal,
    detect_skill_gap_from_matches,
    install_approved_skill,
    match_candidates,
    open_gap_approval,
    poll_gap_approval,
)
from .skill_lock import SkillLock

#: Cognition-context key the driver attaches its gap note under.
GAP_CONTEXT_KEY = "resident_skill_gap"

#: Statuses after which a query is never re-proposed.
_TERMINAL_STATUSES = frozenset(
    {
        GAP_STATUS_NO_CANDIDATE,
        GAP_STATUS_BLOCKED,
        GAP_STATUS_DENIED,
        GAP_STATUS_INSTALLED,
        GAP_STATUS_INSTALL_FAILED,
    }
)

_MAX_BRIEF_CHARS = 700


def _normalize_key(query: object) -> str:
    return " ".join(str(query or "").split()).casefold()


def _clean(value: object, *, limit: int = 0) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit] if limit > 0 else text


def _interpretation(proposal: SkillGapProposal) -> str:
    """One bounded, human-readable line describing what the gap means now."""
    status = proposal.status
    candidates = ", ".join(candidate.name for candidate in proposal.candidates)
    if status == GAP_STATUS_PROPOSED and proposal.approval_request_id:
        return (
            "能力缺口已自动提案并开出审批卡（skill_acquire），待人工批准。"
            "批准后自动按锁定版本安装并可用；拒绝则显式阻塞，本次 Work 按无此能力继续。"
            "安装前不联网、不购买、不自动装。"
        )
    if status == GAP_STATUS_NO_CANDIDATE:
        return (
            "能力缺口已记录：在已批准的插件来源中没有匹配候选，不联网搜索、不开卡。"
            "需人工决定是否引入新的插件来源。"
        )
    if status == GAP_STATUS_BLOCKED:
        reason = proposal.block_reason or "无可用审批通道"
        return f"能力缺口显式阻塞（fail-closed）：{reason}。本次按无此能力继续。"
    if status == GAP_STATUS_DENIED:
        return "能力缺口显式阻塞：人工已拒绝该技能提案，不再重复提案。本次按无此能力继续。"
    if status == GAP_STATUS_APPROVED:
        return "能力缺口提案已获批准，待安装。安装走 M-13 校验与锁定流程。"
    if status == GAP_STATUS_INSTALLED:
        return f"缺口技能已批准并安装：{candidates or '未知'}，现已可引用。"
    if status == GAP_STATUS_INSTALL_FAILED:
        reason = proposal.block_reason or "未知原因"
        return (
            f"缺口技能审批已通过但安装失败：{reason}。"
            "skills 目录与 lockfile 未动，可重新提案。"
        )
    return f"能力缺口状态：{status}。本次按无此能力继续。"


class SkillGapDriver:
    """Auto-trigger for skill-gap proposals inside the Work cognition loop.

    Constructed with the skill store (detection + skills root), an approval
    card store (may be None -> every proposal fail-closes to ``blocked``),
    and optional install plumbing (``fetch_skill`` is injectable for tests;
    default shells out to git, only ever called after approval).
    """

    def __init__(
        self,
        *,
        skill_store: Any | None = None,
        approval_store: Any | None = None,
        skills_root: str | Path | None = None,
        work_dir: str | Path | None = None,
        fetch_skill: Any | None = None,
    ) -> None:
        self.skill_store = skill_store
        self.approval_store = approval_store
        if skills_root is None and skill_store is not None:
            skills_root = getattr(skill_store, "root", None)
        self.skills_root = Path(skills_root) if skills_root else None
        self.work_dir = Path(work_dir) if work_dir else None
        self.fetch_skill = fetch_skill
        # Normalized query -> remembered proposal (dedupe + poll state).
        self._proposals: dict[str, SkillGapProposal] = {}

    # -- core: propose -> open card --------------------------------------

    def propose_gap(
        self, gap: SkillGap | None, *, event: Any = None
    ) -> SkillGapProposal | None:
        """Run detect -> propose -> open-card once per normalized query.

        Idempotent: a repeat query returns the remembered proposal (after
        one poll: approved -> install attempted; denied/expired -> explicit
        block). The one exception is ``no_candidate``: a repeat query
        re-runs candidate matching only, so a newly approved plugin source
        in the lockfile turns the gap into a proposal instead of staying
        silent. Never raises: unexpected failures degrade to a fail-closed
        ``blocked`` proposal; a poll that cannot reach the approval store
        leaves the last known status for the next bind to retry.
        """
        if gap is None:
            return None
        key = _normalize_key(gap.query)
        if not key:
            return None
        existing = self._proposals.get(key)
        if existing is not None:
            if existing.status == GAP_STATUS_NO_CANDIDATE:
                # A new approved plugin source may have appeared in the
                # lockfile since the last check. Re-run matching only (still
                # no network, still no card unless a candidate exists now);
                # a repeat no_candidate keeps the original proposal.
                try:
                    refreshed = self._propose(existing.gap, event=event)
                except Exception:
                    refreshed = existing
                if refreshed.status != GAP_STATUS_NO_CANDIDATE:
                    self._proposals[key] = refreshed
                    return refreshed
                return existing
            try:
                self.poll_proposal(existing)
            except Exception:
                # Last known status stands; the next bind retries the poll.
                pass
            return existing
        try:
            proposal = self._propose(gap, event=event)
        except Exception as exc:
            proposal = build_proposal(gap, [])
            proposal.status = GAP_STATUS_BLOCKED
            proposal.gap.status = GAP_STATUS_BLOCKED
            proposal.block_reason = (
                f"gap driver error (fail-closed): {type(exc).__name__}"
            )
        self._proposals[key] = proposal
        return proposal

    def _propose(self, gap: SkillGap, *, event: Any = None) -> SkillGapProposal:
        lock = SkillLock(self.skills_root) if self.skills_root is not None else None
        entries = approved_plugin_entries(lock) if lock is not None else []
        candidates = match_candidates(gap, entries)
        proposal = build_proposal(gap, candidates)
        event_id = _clean(getattr(event, "event_id", ""), limit=128) if event else ""
        return open_gap_approval(self.approval_store, proposal, event_id=event_id)

    # -- poll + install ----------------------------------------------------

    def poll_proposal(self, proposal: SkillGapProposal) -> SkillGapProposal:
        """Poll one proposal; approved -> install attempted.

        Storage errors propagate (M-13: a broken approval store must
        surface as an error, never as an eternal "still pending"); the
        cognition-loop entry points contain them.
        """
        if proposal is None or proposal.status != GAP_STATUS_PROPOSED:
            return proposal
        poll_gap_approval(self.approval_store, proposal)
        if proposal.status == GAP_STATUS_APPROVED:
            self._install(proposal)
        return proposal

    def _install(self, proposal: SkillGapProposal) -> None:
        if not proposal.candidates or self.skills_root is None:
            return
        try:
            install_approved_skill(
                proposal,
                proposal.candidates[0],
                skills_root=self.skills_root,
                fetch_skill=self.fetch_skill,
                work_dir=self.work_dir,
            )
        except Exception as exc:
            # install_approved_skill already converts expected failures to
            # install_failed; this only guards the truly unexpected.
            proposal.status = GAP_STATUS_INSTALL_FAILED
            proposal.gap.status = GAP_STATUS_INSTALL_FAILED
            proposal.block_reason = f"install error: {type(exc).__name__}"

    # -- cognition-loop entry point -----------------------------------------

    def on_skill_bind(
        self, event: Any, request: Any, *, file_path: str | Path | None = None
    ) -> Any:
        """Work cognition-loop hook.

        Called from ``SkillStore.bind_cognition_context`` when no skill
        matched the task. Detects the gap with the same matching the bind
        used, runs propose -> open-card, and attaches a bounded
        ``resident_skill_gap`` note to the request context. Never raises
        into the cognition loop.
        """
        try:
            query = getattr(event, "task", "") or ""
            store = self.skill_store
            gap = (
                store.detect_skill_gap(query, file_path=file_path, event=event)
                if store is not None
                else detect_skill_gap_from_matches(query, ())
            )
            proposal = self.propose_gap(gap, event=event)
        except Exception:
            return request
        if proposal is None:
            return request
        context = dict(getattr(request, "context", None) or {})
        context[GAP_CONTEXT_KEY] = self.render_note(proposal)
        request.context = context
        return request

    # -- rendering ------------------------------------------------------------

    def render_note(self, proposal: SkillGapProposal) -> dict[str, Any]:
        """Bounded cognition-context note for one proposal."""
        return {
            "source": "resident_skill_gap",
            "query": _clean(proposal.gap.query, limit=500),
            "status": proposal.status,
            "proposal_id": proposal.proposal_id,
            "approval_request_id": proposal.approval_request_id,
            "candidates": [candidate.name for candidate in proposal.candidates],
            "block_reason": _clean(proposal.block_reason, limit=300),
            "interpretation": _interpretation(proposal),
        }

    def render_brief_block(self, proposal: SkillGapProposal) -> str:
        """One bounded advisory block for a specialist brief (team path)."""
        query = _clean(proposal.gap.query, limit=200)
        if proposal.candidates:
            first = proposal.candidates[0]
            names = "、".join(candidate.name for candidate in proposal.candidates)
            detail = (
                f"自动提案：{names}（已批准来源，锁定版本 "
                f"{first.version or '未知'}/SHA {first.locked_sha[:12]}…）。"
            )
            status = proposal.status
            if status == GAP_STATUS_INSTALLED:
                detail += "已批准并安装，现可引用。"
            elif status == GAP_STATUS_DENIED:
                detail += "人工已拒绝，不再重复提案。"
            elif status == GAP_STATUS_INSTALL_FAILED:
                reason = proposal.block_reason or "未知原因"
                detail += f"审批已通过但安装失败：{reason}。"
            elif status == GAP_STATUS_NO_CANDIDATE:
                detail += "已批准来源中无匹配候选，未开卡。"
            elif status == GAP_STATUS_BLOCKED:
                reason = proposal.block_reason or "无可用审批通道"
                detail += f"审批通道不可用，显式阻塞：{reason}。"
            elif proposal.approval_request_id:
                detail += "审批卡已开出（skill_acquire），待人工批准。"
            else:
                detail += "待开卡。"
        else:
            detail = "自动提案：已批准来源中无匹配候选，未开卡。"
        text = (
            f"能力缺口（无确认技能覆盖此目标）：{query}。{detail}"
            "批准后自动安装并可用；拒绝/无审批通道则显式阻塞，本项按无此能力继续。"
        )
        return text[:_MAX_BRIEF_CHARS]


def build_skill_gap_driver(
    *,
    skill_store: Any | None = None,
    store: Any | None = None,
    work_dir: str | Path | None = None,
) -> SkillGapDriver:
    """Production wiring for the driver.

    The approval card store is built from the kernel store's path (the
    same pattern routine/daemon use); when no store path is reachable the
    driver is still returned and every proposal fail-closes to ``blocked``.
    """
    approval_store = None
    path = getattr(store, "path", None)
    if path:
        try:
            from .approval_cards import ApprovalCardStore

            approval_store = ApprovalCardStore(str(path))
        except Exception:
            approval_store = None
    return SkillGapDriver(
        skill_store=skill_store,
        approval_store=approval_store,
        work_dir=work_dir,
    )


__all__ = [
    "GAP_CONTEXT_KEY",
    "SkillGapDriver",
    "build_skill_gap_driver",
]
