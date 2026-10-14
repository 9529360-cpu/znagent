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
"""

import json
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
    '"files": ["<workspace-relative path>"], "unfinished": []}}'
)


@dataclass(frozen=True, slots=True)
class CompletionVerdict:
    """The adjudicator's decision on one completion claim."""

    verdict: str  # verified | partial | rejected
    expected_output: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    reason: str = ""
    missing_items: tuple[str, ...] = ()
    actionable_fix: str = ""

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
) -> str:
    """Render a well-formed completion-report claim (JSON string).

    ``evidence`` accepts ``(criterion, evidence_ref)`` pairs or dicts with
    those keys. Tests and fixtures build claims through here so a typo in
    the wire shape fails loudly instead of silently becoming a verdict.
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
    return json.dumps(
        {
            "completion_report": {
                "conclusion": conclusion,
                "evidence": entries,
                "files": list(files),
                "unfinished": list(unfinished),
            }
        },
        ensure_ascii=False,
    )


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


def adjudicate_completion(
    *,
    expected_output: list[str] | tuple[str, ...],
    evidence: list[dict[str, Any]],
    summary: str,
) -> CompletionVerdict:
    """Judge one completion claim against its expected output.

    Pure function: no I/O, no counting. The caller re-reads ``evidence``
    from the ledger (fresh observation) and owns retry counting.
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

    # -- self-contradiction: "未证实" in the conclusion, yet claiming done --
    if "未证实" in conclusion and not missing:
        return rejected(
            "终报结论称“未证实”却申报全部完成，自相矛盾",
            "把未证实项列入 unfinished 后重提；结论只写已证实的内容。",
        )
    if missing:
        return CompletionVerdict(
            verdict="partial",
            expected_output=expected,
            evidence_refs=tuple(dict.fromkeys(matched_refs)),
            reason="以下验收项缺可验证证据或未完成：" + "、".join(missing),
            missing_items=tuple(missing),
            actionable_fix="对缺失项补可验证证据（写文件/跑脚本并通过 Body 验收），"
            "在终报 evidence 中逐项引用后重提。",
        )
    return CompletionVerdict(
        verdict="verified",
        expected_output=expected,
        evidence_refs=tuple(dict.fromkeys(matched_refs)),
        reason="全部验收项均有可验证证据引用，未完成项为空。",
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
    "CompletionVerdict",
    "adjudicate_completion",
    "record_verdict_attempt",
    "render_completion_report",
]
