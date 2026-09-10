from __future__ import annotations

"""Bounded Research & Information Work evidence owned by one ZN Work.

Search results are discovery candidates. Only successfully extracted source
documents become readable evidence. This module owns no web provider, model,
Resident, memory database, or scheduler; it only normalizes bounded evidence and
validates claim -> source support before a Research Work may complete.
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import utc_now
from .web_resource import WebDocument, WebSearchItem

MAX_SEARCH_RESULTS = 8
MAX_SELECTED_SOURCES = 5
MAX_SOURCE_TEXT_CHARS = 8_000
MAX_TOTAL_EVIDENCE_CHARS = 32_000
MAX_SOURCE_TITLE_CHARS = 500
MAX_SOURCE_URL_CHARS = 2_048
MAX_CLAIMS = 32
MAX_CONFLICTS = 16
MAX_UNKNOWN = 16
MAX_FOLLOW_UP_QUERIES = 2
MAX_CLAIM_TEXT_CHARS = 800
MAX_EVIDENCE_QUOTE_CHARS = 600
RESEARCH_BUNDLE_VERSION = 1

_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "igshid",
}
_TRACKING_QUERY_PREFIXES = ("utm_",)
_FACT_ANCHOR = re.compile(r"(?:[$€£¥]\s*)?\d[\d,._-]*(?:\.\d+)?%?", re.IGNORECASE)


def _bounded(value: object, limit: int) -> str:
    return str(value or "").strip()[: max(0, int(limit))]


def _normalized_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _canonical_host(host: str) -> str:
    value = str(host or "").strip().lower().rstrip(".")
    if value.startswith("www."):
        value = value[4:]
    return value


def canonical_source_url(url: str) -> str:
    """Return a bounded HTTP(S) source identity without tracking noise/fragment."""

    raw = _bounded(url, MAX_SOURCE_URL_CHARS)
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        _ = parsed.port
    except ValueError:
        return ""
    scheme = parsed.scheme.lower()
    if (
        scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return ""
    host = parsed.hostname.lower().rstrip(".")
    port = parsed.port
    if port is None or (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        netloc = host
    else:
        netloc = f"{host}:{port}"

    path = parsed.path or "/"
    while "//" in path:
        path = path.replace("//", "/")
    if path != "/":
        path = path.rstrip("/") or "/"

    query_pairs: list[tuple[str, str]] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        folded = key.casefold()
        if folded in _TRACKING_QUERY_KEYS or any(
            folded.startswith(prefix) for prefix in _TRACKING_QUERY_PREFIXES
        ):
            continue
        query_pairs.append((key, value))
    query_pairs.sort(key=lambda item: (item[0].casefold(), item[1]))
    return urlunsplit((scheme, netloc, path, urlencode(query_pairs, doseq=True), ""))[:MAX_SOURCE_URL_CHARS]


def source_identity(url: str) -> str:
    canonical = canonical_source_url(url)
    if not canonical:
        return ""
    return "source-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def source_domain(url: str) -> str:
    try:
        return str(urlsplit(url).hostname or "").strip().lower()[:255]
    except ValueError:
        return ""


def _published_at(*metadata: Mapping[str, Any] | None) -> str | None:
    keys = (
        "published_at",
        "publishedAt",
        "published_date",
        "publishedDate",
        "date",
        "lastModified",
        "last_modified",
    )
    for mapping in metadata:
        if not isinstance(mapping, Mapping):
            continue
        for key in keys:
            value = mapping.get(key)
            text = _bounded(value, 120)
            if text:
                return text
    return None


def _providers(*metadata: Mapping[str, Any] | None) -> tuple[str, ...]:
    values: list[str] = []
    for mapping in metadata:
        if not isinstance(mapping, Mapping):
            continue
        raw_many = mapping.get("providers")
        if isinstance(raw_many, (list, tuple)):
            candidates: Iterable[Any] = raw_many
        else:
            candidates = (mapping.get("provider"),)
        for raw in candidates:
            value = _bounded(raw, 120)
            if value and value not in values:
                values.append(value)
    return tuple(values[:8])


@dataclass(slots=True)
class ResearchEvidenceRef:
    source_id: str
    quote: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ResearchEvidenceRef":
        return cls(
            source_id=_bounded(raw.get("source_id"), 80),
            quote=_bounded(raw.get("quote"), MAX_EVIDENCE_QUOTE_CHARS),
        )


@dataclass(slots=True)
class ResearchSourceObservation:
    source_id: str
    requested_url: str
    observed_url: str
    canonical_url: str
    domain: str
    title: str
    providers: tuple[str, ...]
    captured_at: str
    published_at: str | None
    freshness_status: str
    extraction_status: str
    evidence_text: str
    evidence_fingerprint: str | None
    search_rank: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["providers"] = list(self.providers)
        return raw

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ResearchSourceObservation":
        providers = raw.get("providers")
        rank = raw.get("search_rank")
        try:
            parsed_rank = int(rank) if rank is not None and not isinstance(rank, bool) else None
        except (TypeError, ValueError):
            parsed_rank = None
        return cls(
            source_id=_bounded(raw.get("source_id"), 80),
            requested_url=_bounded(raw.get("requested_url"), MAX_SOURCE_URL_CHARS),
            observed_url=_bounded(raw.get("observed_url"), MAX_SOURCE_URL_CHARS),
            canonical_url=_bounded(raw.get("canonical_url"), MAX_SOURCE_URL_CHARS),
            domain=_bounded(raw.get("domain"), 255),
            title=_bounded(raw.get("title"), MAX_SOURCE_TITLE_CHARS),
            providers=tuple(
                _bounded(value, 120)
                for value in (providers if isinstance(providers, (list, tuple)) else ())
                if _bounded(value, 120)
            )[:8],
            captured_at=_bounded(raw.get("captured_at"), 120),
            published_at=(_bounded(raw.get("published_at"), 120) or None),
            freshness_status=_bounded(raw.get("freshness_status"), 80) or "unknown",
            extraction_status=_bounded(raw.get("extraction_status"), 80) or "failed",
            evidence_text=str(raw.get("evidence_text") or "")[:MAX_SOURCE_TEXT_CHARS],
            evidence_fingerprint=(_bounded(raw.get("evidence_fingerprint"), 128) or None),
            search_rank=parsed_rank,
            error=(_bounded(raw.get("error"), 2_000) or None),
        )


@dataclass(slots=True)
class ResearchClaim:
    text: str
    supports: tuple[ResearchEvidenceRef, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "supports": [item.to_dict() for item in self.supports]}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ResearchClaim":
        supports = raw.get("supports")
        return cls(
            text=_bounded(raw.get("text"), MAX_CLAIM_TEXT_CHARS),
            supports=tuple(
                ResearchEvidenceRef.from_dict(item)
                for item in (supports if isinstance(supports, list) else [])
                if isinstance(item, Mapping)
            )[:8],
        )


@dataclass(slots=True)
class ResearchConflictClaim:
    value: str
    source_id: str
    quote: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ResearchConflictClaim":
        return cls(
            value=_bounded(raw.get("value"), 400),
            source_id=_bounded(raw.get("source_id"), 80),
            quote=_bounded(raw.get("quote"), MAX_EVIDENCE_QUOTE_CHARS),
        )


@dataclass(slots=True)
class ResearchConflict:
    field: str
    claims: tuple[ResearchConflictClaim, ...]
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "claims": [item.to_dict() for item in self.claims],
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ResearchConflict":
        claims = raw.get("claims")
        return cls(
            field=_bounded(raw.get("field"), 300),
            claims=tuple(
                ResearchConflictClaim.from_dict(item)
                for item in (claims if isinstance(claims, list) else [])
                if isinstance(item, Mapping)
            )[:8],
            status=_bounded(raw.get("status"), 120) or "unresolved",
        )


@dataclass(slots=True)
class ResearchBundle:
    goal: str
    resolved_subject: str
    search_queries: list[str]
    sources: list[ResearchSourceObservation] = field(default_factory=list)
    claims: list[ResearchClaim] = field(default_factory=list)
    conflicts: list[ResearchConflict] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    recommendation: ResearchClaim | None = None
    artifact: dict[str, Any] | None = None
    acquisition_failures: list[str] = field(default_factory=list)
    rejected_claim_count: int = 0
    follow_up_queries: list[str] = field(default_factory=list)
    status: str = "collecting"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    version: int = RESEARCH_BUNDLE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "goal": self.goal[:2_000],
            "resolved_subject": self.resolved_subject[:600],
            "search_queries": [str(value)[:300] for value in self.search_queries[:8]],
            "sources": [item.to_dict() for item in self.sources[:MAX_SELECTED_SOURCES]],
            "claims": [item.to_dict() for item in self.claims[:MAX_CLAIMS]],
            "conflicts": [item.to_dict() for item in self.conflicts[:MAX_CONFLICTS]],
            "unknowns": [str(value)[:600] for value in self.unknowns[:MAX_UNKNOWN]],
            "recommendation": self.recommendation.to_dict() if self.recommendation else None,
            "artifact": dict(self.artifact) if isinstance(self.artifact, dict) else None,
            "acquisition_failures": [str(value)[:2_000] for value in self.acquisition_failures[:16]],
            "rejected_claim_count": max(0, int(self.rejected_claim_count)),
            "follow_up_queries": [str(value)[:300] for value in self.follow_up_queries[:MAX_FOLLOW_UP_QUERIES]],
            "status": self.status[:80],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ResearchBundle":
        sources = raw.get("sources")
        claims = raw.get("claims")
        conflicts = raw.get("conflicts")
        unknowns = raw.get("unknowns")
        followups = raw.get("follow_up_queries")
        recommendation = raw.get("recommendation")
        try:
            version = int(raw.get("version") or RESEARCH_BUNDLE_VERSION)
        except (TypeError, ValueError):
            version = RESEARCH_BUNDLE_VERSION
        return cls(
            version=version,
            goal=_bounded(raw.get("goal"), 2_000),
            resolved_subject=_bounded(raw.get("resolved_subject"), 600),
            search_queries=[
                _bounded(value, 300)
                for value in (raw.get("search_queries") if isinstance(raw.get("search_queries"), list) else [])
                if _bounded(value, 300)
            ][:8],
            sources=[
                ResearchSourceObservation.from_dict(item)
                for item in (sources if isinstance(sources, list) else [])
                if isinstance(item, Mapping)
            ][:MAX_SELECTED_SOURCES],
            claims=[
                ResearchClaim.from_dict(item)
                for item in (claims if isinstance(claims, list) else [])
                if isinstance(item, Mapping)
            ][:MAX_CLAIMS],
            conflicts=[
                ResearchConflict.from_dict(item)
                for item in (conflicts if isinstance(conflicts, list) else [])
                if isinstance(item, Mapping)
            ][:MAX_CONFLICTS],
            unknowns=[
                _bounded(value, 600)
                for value in (unknowns if isinstance(unknowns, list) else [])
                if _bounded(value, 600)
            ][:MAX_UNKNOWN],
            recommendation=(ResearchClaim.from_dict(recommendation) if isinstance(recommendation, Mapping) else None),
            artifact=(dict(raw.get("artifact")) if isinstance(raw.get("artifact"), Mapping) else None),
            acquisition_failures=[
                _bounded(value, 2_000)
                for value in (raw.get("acquisition_failures") if isinstance(raw.get("acquisition_failures"), list) else [])
                if _bounded(value, 2_000)
            ][:16],
            rejected_claim_count=max(0, int(raw.get("rejected_claim_count") or 0)),
            follow_up_queries=[
                _bounded(value, 300)
                for value in (followups if isinstance(followups, list) else [])
                if _bounded(value, 300)
            ][:MAX_FOLLOW_UP_QUERIES],
            status=_bounded(raw.get("status"), 80) or "collecting",
            created_at=_bounded(raw.get("created_at"), 120) or utc_now(),
            updated_at=_bounded(raw.get("updated_at"), 120) or utc_now(),
        )


def search_candidates(items: Iterable[WebSearchItem]) -> list[WebSearchItem]:
    """Dedupe discovery results by source identity before extraction."""

    output: list[WebSearchItem] = []
    seen: set[str] = set()
    for item in list(items)[:MAX_SEARCH_RESULTS]:
        canonical = canonical_source_url(item.url)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        output.append(item)
        if len(output) >= MAX_SELECTED_SOURCES:
            break
    return output


def build_source_observation(
    candidate: WebSearchItem,
    document: WebDocument | None,
    *,
    captured_at: str | None = None,
) -> ResearchSourceObservation:
    requested = _bounded(candidate.url, MAX_SOURCE_URL_CHARS)
    requested_canonical = canonical_source_url(requested)
    document_meta = document.metadata if document is not None else {}
    search_meta = candidate.metadata if isinstance(candidate.metadata, Mapping) else {}
    observed = _bounded(
        (document_meta.get("sourceURL") if isinstance(document_meta, Mapping) else None)
        or (document.url if document is not None else None)
        or requested,
        MAX_SOURCE_URL_CHARS,
    )
    observed_canonical = canonical_source_url(observed)
    providers = _providers(document_meta, search_meta)
    published = _published_at(document_meta, search_meta)
    captured = _bounded(captured_at, 120) or utc_now()
    status = "read"
    error = None

    if document is None:
        status = "failed"
        error = "web resource returned no extracted document"
    elif document.error:
        status = "failed"
        error = _bounded(document.error, 2_000)
    elif not requested_canonical or not observed_canonical:
        status = "failed"
        error = "source identity is not a safe HTTP(S) URL"
    elif _canonical_host(source_domain(requested_canonical)) != _canonical_host(
        source_domain(observed_canonical)
    ):
        status = "identity_mismatch"
        error = "extracted source crossed to an unexpected host during acquisition"

    content = ""
    if document is not None and status == "read":
        content = str(document.content or document.raw_content or "")[:MAX_SOURCE_TEXT_CHARS]
        if not content.strip():
            status = "failed"
            error = "source extraction returned no readable content"
            content = ""

    canonical = observed_canonical or requested_canonical
    fingerprint = (
        hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
        if content
        else None
    )
    return ResearchSourceObservation(
        source_id=source_identity(canonical),
        requested_url=requested,
        observed_url=observed,
        canonical_url=canonical,
        domain=source_domain(canonical),
        title=_bounded(
            (document.title if document is not None else None) or candidate.title,
            MAX_SOURCE_TITLE_CHARS,
        ),
        providers=providers,
        captured_at=captured,
        published_at=published,
        freshness_status="published" if published else "capture_only",
        extraction_status=status,
        evidence_text=content,
        evidence_fingerprint=fingerprint,
        search_rank=int(candidate.position or 0) or None,
        error=error,
    )


def dedupe_source_observations(
    observations: Iterable[ResearchSourceObservation],
) -> list[ResearchSourceObservation]:
    """Count one canonical source once even when multiple providers observed it."""

    merged: dict[str, ResearchSourceObservation] = {}
    order: list[str] = []
    for source in observations:
        key = source.canonical_url or source.requested_url
        if not key:
            continue
        existing = merged.get(key)
        if existing is None:
            merged[key] = source
            order.append(key)
            continue
        providers = tuple(dict.fromkeys((*existing.providers, *source.providers)))[:8]
        prefer_new = (
            existing.extraction_status != "read" and source.extraction_status == "read"
        ) or (
            existing.extraction_status == source.extraction_status == "read"
            and source.captured_at > existing.captured_at
        )
        chosen = source if prefer_new else existing
        chosen.providers = providers
        merged[key] = chosen
    output = [merged[key] for key in order]
    read_total = 0
    bounded: list[ResearchSourceObservation] = []
    chars = 0
    for item in output:
        if item.extraction_status == "read":
            if read_total >= MAX_SELECTED_SOURCES:
                continue
            remaining = MAX_TOTAL_EVIDENCE_CHARS - chars
            if remaining <= 0:
                continue
            if len(item.evidence_text) > remaining:
                item.evidence_text = item.evidence_text[:remaining]
                item.evidence_fingerprint = hashlib.sha256(
                    item.evidence_text.encode("utf-8", errors="replace")
                ).hexdigest()
            chars += len(item.evidence_text)
            read_total += 1
        bounded.append(item)
        if len(bounded) >= MAX_SELECTED_SOURCES:
            break
    return bounded


def independent_read_sources(bundle: ResearchBundle) -> list[ResearchSourceObservation]:
    return [source for source in bundle.sources if source.extraction_status == "read"]


def _source_support_valid(
    source_by_id: Mapping[str, ResearchSourceObservation],
    ref: ResearchEvidenceRef,
) -> bool:
    source = source_by_id.get(ref.source_id)
    if source is None or source.extraction_status != "read" or not ref.quote:
        return False
    evidence = _normalized_text(source.evidence_text).casefold()
    quote = _normalized_text(ref.quote).casefold()
    return bool(quote and quote in evidence)


def _claim_anchor_grounded(text: str, supports: Iterable[ResearchEvidenceRef]) -> bool:
    """Reject numeric/date/price anchors that do not occur in cited evidence."""

    anchors = {
        _normalized_text(value).casefold()
        for value in _FACT_ANCHOR.findall(text)
        if _normalized_text(value)
    }
    if not anchors:
        return True
    quoted = " ".join(_normalized_text(item.quote).casefold() for item in supports)
    return all(anchor in quoted for anchor in anchors)


def verify_claim(raw: Mapping[str, Any], sources: Iterable[ResearchSourceObservation]) -> ResearchClaim | None:
    text = _bounded(raw.get("text"), MAX_CLAIM_TEXT_CHARS)
    supports_raw = raw.get("supports")
    if not text or not isinstance(supports_raw, list):
        return None
    source_by_id = {item.source_id: item for item in sources if item.source_id}
    supports: list[ResearchEvidenceRef] = []
    seen: set[tuple[str, str]] = set()
    for item in supports_raw[:8]:
        if not isinstance(item, Mapping):
            return None
        ref = ResearchEvidenceRef.from_dict(item)
        key = (ref.source_id, _normalized_text(ref.quote).casefold())
        if key in seen:
            continue
        if not _source_support_valid(source_by_id, ref):
            return None
        seen.add(key)
        supports.append(ref)
    if not supports or not _claim_anchor_grounded(text, supports):
        return None
    return ResearchClaim(text=text, supports=tuple(supports))


def verify_conflict(
    raw: Mapping[str, Any],
    sources: Iterable[ResearchSourceObservation],
) -> ResearchConflict | None:
    field_name = _bounded(raw.get("field"), 300)
    status = _bounded(raw.get("status"), 120) or "unresolved"
    claims_raw = raw.get("claims")
    if not field_name or not isinstance(claims_raw, list):
        return None
    source_by_id = {item.source_id: item for item in sources if item.source_id}
    claims: list[ResearchConflictClaim] = []
    values: set[str] = set()
    source_ids: set[str] = set()
    for item in claims_raw[:8]:
        if not isinstance(item, Mapping):
            return None
        claim = ResearchConflictClaim.from_dict(item)
        if not claim.value or not claim.source_id or not claim.quote:
            return None
        ref = ResearchEvidenceRef(source_id=claim.source_id, quote=claim.quote)
        if not _source_support_valid(source_by_id, ref):
            return None
        if _normalized_text(claim.value).casefold() not in _normalized_text(claim.quote).casefold():
            return None
        claims.append(claim)
        values.add(_normalized_text(claim.value).casefold())
        source_ids.add(claim.source_id)
    if len(claims) < 2 or len(values) < 2 or len(source_ids) < 2:
        return None
    return ResearchConflict(field=field_name, claims=tuple(claims), status=status)


def apply_verified_synthesis(bundle: ResearchBundle, raw: Mapping[str, Any]) -> ResearchBundle:
    """Promote only model statements that map to exact observed source evidence."""

    if set(raw) != {"research_synthesis"}:
        raise ValueError("research cognition must return exactly one research_synthesis envelope")
    synthesis = raw.get("research_synthesis")
    if not isinstance(synthesis, Mapping):
        raise ValueError("research_synthesis must be an object")

    claims_raw = synthesis.get("claims")
    conflicts_raw = synthesis.get("conflicts")
    unknowns_raw = synthesis.get("unknowns")
    followups_raw = synthesis.get("follow_up_queries")
    if not isinstance(claims_raw, list) or not isinstance(conflicts_raw, list):
        raise ValueError("research_synthesis claims/conflicts must be arrays")

    accepted_claims: list[ResearchClaim] = []
    rejected = 0
    for item in claims_raw[:MAX_CLAIMS]:
        if not isinstance(item, Mapping):
            rejected += 1
            continue
        claim = verify_claim(item, bundle.sources)
        if claim is None:
            rejected += 1
        else:
            accepted_claims.append(claim)

    conflicts: list[ResearchConflict] = []
    for item in conflicts_raw[:MAX_CONFLICTS]:
        if not isinstance(item, Mapping):
            continue
        conflict = verify_conflict(item, bundle.sources)
        if conflict is not None:
            conflicts.append(conflict)

    recommendation = None
    recommendation_raw = synthesis.get("recommendation")
    if recommendation_raw is not None:
        if not isinstance(recommendation_raw, Mapping):
            rejected += 1
        else:
            recommendation = verify_claim(recommendation_raw, bundle.sources)
            if recommendation is None:
                rejected += 1

    unknowns = [
        _bounded(value, 600)
        for value in (unknowns_raw if isinstance(unknowns_raw, list) else [])
        if _bounded(value, 600)
    ][:MAX_UNKNOWN]
    followups = [
        _bounded(value, 300)
        for value in (followups_raw if isinstance(followups_raw, list) else [])
        if _bounded(value, 300)
    ][:MAX_FOLLOW_UP_QUERIES]

    bundle.claims = accepted_claims
    bundle.conflicts = conflicts
    bundle.recommendation = recommendation
    bundle.unknowns = unknowns
    bundle.follow_up_queries = followups
    bundle.rejected_claim_count += rejected
    bundle.status = "synthesized"
    bundle.updated_at = utc_now()
    return bundle


def evidence_pack(bundle: ResearchBundle) -> dict[str, Any]:
    """Return the only bounded factual context research cognition may synthesize."""

    total = 0
    sources: list[dict[str, Any]] = []
    for source in bundle.sources[:MAX_SELECTED_SOURCES]:
        remaining = max(0, MAX_TOTAL_EVIDENCE_CHARS - total)
        text = source.evidence_text[: min(MAX_SOURCE_TEXT_CHARS, remaining)]
        total += len(text)
        sources.append(
            {
                "source_id": source.source_id,
                "requested_url": source.requested_url,
                "observed_url": source.observed_url,
                "canonical_url": source.canonical_url,
                "domain": source.domain,
                "title": source.title,
                "providers": list(source.providers),
                "captured_at": source.captured_at,
                "published_at": source.published_at,
                "freshness_status": source.freshness_status,
                "extraction_status": source.extraction_status,
                "evidence_text": text,
                "error": source.error,
            }
        )
    return {
        "research_goal": bundle.goal[:2_000],
        "resolved_subject": bundle.resolved_subject[:600],
        "sources": sources,
        "known_unknowns": bundle.unknowns[:MAX_UNKNOWN],
        "bounds": {
            "max_sources": MAX_SELECTED_SOURCES,
            "max_source_chars": MAX_SOURCE_TEXT_CHARS,
            "max_total_chars": MAX_TOTAL_EVIDENCE_CHARS,
            "max_claims": MAX_CLAIMS,
        },
    }


def research_completion_errors(bundle: ResearchBundle, *, recommendation_required: bool = False) -> list[str]:
    errors: list[str] = []
    read_sources = independent_read_sources(bundle)
    if len({source.source_id for source in read_sources if source.source_id}) < 2:
        errors.append("fewer than two independent extracted sources")
    if not bundle.claims:
        errors.append("no grounded verified findings")
    if recommendation_required and bundle.recommendation is None:
        errors.append("requested recommendation has no grounded evidence support")
    for claim in bundle.claims:
        if not claim.supports:
            errors.append("verified finding lost its source support")
    if bundle.recommendation is not None and not bundle.recommendation.supports:
        errors.append("recommendation lost its source support")
    return errors


def _support_suffix(supports: Iterable[ResearchEvidenceRef]) -> str:
    ids = list(dict.fromkeys(item.source_id for item in supports if item.source_id))
    return " ".join(f"[{value}]" for value in ids)


def render_research_response(bundle: ResearchBundle) -> str:
    lines = [f"研究对象：{bundle.resolved_subject}", "", "结论："]
    for claim in bundle.claims:
        lines.append(f"- {claim.text} {_support_suffix(claim.supports)}".rstrip())
    if bundle.conflicts:
        lines.extend(["", "冲突 / 不确定性："])
        for conflict in bundle.conflicts:
            detail = "; ".join(
                f"{item.value} [{item.source_id}]" for item in conflict.claims
            )
            lines.append(f"- {conflict.field}: {detail}（{conflict.status}）")
    if bundle.unknowns:
        for item in bundle.unknowns:
            lines.append(f"- 未确认：{item}")
    if bundle.recommendation is not None:
        lines.extend(
            [
                "",
                "建议：",
                f"- {bundle.recommendation.text} {_support_suffix(bundle.recommendation.supports)}".rstrip(),
            ]
        )
    lines.extend(["", "来源："])
    for source in independent_read_sources(bundle):
        published = source.published_at or "unknown"
        providers = ", ".join(source.providers) or "unknown"
        lines.append(
            f"- [{source.source_id}] {source.title or source.domain or source.canonical_url} — "
            f"{source.observed_url} (captured={source.captured_at}; published={published}; provider={providers})"
        )
    return "\n".join(lines).strip()


def render_research_markdown(bundle: ResearchBundle, *, title: str | None = None) -> str:
    heading = _normalized_text(title or bundle.resolved_subject or "Research")[:160]
    lines = [f"# {heading}", "", "## Summary", ""]
    for claim in bundle.claims[:6]:
        lines.append(f"- {claim.text} {_support_suffix(claim.supports)}".rstrip())
    lines.extend(["", "## Key findings", ""])
    for claim in bundle.claims:
        lines.append(f"- {claim.text} {_support_suffix(claim.supports)}".rstrip())
    lines.extend(["", "## Comparison", ""])
    if bundle.conflicts:
        for conflict in bundle.conflicts:
            lines.append(f"- **{conflict.field}** ({conflict.status})")
            for item in conflict.claims:
                lines.append(f"  - {item.value} [{item.source_id}]")
    else:
        lines.append("- No material cross-source conflict was retained in this bounded evidence set.")
    lines.extend(["", "## Conflicting evidence / uncertainty", ""])
    if bundle.conflicts:
        for conflict in bundle.conflicts:
            detail = "; ".join(
                f"{item.value} [{item.source_id}]" for item in conflict.claims
            )
            lines.append(f"- {conflict.field}: {detail} — {conflict.status}")
    if bundle.unknowns:
        for item in bundle.unknowns:
            lines.append(f"- {item}")
    if not bundle.conflicts and not bundle.unknowns:
        lines.append("- None recorded from the bounded observed evidence.")
    lines.extend(["", "## Recommendation", ""])
    if bundle.recommendation is not None:
        lines.append(
            f"{bundle.recommendation.text} {_support_suffix(bundle.recommendation.supports)}".rstrip()
        )
    else:
        lines.append("No grounded recommendation was requested or verified.")
    lines.extend(["", "## Sources", ""])
    for source in independent_read_sources(bundle):
        published = source.published_at or "unknown"
        providers = ", ".join(source.providers) or "unknown"
        lines.extend(
            [
                f"- **[{source.source_id}] {source.title or source.domain or 'Source'}**",
                f"  - URL: {source.observed_url}",
                f"  - Requested URL: {source.requested_url}",
                f"  - Captured: {source.captured_at}",
                f"  - Published/updated evidence: {published}",
                f"  - Provider: {providers}",
            ]
        )
    if bundle.acquisition_failures:
        lines.extend(["", "### Source acquisition failures", ""])
        for failure in bundle.acquisition_failures:
            lines.append(f"- {failure}")
    return "\n".join(lines).rstrip() + "\n"


def parse_synthesis_json(text: str) -> dict[str, Any]:
    try:
        raw = json.loads(str(text or "").strip())
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("research cognition returned invalid JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("research cognition must return a JSON object")
    return raw
