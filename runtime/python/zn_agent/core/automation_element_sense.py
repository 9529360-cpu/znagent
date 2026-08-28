from __future__ import annotations

"""Fresh read-only Windows UI Automation element evidence owned by the resident."""

import os
import queue
import threading
from dataclasses import dataclass
from typing import Callable

from .models import utc_now


_MAX_AUTOMATION_ID_CHARS = 256


@dataclass(frozen=True, slots=True)
class AutomationElementObservation:
    runtime_id: tuple[int, ...]
    process_id: int
    process_name: str
    framework_id: str
    control_type: int
    class_name: str
    is_enabled: bool
    is_keyboard_focusable: bool
    has_keyboard_focus: bool
    is_offscreen: bool
    native_window_handle: int
    captured_at: str
    automation_id: str = ""
    is_password: bool = False
    is_value_pattern_available: bool = False
    is_text_pattern_available: bool = False
    value_is_read_only: bool | None = None
    source: str = "windows-uia-cache"


AutomationPointProbeFn = Callable[[int, int], AutomationElementObservation]
AutomationFocusedProbeFn = Callable[[], AutomationElementObservation]


@dataclass(slots=True)
class _AutomationRequest:
    mode: str
    x: int | None = None
    y: int | None = None
    done: threading.Event | None = None
    result: AutomationElementObservation | None = None
    error: str | None = None


class _WindowsUiAutomationReader:
    """Single lazy MTA worker that returns cached-property-only UIA snapshots."""

    _START_TIMEOUT_SECONDS = 10.0
    _PROBE_TIMEOUT_SECONDS = 6.0
    _CONNECTION_TIMEOUT_MS = 1500
    _TRANSACTION_TIMEOUT_MS = 2500
    _CUIAUTOMATION8_CLSID = "{e22ad333-b25f-460c-83d0-0581107395c9}"

    def __init__(self):
        self._requests: queue.Queue[_AutomationRequest] = queue.Queue(maxsize=1)
        self._started = threading.Event()
        self._failure: str | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="zn-uia-read-sense",
            daemon=True,
        )
        self._thread.start()
        if not self._started.wait(self._START_TIMEOUT_SECONDS):
            self._failure = "Windows UI Automation read worker did not initialize in time"
            raise RuntimeError(self._failure)
        if self._failure:
            raise RuntimeError(self._failure)

    def probe_at_point(self, x: int, y: int) -> AutomationElementObservation:
        return self._submit(_AutomationRequest(mode="point", x=int(x), y=int(y)))

    def probe_focused(self) -> AutomationElementObservation:
        return self._submit(_AutomationRequest(mode="focused"))

    def _submit(self, request: _AutomationRequest) -> AutomationElementObservation:
        if self._failure:
            raise RuntimeError(self._failure)
        request.done = threading.Event()
        try:
            self._requests.put_nowait(request)
        except queue.Full as exc:
            raise RuntimeError("Windows UI Automation read worker is busy") from exc
        if not request.done.wait(self._PROBE_TIMEOUT_SECONDS):
            self._failure = "Windows UI Automation read probe exceeded its bounded timeout"
            raise RuntimeError(self._failure)
        if request.error:
            raise RuntimeError(request.error)
        if request.result is None:
            raise RuntimeError("Windows UI Automation read probe returned no observation")
        return request.result

    def _run(self) -> None:
        try:
            # comtypes initializes COM automatically on the thread that first
            # imports it. Its default is STA, so a fresh UIA worker must select
            # MTA before that first import rather than trying to change the
            # apartment afterward. If another owner already imported comtypes,
            # this new worker still needs its own explicit MTA initialization.
            import sys

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

            # Keep generated type-library wrappers memory-only. This Sense is
            # evidence, not durable product state, and should not need to write
            # generated COM modules into site-packages or a user cache.
            com_client.gen_dir = None
            client = GetModule("UIAutomationCore.dll")

            # CUIAutomation implements only IUIAutomation. The timeout controls
            # belong to IUIAutomation2, whose Windows 8+ coclass is
            # CUIAutomation8. Instantiate that coclass directly instead of
            # creating the older object and asking it for an unsupported
            # interface.
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
                client.UIA_IsTextPatternAvailablePropertyId,
                client.UIA_ValueIsReadOnlyPropertyId,
            ):
                cache.AddProperty(property_id)
        except Exception as exc:
            self._failure = f"Windows UI Automation read worker initialization failed: {type(exc).__name__}: {exc}"
            self._started.set()
            return

        self._started.set()
        while True:
            request = self._requests.get()
            try:
                if request.mode == "focused":
                    element = automation.GetFocusedElementBuildCache(cache)
                elif request.mode == "point":
                    if request.x is None or request.y is None:
                        raise ValueError("point probe requires desktop coordinates")
                    from ctypes import wintypes

                    element = automation.ElementFromPointBuildCache(
                        wintypes.POINT(int(request.x), int(request.y)),
                        cache,
                    )
                else:
                    raise ValueError(f"unknown automation element probe mode: {request.mode}")
                if not element:
                    raise RuntimeError("Windows UI Automation returned no element")
                request.result = self._snapshot(
                    element,
                    runtime_id_property_id=client.UIA_RuntimeIdPropertyId,
                    automation_id_property_id=client.UIA_AutomationIdPropertyId,
                    is_password_property_id=client.UIA_IsPasswordPropertyId,
                    is_value_pattern_available_property_id=client.UIA_IsValuePatternAvailablePropertyId,
                    is_text_pattern_available_property_id=client.UIA_IsTextPatternAvailablePropertyId,
                    value_is_read_only_property_id=client.UIA_ValueIsReadOnlyPropertyId,
                )
            except Exception as exc:
                request.error = f"Windows UI Automation read probe failed: {type(exc).__name__}: {exc}"
            finally:
                if request.done is not None:
                    request.done.set()

    @staticmethod
    def _cached_bool(element, property_id: int, *, field_name: str) -> bool:
        value = element.GetCachedPropertyValue(int(property_id))
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return bool(value)
        raise RuntimeError(f"cached UI Automation {field_name} is not boolean")

    @staticmethod
    def _snapshot(
        element,
        *,
        runtime_id_property_id: int,
        automation_id_property_id: int,
        is_password_property_id: int | None = None,
        is_value_pattern_available_property_id: int | None = None,
        is_text_pattern_available_property_id: int | None = None,
        value_is_read_only_property_id: int | None = None,
    ) -> AutomationElementObservation:
        # RuntimeId, AutomationId and the capability flags are cached UIA
        # properties. Keep AutomationElementMode_None and use only the standard
        # cached-property method; never fall back to current/full reads.
        # Capability evidence intentionally excludes Value.Value and dynamic
        # Name/text so this Sense can classify modern text controls without
        # turning their current user content into a general observation surface.
        runtime_value = element.GetCachedPropertyValue(int(runtime_id_property_id))
        runtime_id = tuple(int(value) for value in runtime_value)
        automation_id = str(
            element.GetCachedPropertyValue(int(automation_id_property_id)) or ""
        ).strip()[:_MAX_AUTOMATION_ID_CHARS]
        is_password = (
            _WindowsUiAutomationReader._cached_bool(
                element,
                int(is_password_property_id),
                field_name="is_password",
            )
            if is_password_property_id is not None
            else False
        )
        is_value_pattern_available = (
            _WindowsUiAutomationReader._cached_bool(
                element,
                int(is_value_pattern_available_property_id),
                field_name="is_value_pattern_available",
            )
            if is_value_pattern_available_property_id is not None
            else False
        )
        is_text_pattern_available = (
            _WindowsUiAutomationReader._cached_bool(
                element,
                int(is_text_pattern_available_property_id),
                field_name="is_text_pattern_available",
            )
            if is_text_pattern_available_property_id is not None
            else False
        )
        value_is_read_only = None
        if is_value_pattern_available and value_is_read_only_property_id is not None:
            value_is_read_only = _WindowsUiAutomationReader._cached_bool(
                element,
                int(value_is_read_only_property_id),
                field_name="value_is_read_only",
            )

        process_id = int(element.CachedProcessId)
        try:
            import psutil

            process_name = str(psutil.Process(process_id).name() or "").strip()
        except Exception as exc:
            raise RuntimeError("automation element process name is unavailable") from exc
        if not process_name:
            raise RuntimeError("automation element process name is unavailable")

        return AutomationElementObservation(
            runtime_id=runtime_id,
            process_id=process_id,
            process_name=process_name,
            framework_id=str(element.CachedFrameworkId or ""),
            control_type=int(element.CachedControlType),
            class_name=str(element.CachedClassName or ""),
            is_enabled=bool(element.CachedIsEnabled),
            is_keyboard_focusable=bool(element.CachedIsKeyboardFocusable),
            has_keyboard_focus=bool(element.CachedHasKeyboardFocus),
            is_offscreen=bool(element.CachedIsOffscreen),
            native_window_handle=int(element.CachedNativeWindowHandle or 0),
            captured_at=utc_now(),
            automation_id=automation_id,
            is_password=is_password,
            is_value_pattern_available=is_value_pattern_available,
            is_text_pattern_available=is_text_pattern_available,
            value_is_read_only=value_is_read_only,
            source="windows-uia-cache",
        )


class NativeAutomationElementSense:
    """Read one UIA element from a point or the current focused UIA element.

    The native reader starts lazily on first use, runs on a separate MTA daemon
    thread, and requests cached properties only. Besides structural identity it
    may report whether the element is a password control and whether the read-only
    UIA Value/Text capabilities are available (plus Value read-only state). It
    never requests Value.Value, dynamic Name/text, a control-pattern object, a
    tree walk, an event subscription or a UIA mutation method. AutomationId and
    capability flags are short-lived
    application evidence; they do not replace opaque RuntimeId inside an action
    cycle and are not durable semantic identity or mutation authority.
    """

    def __init__(
        self,
        *,
        point_probe_fn: AutomationPointProbeFn | None = None,
        focused_probe_fn: AutomationFocusedProbeFn | None = None,
    ):
        self.point_probe_fn = point_probe_fn
        self.focused_probe_fn = focused_probe_fn
        self._native_reader: _WindowsUiAutomationReader | None = None
        self._native_lock = threading.Lock()

    def probe_at_point(self, x: int, y: int) -> AutomationElementObservation:
        if self.point_probe_fn is not None:
            observation = self.point_probe_fn(int(x), int(y))
        else:
            observation = self._reader().probe_at_point(int(x), int(y))
        return self._validate(observation)

    def probe_focused(self) -> AutomationElementObservation:
        if self.focused_probe_fn is not None:
            observation = self.focused_probe_fn()
        else:
            observation = self._reader().probe_focused()
        return self._validate(observation)

    def _reader(self) -> _WindowsUiAutomationReader:
        if os.name != "nt":
            raise RuntimeError("automation element sense is available only on Windows")
        if self._native_reader is None:
            with self._native_lock:
                if self._native_reader is None:
                    self._native_reader = _WindowsUiAutomationReader()
        return self._native_reader

    @staticmethod
    def _validate(observation: AutomationElementObservation) -> AutomationElementObservation:
        if not isinstance(observation, AutomationElementObservation):
            raise TypeError("automation element probe must return AutomationElementObservation")
        if not observation.runtime_id or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in observation.runtime_id
        ):
            raise ValueError("automation element probe returned no opaque integer runtime id")
        if int(observation.process_id) <= 0:
            raise ValueError("automation element probe returned an invalid process id")
        if not str(observation.process_name or "").strip():
            raise ValueError("automation element probe returned no process name")
        if int(observation.control_type) <= 0:
            raise ValueError("automation element probe returned no control type")
        if len(str(observation.automation_id or "")) > _MAX_AUTOMATION_ID_CHARS:
            raise ValueError("automation element probe returned an oversized automation id")
        if not isinstance(observation.is_password, bool):
            raise ValueError("automation element probe returned invalid password capability evidence")
        if not isinstance(observation.is_value_pattern_available, bool):
            raise ValueError("automation element probe returned invalid Value capability evidence")
        if not isinstance(observation.is_text_pattern_available, bool):
            raise ValueError("automation element probe returned invalid Text capability evidence")
        if observation.value_is_read_only is not None and not isinstance(
            observation.value_is_read_only, bool
        ):
            raise ValueError("automation element probe returned invalid Value read-only evidence")
        if (
            not observation.is_value_pattern_available
            and observation.value_is_read_only is not None
        ):
            raise ValueError(
                "automation element probe returned Value read-only evidence without Value capability"
            )
        return observation
