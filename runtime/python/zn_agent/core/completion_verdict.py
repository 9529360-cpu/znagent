from __future__ import annotations

"""CP-3: structured completion verdict + final-report contract for team work.

Source patterns (mechanisms only, no copied code): CrewAI Task contracts
(``expected_output`` + ``context`` handoff + structured output) + Muse
commitment boundaries and evidence-first reporting.

The old team flow let a specialist claim completion with prose ("搞定了"),
and the verifier only checked "some verified evidence + a non-empty
summary". That produced both false positives (a rejected proposal whose
text contained "完成" was recorded as a claim) and false negatives
("搞定了" sometimes not recognised). The verdict replaces keyword
claiming with a checkable contract:

- A completion claim must be a structured final report
  (``{"completion_report": {...}}``) with four sections: conclusion,
  evidence, files, unfinished items.
- Every ``expected_output`` item (the plan item's acceptance criteria)
  must be cited with an ``evidence_ref`` that matches one real
  Body-verified evidence entry, re-read from the ledger at decision time
  (fresh observation, never a cached claim).
- ``verified``: every expected item cited with matching evidence and
  nothing unfinished. ``partial``: some expected item lacks matching
  evidence or is listed unfinished -- carries the missing-item list.
  ``rejected``: malformed report, no evidence at all, a cited criterion
  outside ``expected_output``, or a self-contradictory report (conclusion
  says "未证实" yet claims completion).
- Uncertainty is not a fact: anything uncertain belongs in ``unfinished``,
  which forces ``partial``, never ``verified``.
- Test claims need a real run (P2): when an acceptance criterion is
  test-related, or a test file was written, the claim is ``partial``
  until some verified evidence entry records a ``run_python`` step.
  Writing tests without running them never earns a "test coverage"
  claim -- the smoke run caught a developer writing ``test_app.py``
  and never executing it while the claim still passed.

What the adjudicator deliberately does NOT do: it checks that each cited
criterion points at real verified evidence; it does not judge semantic
entailment (whether the evidence *means* the criterion is met). That
judgment stays the specialist's honest citation, gated by the
evidence-existence check -- the same boundary as the Body verifier, which
checks postconditions, not intent.

Retry budget: a non-verified verdict sends the specialist back with the
reason + an actionable fix + the missing list. At most
``MAX_VERDICT_ATTEMPTS`` re-runs are allowed after a rejection; the next
rejection escalates to the user. Two consecutive rejections with the
identical reason + missing set escalate at once -- repeating the same
rejected claim is spinning, not progress.

AS-3 dual-track Definition of Done: a claim must satisfy BOTH tracks to
complete an item.

- Track 1 (task acceptance): every ``expected_output`` item cited with
  matching verified evidence, as above.
- Track 2 (standing DoD): the report's ``standing_dod`` section attests
  five standing items -- no_regression (无回归), runtime_verified
  (运行时验证), docs (文档), rollback (回滚路径), approval (审批).
  Each item is ``{"status": "satisfied" | "not_applicable", "detail":
  "<concrete attestation>", "evidence_ref": "<optional>"}``.
  ``detail`` is always required: a satisfied item says what was done, a
  not_applicable item says why the item has no surface here. An
  ``evidence_ref``, when given, must match a real verified evidence
  entry -- a dangling citation makes the item missing, never verified.
  ``no_regression`` and ``runtime_verified`` are evidence-anchored: a
  satisfied claim MUST cite a real evidence entry (a test run / a
  runtime run), because prose alone cannot prove "no regression" or
  "verified at runtime". ``docs`` / ``rollback`` / ``approval`` are
  attestation-anchored: a concrete ``detail`` suffices (e.g. which doc
  was updated, how to revert, whether approval was needed and obtained),
  with an optional real ``evidence_ref``.

  Either track missing -> the claim is not accepted (``partial`` with
  the missing items, DoD items prefixed ``standing_dod:``), with an
  explicit missing list. A structurally invented DoD item (an unknown
  key in ``standing_dod``) is ``rejected``, mirroring unknown criteria.
  When ``require_standing_dod`` is False (the default, for
  backward-compatible library use) a report WITHOUT a ``standing_dod``
  section is judged on track 1 alone; a report WITH the section is
  always judged on both tracks. The team owner passes
  ``require_standing_dod=True`` at both adjudication points, so in the
  product path a missing DoD section is itself a missing track.

M-5 reuses this same adjudicator for single (non-team) Work completion:
the evidence-bound ledger gates ``accept_root_with_current_evidence``
on a ``verified`` verdict here, with evidence entries built from the
Root's completed current-plan children. There is deliberately no second
adjudicator -- one verdict, two call sites (team owner, single-Work
ledger), both with ``require_standing_dod=True``.
"""

import json
import re
from dataclasses import dataclass
from typing import Any

#: Verdict values. ``verified`` is the only one that may complete an item.
VERDICTS = ("verified", "partial", "rejected")

#: Re-runs allowed after a rejection; the next rejection escalates.
MAX_VERDICT_ATTEMPTS = 3

#: Shape hint handed to the specialist when its report is malformed.
REPORT_SHAPE_HINT = (
    '{"completion_report": {"conclusion": "...", "evidence": '
    '[{"criterion": "<exact acceptance criterion>", "evidence_ref": '
    '"<relative_path or objective of one verified evidence entry>"}], '
    '"files": ["<workspace-relative path>"], "unfinished": [], '
    '"standing_dod": {"<no_regression|runtime_verified|docs|rollback|approval>": '
    '{"status": "satisfied|not_applicable", "detail": "...", '
    '"evidence_ref": "<optional, must match real evidence>"}}}}'
)

#: Standing Definition of Done (AS-3): (key, Chinese label) pairs.
#: Every completion claim in the product path must attest all five.
STANDING_DOD_ITEMS: tuple[tuple[str, str], ...] = (
    ("no_regression", "无回归"),
    ("runtime_verified", "运行时验证"),
    ("docs", "文档"),
    ("rollback", "回滚路径"),
    ("approval", "审批"),
)
STANDING_DOD_KEYS: tuple[str, ...] = tuple(
    key for key, _ in STANDING_DOD_ITEMS
)
_STANDING_DOD_LABEL: dict[str, str] = dict(STANDING_DOD_ITEMS)

#: DoD items whose "satisfied" must cite a real verified evidence entry.
#: The other three are attestation-anchored (concrete detail suffices).
STANDING_DOD_EVIDENCE_ANCHORED: tuple[str, ...] = (
    "no_regression",
    "runtime_verified",
)

#: Accepted per-item DoD statuses. Anything else means "not yet attested".
STANDING_DOD_STATUSES: tuple[str, ...] = ("satisfied", "not_applicable")


class CompletionVerdictError(ValueError):
    """A non-verified completion verdict, raised at a completion gate.

    Carries the adjudicator's verdict so the caller can feed its reason
    + missing list + actionable fix back to the claimant and count one
    bounded retry, instead of parsing a message string. Raised by the
    single-Work ledger gate; the team owner reads the verdict directly
    and never sees this exception.
    """

    def __init__(self, verdict: CompletionVerdict) -> None:
        super().__init__(verdict.feedback_text())
        self.verdict = verdict


@dataclass(frozen=True, slots=True)
class CompletionVerdict:
    """The adjudicator's decision on one completion claim."""

    verdict: str  # verified | partial | rejected
    expected_output: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    reason: str = ""
    missing_items: tuple[str, ...] = ()
    actionable_fix: str = ""
    #: Standing-DoD keys (see STANDING_DOD_KEYS) still missing. Empty when
    #: track 2 passes or was not attested. Mirrored inside missing_items
    #: as "standing_dod:<key>" entries so feedback lists one missing list.
    dod_missing: tuple[str, ...] = ()

    def feedback_text(self) -> str:
        """One feedback block for the next cognition call."""
        parts = [f"完成裁决：{self.verdict}。{self.reason}"]
        if self.missing_items:
            parts.append("缺失项：" + "；".join(self.missing_items))
        if self.actionable_fix:
            parts.append(f"可执行修改：{self.actionable_fix}")
        return " ".join(parts)


def render_completion_report(
    *,
    conclusion: str,
    evidence: list[dict[str, str]] | list[tuple[str, str]],
    files: list[str],
    unfinished: list[str],
    standing_dod: dict[str, dict[str, str]] | None = None,
) -> str:
    """Render a well-formed completion-report claim (JSON string).

    ``evidence`` accepts ``(criterion, evidence_ref)`` pairs or dicts with
    those keys. Tests and fixtures build claims through here so a typo in
    the wire shape fails loudly instead of silently becoming a verdict.
    ``standing_dod``, when given, maps each of the five standing-DoD keys
    to ``{"status": ..., "detail": ..., "evidence_ref": ...}`` (see the
    module docstring); it is emitted verbatim as the report's
    ``standing_dod`` section.
    """
    entries = []
    for entry in evidence:
        if isinstance(entry, dict):
            entries.append(
                {
                    "criterion": str(entry.get("criterion") or ""),
                    "evidence_ref": str(entry.get("evidence_ref") or ""),
                }
            )
        else:
            criterion, ref = entry
            entries.append({"criterion": str(criterion), "evidence_ref": str(ref)})
    report: dict[str, Any] = {
        "conclusion": conclusion,
        "evidence": entries,
        "files": list(files),
        "unfinished": list(unfinished),
    }
    if standing_dod is not None:
        report["standing_dod"] = standing_dod
    return json.dumps(
        {"completion_report": report},
        ensure_ascii=False,
    )


def _is_test_related_criterion(criterion: str) -> bool:
    """Does this acceptance criterion ask for tests / test coverage?

    Word-boundary matching for English so "latest" does not match "test";
    plain substring for Chinese, where "测试" has no such collision.
    """
    lowered = criterion.lower()
    if re.search(r"\btests?\b|\btesting\b", lowered):
        return True
    return "测试" in criterion or any(
        token in lowered for token in ("pytest", "unittest", "run_python")
    )


def _is_test_file_path(path: str) -> bool:
    """Does this workspace-relative path look like a test file?"""
    lowered = path.replace("\\", "/").lower()
    base = lowered.rsplit("/", 1)[-1]
    if base.startswith("test_") or base.endswith(("_test.py", "_tests.py")):
        return True
    return "/tests/" in lowered or "/test/" in lowered


def _entry_text(entry: dict[str, Any]) -> str:
    return " ".join(
        str(entry.get(key) or "")
        for key in ("relative_path", "objective", "result")
    ).lower()


def _ref_matches(ref: str, entry: dict[str, Any]) -> bool:
    """Does this evidence_ref cite this verified evidence entry?

    Match is substring in either direction over the entry's path /
    objective / result, so a ref may cite a file path, an objective, or a
    distinctive result excerpt -- but it must cite something real.
    """
    needle = ref.strip().lower()
    if not needle:
        return False
    haystack = _entry_text(entry)
    # An entry with no text at all must not match via the empty string.
    if haystack.strip() and (needle in haystack or haystack in needle):
        return True
    path = str(entry.get("relative_path") or "").strip().lower()
    return bool(path) and (needle in path or path in needle)


def _validate_standing_dod(
    section: Any,
    *,
    evidence: list[dict[str, Any]],
) -> tuple[list[str], tuple[str, str] | None]:
    """Validate track 2 (standing DoD). Returns ``(missing_keys, rejected)``.

    ``missing_keys`` lists the DoD keys not properly attested -- an item
    that is absent, malformed, unattested, or citing a dangling
    ``evidence_ref`` is missing, never verified. ``rejected`` is set only
    for a structurally invented DoD (an unknown key), mirroring the
    unknown-criterion rejection on track 1.
    """
    if not isinstance(section, dict):
        return [], (
            "终报 standing_dod 段必须是对象",
            "standing_dod 按五项逐项填写："
            + "、".join(STANDING_DOD_KEYS)
            + f"；完整结构：{REPORT_SHAPE_HINT}",
        )
    unknown = [key for key in section if key not in _STANDING_DOD_LABEL]
    if unknown:
        return [], (
            "终报 standing_dod 引用了不存在的 DoD 项：" + "、".join(unknown),
            "standing_dod 只写五项："
            + "、".join(STANDING_DOD_KEYS)
            + "。",
        )
    missing: list[str] = []
    for key in STANDING_DOD_KEYS:
        entry = section.get(key)
        if not isinstance(entry, dict):
            missing.append(key)
            continue
        status = str(entry.get("status") or "").strip()
        detail = str(entry.get("detail") or "").strip()
        if status not in STANDING_DOD_STATUSES or not detail:
            missing.append(key)
            continue
        ref = str(entry.get("evidence_ref") or "").strip()
        if ref and not any(_ref_matches(ref, item) for item in evidence):
            # A cited ref must be real, even on an attestation-anchored
            # item or a not_applicable item: a dangling citation is
            # never silently accepted.
            missing.append(key)
            continue
        if (
            status == "satisfied"
            and key in STANDING_DOD_EVIDENCE_ANCHORED
            and not ref
        ):
            # Evidence-anchored items cannot be satisfied by prose alone.
            missing.append(key)
    return missing, None


def adjudicate_completion(
    *,
    expected_output: list[str] | tuple[str, ...],
    evidence: list[dict[str, Any]],
    summary: str,
    require_standing_dod: bool = False,
) -> CompletionVerdict:
    """Judge one completion claim against its expected output.

    Pure function: no I/O, no counting. The caller re-reads ``evidence``
    from the ledger (fresh observation) and owns retry counting.

    AS-3 dual track: ``verified`` requires BOTH the task acceptance
    criteria (track 1) AND the standing DoD (track 2). When
    ``require_standing_dod`` is True, a missing ``standing_dod`` section
    is itself a missing track; otherwise a report without the section is
    judged on track 1 alone, and a report WITH the section is always
    judged on both tracks.
    """
    expected: tuple[str, ...] = tuple(
        dict.fromkeys(
            str(item).strip() for item in (expected_output or []) if str(item).strip()
        )
    )

    def rejected(reason: str, fix: str) -> CompletionVerdict:
        return CompletionVerdict(
            verdict="rejected",
            expected_output=expected,
            reason=reason,
            actionable_fix=fix,
        )

    # -- shape: must be a JSON completion report with four sections -------
    try:
        parsed = json.loads(str(summary or "").strip())
    except (ValueError, TypeError):
        parsed = None
    if not isinstance(parsed, dict) or not isinstance(
        parsed.get("completion_report"), dict
    ):
        return rejected(
            "终报不是结构化完成报告：需为 JSON 对象且含 completion_report",
            f"按四段式结构重提终报：{REPORT_SHAPE_HINT}",
        )
    report = parsed["completion_report"]
    missing_sections = [
        name
        for name in ("conclusion", "evidence", "files", "unfinished")
        if name not in report
    ]
    if missing_sections:
        return rejected(
            "终报缺段：" + "、".join(missing_sections),
            "补齐缺失段后重提："
            + "、".join(missing_sections)
            + f"；完整结构：{REPORT_SHAPE_HINT}",
        )
    conclusion = report.get("conclusion")
    evidence_claims = report.get("evidence")
    files = report.get("files")
    unfinished = report.get("unfinished")
    if not isinstance(conclusion, str) or not conclusion.strip():
        return rejected(
            "终报结论段为空",
            "在 conclusion 中写一句话结论：完成了什么、依据是什么。",
        )
    if not isinstance(evidence_claims, list):
        return rejected("终报 evidence 段必须是列表", "evidence 列出每条验收项的举证。")
    if not isinstance(files, list):
        return rejected("终报 files 段必须是列表", "files 列出本次产物的工作区相对路径，无产物则写 []。")
    if not isinstance(unfinished, list) or not all(
        isinstance(item, str) for item in unfinished
    ):
        return rejected(
            "终报 unfinished 段必须是字符串列表",
            "unfinished 列出未完成/未证实的验收项，全部完成则写 []。",
        )
    unfinished_clean = [str(item).strip() for item in unfinished if str(item).strip()]
    unknown_unfinished = [item for item in unfinished_clean if item not in expected]
    if unknown_unfinished:
        return rejected(
            "终报 unfinished 引用了不在 expected_output 中的验收项："
            + "、".join(unknown_unfinished),
            "unfinished 只能列 expected_output 中的验收项。",
        )

    # -- evidence claims: well-formed, known criteria -----------------------
    cited: dict[str, list[str]] = {}
    for entry in evidence_claims:
        if not isinstance(entry, dict):
            return rejected(
                "终报 evidence 中有非对象条目",
                "每条举证写成 {criterion, evidence_ref}。",
            )
        criterion = str(entry.get("criterion") or "").strip()
        ref = str(entry.get("evidence_ref") or "").strip()
        if not criterion or not ref:
            return rejected(
                "终报 evidence 中有条目缺 criterion 或 evidence_ref",
                "每条举证必须同时写验收项原文与证据引用。",
            )
        if criterion not in expected:
            return rejected(
                f"终报举证引用了不在 expected_output 中的验收项：{criterion}",
                "只对 expected_output 中的验收项逐项举证。",
            )
        cited.setdefault(criterion, []).append(ref)

    # -- no evidence at all: an evidence-free claim never passes -----------
    if not evidence:
        return rejected(
            "认领没有任何 Body 验证证据",
            "先产生可验证的工作产物（写文件/跑脚本并通过 Body 验收），再重提终报。",
        )

    # -- per-criterion coverage: cited AND the ref matches real evidence ---
    matched_refs: list[str] = []
    covered: set[str] = set()
    for criterion, refs in cited.items():
        if criterion in unfinished_clean:
            continue  # listed unfinished: never covered, even if cited
        for ref in refs:
            if any(_ref_matches(ref, entry) for entry in evidence):
                covered.add(criterion)
                matched_refs.append(ref)
                break
    missing = [item for item in expected if item not in covered]
    for item in unfinished_clean:
        if item not in missing:
            missing.append(item)

    # -- P2: test claims need a real run ---------------------------------
    # A test-related criterion, or a written test file, requires at least
    # one verified run_python evidence entry. Without it, the test-related
    # criteria stay missing; when no criterion is test-related but a test
    # file was written and never run, the whole claim waits -- the
    # specialist produced tests it never executed.
    requires_run = any(_is_test_related_criterion(item) for item in expected) or any(
        _is_test_file_path(str(entry.get("relative_path") or ""))
        for entry in evidence
    )
    has_run = any(
        str(entry.get("action_kind") or "") == "run_python" for entry in evidence
    )
    run_gate_triggered = bool(requires_run and not has_run)
    if run_gate_triggered:
        run_missing = [
            item for item in expected if _is_test_related_criterion(item)
        ]
        if not run_missing:
            run_missing = [item for item in expected if item not in missing]
        for item in run_missing:
            if item not in missing:
                missing.append(item)

    # -- AS-3 track 2: standing Definition of Done -----------------------
    dod_section = report.get("standing_dod")
    if dod_section is None:
        if require_standing_dod:
            dod_missing = list(STANDING_DOD_KEYS)
            dod_rejected = None
        else:
            dod_missing, dod_rejected = [], None
    else:
        dod_missing, dod_rejected = _validate_standing_dod(
            dod_section, evidence=evidence
        )
    if dod_rejected is not None:
        reason, fix = dod_rejected
        return rejected(reason, fix)

    # -- self-contradiction: "未证实" in the conclusion, yet claiming done --
    if "未证实" in conclusion and not missing and not dod_missing:
        return rejected(
            "终报结论称“未证实”却申报全部完成，自相矛盾",
            "把未证实项列入 unfinished 后重提；结论只写已证实的内容。",
        )
    if missing or dod_missing:
        actionable = (
            "对缺失项补可验证证据（写文件/跑脚本并通过 Body 验收），"
            "在终报 evidence 中逐项引用后重提。"
        )
        if run_gate_triggered:
            actionable += (
                "测试相关认领还需实际运行证据：先用 run_python 运行测试并通过，"
                "再重提终报；只写测试不运行的认领不被接受。"
            )
        if dod_missing:
            actionable += (
                "对缺失的 standing DoD 项补举证/说明后重提："
                "无回归与运行时验证须引用真实证据条目；其余项须写具体 detail；"
                "无需某项时写 not_applicable 并说明原因。"
            )
        reason = ""
        if missing:
            reason += "以下验收项缺可验证证据或未完成：" + "、".join(missing)
        if dod_missing:
            if reason:
                reason += "；"
            reason += (
                "standing DoD 缺项："
                + "、".join(_STANDING_DOD_LABEL[key] for key in dod_missing)
            )
        return CompletionVerdict(
            verdict="partial",
            expected_output=expected,
            evidence_refs=tuple(dict.fromkeys(matched_refs)),
            reason=reason,
            missing_items=tuple(
                list(missing) + [f"standing_dod:{key}" for key in dod_missing]
            ),
            actionable_fix=actionable,
            dod_missing=tuple(dod_missing),
        )
    return CompletionVerdict(
        verdict="verified",
        expected_output=expected,
        evidence_refs=tuple(dict.fromkeys(matched_refs)),
        reason="全部验收项均有可验证证据引用，未完成项为空；"
        "standing DoD 五项均已举证/说明。",
        actionable_fix="",
    )


# -- retry budget ---------------------------------------------------------

def _signature(verdict: CompletionVerdict) -> tuple[str, str, tuple[str, ...]]:
    return (verdict.verdict, verdict.reason, tuple(verdict.missing_items))


def record_verdict_attempt(
    tracking: dict[str, Any] | None,
    *,
    run_id: str,
    verdict: CompletionVerdict,
) -> tuple[dict[str, Any], bool, str | None]:
    """Record one non-verified verdict; decide whether to escalate.

    Returns ``(updated_tracking, escalate, escalate_reason)``. A new run
    resets the counters. Escalation triggers on the rejection after
    ``MAX_VERDICT_ATTEMPTS`` re-runs, or at once on the second consecutive
    rejection with an identical reason + missing set.
    """
    if not isinstance(tracking, dict) or str(tracking.get("run_id") or "") != run_id:
        tracking = {
            "run_id": run_id,
            "attempts": 0,
            "last_signature": None,
            "consecutive_same": 0,
        }
    attempts = int(tracking.get("attempts") or 0) + 1
    signature = _signature(verdict)
    consecutive = (
        int(tracking.get("consecutive_same") or 0) + 1
        if tracking.get("last_signature") is not None
        and list(tracking.get("last_signature") or []) == _signature_to_list(signature)
        else 1
    )
    updated = {
        "run_id": run_id,
        "attempts": attempts,
        "last_signature": _signature_to_list(signature),
        "consecutive_same": consecutive,
    }
    if consecutive >= 2:
        return updated, True, (
            "完成裁决连续 2 次相同拒绝，已停止等待用户拍板："
            f"{verdict.reason} 可执行修改：{verdict.actionable_fix}"
        )
    if attempts > MAX_VERDICT_ATTEMPTS:
        return updated, True, (
            f"完成裁决拒绝已超 {MAX_VERDICT_ATTEMPTS} 次重跑上限，"
            f"已停止等待用户拍板：{verdict.reason} "
            f"可执行修改：{verdict.actionable_fix}"
        )
    return updated, False, None


def _signature_to_list(
    signature: tuple[str, str, tuple[str, ...]],
) -> list[Any]:
    return [signature[0], signature[1], list(signature[2])]


__all__ = [
    "MAX_VERDICT_ATTEMPTS",
    "REPORT_SHAPE_HINT",
    "CompletionVerdictError",
    "STANDING_DOD_EVIDENCE_ANCHORED",
    "STANDING_DOD_ITEMS",
    "STANDING_DOD_KEYS",
    "STANDING_DOD_STATUSES",
    "CompletionVerdict",
    "adjudicate_completion",
    "record_verdict_attempt",
    "render_completion_report",
]
