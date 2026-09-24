from __future__ import annotations

"""Bounded semantic Windows UI Automation control actions.

The caller supplies semantic control identity only. Native HWND/PID authority is
admitted by the owning Body immediately before dispatch. Mutations use UIA
control patterns and re-read the exact control afterward; this module never owns
planning, routing, or durable replay policy.
"""

import hashlib
import os
import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .models import utc_now

_MAX_NAME_CHARS = 160
_MAX_AUTOMATION_ID_CHARS = 256
_MAX_VALUE_CHARS = 4096

_CONTROL_TYPES = {
    "button": 50000,
    "checkbox": 50002,
    "combo_box": 50003,
    "edit": 50004,
    "document": 50030,
    "list_item": 50007,
    "menu_item": 50011,
    "radio_button": 50013,
    "tab_item": 50019,
    "tree_item": 50024,
    "data_item": 50029,
}
_CONTROL_TYPE_ALIASES = {
    "check_box": "checkbox",
    "combobox": "combo_box",
    "listitem": "list_item",
    "menuitem": "menu_item",
    "radiobutton": "radio_button",
    "tabitem": "tab_item",
    "treeitem": "tree_item",
    "dataitem": "data_item",
}
_PATTERN_NAMES = frozenset({"value", "text", "toggle", "expand_collapse", "selection_item"})
_TOGGLE_STATES = {0: "off", 1: "on", 2: "indeterminate"}
_EXPAND_STATES = {0: "collapsed", 1: "expanded", 2: "partially_expanded", 3: "leaf_node"}


def text_sha256(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def normalize_control_type(value: object) -> str:
    key = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    key = _CONTROL_TYPE_ALIASES.get(key, key)
    if key not in _CONTROL_TYPES:
        raise ValueError(f"unsupported UI Automation control type: {value}")
    return key


def control_type_id(value: object) -> int:
    return _CONTROL_TYPES[normalize_control_type(value)]


@dataclass(frozen=True, slots=True)
class AutomationControlSelector:
    control_type: str
    name: str = ""
    automation_id: str = ""

    def __post_init__(self) -> None:
        control_type = normalize_control_type(self.control_type)
        name = " ".join(str(self.name or "").strip().split())
        automation_id = str(self.automation_id or "").strip()
        if not name and not automation_id:
            raise ValueError("UI Automation selector requires name or automation_id")
        if len(name) > _MAX_NAME_CHARS:
            raise ValueError(f"UI Automation control name exceeds {_MAX_NAME_CHARS} characters")
        if len(automation_id) > _MAX_AUTOMATION_ID_CHARS:
            raise ValueError(
                f"UI Automation automation_id exceeds {_MAX_AUTOMATION_ID_CHARS} characters"
            )
        object.__setattr__(self, "control_type", control_type)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "automation_id", automation_id)

    @property
    def control_type_id(self) -> int:
        return _CONTROL_TYPES[self.control_type]

    def audit(self) -> dict[str, object]:
        return {
            "control_type": self.control_type,
            "name": self.name,
            "automation_id": self.automation_id,
        }


@dataclass(frozen=True, slots=True)
class AutomationControlObservation:
    process_id: int
    process_name: str
    window_handle: int
    runtime_id: tuple[int, ...]
    selector: AutomationControlSelector
    observed_name: str
    observed_automation_id: str
    class_name: str
    is_enabled: bool
    is_offscreen: bool
    is_password: bool
    supported_patterns: tuple[str, ...]
    pattern: str
    is_keyboard_focusable: bool = False
    has_keyboard_focus: bool = False
    state: Mapping[str, Any] = field(default_factory=dict)
    captured_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        pattern = str(self.pattern or "").strip().lower()
        if pattern not in _PATTERN_NAMES:
            raise ValueError(f"unsupported UI Automation observation pattern: {pattern}")
        object.__setattr__(self, "pattern", pattern)
        object.__setattr__(self, "process_name", str(self.process_name or "").strip().lower())
        object.__setattr__(self, "runtime_id", tuple(int(value) for value in self.runtime_id))
        object.__setattr__(self, "supported_patterns", tuple(dict.fromkeys(self.supported_patterns)))
        object.__setattr__(self, "state", dict(self.state or {}))

    def audit(self) -> dict[str, object]:
        return {
            "process_id": self.process_id,
            "process_name": self.process_name,
            "window_handle": self.window_handle,
            "runtime_id": list(self.runtime_id),
            "selector": self.selector.audit(),
            "observed_name": self.observed_name,
            "observed_automation_id": self.observed_automation_id,
            "class_name": self.class_name,
            "is_enabled": self.is_enabled,
            "is_offscreen": self.is_offscreen,
            "is_password": self.is_password,
            "is_keyboard_focusable": self.is_keyboard_focusable,
            "has_keyboard_focus": self.has_keyboard_focus,
            "supported_patterns": list(self.supported_patterns),
            "pattern": self.pattern,
            "state": dict(self.state),
            "captured_at": self.captured_at,
        }


@dataclass(frozen=True, slots=True)
class AutomationControlMutationResult:
    success: bool
    mutation_dispatched: bool
    postcondition_verified: bool
    before: AutomationControlObservation | None = None
    after: AutomationControlObservation | None = None
    error: str | None = None

    def audit(self) -> dict[str, object]:
        return {
            "success": self.success,
            "mutation_dispatched": self.mutation_dispatched,
            "postcondition_verified": self.postcondition_verified,
            "before": self.before.audit() if self.before is not None else None,
            "after": self.after.audit() if self.after is not None else None,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class AutomationControlFocusResult:
    success: bool
    focus_dispatched: bool
    before: AutomationControlObservation | None = None
    after: AutomationControlObservation | None = None
    error: str | None = None

    def audit(self) -> dict[str, object]:
        return {
            "success": self.success,
            "focus_dispatched": self.focus_dispatched,
            "before": self.before.audit() if self.before is not None else None,
            "after": self.after.audit() if self.after is not None else None,
            "error": self.error,
        }


ControlReadFn = Callable[..., AutomationControlObservation]
ControlMutateFn = Callable[..., AutomationControlMutationResult]
ControlFocusFn = Callable[..., AutomationControlFocusResult]


@dataclass(slots=True)
class _ControlRequest:
    operation: str
    process_id: int
    process_name: str
    window_handle: int
    selector: AutomationControlSelector
    pattern: str
    target: str | None = None
    done: threading.Event | None = None
    result: (
        AutomationControlObservation
        | AutomationControlMutationResult
        | AutomationControlFocusResult
        | None
    ) = None
    error: str | None = None


class _WindowsAutomationControlWorker:
    _START_TIMEOUT_SECONDS = 10.0
    _REQUEST_TIMEOUT_SECONDS = 6.0
    _CONNECTION_TIMEOUT_MS = 1500
    _TRANSACTION_TIMEOUT_MS = 2500
    _CUIAUTOMATION8_CLSID = "{e22ad333-b25f-460c-83d0-0581107395c9}"

    def __init__(self) -> None:
        self._requests: queue.Queue[_ControlRequest] = queue.Queue(maxsize=1)
        self._started = threading.Event()
        self._failure: str | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="zn-uia-control-action",
            daemon=True,
        )
        self._thread.start()
        if not self._started.wait(self._START_TIMEOUT_SECONDS):
            self._failure = "Windows UI Automation control-action worker did not initialize in time"
            raise RuntimeError(self._failure)
        if self._failure:
            raise RuntimeError(self._failure)

    def read(
        self,
        *,
        process_id: int,
        process_name: str,
        window_handle: int,
        selector: AutomationControlSelector,
        pattern: str,
    ) -> AutomationControlObservation:
        result = self._submit(
            _ControlRequest(
                operation="read",
                process_id=int(process_id),
                process_name=str(process_name),
                window_handle=int(window_handle),
                selector=selector,
                pattern=str(pattern),
            )
        )
        if not isinstance(result, AutomationControlObservation):
            raise RuntimeError("UI Automation control read returned no observation")
        return result

    def mutate(
        self,
        *,
        process_id: int,
        process_name: str,
        window_handle: int,
        selector: AutomationControlSelector,
        pattern: str,
        target: str,
    ) -> AutomationControlMutationResult:
        result = self._submit(
            _ControlRequest(
                operation="mutate",
                process_id=int(process_id),
                process_name=str(process_name),
                window_handle=int(window_handle),
                selector=selector,
                pattern=str(pattern),
                target=str(target),
            )
        )
        if not isinstance(result, AutomationControlMutationResult):
            raise RuntimeError("UI Automation control mutation returned no result")
        return result

    def focus(
        self,
        *,
        process_id: int,
        process_name: str,
        window_handle: int,
        selector: AutomationControlSelector,
        pattern: str,
    ) -> AutomationControlFocusResult:
        result = self._submit(
            _ControlRequest(
                operation="focus",
                process_id=int(process_id),
                process_name=str(process_name),
                window_handle=int(window_handle),
                selector=selector,
                pattern=str(pattern),
            )
        )
        if not isinstance(result, AutomationControlFocusResult):
            raise RuntimeError("UI Automation control focus returned no result")
        return result

    def _submit(self, request: _ControlRequest):
        if self._failure:
            raise RuntimeError(self._failure)
        request.done = threading.Event()
        try:
            self._requests.put_nowait(request)
        except queue.Full as exc:
            raise RuntimeError("Windows UI Automation control-action worker is busy") from exc
        if not request.done.wait(self._REQUEST_TIMEOUT_SECONDS):
            self._failure = "Windows UI Automation control action exceeded its bounded timeout"
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
                client.UIA_AutomationIdPropertyId,
                client.UIA_ControlTypePropertyId,
                client.UIA_ClassNamePropertyId,
                client.UIA_IsEnabledPropertyId,
                client.UIA_IsKeyboardFocusablePropertyId,
                client.UIA_HasKeyboardFocusPropertyId,
                client.UIA_IsOffscreenPropertyId,
                client.UIA_IsPasswordPropertyId,
                client.UIA_IsValuePatternAvailablePropertyId,
                client.UIA_IsTextPatternAvailablePropertyId,
                client.UIA_IsTogglePatternAvailablePropertyId,
                client.UIA_IsExpandCollapsePatternAvailablePropertyId,
                client.UIA_IsSelectionItemPatternAvailablePropertyId,
            ):
                cache.AddProperty(property_id)
        except Exception as exc:
            self._failure = (
                "Windows UI Automation control-action worker initialization failed: "
                f"{type(exc).__name__}: {exc}"
            )
            self._started.set()
            return

        self._started.set()
        while True:
            request = self._requests.get()
            try:
                pattern = self._normalize_pattern(request.pattern)
                if request.operation == "read":
                    request.result = self._read(automation, client, cache, request, pattern)
                elif request.operation == "mutate":
                    request.result = self._mutate(automation, client, cache, request, pattern)
                elif request.operation == "focus":
                    request.result = self._focus(automation, client, cache, request, pattern)
                else:
                    raise ValueError(f"unknown UI Automation control operation: {request.operation}")
            except Exception as exc:
                request.error = (
                    "Windows UI Automation control operation failed: "
                    f"{type(exc).__name__}: {exc}"
                )
            finally:
                if request.done is not None:
                    request.done.set()

    @staticmethod
    def _normalize_pattern(value: object) -> str:
        pattern = str(value or "").strip().lower().replace("-", "_")
        if pattern not in _PATTERN_NAMES:
            raise ValueError(f"unsupported UI Automation control pattern: {value}")
        return pattern

    @staticmethod
    def _foreground_process(expected_hwnd: int, expected_pid: int) -> None:
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
        hwnd = int(user32.GetForegroundWindow() or 0)
        if hwnd != int(expected_hwnd):
            raise RuntimeError("foreground HWND changed during UI Automation control action")
        pid = wintypes.DWORD(0)
        thread_id = int(user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)))
        if thread_id <= 0 or int(pid.value) != int(expected_pid):
            raise RuntimeError("foreground process changed during UI Automation control action")

    @classmethod
    def _find_exact(cls, automation, client, cache, request: _ControlRequest):
        cls._foreground_process(request.window_handle, request.process_id)
        root = automation.ElementFromHandle(int(request.window_handle))
        if not root:
            raise RuntimeError("Windows UI Automation could not bind the foreground HWND")
        condition = automation.CreateAndCondition(
            automation.CreatePropertyCondition(
                client.UIA_ControlTypePropertyId,
                request.selector.control_type_id,
            ),
            automation.CreatePropertyCondition(
                client.UIA_ProcessIdPropertyId,
                int(request.process_id),
            ),
        )
        if request.selector.name:
            condition = automation.CreateAndCondition(
                condition,
                automation.CreatePropertyCondition(
                    client.UIA_NamePropertyId,
                    request.selector.name,
                ),
            )
        if request.selector.automation_id:
            condition = automation.CreateAndCondition(
                condition,
                automation.CreatePropertyCondition(
                    client.UIA_AutomationIdPropertyId,
                    request.selector.automation_id,
                ),
            )
        matches = root.FindAllBuildCache(client.TreeScope_Descendants, condition, cache)
        count = int(matches.Length)
        if count != 1:
            raise RuntimeError(
                "foreground application did not expose exactly one UIA control matching the "
                f"selector (matches={count})"
            )
        element = matches.GetElement(0)
        if not element:
            raise RuntimeError("exact UI Automation control disappeared during acquisition")
        return element

    @staticmethod
    def _cached_bool(element, property_id: int, *, field_name: str) -> bool:
        value = element.GetCachedPropertyValue(int(property_id))
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return bool(value)
        raise RuntimeError(f"cached UI Automation {field_name} is not boolean")

    @classmethod
    def _snapshot(cls, element, client, request: _ControlRequest, pattern: str):
        runtime_value = element.GetCachedPropertyValue(client.UIA_RuntimeIdPropertyId)
        runtime_id = tuple(int(value) for value in runtime_value)
        process_id = int(element.CachedProcessId)
        try:
            import psutil

            process_name = str(psutil.Process(process_id).name() or "").strip()
        except Exception as exc:
            raise RuntimeError("UI Automation control process identity is unavailable") from exc
        if process_name.lower() != str(request.process_name or "").strip().lower():
            raise RuntimeError("UI Automation control process name changed before action")
        name = " ".join(
            str(element.GetCachedPropertyValue(client.UIA_NamePropertyId) or "").strip().split()
        )
        automation_id = str(
            element.GetCachedPropertyValue(client.UIA_AutomationIdPropertyId) or ""
        ).strip()
        control_type = int(element.CachedControlType)
        is_enabled = bool(element.CachedIsEnabled)
        is_keyboard_focusable = bool(element.CachedIsKeyboardFocusable)
        has_keyboard_focus = bool(element.CachedHasKeyboardFocus)
        is_offscreen = bool(element.CachedIsOffscreen)
        is_password = cls._cached_bool(
            element,
            client.UIA_IsPasswordPropertyId,
            field_name="is_password",
        )
        pattern_flags = {
            "value": cls._cached_bool(
                element,
                client.UIA_IsValuePatternAvailablePropertyId,
                field_name="is_value_pattern_available",
            ),
            "text": cls._cached_bool(
                element,
                client.UIA_IsTextPatternAvailablePropertyId,
                field_name="is_text_pattern_available",
            ),
            "toggle": cls._cached_bool(
                element,
                client.UIA_IsTogglePatternAvailablePropertyId,
                field_name="is_toggle_pattern_available",
            ),
            "expand_collapse": cls._cached_bool(
                element,
                client.UIA_IsExpandCollapsePatternAvailablePropertyId,
                field_name="is_expand_collapse_pattern_available",
            ),
            "selection_item": cls._cached_bool(
                element,
                client.UIA_IsSelectionItemPatternAvailablePropertyId,
                field_name="is_selection_item_pattern_available",
            ),
        }
        supported_patterns = tuple(key for key, available in pattern_flags.items() if available)
        if (
            process_id != int(request.process_id)
            or control_type != request.selector.control_type_id
            or not runtime_id
            or not is_enabled
            or is_offscreen
            or (request.selector.name and name != request.selector.name)
            or (
                request.selector.automation_id
                and automation_id != request.selector.automation_id
            )
        ):
            raise RuntimeError("UI Automation control failed bounded exact-target validation")
        if pattern not in supported_patterns:
            raise RuntimeError(f"exact UI Automation control does not expose {pattern} pattern")
        if pattern == "value" and is_password:
            raise RuntimeError("UI Automation ValuePattern action refuses password controls")
        return {
            "runtime_id": runtime_id,
            "name": name,
            "automation_id": automation_id,
            "class_name": str(element.CachedClassName or ""),
            "is_enabled": is_enabled,
            "is_offscreen": is_offscreen,
            "is_password": is_password,
            "is_keyboard_focusable": is_keyboard_focusable,
            "has_keyboard_focus": has_keyboard_focus,
            "supported_patterns": supported_patterns,
        }

    @classmethod
    def _state(cls, element, client, pattern: str) -> dict[str, object]:
        if pattern == "value":
            unknown = element.GetCurrentPattern(client.UIA_ValuePatternId)
            if not unknown:
                raise RuntimeError("exact UI Automation control lost ValuePattern")
            interface = unknown.QueryInterface(client.IUIAutomationValuePattern)
            value = interface.CurrentValue
            if value is None:
                value = ""
            if not isinstance(value, str):
                raise RuntimeError("UI Automation ValuePattern current value is not text")
            if len(value) > _MAX_VALUE_CHARS:
                raise RuntimeError(
                    f"UI Automation ValuePattern exceeds {_MAX_VALUE_CHARS} characters"
                )
            return {
                "value_chars": len(value),
                "value_sha256": text_sha256(value),
                "read_only": bool(interface.CurrentIsReadOnly),
            }
        if pattern == "text":
            unknown = element.GetCurrentPattern(client.UIA_TextPatternId)
            if not unknown:
                raise RuntimeError("exact UI Automation control lost TextPattern")
            interface = unknown.QueryInterface(client.IUIAutomationTextPattern)
            document_range = interface.DocumentRange
            if not document_range:
                raise RuntimeError("UI Automation TextPattern returned no document range")
            value = document_range.GetText(_MAX_VALUE_CHARS + 1)
            if value is None:
                value = ""
            if not isinstance(value, str):
                raise RuntimeError("UI Automation TextPattern current text is not text")
            if len(value) > _MAX_VALUE_CHARS:
                raise RuntimeError(
                    f"UI Automation TextPattern exceeds {_MAX_VALUE_CHARS} characters"
                )
            return {
                "text_chars": len(value),
                "text_sha256": text_sha256(value),
            }
        if pattern == "toggle":
            unknown = element.GetCurrentPattern(client.UIA_TogglePatternId)
            if not unknown:
                raise RuntimeError("exact UI Automation control lost TogglePattern")
            interface = unknown.QueryInterface(client.IUIAutomationTogglePattern)
            state = int(interface.CurrentToggleState)
            if state not in _TOGGLE_STATES:
                raise RuntimeError(f"unknown UI Automation toggle state: {state}")
            return {"toggle_state": _TOGGLE_STATES[state]}
        if pattern == "expand_collapse":
            unknown = element.GetCurrentPattern(client.UIA_ExpandCollapsePatternId)
            if not unknown:
                raise RuntimeError("exact UI Automation control lost ExpandCollapsePattern")
            interface = unknown.QueryInterface(client.IUIAutomationExpandCollapsePattern)
            state = int(interface.CurrentExpandCollapseState)
            if state not in _EXPAND_STATES:
                raise RuntimeError(f"unknown UI Automation expand/collapse state: {state}")
            return {"expand_collapse_state": _EXPAND_STATES[state]}
        if pattern == "selection_item":
            unknown = element.GetCurrentPattern(client.UIA_SelectionItemPatternId)
            if not unknown:
                raise RuntimeError("exact UI Automation control lost SelectionItemPattern")
            interface = unknown.QueryInterface(client.IUIAutomationSelectionItemPattern)
            return {"selected": bool(interface.CurrentIsSelected)}
        raise ValueError(f"unsupported UI Automation control pattern: {pattern}")

    @classmethod
    def _observe(cls, element, client, request: _ControlRequest, pattern: str):
        snapshot = cls._snapshot(element, client, request, pattern)
        state = cls._state(element, client, pattern)
        cls._foreground_process(request.window_handle, request.process_id)
        return AutomationControlObservation(
            process_id=request.process_id,
            process_name=request.process_name,
            window_handle=request.window_handle,
            runtime_id=snapshot["runtime_id"],
            selector=request.selector,
            observed_name=snapshot["name"],
            observed_automation_id=snapshot["automation_id"],
            class_name=snapshot["class_name"],
            is_enabled=snapshot["is_enabled"],
            is_offscreen=snapshot["is_offscreen"],
            is_password=snapshot["is_password"],
            supported_patterns=snapshot["supported_patterns"],
            pattern=pattern,
            is_keyboard_focusable=bool(snapshot["is_keyboard_focusable"]),
            has_keyboard_focus=bool(snapshot["has_keyboard_focus"]),
            state=state,
        )

    @classmethod
    def _read(cls, automation, client, cache, request: _ControlRequest, pattern: str):
        first = cls._find_exact(automation, client, cache, request)
        before = cls._observe(first, client, request, pattern)
        second = cls._find_exact(automation, client, cache, request)
        after = cls._observe(second, client, request, pattern)
        if before.runtime_id != after.runtime_id:
            raise RuntimeError("exact UI Automation control RuntimeId changed during read")
        return after

    @classmethod
    def _target_verified(cls, pattern: str, target: str, state: Mapping[str, Any]) -> bool:
        if pattern == "value":
            chars = state.get("value_chars")
            return (
                isinstance(chars, int)
                and chars == len(target)
                and str(state.get("value_sha256") or "") == text_sha256(target)
            )
        if pattern == "text":
            chars = state.get("text_chars")
            return (
                isinstance(chars, int)
                and chars == len(target)
                and str(state.get("text_sha256") or "") == text_sha256(target)
            )
        if pattern == "toggle":
            return str(state.get("toggle_state") or "") == target
        if pattern == "expand_collapse":
            return str(state.get("expand_collapse_state") or "") == target
        if pattern == "selection_item":
            return bool(state.get("selected"))
        return False

    @classmethod
    def _focus(cls, automation, client, cache, request: _ControlRequest, pattern: str):
        dispatched = False
        before: AutomationControlObservation | None = None
        try:
            first = cls._find_exact(automation, client, cache, request)
            before = cls._observe(first, client, request, pattern)
            if before.is_password:
                raise RuntimeError("UI Automation focus refuses password controls")
            if not before.is_enabled or before.is_offscreen:
                raise RuntimeError("UI Automation focus requires one enabled onscreen control")
            if not before.is_keyboard_focusable:
                raise RuntimeError("UI Automation control is not keyboard-focusable")
            if before.has_keyboard_focus:
                return AutomationControlFocusResult(
                    success=True,
                    focus_dispatched=False,
                    before=before,
                    after=before,
                )

            current = cls._find_exact(automation, client, cache, request)
            current_observation = cls._observe(current, client, request, pattern)
            if current_observation.runtime_id != before.runtime_id:
                raise RuntimeError(
                    "exact UI Automation control RuntimeId changed at the final focus boundary"
                )
            dispatched = True
            current.SetFocus()

            post = cls._find_exact(automation, client, cache, request)
            after = cls._observe(post, client, request, pattern)
            if after.runtime_id != before.runtime_id:
                raise RuntimeError("exact UI Automation control RuntimeId changed after focus")
            focused = bool(after.has_keyboard_focus)
            return AutomationControlFocusResult(
                success=focused,
                focus_dispatched=dispatched,
                before=before,
                after=after,
                error=None if focused else "fresh UI Automation evidence did not confirm keyboard focus",
            )
        except Exception as exc:
            return AutomationControlFocusResult(
                success=False,
                focus_dispatched=dispatched,
                before=before,
                after=None,
                error=f"{type(exc).__name__}: {exc}",
            )

    @classmethod
    def _mutate(cls, automation, client, cache, request: _ControlRequest, pattern: str):
        dispatched = False
        before: AutomationControlObservation | None = None
        target = str(request.target or "")
        try:
            if pattern == "text":
                raise ValueError(
                    "UI Automation TextPattern is read-only; use bounded focus plus keyboard input"
                )
            if pattern == "value":
                if len(target) > _MAX_VALUE_CHARS:
                    raise ValueError(
                        f"UI Automation replacement value exceeds {_MAX_VALUE_CHARS} characters"
                    )
            elif pattern == "toggle":
                target = target.strip().lower()
                if target not in {"on", "off"}:
                    raise ValueError("UI Automation toggle target must be on or off")
            elif pattern == "expand_collapse":
                target = target.strip().lower().replace("-", "_")
                if target not in {"expanded", "collapsed"}:
                    raise ValueError(
                        "UI Automation expand/collapse target must be expanded or collapsed"
                    )
            elif pattern == "selection_item":
                target = "selected"

            first = cls._find_exact(automation, client, cache, request)
            before = cls._observe(first, client, request, pattern)
            if cls._target_verified(pattern, target, before.state):
                return AutomationControlMutationResult(
                    success=True,
                    mutation_dispatched=False,
                    postcondition_verified=True,
                    before=before,
                    after=before,
                )
            if pattern == "toggle" and before.state.get("toggle_state") == "indeterminate":
                raise RuntimeError(
                    "UI Automation toggle is indeterminate; refusing an ambiguous one-step mutation"
                )
            if pattern == "expand_collapse" and before.state.get("expand_collapse_state") == "leaf_node":
                raise RuntimeError("UI Automation target is a leaf node and cannot expand/collapse")
            if pattern == "value" and bool(before.state.get("read_only")):
                raise RuntimeError("UI Automation ValuePattern target is read-only")

            current = cls._find_exact(automation, client, cache, request)
            current_observation = cls._observe(current, client, request, pattern)
            if current_observation.runtime_id != before.runtime_id:
                raise RuntimeError(
                    "exact UI Automation control RuntimeId changed at the final mutation boundary"
                )

            if pattern == "value":
                interface = current.GetCurrentPattern(client.UIA_ValuePatternId).QueryInterface(
                    client.IUIAutomationValuePattern
                )
                dispatched = True
                interface.SetValue(target)
            elif pattern == "toggle":
                interface = current.GetCurrentPattern(client.UIA_TogglePatternId).QueryInterface(
                    client.IUIAutomationTogglePattern
                )
                dispatched = True
                interface.Toggle()
            elif pattern == "expand_collapse":
                interface = current.GetCurrentPattern(
                    client.UIA_ExpandCollapsePatternId
                ).QueryInterface(client.IUIAutomationExpandCollapsePattern)
                dispatched = True
                if target == "expanded":
                    interface.Expand()
                else:
                    interface.Collapse()
            elif pattern == "selection_item":
                interface = current.GetCurrentPattern(
                    client.UIA_SelectionItemPatternId
                ).QueryInterface(client.IUIAutomationSelectionItemPattern)
                dispatched = True
                interface.Select()

            post = cls._find_exact(automation, client, cache, request)
            after = cls._observe(post, client, request, pattern)
            if after.runtime_id != before.runtime_id:
                raise RuntimeError("exact UI Automation control RuntimeId changed after mutation")
            verified = cls._target_verified(pattern, target, after.state)
            return AutomationControlMutationResult(
                success=verified,
                mutation_dispatched=dispatched,
                postcondition_verified=verified,
                before=before,
                after=after,
                error=None if verified else "fresh UI Automation readback did not match target state",
            )
        except Exception as exc:
            return AutomationControlMutationResult(
                success=False,
                mutation_dispatched=dispatched,
                postcondition_verified=False,
                before=before,
                after=None,
                error=f"{type(exc).__name__}: {exc}",
            )


class NativeAutomationControlAction:
    """Read or mutate one exact semantic control in the current foreground app."""

    def __init__(
        self,
        *,
        read_fn: ControlReadFn | None = None,
        mutate_fn: ControlMutateFn | None = None,
        focus_fn: ControlFocusFn | None = None,
    ) -> None:
        self.read_fn = read_fn
        self.mutate_fn = mutate_fn
        self.focus_fn = focus_fn
        self._native_worker: _WindowsAutomationControlWorker | None = None
        self._worker_lock = threading.Lock()

    def read(
        self,
        *,
        process_id: int,
        process_name: str,
        window_handle: int,
        selector: AutomationControlSelector,
        pattern: str,
    ) -> AutomationControlObservation:
        self._validate_native_identity(process_id, process_name, window_handle)
        pattern = _WindowsAutomationControlWorker._normalize_pattern(pattern)
        reader = self.read_fn or self._worker().read
        observation = reader(
            process_id=int(process_id),
            process_name=str(process_name),
            window_handle=int(window_handle),
            selector=selector,
            pattern=pattern,
        )
        if not isinstance(observation, AutomationControlObservation):
            raise TypeError("UI Automation read function must return AutomationControlObservation")
        return observation

    def mutate(
        self,
        *,
        process_id: int,
        process_name: str,
        window_handle: int,
        selector: AutomationControlSelector,
        pattern: str,
        target: str,
    ) -> AutomationControlMutationResult:
        self._validate_native_identity(process_id, process_name, window_handle)
        pattern = _WindowsAutomationControlWorker._normalize_pattern(pattern)
        mutator = self.mutate_fn or self._worker().mutate
        result = mutator(
            process_id=int(process_id),
            process_name=str(process_name),
            window_handle=int(window_handle),
            selector=selector,
            pattern=pattern,
            target=str(target),
        )
        if not isinstance(result, AutomationControlMutationResult):
            raise TypeError(
                "UI Automation mutate function must return AutomationControlMutationResult"
            )
        return result

    def focus(
        self,
        *,
        process_id: int,
        process_name: str,
        window_handle: int,
        selector: AutomationControlSelector,
        pattern: str,
    ) -> AutomationControlFocusResult:
        self._validate_native_identity(process_id, process_name, window_handle)
        pattern = _WindowsAutomationControlWorker._normalize_pattern(pattern)
        focus = self.focus_fn or self._worker().focus
        result = focus(
            process_id=int(process_id),
            process_name=str(process_name),
            window_handle=int(window_handle),
            selector=selector,
            pattern=pattern,
        )
        if not isinstance(result, AutomationControlFocusResult):
            raise TypeError(
                "UI Automation focus function must return AutomationControlFocusResult"
            )
        return result

    @staticmethod
    def _validate_native_identity(process_id: int, process_name: str, window_handle: int) -> None:
        if int(process_id) <= 0 or int(window_handle) <= 0 or not str(process_name or "").strip():
            raise ValueError("UI Automation control action requires exact positive HWND/PID identity")

    def _worker(self) -> _WindowsAutomationControlWorker:
        if os.name != "nt":
            raise RuntimeError("UI Automation control actions are available only on Windows")
        with self._worker_lock:
            if self._native_worker is None:
                self._native_worker = _WindowsAutomationControlWorker()
            return self._native_worker
