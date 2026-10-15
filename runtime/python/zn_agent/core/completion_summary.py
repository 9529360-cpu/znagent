from __future__ import annotations

"""Rule-based Work completion summaries (P2-6).

Every Work run finalizes through ``ResidentWorkLedger._finalize_run``; that
hook builds one structured summary (goal, key decisions, deliverables,
pitfalls, open items) and stores it in the existing facts table — no parallel
memory system, no model call, no token spend.

Two rules keep summaries honest:

* A key decision is kept only when it cites fresh evidence from *this* run
  (an artifact id/path produced by the run, a message id of the run, or the
  run's own event id). A decision without such a citation is dropped and
  counted in ``dropped_decisions`` — it never enters memory as if proven.
* Every stored field passes through the shared ``public_work_text``
  redaction used by Work outcome projections, so credentials and tokens
  cannot leak into memory through a completion summary.

Later readers get the summary labelled as past memory, not fresh evidence:
each summary carries its ``evidence_refs`` so a later decision can re-check
the cited artifacts instead of trusting the summary alone.
"""

import json
import re
import unicodedata
from typing import Any

from .models import utc_now
from .privacy_choke import strip_tags
from .work_outcome_summary import public_work_text

MEMORY_CATEGORY_PROJECT_SUMMARY = "project_summary"
MEMORY_CATEGORY_PITFALL = "pitfall"
SUMMARY_KEY_PREFIX = "work_summary:"
PITFALL_KEY_PREFIX = "work_pitfall:"

MAX_STORED_SUMMARIES = 50
MAX_STORED_PITFALLS = 100
_MAX_SUMMARY_JSON_CHARS = 6000
_MAX_DECISIONS = 5
_MAX_DELIVERABLES = 12
_MAX_PITFALLS = 5
_MAX_OPEN_ITEMS = 5

_CONTINUATION_RE = re.compile(
    r"继续|接着|上次|昨天|前天|上回|之前那个|昨儿|"
    r"\byesterday\b|\bcontinue\b|\bresume\b|\bpick up\b|\blast time\b|\bwhere we left",
    re.IGNORECASE,
)
_DECISION_RE = re.compile(
    r"决定|选择|采用|改用|定为|拍板|"
    r"\bdecided\b|\bchose\b|\bchoose\b|\badopt(?:ed|ing)?\b|\bswitched\b|\bpicked\b",
    re.IGNORECASE,
)
_FAILURE_RE = re.compile(
    r"失败|错误|踩坑|受阻|卡住|行不通|没成|出问题|"
    r"\bfailed\b|\berror\b|\bblocked\b|\bpitfall\b|\bbroken\b",
    re.IGNORECASE,
)
_OPEN_RE = re.compile(
    r"未完成|待办|后续|还没|尚需|下一步|"
    r"\bTODO\b|\bremaining\b|\bpending\b|\bfollow[- ]?up\b|\bstill need",
    re.IGNORECASE,
)


def continuation_requested(text: str | None) -> bool:
    """True when the user asks to resume earlier Work (e.g. '继续昨天那个')."""
    return bool(text and _CONTINUATION_RE.search(str(text)))


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[\W_]+", " ", text)
    return " ".join(text.split())


def _bigrams(text: str) -> set[str]:
    if len(text) < 2:
        return {text} if text else set()
    return {text[i : i + 2] for i in range(len(text) - 1)}


# Short generic words must not count as a topical match ("the" appears in
# almost every summary). Only content words / CJK bigrams match.
_STOPWORDS = frozenset({
    "the", "what", "when", "where", "which", "who", "whom", "how", "why",
    "and", "for", "with", "from", "that", "this", "your", "tell", "about",
    "explain", "describe", "please", "help", "show", "give", "does", "did",
    "does", "are", "was", "were", "been", "have", "has", "will", "would",
})


def _topical_score(query: str, haystack: str) -> int:
    """Count content-word / CJK-bigram matches between query and summary text."""
    normalized_query = _normalize(query)
    normalized_haystack = _normalize(haystack)
    if not normalized_query or not normalized_haystack:
        return 0
    score = 0
    for token in normalized_query.split():
        if re.search(r"[\u4e00-\u9fff]", token):
            if any(
                bigram in normalized_haystack
                for bigram in _bigrams(token)
                if len(bigram) == 2
            ):
                score += 1
        elif len(token) >= 3 and token not in _STOPWORDS and token in normalized_haystack:
            score += 1
    return score


def _sentences(text: str) -> list[str]:
    """Split response/reason text into short, redacted sentences."""
    raw = str(text or "")
    if not raw.strip():
        return []
    parts = re.split(r"(?<=[。！？!?\n])\s*|\n+", raw)
    sentences: list[str] = []
    for part in parts:
        cleaned = public_work_text(part, limit=400)
        if cleaned:
            sentences.append(cleaned)
    return sentences


def _artifact_refs(artifacts: Any) -> tuple[list[dict[str, Any]], set[str], dict[str, str]]:
    """Normalize artifact inputs (objects or dicts) to views + evidence ids."""
    views: list[dict[str, Any]] = []
    evidence: set[str] = set()
    mention_to_ref: dict[str, str] = {}
    for artifact in list(artifacts or [])[:_MAX_DELIVERABLES]:
        if isinstance(artifact, dict):
            artifact_id = str(artifact.get("artifact_id") or "").strip()
            name = str(artifact.get("name") or "").strip()
            path = str(artifact.get("path") or "").strip()
        else:
            artifact_id = str(getattr(artifact, "artifact_id", "") or "").strip()
            name = str(getattr(artifact, "name", "") or "").strip()
            path = str(getattr(artifact, "path", "") or "").strip()
        if not artifact_id and not name and not path:
            continue
        ref = artifact_id or name or path
        evidence.add(ref)
        if name:
            evidence.add(name)
        if path:
            evidence.add(path)
        view: dict[str, Any] = {"artifact_id": ref}
        if name:
            view["name"] = public_work_text(name, limit=120)
            mention_to_ref[_normalize(name)] = ref
            for fragment in (name.rsplit("/", 1)[-1], name.rsplit("\\", 1)[-1]):
                if fragment:
                    mention_to_ref[_normalize(fragment)] = ref
        if path:
            view["path"] = public_work_text(path, limit=300)
            mention_to_ref[_normalize(path)] = ref
            basename = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            if basename:
                mention_to_ref[_normalize(basename)] = ref
        views.append(view)
    return views, evidence, mention_to_ref


def _decision_evidence(
    sentence: str, mention_to_ref: dict[str, str]
) -> str | None:
    """Return the fresh artifact ref a decision sentence cites, if any."""
    normalized = _normalize(sentence)
    if not normalized:
        return None
    best: str | None = None
    best_len = 0
    for mention, ref in mention_to_ref.items():
        if len(mention) >= 2 and mention in normalized and len(mention) > best_len:
            best, best_len = ref, len(mention)
    return best


def build_completion_summary(
    *,
    thread_id: str,
    thread_title: str,
    task: str,
    event_id: str,
    success: bool,
    response: str,
    reason: str,
    artifacts: Any = (),
    message_ids: tuple[str, ...] = (),
    decisions: tuple[dict[str, Any], ...] = (),
    outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one structured summary from a finalized run.

    ``decisions`` are caller-supplied ``{"text", "evidence_ref"}`` candidates;
    each is kept only when ``evidence_ref`` names fresh evidence from this
    run (an artifact, a run message, or ``event:<event_id>``). Decisions are
    additionally auto-extracted from response/reason sentences that both
    contain a decision verb and cite a fresh artifact by name/path.
    """
    event_ref = f"event:{event_id}"
    deliverables, evidence, mention_to_ref = _artifact_refs(artifacts)
    evidence.add(event_ref)
    for message_id in message_ids:
        if str(message_id or "").strip():
            evidence.add(str(message_id))

    sentences = _sentences(response) + _sentences(reason)
    seen_sentences: set[str] = set()
    unique_sentences: list[str] = []
    for sentence in sentences:
        if sentence not in seen_sentences:
            seen_sentences.add(sentence)
            unique_sentences.append(sentence)

    key_decisions: list[dict[str, str]] = []
    decision_texts: set[str] = set()
    dropped_decisions = 0
    for candidate in list(decisions or []):
        if not isinstance(candidate, dict):
            dropped_decisions += 1
            continue
        text = public_work_text(candidate.get("text"), limit=300)
        ref = str(candidate.get("evidence_ref") or "").strip()
        if not text or ref not in evidence:
            dropped_decisions += 1
            continue
        if text not in decision_texts:
            decision_texts.add(text)
            key_decisions.append({"text": text, "evidence_ref": ref})
    for sentence in unique_sentences:
        if len(key_decisions) >= _MAX_DECISIONS:
            break
        if not _DECISION_RE.search(sentence) or sentence in decision_texts:
            continue
        ref = _decision_evidence(sentence, mention_to_ref)
        if ref is None:
            dropped_decisions += 1
            continue
        decision_texts.add(sentence)
        key_decisions.append({"text": sentence, "evidence_ref": ref})

    pitfalls: list[dict[str, Any]] = []
    pitfall_texts: set[str] = set()
    if not success:
        fallback = public_work_text(reason or response, limit=300) or "Work 未完成"
        failure = next(
            (s for s in unique_sentences if _FAILURE_RE.search(s)), fallback
        )
        pitfalls.append({"text": failure, "evidence_refs": [event_ref]})
        pitfall_texts.add(failure)
    for sentence in unique_sentences:
        if len(pitfalls) >= _MAX_PITFALLS:
            break
        if sentence in pitfall_texts or not _FAILURE_RE.search(sentence):
            continue
        refs = [event_ref]
        ref = _decision_evidence(sentence, mention_to_ref)
        if ref is not None:
            refs.append(ref)
        pitfalls.append({"text": sentence, "evidence_refs": refs})
        pitfall_texts.add(sentence)

    open_items: list[str] = []
    if not success:
        open_items.append(
            public_work_text(f"Work 未完成，需继续处理：{reason or response}", limit=300)
            or "Work 未完成，需继续处理"
        )
    for sentence in unique_sentences:
        if len(open_items) >= _MAX_OPEN_ITEMS:
            break
        if sentence in open_items or not _OPEN_RE.search(sentence):
            continue
        open_items.append(sentence)

    summary: dict[str, Any] = {
        "memory_category": MEMORY_CATEGORY_PROJECT_SUMMARY,
        "source": "work_completion_summary",
        "thread_id": str(thread_id or "").strip(),
        "thread_title": public_work_text(thread_title, limit=120),
        "event_id": str(event_id or "").strip(),
        "goal": public_work_text(task or thread_title, limit=300),
        "success": bool(success),
        "completed_at": utc_now(),
        "key_decisions": key_decisions[:_MAX_DECISIONS],
        "deliverables": deliverables,
        "pitfalls": pitfalls,
        "open_items": open_items,
        "evidence_refs": sorted(evidence),
        "dropped_decisions": dropped_decisions,
        "interpretation": (
            "Past Work summary from memory, not fresh evidence. "
            "Each key decision cites fresh evidence from that run; "
            "re-check the cited evidence_refs before relying on a decision."
        ),
    }
    if isinstance(outcome, dict) and outcome:
        summary["outcome"] = {
            "status": public_work_text(outcome.get("status"), limit=60),
            "reason": public_work_text(outcome.get("reason"), limit=120),
            "counts": outcome.get("counts")
            if isinstance(outcome.get("counts"), dict)
            else {},
        }
    # Hard size bound: drop open items, then pitfalls, then decisions.
    while (
        len(json.dumps(summary, ensure_ascii=False)) > _MAX_SUMMARY_JSON_CHARS
        and (summary["open_items"] or summary["pitfalls"] or summary["key_decisions"])
    ):
        if summary["open_items"]:
            summary["open_items"] = summary["open_items"][:-1]
        elif summary["pitfalls"]:
            summary["pitfalls"] = summary["pitfalls"][:-1]
        else:
            summary["key_decisions"] = summary["key_decisions"][:-1]
    return summary


def save_completion_summary(memory: Any, summary: dict[str, Any]) -> dict[str, Any]:
    """Persist a summary + its pitfalls as facts in the existing facts table.

    Uses ``store.put_fact`` directly (not ``remember``): each run is a
    distinct record keyed by event id and must never supersede/merge into
    another run's summary. Prunes the oldest summaries/pitfalls past the
    retention caps so memory cannot grow without bound.

    CM-3 follow-up F1: the summary is choked here because this path
    bypasses ``StructuredMemory.remember`` (and its choke). ``build_``
    already applies ``public_work_text``, but callers may persist a
    summary built elsewhere -- the choke at the write boundary is what
    guarantees no credential-shaped value lands via this path.
    """
    summary = strip_tags(summary)
    store = memory.store
    thread_id = str(summary.get("thread_id") or "").strip()
    event_id = str(summary.get("event_id") or "").strip()
    if not event_id:
        raise ValueError("completion summary requires event_id")
    summary_key = f"{SUMMARY_KEY_PREFIX}{thread_id}:{event_id}" if thread_id else f"{SUMMARY_KEY_PREFIX}{event_id}"
    store.put_fact(summary_key, summary, aliases=(f"work_summary:{thread_id}",) if thread_id else ())
    pitfall_keys: list[str] = []
    for index, pitfall in enumerate(summary.get("pitfalls") or []):
        if not isinstance(pitfall, dict) or not str(pitfall.get("text") or "").strip():
            continue
        key = f"{PITFALL_KEY_PREFIX}{event_id}:{index}"
        store.put_fact(
            key,
            {
                "memory_category": MEMORY_CATEGORY_PITFALL,
                "source": "work_completion_summary",
                "text": pitfall["text"],
                "source_thread_id": thread_id,
                "source_event_id": event_id,
                "evidence_refs": pitfall.get("evidence_refs") or [f"event:{event_id}"],
                "created_at": summary.get("completed_at"),
            },
            aliases=(),
        )
        pitfall_keys.append(key)
    pruned = _prune(store, MEMORY_CATEGORY_PROJECT_SUMMARY, MAX_STORED_SUMMARIES)
    pruned += _prune(store, MEMORY_CATEGORY_PITFALL, MAX_STORED_PITFALLS)
    return {"summary_key": summary_key, "pitfall_keys": pitfall_keys, "pruned": pruned}


def _prune(store: Any, category: str, keep: int) -> list[str]:
    rows = [
        fact
        for fact in store.list_facts()
        if isinstance(fact.get("value"), dict)
        and fact["value"].get("memory_category") == category
    ]
    if len(rows) <= keep:
        return []
    rows.sort(key=lambda fact: (str(fact.get("updated_at") or ""), str(fact.get("key") or "")))
    pruned: list[str] = []
    for fact in rows[: len(rows) - keep]:
        store.delete_fact(fact["key"])
        pruned.append(fact["key"])
    return pruned


def recall_summary_for_event(memory: Any, event_id: str) -> dict[str, Any] | None:
    """The stored summary for one finalized run, if any."""
    wanted = str(event_id or "").strip()
    if not wanted:
        return None
    for fact in memory.store.list_facts():
        value = fact.get("value")
        if (
            isinstance(value, dict)
            and value.get("memory_category") == MEMORY_CATEGORY_PROJECT_SUMMARY
            and str(value.get("event_id") or "") == wanted
        ):
            return dict(value)
    return None


def list_completion_summaries(memory: Any, *, limit: int = 10) -> list[dict[str, Any]]:
    """Most recent project summaries, newest first."""
    rows = [
        fact
        for fact in memory.store.list_facts()
        if isinstance(fact.get("value"), dict)
        and fact["value"].get("memory_category") == MEMORY_CATEGORY_PROJECT_SUMMARY
    ]
    rows.sort(key=lambda fact: (str(fact.get("updated_at") or ""), str(fact.get("key") or "")), reverse=True)
    return [dict(fact["value"]) for fact in rows[: max(0, int(limit))]]


def list_pitfalls(memory: Any, *, limit: int = 10) -> list[dict[str, Any]]:
    """Most recent pitfall entries, newest first."""
    rows = [
        fact
        for fact in memory.store.list_facts()
        if isinstance(fact.get("value"), dict)
        and fact["value"].get("memory_category") == MEMORY_CATEGORY_PITFALL
    ]
    rows.sort(key=lambda fact: (str(fact.get("updated_at") or ""), str(fact.get("key") or "")), reverse=True)
    return [dict(fact["value"]) for fact in rows[: max(0, int(limit))]]


def recall_completion_summaries(
    memory: Any,
    query: str,
    *,
    thread_id: str | None = None,
    limit: int = 2,
) -> list[dict[str, Any]]:
    """Summaries relevant to a resume request.

    A continuation request ("继续昨天那个") returns the latest summaries,
    preferring the current thread's own summary. Any other query matches by
    bigram overlap against the summary goal/title; non-matching queries
    return nothing so summaries never leak into unrelated contexts.
    """
    count = max(0, min(5, int(limit)))
    if not count:
        return []
    summaries = list_completion_summaries(memory, limit=50)
    if not summaries:
        return []
    if thread_id:
        own = [s for s in summaries if str(s.get("thread_id") or "") == str(thread_id)]
        if own and continuation_requested(query):
            return own[:count]
    if continuation_requested(query):
        return summaries[:count]
    scored: list[tuple[int, dict[str, Any]]] = []
    for summary in summaries:
        haystack = f"{summary.get('goal') or ''} {summary.get('thread_title') or ''}"
        score = _topical_score(query, haystack)
        if score > 0:
            scored.append((score, summary))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [summary for _, summary in scored[:count]]
