from __future__ import annotations

"""Bounded exact-name UIA discovery inside the current foreground desktop app."""

import os
import queue
import threading
from dataclasses import dataclass
from typing import Callable

from .models import utc_now


_UIA_BUTTON_CONTROL_TYPE = 50000
_MAX_NAME_CHARS = 160


@dataclass(frozen=True, slots=True)
class NamedAutomationControlObservation:
    runtime_id: tuple[int, ...]
    process_id: int
    process_name: str
    name: str
    control_type: int
    class_name: str
    is_enabled: bool
    is_offscreen: bool
    left: float
    top: float
    right: float
    bottom: float
    center_x_fraction: float
    center_y_fraction: float
    captured_at: str
    source: str = "windows-uia-exact-name"


NamedControlProbeFn = Callable[[int, str, str], NamedAutomationControlObservation]


@dataclass(slots=True)
class _NamedControlRequest:
    process_id: int
    process_name: str
    name: str
    done: threading.Event | None = None
    result: NamedAutomationControlObservation | None = None
    error: str | None = None


class _WindowsNamedControlReader:
    """Lazy MTA UIA worker restricted to one exact named foreground Button."""

    _START_TIMEOUT_SECONDS = 10.0
    _PROBE_TIMEOUT_SECONDS = 6.0
    _CONNECTION_TIMEOUT_MS = 1500
    _TRANSACTION_TIMEOUT_MS = 2500
    _CUIAUTOMATION8_CLSID = "{e22ad333-b25f-460c-83d0-0581107395c9}"

    def __init__(self):
        self._requests: queue.Queue[_NamedControlRequest] = queue.Queue(maxsize=1)
        self._started = threading.Event()
        self._failure: str | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="zn-uia-named-control-sense",
            daemon=True,
        )
        self._thread.start()
        if not self._started.wait(self._START_TIMEOUT_SECONDS):
            self._failure = "Windows UI Automation named-control worker did not initialize in time"
            raise RuntimeError(self._failure)
        if self._failure:
            raise RuntimeError(self._failure)

    def probe(self, process_id: int, process_name: str, name: str) -> NamedAutomationControlObservation:
        if self._failure:
            raise RuntimeError(self._failure)
        request = _NamedControlRequest(
            process_id=int(process_id),
            process_name=str(process_name),
            name=str(name),
            done=threading.Event(),
        )
        try:
            self._requests.put_nowait(request)
        except queue.Full as exc:
            raise RuntimeError("Windows UI Automation named-control worker is busy") from exc
        assert request.done is not None
        if not request.done.wait(self._PROBE_TIMEOUT_SECONDS):
            self._failure = "Windows UI Automation exact-name probe exceeded its bounded timeout"
            raise RuntimeError(self._failure)
        if request.error:
            raise RuntimeError(request.error)
        if request.result is None:
            raise RuntimeError("Windows UI Automation exact-name probe returned no observation")
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
            cache.AutomationElementMode = client.AutomationElementMode_None
            cache.TreeScope = client.TreeScope_Element
            for property_id in (
                client.UIA_RuntimeIdPropertyId,
                client.UIA_ProcessIdPropertyId,
                client.UIA_NamePropertyId,
                client.UIA_ControlTypePropertyId,
                client.UIA_ClassNamePropertyId,
                client.UIA_IsEnabledPropertyId,
                client.UIA_IsOffscreenPropertyId,
                client.UIA_BoundingRectanglePropertyId,
            ):
                cache.AddProperty(property_id)
        except Exception as exc:
            self._failure = (
                "Windows UI Automation named-control worker initialization failed: "
                f"{type(exc).__name__}: {exc}"
            )
            self._started.set()
            return

        self._started.set()
        while True:
            request = self._requests.get()
            try:
                hwnd, screen_width, screen_height = self._foreground_window_for_process(
                    request.process_id
                )
                root = automation.ElementFromHandle(hwnd)
                if not root:
                    raise RuntimeError("Windows UI Automation could not bind the foreground window")

                name_condition = automation.CreatePropertyCondition(
                    client.UIA_NamePropertyId,
                    request.name,
                )
                type_condition = automation.CreatePropertyCondition(
                    client.UIA_ControlTypePropertyId,
                    _UIA_BUTTON_CONTROL_TYPE,
                )
                process_condition = automation.CreatePropertyCondition(
                    client.UIA_ProcessIdPropertyId,
                    request.process_id,
                )
                condition = automation.CreateAndCondition(
                    automation.CreateAndCondition(name_condition, type_condition),
                    process_condition,
                )
                matches = root.FindAllBuildCache(
                    client.TreeScope_Descendants,
                    condition,
                    cache,
                )
                count = int(matches.Length)
                if count != 1:
                    raise RuntimeError(
                        "foreground application did not expose exactly one enabled UIA Button "
                        f"with the exact requested name (matches={count})"
                    )
                element = matches.GetElement(0)
                if not element:
                    raise RuntimeError("Windows UI Automation exact-name collection returned no element")
                request.result = self._snapshot(
                    element,
                    expected_process_id=request.process_id,
                    expected_process_name=request.process_name,
                    expected_name=request.name,
                    screen_width=screen_width,
                    screen_height=screen_height,
                    runtime_id_property_id=client.UIA_RuntimeIdPropertyId,
                    name_property_id=client.UIA_NamePropertyId,
                )
            except Exception as exc:
                request.error = (
                    "Windows UI Automation exact-name probe failed: "
                    f"{type(exc).__name__}: {exc}"
                )
            finally:
                if request.done is not None:
                    request.done.set()

    @staticmethod
    def _foreground_window_for_process(expected_process_id: int):
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        user32.GetSystemMetrics.restype = ctypes.c_int

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            raise RuntimeError("Windows did not report a foreground window")
        process_id = wintypes.DWORD(0)
        thread_id = int(user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id)))
        if thread_id <= 0 or int(process_id.value) != int(expected_process_id):
            raise RuntimeError("foreground window process changed before exact-name discovery")
        width = int(user32.GetSystemMetrics(0))
        height = int(user32.GetSystemMetrics(1))
        if width <= 0 or height <= 0:
            raise RuntimeError("primary desktop dimensions are unavailable")
        return hwnd, width, height

    @staticmethod
    def _snapshot(
        element,
        *,
        expected_process_id: int,
        expected_process_name: str,
        expected_name: str,
        screen_width: int,
        screen_height: int,
        runtime_id_property_id: int,
        name_property_id: int,
    ) -> NamedAutomationControlObservation:
        runtime_value = element.GetCachedPropertyValue(int(runtime_id_property_id))
        runtime_id = tuple(int(value) for value in runtime_value)
        name = str(element.GetCachedPropertyValue(int(name_property_id)) or "").strip()
        process_id = int(element.CachedProcessId)
        control_type = int(element.CachedControlType)
        is_enabled = bool(element.CachedIsEnabled)
        is_offscreen = bool(element.CachedIsOffscreen)
        rectangle = element.CachedBoundingRectangle
        left = float(rectangle.left)
        top = float(rectangle.top)
        right = float(rectangle.right)
        bottom = float(rectangle.bottom)

        try:
            import psutil

            process_name = str(psutil.Process(process_id).name() or "").strip()
        except Exception as exc:
            raise RuntimeError("named UIA control process name is unavailable") from exc

        if (
            process_id != int(expected_process_id)
            or process_name.lower() != str(expected_process_name or "").strip().lower()
            or name != expected_name
            or control_type != _UIA_BUTTON_CONTROL_TYPE
            or not runtime_id
            or not is_enabled
            or is_offscreen
            or not (right > left and bottom > top)
        ):
            raise RuntimeError("exact named UIA Button failed bounded current-state validation")
        center_x = (left + right) / 2.0
        center_y = (top + bottom) / 2.0
        if not (0 <= center_x < screen_width and 0 <= center_y < screen_height):
            raise RuntimeError("exact named UIA Button center is outside the primary desktop")

        return NamedAutomationControlObservation(
            runtime_id=runtime_id,
            process_id=process_id,
            process_name=process_name,
            name=name,
            control_type=control_type,
            class_name=str(element.CachedClassName or ""),
            is_enabled=is_enabled,
            is_offscreen=is_offscreen,
            left=left,
            top=top,
            right=right,
            bottom=bottom,
            center_x_fraction=round(center_x / float(screen_width), 6),
            center_y_fraction=round(center_y / float(screen_height), 6),
            captured_at=utc_now(),
        )


class NativeNamedAutomationControlSense:
    """Find exactly one current foreground UIA Button by user-visible exact name.

    This is a narrow read-only discovery surface for real desktop task closure,
    not a generic UIA tree browser. Native discovery searches only the current
    foreground window, only the current process, only Button control type 50000,
    and only one exact bounded Name. Zero or multiple matches fail closed. It
    returns structural identity and a bounded click point; it never reads text
    values, passwords, arbitrary descendants, control patterns, or mutation APIs.
    """

    def __init__(self, *, probe_fn: NamedControlProbeFn | None = None):
        self.probe_fn = probe_fn
        self._native_reader: _WindowsNamedControlReader | None = None
        self._reader_lock = threading.Lock()

    def find_unique_button(
        self,
        *,
        process_id: int,
        process_name: str,
        name: str,
    ) -> NamedAutomationControlObservation:
        expected_pid = int(process_id)
        expected_process = str(process_name or "").strip()
        expected_name = " ".join(str(name or "").strip().split())
        if expected_pid <= 0 or not expected_process:
            raise ValueError("exact named desktop Button discovery requires current process identity")
        if not expected_name or len(expected_name) > _MAX_NAME_CHARS:
            raise ValueError("exact named desktop Button requires a 1..160 character accessible name")

        if self.probe_fn is not None:
            observation = self.probe_fn(expected_pid, expected_process, expected_name)
        else:
            if os.name != "nt":
                raise RuntimeError("exact named desktop Button discovery is available only on Windows")
            with self._reader_lock:
                if self._native_reader is None:
                    self._native_reader = _WindowsNamedControlReader()
                reader = self._native_reader
            observation = reader.probe(expected_pid, expected_process, expected_name)

        if not isinstance(observation, NamedAutomationControlObservation):
            raise TypeError("named desktop control probe must return NamedAutomationControlObservation")
        if (
            int(observation.process_id) != expected_pid
            or str(observation.process_name or "").strip().lower() != expected_process.lower()
            or observation.name != expected_name
            or int(observation.control_type) != _UIA_BUTTON_CONTROL_TYPE
            or not observation.runtime_id
            or not observation.is_enabled
            or observation.is_offscreen
            or not 0.0 <= float(observation.center_x_fraction) <= 1.0
            or not 0.0 <= float(observation.center_y_fraction) <= 1.0
        ):
            raise ValueError("named desktop control observation did not match the exact requested Button")
        return observation
