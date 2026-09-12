from __future__ import annotations

"""Bounded current-app UIA ValuePattern read and exact replacement for E2E-13.

The normal structural UIA senses intentionally do not expose application text.
This module is the narrow exception required by E2E-13: one exact named Edit in
the current foreground non-browser process, at most 4096 characters, with
RuntimeId/process checks before and after the Value read.  Raw text is returned
only to the current caller stack; the dataclass ``audit`` views intentionally
contain hashes/counts and identity but no text.
"""

import hashlib
import os
import queue
import threading
from dataclasses import dataclass
from typing import Callable

from .models import utc_now


_UIA_EDIT_CONTROL_TYPE = 50004
_MAX_TEXT_CHARS = 4096
_MAX_NAME_CHARS = 160
_MAX_CANDIDATES = 24
_BROWSER_PROCESSES = frozenset(
    {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"}
)


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AutomationTextTargetSnapshot:
    runtime_id: tuple[int, ...]
    process_id: int
    process_name: str
    window_handle: int
    name: str
    control_type: int
    class_name: str
    is_enabled: bool
    is_offscreen: bool
    is_password: bool
    is_value_pattern_available: bool
    value_is_read_only: bool
    captured_at: str
    source: str = "windows-uia-current-app-edit"

    @property
    def identity(self) -> dict[str, object]:
        return {
            "runtime_id": list(self.runtime_id),
            "process_id": self.process_id,
            "process_name": self.process_name,
            "window_handle": self.window_handle,
            "name": self.name,
            "control_type": self.control_type,
            "class_name": self.class_name,
            "is_enabled": self.is_enabled,
            "is_offscreen": self.is_offscreen,
            "is_password": self.is_password,
            "is_value_pattern_available": self.is_value_pattern_available,
            "value_is_read_only": self.value_is_read_only,
            "captured_at": self.captured_at,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class AutomationTextRead:
    """Transient raw read plus safe before/after authority evidence."""

    text: str
    before: AutomationTextTargetSnapshot
    after: AutomationTextTargetSnapshot

    @property
    def audit(self) -> dict[str, object]:
        return {
            "chars": len(self.text),
            "sha256": text_sha256(self.text),
            "target": self.after.identity,
            "read_identity_stable": True,
        }


@dataclass(frozen=True, slots=True)
class AutomationValueReplacementResult:
    success: bool
    mutation_dispatched: bool
    postcondition_verified: bool
    process_id: int
    process_name: str
    window_handle: int
    name: str
    runtime_id: tuple[int, ...]
    source_chars: int
    source_sha256: str
    result_chars: int
    result_sha256: str
    error: str | None = None

    @property
    def audit(self) -> dict[str, object]:
        return {
            "success": self.success,
            "mutation_dispatched": self.mutation_dispatched,
            "postcondition_verified": self.postcondition_verified,
            "process_id": self.process_id,
            "process_name": self.process_name,
            "window_handle": self.window_handle,
            "name": self.name,
            "runtime_id": list(self.runtime_id),
            "source_chars": self.source_chars,
            "source_sha256": self.source_sha256,
            "result_chars": self.result_chars,
            "result_sha256": self.result_sha256,
            "error": self.error,
        }


TextReadProbeFn = Callable[..., AutomationTextRead]
TextCandidateProbeFn = Callable[..., tuple[AutomationTextTargetSnapshot, ...]]
ValueReplacementProbeFn = Callable[..., AutomationValueReplacementResult]


@dataclass(slots=True)
class _TextRequest:
    operation: str
    process_id: int
    process_name: str
    window_handle: int
    name: str | None = None
    runtime_id: tuple[int, ...] = ()
    allow_read_only: bool = False
    source_chars: int = 0
    source_sha256: str = ""
    replacement_text: str = ""
    result_chars: int = 0
    result_sha256: str = ""
    done: threading.Event | None = None
    result: object | None = None
    error: str | None = None


class _WindowsAutomationTextWorker:
    _START_TIMEOUT_SECONDS = 10.0
    _PROBE_TIMEOUT_SECONDS = 6.0
    _CONNECTION_TIMEOUT_MS = 1500
    _TRANSACTION_TIMEOUT_MS = 2500
    _CUIAUTOMATION8_CLSID = "{e22ad333-b25f-460c-83d0-0581107395c9}"

    def __init__(self) -> None:
        self._requests: queue.Queue[_TextRequest] = queue.Queue(maxsize=1)
        self._started = threading.Event()
        self._failure: str | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="zn-uia-current-app-text",
            daemon=True,
        )
        self._thread.start()
        if not self._started.wait(self._START_TIMEOUT_SECONDS):
            self._failure = "Windows UI Automation current-app text worker did not initialize in time"
            raise RuntimeError(self._failure)
        if self._failure:
            raise RuntimeError(self._failure)

    def read_exact(
        self,
        *,
        process_id: int,
        process_name: str,
        window_handle: int,
        name: str,
        runtime_id: tuple[int, ...],
        allow_read_only: bool,
    ) -> AutomationTextRead:
        result = self._submit(
            _TextRequest(
                operation="read",
                process_id=int(process_id),
                process_name=str(process_name),
                window_handle=int(window_handle),
                name=str(name),
                runtime_id=tuple(int(v) for v in runtime_id),
                allow_read_only=bool(allow_read_only),
            )
        )
        if not isinstance(result, AutomationTextRead):
            raise RuntimeError("Windows UI Automation text read returned no exact observation")
        return result

    def list_value_edits(
        self,
        *,
        process_id: int,
        process_name: str,
        window_handle: int,
    ) -> tuple[AutomationTextTargetSnapshot, ...]:
        result = self._submit(
            _TextRequest(
                operation="list",
                process_id=int(process_id),
                process_name=str(process_name),
                window_handle=int(window_handle),
            )
        )
        if not isinstance(result, tuple):
            raise RuntimeError("Windows UI Automation text candidate collection returned no result")
        return result

    def replace_exact(
        self,
        *,
        process_id: int,
        process_name: str,
        window_handle: int,
        name: str,
        runtime_id: tuple[int, ...],
        source_chars: int,
        source_sha256: str,
        replacement_text: str,
        result_chars: int,
        result_sha256: str,
    ) -> AutomationValueReplacementResult:
        result = self._submit(
            _TextRequest(
                operation="replace",
                process_id=int(process_id),
                process_name=str(process_name),
                window_handle=int(window_handle),
                name=str(name),
                runtime_id=tuple(int(v) for v in runtime_id),
                source_chars=int(source_chars),
                source_sha256=str(source_sha256),
                replacement_text=str(replacement_text),
                result_chars=int(result_chars),
                result_sha256=str(result_sha256),
            )
        )
        if not isinstance(result, AutomationValueReplacementResult):
            raise RuntimeError("Windows UI Automation replacement returned no result")
        return result

    def _submit(self, request: _TextRequest):
        if self._failure:
            raise RuntimeError(self._failure)
        request.done = threading.Event()
        try:
            self._requests.put_nowait(request)
        except queue.Full as exc:
            raise RuntimeError("Windows UI Automation current-app text worker is busy") from exc
        assert request.done is not None
        if not request.done.wait(self._PROBE_TIMEOUT_SECONDS):
            self._failure = "Windows UI Automation current-app text operation exceeded its bounded timeout"
            raise RuntimeError(self._failure)
        if request.error:
            raise RuntimeError(request.error)
        return request.result

    def _run(self) -> None:
        try:
            import sys

            comtypes_was_loaded = "comtypes" in sys.modules
            had_coinitialize_flag = hasattr(sys, "coinit_flags")
            previous_coinitialize_flag = getattr(sys, "coinit_flags", None)
            if not comtypes_was_loaded:
                sys.coinit_flags = 0
            try:
                import comtypes
                import comtypes.client as com_client
                from comtypes.client import CreateObject, GetModule
            finally:
                if not comtypes_was_loaded:
                    if had_coinitialize_flag:
                        sys.coinit_flags = previous_coinitialize_flag
                    else:
                        del sys.coinit_flags
            if comtypes_was_loaded:
                comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)

            com_client.gen_dir = None
            client = GetModule("UIAutomationCore.dll")
            automation = CreateObject(
                self._CUIAUTOMATION8_CLSID,
                interface=client.IUIAutomation2,
            )
            automation.ConnectionTimeout = self._CONNECTION_TIMEOUT_MS
            automation.TransactionTimeout = self._TRANSACTION_TIMEOUT_MS
            cache = automation.CreateCacheRequest()
            cache.AutomationElementMode = client.AutomationElementMode_Full
            cache.TreeScope = client.TreeScope_Element
            for property_id in (
                client.UIA_RuntimeIdPropertyId,
                client.UIA_ProcessIdPropertyId,
                client.UIA_NamePropertyId,
                client.UIA_ControlTypePropertyId,
                client.UIA_ClassNamePropertyId,
                client.UIA_IsEnabledPropertyId,
                client.UIA_IsOffscreenPropertyId,
                client.UIA_IsPasswordPropertyId,
                client.UIA_IsValuePatternAvailablePropertyId,
                client.UIA_ValueIsReadOnlyPropertyId,
            ):
                cache.AddProperty(property_id)
        except Exception as exc:
            self._failure = (
                "Windows UI Automation current-app text worker initialization failed: "
                f"{type(exc).__name__}: {exc}"
            )
            self._started.set()
            return

        self._started.set()
        while True:
            request = self._requests.get()
            try:
                if request.operation == "list":
                    request.result = self._list_candidates(
                        automation,
                        client,
                        cache,
                        request,
                    )
                elif request.operation == "read":
                    request.result = self._read(
                        automation,
                        client,
                        cache,
                        request,
                    )
                elif request.operation == "replace":
                    request.result = self._replace(
                        automation,
                        client,
                        cache,
                        request,
                    )
                else:
                    raise ValueError(f"unknown current-app text operation: {request.operation}")
            except Exception as exc:
                request.error = (
                    "Windows UI Automation current-app text operation failed: "
                    f"{type(exc).__name__}: {exc}"
                )
            finally:
                if request.done is not None:
                    request.done.set()

    @staticmethod
    def _foreground_process(expected_hwnd: int, expected_pid: int) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        hwnd = int(user32.GetForegroundWindow() or 0)
        if hwnd != int(expected_hwnd):
            raise RuntimeError("foreground HWND changed during current-app text operation")
        pid = wintypes.DWORD(0)
        thread_id = int(user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)))
        if thread_id <= 0 or int(pid.value) != int(expected_pid):
            raise RuntimeError("foreground process changed during current-app text operation")

    @staticmethod
    def _cached_bool(element, property_id: int, *, field_name: str) -> bool:
        value = element.GetCachedPropertyValue(int(property_id))
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return bool(value)
        raise RuntimeError(f"cached UI Automation {field_name} is not boolean")

    @classmethod
    def _snapshot(cls, element, client, *, window_handle: int) -> AutomationTextTargetSnapshot:
        runtime_value = element.GetCachedPropertyValue(client.UIA_RuntimeIdPropertyId)
        runtime_id = tuple(int(value) for value in runtime_value)
        process_id = int(element.CachedProcessId)
        try:
            import psutil

            process_name = str(psutil.Process(process_id).name() or "").strip().lower()
        except Exception as exc:
            raise RuntimeError("current-app UIA text process name is unavailable") from exc
        return AutomationTextTargetSnapshot(
            runtime_id=runtime_id,
            process_id=process_id,
            process_name=process_name,
            window_handle=int(window_handle),
            name=" ".join(str(element.CachedName or "").strip().split()),
            control_type=int(element.CachedControlType),
            class_name=str(element.CachedClassName or ""),
            is_enabled=bool(element.CachedIsEnabled),
            is_offscreen=bool(element.CachedIsOffscreen),
            is_password=cls._cached_bool(
                element,
                client.UIA_IsPasswordPropertyId,
                field_name="is_password",
            ),
            is_value_pattern_available=cls._cached_bool(
                element,
                client.UIA_IsValuePatternAvailablePropertyId,
                field_name="is_value_pattern_available",
            ),
            value_is_read_only=cls._cached_bool(
                element,
                client.UIA_ValueIsReadOnlyPropertyId,
                field_name="value_is_read_only",
            ),
            captured_at=utc_now(),
        )

    @classmethod
    def _require_target(
        cls,
        snapshot: AutomationTextTargetSnapshot,
        *,
        process_id: int,
        process_name: str,
        window_handle: int,
        name: str,
        runtime_id: tuple[int, ...] | None,
        allow_read_only: bool,
    ) -> None:
        if (
            snapshot.process_id != int(process_id)
            or snapshot.process_name != str(process_name or "").strip().lower()
            or snapshot.window_handle != int(window_handle)
            or snapshot.name != str(name)
            or snapshot.control_type != _UIA_EDIT_CONTROL_TYPE
            or not snapshot.runtime_id
            or not snapshot.is_enabled
            or snapshot.is_offscreen
            or snapshot.is_password
            or not snapshot.is_value_pattern_available
        ):
            raise RuntimeError("UIA Edit failed bounded current-app text validation")
        if snapshot.process_name in _BROWSER_PROCESSES:
            raise RuntimeError("current-app text operation refuses browser processes")
        if runtime_id is not None and snapshot.runtime_id != tuple(runtime_id):
            raise RuntimeError("exact UIA Edit RuntimeId changed before current-app text operation")
        if snapshot.value_is_read_only and not allow_read_only:
            raise RuntimeError("current-app text mutation/read authority requires a writable Edit")

    @classmethod
    def _find_exact(cls, automation, client, cache, request: _TextRequest):
        cls._foreground_process(request.window_handle, request.process_id)
        root = automation.ElementFromHandle(int(request.window_handle))
        if not root:
            raise RuntimeError("Windows UI Automation could not bind the foreground HWND")
        type_condition = automation.CreatePropertyCondition(
            client.UIA_ControlTypePropertyId,
            _UIA_EDIT_CONTROL_TYPE,
        )
        process_condition = automation.CreatePropertyCondition(
            client.UIA_ProcessIdPropertyId,
            int(request.process_id),
        )
        name_condition = automation.CreatePropertyCondition(
            client.UIA_NamePropertyId,
            str(request.name or ""),
        )
        condition = automation.CreateAndCondition(
            automation.CreateAndCondition(type_condition, process_condition),
            name_condition,
        )
        matches = root.FindAllBuildCache(client.TreeScope_Descendants, condition, cache)
        if int(matches.Length) != 1:
            raise RuntimeError(
                "foreground application did not expose exactly one exact named UIA Edit "
                f"(matches={int(matches.Length)})"
            )
        element = matches.GetElement(0)
        if not element:
            raise RuntimeError("exact named UIA Edit disappeared during acquisition")
        return element

    @staticmethod
    def _pattern_value(element, client) -> str:
        unknown = element.GetCurrentPattern(client.UIA_ValuePatternId)
        if not unknown:
            raise RuntimeError("exact UIA Edit did not return ValuePattern")
        pattern = unknown.QueryInterface(client.IUIAutomationValuePattern)
        value = pattern.CurrentValue
        if value is None:
            return ""
        if not isinstance(value, str):
            raise RuntimeError("exact UIA ValuePattern current value is not a string")
        if len(value) > _MAX_TEXT_CHARS:
            raise RuntimeError(
                f"exact UIA Edit text exceeds the {_MAX_TEXT_CHARS}-character bound"
            )
        return value

    @classmethod
    def _read(cls, automation, client, cache, request: _TextRequest) -> AutomationTextRead:
        first = cls._find_exact(automation, client, cache, request)
        before = cls._snapshot(first, client, window_handle=request.window_handle)
        cls._require_target(
            before,
            process_id=request.process_id,
            process_name=request.process_name,
            window_handle=request.window_handle,
            name=str(request.name or ""),
            runtime_id=request.runtime_id,
            allow_read_only=request.allow_read_only,
        )
        text = cls._pattern_value(first, client)
        second = cls._find_exact(automation, client, cache, request)
        after = cls._snapshot(second, client, window_handle=request.window_handle)
        cls._require_target(
            after,
            process_id=request.process_id,
            process_name=request.process_name,
            window_handle=request.window_handle,
            name=str(request.name or ""),
            runtime_id=request.runtime_id,
            allow_read_only=request.allow_read_only,
        )
        cls._foreground_process(request.window_handle, request.process_id)
        if before.runtime_id != after.runtime_id:
            raise RuntimeError("exact UIA Edit RuntimeId changed during ValuePattern read")
        if before.process_id != after.process_id or before.process_name != after.process_name:
            raise RuntimeError("exact UIA Edit process identity changed during ValuePattern read")
        return AutomationTextRead(text=text, before=before, after=after)

    @classmethod
    def _list_candidates(cls, automation, client, cache, request: _TextRequest):
        cls._foreground_process(request.window_handle, request.process_id)
        root = automation.ElementFromHandle(int(request.window_handle))
        if not root:
            raise RuntimeError("Windows UI Automation could not bind the foreground HWND")
        type_condition = automation.CreatePropertyCondition(
            client.UIA_ControlTypePropertyId,
            _UIA_EDIT_CONTROL_TYPE,
        )
        process_condition = automation.CreatePropertyCondition(
            client.UIA_ProcessIdPropertyId,
            int(request.process_id),
        )
        condition = automation.CreateAndCondition(type_condition, process_condition)
        matches = root.FindAllBuildCache(client.TreeScope_Descendants, condition, cache)
        count = int(matches.Length)
        if count > _MAX_CANDIDATES:
            raise RuntimeError(
                "foreground application exposed too many UIA Edit candidates for bounded text verification"
            )
        output: list[AutomationTextTargetSnapshot] = []
        for index in range(count):
            element = matches.GetElement(index)
            if not element:
                continue
            snapshot = cls._snapshot(element, client, window_handle=request.window_handle)
            if (
                snapshot.process_id != request.process_id
                or snapshot.process_name != request.process_name.strip().lower()
                or snapshot.control_type != _UIA_EDIT_CONTROL_TYPE
                or not snapshot.name
                or len(snapshot.name) > _MAX_NAME_CHARS
                or not snapshot.runtime_id
                or not snapshot.is_enabled
                or snapshot.is_offscreen
                or snapshot.is_password
                or not snapshot.is_value_pattern_available
            ):
                continue
            output.append(snapshot)
        cls._foreground_process(request.window_handle, request.process_id)
        return tuple(output)

    @classmethod
    def _replace(
        cls,
        automation,
        client,
        cache,
        request: _TextRequest,
    ) -> AutomationValueReplacementResult:
        dispatched = False
        safe_runtime = tuple(request.runtime_id)
        try:
            first = cls._find_exact(automation, client, cache, request)
            before = cls._snapshot(first, client, window_handle=request.window_handle)
            cls._require_target(
                before,
                process_id=request.process_id,
                process_name=request.process_name,
                window_handle=request.window_handle,
                name=str(request.name or ""),
                runtime_id=request.runtime_id,
                allow_read_only=False,
            )
            safe_runtime = before.runtime_id
            first_value = cls._pattern_value(first, client)
            if len(first_value) != request.source_chars or text_sha256(first_value) != request.source_sha256:
                raise RuntimeError("exact UIA Edit content changed before replacement authority")

            # Re-acquire immediately before SetValue.  The first Value read is
            # evidence only and never becomes mutation authority by itself.
            current = cls._find_exact(automation, client, cache, request)
            current_snapshot = cls._snapshot(current, client, window_handle=request.window_handle)
            cls._require_target(
                current_snapshot,
                process_id=request.process_id,
                process_name=request.process_name,
                window_handle=request.window_handle,
                name=str(request.name or ""),
                runtime_id=request.runtime_id,
                allow_read_only=False,
            )
            current_value = cls._pattern_value(current, client)
            if len(current_value) != request.source_chars or text_sha256(current_value) != request.source_sha256:
                raise RuntimeError("exact UIA Edit content drifted at the final replacement boundary")
            if len(request.replacement_text) != request.result_chars:
                raise RuntimeError("replacement text length does not match Resident result authority")
            if text_sha256(request.replacement_text) != request.result_sha256:
                raise RuntimeError("replacement text digest does not match Resident result authority")
            if not request.replacement_text or len(request.replacement_text) > _MAX_TEXT_CHARS:
                raise RuntimeError("replacement text violates the bounded non-empty text contract")

            unknown = current.GetCurrentPattern(client.UIA_ValuePatternId)
            if not unknown:
                raise RuntimeError("exact UIA Edit lost ValuePattern before replacement")
            pattern = unknown.QueryInterface(client.IUIAutomationValuePattern)
            dispatched = True
            pattern.SetValue(request.replacement_text)

            post = cls._find_exact(automation, client, cache, request)
            post_snapshot = cls._snapshot(post, client, window_handle=request.window_handle)
            cls._require_target(
                post_snapshot,
                process_id=request.process_id,
                process_name=request.process_name,
                window_handle=request.window_handle,
                name=str(request.name or ""),
                runtime_id=request.runtime_id,
                allow_read_only=False,
            )
            post_value = cls._pattern_value(post, client)
            cls._foreground_process(request.window_handle, request.process_id)
            post_hash = text_sha256(post_value)
            if len(post_value) != request.result_chars or post_hash != request.result_sha256:
                return AutomationValueReplacementResult(
                    success=False,
                    mutation_dispatched=True,
                    postcondition_verified=False,
                    process_id=request.process_id,
                    process_name=request.process_name.strip().lower(),
                    window_handle=request.window_handle,
                    name=str(request.name or ""),
                    runtime_id=post_snapshot.runtime_id,
                    source_chars=request.source_chars,
                    source_sha256=request.source_sha256,
                    result_chars=len(post_value),
                    result_sha256=post_hash,
                    error="fresh exact-target post-read did not match the expected replacement",
                )
            return AutomationValueReplacementResult(
                success=True,
                mutation_dispatched=True,
                postcondition_verified=True,
                process_id=request.process_id,
                process_name=request.process_name.strip().lower(),
                window_handle=request.window_handle,
                name=str(request.name or ""),
                runtime_id=post_snapshot.runtime_id,
                source_chars=request.source_chars,
                source_sha256=request.source_sha256,
                result_chars=request.result_chars,
                result_sha256=request.result_sha256,
            )
        except Exception as exc:
            return AutomationValueReplacementResult(
                success=False,
                mutation_dispatched=dispatched,
                postcondition_verified=False,
                process_id=request.process_id,
                process_name=request.process_name.strip().lower(),
                window_handle=request.window_handle,
                name=str(request.name or ""),
                runtime_id=safe_runtime,
                source_chars=request.source_chars,
                source_sha256=request.source_sha256,
                result_chars=request.result_chars,
                result_sha256=request.result_sha256,
                error=f"{type(exc).__name__}: {exc}",
            )


class NativeAutomationTextContentSense:
    """Read one exact current-app UIA Edit without widening structural Sense."""

    def __init__(
        self,
        *,
        read_probe_fn: TextReadProbeFn | None = None,
        candidate_probe_fn: TextCandidateProbeFn | None = None,
    ) -> None:
        self.read_probe_fn = read_probe_fn
        self.candidate_probe_fn = candidate_probe_fn
        self._native_worker: _WindowsAutomationTextWorker | None = None
        self._lock = threading.Lock()

    def read_exact(
        self,
        *,
        process_id: int,
        process_name: str,
        window_handle: int,
        name: str,
        runtime_id: tuple[int, ...],
        allow_read_only: bool = False,
    ) -> AutomationTextRead:
        expected_pid, expected_process, expected_hwnd, expected_name, expected_runtime = self._inputs(
            process_id,
            process_name,
            window_handle,
            name,
            runtime_id,
        )
        if self.read_probe_fn is not None:
            read = self.read_probe_fn(
                process_id=expected_pid,
                process_name=expected_process,
                window_handle=expected_hwnd,
                name=expected_name,
                runtime_id=expected_runtime,
                allow_read_only=bool(allow_read_only),
            )
        else:
            read = self._worker().read_exact(
                process_id=expected_pid,
                process_name=expected_process,
                window_handle=expected_hwnd,
                name=expected_name,
                runtime_id=expected_runtime,
                allow_read_only=bool(allow_read_only),
            )
        if not isinstance(read, AutomationTextRead):
            raise TypeError("current-app text read probe must return AutomationTextRead")
        self._validate_read(
            read,
            process_id=expected_pid,
            process_name=expected_process,
            window_handle=expected_hwnd,
            name=expected_name,
            runtime_id=expected_runtime,
            allow_read_only=bool(allow_read_only),
        )
        return read

    def list_value_edits(
        self,
        *,
        process_id: int,
        process_name: str,
        window_handle: int,
    ) -> tuple[AutomationTextTargetSnapshot, ...]:
        expected_pid, expected_process, expected_hwnd, _, _ = self._inputs(
            process_id,
            process_name,
            window_handle,
            "candidate",
            (1,),
        )
        if self.candidate_probe_fn is not None:
            candidates = self.candidate_probe_fn(
                process_id=expected_pid,
                process_name=expected_process,
                window_handle=expected_hwnd,
            )
        else:
            candidates = self._worker().list_value_edits(
                process_id=expected_pid,
                process_name=expected_process,
                window_handle=expected_hwnd,
            )
        if not isinstance(candidates, tuple) or len(candidates) > _MAX_CANDIDATES:
            raise ValueError("current-app text candidate probe exceeded its bounded contract")
        checked: list[AutomationTextTargetSnapshot] = []
        for candidate in candidates:
            self._validate_snapshot(
                candidate,
                process_id=expected_pid,
                process_name=expected_process,
                window_handle=expected_hwnd,
                name=None,
                runtime_id=None,
                allow_read_only=True,
            )
            if not candidate.name or len(candidate.name) > _MAX_NAME_CHARS:
                raise ValueError("current-app text candidate has no bounded semantic name")
            checked.append(candidate)
        return tuple(checked)

    @staticmethod
    def _inputs(process_id, process_name, window_handle, name, runtime_id):
        pid = int(process_id)
        process = str(process_name or "").strip().lower()
        hwnd = int(window_handle)
        semantic_name = " ".join(str(name or "").strip().split())
        rid = tuple(int(v) for v in runtime_id)
        if pid <= 0 or hwnd <= 0 or not process or process in _BROWSER_PROCESSES:
            raise ValueError("current-app text Sense requires one foreground non-browser process/HWND")
        if not semantic_name or len(semantic_name) > _MAX_NAME_CHARS:
            raise ValueError("current-app text Sense requires one bounded exact Edit name")
        if not rid:
            raise ValueError("current-app text Sense requires one exact RuntimeId")
        return pid, process, hwnd, semantic_name, rid

    @classmethod
    def _validate_read(
        cls,
        read: AutomationTextRead,
        *,
        process_id: int,
        process_name: str,
        window_handle: int,
        name: str,
        runtime_id: tuple[int, ...],
        allow_read_only: bool,
    ) -> None:
        if not isinstance(read.text, str) or len(read.text) > _MAX_TEXT_CHARS:
            raise ValueError("current-app text read returned an invalid or oversized value")
        cls._validate_snapshot(
            read.before,
            process_id=process_id,
            process_name=process_name,
            window_handle=window_handle,
            name=name,
            runtime_id=runtime_id,
            allow_read_only=allow_read_only,
        )
        cls._validate_snapshot(
            read.after,
            process_id=process_id,
            process_name=process_name,
            window_handle=window_handle,
            name=name,
            runtime_id=runtime_id,
            allow_read_only=allow_read_only,
        )
        if read.before.runtime_id != read.after.runtime_id:
            raise ValueError("current-app text RuntimeId drifted during read")
        if (
            read.before.process_id != read.after.process_id
            or read.before.process_name != read.after.process_name
        ):
            raise ValueError("current-app text process identity drifted during read")

    @staticmethod
    def _validate_snapshot(
        snapshot: AutomationTextTargetSnapshot,
        *,
        process_id: int,
        process_name: str,
        window_handle: int,
        name: str | None,
        runtime_id: tuple[int, ...] | None,
        allow_read_only: bool,
    ) -> None:
        if not isinstance(snapshot, AutomationTextTargetSnapshot):
            raise TypeError("current-app text target must be AutomationTextTargetSnapshot")
        if (
            snapshot.process_id != int(process_id)
            or snapshot.process_name.strip().lower() != str(process_name).strip().lower()
            or snapshot.window_handle != int(window_handle)
            or snapshot.control_type != _UIA_EDIT_CONTROL_TYPE
            or not snapshot.runtime_id
            or not snapshot.is_enabled
            or snapshot.is_offscreen
            or snapshot.is_password
            or not snapshot.is_value_pattern_available
        ):
            raise ValueError("current-app text target failed safe exact-Edit validation")
        if snapshot.process_name.strip().lower() in _BROWSER_PROCESSES:
            raise ValueError("current-app text target is a browser process")
        if name is not None and snapshot.name != name:
            raise ValueError("current-app text target name drifted")
        if runtime_id is not None and snapshot.runtime_id != tuple(runtime_id):
            raise ValueError("current-app text target RuntimeId drifted")
        if snapshot.value_is_read_only and not allow_read_only:
            raise ValueError("current-app text read refuses read-only mutation targets")

    def _worker(self) -> _WindowsAutomationTextWorker:
        if os.name != "nt":
            raise RuntimeError("current-app UI Automation text Sense is available only on Windows")
        if self._native_worker is None:
            with self._lock:
                if self._native_worker is None:
                    self._native_worker = _WindowsAutomationTextWorker()
        return self._native_worker


class NativeAutomationValueReplacementBody:
    """Exact ValuePattern.SetValue primitive with no target/planning semantics."""

    def __init__(self, *, replace_probe_fn: ValueReplacementProbeFn | None = None) -> None:
        self.replace_probe_fn = replace_probe_fn
        self._native_worker: _WindowsAutomationTextWorker | None = None
        self._lock = threading.Lock()

    def replace_exact(
        self,
        *,
        process_id: int,
        process_name: str,
        window_handle: int,
        name: str,
        runtime_id: tuple[int, ...],
        source_chars: int,
        source_sha256: str,
        replacement_text: str,
        result_chars: int,
        result_sha256: str,
    ) -> AutomationValueReplacementResult:
        pid, process, hwnd, semantic_name, rid = NativeAutomationTextContentSense._inputs(
            process_id,
            process_name,
            window_handle,
            name,
            runtime_id,
        )
        source_hash = self._digest(source_sha256, "source")
        result_hash = self._digest(result_sha256, "result")
        source_count = int(source_chars)
        result_count = int(result_chars)
        value = str(replacement_text)
        if not 0 <= source_count <= _MAX_TEXT_CHARS:
            raise ValueError("replacement source length is outside the bounded text contract")
        if not 0 < result_count <= _MAX_TEXT_CHARS:
            raise ValueError("replacement result length is outside the bounded text contract")
        if len(value) != result_count or text_sha256(value) != result_hash:
            raise ValueError("replacement raw value does not match its Resident-owned digest authority")
        if self.replace_probe_fn is not None:
            result = self.replace_probe_fn(
                process_id=pid,
                process_name=process,
                window_handle=hwnd,
                name=semantic_name,
                runtime_id=rid,
                source_chars=source_count,
                source_sha256=source_hash,
                replacement_text=value,
                result_chars=result_count,
                result_sha256=result_hash,
            )
        else:
            result = self._worker().replace_exact(
                process_id=pid,
                process_name=process,
                window_handle=hwnd,
                name=semantic_name,
                runtime_id=rid,
                source_chars=source_count,
                source_sha256=source_hash,
                replacement_text=value,
                result_chars=result_count,
                result_sha256=result_hash,
            )
        if not isinstance(result, AutomationValueReplacementResult):
            raise TypeError("automation Value replacement probe returned an invalid result")
        if (
            result.process_id != pid
            or result.process_name.strip().lower() != process
            or result.window_handle != hwnd
            or result.name != semantic_name
            or result.runtime_id != rid
            or result.source_chars != source_count
            or result.source_sha256 != source_hash
        ):
            raise ValueError("automation Value replacement result lost exact target/source authority")
        if result.success and (
            not result.mutation_dispatched
            or not result.postcondition_verified
            or result.result_chars != result_count
            or result.result_sha256 != result_hash
        ):
            raise ValueError("automation Value replacement claimed success without exact postcondition")
        return result

    @staticmethod
    def _digest(value: str, label: str) -> str:
        digest = str(value or "").strip().lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"replacement {label} SHA-256 is invalid")
        return digest

    def _worker(self) -> _WindowsAutomationTextWorker:
        if os.name != "nt":
            raise RuntimeError("automation Value replacement is available only on Windows")
        if self._native_worker is None:
            with self._lock:
                if self._native_worker is None:
                    self._native_worker = _WindowsAutomationTextWorker()
        return self._native_worker
