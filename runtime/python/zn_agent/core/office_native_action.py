from __future__ import annotations

"""Exact-HWND Microsoft Office native-object actions for ZN.

This module is a mechanism, not an agent/runtime. Each request starts from one
already-admitted foreground Office HWND/PID, reacquires the Office Native Object
Model through OBJID_NATIVEOM, performs one bounded read/mutation, and discards
the COM object afterward.
"""

import hashlib
import json
import math
import os
import queue
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .models import utc_now

_MAX_TEXT_CHARS = 4096
_MAX_DOCUMENT_NAME_CHARS = 260
_CELL_RE = re.compile(r"^\$?([A-Za-z]{1,3})\$?([1-9][0-9]{0,6})$")
_OFFICE_KINDS = frozenset({"word", "excel", "powerpoint"})
_NATIVE_CLASSES = {
    "word": ("_WwG",),
    "excel": ("EXCEL7",),
    # paneClassDC is documented by Microsoft; current Office 16 on the ZN
    # Windows acceptance host exposes NativeOM from mdiClass instead.
    "powerpoint": ("paneClassDC", "mdiClass"),
}


def text_sha256(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def normalize_office_kind(value: object) -> str:
    key = str(value or "").strip().lower().replace("-", "").replace("_", "")
    aliases = {
        "word": "word",
        "winword": "word",
        "winword.exe": "word",
        "excel": "excel",
        "excel.exe": "excel",
        "powerpoint": "powerpoint",
        "powerpnt": "powerpoint",
        "powerpnt.exe": "powerpoint",
    }
    normalized = aliases.get(key)
    if normalized not in _OFFICE_KINDS:
        raise ValueError(f"unsupported Microsoft Office application: {value}")
    return normalized


def _column_number(label: str) -> int:
    value = 0
    for char in label.upper():
        value = value * 26 + (ord(char) - 64)
    return value


def normalize_cell_address(value: object) -> str:
    address = str(value or "").strip()
    match = _CELL_RE.fullmatch(address)
    if match is None:
        raise ValueError("Excel cell address must be one A1-style single cell")
    column, row_text = match.groups()
    row = int(row_text)
    column_number = _column_number(column)
    if not 1 <= column_number <= 16384 or not 1 <= row <= 1_048_576:
        raise ValueError("Excel cell address is outside the worksheet bounds")
    return f"{column.upper()}{row}"


def normalize_worksheet_name(value: object) -> str:
    name = str(value or "").strip()
    if not name or len(name) > 31:
        raise ValueError("Excel worksheet_name must contain 1..31 characters")
    return name


def _canonical_scalar(value: object) -> tuple[str, str]:
    if value is None:
        return "blank", "null"
    if isinstance(value, bool):
        return "boolean", "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Office scalar number must be finite")
        if number.is_integer():
            return "number", str(int(number))
        return "number", format(number, ".15g")
    if isinstance(value, str):
        if len(value) > _MAX_TEXT_CHARS:
            raise ValueError(f"Office text scalar exceeds {_MAX_TEXT_CHARS} characters")
        return "text", value
    raise ValueError("Office scalar must be text, finite number, boolean, or null")


def scalar_digest(value: object) -> dict[str, object]:
    kind, canonical = _canonical_scalar(value)
    return {
        "value_kind": kind,
        "value_chars": len(canonical),
        "value_sha256": text_sha256(canonical),
    }


@dataclass(frozen=True, slots=True)
class OfficeSessionObservation:
    office_kind: str
    process_id: int
    process_name: str
    window_handle: int
    native_window_class: str
    version: str
    document_kind: str
    document_name: str
    captured_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "office_kind", normalize_office_kind(self.office_kind))
        object.__setattr__(self, "process_name", str(self.process_name or "").strip().lower())
        object.__setattr__(
            self,
            "document_name",
            str(self.document_name or "").strip()[:_MAX_DOCUMENT_NAME_CHARS],
        )

    def audit(self) -> dict[str, object]:
        return {
            "office_kind": self.office_kind,
            "process_id": self.process_id,
            "process_name": self.process_name,
            "window_handle": self.window_handle,
            "native_window_class": self.native_window_class,
            "version": self.version,
            "document_kind": self.document_kind,
            "document_name": self.document_name,
            "captured_at": self.captured_at,
        }


@dataclass(frozen=True, slots=True)
class OfficeValueObservation:
    session: OfficeSessionObservation
    target: Mapping[str, Any]
    state: Mapping[str, Any]
    captured_at: str = field(default_factory=utc_now)

    def audit(self) -> dict[str, object]:
        return {
            "session": self.session.audit(),
            "target": dict(self.target),
            "state": dict(self.state),
            "captured_at": self.captured_at,
        }


@dataclass(frozen=True, slots=True)
class OfficeMutationResult:
    success: bool
    mutation_dispatched: bool
    postcondition_verified: bool
    before: OfficeValueObservation | None = None
    after: OfficeValueObservation | None = None
    error: str | None = None

    def audit(self) -> dict[str, object]:
        return {
            "success": self.success,
            "mutation_dispatched": self.mutation_dispatched,
            "postcondition_verified": self.postcondition_verified,
            "before": self.before.audit() if self.before else None,
            "after": self.after.audit() if self.after else None,
            "error": self.error,
        }


OfficeSessionReadFn = Callable[..., OfficeSessionObservation]
OfficeValueReadFn = Callable[..., OfficeValueObservation]
OfficeMutateFn = Callable[..., OfficeMutationResult]


@dataclass(slots=True)
class _OfficeRequest:
    operation: str
    office_kind: str
    process_id: int
    process_name: str
    window_handle: int
    worksheet_name: str = ""
    cell_address: str = ""
    value: object = None
    text: str = ""
    done: threading.Event | None = None
    result: OfficeSessionObservation | OfficeValueObservation | OfficeMutationResult | None = None
    error: str | None = None


class _WindowsOfficeNativeWorker:
    _START_TIMEOUT_SECONDS = 10.0
    _REQUEST_TIMEOUT_SECONDS = 8.0
    _OBJID_NATIVEOM = 0xFFFFFFF0

    def __init__(self) -> None:
        self._requests: queue.Queue[_OfficeRequest] = queue.Queue(maxsize=1)
        self._started = threading.Event()
        self._failure: str | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="zn-office-native-object",
            daemon=True,
        )
        self._thread.start()
        if not self._started.wait(self._START_TIMEOUT_SECONDS):
            self._failure = "Microsoft Office native-object worker did not initialize in time"
            raise RuntimeError(self._failure)
        if self._failure:
            raise RuntimeError(self._failure)

    def submit(self, request: _OfficeRequest):
        if self._failure:
            raise RuntimeError(self._failure)
        request.done = threading.Event()
        try:
            self._requests.put_nowait(request)
        except queue.Full as exc:
            raise RuntimeError("Microsoft Office native-object worker is busy") from exc
        if not request.done.wait(self._REQUEST_TIMEOUT_SECONDS):
            self._failure = "Microsoft Office native-object action exceeded its bounded timeout"
            raise RuntimeError(self._failure)
        if request.error:
            raise RuntimeError(request.error)
        return request.result

    def _run(self) -> None:
        try:
            import ctypes
            from ctypes import wintypes

            import comtypes
            from comtypes.automation import IDispatch
            from comtypes.client.dynamic import Dispatch

            comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            oleacc = ctypes.OleDLL("oleacc")
            enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            user32.EnumChildWindows.argtypes = [wintypes.HWND, enum_proc, wintypes.LPARAM]
            user32.EnumChildWindows.restype = wintypes.BOOL
            user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user32.GetClassNameW.restype = ctypes.c_int
            user32.GetForegroundWindow.argtypes = []
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetWindowThreadProcessId.argtypes = [
                wintypes.HWND,
                ctypes.POINTER(wintypes.DWORD),
            ]
            user32.GetWindowThreadProcessId.restype = wintypes.DWORD
            oleacc.AccessibleObjectFromWindow.argtypes = [
                wintypes.HWND,
                wintypes.DWORD,
                ctypes.POINTER(comtypes.GUID),
                ctypes.POINTER(ctypes.POINTER(IDispatch)),
            ]
            oleacc.AccessibleObjectFromWindow.restype = ctypes.HRESULT
            iid_dispatch = comtypes.GUID("{00020400-0000-0000-C000-000000000046}")
        except Exception as exc:
            self._failure = (
                "Microsoft Office native-object worker initialization failed: "
                f"{type(exc).__name__}: {exc}"
            )
            self._started.set()
            return

        self._started.set()
        while True:
            request = self._requests.get()
            try:
                request.result = self._execute(
                    request,
                    ctypes=ctypes,
                    wintypes=wintypes,
                    enum_proc=enum_proc,
                    user32=user32,
                    oleacc=oleacc,
                    dispatch_type=IDispatch,
                    dynamic_dispatch=Dispatch,
                    iid_dispatch=iid_dispatch,
                )
            except Exception as exc:
                request.error = (
                    "Microsoft Office native-object action failed: "
                    f"{type(exc).__name__}: {exc}"
                )
            finally:
                if request.done is not None:
                    request.done.set()

    @staticmethod
    def _window_process_id(hwnd: int, *, ctypes, wintypes, user32) -> int:
        pid = wintypes.DWORD(0)
        thread_id = int(user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid)))
        if thread_id <= 0 or int(pid.value) <= 0:
            raise RuntimeError("Windows did not expose the Office window process identity")
        return int(pid.value)

    @classmethod
    def _foreground_identity(cls, request: _OfficeRequest, *, ctypes, wintypes, user32) -> None:
        hwnd = int(user32.GetForegroundWindow() or 0)
        if hwnd != int(request.window_handle):
            raise RuntimeError("foreground HWND changed during Microsoft Office native action")
        pid = cls._window_process_id(hwnd, ctypes=ctypes, wintypes=wintypes, user32=user32)
        if pid != int(request.process_id):
            raise RuntimeError("foreground Office process changed during native action")
        try:
            import psutil

            process_name = str(psutil.Process(pid).name() or "").strip()
        except Exception as exc:
            raise RuntimeError("foreground Office process name is unavailable") from exc
        if process_name.lower() != str(request.process_name or "").strip().lower():
            raise RuntimeError("foreground Office process name changed during native action")

    @classmethod
    def _native_object(
        cls,
        request: _OfficeRequest,
        *,
        ctypes,
        wintypes,
        enum_proc,
        user32,
        oleacc,
        dispatch_type,
        dynamic_dispatch,
        iid_dispatch,
    ):
        cls._foreground_identity(request, ctypes=ctypes, wintypes=wintypes, user32=user32)
        wanted = set(_NATIVE_CLASSES[normalize_office_kind(request.office_kind)])
        candidates: list[tuple[int, str]] = []

        @enum_proc
        def collect(hwnd, _lparam):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            class_name = str(buf.value or "")
            if class_name in wanted:
                child_pid = cls._window_process_id(
                    int(hwnd),
                    ctypes=ctypes,
                    wintypes=wintypes,
                    user32=user32,
                )
                if child_pid == int(request.process_id):
                    candidates.append((int(hwnd), class_name))
            return True

        user32.EnumChildWindows(int(request.window_handle), collect, 0)
        valid: list[tuple[object, str]] = []
        for hwnd, class_name in candidates:
            ptr = ctypes.POINTER(dispatch_type)()
            try:
                hr = oleacc.AccessibleObjectFromWindow(
                    int(hwnd),
                    cls._OBJID_NATIVEOM,
                    ctypes.byref(iid_dispatch),
                    ctypes.byref(ptr),
                )
            except OSError:
                continue
            if hr < 0 or not ptr:
                continue
            try:
                obj = dynamic_dispatch(ptr)
                app = obj.Application
                version = str(app.Version or "").strip()
                if not version:
                    continue
                if request.office_kind == "word":
                    _ = obj.Document
                elif request.office_kind == "excel":
                    _ = app.ActiveWorkbook
                else:
                    _ = obj.Presentation
                valid.append((obj, class_name))
            except Exception:
                continue
        if len(valid) != 1:
            raise RuntimeError(
                "exact Office window did not expose one unique Native Object Model "
                f"target (matches={len(valid)})"
            )
        cls._foreground_identity(request, ctypes=ctypes, wintypes=wintypes, user32=user32)
        return valid[0]

    @staticmethod
    def _session(request: _OfficeRequest, obj, native_class: str) -> OfficeSessionObservation:
        app = obj.Application
        kind = normalize_office_kind(request.office_kind)
        if kind == "word":
            document = obj.Document
            document_kind = "document"
        elif kind == "excel":
            document = app.ActiveWorkbook
            if document is None:
                raise RuntimeError("Excel has no active workbook")
            document_kind = "workbook"
        else:
            document = obj.Presentation
            document_kind = "presentation"
        name = str(getattr(document, "Name", "") or "").strip()
        if not name:
            raise RuntimeError("active Office document identity is unavailable")
        return OfficeSessionObservation(
            office_kind=kind,
            process_id=request.process_id,
            process_name=request.process_name,
            window_handle=request.window_handle,
            native_window_class=native_class,
            version=str(app.Version or "").strip(),
            document_kind=document_kind,
            document_name=name,
        )

    @classmethod
    def _excel_cell_read(cls, request: _OfficeRequest, obj, native_class: str):
        session = cls._session(request, obj, native_class)
        workbook = obj.Application.ActiveWorkbook
        worksheet_name = normalize_worksheet_name(request.worksheet_name)
        address = normalize_cell_address(request.cell_address)
        worksheet = workbook.Worksheets(worksheet_name)
        cell = worksheet.Range(address)
        if int(cell.Rows.Count) != 1 or int(cell.Columns.Count) != 1:
            raise RuntimeError("Excel target no longer resolves to one cell")
        return OfficeValueObservation(
            session=session,
            target={"worksheet_name": worksheet_name, "cell_address": address},
            state=scalar_digest(cell.Value2),
        )

    @classmethod
    def _word_selection_read(cls, request: _OfficeRequest, obj, native_class: str):
        session = cls._session(request, obj, native_class)
        selection = obj.Application.Selection
        text = str(selection.Text or "")
        if len(text) > _MAX_TEXT_CHARS:
            raise RuntimeError("Word selection exceeds the bounded text verification limit")
        return OfficeValueObservation(
            session=session,
            target={"selection": "current"},
            state={
                "selection_chars": len(text),
                "selection_sha256": text_sha256(text),
                "collapsed": int(selection.Start) == int(selection.End),
            },
        )

    @classmethod
    def _execute(cls, request: _OfficeRequest, **native):
        kind = normalize_office_kind(request.office_kind)
        request.office_kind = kind
        obj, native_class = cls._native_object(request, **native)

        if request.operation == "session_read":
            return cls._session(request, obj, native_class)
        if request.operation == "excel_cell_read":
            if kind != "excel":
                raise RuntimeError("Excel cell action requires the foreground Excel application")
            return cls._excel_cell_read(request, obj, native_class)
        if request.operation == "word_selection_read":
            if kind != "word":
                raise RuntimeError("Word selection action requires the foreground Word application")
            return cls._word_selection_read(request, obj, native_class)

        if request.operation == "excel_cell_set":
            before = cls._excel_cell_read(request, obj, native_class)
            target_digest = scalar_digest(request.value)
            if before.state == target_digest:
                return OfficeMutationResult(True, False, True, before=before, after=before)
            dispatched = False
            try:
                workbook = obj.Application.ActiveWorkbook
                worksheet = workbook.Worksheets(normalize_worksheet_name(request.worksheet_name))
                cell = worksheet.Range(normalize_cell_address(request.cell_address))
                dispatched = True
                cell.Value2 = request.value
                after = cls._excel_cell_read(request, obj, native_class)
                verified = after.state == target_digest
                return OfficeMutationResult(
                    verified,
                    dispatched,
                    verified,
                    before=before,
                    after=after,
                    error=None if verified else "fresh Excel cell readback did not match target value",
                )
            except Exception as exc:
                return OfficeMutationResult(
                    False,
                    dispatched,
                    False,
                    before=before,
                    error=f"{type(exc).__name__}: {exc}",
                )

        if request.operation == "word_selection_set_text":
            if not isinstance(request.text, str) or len(request.text) > _MAX_TEXT_CHARS:
                raise ValueError(f"Word replacement text must be <= {_MAX_TEXT_CHARS} characters")
            before = cls._word_selection_read(request, obj, native_class)
            target = {
                "selection_chars": len(request.text),
                "selection_sha256": text_sha256(request.text),
            }
            if (
                before.state.get("selection_chars") == target["selection_chars"]
                and before.state.get("selection_sha256") == target["selection_sha256"]
            ):
                return OfficeMutationResult(True, False, True, before=before, after=before)
            dispatched = False
            try:
                selection = obj.Application.Selection
                dispatched = True
                selection.Text = request.text
                after = cls._word_selection_read(request, obj, native_class)
                verified = bool(
                    after.state.get("selection_chars") == target["selection_chars"]
                    and after.state.get("selection_sha256") == target["selection_sha256"]
                )
                return OfficeMutationResult(
                    verified,
                    dispatched,
                    verified,
                    before=before,
                    after=after,
                    error=None if verified else "fresh Word selection readback did not match target text",
                )
            except Exception as exc:
                return OfficeMutationResult(
                    False,
                    dispatched,
                    False,
                    before=before,
                    error=f"{type(exc).__name__}: {exc}",
                )

        raise ValueError(f"unknown Microsoft Office native operation: {request.operation}")


class NativeOfficeAction:
    """Fresh-bind one foreground Office window for each bounded operation."""

    def __init__(
        self,
        *,
        session_read_fn: OfficeSessionReadFn | None = None,
        excel_read_fn: OfficeValueReadFn | None = None,
        word_read_fn: OfficeValueReadFn | None = None,
        mutate_fn: OfficeMutateFn | None = None,
    ) -> None:
        self.session_read_fn = session_read_fn
        self.excel_read_fn = excel_read_fn
        self.word_read_fn = word_read_fn
        self.mutate_fn = mutate_fn
        self._native_worker: _WindowsOfficeNativeWorker | None = None
        self._worker_lock = threading.Lock()

    @staticmethod
    def _base(
        *,
        office_kind: str,
        process_id: int,
        process_name: str,
        window_handle: int,
        operation: str,
        **kwargs,
    ) -> _OfficeRequest:
        if int(process_id) <= 0 or int(window_handle) <= 0:
            raise ValueError("Office native action requires positive process/window identity")
        name = str(process_name or "").strip()
        if not name:
            raise ValueError("Office native action requires process name")
        return _OfficeRequest(
            operation=operation,
            office_kind=normalize_office_kind(office_kind),
            process_id=int(process_id),
            process_name=name,
            window_handle=int(window_handle),
            **kwargs,
        )

    def session_read(self, **kwargs) -> OfficeSessionObservation:
        if self.session_read_fn is not None:
            return self.session_read_fn(**kwargs)
        result = self._worker().submit(self._base(operation="session_read", **kwargs))
        if not isinstance(result, OfficeSessionObservation):
            raise RuntimeError("Office session read returned no observation")
        return result

    def excel_cell_read(self, *, worksheet_name: str, cell_address: str, **kwargs):
        request = self._base(
            operation="excel_cell_read",
            worksheet_name=normalize_worksheet_name(worksheet_name),
            cell_address=normalize_cell_address(cell_address),
            **kwargs,
        )
        if self.excel_read_fn is not None:
            return self.excel_read_fn(
                worksheet_name=request.worksheet_name,
                cell_address=request.cell_address,
                **kwargs,
            )
        result = self._worker().submit(request)
        if not isinstance(result, OfficeValueObservation):
            raise RuntimeError("Excel cell read returned no observation")
        return result

    def word_selection_read(self, **kwargs):
        if self.word_read_fn is not None:
            return self.word_read_fn(**kwargs)
        result = self._worker().submit(self._base(operation="word_selection_read", **kwargs))
        if not isinstance(result, OfficeValueObservation):
            raise RuntimeError("Word selection read returned no observation")
        return result

    def excel_cell_set(self, *, worksheet_name: str, cell_address: str, value: object, **kwargs):
        request = self._base(
            operation="excel_cell_set",
            worksheet_name=normalize_worksheet_name(worksheet_name),
            cell_address=normalize_cell_address(cell_address),
            value=value,
            **kwargs,
        )
        scalar_digest(value)
        if self.mutate_fn is not None:
            return self.mutate_fn(
                operation="excel_cell_set",
                worksheet_name=request.worksheet_name,
                cell_address=request.cell_address,
                value=value,
                **kwargs,
            )
        result = self._worker().submit(request)
        if not isinstance(result, OfficeMutationResult):
            raise RuntimeError("Excel cell mutation returned no result")
        return result

    def word_selection_set_text(self, *, text: str, **kwargs):
        if not isinstance(text, str) or len(text) > _MAX_TEXT_CHARS:
            raise ValueError(f"Word replacement text must be <= {_MAX_TEXT_CHARS} characters")
        if self.mutate_fn is not None:
            return self.mutate_fn(operation="word_selection_set_text", text=text, **kwargs)
        result = self._worker().submit(
            self._base(operation="word_selection_set_text", text=text, **kwargs)
        )
        if not isinstance(result, OfficeMutationResult):
            raise RuntimeError("Word selection mutation returned no result")
        return result

    def _worker(self) -> _WindowsOfficeNativeWorker:
        if os.name != "nt":
            raise RuntimeError("Microsoft Office native actions are available only on Windows")
        with self._worker_lock:
            if self._native_worker is None:
                self._native_worker = _WindowsOfficeNativeWorker()
            return self._native_worker
