from __future__ import annotations

"""RSS/Atom feed connector (R3): subscriptions, fetching, digests.

ZN's second real external connector, after R1 weather. The paradigm is
the same one R1 landed: trusted host configuration attached to the SAME
Action Fabric / Body as every other capability — never a parallel
plugin path, never model-supplied configuration. The differences are
shape, not mechanism:

- The read tools (list subscriptions, fetch one feed, build a digest)
  ride the Body's external read handlers, the same entry point the
  MCP/REST/CLI adapters use (the ``rss`` namespace is admitted next to
  theirs in :mod:`zn_agent.core.body`).
- The write tools (add/remove a subscription) change only ZN-local
  state, and they follow the M-7 write contract exactly, via
  :class:`ApprovedRssWriteTool`: registered ONLY when the host approves
  the tool and supplies a postcondition probe, replay identity refuses
  blind redispatch, and the runtime verifies the effect against a
  fresh store readback before calling the write verified.
- Feed fetching rides the REST adapter's injectable HTTP transport
  protocol (:class:`~zn_agent.core.openapi_rest_adapter.RestHttpClient`),
  so tests substitute a fake exactly the way R1's tests do. The
  default transport is a feed-sized sibling of the shared urllib
  client: the shared one silently truncates at 1 MB (fine for JSON
  APIs), which cuts large real-world feeds mid-element, so the feed
  transport reads to the feed bound and fails explicitly on overflow
  instead of returning a cut body.

Everything is key-free and local: subscriptions live in one JSON file
the host owns; fetching is a plain HTTP GET; parsing is stdlib
``xml.etree`` with per-entry tolerance — a malformed entry is skipped
and counted, never allowed to sink the whole feed, and a document that
is not a feed at all raises :class:`RssFeedError` with the reason.

Failure honesty: an unknown subscription, a non-2xx response, a
transport failure, a corrupt store, or a malformed document all raise
:class:`RssFeedError` (or fail the action outcome) with the concrete
reason. Entries are never invented, and an entry whose date cannot be
parsed keeps ``published_at=None`` instead of a guessed date.
"""

import hashlib
import html
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from .action_execution import ActionExecutionRuntime, ActionRequest
from .action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionFabricRegistry,
)
from .body import BodyAction, BodyActionResult, NativeBody
from .mcp_capability_adapter import (
    ApprovedMcpWriteTool,
    McpWritePostcondition,
    McpWritePostconditionProbe,
    mcp_write_replay_identity,
)
from .models import utc_now
from .openapi_rest_adapter import RestHttpClient, RestHttpResponse

__all__ = [
    "ADD_TOOL_NAME",
    "APPROVAL_KIND_FEED_SUBSCRIPTION",
    "DIGEST_ACTION_ID",
    "FETCH_ACTION_ID",
    "LIST_ACTION_ID",
    "ADD_ACTION_ID",
    "PROVIDER_ID",
    "REMOVE_ACTION_ID",
    "REMOVE_TOOL_NAME",
    "ApprovedRssWriteTool",
    "FeedEntry",
    "FeedSubscription",
    "ParsedFeed",
    "RssFeedAttachment",
    "RssFeedError",
    "RssSubscriptionStore",
    "add_subscription",
    "approved_rss_write_tools",
    "attach_rss_tools",
    "build_feed_digest",
    "fetch_feed",
    "list_subscriptions",
    "parse_feed_document",
    "remove_subscription",
    "subscription_postcondition_probes",
]

PROVIDER_ID = "feeds"
LIST_ACTION_ID = "rss.feeds.list_subscriptions"
FETCH_ACTION_ID = "rss.feeds.fetch_feed"
DIGEST_ACTION_ID = "rss.feeds.digest"
ADD_ACTION_ID = "rss.feeds.add_subscription"
REMOVE_ACTION_ID = "rss.feeds.remove_subscription"
ADD_TOOL_NAME = "add_subscription"
REMOVE_TOOL_NAME = "remove_subscription"
WRITE_TOOL_NAMES = (ADD_TOOL_NAME, REMOVE_TOOL_NAME)

#: Approval-card kind gating the two subscription write tools. The host
#: still chooses the kind on each ApprovedRssWriteTool; this is the
#: standard one the connector ships (registered in APPROVAL_KINDS).
APPROVAL_KIND_FEED_SUBSCRIPTION = "feed_subscription"

_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_MAX_URL_CHARS = 2048
_MAX_FEED_BYTES = 5_000_000
_MAX_ENTRIES_PER_FEED = 200
_MAX_DIGEST_LIMIT = 50
_MAX_SUMMARY_CHARS = 500
_MAX_TITLE_CHARS = 300
_MAX_KEYWORD_CHARS = 200
_MAX_SINCE_HOURS = 24 * 90
_ATOM_NS = "http://www.w3.org/2005/Atom"
_RDF_TAG = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF"
_TAG_RE = re.compile(r"<[^>]+>")

_RSS_WRITE_REVERSIBILITY: dict[str, str] = {
    "reversible_side_effect": "reversible",
    "potential_side_effect": "unknown",
    "irreversible_side_effect": "irreversible",
}


class RssFeedError(RuntimeError):
    """One explicit RSS connector failure; the message IS the reason."""


class ApprovedRssWriteTool(ApprovedMcpWriteTool):
    """RSS spelling of the M-7 write approval contract.

    Inherits every validation from ``ApprovedMcpWriteTool`` (stable
    tool name, explicit non-read-only effect class, validated approval
    kind, at least one named postcondition) so the approval contract
    exists in exactly one place. ``tool_name`` is one of
    ``add_subscription`` / ``remove_subscription``.
    """


# ---------------------------------------------------------------------------
# Subscription store: one local JSON file, fresh read on every access.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FeedSubscription:
    """One saved subscription: a stable name for one feed URL."""

    name: str
    url: str
    added_at: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "url": self.url, "added_at": self.added_at}


def _validate_name(name: Any) -> str:
    normalized = str(name or "").strip().lower()
    if not _NAME_RE.fullmatch(normalized):
        raise RssFeedError(
            "subscription name must be 1-64 chars of a-z, 0-9, '-' or '_', "
            f"starting with a letter or digit: {name!r}"
        )
    return normalized


def _validate_url(url: Any) -> str:
    normalized = str(url or "").strip()
    if not normalized or len(normalized) > _MAX_URL_CHARS:
        raise RssFeedError("feed URL is empty or too long")
    parts = urlsplit(normalized)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise RssFeedError(
            f"feed URL must be an absolute http(s) URL: {normalized!r}"
        )
    return normalized


class RssSubscriptionStore:
    """Subscription list persisted as one JSON file the host owns.

    Every read goes back to the file (no in-memory cache), so a
    postcondition probe reading the store observes what is actually
    persisted, independent of the write handler's success claim. Every
    write replaces the file atomically (temp file + ``os.replace``);
    a corrupt file is an explicit :class:`RssFeedError`, never a
    silent reset to empty.
    """

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> list[FeedSubscription]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError, OSError) as exc:
            raise RssFeedError(
                f"subscription store is unreadable or corrupt: {self._path}"
            ) from exc
        if not isinstance(raw, dict) or not isinstance(
            raw.get("subscriptions"), list
        ):
            raise RssFeedError(
                f"subscription store has an unexpected shape: {self._path}"
            )
        subscriptions: list[FeedSubscription] = []
        for item in raw["subscriptions"]:
            if not isinstance(item, dict):
                raise RssFeedError(
                    f"subscription store has an unexpected shape: {self._path}"
                )
            subscriptions.append(
                FeedSubscription(
                    name=_validate_name(item.get("name")),
                    url=_validate_url(item.get("url")),
                    added_at=str(item.get("added_at") or ""),
                )
            )
        return subscriptions

    def _save(self, subscriptions: Sequence[FeedSubscription]) -> None:
        payload = {
            "version": 1,
            "subscriptions": [item.to_dict() for item in subscriptions],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_name(
            f".{self._path.name}.tmp-{os.getpid()}"
        )
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, self._path)

    def list(self) -> list[FeedSubscription]:
        """All subscriptions, sorted by name; reads the file fresh."""
        with self._lock:
            return sorted(self._load(), key=lambda item: item.name)

    def get(self, name: str) -> FeedSubscription | None:
        normalized = _validate_name(name)
        for item in self.list():
            if item.name == normalized:
                return item
        return None

    def add(self, name: str, url: str) -> FeedSubscription:
        normalized_name = _validate_name(name)
        normalized_url = _validate_url(url)
        with self._lock:
            current = self._load()
            if any(item.name == normalized_name for item in current):
                raise RssFeedError(
                    f"subscription already exists: {normalized_name}"
                )
            created = FeedSubscription(
                name=normalized_name,
                url=normalized_url,
                added_at=utc_now(),
            )
            self._save([*current, created])
            return created

    def remove(self, name: str) -> FeedSubscription:
        normalized = _validate_name(name)
        with self._lock:
            current = self._load()
            removed = [item for item in current if item.name == normalized]
            if not removed:
                raise RssFeedError(f"unknown subscription: {normalized}")
            self._save(
                [item for item in current if item.name != normalized]
            )
            return removed[0]


# ---------------------------------------------------------------------------
# Feed parsing: RSS 2.0 / RSS 1.0 (RDF) / Atom, per-entry tolerance.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FeedEntry:
    """One parsed feed entry; missing fields stay empty/None, never guessed."""

    title: str = ""
    link: str = ""
    summary: str = ""
    published_at: str | None = None
    entry_id: str = ""
    author: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "link": self.link,
            "summary": self.summary,
            "published_at": self.published_at,
            "entry_id": self.entry_id,
            "author": self.author,
        }


@dataclass(frozen=True, slots=True)
class ParsedFeed:
    """One parsed feed document plus its per-entry tolerance accounting."""

    title: str = ""
    link: str = ""
    description: str = ""
    format: str = ""
    entries: tuple[FeedEntry, ...] = ()
    skipped_entries: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "link": self.link,
            "description": self.description,
            "format": self.format,
            "entry_count": len(self.entries),
            "skipped_entries": self.skipped_entries,
        }


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _child_text(element: ET.Element, *names: str) -> str:
    for child in element:
        if _local_name(child.tag) in names:
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return ""


def _clean_text(raw: str, *, limit: int) -> str:
    text = _TAG_RE.sub(" ", str(raw or ""))
    text = html.unescape(text)
    text = " ".join(text.split())
    return text[:limit]


def _parse_date(raw: str) -> str | None:
    """RFC 822 or ISO 8601 -> UTC ISO string; unparseable stays None."""
    text = str(raw or "").strip()
    if not text:
        return None
    parsed: datetime | None = None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _rss_entry(item: ET.Element) -> FeedEntry:
    return FeedEntry(
        title=_clean_text(_child_text(item, "title"), limit=_MAX_TITLE_CHARS),
        link=_child_text(item, "link"),
        summary=_clean_text(
            _child_text(item, "description", "encoded"),
            limit=_MAX_SUMMARY_CHARS,
        ),
        published_at=_parse_date(
            _child_text(item, "pubDate", "date")
        ),
        entry_id=_child_text(item, "guid", "id"),
        author=_clean_text(
            _child_text(item, "author", "creator"), limit=120
        ),
    )


def _atom_link(entry: ET.Element) -> str:
    links = [
        child
        for child in entry
        if _local_name(child.tag) == "link" and child.get("href")
    ]
    for link in links:
        if (link.get("rel") or "alternate") == "alternate":
            return str(link.get("href"))
    return str(links[0].get("href")) if links else ""


def _atom_entry(entry: ET.Element) -> FeedEntry:
    return FeedEntry(
        title=_clean_text(_child_text(entry, "title"), limit=_MAX_TITLE_CHARS),
        link=_atom_link(entry),
        summary=_clean_text(
            _child_text(entry, "summary", "content"),
            limit=_MAX_SUMMARY_CHARS,
        ),
        published_at=_parse_date(
            _child_text(entry, "published", "updated")
        ),
        entry_id=_child_text(entry, "id"),
        author=_clean_text(
            _child_text(entry, "author"), limit=120
        ),
    )


def _collect_entries(
    elements: Sequence[ET.Element],
    builder: Any,
) -> tuple[list[FeedEntry], int]:
    entries: list[FeedEntry] = []
    skipped = 0
    for element in elements:
        try:
            entry = builder(element)
        except Exception:
            skipped += 1
            continue
        if not entry.title and not entry.link:
            # An entry with neither a title nor a link carries nothing a
            # reader can use or cite; count it as skipped, never invent.
            skipped += 1
            continue
        entries.append(entry)
        if len(entries) >= _MAX_ENTRIES_PER_FEED:
            break
    return entries, skipped


def parse_feed_document(data: bytes) -> ParsedFeed:
    """Parse one RSS 2.0 / RSS 1.0 / Atom document with entry tolerance.

    Raises :class:`RssFeedError` when the payload is not a feed at
    all (not XML, an XML document of another kind, an oversized
    document, or one carrying entity declarations, which this
    connector refuses outright). Individual bad entries never raise:
    they are skipped and counted on the returned document.
    """
    if not data:
        raise RssFeedError("feed document is empty")
    if len(data) > _MAX_FEED_BYTES:
        raise RssFeedError(
            f"feed document too large: {len(data)} bytes "
            f"(limit {_MAX_FEED_BYTES})"
        )
    if b"<!ENTITY" in data:
        raise RssFeedError(
            "feed document declares XML entities; refused"
        )
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise RssFeedError(
            f"feed document is not well-formed XML: {exc}"
        ) from exc

    root_name = _local_name(root.tag)
    if root_name == "rss":
        channel = next(
            (child for child in root if _local_name(child.tag) == "channel"),
            None,
        )
        if channel is None:
            raise RssFeedError("RSS document has no channel element")
        items = [
            child for child in channel if _local_name(child.tag) == "item"
        ]
        entries, skipped = _collect_entries(items, _rss_entry)
        return ParsedFeed(
            title=_clean_text(
                _child_text(channel, "title"), limit=_MAX_TITLE_CHARS
            ),
            link=_child_text(channel, "link"),
            description=_clean_text(
                _child_text(channel, "description"), limit=_MAX_SUMMARY_CHARS
            ),
            format="rss2",
            entries=tuple(entries),
            skipped_entries=skipped,
        )
    if root_name == "feed":
        items = [
            child for child in root if _local_name(child.tag) == "entry"
        ]
        entries, skipped = _collect_entries(items, _atom_entry)
        return ParsedFeed(
            title=_clean_text(
                _child_text(root, "title"), limit=_MAX_TITLE_CHARS
            ),
            link=_atom_link(root),
            description=_clean_text(
                _child_text(root, "subtitle"), limit=_MAX_SUMMARY_CHARS
            ),
            format="atom",
            entries=tuple(entries),
            skipped_entries=skipped,
        )
    if root.tag == _RDF_TAG or root_name == "RDF":
        items = [
            child for child in root if _local_name(child.tag) == "item"
        ]
        channel = next(
            (child for child in root if _local_name(child.tag) == "channel"),
            None,
        )
        entries, skipped = _collect_entries(items, _rss_entry)
        return ParsedFeed(
            title=_clean_text(
                _child_text(channel, "title") if channel is not None else "",
                limit=_MAX_TITLE_CHARS,
            ),
            link=_child_text(channel, "link") if channel is not None else "",
            description="",
            format="rss1",
            entries=tuple(entries),
            skipped_entries=skipped,
        )
    raise RssFeedError(
        f"document is not an RSS or Atom feed (root element: {root_name})"
    )


# ---------------------------------------------------------------------------
# Fetching through the shared injectable HTTP transport.
# ---------------------------------------------------------------------------


class _UrllibFeedHttpClient:
    """Stdlib ``urllib`` transport sized for feed documents.

    Implements the REST adapter's ``RestHttpClient`` protocol so any
    conforming transport can be injected instead. Unlike the shared
    REST transport (1 MB silent truncation, sized for JSON APIs), this
    one reads to the feed bound and raises on overflow: a large feed
    is an explicit failure, never a silently cut body that later
    masquerades as malformed XML. HTTP error statuses are returned as
    responses, mirroring the shared transport; only transport failures
    raise.
    """

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any],
        headers: Mapping[str, str],
        json_body: Mapping[str, Any] | None,
        timeout_seconds: float,
    ) -> RestHttpResponse:
        if str(method or "GET").upper() != "GET":
            raise RuntimeError("feed transport only performs GET")
        if json_body is not None:
            raise RuntimeError("feed transport sends no request body")
        query = urlencode(
            {str(key): str(value) for key, value in dict(params).items()},
            doseq=False,
        )
        full_url = f"{url}?{query}" if query else url
        request = Request(full_url, method="GET")
        for name, value in dict(headers).items():
            request.add_header(str(name), str(value))
        try:
            with urlopen(request, timeout=float(timeout_seconds)) as response:
                raw = response.read(_MAX_FEED_BYTES + 1)
                if len(raw) > _MAX_FEED_BYTES:
                    raise RuntimeError(
                        f"feed document exceeds {_MAX_FEED_BYTES} bytes"
                    )
                return RestHttpResponse(
                    status_code=int(response.status),
                    headers={
                        str(k): str(v) for k, v in response.headers.items()
                    },
                    body=bytes(raw),
                )
        except HTTPError as exc:
            raw = exc.read(_MAX_FEED_BYTES + 1)
            return RestHttpResponse(
                status_code=int(exc.code),
                headers={str(k): str(v) for k, v in exc.headers.items()},
                body=bytes(raw[:_MAX_FEED_BYTES]),
            )
        except URLError as exc:
            raise RuntimeError(
                f"feed transport failed: {type(exc).__name__}"
            ) from exc


def _fetch_document(
    client: RestHttpClient,
    url: str,
    *,
    timeout_seconds: float,
) -> bytes:
    try:
        response = client.request(
            "get",
            url,
            params={},
            headers={
                "accept": (
                    "application/rss+xml, application/atom+xml, "
                    "application/xml, text/xml"
                ),
                "user-agent": "ZN RSS feed connector",
            },
            json_body=None,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        raise RssFeedError(
            f"feed fetch failed for {url}: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(response, RestHttpResponse):
        raise RssFeedError("feed HTTP client returned a malformed response")
    if not 200 <= response.status_code < 300:
        raise RssFeedError(
            f"feed fetch failed with HTTP {response.status_code} for {url}"
        )
    return response.body


# ---------------------------------------------------------------------------
# Host-side approval helpers: the standard write pair + fresh-read probes.
# ---------------------------------------------------------------------------


def approved_rss_write_tools() -> tuple[ApprovedRssWriteTool, ...]:
    """The standard host approval for both subscription write tools."""
    return (
        ApprovedRssWriteTool(
            tool_name=ADD_TOOL_NAME,
            effect_class="reversible_side_effect",
            approval_kind=APPROVAL_KIND_FEED_SUBSCRIPTION,
            verification=(
                "subscription present in a fresh store readback "
                "with the dispatched URL",
            ),
        ),
        ApprovedRssWriteTool(
            tool_name=REMOVE_TOOL_NAME,
            effect_class="reversible_side_effect",
            approval_kind=APPROVAL_KIND_FEED_SUBSCRIPTION,
            verification=(
                "subscription absent from a fresh store readback",
            ),
        ),
    )


def subscription_postcondition_probes(
    store: RssSubscriptionStore,
) -> dict[str, McpWritePostconditionProbe]:
    """Fresh-readback probes for both subscription write tools.

    Each probe re-reads the store file (the store never caches), so
    the observation is independent of the write handler's own success
    claim — the local-readback path the M-7 probe protocol allows.
    """

    def add_probe(
        args: Mapping[str, Any], result: BodyActionResult
    ) -> McpWritePostcondition:
        name = str(args.get("name") or "")
        url = str(args.get("url") or "")
        try:
            fresh = store.get(name)
        except RssFeedError as exc:
            return McpWritePostcondition(False, str(exc), {"name": name})
        ok = fresh is not None and fresh.url == url
        return McpWritePostcondition(
            ok,
            (
                "subscription present in store readback"
                if ok
                else "subscription missing or URL differs in store readback"
            ),
            {"name": name, "url": url},
        )

    def remove_probe(
        args: Mapping[str, Any], result: BodyActionResult
    ) -> McpWritePostcondition:
        name = str(args.get("name") or "")
        try:
            fresh = store.get(name)
        except RssFeedError as exc:
            return McpWritePostcondition(False, str(exc), {"name": name})
        ok = fresh is None
        return McpWritePostcondition(
            ok,
            (
                "subscription absent from store readback"
                if ok
                else "subscription still present in store readback"
            ),
            {"name": name},
        )

    return {ADD_TOOL_NAME: add_probe, REMOVE_TOOL_NAME: remove_probe}


# ---------------------------------------------------------------------------
# Attachment: Fabric descriptors + Body handlers, detach, verifications.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RssFeedAttachment:
    """Detach removes every RSS tool from the Fabric and Body at once."""

    fabric: ActionFabricRegistry
    body: NativeBody
    descriptors: tuple[ActionDescriptor, ...]
    probes: Mapping[str, McpWritePostconditionProbe]
    disabled_write_operations: tuple[str, ...] = ()
    _closed: bool = False

    def detach(self) -> None:
        if self._closed:
            return
        self._closed = True
        for descriptor in self.descriptors:
            self.fabric.unregister(descriptor.action_id)
            assert descriptor.body_action_kind is not None
            if descriptor.effect_class == "read_only":
                self.body.unregister_external_read_handler(
                    descriptor.body_action_kind
                )
            else:
                self.body.unregister_external_write_handler(
                    descriptor.body_action_kind
                )

    def register_verifications(self, runtime: Any) -> None:
        """Wire each approved write tool's probe into a runtime.

        Same fail-closed rule as the M-7 contract: without this
        wiring the runtime reports "no independent postcondition
        verifier" instead of treating Body success as proof.
        """
        for descriptor in self.descriptors:
            if descriptor.effect_class == "read_only":
                continue
            probe = self.probes[descriptor.action_id]
            runtime.register_verification(
                descriptor.action_id,
                observe=_rss_write_observer(probe),
                verify=_rss_write_verifier,
            )


def _rss_write_observer(
    probe: McpWritePostconditionProbe,
) -> Any:
    from .action_execution import ActionObservation

    def observe(request: Any, result: BodyActionResult | None) -> Any:
        if result is None:
            raise RuntimeError("RSS write postcondition needs a Body result")
        outcome = probe(dict(request.args or {}), result)
        if not isinstance(outcome, McpWritePostcondition):
            raise ValueError(
                "RSS write postcondition probe returned a malformed outcome"
            )
        return ActionObservation(
            request.action_id,
            "rss_write_postcondition",
            data={
                "verified": bool(outcome.verified),
                "reason": outcome.reason,
                "evidence": dict(outcome.evidence or {}),
            },
            observed_at=result.completed_at or utc_now(),
        )

    return observe


def _rss_write_verifier(
    request: Any, observation: Any, result: BodyActionResult | None
) -> Any:
    from .action_execution import ActionVerification

    data = dict(observation.data or {})
    if data.get("verified") is True:
        return ActionVerification(
            "verified",
            str(data.get("reason") or "RSS write postcondition verified"),
            evidence={
                "body_action_id": result.action_id if result is not None else None,
                "postcondition": data.get("evidence") or {},
            },
            observed_at=observation.observed_at,
        )
    return ActionVerification(
        "failed",
        str(data.get("reason") or "RSS write postcondition not met"),
        evidence={
            "body_action_id": result.action_id if result is not None else None,
            "postcondition": data.get("evidence") or {},
        },
        observed_at=observation.observed_at,
    )


def _kind_for(action_id: str, *, write: bool) -> str:
    digest = hashlib.sha256(action_id.encode("utf-8")).hexdigest()[:24]
    return f"zn_rss_{'write' if write else 'read'}_{digest}"


def _limit_arg(args: Mapping[str, Any], *, default: int = 20) -> int:
    raw = args.get("limit", default)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise RssFeedError("limit must be an integer")
    if not 1 <= raw <= _MAX_DIGEST_LIMIT:
        raise RssFeedError(f"limit must be between 1 and {_MAX_DIGEST_LIMIT}")
    return raw


def attach_rss_tools(
    fabric: ActionFabricRegistry,
    body: NativeBody,
    *,
    store: RssSubscriptionStore,
    http_client: RestHttpClient | None = None,
    timeout_seconds: float = 15.0,
    approved_write_tools: Sequence[ApprovedRssWriteTool] = (),
    postcondition_probes: Mapping[str, McpWritePostconditionProbe] | None = None,
) -> RssFeedAttachment:
    """Attach the RSS feed tools to a Body/Fabric pair.

    Reads are always attached. The two subscription writes are
    attached ONLY when the host approves them here (per-tool
    :class:`ApprovedRssWriteTool` plus exactly one postcondition probe
    each); unapproved writes stay unregistered and uncallable, and are
    listed on the attachment as ``disabled_write_operations``.
    """
    if not isinstance(store, RssSubscriptionStore):
        raise TypeError("store must be an RssSubscriptionStore")
    if not 1.0 <= float(timeout_seconds) <= 60.0:
        raise ValueError("RSS timeout must be between 1 and 60 seconds")
    timeout = float(timeout_seconds)
    client: RestHttpClient = http_client or _UrllibFeedHttpClient()

    approved = tuple(approved_write_tools or ())
    if len(approved) > len(WRITE_TOOL_NAMES):
        raise ValueError("approved RSS write tools must be a bounded allowlist")
    approved_names = [item.tool_name for item in approved]
    if len(set(approved_names)) != len(approved_names):
        raise ValueError("approved RSS write tools must be unique")
    unknown_approved = sorted(set(approved_names) - set(WRITE_TOOL_NAMES))
    if unknown_approved:
        raise ValueError(
            "approved RSS write tools must name subscription write tools: "
            f"{unknown_approved}"
        )
    probes = dict(postcondition_probes or {})
    if set(probes) != set(approved_names):
        raise ValueError(
            "RSS write tools need exactly one postcondition probe each: "
            "missing or unapproved probes are refused"
        )
    for probe in probes.values():
        if not callable(probe):
            raise TypeError("RSS write postcondition probe must be callable")
    approvals = {item.tool_name: item for item in approved}
    disabled = tuple(
        sorted(set(WRITE_TOOL_NAMES) - set(approved_names))
    )

    completed_identities: set[str] = set()

    # -- read handlers ------------------------------------------------------

    def _result(
        action: BodyAction, started: str, payload: Mapping[str, Any], *, external: bool
    ) -> BodyActionResult:
        data = dict(payload)
        if external:
            data["untrusted_external_evidence"] = True
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            output=json.dumps(payload, ensure_ascii=False),
            data=data,
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

    def _resolve_feed_url(args: Mapping[str, Any]) -> tuple[str, str]:
        name = str(args.get("name") or "").strip()
        url = str(args.get("url") or "").strip()
        if bool(name) == bool(url):
            raise RssFeedError(
                "fetch_feed needs exactly one of name or url"
            )
        if name:
            subscription = store.get(name)
            if subscription is None:
                raise RssFeedError(f"unknown subscription: {name}")
            return subscription.name, subscription.url
        return "", _validate_url(url)

    def _fetch_parsed(url: str) -> ParsedFeed:
        return parse_feed_document(
            _fetch_document(client, url, timeout_seconds=timeout)
        )

    def handle_list(action: BodyAction, started: str) -> BodyActionResult:
        subscriptions = store.list()
        payload = {
            "subscriptions": [item.to_dict() for item in subscriptions],
            "count": len(subscriptions),
        }
        return _result(action, started, payload, external=False)

    def handle_fetch(action: BodyAction, started: str) -> BodyActionResult:
        limit = _limit_arg(action.args)
        name, url = _resolve_feed_url(action.args)
        parsed = _fetch_parsed(url)
        payload = {
            "subscription": name,
            "source_url": url,
            "feed": parsed.to_dict(),
            "entries": [entry.to_dict() for entry in parsed.entries[:limit]],
            "fetched_at": utc_now(),
        }
        return _result(action, started, payload, external=True)

    def handle_digest(action: BodyAction, started: str) -> BodyActionResult:
        limit = _limit_arg(action.args)
        keyword = str(action.args.get("keyword") or "").strip()
        if len(keyword) > _MAX_KEYWORD_CHARS:
            raise RssFeedError("keyword is too long")
        since_raw = action.args.get("since_hours")
        since_hours: float | None = None
        if since_raw is not None:
            if isinstance(since_raw, bool) or not isinstance(
                since_raw, (int, float)
            ):
                raise RssFeedError("since_hours must be a number")
            since_hours = float(since_raw)
            if not 0 < since_hours <= _MAX_SINCE_HOURS:
                raise RssFeedError(
                    f"since_hours must be within (0, {_MAX_SINCE_HOURS}]"
                )
        names_raw = action.args.get("names")
        subscriptions = store.list()
        if names_raw is not None:
            if not isinstance(names_raw, list) or not all(
                isinstance(item, str) for item in names_raw
            ):
                raise RssFeedError("names must be a list of subscription names")
            wanted = [_validate_name(item) for item in names_raw]
            by_name = {item.name: item for item in subscriptions}
            missing = [name for name in wanted if name not in by_name]
            if missing:
                raise RssFeedError(
                    f"unknown subscription: {missing[0]}"
                )
            subscriptions = [by_name[name] for name in wanted]

        cutoff: datetime | None = None
        if since_hours is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        needle = keyword.lower()
        merged: list[dict[str, Any]] = []
        feed_errors: list[dict[str, str]] = []
        undated_excluded = 0
        for subscription in subscriptions:
            try:
                parsed = _fetch_parsed(subscription.url)
            except RssFeedError as exc:
                # One broken feed must not sink the digest; it is
                # reported in feed_errors instead of silently dropped.
                feed_errors.append(
                    {
                        "name": subscription.name,
                        "url": subscription.url,
                        "error": str(exc),
                    }
                )
                continue
            for entry in parsed.entries:
                if cutoff is not None:
                    if entry.published_at is None:
                        undated_excluded += 1
                        continue
                    if (
                        datetime.fromisoformat(entry.published_at) < cutoff
                    ):
                        continue
                if needle:
                    haystack = f"{entry.title}\n{entry.summary}".lower()
                    if needle not in haystack:
                        continue
                merged.append(
                    {
                        **entry.to_dict(),
                        "feed_name": subscription.name,
                        "feed_url": subscription.url,
                    }
                )
        merged.sort(
            key=lambda item: item["published_at"] or "", reverse=True
        )
        payload = {
            "entries": merged[:limit],
            "entry_count": len(merged[:limit]),
            "feeds_checked": len(subscriptions),
            "feed_errors": feed_errors,
            "keyword": keyword,
            "since_hours": since_hours,
            "undated_entries_excluded": undated_excluded,
            "generated_at": utc_now(),
        }
        return _result(action, started, payload, external=True)

    # -- write handlers (M-7 contract: replay identity + store effect) ------

    def _write_handler(tool_name: str) -> Any:
        def handle(action: BodyAction, started: str) -> BodyActionResult:
            identity = mcp_write_replay_identity(
                provider_id=PROVIDER_ID,
                tool_name=tool_name,
                args=action.args,
                event_id=action.event_id,
            )
            if identity in completed_identities:
                raise RuntimeError(
                    "RSS write replay refused: this exact write occurrence "
                    "already reached the subscription store; re-observe "
                    "with the postcondition probe instead of redispatching"
                )
            if tool_name == ADD_TOOL_NAME:
                created = store.add(
                    action.args.get("name"), action.args.get("url")
                )
                payload = {"subscription": created.to_dict()}
            else:
                removed = store.remove(action.args.get("name"))
                payload = {"removed": removed.to_dict()}
            # The store effect has been applied and persisted; record
            # the identity before reporting success (M-7 replay rule).
            completed_identities.add(identity)
            data = dict(payload)
            data["replay_identity"] = identity
            data["replayed"] = False
            return BodyActionResult(
                action_id=action.action_id,
                kind=action.kind,
                success=True,
                output=json.dumps(payload, ensure_ascii=False),
                data=data,
                event_id=action.event_id,
                started_at=started,
                completed_at=utc_now(),
            )

        return handle

    # -- descriptors ---------------------------------------------------------

    read_schema_list: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    read_schema_fetch: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Subscription name to fetch",
            },
            "url": {
                "type": "string",
                "description": "Feed URL to fetch directly (alternative to name)",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum entries to return (1-50)",
            },
        },
        "additionalProperties": False,
    }
    read_schema_digest: dict[str, Any] = {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "Case-insensitive substring matched on title and summary",
            },
            "since_hours": {
                "type": "number",
                "description": "Only entries published within this many hours",
            },
            "names": {
                "type": "array",
                "description": "Subscription names to include (default: all)",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum entries to return (1-50)",
            },
        },
        "additionalProperties": False,
    }

    prepared: list[tuple[ActionDescriptor, Any, bool]] = [
        (
            ActionDescriptor(
                action_id=LIST_ACTION_ID,
                provider=f"zn.rss.{PROVIDER_ID}",
                description=(
                    "List the RSS/Atom feed subscriptions saved in ZN's "
                    "local subscription store"
                ),
                body_action_kind=_kind_for(LIST_ACTION_ID, write=False),
                input_schema=read_schema_list,
                effect_class="read_only",
                required_authority=("explicit_rss_feed_connector_approval",),
                sensitivity="normal",
                preconditions=("host-configured RSS subscription store",),
                verification=(
                    "fresh read-only Body observation; not goal completion",
                ),
                replay_semantics="read_only",
                tags=("rss", "feeds", "read_only", PROVIDER_ID),
            ),
            handle_list,
            True,
        ),
        (
            ActionDescriptor(
                action_id=FETCH_ACTION_ID,
                provider=f"zn.rss.{PROVIDER_ID}",
                description=(
                    "Fetch and parse one RSS/Atom feed (by subscription "
                    "name or URL) and return its latest entries"
                ),
                body_action_kind=_kind_for(FETCH_ACTION_ID, write=False),
                input_schema=read_schema_fetch,
                effect_class="read_only",
                required_authority=("explicit_rss_feed_connector_approval",),
                sensitivity="external",
                preconditions=("host-configured RSS subscription store",),
                verification=(
                    "fresh read-only Body observation; not goal completion",
                ),
                replay_semantics="read_only",
                tags=("rss", "feeds", "read_only", PROVIDER_ID),
            ),
            handle_fetch,
            True,
        ),
        (
            ActionDescriptor(
                action_id=DIGEST_ACTION_ID,
                provider=f"zn.rss.{PROVIDER_ID}",
                description=(
                    "Fetch all (or named) subscriptions and merge their "
                    "entries into one digest filtered by recency and/or "
                    "keyword, newest first"
                ),
                body_action_kind=_kind_for(DIGEST_ACTION_ID, write=False),
                input_schema=read_schema_digest,
                effect_class="read_only",
                required_authority=("explicit_rss_feed_connector_approval",),
                sensitivity="external",
                preconditions=("host-configured RSS subscription store",),
                verification=(
                    "fresh read-only Body observation; not goal completion",
                ),
                replay_semantics="read_only",
                tags=("rss", "feeds", "read_only", PROVIDER_ID),
            ),
            handle_digest,
            True,
        ),
    ]

    write_schemas: dict[str, dict[str, Any]] = {
        ADD_TOOL_NAME: {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Stable subscription name (a-z, 0-9, '-', '_')",
                },
                "url": {
                    "type": "string",
                    "description": "Absolute http(s) feed URL",
                },
            },
            "required": ["name", "url"],
            "additionalProperties": False,
        },
        REMOVE_TOOL_NAME: {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Subscription name to remove",
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    }
    write_action_ids = {
        ADD_TOOL_NAME: ADD_ACTION_ID,
        REMOVE_TOOL_NAME: REMOVE_ACTION_ID,
    }
    write_descriptions = {
        ADD_TOOL_NAME: (
            "Add one subscription to ZN's local RSS/Atom subscription "
            "store (host-approved write)"
        ),
        REMOVE_TOOL_NAME: (
            "Remove one subscription from ZN's local RSS/Atom "
            "subscription store (host-approved write)"
        ),
    }
    for tool_name in WRITE_TOOL_NAMES:
        approval = approvals.get(tool_name)
        if approval is None:
            continue  # Default disabled: never registered, never callable.
        action_id = write_action_ids[tool_name]
        prepared.append(
            (
                ActionDescriptor(
                    action_id=action_id,
                    provider=f"zn.rss.{PROVIDER_ID}",
                    description=write_descriptions[tool_name],
                    body_action_kind=_kind_for(action_id, write=True),
                    input_schema=write_schemas[tool_name],
                    effect_class=approval.effect_class,
                    required_authority=(
                        "explicit_rss_feed_connector_approval",
                        "explicit_rss_write_tool_approval",
                    ),
                    sensitivity="normal",
                    preconditions=(
                        "host-configured RSS subscription store",
                        "per-tool explicit write approval",
                        "stable event_id for the write occurrence",
                    ),
                    postconditions=tuple(approval.verification),
                    verification=(
                        "independent postcondition probe must verify the "
                        "effect; Body success is dispatch evidence only",
                        *approval.verification,
                    ),
                    reversibility=_RSS_WRITE_REVERSIBILITY[
                        approval.effect_class
                    ],
                    replay_semantics="verify_before_replay",
                    tags=(
                        "rss",
                        "feeds",
                        "rss_write",
                        PROVIDER_ID,
                        f"approval:{approval.approval_kind}",
                    ),
                ),
                _write_handler(tool_name),
                False,
            )
        )

    for descriptor, _, _ in prepared:
        if fabric.descriptor(descriptor.action_id) is not None:
            raise ValueError(
                f"Action Fabric already owns action {descriptor.action_id}"
            )
        assert descriptor.body_action_kind is not None
        handlers = (
            body._external_read_handlers
            if descriptor.effect_class == "read_only"
            else body._external_write_handlers
        )
        if descriptor.body_action_kind in handlers:
            raise ValueError("Body extension identifier collision")

    registered: list[ActionDescriptor] = []
    attached_kinds: list[tuple[str, bool]] = []
    try:
        for descriptor, handler, is_read in prepared:
            assert descriptor.body_action_kind is not None
            if is_read:
                body.register_external_read_handler(
                    descriptor.body_action_kind, handler
                )
            else:
                body.register_external_write_handler(
                    descriptor.body_action_kind, handler
                )
            attached_kinds.append((descriptor.body_action_kind, is_read))
            fabric.register(
                descriptor,
                availability_probe=lambda item, path=str(store.path): (
                    ActionAvailability(
                        item.action_id,
                        "available",
                        reason="RSS feed connector configured",
                        evidence={
                            "provider_id": PROVIDER_ID,
                            "store": path,
                        },
                    )
                ),
            )
            registered.append(descriptor)
    except Exception:
        for descriptor in registered:
            fabric.unregister(descriptor.action_id)
        for kind, was_read in attached_kinds:
            if was_read:
                body.unregister_external_read_handler(kind)
            else:
                body.unregister_external_write_handler(kind)
        raise
    return RssFeedAttachment(
        fabric=fabric,
        body=body,
        descriptors=tuple(registered),
        probes={
            write_action_ids[tool_name]: probes[tool_name]
            for tool_name in approved_names
        },
        disabled_write_operations=disabled,
    )


# ---------------------------------------------------------------------------
# Thin helpers: the normal capability path, like R1's lookup_weather.
# ---------------------------------------------------------------------------


def _execute_json(
    runtime: ActionExecutionRuntime,
    action_id: str,
    args: Mapping[str, Any],
    *,
    event_id: str,
    stage: str,
) -> dict[str, Any]:
    outcome = runtime.execute(
        ActionRequest(action_id, dict(args), event_id=event_id)
    )
    if not outcome.success or outcome.body_result is None:
        reason = outcome.error or "no result returned"
        raise RssFeedError(f"rss {stage} failed: {reason}")
    try:
        payload = json.loads(outcome.body_result.output or "")
    except ValueError as exc:
        raise RssFeedError(
            f"rss {stage} returned a malformed payload"
        ) from exc
    if not isinstance(payload, dict):
        raise RssFeedError(f"rss {stage} returned a malformed payload")
    return payload


def list_subscriptions(
    runtime: ActionExecutionRuntime,
    *,
    event_id: str,
) -> dict[str, Any]:
    """List saved subscriptions through the normal capability path."""
    return _execute_json(
        runtime, LIST_ACTION_ID, {}, event_id=event_id, stage="list"
    )


def fetch_feed(
    runtime: ActionExecutionRuntime,
    *,
    event_id: str,
    name: str | None = None,
    url: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Fetch + parse one feed (by subscription name or URL)."""
    args: dict[str, Any] = {"limit": int(limit)}
    if name:
        args["name"] = str(name)
    if url:
        args["url"] = str(url)
    return _execute_json(
        runtime, FETCH_ACTION_ID, args, event_id=event_id, stage="fetch"
    )


def build_feed_digest(
    runtime: ActionExecutionRuntime,
    *,
    event_id: str,
    keyword: str | None = None,
    since_hours: float | None = None,
    names: Sequence[str] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Merge subscribed feeds into one filtered digest, newest first."""
    args: dict[str, Any] = {"limit": int(limit)}
    if keyword:
        args["keyword"] = str(keyword)
    if since_hours is not None:
        args["since_hours"] = float(since_hours)
    if names is not None:
        args["names"] = [str(name) for name in names]
    return _execute_json(
        runtime, DIGEST_ACTION_ID, args, event_id=event_id, stage="digest"
    )


def add_subscription(
    runtime: ActionExecutionRuntime,
    name: str,
    url: str,
    *,
    event_id: str,
) -> dict[str, Any]:
    """Add one subscription via the approved write tool."""
    return _execute_json(
        runtime,
        ADD_ACTION_ID,
        {"name": str(name), "url": str(url)},
        event_id=event_id,
        stage="add subscription",
    )


def remove_subscription(
    runtime: ActionExecutionRuntime,
    name: str,
    *,
    event_id: str,
) -> dict[str, Any]:
    """Remove one subscription via the approved write tool."""
    return _execute_json(
        runtime,
        REMOVE_ACTION_ID,
        {"name": str(name)},
        event_id=event_id,
        stage="remove subscription",
    )
