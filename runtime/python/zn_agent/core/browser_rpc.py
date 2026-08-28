from __future__ import annotations

"""Resident-owned RPC control surface for the managed browser.

This module deliberately exposes a narrow first product path: create an ephemeral
managed session, observe it, navigate with fresh observation-bound authority,
and close it. The browser adapter still owns URL/network safety enforcement and
post-action effect evidence; the RPC face does not treat dispatch as completion.
"""

from dataclasses import asdict
from enum import Enum
from typing import Any

from .browser import (
    BrowserAction,
    BrowserActionAuthority,
    BrowserActionKind,
    BrowserPermissionContext,
)
from .daemon import ResidentRpcServer


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


class BrowserResidentRpcServer(ResidentRpcServer):
    """Extend the normal resident RPC face with bounded managed browsing."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._browser_permissions: dict[str, BrowserPermissionContext] = {}

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        method = str(request.get("method") or "").strip()
        if not method.startswith("browser_"):
            return super().handle(request)

        request_id = request.get("id")
        params = request.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError("params must be an object")

        browser = getattr(self.resident, "managed_browser", None)
        if browser is None:
            raise ValueError("resident has no managed browser")

        if method == "browser_open":
            permission = self._permission_from_params(params.get("permission"))
            session = browser.open_session(
                permission=permission,
                headless=bool(params.get("headless", True)),
            )
            self._browser_permissions[session.session_id] = permission
            result = _jsonable(asdict(session))
        elif method == "browser_observe":
            session_id = self._session_id(params, method)
            self._require_known_session(session_id)
            result = _jsonable(
                asdict(
                    browser.observe(
                        session_id,
                        page_id=str(params.get("page_id") or "").strip(),
                    )
                )
            )
        elif method == "browser_navigate":
            session_id = self._session_id(params, method)
            permission = self._require_known_session(session_id)
            url = str(params.get("url") or "").strip()
            if not url:
                raise ValueError("browser_navigate requires url")
            page_id = str(params.get("page_id") or "").strip()
            observation = browser.observe(session_id, page_id=page_id)
            action = BrowserAction.create(
                session_id=session_id,
                kind=BrowserActionKind.NAVIGATE,
                page_id=page_id or observation.page_id,
                args={"url": url},
                expected=(
                    {"url_equals": str(params.get("url_equals") or "").strip()}
                    if str(params.get("url_equals") or "").strip()
                    else {}
                ),
            )
            authority = BrowserActionAuthority.from_observation(
                action,
                observation,
                permission,
            )
            evidence = browser.act(action, authority)
            result = _jsonable(asdict(evidence))
        elif method == "browser_close":
            session_id = self._session_id(params, method)
            self._require_known_session(session_id)
            browser.close_session(session_id)
            self._browser_permissions.pop(session_id, None)
            result = {"closed": True, "session_id": session_id}
        else:
            raise ValueError(f"unknown method: {method}")

        return {"id": request_id, "ok": True, "result": result}

    @staticmethod
    def _session_id(params: dict[str, Any], method: str) -> str:
        session_id = str(params.get("session_id") or "").strip()
        if not session_id:
            raise ValueError(f"{method} requires session_id")
        return session_id

    def _require_known_session(self, session_id: str) -> BrowserPermissionContext:
        permission = self._browser_permissions.get(session_id)
        if permission is None:
            raise ValueError("unknown resident managed-browser session")
        return permission

    @staticmethod
    def _permission_from_params(raw: Any) -> BrowserPermissionContext:
        if raw is None:
            return BrowserPermissionContext()
        if not isinstance(raw, dict):
            raise ValueError("browser_open permission must be an object")
        allowed_origins = raw.get("allowed_origins") or []
        if not isinstance(allowed_origins, list):
            raise ValueError("browser allowed_origins must be a list")
        return BrowserPermissionContext(
            allow_navigation=bool(raw.get("allow_navigation", False)),
            allow_page_interaction=bool(raw.get("allow_page_interaction", False)),
            allow_text_entry=bool(raw.get("allow_text_entry", False)),
            allow_downloads=bool(raw.get("allow_downloads", False)),
            allow_uploads=bool(raw.get("allow_uploads", False)),
            allow_clipboard=bool(raw.get("allow_clipboard", False)),
            allow_sensitive_fields=bool(raw.get("allow_sensitive_fields", False)),
            allow_private_network=bool(raw.get("allow_private_network", False)),
            allowed_origins=tuple(str(item) for item in allowed_origins),
        )
