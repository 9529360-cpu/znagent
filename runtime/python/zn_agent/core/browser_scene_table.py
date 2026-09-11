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
  if (!element || !element.isConnected) return {connected: false};
  const role = String(element.getAttribute?.("role") || "").trim().toLowerCase();
  const tag = String(element.tagName || "").trim().toLowerCase();
  const supported = tag === "table" || role === "table";
  if (!supported) return {connected: true, supported: false};

  const norm = (value) => String(value ?? "").replace(/\s+/g, " ").trim();
  const hidden = (node) => {
    if (!node || node.hidden || node.getAttribute?.("aria-hidden") === "true") return true;
    const style = window.getComputedStyle(node);
    return style.display === "none" || style.visibility === "hidden";
  };
  const positiveCount = (name) => {
    if (!element.hasAttribute?.(name)) return null;
    const raw = String(element.getAttribute(name) || "").trim();
    if (!/^\d+$/.test(raw)) return {invalid: true, value: null};
    const value = Number(raw);
    if (!Number.isSafeInteger(value) || value < 1) return {invalid: true, value: null};
    return {invalid: false, value};
  };

  if (element.querySelector("table, [role='table']")) {
    return {connected: true, supported: true, complex_reason: "nested_table"};
  }

  const rowNodes = tag === "table"
    ? Array.from(element.rows || [])
    : Array.from(element.querySelectorAll(
        ":scope > [role='row'], :scope > [role='rowgroup'] > [role='row']"
      ));
  if (rowNodes.some(hidden)) {
    return {connected: true, supported: true, complex_reason: "hidden_row"};
  }

  const ariaRows = positiveCount("aria-rowcount");
  const ariaCols = positiveCount("aria-colcount");
  if (ariaRows?.invalid || ariaCols?.invalid) {
    return {connected: true, supported: true, complex_reason: "invalid_aria_count"};
  }

  const rows = [];
  let truncated = rowNodes.length > limits.maxRows;
  let observedColumns = null;
  for (const row of rowNodes.slice(0, limits.maxRows)) {
    const rowTag = String(row.tagName || "").toLowerCase();
    const cellNodes = rowTag === "tr" && row.cells
      ? Array.from(row.cells)
      : Array.from(row.querySelectorAll(
          ":scope > [role='columnheader'], :scope > [role='rowheader'], :scope > [role='cell']"
        ));
    if (cellNodes.some(hidden)) {
      return {connected: true, supported: true, complex_reason: "hidden_cell"};
    }
    if (cellNodes.some((cell) =>
      cell.hasAttribute?.("rowspan") || cell.hasAttribute?.("colspan") ||
      cell.hasAttribute?.("aria-rowspan") || cell.hasAttribute?.("aria-colspan")
    )) {
      return {connected: true, supported: true, complex_reason: "cell_span"};
    }
    if (observedColumns === null) observedColumns = cellNodes.length;
    if (cellNodes.length > limits.maxCells) truncated = true;
    const cells = cellNodes.slice(0, limits.maxCells).map((cell) => {
      const cellRole = String(cell.getAttribute?.("role") || "").trim().toLowerCase();
      const cellTag = String(cell.tagName || "").trim().toLowerCase();
      const kind = cellTag === "th" || cellRole === "columnheader" || cellRole === "rowheader"
        ? "header" : "cell";
      const text = norm(cell.innerText ?? cell.textContent ?? "");
      return {
        kind,
        text: text.slice(0, limits.maxText),
        truncated: text.length > limits.maxText,
      };
    });
    if (cells.some((cell) => cell.truncated)) truncated = true;
    rows.push(cells);
  }

  const rowCount = rowNodes.length;
  const materializedCols = observedColumns === null ? 0 : observedColumns;
  if (ariaRows && ariaRows.value !== rowCount) {
    return {connected: true, supported: true, complex_reason: "aria_rowcount_mismatch"};
  }
  if (ariaCols && ariaCols.value !== materializedCols) {
    return {connected: true, supported: true, complex_reason: "aria_colcount_mismatch"};
  }
  return {
    connected: true,
    supported: true,
    row_count_observed: rowCount,
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
    """Observe one exact current main-frame table without widening browser authority."""

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
        # Revalidate the retained BrowserScene binding before reading table payload.
        # This is the existing browser authority for exact-node continuity; this
        # mixin deliberately does not invent a second locator or target identity.
        self._scene_revalidate_binding(session, binding)
        if str(binding.scene_target.role or "") != "table":
            raise ManagedBrowserError(
                "structured table observation requires a BrowserScene table target"
            )
        page = self._page(session, binding.page_id)
        if binding.frame is not getattr(page, "main_frame", None):
            raise ManagedBrowserError(
                "structured table observation currently supports only a main-frame table target"
            )

        row_limit = max(1, min(int(max_rows), _MAX_TABLE_ROWS))
        cell_limit = max(1, min(int(max_cells_per_row), _MAX_TABLE_CELLS_PER_ROW))
        text_limit = max(1, min(int(max_cell_text), _MAX_CELL_TEXT))
        try:
            raw = binding.handle.evaluate(
                _TABLE_SCRIPT,
                {"maxRows": row_limit, "maxCells": cell_limit, "maxText": text_limit},
            )
        except Exception as exc:
            raise ManagedBrowserError(
                f"structured table provider failed: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise ManagedBrowserError("structured table provider returned malformed evidence")
        if raw.get("connected") is not True:
            raise ManagedBrowserError("structured table target detached during observation")
        if raw.get("supported") is not True:
            raise ManagedBrowserError(
                "structured table observation supports native/ARIA table targets only"
            )
        complex_reason = raw.get("complex_reason")
        if complex_reason is not None:
            if not isinstance(complex_reason, str) or not complex_reason:
                raise ManagedBrowserError(
                    "structured table provider returned malformed complexity evidence"
                )
            raise ManagedBrowserError(
                f"structured table is outside the bounded simple-table scope: {complex_reason}"
            )

        rows_raw = raw.get("rows")
        observed_count = raw.get("row_count_observed")
        truncated = raw.get("truncated")
        if not isinstance(rows_raw, list):
            raise ManagedBrowserError("structured table provider returned invalid rows")
        if (
            isinstance(observed_count, bool)
            or not isinstance(observed_count, int)
            or observed_count < 0
        ):
            raise ManagedBrowserError("structured table provider returned invalid row count")
        if not isinstance(truncated, bool):
            raise ManagedBrowserError(
                "structured table provider returned invalid truncation evidence"
            )
        if len(rows_raw) > row_limit or observed_count < len(rows_raw):
            raise ManagedBrowserError(
                "structured table provider exceeded its bounded row contract"
            )

        rows: list[BrowserTableRow] = []
        for raw_row in rows_raw:
            if not isinstance(raw_row, list) or len(raw_row) > cell_limit:
                raise ManagedBrowserError("structured table provider returned invalid row")
            cells: list[BrowserTableCell] = []
            for raw_cell in raw_row:
                if not isinstance(raw_cell, dict):
                    raise ManagedBrowserError(
                        "structured table provider returned invalid cell"
                    )
                kind = raw_cell.get("kind")
                text = raw_cell.get("text")
                cell_truncated = raw_cell.get("truncated")
                if kind not in {"cell", "header"} or not isinstance(text, str):
                    raise ManagedBrowserError(
                        "structured table provider returned malformed cell evidence"
                    )
                if len(text) > text_limit or not isinstance(cell_truncated, bool):
                    raise ManagedBrowserError(
                        "structured table provider exceeded its bounded cell contract"
                    )
                if cell_truncated and not truncated:
                    raise ManagedBrowserError(
                        "structured table provider returned inconsistent truncation evidence"
                    )
                cells.append(BrowserTableCell(kind=kind, text=text))
            rows.append(BrowserTableRow(cells=tuple(cells)))

        return BrowserStructuredTable(
            session_id=session.identity.session_id,
            page_id=binding.page_id,
            target_id=binding.target.target_id,
            captured_at=utc_now(),
            rows=tuple(rows),
            row_count_observed=observed_count,
            truncated=truncated,
        )
