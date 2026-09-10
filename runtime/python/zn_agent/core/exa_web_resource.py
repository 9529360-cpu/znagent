from __future__ import annotations

"""ZN-owned Exa web search/extract resource.

Source-extracted from the mature Exa provider. The useful mechanism is kept:
semantic search with highlights, normalized positions, batch content extraction
and per-URL failure evidence. The old plugin registry, legacy env resolver,
lazy-dependency manager and keyless MCP control plane are not dependencies.
"""

from typing import Any, Callable

from .web_resource import WebDocument, WebResourceError, WebSearchItem


ClientBuilder = Callable[..., Any]


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _source_metadata(item: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {"provider": "exa"}
    for key in ("publishedDate", "published_date", "author", "score"):
        value = _value(item, key)
        if value is not None:
            metadata[key] = value
    return metadata


class ExaWebResource:
    name = "exa"

    def __init__(
        self,
        *,
        api_key: str,
        client: Any | None = None,
        client_builder: ClientBuilder | None = None,
    ):
        self.api_key = str(api_key or "").strip()
        if not self.api_key:
            raise ValueError("Exa web resource requires EXA_API_KEY")
        self._client_instance = client
        self._client_builder = client_builder

    def _client(self):
        if self._client_instance is not None:
            return self._client_instance
        builder = self._client_builder
        if builder is None:
            try:
                from exa_py import Exa
            except ImportError as exc:
                raise WebResourceError(
                    "Exa resource requires the optional 'exa' dependency"
                ) from exc
            builder = Exa
        client = builder(api_key=self.api_key)
        headers = getattr(client, "headers", None)
        if isinstance(headers, dict):
            headers["x-exa-integration"] = "zn-agent"
        self._client_instance = client
        return client

    def search(self, query: str, *, limit: int = 5) -> list[WebSearchItem]:
        text = str(query or "").strip()
        if not text:
            raise ValueError("web search query must not be empty")
        try:
            response = self._client().search(
                text,
                num_results=max(1, min(20, int(limit))),
                contents={"highlights": True},
            )
        except Exception as exc:
            if isinstance(exc, WebResourceError):
                raise
            raise WebResourceError(f"Exa search failed: {exc}") from exc

        results = _value(response, "results", []) or []
        items: list[WebSearchItem] = []
        for index, result in enumerate(results):
            highlights = _value(result, "highlights", []) or []
            description = " ".join(str(part) for part in highlights if str(part).strip())
            items.append(
                WebSearchItem(
                    title=str(_value(result, "title", "") or ""),
                    url=str(_value(result, "url", "") or ""),
                    description=description,
                    position=index + 1,
                    metadata=_source_metadata(result),
                )
            )
        return items

    def extract(self, urls: list[str]) -> list[WebDocument]:
        normalized = [str(url or "").strip() for url in urls if str(url or "").strip()]
        if not normalized:
            return []
        try:
            response = self._client().get_contents(normalized, text=True)
            results = _value(response, "results", []) or []
        except Exception as exc:
            detail = f"Exa extract failed: {exc}"
            return [
                WebDocument(
                    url=url,
                    metadata={"sourceURL": url, "requestedURL": url, "provider": "exa"},
                    error=detail,
                )
                for url in normalized
            ]

        documents: list[WebDocument] = []
        returned_urls: set[str] = set()
        for result in results:
            url = str(_value(result, "url", "") or "").strip()
            title = str(_value(result, "title", "") or "")
            content = str(_value(result, "text", "") or "")
            if url:
                returned_urls.add(url)
            metadata = _source_metadata(result)
            metadata["sourceURL"] = url or normalized[0]
            metadata["title"] = title
            if url in normalized:
                metadata["requestedURL"] = url
            documents.append(
                WebDocument(
                    url=url or normalized[0],
                    title=title,
                    content=content,
                    raw_content=content,
                    metadata=metadata,
                )
            )

        # The SDK can return a partial batch without raising. Preserve missing
        # URLs as explicit evidence instead of silently pretending extraction
        # completed for the full resident request.
        for url in normalized:
            if url not in returned_urls:
                documents.append(
                    WebDocument(
                        url=url,
                        metadata={"sourceURL": url, "requestedURL": url, "provider": "exa"},
                        error="Exa returned no document for this URL",
                    )
                )
        return documents
