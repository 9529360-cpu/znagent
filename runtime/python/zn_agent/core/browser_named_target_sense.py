from __future__ import annotations

"""Privacy-bounded exact semantic target Sense for the user's foreground browser.

The Sense does not attach to a browser profile, read cookies, inspect stored
credentials, walk arbitrary page text, or return the accessible Name of unrelated
controls. It first asks Windows UI Automation for one exact Name + control-type
match under the *current foreground window*. Chromium may not honor Name inside a
server-side UIA property condition for an unfocused DOM control, so a bounded
fallback may enumerate only UIA Edit controls and compare cached Name values
inside the worker. Unrelated names never leave that worker or become resident
evidence. Ambiguous matches fail closed.
"""

import os
import queue
import threading
from dataclasses import dataclass
from typing import Callable

from .models import utc_now

_MAX_TARGET_NAME_CHARS = 256
_MAX_FALLBACK_EDIT_CANDIDATES = 128
_ALLOWED_BROWSER_PROCESSES = frozenset({"chrome.exe", "msedge.exe"})
_UIA_EDIT_CONTROL_TYPE = 50004


@dataclass(frozen=True, slots=True)
class BrowserNamedTargetObservation:
    runtime_id: tuple[int, ...]
    process_id: int
    process_name: str
    foreground_title: str
    framework_id: str
    control_type: int
    class_name: str
    automation_id: str
    is_enabled: bool
    is_keyboard_focusable: bool
    has_keyboard_focus: bool
    is_offscreen: bool
    is_password: bool
    is_value_pattern_available: bool
    value_is_read_only: bool | None
    native_window_handle: int
    center_x_fraction: float
    center_y_fraction: float
    captured_at: str
    source: str = "windows-uia-exact-name"


BrowserNamedTargetProbeFn = Callable[[str, int], BrowserNamedTargetObservation]


@dataclass(slots=True)
class _TargetRequest:
    name: str
    control_type: int
    done: threading.Event | None = None
    result: BrowserNamedTargetObservation | None = None
    error: str | None = None


class _WindowsBrowserNamedTargetReader:
    _START_TIMEOUT_SECONDS = 10.0
    _PROBE_TIMEOUT_SECONDS = 6.0
    _CONNECTION_TIMEOUT_MS = 1500
    _TRANSACTION_TIMEOUT_MS = 2500
    _CUIAUTOMATION8_CLSID = "{e22ad333-b25f-460c-83d0-0581107395c9}"

    def __init__(self) -> None:
        self._requests: queue.Queue[_TargetRequest] = queue.Queue(maxsize=1)
        self._started = threading.Event()
        self._failure: str | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="zn-uia-exact-browser-target",
            daemon=True,
        )
        self._thread.start()
        if not self._started.wait(self._START_TIMEOUT_SECONDS):
            self._failure = "Windows exact browser target reader did not initialize in time"
            raise RuntimeError(self._failure)
        if self._failure:
            raise RuntimeError(self._failure)

    def probe(self, name: str, control_type: int) -> BrowserNamedTargetObservation:
        request = _TargetRequest(name=name, control_type=int(control_type), done=threading.Event())
        try:
            self._requests.put_nowait(request)
        except queue.Full as exc:
            raise RuntimeError("Windows exact browser target reader is busy") from exc
        assert request.done is not None
        if not request.done.wait(self._PROBE_TIMEOUT_SECONDS):
            raise RuntimeError("Windows exact browser target probe exceeded its bounded timeout")
        if request.error:
            raise RuntimeError(request.error)
        if request.result is None:
            raise RuntimeError("Windows exact browser target probe returned no observation")
        return request.result

    def _run(self) -> None:
        comtypes_was_loaded = False
        try:
            import ctypes
            import sys
            from ctypes import wintypes

            comtypes_was_loaded = "comtypes" in sys.modules
            had_coinitialize_flag = hasattr(sys, "coinit_flags")
            previous_coinitialize_flag = getattr(sys, "coinit_flags", None)
            if not comtypes_was_loaded:
                sys.coinit_flags = 0  # COINIT_MULTITHREADED
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
                client.UIA_AutomationIdPropertyId,
                client.UIA_FrameworkIdPropertyId,
                client.UIA_ControlTypePropertyId,
                client.UIA_ClassNamePropertyId,
                client.UIA_IsEnabledPropertyId,
                client.UIA_IsKeyboardFocusablePropertyId,
                client.UIA_HasKeyboardFocusPropertyId,
                client.UIA_IsOffscreenPropertyId,
                client.UIA_NativeWindowHandlePropertyId,
                client.UIA_IsPasswordPropertyId,
                client.UIA_IsValuePatternAvailablePropertyId,
                client.UIA_ValueIsReadOnlyPropertyId,
                client.UIA_BoundingRectanglePropertyId,
            ):
                cache.AddProperty(property_id)

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetForegroundWindow.argtypes = []
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
            user32.GetWindowTextLengthW.restype = ctypes.c_int
            user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user32.GetWindowTextW.restype = ctypes.c_int
            user32.GetSystemMetrics.argtypes = [ctypes.c_int]
            user32.GetSystemMetrics.restype = ctypes.c_int
        except Exception as exc:
            self._failure = (
                "Windows exact browser target reader initialization failed: "
                f"{type(exc).__name__}: {exc}"
            )
            self._started.set()
            return

        self._started.set()
        while True:
            request = self._requests.get()
            try:
                hwnd = user32.GetForegroundWindow()
                if not hwnd:
                    raise RuntimeError("Windows did not report a foreground window")
                title_length = max(0, int(user32.GetWindowTextLengthW(hwnd)))
                title_buffer = ctypes.create_unicode_buffer(max(1, title_length + 1))
                user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
                foreground_title = str(title_buffer.value or "").strip()
                if not foreground_title:
                    raise RuntimeError("foreground browser window has no stable title")

                # The search root remains a short-lived live UIA reference. The
                # returned descendants are Mode_None cache snapshots, so unrelated
                # controls never become live action authorities.
                root = automation.ElementFromHandle(hwnd)
                if not root:
                    raise RuntimeError("Windows UI Automation returned no foreground root element")

                name_condition = automation.CreatePropertyCondition(
                    client.UIA_NamePropertyId,
                    request.name,
                )
                type_condition = automation.CreatePropertyCondition(
                    client.UIA_ControlTypePropertyId,
                    int(request.control_type),
                )
                condition = automation.CreateAndCondition(name_condition, type_condition)
                matches = root.FindAllBuildCache(
                    client.TreeScope_Descendants,
                    condition,
                    cache,
                )
                count = int(matches.Length)
                if count == 1:
                    element = matches.GetElement(0)
                elif count == 0:
                    # Chromium can expose an unfocused DOM Edit while declining
                    # to evaluate its Name in a server-side condition. Fall back
                    # only to Edit candidates. Cached Name is compared transiently
                    # and never copied into the returned observation or any error.
                    edit_matches = root.FindAllBuildCache(
                        client.TreeScope_Descendants,
                        type_condition,
                        cache,
                    )
                    candidate_count = int(edit_matches.Length)
                    if candidate_count > _MAX_FALLBACK_EDIT_CANDIDATES:
                        raise RuntimeError(
                            "foreground browser exposes too many Edit controls for bounded exact-name matching"
                        )
                    element = None
                    exact_count = 0
                    for index in range(candidate_count):
                        candidate = edit_matches.GetElement(index)
                        if not candidate:
                            continue
                        cached_name = str(
                            candidate.GetCachedPropertyValue(client.UIA_NamePropertyId) or ""
                        ).strip()
                        if cached_name != request.name:
                            continue
                        exact_count += 1
                        if exact_count == 1:
                            element = candidate
                    if exact_count != 1:
                        raise RuntimeError(
                            "exact foreground browser target is ambiguous or absent after bounded Edit-only matching: "
                            f"matching_controls={exact_count}"
                        )
                else:
                    raise RuntimeError(
                        "exact foreground browser target is ambiguous: "
                        f"matching_controls={count}"
                    )
                if not element:
                    raise RuntimeError("exact foreground browser target disappeared")

                rect = element.CachedBoundingRectangle
                left, top, right, bottom = self._rectangle_edges(rect)
                screen_width = int(user32.GetSystemMetrics(0))
                screen_height = int(user32.GetSystemMetrics(1))
                if screen_width <= 1 or screen_height <= 1:
                    raise RuntimeError("primary screen dimensions are unavailable")
                center_x = (left + right) / 2.0
                center_y = (top + bottom) / 2.0
                if not (0.0 <= center_x < screen_width and 0.0 <= center_y < screen_height):
                    raise RuntimeError(
                        "exact browser target is outside the primary-screen bounded input scope"
                    )

                request.result = self._snapshot(
                    element,
                    foreground_title=foreground_title,
                    center_x_fraction=center_x / float(screen_width - 1),
                    center_y_fraction=center_y / float(screen_height - 1),
                    runtime_id_property_id=client.UIA_RuntimeIdPropertyId,
                    automation_id_property_id=client.UIA_AutomationIdPropertyId,
                    is_password_property_id=client.UIA_IsPasswordPropertyId,
                    is_value_pattern_available_property_id=(
                        client.UIA_IsValuePatternAvailablePropertyId
                    ),
                    value_is_read_only_property_id=client.UIA_ValueIsReadOnlyPropertyId,
                )
            except Exception as exc:
                request.error = (
                    "Windows exact browser target probe failed: "
                    f"{type(exc).__name__}: {exc}"
                )
            finally:
                if request.done is not None:
                    request.done.set()

    @staticmethod
    def _rectangle_edges(rect) -> tuple[float, float, float, float]:
        if all(hasattr(rect, field) for field in ("left", "top", "right", "bottom")):
            left = float(rect.left)
            top = float(rect.top)
            right = float(rect.right)
            bottom = float(rect.bottom)
        elif isinstance(rect, (tuple, list)) and len(rect) == 4:
            left, top, right, bottom = (float(value) for value in rect)
        else:
            raise RuntimeError("UI Automation target bounding rectangle is unavailable")
        if right <= left or bottom <= top:
            raise RuntimeError("UI Automation target bounding rectangle is empty")
        return left, top, right, bottom

    @staticmethod
    def _cached_bool(element, property_id: int, *, field_name: str) -> bool:
        value = element.GetCachedPropertyValue(int(property_id))
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return bool(value)
        raise RuntimeError(f"cached UI Automation {field_name} is not boolean")

    @classmethod
    def _snapshot(
        cls,
        element,
        *,
        foreground_title: str,
        center_x_fraction: float,
        center_y_fraction: float,
        runtime_id_property_id: int,
        automation_id_property_id: int,
        is_password_property_id: int,
        is_value_pattern_available_property_id: int,
        value_is_read_only_property_id: int,
    ) -> BrowserNamedTargetObservation:
        runtime_value = element.GetCachedPropertyValue(int(runtime_id_property_id))
        runtime_id = tuple(int(value) for value in runtime_value)
        automation_id = str(
            element.GetCachedPropertyValue(int(automation_id_property_id)) or ""
        ).strip()[:256]
        is_password = cls._cached_bool(
            element,
            is_password_property_id,
            field_name="is_password",
        )
        is_value_pattern_available = cls._cached_bool(
            element,
            is_value_pattern_available_property_id,
            field_name="is_value_pattern_available",
        )
        value_is_read_only = None
        if is_value_pattern_available:
            value_is_read_only = cls._cached_bool(
                element,
                value_is_read_only_property_id,
                field_name="value_is_read_only",
            )

        process_id = int(element.CachedProcessId)
        try:
            import psutil

            process_name = str(psutil.Process(process_id).name() or "").strip().lower()
        except Exception as exc:
            raise RuntimeError("exact browser target process name is unavailable") from exc

        return BrowserNamedTargetObservation(
            runtime_id=runtime_id,
            process_id=process_id,
            process_name=process_name,
            foreground_title=foreground_title,
            framework_id=str(element.CachedFrameworkId or ""),
            control_type=int(element.CachedControlType),
            class_name=str(element.CachedClassName or ""),
            automation_id=automation_id,
            is_enabled=bool(element.CachedIsEnabled),
            is_keyboard_focusable=bool(element.CachedIsKeyboardFocusable),
            has_keyboard_focus=bool(element.CachedHasKeyboardFocus),
            is_offscreen=bool(element.CachedIsOffscreen),
            is_password=is_password,
            is_value_pattern_available=is_value_pattern_available,
            value_is_read_only=value_is_read_only,
            native_window_handle=int(element.CachedNativeWindowHandle or 0),
            center_x_fraction=round(float(center_x_fraction), 6),
            center_y_fraction=round(float(center_y_fraction), 6),
            captured_at=utc_now(),
        )


class NativeBrowserNamedTargetSense:
    """Find one exact writable Edit in the current foreground Chrome/Edge window."""

    def __init__(self, *, probe_fn: BrowserNamedTargetProbeFn | None = None) -> None:
        self.probe_fn = probe_fn
        self._reader: _WindowsBrowserNamedTargetReader | None = None
        self._lock = threading.Lock()

    def probe_exact_edit(self, accessible_name: str) -> BrowserNamedTargetObservation:
        name = str(accessible_name or "").strip()
        if not name:
            raise ValueError("exact browser target accessible name must not be empty")
        if len(name) > _MAX_TARGET_NAME_CHARS:
            raise ValueError("exact browser target accessible name exceeds 256 characters")
        if self.probe_fn is not None:
            observation = self.probe_fn(name, _UIA_EDIT_CONTROL_TYPE)
        else:
            observation = self._native_reader().probe(name, _UIA_EDIT_CONTROL_TYPE)
        return self._validate(observation)

    def _native_reader(self) -> _WindowsBrowserNamedTargetReader:
        if os.name != "nt":
            raise RuntimeError("exact browser target Sense is available only on Windows")
        if self._reader is None:
            with self._lock:
                if self._reader is None:
                    self._reader = _WindowsBrowserNamedTargetReader()
        return self._reader

    @staticmethod
    def _validate(observation: BrowserNamedTargetObservation) -> BrowserNamedTargetObservation:
        if not isinstance(observation, BrowserNamedTargetObservation):
            raise TypeError("exact browser target probe must return BrowserNamedTargetObservation")
        if observation.process_name.lower() not in _ALLOWED_BROWSER_PROCESSES:
            raise ValueError("exact browser target is not owned by foreground Chrome or Edge")
        if observation.control_type != _UIA_EDIT_CONTROL_TYPE:
            raise ValueError("exact browser target is not a UI Automation Edit")
        if not observation.runtime_id:
            raise ValueError("exact browser target has no opaque RuntimeId")
        if not observation.foreground_title.strip():
            raise ValueError("exact browser target has no foreground window title")
        if not observation.is_enabled or not observation.is_keyboard_focusable:
            raise ValueError("exact browser target is not enabled and keyboard-focusable")
        if observation.is_offscreen:
            raise ValueError("exact browser target is offscreen")
        if observation.is_password:
            raise ValueError("exact browser target is a password field")
        if not observation.is_value_pattern_available or observation.value_is_read_only is True:
            raise ValueError("exact browser target is not a writable UI Automation value control")
        for value, label in (
            (observation.center_x_fraction, "x"),
            (observation.center_y_fraction, "y"),
        ):
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"exact browser target {label} fraction is outside primary screen")
        return observation
