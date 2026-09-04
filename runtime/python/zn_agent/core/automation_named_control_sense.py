from __future__ import annotations

"""Bounded UIA discovery inside the current foreground desktop app."""

import os
import queue
import threading
from dataclasses import dataclass
from typing import Callable

from .models import utc_now


_UIA_BUTTON_CONTROL_TYPE = 50000
_UIA_EDIT_CONTROL_TYPE = 50004
_MAX_NAME_CHARS = 160
_MAX_CANDIDATES = 24


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
    is_keyboard_focusable: bool = False
    has_keyboard_focus: bool = False
    is_password: bool = False
    is_value_pattern_available: bool = False
    value_is_read_only: bool | None = None
    source: str = "windows-uia-foreground-control"


NamedControlProbeFn = Callable[[int, str, str], NamedAutomationControlObservation]
CandidateControlProbeFn = Callable[
    [int, str, int], tuple[NamedAutomationControlObservation, ...]
]


@dataclass(slots=True)
class _NamedControlRequest:
    process_id: int
    process_name: str
    name: str | None
    control_type: int
    role: str
    collect_candidates: bool = False
    done: threading.Event | None = None
    result: NamedAutomationControlObservation | tuple[NamedAutomationControlObservation, ...] | None = None
    error: str | None = None


class _WindowsNamedControlReader:
    """Lazy MTA UIA worker restricted to the current foreground process."""

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

    def probe(
        self,
        process_id: int,
        process_name: str,
        name: str,
        *,
        control_type: int,
        role: str,
    ) -> NamedAutomationControlObservation:
        result = self._request(
            process_id=process_id,
            process_name=process_name,
            name=name,
            control_type=control_type,
            role=role,
            collect_candidates=False,
        )
        if not isinstance(result, NamedAutomationControlObservation):
            raise RuntimeError("Windows UI Automation exact-name probe returned no observation")
        return result

    def candidates(
        self,
        process_id: int,
        process_name: str,
        *,
        control_type: int,
        role: str,
    ) -> tuple[NamedAutomationControlObservation, ...]:
        result = self._request(
            process_id=process_id,
            process_name=process_name,
            name=None,
            control_type=control_type,
            role=role,
            collect_candidates=True,
        )
        if not isinstance(result, tuple):
            raise RuntimeError("Windows UI Automation candidate probe returned no collection")
        return result

    def _request(
        self,
        *,
        process_id: int,
        process_name: str,
        name: str | None,
        control_type: int,
        role: str,
        collect_candidates: bool,
    ):
        if self._failure:
            raise RuntimeError(self._failure)
        request = _NamedControlRequest(
            process_id=int(process_id),
            process_name=str(process_name),
            name=None if name is None else str(name),
            control_type=int(control_type),
            role=str(role),
            collect_candidates=bool(collect_candidates),
            done=threading.Event(),
        )
        try:
            self._requests.put_nowait(request)
        except queue.Full as exc:
            raise RuntimeError("Windows UI Automation named-control worker is busy") from exc
        assert request.done is not None
        if not request.done.wait(self._PROBE_TIMEOUT_SECONDS):
            self._failure = "Windows UI Automation foreground-control probe exceeded its bounded timeout"
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
            cache.AutomationElementMode = client.AutomationElementMode_None
            cache.TreeScope = client.TreeScope_Element
            for property_id in (
                client.UIA_RuntimeIdPropertyId,
                client.UIA_ProcessIdPropertyId,
                client.UIA_NamePropertyId,
                client.UIA_ControlTypePropertyId,
                client.UIA_ClassNamePropertyId,
                client.UIA_IsEnabledPropertyId,
                client.UIA_IsKeyboardFocusablePropertyId,
                client.UIA_HasKeyboardFocusPropertyId,
                client.UIA_IsOffscreenPropertyId,
                client.UIA_IsPasswordPropertyId,
                client.UIA_IsValuePatternAvailablePropertyId,
                client.UIA_ValueIsReadOnlyPropertyId,
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

                type_condition = automation.CreatePropertyCondition(
                    client.UIA_ControlTypePropertyId,
                    request.control_type,
                )
                process_condition = automation.CreatePropertyCondition(
                    client.UIA_ProcessIdPropertyId,
                    request.process_id,
                )
                condition = automation.CreateAndCondition(type_condition, process_condition)
                if not request.collect_candidates:
                    assert request.name is not None
                    name_condition = automation.CreatePropertyCondition(
                        client.UIA_NamePropertyId,
                        request.name,
                    )
                    condition = automation.CreateAndCondition(condition, name_condition)

                matches = root.FindAllBuildCache(
                    client.TreeScope_Descendants,
                    condition,
                    cache,
                )
                count = int(matches.Length)
                if request.collect_candidates:
                    if count > _MAX_CANDIDATES:
                        raise RuntimeError(
                            "foreground application exposed too many UIA "
                            f"{request.role} candidates for bounded grounding (matches={count})"
                        )
                    candidates: list[NamedAutomationControlObservation] = []
                    for index in range(count):
                        element = matches.GetElement(index)
                        if not element:
                            continue
                        candidate_name = " ".join(
                            str(
                                element.GetCachedPropertyValue(client.UIA_NamePropertyId) or ""
                            ).strip().split()
                        )
                        if not candidate_name or len(candidate_name) > _MAX_NAME_CHARS:
                            continue
                        try:
                            candidate = self._snapshot(
                                element,
                                expected_process_id=request.process_id,
                                expected_process_name=request.process_name,
                                expected_name=candidate_name,
                                expected_control_type=request.control_type,
                                expected_role=request.role,
                                screen_width=screen_width,
                                screen_height=screen_height,
                                runtime_id_property_id=client.UIA_RuntimeIdPropertyId,
                                name_property_id=client.UIA_NamePropertyId,
                                is_password_property_id=client.UIA_IsPasswordPropertyId,
                                is_value_pattern_available_property_id=client.UIA_IsValuePatternAvailablePropertyId,
                                value_is_read_only_property_id=client.UIA_ValueIsReadOnlyPropertyId,
                            )
                        except RuntimeError:
                            continue
                        candidates.append(candidate)
                    request.result = tuple(candidates)
                else:
                    if count != 1:
                        raise RuntimeError(
                            "foreground application did not expose exactly one enabled UIA "
                            f"{request.role} with the exact requested name (matches={count})"
                        )
                    element = matches.GetElement(0)
                    if not element:
                        raise RuntimeError(
                            "Windows UI Automation exact-name collection returned no element"
                        )
                    assert request.name is not None
                    request.result = self._snapshot(
                        element,
                        expected_process_id=request.process_id,
                        expected_process_name=request.process_name,
                        expected_name=request.name,
                        expected_control_type=request.control_type,
                        expected_role=request.role,
                        screen_width=screen_width,
                        screen_height=screen_height,
                        runtime_id_property_id=client.UIA_RuntimeIdPropertyId,
                        name_property_id=client.UIA_NamePropertyId,
                        is_password_property_id=client.UIA_IsPasswordPropertyId,
                        is_value_pattern_available_property_id=client.UIA_IsValuePatternAvailablePropertyId,
                        value_is_read_only_property_id=client.UIA_ValueIsReadOnlyPropertyId,
                    )
            except Exception as exc:
                request.error = (
                    "Windows UI Automation foreground-control probe failed: "
                    f"{type(exc).__name__}: {exc}"
                )
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
            raise RuntimeError("foreground window process changed before UIA discovery")
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
        expected_control_type: int,
        expected_role: str,
        screen_width: int,
        screen_height: int,
        runtime_id_property_id: int,
        name_property_id: int,
        is_password_property_id: int,
        is_value_pattern_available_property_id: int,
        value_is_read_only_property_id: int,
    ) -> NamedAutomationControlObservation:
        runtime_value = element.GetCachedPropertyValue(int(runtime_id_property_id))
        runtime_id = tuple(int(value) for value in runtime_value)
        name = " ".join(
            str(element.GetCachedPropertyValue(int(name_property_id)) or "").strip().split()
        )
        process_id = int(element.CachedProcessId)
        control_type = int(element.CachedControlType)
        is_enabled = bool(element.CachedIsEnabled)
        is_keyboard_focusable = bool(element.CachedIsKeyboardFocusable)
        has_keyboard_focus = bool(element.CachedHasKeyboardFocus)
        is_offscreen = bool(element.CachedIsOffscreen)
        is_password = _WindowsNamedControlReader._cached_bool(
            element,
            is_password_property_id,
            field_name="is_password",
        )
        is_value_pattern_available = _WindowsNamedControlReader._cached_bool(
            element,
            is_value_pattern_available_property_id,
            field_name="is_value_pattern_available",
        )
        value_is_read_only = None
        if is_value_pattern_available:
            value_is_read_only = _WindowsNamedControlReader._cached_bool(
                element,
                value_is_read_only_property_id,
                field_name="value_is_read_only",
            )
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
            or control_type != int(expected_control_type)
            or not runtime_id
            or not is_enabled
            or is_offscreen
            or not (right > left and bottom > top)
        ):
            raise RuntimeError(
                f"UIA {expected_role} failed bounded current-state validation"
            )
        if control_type == _UIA_EDIT_CONTROL_TYPE and (
            not is_keyboard_focusable
            or is_password
            or value_is_read_only is True
        ):
            raise RuntimeError(
                "UIA Edit is not one safe focusable non-password writable target"
            )

        center_x = (left + right) / 2.0
        center_y = (top + bottom) / 2.0
        if not (0 <= center_x < screen_width and 0 <= center_y < screen_height):
            raise RuntimeError(
                f"UIA {expected_role} center is outside the primary desktop"
            )

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
            is_keyboard_focusable=is_keyboard_focusable,
            has_keyboard_focus=has_keyboard_focus,
            is_password=is_password,
            is_value_pattern_available=is_value_pattern_available,
            value_is_read_only=value_is_read_only,
        )


class NativeNamedAutomationControlSense:
    """Observe bounded safe controls in the current foreground app.

    Exact-name discovery remains the fast path used by existing callers. Candidate
    discovery exists only so Resident can ground a semantic user goal in freshly
    observed UIA objects. It is still restricted to the current foreground
    window/process and one explicit control type, returns at most 24 safe named
    controls, never reads text values, and exposes no mutation surface.
    """

    def __init__(
        self,
        *,
        probe_fn: NamedControlProbeFn | None = None,
        edit_probe_fn: NamedControlProbeFn | None = None,
        candidate_probe_fn: CandidateControlProbeFn | None = None,
    ):
        self.probe_fn = probe_fn
        self.edit_probe_fn = edit_probe_fn
        self.candidate_probe_fn = candidate_probe_fn
        self._native_reader: _WindowsNamedControlReader | None = None
        self._reader_lock = threading.Lock()

    def find_unique_button(
        self,
        *,
        process_id: int,
        process_name: str,
        name: str,
    ) -> NamedAutomationControlObservation:
        return self._find_unique(
            process_id=process_id,
            process_name=process_name,
            name=name,
            control_type=_UIA_BUTTON_CONTROL_TYPE,
            role="Button",
            injected=self.probe_fn,
        )

    def find_unique_edit(
        self,
        *,
        process_id: int,
        process_name: str,
        name: str,
    ) -> NamedAutomationControlObservation:
        return self._find_unique(
            process_id=process_id,
            process_name=process_name,
            name=name,
            control_type=_UIA_EDIT_CONTROL_TYPE,
            role="Edit",
            injected=self.edit_probe_fn,
        )

    def list_safe_edits(
        self,
        *,
        process_id: int,
        process_name: str,
    ) -> tuple[NamedAutomationControlObservation, ...]:
        return self._list_candidates(
            process_id=process_id,
            process_name=process_name,
            control_type=_UIA_EDIT_CONTROL_TYPE,
            role="Edit",
        )

    def list_buttons(
        self,
        *,
        process_id: int,
        process_name: str,
    ) -> tuple[NamedAutomationControlObservation, ...]:
        return self._list_candidates(
            process_id=process_id,
            process_name=process_name,
            control_type=_UIA_BUTTON_CONTROL_TYPE,
            role="Button",
        )

    def _list_candidates(
        self,
        *,
        process_id: int,
        process_name: str,
        control_type: int,
        role: str,
    ) -> tuple[NamedAutomationControlObservation, ...]:
        expected_pid = int(process_id)
        expected_process = str(process_name or "").strip()
        if expected_pid <= 0 or not expected_process:
            raise ValueError(
                f"desktop {role} candidate discovery requires current process identity"
            )
        if self.candidate_probe_fn is not None:
            observations = self.candidate_probe_fn(
                expected_pid,
                expected_process,
                int(control_type),
            )
        else:
            reader = self._reader(role)
            observations = reader.candidates(
                expected_pid,
                expected_process,
                control_type=control_type,
                role=role,
            )
        if not isinstance(observations, tuple) or len(observations) > _MAX_CANDIDATES:
            raise ValueError("desktop candidate probe exceeded its bounded collection contract")
        checked: list[NamedAutomationControlObservation] = []
        for observation in observations:
            self._validate_observation(
                observation,
                expected_pid=expected_pid,
                expected_process=expected_process,
                expected_name=None,
                control_type=control_type,
                role=role,
            )
            checked.append(observation)
        return tuple(checked)

    def _find_unique(
        self,
        *,
        process_id: int,
        process_name: str,
        name: str,
        control_type: int,
        role: str,
        injected: NamedControlProbeFn | None,
    ) -> NamedAutomationControlObservation:
        expected_pid = int(process_id)
        expected_process = str(process_name or "").strip()
        expected_name = " ".join(str(name or "").strip().split())
        if expected_pid <= 0 or not expected_process:
            raise ValueError(
                f"exact named desktop {role} discovery requires current process identity"
            )
        if not expected_name or len(expected_name) > _MAX_NAME_CHARS:
            raise ValueError(
                f"exact named desktop {role} requires a 1..160 character accessible name"
            )

        if injected is not None:
            observation = injected(expected_pid, expected_process, expected_name)
        else:
            observation = self._reader(role).probe(
                expected_pid,
                expected_process,
                expected_name,
                control_type=control_type,
                role=role,
            )
        self._validate_observation(
            observation,
            expected_pid=expected_pid,
            expected_process=expected_process,
            expected_name=expected_name,
            control_type=control_type,
            role=role,
        )
        return observation

    def _reader(self, role: str) -> _WindowsNamedControlReader:
        if os.name != "nt":
            raise RuntimeError(
                f"desktop {role} UI Automation discovery is available only on Windows"
            )
        with self._reader_lock:
            if self._native_reader is None:
                self._native_reader = _WindowsNamedControlReader()
            return self._native_reader

    @staticmethod
    def _validate_observation(
        observation,
        *,
        expected_pid: int,
        expected_process: str,
        expected_name: str | None,
        control_type: int,
        role: str,
    ) -> None:
        if not isinstance(observation, NamedAutomationControlObservation):
            raise TypeError(
                "named desktop control probe must return NamedAutomationControlObservation"
            )
        safe_edit = bool(
            control_type != _UIA_EDIT_CONTROL_TYPE
            or (
                observation.is_keyboard_focusable
                and not observation.is_password
                and observation.value_is_read_only is not True
            )
        )
        normalized_name = " ".join(str(observation.name or "").strip().split())
        if (
            int(observation.process_id) != expected_pid
            or str(observation.process_name or "").strip().lower()
            != expected_process.lower()
            or not normalized_name
            or len(normalized_name) > _MAX_NAME_CHARS
            or (expected_name is not None and normalized_name != expected_name)
            or int(observation.control_type) != int(control_type)
            or not observation.runtime_id
            or not observation.is_enabled
            or observation.is_offscreen
            or not safe_edit
            or not 0.0 <= float(observation.center_x_fraction) <= 1.0
            or not 0.0 <= float(observation.center_y_fraction) <= 1.0
        ):
            raise ValueError(
                f"desktop control observation did not match the bounded safe {role} contract"
            )
