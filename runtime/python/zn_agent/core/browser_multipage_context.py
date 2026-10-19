from __future__ import annotations

"""Work-level multi-page/tab browser context retention (M-10).

A Work that crosses pages (A -> B -> back to A) can record which page serves
which part of its task, then *return* to a page later. Returning always
re-observes the page fresh through the provider-neutral
``observe(session_id, page_id=...)`` call -- nothing is dispatched and no side
effect is replayed. When the page drifted while the Work was away (URL
changed, page entered a failed load state, or the page can no longer be
observed), the drift is handled explicitly: the caller gets ``drifted=True``
with the reason and the fresh state, and must not act on the remembered
state. The stored record is refreshed to the fresh observation either way,
so a stale snapshot can never be reused silently.

This module deliberately does not change the provider, does not switch
tabs, and does not perform any automatic cross-site login. It plugs into
the existing browser loop (``browser_loop.py``) through two read-only loop
actions (``browser.page.register`` / ``browser.page.return``); the returned
fresh observation feeds the same URL-pin mechanism
(``execute_fresh_semantic_action`` with ``expected_url_before``) that the
rest of the loop uses, so a drifted page can never be acted on with an old
pin.
"""

from dataclasses import dataclass, field
from typing import Any, Mapping

from .browser import BrowserObservation
from .models import utc_now

_MAX_PAGES = 8
_MAX_TASK_ROLE = 256
_MAX_NOTE = 512
_MAX_EVENTS = 64
_MAX_PAGE_ID = 128

_FAILED_LOAD_STATES = frozenset({"crashed", "error", "failed"})


def _require_page_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("browser multi-page context page_id must be a string")
    page_id = value.strip()
    if not page_id:
        raise ValueError("browser multi-page context page_id must not be empty")
    if len(page_id) > _MAX_PAGE_ID:
        raise ValueError("browser multi-page context page_id is too long")
    return page_id


def _require_task_role(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("browser multi-page context task_role must be a string")
    role = value.strip()
    if not role:
        raise ValueError("browser multi-page context task_role must not be empty")
    if len(role) > _MAX_TASK_ROLE:
        raise ValueError("browser multi-page context task_role is too long")
    return role


def _require_note(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("browser multi-page context note must be a string")
    note = value.strip()
    if len(note) > _MAX_NOTE:
        raise ValueError("browser multi-page context note is too long")
    return note


def _observation_snapshot(observation: BrowserObservation) -> dict[str, str]:
    return {
        "url": str(observation.url or ""),
        "title": str(observation.title or ""),
        "load_state": str(observation.load_state or ""),
        "captured_at": str(observation.captured_at or ""),
    }


@dataclass(frozen=True, slots=True)
class BrowserPageRecord:
    """One page's remembered place in the Work's task."""

    page_id: str
    task_role: str
    note: str
    url: str
    title: str
    load_state: str
    captured_at: str
    registered_at: str
    reobservations: int = 0
    drift_events: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "task_role": self.task_role,
            "note": self.note,
            "url": self.url,
            "title": self.title,
            "load_state": self.load_state,
            "captured_at": self.captured_at,
            "registered_at": self.registered_at,
            "reobservations": int(self.reobservations),
            "drift_events": int(self.drift_events),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "BrowserPageRecord":
        if not isinstance(raw, Mapping):
            raise ValueError("browser page record must be an object")
        page_id = _require_page_id(raw.get("page_id"))
        task_role = _require_task_role(raw.get("task_role"))
        note = _require_note(raw.get("note"))
        reobservations = raw.get("reobservations", 0)
        drift_events = raw.get("drift_events", 0)
        if (
            not isinstance(reobservations, int)
            or isinstance(reobservations, bool)
            or reobservations < 0
        ):
            raise ValueError("browser page record reobservations must be a non-negative int")
        if (
            not isinstance(drift_events, int)
            or isinstance(drift_events, bool)
            or drift_events < 0
        ):
            raise ValueError("browser page record drift_events must be a non-negative int")
        snapshot: dict[str, str] = {}
        for key in ("url", "title", "load_state", "captured_at", "registered_at"):
            value = raw.get(key, "")
            if not isinstance(value, str):
                raise ValueError(f"browser page record {key} must be a string")
            snapshot[key] = value
        return cls(
            page_id=page_id,
            task_role=task_role,
            note=note,
            url=snapshot["url"],
            title=snapshot["title"],
            load_state=snapshot["load_state"],
            captured_at=snapshot["captured_at"],
            registered_at=snapshot["registered_at"],
            reobservations=reobservations,
            drift_events=drift_events,
        )


@dataclass(frozen=True, slots=True)
class BrowserPageReturn:
    """Outcome of returning to a previously registered page."""

    fresh_observation: BrowserObservation | None
    record: BrowserPageRecord
    drifted: bool
    drift_reason: str


class BrowserMultiPageContext:
    """Retention registry for one Work's browser pages.

    The context itself is plain bookkeeping; every re-observation goes
    through the provider's read-only ``observe`` path, so returning to a
    page can never dispatch or replay a side effect.
    """

    def __init__(self) -> None:
        self._pages: dict[str, BrowserPageRecord] = {}
        self._events: list[dict[str, Any]] = []

    def register_page(
        self,
        page_id: str,
        *,
        task_role: str,
        note: str = "",
        observation: BrowserObservation | None = None,
    ) -> BrowserPageRecord:
        """Record (or refresh) which task part a page serves.

        When an observation is supplied its snapshot is stored, so a later
        return can detect drift against this fresh baseline.
        """
        clean_id = _require_page_id(page_id)
        role = _require_task_role(task_role)
        clean_note = _require_note(note)
        if observation is None:
            raise ValueError(
                "browser multi-page context register_page requires a fresh observation"
            )
        if clean_id not in self._pages and len(self._pages) >= _MAX_PAGES:
            raise ValueError(
                f"browser multi-page context keeps at most {_MAX_PAGES} pages; "
                "forget an unused page before registering another"
            )
        snapshot = _observation_snapshot(observation)
        existing = self._pages.get(clean_id)
        record = BrowserPageRecord(
            page_id=clean_id,
            task_role=role,
            note=clean_note,
            url=snapshot["url"],
            title=snapshot["title"],
            load_state=snapshot["load_state"],
            captured_at=snapshot["captured_at"],
            registered_at=existing.registered_at if existing else utc_now(),
            reobservations=existing.reobservations if existing else 0,
            drift_events=existing.drift_events if existing else 0,
        )
        self._pages[clean_id] = record
        return record

    def forget_page(self, page_id: str) -> bool:
        clean_id = _require_page_id(page_id)
        return self._pages.pop(clean_id, None) is not None

    def get_page(self, page_id: str) -> BrowserPageRecord | None:
        return self._pages.get(_require_page_id(page_id))

    def known_pages(self) -> tuple[BrowserPageRecord, ...]:
        return tuple(self._pages.values())

    def describe(self) -> list[dict[str, Any]]:
        """Model-facing summary: which page belongs to which task part."""
        return [
            {
                "page_id": record.page_id,
                "task_role": record.task_role,
                "note": record.note,
                "url": record.url,
                "title": record.title,
                "reobservations": record.reobservations,
            }
            for record in self._pages.values()
        ]

    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._events)

    def _append_event(self, event: dict[str, Any]) -> None:
        self._events.append(dict(event))
        del self._events[: max(0, len(self._events) - _MAX_EVENTS)]

    def return_to_page(
        self,
        provider: Any,
        *,
        session_id: str,
        page_id: str,
    ) -> BrowserPageReturn:
        """Re-observe a registered page and handle drift explicitly.

        The page is always re-observed fresh; the stored record is then
        refreshed to that fresh observation. When the page drifted while
        the Work was away, ``drifted`` is True and ``drift_reason``
        explains it -- the caller must decide again from the fresh state
        instead of acting on what it remembers.
        """
        clean_id = _require_page_id(page_id)
        record = self._pages.get(clean_id)
        if record is None:
            raise ValueError(
                f"browser multi-page context has no record for page {clean_id!r}; "
                "register it with browser.page.register before returning"
            )
        session = str(session_id or "").strip()
        if not session:
            raise ValueError("browser multi-page context return requires an open session")

        try:
            fresh = provider.observe(session, page_id=clean_id)
        except Exception as exc:
            reason = (
                f"page {clean_id!r} could not be re-observed on return: "
                f"{type(exc).__name__}: {exc}"
            )
            self._append_event(
                {
                    "kind": "page_return",
                    "page_id": clean_id,
                    "url_before": record.url,
                    "url_after": "",
                    "drifted": True,
                    "reason": reason,
                    "at": utc_now(),
                }
            )
            # The stale record is kept as-is: there is no fresh state to
            # refresh it with, and callers must treat it as unreliable.
            stale = BrowserPageRecord(
                **{**record.to_dict(), "drift_events": record.drift_events + 1}
            )
            self._pages[clean_id] = stale
            return BrowserPageReturn(
                fresh_observation=None,
                record=stale,
                drifted=True,
                drift_reason=reason,
            )

        if not isinstance(fresh, BrowserObservation):
            raise ValueError(
                "browser multi-page context return requires a BrowserObservation"
            )
        if str(getattr(fresh, "page_id", "") or "").strip() != clean_id:
            raise ValueError(
                "browser multi-page context return observed a different page "
                f"than requested: {str(getattr(fresh, 'page_id', '') or '')!r} != {clean_id!r}"
            )

        snapshot = _observation_snapshot(fresh)
        drift_reason = ""
        if snapshot["url"] != record.url:
            drift_reason = (
                f"page URL changed while away (was {record.url!r}, now {snapshot['url']!r})"
            )
        elif (
            snapshot["load_state"] in _FAILED_LOAD_STATES
            and record.load_state not in _FAILED_LOAD_STATES
        ):
            drift_reason = (
                f"page entered a failed load state ({snapshot['load_state']!r}) while away"
            )
        drifted = bool(drift_reason)

        refreshed = BrowserPageRecord(
            page_id=clean_id,
            task_role=record.task_role,
            note=record.note,
            url=snapshot["url"],
            title=snapshot["title"],
            load_state=snapshot["load_state"],
            captured_at=snapshot["captured_at"],
            registered_at=record.registered_at,
            reobservations=record.reobservations + 1,
            drift_events=record.drift_events + (1 if drifted else 0),
        )
        self._pages[clean_id] = refreshed
        self._append_event(
            {
                "kind": "page_return",
                "page_id": clean_id,
                "url_before": record.url,
                "url_after": snapshot["url"],
                "drifted": drifted,
                "reason": drift_reason,
                "at": utc_now(),
            }
        )
        return BrowserPageReturn(
            fresh_observation=fresh,
            record=refreshed,
            drifted=drifted,
            drift_reason=drift_reason,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "pages": [record.to_dict() for record in self._pages.values()],
            "events": [dict(event) for event in self._events],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> "BrowserMultiPageContext":
        context = cls()
        if raw is None:
            return context
        if not isinstance(raw, Mapping):
            raise ValueError("browser multi-page context must be an object")
        pages = raw.get("pages", [])
        if not isinstance(pages, list):
            raise ValueError("browser multi-page context pages must be a list")
        for item in pages:
            record = BrowserPageRecord.from_dict(item)
            if record.page_id in context._pages:
                raise ValueError(
                    "browser multi-page context has a duplicate page record"
                )
            if len(context._pages) >= _MAX_PAGES:
                raise ValueError(
                    f"browser multi-page context keeps at most {_MAX_PAGES} pages"
                )
            context._pages[record.page_id] = record
        events = raw.get("events", [])
        if not isinstance(events, list):
            raise ValueError("browser multi-page context events must be a list")
        for event in events:
            if not isinstance(event, dict):
                raise ValueError("browser multi-page context event must be an object")
            context._append_event(event)
        return context


def load_multipage_context(session: Mapping[str, Any] | None) -> BrowserMultiPageContext:
    """Load the retention context carried in a browser loop session dict."""
    if not session:
        return BrowserMultiPageContext()
    return BrowserMultiPageContext.from_dict(session.get("multipage_context"))


def store_multipage_context(
    session: dict[str, Any],
    context: BrowserMultiPageContext,
) -> dict[str, Any]:
    """Persist the retention context back into a browser loop session dict."""
    session["multipage_context"] = context.to_dict()
    return session
