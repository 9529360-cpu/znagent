from __future__ import annotations

"""Local Documents & Spreadsheet Work 1.0 on the existing Resident/Body/Work."""

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from .file_identity import compare_file_identities
from .models import ExecutionPath, ResidentRunResult, utc_now
from .office_document import inspect_docx, write_docx_copy
from .spreadsheet_work import AMOUNT_NUMBER_FORMAT, inspect_xlsx, write_xlsx_copy

_STATE_KEY = "local_office_work_v1"
_INSTALL_MARKER = "_zn_local_office_work_v1_installed"
_DOCX_ACCEPTANCE = "local_document_work:v1"
_XLSX_ACCEPTANCE = "spreadsheet_cleanup_work:v1"
MAX_ENTRIES = 64
MAX_CANDIDATES = 8
_DATE_TOKEN = re.compile(
    r"(?<!\d)(?:(?P<cy>\d{4})年(?P<cm>\d{1,2})月(?P<cd>\d{1,2})日|"
    r"(?P<iy>\d{4})[-/.](?P<im>\d{1,2})[-/.](?P<id>\d{1,2}))(?!\d)"
)


def _request(event) -> str | None:
    if str(getattr(event, "kind", "") or "").lower() != "desktop_user_event":
        return None
    payload = getattr(event, "payload", {}) or {}
    if payload.get("body_action") or payload.get("native_action"):
        return None
    task = " ".join(str(getattr(event, "task", "") or "").split())
    lowered = task.casefold()
    docx = bool(
        "昨天" in task
        and "合同" in task
        and "付款日期" in task
        and "项目文件夹" in task
        and any(marker in task for marker in ("保存", "放到", "放进"))
    )
    xlsx = bool(
        "昨天" in task
        and "表" in task
        and "重复" in task
        and "金额" in task
        and any(marker in task for marker in ("别动原文件", "不要动原文件", "不动原文件"))
        and any(marker in task for marker in ("处理好的版本", "整理好的版本", "新版本"))
    )
    if docx and any(marker in lowered for marker in (".docx", "合同", "word")):
        return "docx"
    return "xlsx" if xlsx else None


def _normalize_date_match(match: re.Match[str]) -> str | None:
    year = int(match.group("cy") or match.group("iy") or 0)
    month = int(match.group("cm") or match.group("im") or 0)
    day = int(match.group("cd") or match.group("id") or 0)
    try:
        value = date(year, month, day)
    except ValueError:
        return None
    return f"{value.year}年{value.month}月{value.day}日"


def _dates(text: str) -> list[str]:
    values = [_normalize_date_match(match) for match in _DATE_TOKEN.finditer(str(text or ""))]
    return list(dict.fromkeys(value for value in values if value))


def _agreed_date(resident, event, thread_id: str):
    current = _dates(event.task)
    if len(current) == 1:
        return current[0], {"source": "current_user_message", "normalized_date": current[0]}, None
    if len(current) > 1:
        return None, None, "current user message contains multiple explicit dates"
    current_message_id = str((event.payload or {}).get("work_message_id") or "")
    relevant: list[tuple[str, str]] = []
    for message in resident.work_ledger.list_messages(thread_id, limit=12):
        if message.role != "user" or message.message_id == current_message_id:
            continue
        text = str(message.text or "")
        lowered = text.casefold()
        payment_cue = any(marker in lowered for marker in ("付款日期", "付款", "payment date", "payment"))
        agreement_cue = any(marker in lowered for marker in ("说好的", "说好", "约定", "确认", "agreed"))
        if not (payment_cue or (agreement_cue and "日期" in lowered)):
            continue
        for value in _dates(text):
            relevant.append((value, message.message_id))
    unique = list(dict.fromkeys(value for value, _ in relevant))
    if len(unique) == 1:
        return unique[0], {
            "source": "current_work_confirmed_context",
            "normalized_date": unique[0],
            "message_ids": list(dict.fromkeys(mid for value, mid in relevant if value == unique[0]))[-4:],
        }, None
    if len(unique) > 1:
        return None, None, "current Work contains multiple plausible agreed payment dates"
    return None, None, "current Work does not contain one explicit agreed payment date"


def _authorized_paths(resident, event, thread_id: str):
    explicit_destination = str((event.payload or {}).get("workspace_path") or "").strip()
    explicit_source = str(
        (event.payload or {}).get("downloads_path")
        or (event.payload or {}).get("source_workspace_path")
        or ""
    ).strip()
    if not explicit_destination or not explicit_source:
        return None, None, "local Office work requires an exact attached project workspace and an explicitly authorized source workspace"
    thread = resident.work_ledger.get_thread(thread_id)
    association = resident.work_ledger.workspace_for(thread) if thread is not None else None
    if association is None:
        return None, None, "local Office work has no attached project workspace"
    try:
        destination = Path(explicit_destination).resolve(strict=True)
        attached = Path(association.path).resolve(strict=True)
        source = Path(explicit_source).resolve(strict=True)
    except (OSError, RuntimeError):
        return None, None, "authorized source or destination workspace is unavailable"
    if destination != attached or not destination.is_dir() or not source.is_dir():
        return None, None, "Office source/destination authority does not match current Work workspace evidence"
    return source, destination, None


def _local_day(identity: Mapping[str, Any]) -> date | None:
    try:
        mtime_ns = int(identity.get("mtime_ns") or 0)
        return datetime.fromtimestamp(mtime_ns / 1_000_000_000).astimezone().date() if mtime_ns > 0 else None
    except (OSError, OverflowError, TypeError, ValueError):
        return None


def _evidence(meta: Mapping[str, Any], *, status: str, blocker: str | None = None) -> dict[str, Any]:
    selected = meta.get("selected") if isinstance(meta.get("selected"), Mapping) else {}
    result = meta.get("operation_result") if isinstance(meta.get("operation_result"), Mapping) else {}
    verified = meta.get("verification") if isinstance(meta.get("verification"), Mapping) else {}
    return {
        "version": 1,
        "status": status,
        "kind": meta.get("kind"),
        "source_workspace": meta.get("source_workspace"),
        "destination_workspace": meta.get("destination_workspace"),
        "source_path": selected.get("path"),
        "source_observed_date": selected.get("observed_date"),
        "source_identity": selected.get("identity"),
        "destination_path": meta.get("destination_path"),
        "operation": "replace_payment_date" if meta.get("kind") == "docx" else "exact_duplicate_removal_and_amount_format_normalization",
        "target": meta.get("date_evidence") if meta.get("kind") == "docx" else selected.get("inspection"),
        "before": {"source_identity": selected.get("identity"), "source_inspection": selected.get("inspection")},
        "after": {"destination_identity": result.get("destination_identity"), "source_identity": result.get("source_identity_after")},
        "verification": verified,
        "blocker": blocker,
    }


def _persist(resident, event, meta: Mapping[str, Any], *, status: str, blocker: str | None = None) -> None:
    root = resident.work_ledger.work_item_for_event(event.event_id)
    if root is None:
        return
    acceptance = _DOCX_ACCEPTANCE if meta.get("kind") == "docx" else _XLSX_ACCEPTANCE
    item = next(
        (
            value for value in resident.work_ledger.list_work_items(root.work_thread_id, limit=256)
            if value.parent_work_item_id == root.work_item_id
            and value.plan_version == root.plan_version
            and acceptance in value.acceptance_criteria
        ),
        None,
    )
    if item is None:
        item = resident.work_ledger.create_child_item(
            root_work_item_id=root.work_item_id,
            objective="Preserve bounded local Office source/mutation/verification evidence",
            acceptance_criteria=[acceptance],
            title="Local document work" if meta.get("kind") == "docx" else "Spreadsheet cleanup",
        )
    now = utc_now()
    item.status = "completed" if status == "complete" else "blocked" if status == "blocked" else "running"
    item.result = json.dumps(_evidence(meta, status=status, blocker=blocker), ensure_ascii=False, separators=(",", ":"))
    item.blocker = blocker
    if status == "complete":
        item.completed_at = now
    item.updated_at = now
    resident.work_ledger._save_item(item)


def _blocked(resident, event, state, meta: dict[str, Any], code: str, detail: str, response: str) -> ResidentRunResult:
    reason = f"{code}: {detail}"[:4000]
    meta["blocker"] = {"code": code, "detail": str(detail)[:2000]}
    state.data[_STATE_KEY] = meta
    state.stage = "failed"
    state.next_action = None
    state.blocked_by = code
    resident.store.save_working_state(state)
    _persist(resident, event, meta, status="blocked", blocker=reason)
    return ResidentRunResult(
        event=event,
        execution_path=ExecutionPath.INVESTIGATION,
        success=False,
        response=response[:8000],
        model_invocations=0,
        reason=reason,
    )


def _begin(resident, event, state, kind: str):
    root = resident.work_ledger.work_item_for_event(event.event_id)
    if root is None or root.parent_work_item_id is not None:
        return _blocked(resident, event, state, {"kind": kind}, "missing_root_work", "local Office work requires durable Root Work", "当前任务没有绑定到可持续的 Root Work，未修改任何文件。")
    source, destination, error = _authorized_paths(resident, event, root.work_thread_id)
    meta: dict[str, Any] = {
        "kind": kind,
        "work_thread_id": root.work_thread_id,
        "root_work_item_id": root.work_item_id,
        "plan_version": root.plan_version,
        "source_workspace": str(source) if source else None,
        "destination_workspace": str(destination) if destination else None,
        "model_invocations": 0,
    }
    if error:
        return _blocked(resident, event, state, meta, "workspace_authority_missing", error, "我还没有唯一、明确的来源目录和项目目录权限，所以不会扩大搜索或修改文件。")
    if kind == "docx":
        replacement_date, evidence, date_error = _agreed_date(resident, event, root.work_thread_id)
        if date_error or not replacement_date:
            return _blocked(resident, event, state, meta, "agreed_date_ambiguous", date_error or "agreed payment date is unavailable", "当前 Work 里没有唯一明确的“说好的付款日期”。请明确一个具体日期；在此之前不会修改任何合同。")
        meta["replacement_date"] = replacement_date
        meta["date_evidence"] = evidence
    state.data[_STATE_KEY] = meta
    state.stage = "local_office_discover"
    state.next_action = "bounded source enumeration and exact local-file identity comparison"
    state.blocked_by = None
    resident.store.save_working_state(state)
    _persist(resident, event, meta, status="discovering")
    return None


def _discover(resident, event, state):
    meta = dict(state.data.get(_STATE_KEY) or {})
    kind = str(meta.get("kind") or "")
    source = Path(str(meta.get("source_workspace") or ""))
    destination_workspace = Path(str(meta.get("destination_workspace") or ""))
    listing = resident.body.act("list_directory", event_id=event.event_id, path=str(source), limit=MAX_ENTRIES + 1)
    if not listing.success:
        return _blocked(resident, event, state, meta, "source_enumeration_failed", listing.error or "list_directory failed", "来源目录无法完成 bounded enumeration，因此没有修改任何文件。")
    entries = [dict(value) for value in (listing.data.get("entries") or ()) if isinstance(value, Mapping)]
    if len(entries) > MAX_ENTRIES:
        return _blocked(resident, event, state, meta, "bounded_source_overflow", "source workspace exceeds top-level entry limit", "来源目录条目超过第一版安全边界；ZN 不会扩大扫描范围。")
    suffix = ".docx" if kind == "docx" else ".xlsx"
    paths: list[Path] = []
    for item in entries:
        if str(item.get("type") or "").lower() != "file":
            continue
        try:
            path = Path(str(item.get("path") or "")).resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if path.parent == source and path.suffix.casefold() == suffix:
            paths.append(path)
    if len(paths) > MAX_CANDIDATES:
        return _blocked(resident, event, state, meta, "bounded_candidate_overflow", "too many Office candidates for safe comparison", "候选文件过多，超过第一版 bounded comparison 上限；不会猜测目标。")
    if not paths:
        return _blocked(resident, event, state, meta, "no_candidate", f"no top-level {suffix} candidate exists", f"授权来源目录里没有可用的 {suffix} 候选文件。")

    rows: list[dict[str, Any]] = []
    inspect_kind = "inspect_docx" if kind == "docx" else "inspect_xlsx"
    yesterday = datetime.now().astimezone().date() - timedelta(days=1)
    for path in paths:
        observed = resident.body.act(inspect_kind, event_id=event.event_id, path=str(path))
        if not observed.success:
            return _blocked(resident, event, state, meta, "source_inspection_failed", observed.error or f"{inspect_kind} failed", "候选文件无法完成真实结构检查，因此没有修改任何文件。")
        inspection = dict(observed.data)
        identity = inspection.get("identity") if isinstance(inspection.get("identity"), Mapping) else {}
        day = _local_day(identity)
        if day is None:
            return _blocked(resident, event, state, meta, "source_date_unobservable", "candidate local modified date is unavailable", "有候选文件无法可靠判断是否属于“昨天”，因此不会用最新文件之类的猜法代替。")
        rows.append({
            "path": str(path),
            "name": path.name,
            "observed_date": day.isoformat(),
            "matches_yesterday": day == yesterday,
            "identity": dict(identity),
            "inspection": inspection,
        })
    yesterday_rows = [row for row in rows if row["matches_yesterday"]]
    meta["candidate_summary"] = {
        "expected_local_date": yesterday.isoformat(),
        "candidate_count": len(rows),
        "yesterday_count": len(yesterday_rows),
        "paths": [row["path"] for row in rows],
    }
    if not yesterday_rows:
        return _blocked(resident, event, state, meta, "no_yesterday_candidate", "no candidate has a freshly observed local modified date of yesterday", "没有候选文件被 fresh filesystem evidence 证明为昨天修改；不会改成选择目录里最新的文件。")

    if kind == "docx":
        unsupported = [row for row in yesterday_rows if row["inspection"].get("ready") is not True]
        if unsupported:
            info = unsupported[0]["inspection"]
            return _blocked(resident, event, state, meta, str(info.get("blocker") or "unsupported_document_structure"), str(info.get("detail") or "unsafe DOCX"), "昨天的 DOCX 候选里存在当前无法安全验证/保存的结构，已 fail closed，未生成修改文件。")
        target_rows = [row for row in yesterday_rows if int(row["inspection"].get("payment_date_occurrence_count") or 0) > 0]
        if len(target_rows) != 1:
            code = "ambiguous_source" if len(target_rows) > 1 else "payment_date_not_found"
            return _blocked(resident, event, state, meta, code, f"expected one plausible DOCX target, observed {len(target_rows)}", "昨天的合同候选不能唯一确定。请指定具体文件；在此之前不会修改任何 DOCX。")
        selected = target_rows[0]
        count = int(selected["inspection"].get("payment_date_occurrence_count") or 0)
        if count != 1:
            return _blocked(resident, event, state, meta, "ambiguous_payment_date_target", f"payment date occurs {count} times", "目标合同里的付款日期不是唯一位置，无法安全判断该改哪一处；未执行全局替换。")
        destination = destination_workspace / f"{Path(selected['name']).stem}-updated.docx"
    else:
        if len(yesterday_rows) != 1:
            return _blocked(resident, event, state, meta, "ambiguous_source", f"expected one yesterday XLSX, observed {len(yesterday_rows)}", "昨天的 XLSX 候选不能唯一确定。请指定具体文件；不会让模型代替你猜。")
        selected = yesterday_rows[0]
        if selected["inspection"].get("ready") is not True:
            blocker = str(selected["inspection"].get("blocker") or "unsupported_workbook_structure")
            detail = str(selected["inspection"].get("detail") or "XLSX is outside the safe first-version scope")
            response = "金额列无法唯一确定，请明确要处理哪一列；原文件没有改动。" if blocker == "ambiguous_amount_column" else "这个 XLSX 含有当前无法证明安全的结构，已 fail closed；原文件没有改动。"
            return _blocked(resident, event, state, meta, blocker, detail, response)
        destination = destination_workspace / f"{Path(selected['name']).stem}-cleaned.xlsx"

    if destination.exists():
        return _blocked(resident, event, state, meta, "output_collision", f"destination already exists: {destination}", "目标输出名已经存在。为避免静默覆盖，当前任务已停止，原文件未改动。")
    meta["selected"] = selected
    meta["destination_path"] = str(destination)
    state.data[_STATE_KEY] = meta
    state.stage = "local_office_mutate"
    state.next_action = "revalidate exact source identity and create a verified Office copy"
    resident.store.save_working_state(state)
    _persist(resident, event, meta, status="bound")
    return None


def _mutate(resident, event, state):
    meta = dict(state.data.get(_STATE_KEY) or {})
    selected = meta.get("selected") if isinstance(meta.get("selected"), Mapping) else None
    if not selected:
        return _blocked(resident, event, state, meta, "source_binding_lost", "selected source evidence is missing", "已绑定的源文件证据丢失，未执行写入。")
    kind = str(meta.get("kind") or "")
    args = {
        "source_path": str(selected.get("path") or ""),
        "destination_path": str(meta.get("destination_path") or ""),
        "precondition_identity": dict(selected.get("identity") or {}),
    }
    action_kind = "write_docx_copy" if kind == "docx" else "write_xlsx_copy"
    if kind == "docx":
        args["replacement_date"] = str(meta.get("replacement_date") or "")
    else:
        args["number_format"] = AMOUNT_NUMBER_FORMAT
    result = resident.body.act(action_kind, event_id=event.event_id, **args)
    if not result.success:
        error = str(result.error or result.output or "Office Body mutation failed")
        if "stale_source_evidence" in error:
            code, response = "stale_source_evidence", "源文件在选择后发生了变化；旧证据已被拒绝，没有基于 stale identity 继续生成结果。"
        elif "output_collision" in error or "destination already exists" in error:
            code, response = "output_collision", "输出路径发生冲突；为避免覆盖现有文件，任务已停止。"
        else:
            code, response = "office_mutation_failed", "Office 文件转换没有通过 deterministic Body 执行/验证，因此任务不会被标记完成。"
        return _blocked(resident, event, state, meta, code, error, response)
    meta["operation_result"] = dict(result.data)
    state.data[_STATE_KEY] = meta
    state.stage = "local_office_verify"
    state.next_action = "freshly reopen source and destination and verify Root acceptance invariants"
    resident.store.save_working_state(state)
    _persist(resident, event, meta, status="mutated")
    return None


def _verify(resident, event, state):
    meta = dict(state.data.get(_STATE_KEY) or {})
    selected = meta.get("selected") if isinstance(meta.get("selected"), Mapping) else {}
    operation = meta.get("operation_result") if isinstance(meta.get("operation_result"), Mapping) else {}
    kind = str(meta.get("kind") or "")
    inspect_kind = "inspect_docx" if kind == "docx" else "inspect_xlsx"
    source = resident.body.act(inspect_kind, event_id=event.event_id, path=str(selected.get("path") or ""))
    destination = resident.body.act(inspect_kind, event_id=event.event_id, path=str(meta.get("destination_path") or ""))
    if not source.success or not destination.success:
        return _blocked(resident, event, state, meta, "fresh_reopen_failed", source.error or destination.error or "fresh Office inspection failed", "输出文件没有通过独立 fresh reopen，因此任务没有被标记完成。")
    source_identity = source.data.get("identity") if isinstance(source.data.get("identity"), Mapping) else {}
    destination_identity = destination.data.get("identity") if isinstance(destination.data.get("identity"), Mapping) else {}
    source_exact = compare_file_identities(dict(selected.get("identity") or {}), dict(source_identity)).get("exact") is True
    destination_exact = compare_file_identities(dict(operation.get("destination_identity") or {}), dict(destination_identity)).get("exact") is True
    verified = bool(source_exact and destination_exact and source.data.get("ready") is True and destination.data.get("ready") is True)
    verification: dict[str, Any] = {
        "source_identity_exact_after": source_exact,
        "destination_identity_exact_on_fresh_reopen": destination_exact,
        "destination_ready": destination.data.get("ready") is True,
    }
    if kind == "docx":
        occurrences = destination.data.get("payment_date_occurrences") or []
        structure_ok = destination.data.get("structure_fingerprint") == operation.get("expected_structure_fingerprint")
        target_ok = len(occurrences) == 1 and str(occurrences[0].get("date") or "") == str(meta.get("replacement_date") or "")
        verified = bool(verified and structure_ok and target_ok and operation.get("source_unchanged") is True and operation.get("format_preserved") is True)
        verification.update({
            "source_unchanged": source_exact,
            "destination_reopened": True,
            "payment_date_exact": target_ok,
            "surrounding_structure_preserved": structure_ok,
            "run_format_preserved": operation.get("format_preserved") is True,
        })
    else:
        rows_ok = destination.data.get("data_row_count") == operation.get("retained_data_rows")
        dupes_ok = destination.data.get("duplicate_row_count") == 0
        format_ok = destination.data.get("amount_number_formats") == [AMOUNT_NUMBER_FORMAT]
        fingerprint_ok = destination.data.get("data_fingerprint") == operation.get("expected_data_fingerprint")
        verified = bool(
            verified and rows_ok and dupes_ok and format_ok and fingerprint_ok
            and operation.get("source_unchanged") is True
            and operation.get("amount_values_semantically_unchanged") is True
            and operation.get("amount_cells_numeric") is True
            and operation.get("non_target_values_unchanged") is True
        )
        verification.update({
            "source_sha256_unchanged": source_exact,
            "destination_reopened": True,
            "row_count_expected": rows_ok,
            "zero_exact_duplicate_rows": dupes_ok,
            "amount_number_format_uniform": format_ok,
            "business_value_fingerprint_exact": fingerprint_ok,
            "amount_values_semantically_unchanged": operation.get("amount_values_semantically_unchanged") is True,
            "amount_cells_numeric": operation.get("amount_cells_numeric") is True,
            "non_target_values_unchanged": operation.get("non_target_values_unchanged") is True,
        })
    meta["verification"] = verification
    state.data[_STATE_KEY] = meta
    if not verified:
        return _blocked(resident, event, state, meta, "completion_verification_failed", json.dumps(verification, ensure_ascii=False), "新文件已尝试生成，但 fresh reality verification 没有全部通过，因此任务没有被标记完成。")

    state.stage = "complete"
    state.next_action = None
    state.blocked_by = None
    resident.store.save_working_state(state)
    _persist(resident, event, meta, status="complete")
    if kind == "docx":
        response = f"合同已按当前 Work 中唯一确认的付款日期更新并保存为新 DOCX：{meta['destination_path']}。源合同保持不变，目标文件已重新打开并验证。"
        reason = "E2E-09 local DOCX representative path completed only after exact source binding, run-aware copy mutation, source-preservation proof, and fresh reopen verification"
    else:
        removed = int(operation.get("removed_duplicate_rows") or 0)
        response = f"表格已生成处理后的新 XLSX：{meta['destination_path']}。已移除 {removed} 行 exact duplicate，并把金额列统一为 {AMOUNT_NUMBER_FORMAT}；原文件 SHA-256 保持不变，新文件已重新打开验证。"
        reason = "E2E-10 spreadsheet representative path completed with zero model calls after exact duplicate cleanup, numeric format normalization, source hash preservation, and fresh reopen verification"
    return ResidentRunResult(
        event=event,
        execution_path=ExecutionPath.INVESTIGATION,
        success=True,
        response=response[:8000],
        model_invocations=0,
        reason=reason,
    )


def install_local_office_behavior(resident) -> None:
    """Attach the narrow Office behavior to the one existing Resident and Body."""
    if getattr(resident, _INSTALL_MARKER, False):
        return
    body = resident.body
    original_dispatch = body._dispatch

    def body_dispatch(action, started):
        kind = str(action.kind or "").lower()
        if kind == "inspect_docx":
            data = inspect_docx(action.args.get("path") or action.args.get("source_path"))
            return body._ok(action, started, output=str(action.args.get("path") or ""), data=data)
        if kind == "write_docx_copy":
            data = write_docx_copy(
                action.args.get("source_path"),
                action.args.get("destination_path"),
                replacement_date=str(action.args.get("replacement_date") or ""),
                precondition_identity=dict(action.args.get("precondition_identity") or {}),
            )
            return body._ok(action, started, output=str(action.args.get("destination_path") or ""), data=data)
        if kind == "inspect_xlsx":
            data = inspect_xlsx(action.args.get("path") or action.args.get("source_path"))
            return body._ok(action, started, output=str(action.args.get("path") or ""), data=data)
        if kind == "write_xlsx_copy":
            data = write_xlsx_copy(
                action.args.get("source_path"),
                action.args.get("destination_path"),
                precondition_identity=dict(action.args.get("precondition_identity") or {}),
                number_format=str(action.args.get("number_format") or AMOUNT_NUMBER_FORMAT),
            )
            return body._ok(action, started, output=str(action.args.get("destination_path") or ""), data=data)
        return original_dispatch(action, started)

    original_advance = resident._advance_event_step

    def advance_event_step(event, state, *, readiness, learning_evidence, thought=None):
        stage = str(state.stage or "")
        request = _request(event)
        if stage == "orient" and request is not None:
            return _begin(resident, event, state, request)
        if stage == "local_office_discover":
            return _discover(resident, event, state)
        if stage == "local_office_mutate":
            return _mutate(resident, event, state)
        if stage == "local_office_verify":
            return _verify(resident, event, state)
        return original_advance(
            event,
            state,
            readiness=readiness,
            learning_evidence=learning_evidence,
            thought=thought,
        )

    body._dispatch = body_dispatch
    resident._advance_event_step = advance_event_step
    setattr(resident, _INSTALL_MARKER, True)
