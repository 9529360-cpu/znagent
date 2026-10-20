from __future__ import annotations

"""SearXNG web search connector (R2): key-free web search for ZN.

One SearXNG search endpoint becomes a ZN tool through the EXISTING
M-8 OpenAPI REST adapter (:mod:`zn_agent.core.openapi_rest_adapter`) —
the same mechanism R1 used for Open-Meteo. This module adds no new
mechanism, only trusted host configuration (the SearXNG OpenAPI
document below plus an ordered list of instance base URLs), one attach
helper, and one lookup that walks the normal capability path
(``ActionExecutionRuntime`` + ``ActionRequest``) exactly the way a Work
does.

Why SearXNG, and why the instance list is configuration: SearXNG is
the only key-free general web-search API shape that fits the REST
adapter (``GET /search?q=...&format=json``). Public instances,
however, are mostly NOT usable programmatically. Verified live on
2026-10-20 from this network against 41 public instances listed by
searx.space plus well-known extras:

- most answered HTTP 429 — SearXNG's refusal when the JSON format is
  not enabled on that instance (the upstream default) or when rate
  limited;
- several answered 403 / 418 / 202 bot challenges, or HTTP 200 with
  an HTML bot-check page instead of JSON;
- DuckDuckGo's key-free endpoints are not a web search either: the
  Instant Answer API answered HTTP 202 with an empty abstract and
  zero results, and the HTML endpoint answered a 202 challenge page.

Exactly one public instance returned real JSON results in every probe
(English and Chinese queries, 1.5-2s each): ``search.lumy.live``. It
is the default below — a default of one, stated plainly, not a
pretend fleet. Deployments can pass their own ordered ``instances``
(a self-hosted SearXNG is the genuinely stable option) without code
changes; :func:`search_web` tries each attached instance in order.

Failure honesty: a non-2xx status, a transport failure, a bot-check
or otherwise malformed payload on one instance is recorded with its
reason and the next instance is tried. If every instance fails,
:class:`WebSearchError` lists each instance and its reason. A
well-formed response with zero results is an answer ("no results"),
never dressed up with invented links. Nothing here fabricates
titles, URLs, or snippets.

One bounded-output wrinkle: the Fabric caps tool output (the M-8
adapter truncates at 12,000 chars), and a SearXNG response with many
results can exceed that and arrive cut mid-JSON. When the payload
does not parse whole, :func:`search_web` recovers the complete
leading result entries and drops the incomplete tail — recovered
entries are verbatim from the instance, and the answer carries
``"truncated": True`` to say so.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from .action_execution import ActionExecutionRuntime, ActionRequest
from .action_fabric import ActionFabricRegistry
from .body import NativeBody
from .models import utc_now
from .openapi_rest_adapter import (
    OpenApiRestAttachment,
    RestHttpClient,
    attach_openapi_rest_tools,
)

__all__ = [
    "DEFAULT_INSTANCES",
    "OPERATION_ID",
    "SEARCH_SPEC",
    "WebSearchAttachment",
    "WebSearchError",
    "action_id_for_instance",
    "attach_web_search_tools",
    "provider_id_for_instance",
    "search_web",
    "spec_for_instance",
]

OPERATION_ID = "web_search"

#: Public SearXNG instances verified live on 2026-10-20 to return real
#: JSON search results (see module docstring for the full probe). One
#: entry is the honest count; hosts may configure more, in order.
DEFAULT_INSTANCES: tuple[str, ...] = ("https://search.lumy.live",)

_SOURCE_LABEL = "SearXNG metasearch (key-free public instance)"
_MAX_SNIPPET_CHARS = 500


def _host_slug(base_url: str) -> str:
    host = urlsplit(str(base_url or "")).netloc.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", host).strip("_")
    return slug or "instance"


def provider_id_for_instance(base_url: str) -> str:
    """Stable provider namespace for one SearXNG instance base URL."""
    return f"searxng_{_host_slug(base_url)}"


def action_id_for_instance(base_url: str) -> str:
    """Fabric action id of one instance's ``web_search`` tool."""
    return f"rest.{provider_id_for_instance(base_url)}.{OPERATION_ID}"


def spec_for_instance(base_url: str) -> dict[str, Any]:
    """The trusted SearXNG OpenAPI document for one instance.

    The document is identical for every instance except ``servers``;
    it is host configuration, never model-supplied. The single
    operation is a read-only GET, so the registered tool is
    ``read_only`` and no write approvals exist.
    """
    return {
        "openapi": "3.0.3",
        "info": {"title": "SearXNG Search API", "version": "1.0.0"},
        "servers": [{"url": str(base_url).rstrip("/")}],
        "paths": {
            "/search": {
                "get": {
                    "operationId": OPERATION_ID,
                    "summary": (
                        "Search the web with a SearXNG metasearch "
                        "instance and return result titles, URLs and "
                        "snippets"
                    ),
                    "parameters": [
                        {
                            "name": "q",
                            "in": "query",
                            "required": True,
                            "schema": {
                                "type": "string",
                                "description": (
                                    "Search query text, e.g. "
                                    "'Berlin weather forecast'"
                                ),
                            },
                        },
                        {
                            "name": "format",
                            "in": "query",
                            "required": False,
                            "schema": {
                                "type": "string",
                                "enum": ["json"],
                                "description": (
                                    "Response format; this connector "
                                    "only supports json"
                                ),
                            },
                        },
                        {
                            "name": "language",
                            "in": "query",
                            "required": False,
                            "schema": {
                                "type": "string",
                                "description": (
                                    "Language code for results, e.g. "
                                    "en, de or zh"
                                ),
                            },
                        },
                        {
                            "name": "categories",
                            "in": "query",
                            "required": False,
                            "schema": {
                                "type": "string",
                                "description": (
                                    "Comma-separated SearXNG "
                                    "categories, e.g. general or news"
                                ),
                            },
                        },
                        {
                            "name": "pageno",
                            "in": "query",
                            "required": False,
                            "schema": {
                                "type": "integer",
                                "description": "Result page number",
                            },
                        },
                        {
                            "name": "time_range",
                            "in": "query",
                            "required": False,
                            "schema": {
                                "type": "string",
                                "enum": ["day", "week", "month", "year"],
                                "description": (
                                    "Restrict results to a recent "
                                    "time range"
                                ),
                            },
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": (
                                "JSON object with a results list; "
                                "each result carries title, url, "
                                "content (snippet) and engine"
                            )
                        }
                    },
                }
            }
        },
    }


#: The spec for the default instance; kept as a module constant in the
#: R1 style for tests and host inspection.
SEARCH_SPEC: dict[str, Any] = spec_for_instance(DEFAULT_INSTANCES[0])


class WebSearchError(RuntimeError):
    """One explicit web search failure; the message IS the reason."""


@dataclass(slots=True)
class WebSearchAttachment:
    """Every attached SearXNG instance; detach removes all at once."""

    instances: tuple[str, ...]
    attachments: tuple[OpenApiRestAttachment, ...]
    _closed: bool = False

    def action_id(self, instance: str) -> str:
        return action_id_for_instance(instance)

    @property
    def action_ids(self) -> tuple[str, ...]:
        return tuple(action_id_for_instance(url) for url in self.instances)

    def detach(self) -> None:
        if self._closed:
            return
        self._closed = True
        for attachment in self.attachments:
            attachment.detach()


def attach_web_search_tools(
    fabric: ActionFabricRegistry,
    body: NativeBody,
    *,
    instances: Sequence[str] = DEFAULT_INSTANCES,
    http_client: RestHttpClient | None = None,
    timeout_seconds: float = 20.0,
) -> WebSearchAttachment:
    """Attach one read-only ``web_search`` tool per SearXNG instance.

    ``instances`` is trusted host configuration, tried in order by
    :func:`search_web`. The same ``http_client`` (real urllib
    transport by default) serves every instance.
    """
    ordered: list[str] = []
    for raw in instances:
        url = str(raw or "").strip().rstrip("/")
        if url and url not in ordered:
            ordered.append(url)
    if not ordered:
        raise WebSearchError(
            "web search needs at least one SearXNG instance base URL"
        )
    attached: list[OpenApiRestAttachment] = []
    try:
        for url in ordered:
            attached.append(
                attach_openapi_rest_tools(
                    fabric=fabric,
                    body=body,
                    spec=spec_for_instance(url),
                    provider_id=provider_id_for_instance(url),
                    http_client=http_client,
                    timeout_seconds=timeout_seconds,
                )
            )
    except Exception:
        for attachment in attached:
            attachment.detach()
        raise
    return WebSearchAttachment(
        instances=tuple(ordered), attachments=tuple(attached)
    )


def _recover_truncated_results(text: str) -> list[Any] | None:
    """Recover complete result entries from a truncated payload.

    Only whole entries decoded cleanly from the front of the results
    list are kept; the incomplete tail is dropped, never repaired.
    Returns ``None`` when nothing complete can be recovered.
    """
    if not text.lstrip().startswith("{") or '"results"' not in text:
        return None
    bracket = text.find("[", text.index('"results"'))
    if bracket < 0:
        return None
    decoder = json.JSONDecoder()
    idx = bracket + 1
    recovered: list[Any] = []
    while idx < len(text):
        while idx < len(text) and text[idx] in " \t\r\n,":
            idx += 1
        if idx >= len(text) or text[idx] == "]":
            break
        try:
            entry, idx = decoder.raw_decode(text, idx)
        except ValueError:
            break
        recovered.append(entry)
    return recovered or None


def _execute_search(
    runtime: ActionExecutionRuntime,
    action_id: str,
    args: Mapping[str, Any],
    *,
    event_id: str,
) -> tuple[dict[str, Any], bool]:
    """Run one instance's tool; return (payload, payload_was_truncated)."""
    outcome = runtime.execute(
        ActionRequest(action_id, dict(args), event_id=event_id)
    )
    if not outcome.success or outcome.body_result is None:
        reason = outcome.error or "no result returned"
        raise WebSearchError(reason)
    output = outcome.body_result.output or ""
    try:
        payload = json.loads(output)
    except ValueError:
        recovered = _recover_truncated_results(output)
        if recovered is not None:
            return {"results": recovered}, True
        raise WebSearchError(
            "returned a malformed payload (not JSON; the instance "
            "may have answered a bot check instead of search results)"
        ) from None
    if not isinstance(payload, dict) or not isinstance(
        payload.get("results"), list
    ):
        raise WebSearchError(
            "returned a malformed payload (JSON without a results list)"
        )
    return payload, False


def _normalize_results(
    payload: Mapping[str, Any], max_results: int
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for entry in payload["results"]:
        if not isinstance(entry, Mapping):
            continue
        title = str(entry.get("title") or "").strip()
        url = str(entry.get("url") or "").strip()
        if not title or not url:
            continue
        snippet = str(entry.get("content") or "").strip()
        if len(snippet) > _MAX_SNIPPET_CHARS:
            snippet = snippet[:_MAX_SNIPPET_CHARS]
        results.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "engine": str(entry.get("engine") or "").strip(),
            }
        )
        if len(results) >= max_results:
            break
    return results


def search_web(
    runtime: ActionExecutionRuntime,
    attachment: WebSearchAttachment,
    query: str,
    *,
    max_results: int = 5,
    language: str | None = None,
    event_id: str,
) -> dict[str, Any]:
    """Search the web through the normal capability path.

    Tries each attached instance in order. Returns the structured
    answer (query, results with title/url/snippet/engine, the
    answering instance, source, retrieval time). A well-formed
    zero-result response is returned as an explicit empty answer.
    Raises :class:`WebSearchError` when every instance failed, with
    each instance's concrete reason in the message.
    """
    text = str(query or "").strip()
    if not text:
        raise WebSearchError("web search needs a query")
    if (
        isinstance(max_results, bool)
        or not isinstance(max_results, int)
        or not 1 <= max_results <= 20
    ):
        raise WebSearchError("max_results must be between 1 and 20")
    retrieved_at = utc_now()

    args: dict[str, Any] = {"q": text, "format": "json"}
    if language:
        args["language"] = str(language)

    failures: list[str] = []
    for instance in attachment.instances:
        try:
            payload, truncated = _execute_search(
                runtime,
                attachment.action_id(instance),
                args,
                event_id=f"{event_id}:{_host_slug(instance)}",
            )
        except WebSearchError as exc:
            failures.append(f"{instance}: {exc}")
            continue
        return {
            "query": text,
            "results": _normalize_results(payload, max_results),
            "instance": instance,
            "source": _SOURCE_LABEL,
            "retrieved_at": retrieved_at,
            "truncated": truncated,
        }
    raise WebSearchError(
        "web search failed on every configured instance: "
        + "; ".join(failures)
    )
