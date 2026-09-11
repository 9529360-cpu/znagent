from __future__ import annotations

"""E2E-11: bounded Managed Browser table -> attached-workspace XLSX copy."""

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .browser import BrowserPlane
from .file_identity import compare_file_identities
from .models import ExecutionPath, ResidentRunResult, utc_now
from .spreadsheet_work import append_xlsx_rows_copy, inspect_xlsx_append_target

_STATE_KEY = "browser_spreadsheet_work_v1"
_INSTALL_MARKER = "_zn_browser_spreadsheet_work_v1_installed"
_ACCEPTANCE = "browser_spreadsheet_import:v1"
_INTENTS = (
    "把这个网站里的数据整理进我现在这个表里",
    "把这个网页里的数据整理进我现在这个表里",
    "把这个网站的数据整理进我现在这个表里",
    "put the data from this website into my current spreadsheet",
)


class _Blocked(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code, self.detail = code, detail


def _is_request(event) -> bool:
    if str(getattr(event, "kind", "") or "").lower() != "desktop_user_event":
        return False
    payload = getattr(event, "payload", {}) or {}
    if payload.get("body_action") or payload.get("native_action"):
        return False
    task = " ".join(str(getattr(event, "task", "") or "").split()).casefold()
    return any(marker.casefold() in task for marker in _INTENTS)


def _hash_table(url: str, headers: list[str], rows: list[list[str]]) -> str:
    raw = {
        "url": url,
        "headers": headers,
        "rows": rows,
        "row_count": len(rows) + 1,
        "column_count": len(headers),
    }
    return hashlib.sha256(
        json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _child_evidence(meta: Mapping[str, Any], status: str, blocker: str | None) -> dict[str, Any]:
    capture = meta.get("browser_capture") if isinstance(meta.get("browser_capture"), Mapping) else {}
    source = meta.get("source_inspection") if isinstance(meta.get("source_inspection"), Mapping) else {}
    mutation = meta.get("mutation_result") if isinstance(meta.get("mutation_result"), Mapping) else {}
    verify = meta.get("verification") if isinstance(meta.get("verification"), Mapping) else {}
    return {
        "version": 1,
        "status": status,
        "acceptance": _ACCEPTANCE,
        "browser_provider": capture.get("provider"),
        "browser_session_id": meta.get("browser_session_id"),
        "page_id": meta.get("page_id"),
        "source_url": capture.get("url"),
        "table_target_identity": capture.get("target"),
        "ordered_headers": capture.get("headers"),
        "imported_row_count": capture.get("data_row_count"),
        "imported_column_count": capture.get("column_count"),
        "browser_source_fingerprint": capture.get("fingerprint"),
        "source_spreadsheet_path": meta.get("spreadsheet_path"),
        "source_spreadsheet_initial_identity": source.get("identity"),
        "source_spreadsheet_initial_semantic_fingerprint": source.get("semantic_fingerprint"),
        "destination_path": meta.get("destination_path"),
        "destination_identity": mutation.get("destination_identity"),
        "mutation_result": mutation,
        "fresh_browser_verification_fingerprint": verify.get("browser_fingerprint"),
        "fresh_source_xlsx_identity_result": verify.get("source_identity"),
        "fresh_destination_reopen_result": verify.get("destination"),
        "blocker": blocker,
    }


def _persist(resident, event, meta: Mapping[str, Any], status: str, blocker: str | None = None) -> None:
    root = resident.work_ledger.work_item_for_event(event.event_id)
    if root is None:
        return
    item = next((
        item for item in resident.work_ledger.list_work_items(root.work_thread_id, limit=256)
        if item.parent_work_item_id == root.work_item_id
        and item.plan_version == root.plan_version
        and _ACCEPTANCE in item.acceptance_criteria
    ), None)
    if item is None:
        item = resident.work_ledger.create_child_item(
            root_work_item_id=root.work_item_id,
            objective="Preserve exact Browser source, XLSX append-copy, and fresh completion evidence",
            acceptance_criteria=[_ACCEPTANCE],
            title="Browser data to spreadsheet",
        )
    item.status = "completed" if status == "complete" else "blocked" if status == "blocked" else "running"
    item.result = json.dumps(_child_evidence(meta, status, blocker), ensure_ascii=False, separators=(",", ":"))
    item.blocker = blocker
    item.updated_at = utc_now()
    if status == "complete":
        item.completed_at = item.updated_at
    resident.work_ledger._save_item(item)


def _fail(resident, event, state, meta: dict[str, Any], code: str, detail: str, response: str) -> ResidentRunResult:
    reason = f"{code}: {detail}"[:4000]
    meta["blocker"] = {"code": code, "detail": str(detail)[:2000]}
    state.data[_STATE_KEY] = meta
    state.stage, state.next_action, state.blocked_by = "failed", None, code
    resident.store.save_working_state(state)
    _persist(resident, event, meta, "blocked", reason)
    return ResidentRunResult(
        event=event,
        execution_path=ExecutionPath.INVESTIGATION,
        success=False,
        response=response[:8000],
        model_invocations=0,
        reason=reason,
    )


def _authorized_context(resident, event, root):
    payload = getattr(event, "payload", {}) or {}
    workspace_raw = str(payload.get("workspace_path") or "").strip()
    spreadsheet_raw = str(payload.get("spreadsheet_path") or "").strip()
    session_id = str(payload.get("browser_session_id") or "").strip()
    page_id = str(payload.get("page_id") or "").strip()
    if not session_id or not page_id:
        raise _Blocked("browser_context_missing", "exact browser_session_id and page_id are required")
    if not workspace_raw or not spreadsheet_raw:
        raise _Blocked("spreadsheet_context_missing", "exact workspace_path and spreadsheet_path are required")
    thread = resident.work_ledger.get_thread(root.work_thread_id)
    attached = resident.work_ledger.workspace_for(thread) if thread is not None else None
    if attached is None:
        raise _Blocked("workspace_authority_missing", "Root Work has no attached workspace")
    try:
        workspace = Path(workspace_raw).resolve(strict=True)
        attached_path = Path(attached.path).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _Blocked("workspace_authority_missing", str(exc)) from exc
    if workspace != attached_path or not workspace.is_dir():
        raise _Blocked("workspace_authority_missing", "event workspace does not exactly match attached workspace")
    raw_path = Path(spreadsheet_raw)
    if not raw_path.is_absolute() or ".." in raw_path.parts:
        raise _Blocked("spreadsheet_authority_missing", "spreadsheet_path must be absolute and traversal-free")
    try:
        source = raw_path.resolve(strict=True)
        source.relative_to(workspace)
    except (OSError, RuntimeError, ValueError) as exc:
        raise _Blocked("spreadsheet_authority_missing", "spreadsheet escapes or is unavailable inside workspace") from exc
    if not source.is_file() or source.suffix.casefold() != ".xlsx":
        raise _Blocked("spreadsheet_authority_missing", "spreadsheet_path must identify one existing .xlsx")
    destination = (workspace / f"{source.stem}-webdata.xlsx").resolve(strict=False)
    if destination.parent != workspace:
        raise _Blocked("spreadsheet_authority_missing", "derived output left attached workspace")
    return workspace, source, destination, session_id, page_id


def _fresh_table(resident, session_id: str, page_id: str) -> dict[str, Any]:
    browser = resident.managed_browser
    if getattr(browser, "plane", None) is not BrowserPlane.MANAGED:
        raise _Blocked(
            "unsupported_browser_plane",
            "E2E-11 Browser table import is supported only on the managed browser plane",
        )
    try:
        session = browser._session(session_id)
    except Exception as exc:
        raise _Blocked(
            "browser_context_invalid",
            f"exact managed browser session is unavailable: {type(exc).__name__}: {exc}",
        ) from exc
    if getattr(getattr(session, "identity", None), "plane", None) is not BrowserPlane.MANAGED:
        raise _Blocked(
            "unsupported_browser_plane",
            "E2E-11 Browser table import requires a managed-plane session identity",
        )
    try:
        scene = browser.observe_scene(session_id, page_id=page_id)
    except Exception as exc:
        raise _Blocked("browser_context_invalid", f"fresh BrowserScene failed: {type(exc).__name__}: {exc}") from exc
    if bool(scene.truncated):
        raise _Blocked("browser_scene_truncated", "table uniqueness cannot be proven from a truncated scene")
    main_frames = {frame.frame_id for frame in scene.frames if frame.is_main and frame.observable}
    tables = [target for target in scene.targets if target.role == "table" and target.frame_id in main_frames]
    if not tables:
        raise _Blocked("browser_table_not_found", "no current main-frame table exists")
    if len(tables) != 1:
        raise _Blocked("ambiguous_browser_table", f"expected one main-frame table, observed {len(tables)}")
    target = tables[0]
    try:
        table = browser.observe_scene_table(session_id, target.target_id, page_id=page_id)
    except Exception as exc:
        raise _Blocked("browser_table_observation_failed", f"structured table failed: {type(exc).__name__}: {exc}") from exc
    if table.truncated:
        raise _Blocked("browser_table_truncated", "structured table exceeded complete-table bounds")
    if table.row_count_observed != len(table.rows):
        raise _Blocked("browser_table_incomplete", "table row count is not fully materialized")
    if len(table.rows) < 2:
        raise _Blocked("browser_table_invalid", "one header row and at least one data row are required")
    header_cells = list(table.rows[0].cells)
    if not header_cells or any(cell.kind != "header" for cell in header_cells):
        raise _Blocked("browser_table_invalid", "first row must be the unique header row")
    headers = [cell.text for cell in header_cells]
    if any(not value for value in headers) or len(set(headers)) != len(headers):
        raise _Blocked("browser_table_invalid", "headers must be non-empty and unique")
    rows: list[list[str]] = []
    for row in table.rows[1:]:
        cells = list(row.cells)
        if len(cells) != len(headers) or any(cell.kind != "cell" for cell in cells):
            raise _Blocked("browser_table_invalid", "data rows must be rectangular and contain no header cells")
        rows.append([cell.text for cell in cells])
    if not rows:
        raise _Blocked("browser_table_invalid", "table has no data rows")
    provider = str(session.identity.provider or "")
    return {
        "provider": provider,
        "url": str(scene.url or ""),
        "target": {
            "target_id": target.target_id,
            "frame_id": target.frame_id,
            "role": target.role,
            "accessible_name": target.accessible_name,
        },
        "headers": headers,
        "rows": rows,
        "data_row_count": len(rows),
        "column_count": len(headers),
        "fingerprint": _hash_table(str(scene.url or ""), headers, rows),
    }


def _set_stage(resident, state, meta: dict[str, Any], stage: str, next_action: str) -> None:
    state.data[_STATE_KEY] = meta
    state.stage, state.next_action, state.blocked_by = stage, next_action, None
    resident.store.save_working_state(state)


def _begin(resident, event, state):
    root = resident.work_ledger.work_item_for_event(event.event_id)
    if root is None or root.parent_work_item_id is not None:
        return _fail(resident, event, state, {}, "missing_root_work", "durable Root Work is required", "当前任务没有绑定到 Root Work，未写入文件。")
    try:
        workspace, source, destination, session_id, page_id = _authorized_context(resident, event, root)
    except _Blocked as exc:
        return _fail(resident, event, state, {}, exc.code, exc.detail, "缺少唯一且已授权的当前网页或 XLSX 上下文，未写入文件。")
    meta = {
        "work_thread_id": root.work_thread_id,
        "root_work_item_id": root.work_item_id,
        "plan_version": root.plan_version,
        "workspace_path": str(workspace),
        "spreadsheet_path": str(source),
        "destination_path": str(destination),
        "browser_session_id": session_id,
        "page_id": page_id,
        "model_invocations": 0,
    }
    _set_stage(resident, state, meta, "browser_spreadsheet_capture", "capture exact current Browser table")
    _persist(resident, event, meta, "binding")
    return None


def _capture(resident, event, state):
    meta = dict(state.data.get(_STATE_KEY) or {})
    try:
        meta["browser_capture"] = _fresh_table(resident, meta["browser_session_id"], meta["page_id"])
    except _Blocked as exc:
        return _fail(resident, event, state, meta, exc.code, exc.detail, "当前网页没有一个可唯一完整验证的简单表格，未写入 XLSX。")
    _set_stage(resident, state, meta, "browser_spreadsheet_inspect", "inspect exact current XLSX append target")
    _persist(resident, event, meta, "captured")
    return None


def _inspect(resident, event, state):
    meta = dict(state.data.get(_STATE_KEY) or {})
    result = resident.body.act("inspect_xlsx_append_target", event_id=event.event_id, path=meta["spreadsheet_path"])
    if not result.success:
        return _fail(resident, event, state, meta, "spreadsheet_inspection_failed", result.error or "inspection failed", "当前 XLSX 无法安全检查，未生成新文件。")
    inspection = dict(result.data)
    if inspection.get("ready") is not True:
        return _fail(resident, event, state, meta, str(inspection.get("blocker") or "unsupported_workbook_structure"), str(inspection.get("detail") or "unsupported XLSX"), "当前 XLSX 超出安全 round-trip 范围，未生成新文件。")
    capture = meta["browser_capture"]
    if list(inspection.get("headers") or []) != list(capture["headers"]):
        return _fail(resident, event, state, meta, "spreadsheet_header_mismatch", "Browser and XLSX headers differ", "网页表头与 XLSX 第一行表头不是逐列完全一致，未写入。")
    if Path(meta["destination_path"]).exists():
        return _fail(resident, event, state, meta, "output_collision", "destination already exists", "固定输出文件已存在，为避免覆盖已停止。")
    meta["source_inspection"] = inspection
    _set_stage(resident, state, meta, "browser_spreadsheet_mutate", "re-observe Browser and publish verified append-copy")
    _persist(resident, event, meta, "bound")
    return None


def _mutate(resident, event, state):
    meta = dict(state.data.get(_STATE_KEY) or {})
    capture, inspection = meta["browser_capture"], meta["source_inspection"]
    try:
        fresh = _fresh_table(resident, meta["browser_session_id"], meta["page_id"])
    except _Blocked as exc:
        return _fail(resident, event, state, meta, "stale_browser_table_evidence", f"{exc.code}: {exc.detail}", "网页表格在写入前无法重新证明一致，未生成目标 XLSX。")
    if fresh["fingerprint"] != capture["fingerprint"]:
        return _fail(resident, event, state, meta, "stale_browser_table_evidence", "Browser URL/header/rows/count changed", "网页表格在捕获后发生变化，已在写入前停止。")
    if Path(meta["destination_path"]).exists():
        return _fail(resident, event, state, meta, "output_collision", "destination appeared before mutation", "输出路径发生冲突，为避免覆盖已停止。")
    result = resident.body.act(
        "append_xlsx_rows_copy",
        event_id=event.event_id,
        source_path=meta["spreadsheet_path"],
        destination_path=meta["destination_path"],
        precondition_identity=dict(inspection["identity"]),
        headers=list(capture["headers"]),
        rows=[list(row) for row in capture["rows"]],
    )
    if not result.success:
        error = str(result.error or "append-copy failed")
        code = "stale_source_evidence" if "stale_source_evidence" in error else "output_collision" if "output_collision" in error or "destination already exists" in error else "spreadsheet_header_mismatch" if "spreadsheet_header_mismatch" in error else "spreadsheet_mutation_failed"
        return _fail(resident, event, state, meta, code, error, "XLSX append-copy 未通过 deterministic Body 执行与验证，任务未完成。")
    meta["mutation_result"] = dict(result.data)
    _set_stage(resident, state, meta, "browser_spreadsheet_verify", "freshly re-observe Browser and reopen both XLSX files")
    _persist(resident, event, meta, "mutated")
    return None


def _verify(resident, event, state):
    meta = dict(state.data.get(_STATE_KEY) or {})
    capture, inspection, mutation = meta["browser_capture"], meta["source_inspection"], meta["mutation_result"]
    try:
        browser = _fresh_table(resident, meta["browser_session_id"], meta["page_id"])
    except _Blocked as exc:
        return _fail(resident, event, state, meta, "completion_verification_failed", f"Browser: {exc.code}: {exc.detail}", "目标副本已尝试生成，但网页来源未通过 fresh verification，任务未标记完成。")
    source = resident.body.act("inspect_xlsx_append_target", event_id=event.event_id, path=meta["spreadsheet_path"])
    destination = resident.body.act("inspect_xlsx_append_target", event_id=event.event_id, path=meta["destination_path"])
    if not source.success or not destination.success:
        return _fail(resident, event, state, meta, "completion_verification_failed", source.error or destination.error or "fresh reopen failed", "源或目标 XLSX 未通过 fresh reopen，任务未标记完成。")
    checks = {
        "browser_exact": browser["fingerprint"] == capture["fingerprint"],
        "source_ready": source.data.get("ready") is True,
        "source_identity_exact": compare_file_identities(dict(inspection["identity"]), dict(source.data.get("identity") or {})).get("exact") is True,
        "source_semantic_exact": source.data.get("semantic_fingerprint") == inspection.get("semantic_fingerprint"),
        "destination_ready": destination.data.get("ready") is True,
        "destination_identity_exact": compare_file_identities(dict(mutation.get("destination_identity") or {}), dict(destination.data.get("identity") or {})).get("exact") is True,
        "destination_semantic_exact": destination.data.get("semantic_fingerprint") == mutation.get("destination_semantic_fingerprint"),
        "destination_shape_exact": destination.data.get("sheet_name") == mutation.get("sheet_name") and list(destination.data.get("headers") or []) == list(capture["headers"]) and destination.data.get("existing_row_count") == mutation.get("final_data_rows"),
        "mutation_proof": mutation.get("source_unchanged") is True and mutation.get("destination_reopened") is True and mutation.get("existing_content_unchanged") is True and mutation.get("appended_rows_exact") is True and mutation.get("imported_row_count") == capture.get("data_row_count"),
    }
    meta["verification"] = {
        "browser_fingerprint": browser["fingerprint"],
        "source_identity": dict(source.data.get("identity") or {}),
        "destination": dict(destination.data),
        **checks,
    }
    state.data[_STATE_KEY] = meta
    if not all(checks.values()):
        return _fail(resident, event, state, meta, "completion_verification_failed", json.dumps(checks, ensure_ascii=False), "Browser、源 XLSX、目标 XLSX 的 fresh verification 未全部通过，任务未标记完成。")
    state.stage, state.next_action, state.blocked_by = "complete", None, None
    resident.store.save_working_state(state)
    _persist(resident, event, meta, "complete")
    return ResidentRunResult(
        event=event,
        execution_path=ExecutionPath.INVESTIGATION,
        success=True,
        response=f"网页表格数据已追加到安全副本：{meta['destination_path']}。原 XLSX 未变，Browser 与两个 XLSX 均已 fresh verify。",
        model_invocations=0,
        reason="E2E-11 completed only after fresh Browser/source/destination verification",
    )


def install_browser_spreadsheet_behavior(resident) -> None:
    """Compose E2E-11 onto the existing Product Resident and unified Body."""
    if getattr(resident, _INSTALL_MARKER, False):
        return
    body = resident.body
    original_dispatch = body._dispatch

    def dispatch(action, started):
        if action.kind == "inspect_xlsx_append_target":
            path = action.args.get("path") or action.args.get("source_path")
            return body._ok(action, started, output=str(path or ""), data=inspect_xlsx_append_target(path))
        if action.kind == "append_xlsx_rows_copy":
            data = append_xlsx_rows_copy(
                action.args.get("source_path"),
                action.args.get("destination_path"),
                precondition_identity=dict(action.args.get("precondition_identity") or {}),
                headers=list(action.args.get("headers") or []),
                rows=[list(row) for row in (action.args.get("rows") or [])],
            )
            return body._ok(action, started, output=str(action.args.get("destination_path") or ""), data=data)
        return original_dispatch(action, started)

    original_advance = resident._advance_event_step

    def advance(event, state, *, readiness, learning_evidence, thought=None):
        stage = str(state.stage or "")
        if stage == "orient" and _is_request(event):
            return _begin(resident, event, state)
        handlers = {
            "browser_spreadsheet_capture": _capture,
            "browser_spreadsheet_inspect": _inspect,
            "browser_spreadsheet_mutate": _mutate,
            "browser_spreadsheet_verify": _verify,
        }
        if stage in handlers:
            return handlers[stage](resident, event, state)
        return original_advance(event, state, readiness=readiness, learning_evidence=learning_evidence, thought=thought)

    body._dispatch = dispatch
    resident._advance_event_step = advance
    setattr(resident, _INSTALL_MARKER, True)
