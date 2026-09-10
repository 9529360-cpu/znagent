from __future__ import annotations

"""ZN-owned Firecrawl search/extract resource.

Source-extracted from the mature Firecrawl provider while removing the old
plugin/managed-gateway control plane. ZN keeps the useful provider behavior:
keyed or keyless REST search, response-shape normalization, per-URL scrape
failures, and pre/post-redirect URL safety checks.
"""

import os
from collections.abc import Mapping
from typing import Any, Callable

import httpx

from .url_safety import is_safe_url
from .web_resource import WebDocument, WebResourceError, WebSearchItem


SafetyCheck = Callable[[str], bool]


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list, str, int, float, bool)):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return dump()
        except Exception:
            pass
    raw = getattr(value, "__dict__", None)
    if isinstance(raw, dict):
        return {key: item for key, item in raw.items() if not key.startswith("_")}
    return value


def _result_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    results: list[dict[str, Any]] = []
    for item in value:
        plain = _plain(item)
        if isinstance(plain, dict):
            results.append(plain)
    return results


def _search_results(response: Any) -> list[dict[str, Any]]:
    payload = _plain(response)
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return _result_dicts(data)
    if isinstance(data, dict):
        nested = _result_dicts(data.get("web")) or _result_dicts(data.get("results"))
        if nested:
            return nested
    return _result_dicts(payload.get("web")) or _result_dicts(payload.get("results"))


def _scrape_payload(response: Any) -> dict[str, Any]:
    payload = _plain(response)
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


class FirecrawlWebResource:
    name = "firecrawl"

    def __init__(
        self,
        *,
        api_key: str = "",
        api_url: str = "https://api.firecrawl.dev",
        timeout: float = 60.0,
        client: Any | None = None,
        safety_check: SafetyCheck | None = None,
        safety_config: Mapping[str, object] | None = None,
        environ: Mapping[str, str] | None = None,
    ):
        self.api_key = str(api_key or "").strip()
        self.api_url = str(api_url or "https://api.firecrawl.dev").rstrip("/")
        self.timeout = max(1.0, float(timeout))
        self._client = client
        env = environ if environ is not None else os.environ
        self._safety_check = safety_check or (
            lambda url: is_safe_url(url, config=safety_config, environ=env)
        )

    @property
    def keyless(self) -> bool:
        return not bool(self.api_key)

    def search(self, query: str, *, limit: int = 5) -> list[WebSearchItem]:
        text = str(query or "").strip()
        if not text:
            raise ValueError("web search query must not be empty")
        response = self._post(
            "/v2/search",
            {"query": text, "limit": max(1, min(20, int(limit)))},
        )
        items: list[WebSearchItem] = []
        for index, result in enumerate(_search_results(response)):
            title = str(result.get("title") or "")
            url = str(result.get("url") or result.get("sourceURL") or "")
            description = str(
                result.get("description")
                or result.get("content")
                or result.get("markdown")
                or ""
            )
            metadata = {
                key: result[key]
                for key in ("score", "category", "publishedDate", "published_date")
                if result.get(key) is not None
            }
            metadata["provider"] = self.name
            items.append(
                WebSearchItem(
                    title=title,
                    url=url,
                    description=description,
                    position=index + 1,
                    metadata=metadata,
                )
            )
        return items

    def extract(self, urls: list[str]) -> list[WebDocument]:
        normalized = [str(url or "").strip() for url in urls if str(url or "").strip()]
        results: list[WebDocument] = []
        for url in normalized:
            if not self._safety_check(url):
                results.append(
                    WebDocument(
                        url=url,
                        metadata={"sourceURL": url, "requestedURL": url, "provider": self.name},
                        error="Blocked: URL targets a private, internal, unresolved, or unsafe network address",
                    )
                )
                continue
            try:
                response = self._post(
                    "/v2/scrape",
                    {"url": url, "formats": ["markdown", "html"]},
                )
                payload = _scrape_payload(response)
            except Exception as exc:
                results.append(
                    WebDocument(
                        url=url,
                        metadata={"sourceURL": url, "requestedURL": url, "provider": self.name},
                        error=f"Firecrawl scrape failed: {exc}",
                    )
                )
                continue

            metadata = _plain(payload.get("metadata"))
            if not isinstance(metadata, dict):
                metadata = {}
            final_url = str(metadata.get("sourceURL") or url).strip() or url
            title = str(metadata.get("title") or "")
            if not self._safety_check(final_url):
                results.append(
                    WebDocument(
                        url=final_url,
                        title=title,
                        metadata={"sourceURL": final_url, "requestedURL": url, "provider": self.name},
                        error="Blocked: redirected URL targets a private, internal, unresolved, or unsafe network address",
                    )
                )
                continue

            markdown = payload.get("markdown")
            html = payload.get("html")
            content = str(markdown or html or "")
            normalized_metadata = dict(metadata)
            normalized_metadata["sourceURL"] = final_url
            normalized_metadata["requestedURL"] = url
            normalized_metadata["provider"] = self.name
            if title:
                normalized_metadata.setdefault("title", title)
            results.append(
                WebDocument(
                    url=final_url,
                    title=title,
                    content=content,
                    raw_content=content,
                    metadata=normalized_metadata,
                )
            )
        return results

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "X-Client-Name": "zn-agent"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        client = self._client or httpx
        try:
            response = client.post(
                f"{self.api_url}{path}",
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
        except Exception as exc:
            raise WebResourceError(f"Firecrawl request failed: {exc}") from exc
        status = int(getattr(response, "status_code", 0) or 0)
        if status < 200 or status >= 300:
            detail = str(getattr(response, "text", "") or "").strip() or f"HTTP {status}"
            raise WebResourceError(f"Firecrawl request failed: {detail[:1000]}")
        try:
            payload = response.json()
        except Exception as exc:
            raise WebResourceError("Firecrawl returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise WebResourceError("Firecrawl returned a non-object response")
        if payload.get("success") is False:
            detail = str(payload.get("error") or payload.get("message") or "request failed")
            raise WebResourceError(f"Firecrawl request failed: {detail[:1000]}")
        return payload
