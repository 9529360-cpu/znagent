from __future__ import annotations

"""Bounded readable observations for ZN-owned managed Chromium investigation."""

from typing import Any

from .semantic_managed_browser import SemanticPlaywrightManagedBrowser


_READABLE_PAGE_SCRIPT = r"""
() => {
  const visible = element => {
    if (!element || !element.isConnected || element.hidden) return false;
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  };
  const text = String(document.body && document.body.innerText || "").slice(0, 8192);
  const links = [];
  for (const anchor of Array.from(document.querySelectorAll("a[href]"))) {
    if (links.length >= 24 || !visible(anchor)) continue;
    let href = "";
    try { href = new URL(anchor.href, location.href).href; } catch { continue; }
    if (!/^https?:/i.test(href)) continue;
    const label = String(anchor.innerText || anchor.textContent || "")
      .trim()
      .replace(/\s+/g, " ")
      .slice(0, 240);
    if (!label) continue;
    links.push({ href: href.slice(0, 2048), text: label });
  }
  return { text, links };
}
"""


class ResearchSemanticPlaywrightManagedBrowser(SemanticPlaywrightManagedBrowser):
    """Keep the existing managed-browser owner while exposing bounded page evidence."""

    def read_page(self, session_id: str, *, page_id: str = "") -> dict[str, Any]:
        session = self._session(session_id)
        resolved_page_id = page_id or self._default_page_id(session)
        observation = self.observe(session_id, page_id=resolved_page_id)
        page = self._page(session, resolved_page_id)
        try:
            raw = page.evaluate(_READABLE_PAGE_SCRIPT)
        except Exception as exc:
            raise RuntimeError(
                f"managed browser readable observation failed: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise RuntimeError("managed browser readable observation returned invalid evidence")
        text = raw.get("text")
        links = raw.get("links")
        if not isinstance(text, str) or not isinstance(links, list):
            raise RuntimeError("managed browser readable observation returned malformed evidence")
        bounded_links = []
        for item in links[:24]:
            if not isinstance(item, dict):
                continue
            href = str(item.get("href") or "").strip()[:2048]
            label = str(item.get("text") or "").strip()[:240]
            if href and label:
                bounded_links.append({"href": href, "text": label})
        return {
            "url": observation.url,
            "title": observation.title,
            "captured_at": observation.captured_at,
            "page_id": observation.page_id,
            "text": text[:8192],
            "links": bounded_links,
            "provider": observation.session.provider,
            "profile_scope": observation.session.profile_scope,
        }
