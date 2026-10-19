from __future__ import annotations

"""Skill-gap proposals: detect a missing capability at Work time, propose an
acquisition from an already-approved plugin source, and install only after a
human approves the proposal (M-13, self-drive: "缺什么、找什么、批了再装").

Why this exists: when the capability a Work needs is not in Action Fabric or
any Skill, ZN today just fails (or silently continues without the skill).
The nightly plugin check is a scheduled external job, not a runtime gap
response. This module closes the runtime loop:

    Work needs capability -> SkillRouter says no_skill
    -> detect_skill_gap() records the gap
    -> match_candidates() searches ONLY already-approved plugin sources
       (external, pinned lockfile entries -- never a fresh network search)
    -> build_proposal() explains what is missing, what would be installed,
       and the risk
    -> open_gap_approval() raises an approval card (kind ``skill_acquire``);
       without approval nothing is fetched, bought, or installed
    -> poll_gap_approval(): approved -> install_approved_skill() fetches the
       plugin at its pinned SHA, runs the existing skill validation, and
       records the install in the lockfile; denied/expired -> explicitly
       blocked, nothing installed

Hard rules (the spec's non-goals are load-bearing here):
- No network access in the detect/propose path. Candidate plugins come only
  from the lockfile's already-approved external entries. A gap with no
  approved candidate ends as ``no_candidate``: the proposal says so and no
  card is opened, because there is nothing concrete to approve.
- No purchase, no auto-install: ``install_approved_skill`` refuses to run
  unless the proposal's approval was recorded as approved.
- No new approval semantics: the card reuses ``ApprovalCardStore`` and the
  new ``skill_acquire`` kind (see ``approval_cards.APPROVAL_KINDS``); the
  M-7 "per-tool explicit approval" contract is the model, and the M-12
  ``team_assembly`` card is the pattern for open/poll.
- Installation goes through the existing gates: ``validate_skill_file``
  (external skills additionally require a recorded human review,
  ``reviewed: true`` + ``reviewed_by``) and the lockfile pin machinery.
  A pinned skill that already exists refuses an overwriting change.

This module is stdlib-only apart from ``.models.utc_now`` so the logic
stays cheap to import; the default fetcher shells out to ``git`` (only ever
called after approval).
"""

import re
import shutil
import subprocess
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .models import utc_now
from .skill_lock import LockEntry, SkillLock, SkillLockedError, content_sha256
from .skill_routing import RouteResult, SkillRouter, validate_skill_file

#: Approval kind for a skill-acquisition proposal card.
#: Registered in ``approval_cards.APPROVAL_KINDS`` (M-13).
APPROVAL_KIND_SKILL_ACQUIRE = "skill_acquire"

#: Proposal lifecycle. ``blocked`` = fail-closed (no approval path);
#: ``denied`` = the human said no (explicit block, nothing installed).
GAP_STATUS_PROPOSED = "proposed"
GAP_STATUS_NO_CANDIDATE = "no_candidate"
GAP_STATUS_APPROVED = "approved"
GAP_STATUS_DENIED = "denied"
GAP_STATUS_BLOCKED = "blocked"
GAP_STATUS_INSTALLED = "installed"
GAP_STATUS_INSTALL_FAILED = "install_failed"

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_FETCH_TIMEOUT_SECONDS = 120


def _clean(value: object, *, limit: int = 0) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit] if limit > 0 else text


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    normalized = re.sub(r"[\W_]+", " ", normalized)
    return " ".join(normalized.split())


def _name_cues(name: str) -> tuple[str, ...]:
    """Conservative match cues from a plugin name: tokens of length >= 3."""
    tokens = [token for token in re.split(r"[\W_]+", _normalize(name)) if len(token) >= 3]
    seen: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.append(token)
    return tuple(seen)


@dataclass(slots=True)
class SkillGap:
    """A capability the Work needs that no Skill covers."""

    gap_id: str
    query: str
    router_message: str = ""
    event_id: str = ""
    work_thread_id: str = ""
    detected_at: str = field(default_factory=utc_now)
    status: str = GAP_STATUS_PROPOSED


@dataclass(slots=True)
class PluginCandidate:
    """One already-approved plugin that could fill the gap.

    ``source`` is an approved source from the lockfile (``git+https://…``);
    ``locked_sha`` is the full 40-hex SHA the install would pin to.
    """

    name: str
    source: str
    locked_sha: str
    version: str = ""
    risk_notes: tuple[str, ...] = ()


@dataclass(slots=True)
class SkillGapProposal:
    """The acquisition proposal: what is missing, what would be installed,
    and the risk -- for a human to approve or deny."""

    proposal_id: str
    gap: SkillGap
    candidates: tuple[PluginCandidate, ...] = ()
    risk_summary: str = ""
    approval_request_id: str | None = None
    status: str = GAP_STATUS_PROPOSED
    #: Why the proposal was blocked without a card (fail-closed path);
    #: empty when not blocked or when blocked by an explicit denial.
    block_reason: str = ""


@dataclass(slots=True)
class InstallResult:
    """Outcome of ``install_approved_skill``."""

    success: bool
    skill_name: str = ""
    installed_path: str = ""
    reason: str = ""


def _gap_from_event(query: str, message: str, event: Any) -> SkillGap:
    payload = getattr(event, "payload", None)
    thread_id = ""
    event_id = ""
    if isinstance(payload, dict):
        thread_id = _clean(payload.get("work_thread_id"), limit=128)
    event_id = _clean(getattr(event, "event_id", ""), limit=128)
    return SkillGap(
        gap_id=uuid.uuid4().hex,
        query=_clean(query, limit=500),
        router_message=_clean(message, limit=500),
        event_id=event_id,
        work_thread_id=thread_id,
    )


def detect_skill_gap(
    query: str, route_result: RouteResult, *, event: Any = None
) -> SkillGap | None:
    """A gap exists when the router claims no skill for a non-empty query.

    ``route_result.no_skill`` covers both "nothing matched" and "matched
    but nothing could be activated". An empty query is not a gap -- there
    is nothing to look for.
    """
    if not _clean(query):
        return None
    if route_result is None or not route_result.no_skill:
        return None
    return _gap_from_event(query, route_result.message, event)


def detect_skill_gap_from_matches(
    query: str, matched: Any, *, event: Any = None
) -> SkillGap | None:
    """Same gap test over a plain match list (the ``SkillStore`` path)."""
    if not _clean(query):
        return None
    if matched:
        return None
    return _gap_from_event(query, "no skill matched this request", event)


def approved_plugin_entries(lock: SkillLock) -> list[LockEntry]:
    """Already-approved plugin sources: external, pinned lockfile entries.

    A pinned entry is an explicit prior human decision ("this exact plugin
    at this exact SHA is trusted"); unpinned or local entries are never
    acquisition candidates.
    """
    approved: list[LockEntry] = []
    for entry in lock.entries.values():
        if entry.kind != "external":
            continue
        if not entry.pinned:
            continue
        if not entry.source:
            continue
        if not _SHA_RE.match(entry.sha or ""):
            continue
        approved.append(entry)
    return sorted(approved, key=lambda item: item.name)


def match_candidates(gap: SkillGap, entries: list[LockEntry]) -> list[PluginCandidate]:
    """Find approved plugins whose name cues overlap the gap query.

    Conservative on purpose: a name token of length >= 3 must appear in the
    normalized gap query. This never invents a source -- ``entries`` must
    already be the approved set from :func:`approved_plugin_entries`.
    """
    normalized_query = f" {_normalize(gap.query)} "
    candidates: list[PluginCandidate] = []
    for entry in entries:
        cues = _name_cues(entry.name)
        if not cues:
            continue
        if not any(f" {cue} " in normalized_query for cue in cues):
            # Fallback: the whole compact name appearing in the compact query.
            normalized_name = _normalize(entry.name).replace(" ", "")
            if not normalized_name or normalized_name not in normalized_query.replace(" ", ""):
                continue
        candidates.append(
            PluginCandidate(
                name=entry.name,
                source=entry.source,
                locked_sha=entry.sha,
                version=entry.version,
                risk_notes=(
                    "外部插件代码：安装包来自已批准来源，但内容仍可能随版本变化；"
                    "本次安装固定到 lockfile 记录的 SHA，不取最新。",
                    "安装后仍走现有 Skill 校验：external 技能要求 frontmatter 中 "
                    "reviewed: true + reviewed_by（人工代码审查记录），缺失则拒绝启用。",
                    "安装即按 pin 锁定：后续任何覆盖变更都会被拒绝，需显式 unpin。",
                ),
            )
        )
    return candidates


def build_proposal(
    gap: SkillGap, candidates: list[PluginCandidate]
) -> SkillGapProposal:
    """Assemble the human-readable proposal: missing what, install what, risk."""
    if candidates:
        names = "、".join(candidate.name for candidate in candidates)
        risk_summary = (
            f"能力缺口：{gap.query}。候选插件（均来自已批准来源）：{names}。"
            "批准后：按 lockfile 记录的 SHA 拉取对应插件版本，跑 Skill 校验 "
            "（含外部技能人工审查要求），校验通过后安装并 pin 锁定；"
            "校验失败则不安装。拒绝：不安装，该缺口显式阻塞，本次 Work 按无此能力继续。"
            "不联网搜索新插件、不购买、不自动装。"
        )
        status = GAP_STATUS_PROPOSED
    else:
        risk_summary = (
            f"能力缺口：{gap.query}。已批准的插件来源中没有匹配的候选："
            "不联网搜索、不引入新来源、不安装。需人工决定是否引入新的插件来源。"
        )
        status = GAP_STATUS_NO_CANDIDATE
    proposal = SkillGapProposal(
        proposal_id=uuid.uuid4().hex,
        gap=gap,
        candidates=tuple(candidates),
        risk_summary=risk_summary,
        status=status,
    )
    gap.status = status
    return proposal


def _proposal_value_text(proposal: SkillGapProposal) -> str:
    lines = [
        f"缺口：{proposal.gap.query}",
        f"检测：{proposal.gap.router_message or '无 Skill 覆盖该能力'}",
    ]
    for candidate in proposal.candidates:
        lines.append(
            f"候选：{candidate.name}（来源 {candidate.source}，"
            f"锁定版本 {candidate.version or '未知'} / SHA {candidate.locked_sha[:12]}…）"
        )
    lines.append(f"风险：{proposal.risk_summary}")
    return "；".join(lines)


def open_gap_approval(
    store: Any, proposal: SkillGapProposal, *, event_id: str = ""
) -> SkillGapProposal:
    """Raise the approval card. Fail closed: no approval path -> blocked.

    A proposal with no candidates never opens a card -- there is nothing
    concrete to approve; it stays ``no_candidate`` (an explicit block).

    Idempotent: calling this twice while the card is still pending reuses
    the open card instead of opening a second one, and a proposal that
    already reached a decision (approved/denied/installed/...) is left
    untouched -- re-opening must never clobber a recorded decision. A
    failed install (``install_failed``) may be re-proposed.
    """
    if proposal.status == GAP_STATUS_NO_CANDIDATE or not proposal.candidates:
        proposal.status = GAP_STATUS_NO_CANDIDATE
        proposal.gap.status = GAP_STATUS_NO_CANDIDATE
        proposal.block_reason = "no approved plugin candidate for this gap"
        return proposal
    if proposal.approval_request_id and proposal.status == GAP_STATUS_PROPOSED:
        return proposal
    if proposal.status not in (GAP_STATUS_PROPOSED, GAP_STATUS_INSTALL_FAILED):
        return proposal
    requester = getattr(store, "request_approval", None)
    if not callable(requester):
        proposal.status = GAP_STATUS_BLOCKED
        proposal.gap.status = GAP_STATUS_BLOCKED
        proposal.block_reason = "no approval path available (fail-closed)"
        return proposal
    try:
        request = requester(
            action_kind=APPROVAL_KIND_SKILL_ACQUIRE,
            target=proposal.candidates[0].name,
            scope=f"skill-gap:{proposal.gap.gap_id}",
            value_text=_proposal_value_text(proposal),
            source="resident",
            event_id=event_id or proposal.gap.event_id,
        )
    except Exception as exc:
        # Fail closed, but record WHY the card could not be opened: a dead
        # approval store must not be indistinguishable from "no channel".
        proposal.status = GAP_STATUS_BLOCKED
        proposal.gap.status = GAP_STATUS_BLOCKED
        proposal.block_reason = f"approval card creation failed: {type(exc).__name__}: {exc}"
        return proposal
    proposal.approval_request_id = _clean(getattr(request, "request_id", "")) or None
    if not proposal.approval_request_id:
        proposal.status = GAP_STATUS_BLOCKED
        proposal.gap.status = GAP_STATUS_BLOCKED
        proposal.block_reason = "approval store returned no request id"
        return proposal
    proposal.status = GAP_STATUS_PROPOSED
    proposal.gap.status = GAP_STATUS_PROPOSED
    proposal.block_reason = ""
    return proposal


def poll_gap_approval(store: Any, proposal: SkillGapProposal) -> SkillGapProposal:
    """Poll the card: approved -> may install; denied/expired -> blocked.

    Storage errors propagate: a broken approval store must surface as an
    error, never as an eternal "still pending".
    """
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
        proposal.status = GAP_STATUS_APPROVED
        proposal.gap.status = GAP_STATUS_APPROVED
    elif status in ("denied", "expired"):
        # Explicit block: nothing is installed, the gap stays recorded.
        proposal.status = GAP_STATUS_DENIED
        proposal.gap.status = GAP_STATUS_DENIED
    return proposal


def default_fetch_plugin(source: str, sha: str, dest: Path) -> None:
    """Fetch a plugin repo at an exact SHA. Called only after approval.

    Clones the approved source, checks out the pinned SHA, verifies HEAD,
    and removes the nested ``.git`` so the bundle is plain files.
    """
    url = source[4:] if source.startswith("git+") else source
    if dest.exists():
        raise RuntimeError(f"destination already exists: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["git", "clone", "--quiet", url, str(dest)],
        capture_output=True,
        text=True,
        timeout=_FETCH_TIMEOUT_SECONDS,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git clone failed for {url}: {proc.stderr.strip()[:300]}")
    proc = subprocess.run(
        ["git", "-C", str(dest), "checkout", "--quiet", sha],
        capture_output=True,
        text=True,
        timeout=_FETCH_TIMEOUT_SECONDS,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git checkout {sha[:12]} failed: {proc.stderr.strip()[:300]}")
    proc = subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.stdout.strip() != sha:
        raise RuntimeError("checked-out SHA does not match the pinned SHA")
    git_dir = dest / ".git"
    if git_dir.is_dir():
        # Explicit: a leftover .git would ship remote URLs and history
        # objects inside the installed bundle, so a removal failure is an
        # install failure, not a silent skip.
        shutil.rmtree(git_dir)


def _frontmatter_version(text: str) -> str:
    """Best-effort ``version:`` from a skill file's frontmatter block."""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    head = text[3:end] if end != -1 else ""
    match = re.search(r"^version\s*:\s*[\"']?([^\"'\s]+)", head, re.M)
    return match.group(1).strip() if match else ""


def _find_skill_file(fetched: Path) -> Path | None:
    """Locate ``skill.md`` at the plugin repo root.

    Only the root is honored: ZN's router only activates
    ``<bundle>/skill.md``, so a nested layout could never be activated
    anyway -- finding it would only produce a confusing late failure.
    """
    root_file = fetched / "skill.md"
    return root_file if root_file.is_file() else None


def install_approved_skill(
    proposal: SkillGapProposal,
    candidate: PluginCandidate,
    *,
    skills_root: str | Path,
    fetch_skill: Callable[[str, str, Path], None] | None = None,
    work_dir: str | Path | None = None,
) -> InstallResult:
    """Install the candidate plugin. Only runs on an approved proposal.

    Steps: fetch at the pinned SHA (network happens here and only here) ->
    locate ``skill.md`` -> run the existing skill validation (external
    policy: human review record required) -> activation-check the *staged*
    bundle -> pin-enforced write of the bundle under the skills root ->
    record/refresh the pinned lockfile entry.

    Any failure leaves the skills root and lockfile untouched and reports
    ``install_failed`` with the reason: the activation check runs against
    the staged copy *before* anything is written, so a bundle that cannot
    be activated never reaches the skills root. Installing over an
    existing pinned skill with different content is refused (the
    lockfile's own rule).
    """
    if proposal.status != GAP_STATUS_APPROVED:
        return InstallResult(
            success=False,
            skill_name=candidate.name,
            reason=(
                f"refused: proposal is '{proposal.status}', not approved; "
                "installation requires a recorded approval"
            ),
        )
    if not _SHA_RE.match(candidate.locked_sha or ""):
        return _mark_install_failed(
            proposal, candidate,
            "refused: candidate SHA is not a full 40-hex pin",
        )
    # Trust-chain binding: the human approved exactly the candidates on
    # this proposal (name + source + pinned SHA). Installing anything else
    # -- "approve A, install B" -- is refused, even with an approved card.
    if not any(
        other.name == candidate.name
        and other.source == candidate.source
        and other.locked_sha == candidate.locked_sha
        for other in proposal.candidates
    ):
        return _mark_install_failed(
            proposal, candidate,
            "refused: candidate is not one of this proposal's approved "
            "candidates (name/source/SHA must match what the card lists)",
        )
    root = Path(skills_root)
    target_dir = root / candidate.name
    fetcher = fetch_skill or default_fetch_plugin
    if work_dir is not None:
        staging_base = Path(work_dir)
        staging_base.mkdir(parents=True, exist_ok=True)
        stage_parent = staging_base / f"skill-gap-{proposal.proposal_id[:12]}"
        stage_parent.mkdir(parents=True, exist_ok=True)
        tmp_handle = None
    else:
        import tempfile

        tmp_handle = tempfile.TemporaryDirectory(prefix="zn-skill-gap-")
        stage_parent = Path(tmp_handle.name)
    stage_dir = stage_parent / candidate.name
    try:
        try:
            fetcher(candidate.source, candidate.locked_sha, stage_dir)
        except Exception as exc:
            raise _InstallError(f"fetch failed: {type(exc).__name__}: {exc}") from exc
        skill_file = _find_skill_file(stage_dir)
        if skill_file is None:
            raise _InstallError("no skill.md found in the fetched plugin")
        validation = validate_skill_file(skill_file, external=True)
        if not validation.valid:
            raise _InstallError(
                "skill validation failed: " + "; ".join(validation.reasons)
            )
        # Activation check against the STAGED bundle: SkillRouter.activate()
        # only reads the bundle directory (no lockfile involved), so a
        # bundle that cannot be activated is rejected before the skills
        # root or the lockfile is touched.
        staged_router = SkillRouter(stage_parent)
        if staged_router.activate(candidate.name) is None:
            raise _InstallError(
                "staged skill failed the activation check "
                "(not discoverable/activatable under its own name)"
            )
        text = skill_file.read_text(encoding="utf-8")
        digest = content_sha256(text)
        lock = SkillLock(root)
        try:
            # Sanctioned pin enforcement: an overwriting change to a pinned
            # skill raises SkillLockedError and the file stays untouched;
            # a byte-identical rewrite is allowed (idempotent, not a change).
            lock.check_write(
                candidate.name,
                new_text=text,
                new_version=_frontmatter_version(text) or candidate.version,
                new_sha=candidate.locked_sha,
            )
        except SkillLockedError as exc:
            raise _InstallError(f"refused: {exc}") from exc
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "skill.md").write_text(text, encoding="utf-8")
        lock.pin(
            candidate.name,
            version=_frontmatter_version(text) or candidate.version,
            sha=candidate.locked_sha,
            content_sha256=digest,
            kind="external",
            source=candidate.source,
        )
        lock.save()
        proposal.status = GAP_STATUS_INSTALLED
        proposal.gap.status = GAP_STATUS_INSTALLED
        return InstallResult(
            success=True,
            skill_name=candidate.name,
            installed_path=str(target_dir / "skill.md"),
        )
    except _InstallError as exc:
        return _mark_install_failed(proposal, candidate, str(exc))
    except Exception as exc:
        return _mark_install_failed(
            proposal, candidate,
            f"install failed: {type(exc).__name__}: {exc}",
        )
    finally:
        # Staging is always cleaned: the TemporaryDirectory case and the
        # explicit work_dir case alike, on success and on failure.
        if tmp_handle is not None:
            tmp_handle.cleanup()
        elif stage_parent.is_dir():
            shutil.rmtree(stage_parent, ignore_errors=True)


class _InstallError(Exception):
    """Expected install failure: reported, never mistaken for success."""


def _mark_install_failed(
    proposal: SkillGapProposal, candidate: PluginCandidate, reason: str
) -> InstallResult:
    """Record an install failure on the proposal: never look approved."""
    proposal.status = GAP_STATUS_INSTALL_FAILED
    proposal.gap.status = GAP_STATUS_INSTALL_FAILED
    return InstallResult(success=False, skill_name=candidate.name, reason=reason)


__all__ = [
    "APPROVAL_KIND_SKILL_ACQUIRE",
    "GAP_STATUS_PROPOSED",
    "GAP_STATUS_NO_CANDIDATE",
    "GAP_STATUS_APPROVED",
    "GAP_STATUS_DENIED",
    "GAP_STATUS_BLOCKED",
    "GAP_STATUS_INSTALLED",
    "GAP_STATUS_INSTALL_FAILED",
    "SkillGap",
    "PluginCandidate",
    "SkillGapProposal",
    "InstallResult",
    "detect_skill_gap",
    "detect_skill_gap_from_matches",
    "approved_plugin_entries",
    "match_candidates",
    "build_proposal",
    "open_gap_approval",
    "poll_gap_approval",
    "default_fetch_plugin",
    "install_approved_skill",
]
