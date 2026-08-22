from __future__ import annotations

"""ZN-owned web search/extract resources.

The reference repository contains mature provider implementations. ZN extracts
their transport and normalization behavior behind a resident-owned resource
interface instead of making ``tools.web_tools`` / the old plugin registry the
owner of world sensing.

Tavily and Exa are currently extracted. Explicit provider selection remains
pinned; an explicit ``auto``/``failover`` mode composes those resources through
a small ZN-owned failover chain without reviving the old provider control plane.
"""

import json
import os
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Mapping, Protocol

import httpx

from .config import load_zn_config


class WebResourceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WebSearchItem:
    title: str
    url: str
    description: str = ""
    position: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WebDocument:
    url: str
    title: str = ""
    content: str = ""
    raw_content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class WebResource(Protocol):
    name: str

    def search(self, query: str, *, limit: int = 5) -> list[WebSearchItem]: ...

    def extract(self, urls: list[str]) -> list[WebDocument]: ...


class TavilyWebResource:
    """Source-extracted Tavily search/extract transport owned by ZN."""

    name = "tavily"

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = "https://api.tavily.com",
        timeout: float = 60.0,
        client: Any | None = None,
    ):
        self.api_key = str(api_key or "").strip()
        self.base_url = str(base_url or "https://api.tavily.com").rstrip("/")
        self.timeout = max(1.0, float(timeout))
        self._client = client

    @property
    def keyless(self) -> bool:
        return not bool(self.api_key)

    def search(self, query: str, *, limit: int = 5) -> list[WebSearchItem]:
        text = str(query or "").strip()
        if not text:
            raise ValueError("web search query must not be empty")
        raw = self._post(
            "search",
            {
                "query": text,
                "max_results": max(1, min(20, int(limit))),
                "include_raw_content": False,
                "include_images": False,
            },
        )
        items: list[WebSearchItem] = []
        for index, result in enumerate(raw.get("results") or []):
            if not isinstance(result, dict):
                continue
            items.append(
                WebSearchItem(
                    title=str(result.get("title") or ""),
                    url=str(result.get("url") or ""),
                    description=str(result.get("content") or ""),
                    position=index + 1,
                    metadata={
                        key: result[key]
                        for key in ("score", "published_date")
                        if result.get(key) is not None
                    },
                )
            )
        return items

    def extract(self, urls: list[str]) -> list[WebDocument]:
        normalized = [str(url or "").strip() for url in urls if str(url or "").strip()]
        if not normalized:
            return []
        raw = self._post(
            "extract",
            {"urls": normalized, "include_images": False},
        )
        documents: list[WebDocument] = []
        fallback = normalized[0]
        for result in raw.get("results") or []:
            if not isinstance(result, dict):
                continue
            url = str(result.get("url") or fallback)
            title = str(result.get("title") or "")
            content = str(result.get("raw_content") or result.get("content") or "")
            documents.append(
                WebDocument(
                    url=url,
                    title=title,
                    content=content,
                    raw_content=content,
                    metadata={"sourceURL": url, "title": title},
                )
            )
        for failed in raw.get("failed_results") or []:
            if not isinstance(failed, dict):
                continue
            url = str(failed.get("url") or fallback)
            documents.append(
                WebDocument(
                    url=url,
                    error=str(failed.get("error") or "extraction failed"),
                    metadata={"sourceURL": url},
                )
            )
        for failed_url in raw.get("failed_urls") or []:
            url = str(failed_url or fallback)
            documents.append(
                WebDocument(
                    url=url,
                    error="extraction failed",
                    metadata={"sourceURL": url},
                )
            )
        return documents

    def _headers(self) -> dict[str, str]:
        headers = {"X-Client-Name": "zn-agent"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            headers["X-Tavily-Access-Mode"] = "keyless"
        return headers

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        client = self._client or httpx
        try:
            response = client.post(
                url,
                json=payload,
                timeout=self.timeout,
                headers=self._headers(),
            )
        except Exception as exc:
            raise WebResourceError(f"Tavily {endpoint} request failed: {exc}") from exc
        status = int(getattr(response, "status_code", 0) or 0)
        if status < 200 or status >= 300:
            detail = str(getattr(response, "text", "") or "").strip() or f"HTTP {status}"
            raise WebResourceError(f"Tavily {endpoint} failed: {detail[:1000]}")
        try:
            response_payload = response.json()
        except Exception as exc:
            raise WebResourceError(f"Tavily {endpoint} returned invalid JSON") from exc
        if not isinstance(response_payload, dict):
            raise WebResourceError(f"Tavily {endpoint} returned a non-object response")
        return response_payload


class FailoverWebResource:
    """Small resident-owned provider chain with evidence-preserving semantics.

    Search fails over only when a provider raises. An empty result is a valid
    observation and therefore stops the chain. Extraction is finer-grained:
    URLs that a provider cannot extract remain pending for the next resource,
    while successful documents are retained immediately.
    """

    name = "failover"

    def __init__(self, resources: list[WebResource] | tuple[WebResource, ...]):
        self.resources = tuple(resources)
        if not self.resources:
            raise ValueError("web failover requires at least one resource")
        names = [str(resource.name or "").strip().lower() for resource in self.resources]
        if any(not name for name in names):
            raise ValueError("web resource name must not be empty")
        if len(set(names)) != len(names):
            raise ValueError("web failover resource names must be unique")
        self.last_provider: str | None = None

    def search(self, query: str, *, limit: int = 5) -> list[WebSearchItem]:
        failures: list[str] = []
        for resource in self.resources:
            try:
                items = resource.search(query, limit=limit)
            except Exception as exc:
                failures.append(f"{resource.name}: {type(exc).__name__}: {exc}")
                continue
            self.last_provider = resource.name
            return [self._search_item_with_provider(item, resource.name) for item in items]
        self.last_provider = None
        raise WebResourceError(
            "all ZN web search resources failed: " + " | ".join(failures)
        )

    def extract(self, urls: list[str]) -> list[WebDocument]:
        normalized = list(
            dict.fromkeys(
                str(url or "").strip()
                for url in urls
                if str(url or "").strip()
            )
        )
        if not normalized:
            return []

        settled: dict[str, WebDocument] = {}
        errors: dict[str, list[str]] = {url: [] for url in normalized}
        pending = list(normalized)
        used_providers: list[str] = []

        for resource in self.resources:
            if not pending:
                break
            requested = list(pending)
            try:
                documents = resource.extract(requested)
            except Exception as exc:
                detail = f"{resource.name}: {type(exc).__name__}: {exc}"
                for url in requested:
                    errors[url].append(detail)
                continue

            used_providers.append(resource.name)
            by_url: dict[str, WebDocument] = {}
            for document in documents:
                url = str(document.url or "").strip()
                if url and url in errors:
                    by_url[url] = document

            next_pending: list[str] = []
            for url in requested:
                document = by_url.get(url)
                if document is None:
                    errors[url].append(f"{resource.name}: returned no document")
                    next_pending.append(url)
                    continue
                if document.error:
                    errors[url].append(f"{resource.name}: {document.error}")
                    next_pending.append(url)
                    continue
                settled[url] = self._document_with_provider(document, resource.name)
            pending = next_pending

        if used_providers:
            self.last_provider = used_providers[-1]
        else:
            self.last_provider = None

        output: list[WebDocument] = []
        for url in normalized:
            if url in settled:
                output.append(settled[url])
                continue
            detail = " | ".join(errors[url]) or "no ZN web resource returned a document"
            output.append(
                WebDocument(
                    url=url,
                    metadata={"sourceURL": url, "providers": list(used_providers)},
                    error=detail[:2000],
                )
            )
        return output

    @staticmethod
    def _search_item_with_provider(item: WebSearchItem, provider: str) -> WebSearchItem:
        metadata = dict(item.metadata)
        metadata.setdefault("provider", provider)
        return replace(item, metadata=metadata)

    @staticmethod
    def _document_with_provider(document: WebDocument, provider: str) -> WebDocument:
        metadata = dict(document.metadata)
        metadata.setdefault("provider", provider)
        return replace(document, metadata=metadata)


def _provider_order(web_cfg: Mapping[str, Any]) -> list[str]:
    raw = web_cfg.get("provider_order") or ["exa", "tavily"]
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",")]
    if not isinstance(raw, (list, tuple)):
        raise ValueError("ZN web.provider_order must be a list or comma-separated string")
    order = [str(item or "").strip().lower() for item in raw]
    order = [name for name in order if name]
    if not order:
        raise ValueError("ZN web.provider_order must not be empty")
    if len(set(order)) != len(order):
        raise ValueError("ZN web.provider_order must not contain duplicates")
    return order


def _build_provider(
    provider: str,
    web_cfg: Mapping[str, Any],
    *,
    environ: Mapping[str, str],
    client: Any | None = None,
    optional: bool = False,
) -> WebResource | None:
    name = str(provider or "").strip().lower()
    if name == "tavily":
        tavily_cfg = web_cfg.get("tavily") or {}
        if not isinstance(tavily_cfg, Mapping):
            raise ValueError("ZN web.tavily config must be a mapping")
        api_key = str(
            tavily_cfg.get("api_key")
            or web_cfg.get("api_key")
            or environ.get("TAVILY_API_KEY")
            or ""
        ).strip()
        base_url = str(
            tavily_cfg.get("base_url")
            or web_cfg.get("base_url")
            or environ.get("TAVILY_BASE_URL")
            or "https://api.tavily.com"
        ).strip()
        timeout = float(tavily_cfg.get("timeout") or web_cfg.get("timeout") or 60.0)
        return TavilyWebResource(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            client=client,
        )

    if name == "exa":
        from .exa_web_resource import ExaWebResource

        exa_cfg = web_cfg.get("exa") or {}
        if not isinstance(exa_cfg, Mapping):
            raise ValueError("ZN web.exa config must be a mapping")
        api_key = str(
            exa_cfg.get("api_key")
            or environ.get("EXA_API_KEY")
            or ""
        ).strip()
        if not api_key and optional:
            return None
        return ExaWebResource(api_key=api_key, client=client)

    if optional:
        return None
    raise WebResourceError(
        f"ZN web provider {name!r} is not extracted yet; available: tavily, exa"
    )


def build_zn_web_resource(
    config: dict[str, Any] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    client: Any | None = None,
) -> WebResource:
    """Build the configured ZN web resource without old product config."""
    cfg = config if config is not None else load_zn_config()
    env = environ if environ is not None else os.environ
    web_cfg = cfg.get("web") or {}
    if not isinstance(web_cfg, Mapping):
        raise ValueError("ZN web config must be a mapping")

    provider = str(
        web_cfg.get("search_backend")
        or web_cfg.get("backend")
        or "tavily"
    ).strip().lower()

    if provider not in {"auto", "failover"}:
        resource = _build_provider(
            provider,
            web_cfg,
            environ=env,
            client=client,
            optional=False,
        )
        assert resource is not None
        return resource

    resources: list[WebResource] = []
    for name in _provider_order(web_cfg):
        resource = _build_provider(
            name,
            web_cfg,
            environ=env,
            client=client,
            optional=True,
        )
        if resource is not None:
            resources.append(resource)
    if not resources:
        raise WebResourceError("no configured ZN web resource is available for failover")
    return FailoverWebResource(resources)


def web_search_json(
    query: str,
    limit: int = 5,
    *,
    resource: WebResource | None = None,
) -> str:
    """Compatibility shape consumed by NativeWorldSense's structured parser."""
    active = resource or build_zn_web_resource()
    results = active.search(query, limit=max(1, int(limit)))
    provider = str(getattr(active, "last_provider", None) or active.name)
    payload = {
        "success": True,
        "provider": provider,
        "data": {"web": [asdict(item) for item in results]},
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
