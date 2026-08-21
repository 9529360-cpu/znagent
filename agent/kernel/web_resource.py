from __future__ import annotations

"""ZN-owned web search/extract resources.

The reference repository already contains mature provider implementations. ZN
extracts their transport and normalization behavior behind a resident-owned
resource interface instead of making ``tools.web_tools`` / the old plugin
registry the owner of world sensing.

Tavily and Exa are the first extracted providers. Additional mature providers
can be ported behind the same interface without changing NativeWorldSense.
"""

import json
import os
from dataclasses import asdict, dataclass, field
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


def build_zn_web_resource(
    config: dict[str, Any] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    client: Any | None = None,
) -> WebResource:
    """Build the configured ZN web resource without loading old product config."""
    cfg = config if config is not None else load_zn_config()
    env = environ if environ is not None else os.environ
    web_cfg = cfg.get("web") or {}
    if not isinstance(web_cfg, dict):
        raise ValueError("ZN web config must be a mapping")

    provider = str(
        web_cfg.get("search_backend")
        or web_cfg.get("backend")
        or "tavily"
    ).strip().lower()

    if provider == "tavily":
        tavily_cfg = web_cfg.get("tavily") or {}
        if not isinstance(tavily_cfg, dict):
            raise ValueError("ZN web.tavily config must be a mapping")
        api_key = str(
            tavily_cfg.get("api_key")
            or web_cfg.get("api_key")
            or env.get("TAVILY_API_KEY")
            or ""
        ).strip()
        base_url = str(
            tavily_cfg.get("base_url")
            or web_cfg.get("base_url")
            or env.get("TAVILY_BASE_URL")
            or "https://api.tavily.com"
        ).strip()
        timeout = float(tavily_cfg.get("timeout") or web_cfg.get("timeout") or 60.0)
        return TavilyWebResource(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            client=client,
        )

    if provider == "exa":
        from .exa_web_resource import ExaWebResource

        exa_cfg = web_cfg.get("exa") or {}
        if not isinstance(exa_cfg, dict):
            raise ValueError("ZN web.exa config must be a mapping")
        api_key = str(
            exa_cfg.get("api_key")
            or web_cfg.get("api_key")
            or env.get("EXA_API_KEY")
            or ""
        ).strip()
        return ExaWebResource(api_key=api_key, client=client)

    raise WebResourceError(
        f"ZN web provider {provider!r} is not extracted yet; available: tavily, exa"
    )


def web_search_json(
    query: str,
    limit: int = 5,
    *,
    resource: WebResource | None = None,
) -> str:
    """Compatibility shape consumed by NativeWorldSense's structured parser."""
    active = resource or build_zn_web_resource()
    results = active.search(query, limit=max(1, int(limit)))
    payload = {
        "success": True,
        "provider": active.name,
        "data": {"web": [asdict(item) for item in results]},
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
