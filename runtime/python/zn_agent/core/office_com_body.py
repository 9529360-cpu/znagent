from __future__ import annotations

"""Microsoft Office native-object movements on ZN's existing durable Body."""

import copy
import uuid
from typing import Any

from .body import BodyAction, BodyActionResult
from .gui_automation_body import GuiAutomationBody
from .models import utc_now
from .office_native_action import (
    NativeOfficeAction,
    OfficeSessionObservation,
    OfficeValueObservation,
    normalize_cell_address,
    normalize_office_kind,
    normalize_worksheet_name,
    scalar_digest,
    text_sha256,
)


class OfficeComAwareBody(GuiAutomationBody):
    """Add exact-foreground Office COM without adding another execution plane."""

    _SESSION_READ = "office_session_read"
    _EXCEL_CELL_READ = "office_excel_cell_read"
    _EXCEL_CELL_SET = "office_excel_cell_set"
    _WORD_SELECTION_READ = "office_word_selection_read"
    _WORD_SELECTION_SET = "office_word_selection_set_text"
    _MUTATION_KINDS = frozenset({_EXCEL_CELL_SET, _WORD_SELECTION_SET})

    _DISPATCH_MARKER = "__zn_office_dispatch_admitted"
    _WINDOW_ARG = "__zn_office_window_handle"
    _PROCESS_ARG = "__zn_office_process_id"
    _PROCESS_NAME_ARG = "__zn_office_process_name"
    _OFFICE_KIND_ARG = "__zn_office_kind"
    _PRIVATE_ARGS = frozenset(
        {
            _DISPATCH_MARKER,
            _WINDOW_ARG,
            _PROCESS_ARG,
            _PROCESS_NAME_ARG,
            _OFFICE_KIND_ARG,
        }
    )

    def __init__(
        self,
        *args,
        office_action: NativeOfficeAction | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._office_action = office_action or NativeOfficeAction()

    def act(self, kind: str, *, event_id: str | None = None, **args: Any) -> BodyActionResult:
        normalized = str(kind or "").strip().lower()
        if normalized == self._SESSION_READ:
            return self._act_session_read(event_id=event_id, args=dict(args))
        if normalized == self._EXCEL_CELL_READ:
            return self._act_excel_cell_read(event_id=event_id, args=dict(args))
        if normalized == self._WORD_SELECTION_READ:
            return self._act_word_selection_read(event_id=event_id, args=dict(args))
        if normalized in self._MUTATION_KINDS:
            return self._act_office_mutation(normalized, event_id=event_id, args=dict(args))
        return super().act(kind, event_id=event_id, **args)

    def observe_office_session(self, *, application_id: str) -> OfficeSessionObservation:
        _, process, window, office_kind = self._office_target(application_id)
        return self._office_action.session_read(
            office_kind=office_kind,
            process_id=process.process_id,
            process_name=process.process_name,
            window_handle=window.hwnd,
        )

    def observe_excel_cell(
        self,
        *,
        application_id: str,
        worksheet_name: str,
        cell_address: str,
    ) -> OfficeValueObservation:
        _, process, window, office_kind = self._office_target(application_id)
        if office_kind != "excel":
            raise RuntimeError("Excel cell observation requires foreground Microsoft Excel")
        return self._office_action.excel_cell_read(
            office_kind=office_kind,
            process_id=process.process_id,
            process_name=process.process_name,
            window_handle=window.hwnd,
            worksheet_name=worksheet_name,
            cell_address=cell_address,
        )

    def observe_word_selection(self, *, application_id: str) -> OfficeValueObservation:
        _, process, window, office_kind = self._office_target(application_id)
        if office_kind != "word":
            raise RuntimeError("Word selection observation requires foreground Microsoft Word")
        return self._office_action.word_selection_read(
            office_kind=office_kind,
            process_id=process.process_id,
            process_name=process.process_name,
            window_handle=window.hwnd,
        )

    def _office_target(self, app_id: str):
        application, process, window = self._foreground_target(str(app_id or "").strip())
        office_kind = normalize_office_kind(process.process_name)
        return application, process, window, office_kind

    def _act_session_read(self, *, event_id: str | None, args: dict[str, Any]) -> BodyActionResult:
        app_id = str(args.get("application_id") or "").strip()
        if set(args) != {"application_id"}:
            return self._office_preflight(
                self._SESSION_READ,
                event_id,
                app_id,
                False,
                data={},
                error="Office session read accepts only application_id",
            )
        try:
            observation = self.observe_office_session(application_id=app_id)
        except Exception as exc:
            return self._office_preflight(
                self._SESSION_READ,
                event_id,
                app_id,
                False,
                data={},
                error=f"Office session read failed: {type(exc).__name__}: {exc}",
            )
        return self._read_observation_result(
            self._SESSION_READ,
            event_id,
            app_id,
            observation.audit(),
        )

    def _act_excel_cell_read(
        self,
        *,
        event_id: str | None,
        args: dict[str, Any],
    ) -> BodyActionResult:
        allowed = {"application_id", "worksheet_name", "cell_address"}
        app_id = str(args.get("application_id") or "").strip()
        rejected = sorted(set(args) - allowed)
        if rejected:
            return self._office_preflight(
                self._EXCEL_CELL_READ,
                event_id,
                app_id,
                False,
                data={},
                error="Excel cell read rejected arguments: " + ", ".join(rejected),
            )
        try:
            observation = self.observe_excel_cell(
                application_id=app_id,
                worksheet_name=normalize_worksheet_name(args.get("worksheet_name")),
                cell_address=normalize_cell_address(args.get("cell_address")),
            )
        except Exception as exc:
            return self._office_preflight(
                self._EXCEL_CELL_READ,
                event_id,
                app_id,
                False,
                data={},
                error=f"Excel cell read failed: {type(exc).__name__}: {exc}",
            )
        return self._read_observation_result(
            self._EXCEL_CELL_READ,
            event_id,
            app_id,
            observation.audit(),
        )

    def _act_word_selection_read(
        self,
        *,
        event_id: str | None,
        args: dict[str, Any],
    ) -> BodyActionResult:
        app_id = str(args.get("application_id") or "").strip()
        if set(args) != {"application_id"}:
            return self._office_preflight(
                self._WORD_SELECTION_READ,
                event_id,
                app_id,
                False,
                data={},
                error="Word selection read accepts only application_id",
            )
        try:
            observation = self.observe_word_selection(application_id=app_id)
        except Exception as exc:
            return self._office_preflight(
                self._WORD_SELECTION_READ,
                event_id,
                app_id,
                False,
                data={},
                error=f"Word selection read failed: {type(exc).__name__}: {exc}",
            )
        return self._read_observation_result(
            self._WORD_SELECTION_READ,
            event_id,
            app_id,
            observation.audit(),
        )

    def _act_office_mutation(
        self,
        kind: str,
        *,
        event_id: str | None,
        args: dict[str, Any],
    ) -> BodyActionResult:
        if kind == self._EXCEL_CELL_SET:
            allowed = {"application_id", "worksheet_name", "cell_address", "value"}
        else:
            allowed = {"application_id", "text"}
        app_id = str(args.get("application_id") or "").strip()
        rejected = sorted(set(args) - allowed)
        if rejected:
            return self._office_preflight(
                kind,
                event_id,
                app_id,
                False,
                data={"dispatch_sent": False, "rejected_arguments": rejected},
                error=(
                    "Office native mutation accepts semantic targets only; native HWND/PID "
                    "are not caller authority: " + ", ".join(rejected)
                ),
            )
        if not app_id:
            return self._office_preflight(
                kind,
                event_id,
                app_id,
                False,
                data={"dispatch_sent": False},
                error="Office native mutation requires a resolved application_id",
            )
        try:
            application, process, window, office_kind = self._office_target(app_id)
            public: dict[str, Any] = {"application_id": application.app_id}
            if kind == self._EXCEL_CELL_SET:
                if office_kind != "excel":
                    raise RuntimeError("Excel cell mutation requires foreground Microsoft Excel")
                if "value" not in args:
                    raise ValueError("Excel cell mutation requires value")
                public.update(
                    worksheet_name=normalize_worksheet_name(args.get("worksheet_name")),
                    cell_address=normalize_cell_address(args.get("cell_address")),
                    value=args.get("value"),
                )
                scalar_digest(args.get("value"))
            else:
                if office_kind != "word":
                    raise RuntimeError("Word selection mutation requires foreground Microsoft Word")
                text = args.get("text")
                if not isinstance(text, str) or len(text) > 4096:
                    raise ValueError("Word selection text must be a string of at most 4096 characters")
                public["text"] = text
        except Exception as exc:
            return self._office_preflight(
                kind,
                event_id,
                app_id,
                False,
                data={"dispatch_sent": False},
                error=f"Office native preflight failed: {type(exc).__name__}: {exc}",
            )

        return super().act(
            kind,
            event_id=event_id,
            **public,
            **{
                self._DISPATCH_MARKER: True,
                self._WINDOW_ARG: int(window.hwnd),
                self._PROCESS_ARG: int(process.process_id),
                self._PROCESS_NAME_ARG: str(process.process_name),
                self._OFFICE_KIND_ARG: office_kind,
            },
        )

    @classmethod
    def _requires_guard(cls, kind: str, args: dict[str, Any]) -> bool:
        if kind in cls._MUTATION_KINDS:
            return args.get(cls._DISPATCH_MARKER) is True
        return super()._requires_guard(kind, args)

    @classmethod
    def _signature_hash(cls, kind: str, args: dict[str, Any]) -> str:
        if kind in cls._MUTATION_KINDS:
            stable = dict(args)
            for key in cls._PRIVATE_ARGS:
                stable.pop(key, None)
            return super()._signature_hash(kind, stable)
        return super()._signature_hash(kind, args)

    @staticmethod
    def _redact_document_names(value: Any) -> Any:
        if isinstance(value, dict):
            output = {}
            for key, item in value.items():
                if key == "document_name" and item not in (None, ""):
                    text = str(item)
                    output["document_name_redacted"] = True
                    output["document_name_chars"] = len(text)
                    output["document_name_sha256"] = text_sha256(text)
                else:
                    output[key] = OfficeComAwareBody._redact_document_names(item)
            return output
        if isinstance(value, list):
            return [OfficeComAwareBody._redact_document_names(item) for item in value]
        return value

    def _record(self, action: BodyAction, result: BodyActionResult) -> None:
        safe_action = action
        if action.kind in self._MUTATION_KINDS:
            safe_args = dict(action.args)
            for key in self._PRIVATE_ARGS:
                safe_args.pop(key, None)
            if action.kind == self._EXCEL_CELL_SET and "value" in safe_args:
                raw = safe_args.pop("value")
                safe_args.update(scalar_digest(raw))
                safe_args["value_redacted"] = True
            if action.kind == self._WORD_SELECTION_SET and "text" in safe_args:
                raw_text = str(safe_args.pop("text"))
                safe_args["text_redacted"] = True
                safe_args["text_chars"] = len(raw_text)
                safe_args["text_sha256"] = text_sha256(raw_text)
            safe_action = BodyAction(
                action_id=action.action_id,
                kind=action.kind,
                args=safe_args,
                event_id=action.event_id,
                created_at=action.created_at,
            )
        safe_result = BodyActionResult(
            action_id=result.action_id,
            kind=result.kind,
            success=result.success,
            output=result.output,
            data=self._redact_document_names(copy.deepcopy(dict(result.data or {}))),
            error=result.error,
            event_id=result.event_id,
            started_at=result.started_at,
            completed_at=result.completed_at,
        )
        super()._record(safe_action, safe_result)

    def _dispatch(self, action: BodyAction, started: str) -> BodyActionResult:
        if action.kind in self._MUTATION_KINDS:
            return self._dispatch_office_mutation(action, started)
        return super()._dispatch(action, started)

    def _dispatch_office_mutation(
        self,
        action: BodyAction,
        started: str,
    ) -> BodyActionResult:
        if action.args.get(self._DISPATCH_MARKER) is not True:
            raise PermissionError("Office native dispatch did not pass machine-fact preflight")
        app_id = str(action.args.get("application_id") or "").strip()
        expected_hwnd = int(action.args.get(self._WINDOW_ARG) or 0)
        expected_pid = int(action.args.get(self._PROCESS_ARG) or 0)
        expected_process = str(action.args.get(self._PROCESS_NAME_ARG) or "").strip()
        expected_kind = str(action.args.get(self._OFFICE_KIND_ARG) or "").strip()
        base_data = {
            "application_id": app_id,
            "dispatch_sent": False,
            "postcondition_verified": False,
        }
        try:
            _, process, window, office_kind = self._office_target(app_id)
        except Exception as exc:
            return self._result(
                action,
                started,
                False,
                base_data,
                f"Office target changed before dispatch: {type(exc).__name__}: {exc}",
            )
        if (
            int(window.hwnd) != expected_hwnd
            or int(process.process_id) != expected_pid
            or str(process.process_name).strip().lower() != expected_process.lower()
            or office_kind != expected_kind
        ):
            return self._result(
                action,
                started,
                False,
                {**base_data, "disposition": "foreground_identity_changed"},
                "Office foreground identity changed before native dispatch",
            )

        common = {
            "office_kind": office_kind,
            "process_id": expected_pid,
            "process_name": expected_process,
            "window_handle": expected_hwnd,
        }
        if action.kind == self._EXCEL_CELL_SET:
            mutation = self._office_action.excel_cell_set(
                **common,
                worksheet_name=str(action.args.get("worksheet_name") or ""),
                cell_address=str(action.args.get("cell_address") or ""),
                value=action.args.get("value"),
            )
        else:
            mutation = self._office_action.word_selection_set_text(
                **common,
                text=str(action.args.get("text") or ""),
            )
        data = {
            **base_data,
            "office_kind": office_kind,
            "dispatch_sent": bool(mutation.mutation_dispatched),
            "postcondition_verified": bool(mutation.postcondition_verified),
            "side_effect_uncertain": bool(
                mutation.mutation_dispatched and not mutation.postcondition_verified
            ),
            "before": mutation.before.audit() if mutation.before else None,
            "after": mutation.after.audit() if mutation.after else None,
        }
        return self._result(
            action,
            started,
            bool(mutation.success),
            data,
            mutation.error,
            output="Microsoft Office native target state verified" if mutation.success else "",
        )

    def _read_observation_result(
        self,
        kind: str,
        event_id: str | None,
        app_id: str,
        data: dict[str, Any],
    ) -> BodyActionResult:
        action = BodyAction(
            action_id=f"body-{uuid.uuid4().hex[:12]}",
            kind=kind,
            args={"application_id": app_id},
            event_id=event_id,
        )
        started = utc_now()
        result = BodyActionResult(
            action_id=action.action_id,
            kind=kind,
            success=True,
            data={"application_id": app_id, **data},
            event_id=event_id,
            started_at=started,
            completed_at=utc_now(),
        )
        self._record(action, result)
        return result

    def _office_preflight(
        self,
        kind: str,
        event_id: str | None,
        app_id: str,
        success: bool,
        *,
        data: dict[str, Any],
        error: str | None = None,
    ) -> BodyActionResult:
        action = BodyAction(
            action_id=f"body-{uuid.uuid4().hex[:12]}",
            kind=kind,
            args={"application_id": app_id} if app_id else {},
            event_id=event_id,
        )
        started = utc_now()
        result = BodyActionResult(
            action_id=action.action_id,
            kind=kind,
            success=success,
            data=data,
            error=error,
            event_id=event_id,
            started_at=started,
            completed_at=utc_now(),
        )
        self._record(action, result)
        return result
