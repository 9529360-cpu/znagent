from __future__ import annotations

"""Deterministic safety gates for the bounded E2E-12 completion behavior.

The model remains a candidate generator. Retrieved source content and model
outputs are untrusted until these local gates admit them. This module does not
own routing, Web acquisition, DOCX mutation, Work, or completion truth; it only
wraps the existing E2E-12 behavior before synthesis and before mutation.
"""

import re
from typing import Any, Mapping

from .document_research_completion_behavior import _STATE_KEY, _blocked, _persist
from .research_information_work import ResearchSourceObservation

_INSTALL_MARKER = "_zn_document_research_completion_safety_v1_installed"
_MIN_INDEPENDENT_SUPPORTS = 2

_PROMPT_INJECTION_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore_prior_instructions",
        re.compile(
            r"\b(?:ignore|disregard|forget|override)\b.{0,80}\b(?:previous|prior|above|earlier)\b.{0,40}\b(?:instruction|instructions|prompt|prompts|message|messages|rules)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "role_or_system_override",
        re.compile(
            r"\b(?:system|developer|assistant)\b.{0,40}\b(?:prompt|message|instruction|instructions|role)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "structured_output_directive",
        re.compile(
            r"\b(?:return|output|respond|emit|write)\b.{0,100}\b(?:json|document_completion_synthesis|target_id|destination_path|replacement|replacements)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "tool_or_file_directive",
        re.compile(
            r"\b(?:call|invoke|use|delete|overwrite|change|set|modify)\b.{0,100}\b(?:tool|function|body action|destination|destination_path|file|files|document)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "identity_override",
        re.compile(r"\byou are now\b|\bact as\b.{0,60}\b(?:system|developer|assistant)\b", re.IGNORECASE | re.DOTALL),
    ),
    (
        "zh_instruction_override",
        re.compile(r"(?:忽略|无视|覆盖).{0,24}(?:之前|以上|前面|原有).{0,24}(?:指令|提示|规则|要求)"),
    ),
    (
        "zh_action_directive",
        re.compile(r"(?:输出|返回|写入|删除|调用|修改).{0,40}(?:JSON|json|工具|文件|目标路径|destination_path|target_id|replacement)"),
    ),
)

_DATE_RE = re.compile(
    r"(?<!\d)(?P<year>(?:19|20)\d{2})[-/.年](?P<month>0?[1-9]|1[0-2])[-/.月](?P<day>0?[1-9]|[12]\d|3[01])日?(?!\d)"
)
_CURRENCY_SYMBOL_RE = re.compile(r"(?P<symbol>[$€£¥])\s*(?P<amount>\d[\d,]*(?:\.\d+)?)")
_CURRENCY_WORD_RE = re.compile(
    r"(?P<amount>\d[\d,]*(?:\.\d+)?)\s*(?:USD|EUR|GBP|JPY|CNY|RMB|dollars?|euros?|pounds?|yen|美元|美金|欧元|英镑|日元|人民币|元)",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"(?<![\d.])(?P<amount>\d+(?:\.\d+)?)\s*%")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？；;])\s+|[\r\n]+")
_WORD_RE = re.compile(r"[a-z][a-z0-9_-]{2,}", re.IGNORECASE)
_FIELD_WORDS = {
    "currency": ("price", "cost", "fee", "amount", "budget", "售价", "价格", "费用", "金额", "预算"),
    "date": ("date", "launch", "release", "released", "published", "发布日期", "发布日", "日期", "上线"),
    "percent": ("percent", "percentage", "rate", "ratio", "占比", "比例", "百分比", "率"),
}
_SIGNAL_STOPWORDS = {
    "official",
    "independent",
    "source",
    "bulletin",
    "current",
    "confirms",
    "confirm",
    "lists",
    "list",
    "says",
    "said",
    "observed",
    "document",
    "information",
    "price",
    "cost",
    "date",
    "launch",
    "release",
    "published",
    "amount",
    "budget",
    "percent",
    "percentage",
    "rate",
}


def _meta(state) -> dict[str, Any]:
    raw = state.data.get(_STATE_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def _normalized_text(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def _normalized_amount(raw: str) -> str:
    value = str(raw or "").replace(",", "").strip()
    if not value:
        return ""
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    whole, dot, fraction = value.partition(".")
    whole = whole.lstrip("0") or "0"
    return whole + (dot + fraction if dot and fraction else "")


def _typed_values(text: object) -> dict[str, set[str]]:
    value = str(text or "")
    output: dict[str, set[str]] = {"date": set(), "currency": set(), "percent": set()}
    for match in _DATE_RE.finditer(value):
        output["date"].add(
            f"{int(match.group('year')):04d}-{int(match.group('month')):02d}-{int(match.group('day')):02d}"
        )
    for pattern in (_CURRENCY_SYMBOL_RE, _CURRENCY_WORD_RE):
        for match in pattern.finditer(value):
            amount = _normalized_amount(match.group("amount"))
            if amount:
                output["currency"].add(amount)
    for match in _PERCENT_RE.finditer(value):
        amount = _normalized_amount(match.group("amount"))
        if amount:
            output["percent"].add(amount)
    return output


def _prompt_injection_reason(source: ResearchSourceObservation) -> str | None:
    visible = "\n".join(
        (
            source.title,
            source.requested_url,
            source.observed_url,
            source.canonical_url,
            source.evidence_text,
            source.error or "",
        )
    )[:12_000]
    for label, pattern in _PROMPT_INJECTION_RULES:
        if pattern.search(visible):
            return label
    return None


def _screen_sources_before_synthesis(resident, event, state) -> None:
    meta = _meta(state)
    raw_sources = meta.get("sources") if isinstance(meta.get("sources"), list) else []
    admitted: list[dict[str, Any]] = []
    rejected = list(meta.get("rejected") if isinstance(meta.get("rejected"), list) else [])
    changed = False
    for raw in raw_sources:
        if not isinstance(raw, Mapping):
            changed = True
            continue
        source = ResearchSourceObservation.from_dict(raw)
        if source.extraction_status != "read":
            admitted.append(source.to_dict())
            continue
        reason = _prompt_injection_reason(source)
        if reason is None:
            admitted.append(source.to_dict())
            continue
        changed = True
        rejected.append(
            {
                "kind": "prompt_injection_source",
                "source_id": source.source_id,
                "canonical_url": source.canonical_url,
                "evidence_fingerprint": source.evidence_fingerprint,
                "reason": reason,
            }
        )

    if not changed:
        return
    meta["sources"] = admitted
    meta["rejected"] = rejected[-16:]
    state.data[_STATE_KEY] = meta
    resident.store.save_working_state(state)
    _persist(resident, event, meta, status="evidence_sanitized")


def _replacement_supports(replacement: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = replacement.get("supports")
    return [item for item in raw if isinstance(item, Mapping)] if isinstance(raw, list) else []


def _validate_replacement_support_quorum(meta: Mapping[str, Any]) -> None:
    sources = [
        ResearchSourceObservation.from_dict(raw)
        for raw in (meta.get("sources") if isinstance(meta.get("sources"), list) else [])
        if isinstance(raw, Mapping)
    ]
    source_by_id = {
        source.source_id: source
        for source in sources
        if source.source_id and source.extraction_status == "read"
    }
    if len(source_by_id) < _MIN_INDEPENDENT_SUPPORTS:
        raise ValueError("fewer than two prompt-safe independently extracted sources remain before mutation")

    replacements = meta.get("validated_replacements") if isinstance(meta.get("validated_replacements"), list) else []
    for replacement in replacements:
        if not isinstance(replacement, Mapping):
            raise ValueError("validated replacement is not structured")
        text = str(replacement.get("text") or "").strip()
        supports = _replacement_supports(replacement)
        source_ids = {str(item.get("source_id") or "").strip() for item in supports if str(item.get("source_id") or "").strip()}
        if len(source_ids) < _MIN_INDEPENDENT_SUPPORTS:
            raise ValueError("each replacement requires support from at least two independent prompt-safe extracted sources")

        expected = _typed_values(text)
        has_typed_anchor = any(expected.values())
        for support in supports:
            source_id = str(support.get("source_id") or "").strip()
            quote = str(support.get("quote") or "")
            source = source_by_id.get(source_id)
            if source is None:
                raise ValueError("replacement cites a source that is not prompt-safe readable evidence")
            if not quote or quote not in source.evidence_text:
                raise ValueError("replacement support quote is not an exact substring of prompt-safe extracted evidence")
            if has_typed_anchor:
                observed = _typed_values(quote)
                for kind, values in expected.items():
                    if values and not values.issubset(observed.get(kind, set())):
                        raise ValueError(
                            f"every independent support quote must contain the replacement's {kind} anchor(s)"
                        )
            elif _normalized_text(text) not in _normalized_text(quote):
                raise ValueError(
                    "text-only replacement must occur verbatim in every independent support quote"
                )


def _signal_tokens(supports: list[Mapping[str, Any]]) -> set[str]:
    joined = " ".join(str(item.get("quote") or "") for item in supports).casefold()
    return {token for token in _WORD_RE.findall(joined) if token not in _SIGNAL_STOPWORDS}


def _relevant_values(
    source: ResearchSourceObservation,
    *,
    kind: str,
    signal_tokens: set[str],
) -> dict[str, str]:
    values: dict[str, str] = {}
    field_words = _FIELD_WORDS.get(kind, ())
    for sentence in _SENTENCE_SPLIT_RE.split(source.evidence_text):
        sentence = sentence.strip()
        if not sentence:
            continue
        folded = sentence.casefold()
        if field_words and not any(word.casefold() in folded for word in field_words):
            continue
        if signal_tokens:
            sentence_tokens = set(_WORD_RE.findall(folded))
            if not (sentence_tokens & signal_tokens):
                continue
        typed = _typed_values(sentence).get(kind, set())
        for value in typed:
            values.setdefault(value, sentence[:600])
    return values


def _detect_omitted_anchor_conflicts(meta: Mapping[str, Any]) -> list[dict[str, Any]]:
    sources = [
        ResearchSourceObservation.from_dict(raw)
        for raw in (meta.get("sources") if isinstance(meta.get("sources"), list) else [])
        if isinstance(raw, Mapping)
    ]
    readable = [source for source in sources if source.extraction_status == "read" and source.source_id]
    replacements = meta.get("validated_replacements") if isinstance(meta.get("validated_replacements"), list) else []
    conflicts: list[dict[str, Any]] = []

    for replacement in replacements:
        if not isinstance(replacement, Mapping):
            continue
        target_id = str(replacement.get("target_id") or "")
        expected = _typed_values(replacement.get("text"))
        supports = _replacement_supports(replacement)
        signal_tokens = _signal_tokens(supports)
        support_by_id = {str(item.get("source_id") or ""): item for item in supports}

        for kind, expected_values in expected.items():
            if not expected_values:
                continue
            conflicting_claims: list[dict[str, str]] = []
            for source in readable:
                observed = _relevant_values(source, kind=kind, signal_tokens=signal_tokens)
                for observed_value, quote in observed.items():
                    if observed_value not in expected_values:
                        conflicting_claims.append(
                            {
                                "value": observed_value,
                                "source_id": source.source_id,
                                "quote": quote,
                            }
                        )
            if not conflicting_claims:
                continue

            expected_claim = None
            for source_id, support in support_by_id.items():
                quote = str(support.get("quote") or "")
                quote_values = _typed_values(quote).get(kind, set())
                if expected_values & quote_values:
                    expected_claim = {
                        "value": sorted(expected_values)[0],
                        "source_id": source_id,
                        "quote": quote[:600],
                    }
                    break
            claims = ([expected_claim] if expected_claim is not None else []) + conflicting_claims[:7]
            if len({claim["source_id"] for claim in claims if claim.get("source_id")}) < 2:
                continue
            conflicts.append(
                {
                    "field": f"{target_id}:{kind}",
                    "claims": claims,
                    "status": "unresolved",
                    "detected_by": "deterministic_source_anchor_consistency",
                }
            )
    return conflicts[:16]


def _gate_before_mutation(resident, event, state):
    meta = _meta(state)
    detected_conflicts = _detect_omitted_anchor_conflicts(meta)
    if detected_conflicts:
        existing = list(meta.get("conflicts") if isinstance(meta.get("conflicts"), list) else [])
        meta["conflicts"] = (existing + detected_conflicts)[:16]
        state.data[_STATE_KEY] = meta
        return _blocked(
            resident,
            event,
            state,
            meta,
            "source_conflict",
            "deterministic consistency gate observed target-relevant factual anchors that disagree across extracted sources",
            "至少一个必填 placeholder 的来源存在本地检测到的事实冲突；即使模型漏报 conflicts，也不会生成 completed DOCX。",
        )

    try:
        _validate_replacement_support_quorum(meta)
    except ValueError as exc:
        rejected = list(meta.get("rejected") if isinstance(meta.get("rejected"), list) else [])
        rejected.append({"kind": "replacement_safety_gate", "reason": str(exc)})
        meta["rejected"] = rejected[-16:]
        state.data[_STATE_KEY] = meta
        return _blocked(
            resident,
            event,
            state,
            meta,
            "invalid_document_completion_synthesis",
            str(exc),
            "补全文本未通过独立来源 quorum / prompt-safe evidence 校验；整个 DOCX 保持不变。",
        )

    _persist(resident, event, meta, status="safety_validated")
    return None


def install_document_research_completion_safety(resident) -> None:
    """Wrap only the existing E2E-12 stages with deterministic safety gates."""
    if getattr(resident, _INSTALL_MARKER, False):
        return

    original_advance = resident._advance_event_step

    def advance_event_step(event, state, *, readiness, learning_evidence, thought=None):
        entering_stage = str(state.stage or "")
        result = original_advance(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )
        if result is not None:
            return result

        if entering_stage == "document_completion_acquire" and str(state.stage or "") == "document_completion_synthesize":
            _screen_sources_before_synthesis(resident, event, state)
            return None

        if entering_stage == "document_completion_synthesize" and str(state.stage or "") == "document_completion_mutate":
            return _gate_before_mutation(resident, event, state)

        return None

    resident._advance_event_step = advance_event_step
    setattr(resident, _INSTALL_MARKER, True)
