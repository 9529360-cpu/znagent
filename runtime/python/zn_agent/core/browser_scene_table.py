from __future__ import annotations

"""Bounded structured-table sensing for exact BrowserScene table targets."""

from dataclasses import dataclass
from typing import Any

from .managed_browser import ManagedBrowserError
from .models import utc_now


_MAX_TABLE_ROWS = 64
_MAX_TABLE_CELLS_PER_ROW = 32
_MAX_CELL_TEXT = 512

_TABLE_SCRIPT = r"""
(element, limits) => {
  if (!element || !element.isConnected) return { connected: false };
  const role = String(element.getAttribute?.("role") || "").toLowerCase();
  const tag = String(element.tagName || "").toLowerCase();
  const supported = tag === "table" || role === "table" || role === "grid";
  if (!supported) return { connected: true, supported: false };
  const norm = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const rowNodes = Array.from(element.querySelectorAll("tr,[role='row']"));
  const rows = [];
  let truncated = rowNodes.length > limits.maxRows;
  for (const row of rowNodes.slice(0, limits.maxRows)) {
    const cellNodes = Array.from(
      row.querySelectorAll(":scope > th,:scope > td,:scope > [role='columnheader'],:scope > [role='rowheader'],:scope > [role='cell'],:scope > [role='gridcell']")
    );
    if (cellNodes.length > limits.maxCells) truncated = true;
    const cells = cellNodes.slice(0, limits.maxCells).map((cell) => {
      const cellRole = String(cell.getAttribute?.("role") || "").toLowerCase();
      const cellTag = String(cell.tagName || "").toLowerCase();
      let kind = "cell";
      if (cellTag === "th" || cellRole === "columnheader" || cellRole === "rowheader") {
        kind = "header";
      }
      const text = norm(cell.innerText || cell.textContent || "");
      return { kind, text: text.slice(0, limits.maxText), truncated: text.length > limits.maxText };
    });
    if (cells.some((cell) => cell.truncated)) truncated = true;
    rows.push(cells);
  }
  return {
    connected: true,
    supported: true,
    row_count_observed: rowNodes.length,
    rows,
    truncated,
  };
}
"""


@dataclass(frozen=True, slots=True)
class BrowserTableCell:
    kind: str
    text: str


@dataclass(frozen=True, slots=True)
class BrowserTableRow:
    cells: tuple[BrowserTableCell, ...]


@dataclass(frozen=True, slots=True)
class BrowserStructuredTable:
    session_id: str
    page_id: str
    target_id: str
    captured_at: str
    rows: tuple[BrowserTableRow, ...]
    row_count_observed: int
    truncated: bool


class PlaywrightBrowserSceneTableMixin:
    """Observe one exact current BrowserScene table as bounded structured rows/cells."""

    def observe_scene_table(
        self,
        session_id: str,
        target_id: str,
        *,
        page_id: str = "",
        max_rows: int = _MAX_TABLE_ROWS,
        max_cells_per_row: int = _MAX_TABLE_CELLS_PER_ROW,
        max_cell_text: int = _MAX_CELL_TEXT,
    ) -> BrowserStructuredTable:
        session = self._session(session_id)
        binding = self._scene_action_binding(
            session,
            str(target_id or "").strip(),
            page_id=page_id,
        )
        self._scene_revalidate_binding(session, binding)
        if str(binding.scene_target.role or "") != "table":
            raise ManagedBrowserError(
                "structured table observation requires a BrowserScene table target"
            )

        row_limit = max(1, min(int(max_rows), _MAX_TABLE_ROWS))
        cell_limit = max(1, min(int(max_cells_per_row), _MAX_TABLE_CELLS_PER_ROW))
        text_limit = max(1, min(int(max_cell_text), _MAX_CELL_TEXT))
        try:
            raw = binding.handle.evaluate(
                _TABLE_SCRIPT,
                {
                    "maxRows": row_limit,
                    "maxCells": cell_limit,
                    "maxText": text_limit,
                },
            )
        except Exception as exc:
            raise ManagedBrowserError(
                f"structured table provider failed: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(raw, dict) or not bool(raw.get("connected")):
            raise ManagedBrowserError("structured table target detached during observation")
        if not bool(raw.get("supported")):
            raise ManagedBrowserError(
                "structured table observation supports native/ARIA table targets only"
            )

        rows_raw = raw.get("rows")
        if not isinstance(rows_raw, list):
            raise ManagedBrowserError("structured table provider returned invalid rows")
        rows: list[BrowserTableRow] = []
        for raw_row in rows_raw[:row_limit]:
            if not isinstance(raw_row, list):
                raise ManagedBrowserError("structured table provider returned invalid row")
            cells: list[BrowserTableCell] = []
            for raw_cell in raw_row[:cell_limit]:
                if not isinstance(raw_cell, dict):
                    raise ManagedBrowserError(
                        "structured table provider returned invalid cell"
                    )
                kind = str(raw_cell.get("kind") or "cell")
                if kind not in {"cell", "header"}:
                    kind = "cell"
                text = str(raw_cell.get("text") or "")[:text_limit]
                cells.append(BrowserTableCell(kind=kind, text=text))
            rows.append(BrowserTableRow(cells=tuple(cells)))

        observed_count = raw.get("row_count_observed")
        if not isinstance(observed_count, int) or observed_count < 0:
            observed_count = len(rows)
        return BrowserStructuredTable(
            session_id=session.identity.session_id,
            page_id=binding.page_id,
            target_id=binding.target.target_id,
            captured_at=utc_now(),
            rows=tuple(rows),
            row_count_observed=observed_count,
            truncated=bool(raw.get("truncated")),
        )
