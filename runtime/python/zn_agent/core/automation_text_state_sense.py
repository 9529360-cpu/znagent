from __future__ import annotations

"""Privacy-safe current text-state evidence for one focused Windows UIA Edit."""

import hashlib
import os
import queue
import threading
from dataclasses import dataclass
from typing import Callable

from .models import utc_now


_MAX_AUTOMATION_ID_CHARS = 256
_MAX_TEXT_CHARS = 4096
_UIA_EDIT_CONTROL_TYPE_ID = 50004


@dataclass(frozen=True, slots=True)
class FocusedAutomationTextObservation:
    runtime_id: tuple[int, ...]
    process_id: int
    process_name: str
    framework_id: str
    control_type: int
    class_name: str
    automation_id: str
    native_window_handle: int
    is_enabled: bool
    is_keyboard_focusable: bool
    has_keyboard_focus: bool
    is_offscreen: bool
    is_password: bool
    is_value_pattern_available: bool
    value_is_read_only: bool
    text_length: int
    text_sha256: str
    captured_at: str
    source: str = "windows-uia-focused-edit-value-digest"


FocusedAutomationTextProbeFn = Callable[[], FocusedAutomationTextObservation]


@dataclass(slots=True)
class _TextStateRequest:
    done: threading.Event | None = None
    result: FocusedAutomationTextObservation | None = None
    error: str | None = None


class _WindowsAutomationTextStateReader:
    """Lazy MTA worker for one guarded focused UIA Value read.

    The worker first captures cached safety/identity properties only. Dynamic
    Value is read only after that snapshot proves an enabled, visible, focused,
    non-password, writable UIA Edit with ValuePattern support. The raw string is
    kept only in the worker stack long enough to bound and hash it. A second
    focused-element capture must identify the same RuntimeId before the digest
    is returned.
    """

    _START_TIMEOUT_SECONDS = 10.0
    _PROBE_TIMEOUT_SECONDS = 6.0
    _CONNECTION_TIMEOUT_MS = 1500
    _TRANSACTION_TIMEOUT_MS = 2500
    _CUIAUTOMATION8_CLSID = "{e22ad333-b25f-460c-83d0-0581107395c9}"

    def __init__(self):
        self._requests: queue.Queue[_TextStateRequest] = queue.Queue(maxsize=1)
        self._started = threading.Event()
        self._failure: str | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="zn-uia-text-state-sense",
            daemon=True,
        )
        self._thread.start()
        if not self._started.wait(self._START_TIMEOUT_SECONDS):
            self._failure = "Windows UI Automation text-state worker did not initialize in time"
            raise RuntimeError(self._failure)
        if self._failure:
            raise RuntimeError(self._failure)

    def probe_focused(self) -> FocusedAutomationTextObservation:
        if self._failure:
            raise RuntimeError(self._failure)
        request = _TextStateRequest(done=threading.Event())
        try:
            self._requests.put_nowait(request)
        except queue.Full as exc:
            raise RuntimeError("Windows UI Automation text-state worker is busy") from exc
        assert request.done is not None
        if not request.done.wait(self._PROBE_TIMEOUT_SECONDS):
            self._failure = "Windows UI Automation text-state probe exceeded its bounded timeout"
            raise RuntimeError(self._failure)
        if request.error:
            raise RuntimeError(request.error)
        if request.result is None:
            raise RuntimeError("Windows UI Automation text-state probe returned no observation")
        return request.result

    def _run(self) -> None:
        try:
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

            com_client.gen_dir = None
            client = GetModule("UIAutomationCore.dll")
            automation = CreateObject(
                self._CUIAUTOMATION8_CLSID,
                interface=client.IUIAutomation2,
            )
            automation.ConnectionTimeout = self._CONNECTION_TIMEOUT_MS
            automation.TransactionTimeout = self._TRANSACTION_TIMEOUT_MS

            cache = automation.CreateCacheRequest()
            # Full mode is deliberate here. Unlike the structural UIA Sense,
            # this separate Sense may perform one guarded current Value read on
            # the exact cached focused element after the safety gate passes.
            cache.AutomationElementMode = client.AutomationElementMode_Full
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
                client.UIA_ValueIsReadOnlyPropertyId,
            ):
                cache.AddProperty(property_id)
        except Exception as exc:
            self._failure = (
                "Windows UI Automation text-state worker initialization failed: "
                f"{type(exc).__name__}: {exc}"
            )
            self._started.set()
            return

        self._started.set()
        while True:
            request = self._requests.get()
            try:
                element = automation.GetFocusedElementBuildCache(cache)
                if not element:
                    raise RuntimeError("Windows UI Automation returned no focused element")
                request.result = self._snapshot(
                    element,
                    recheck_fn=lambda: automation.GetFocusedElementBuildCache(cache),
                    runtime_id_property_id=client.UIA_RuntimeIdPropertyId,
                    automation_id_property_id=client.UIA_AutomationIdPropertyId,
                    is_password_property_id=client.UIA_IsPasswordPropertyId,
                    is_value_pattern_available_property_id=client.UIA_IsValuePatternAvailablePropertyId,
                    value_is_read_only_property_id=client.UIA_ValueIsReadOnlyPropertyId,
                    value_value_property_id=client.UIA_ValueValuePropertyId,
                )
            except Exception as exc:
                request.error = (
                    "Windows UI Automation text-state probe failed: "
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
    def _cached_identity(
        element,
        *,
        runtime_id_property_id: int,
        automation_id_property_id: int,
        is_password_property_id: int,
        is_value_pattern_available_property_id: int,
        value_is_read_only_property_id: int,
    ) -> dict[str, object]:
        runtime_value = element.GetCachedPropertyValue(int(runtime_id_property_id))
        runtime_id = tuple(int(value) for value in runtime_value)
        automation_id = str(
            element.GetCachedPropertyValue(int(automation_id_property_id)) or ""
        ).strip()[:_MAX_AUTOMATION_ID_CHARS]
        is_password = _WindowsAutomationTextStateReader._cached_bool(
            element,
            int(is_password_property_id),
            field_name="is_password",
        )
        is_value_pattern_available = _WindowsAutomationTextStateReader._cached_bool(
            element,
            int(is_value_pattern_available_property_id),
            field_name="is_value_pattern_available",
        )
        value_is_read_only = False
        if is_value_pattern_available:
            value_is_read_only = _WindowsAutomationTextStateReader._cached_bool(
                element,
                int(value_is_read_only_property_id),
                field_name="value_is_read_only",
            )
        return {
            "runtime_id": runtime_id,
            "process_id": int(element.CachedProcessId),
            "framework_id": str(element.CachedFrameworkId or ""),
            "control_type": int(element.CachedControlType),
            "class_name": str(element.CachedClassName or ""),
            "automation_id": automation_id,
            "native_window_handle": int(element.CachedNativeWindowHandle or 0),
            "is_enabled": bool(element.CachedIsEnabled),
            "is_keyboard_focusable": bool(element.CachedIsKeyboardFocusable),
            "has_keyboard_focus": bool(element.CachedHasKeyboardFocus),
            "is_offscreen": bool(element.CachedIsOffscreen),
            "is_password": is_password,
            "is_value_pattern_available": is_value_pattern_available,
            "value_is_read_only": value_is_read_only,
        }

    @staticmethod
    def _require_safe_edit(identity: dict[str, object]) -> None:
        runtime_id = identity.get("runtime_id")
        if not isinstance(runtime_id, tuple) or not runtime_id:
            raise RuntimeError("focused UI Automation text target has no RuntimeId")
        if int(identity.get("process_id") or 0) <= 0:
            raise RuntimeError("focused UI Automation text target has no process identity")
        if int(identity.get("control_type") or 0) != _UIA_EDIT_CONTROL_TYPE_ID:
            raise RuntimeError("focused UI Automation text-state Sense is limited to Edit controls")
        if not bool(identity.get("is_enabled")):
            raise RuntimeError("focused UI Automation text target is disabled")
        if not bool(identity.get("is_keyboard_focusable")) or not bool(
            identity.get("has_keyboard_focus")
        ):
            raise RuntimeError("focused UI Automation text target does not own keyboard focus")
        if bool(identity.get("is_offscreen")):
            raise RuntimeError("focused UI Automation text target is offscreen")
        if bool(identity.get("is_password")):
            raise RuntimeError("focused UI Automation text-state Sense refuses password controls")
        if not bool(identity.get("is_value_pattern_available")):
            raise RuntimeError("focused UI Automation Edit does not expose ValuePattern")
        if bool(identity.get("value_is_read_only")):
            raise RuntimeError("focused UI Automation text-state Sense refuses read-only controls")

    @staticmethod
    def _snapshot(
        element,
        *,
        recheck_fn,
        runtime_id_property_id: int,
        automation_id_property_id: int,
        is_password_property_id: int,
        is_value_pattern_available_property_id: int,
        value_is_read_only_property_id: int,
        value_value_property_id: int,
    ) -> FocusedAutomationTextObservation:
        pre = _WindowsAutomationTextStateReader._cached_identity(
            element,
            runtime_id_property_id=runtime_id_property_id,
            automation_id_property_id=automation_id_property_id,
            is_password_property_id=is_password_property_id,
            is_value_pattern_available_property_id=is_value_pattern_available_property_id,
            value_is_read_only_property_id=value_is_read_only_property_id,
        )
        _WindowsAutomationTextStateReader._require_safe_edit(pre)

        # This is the only dynamic text read in the Sense. It happens after the
        # password/capability/read-only/focus gate and is reduced immediately to
        # bounded length + SHA-256. No raw content leaves this stack frame.
        raw_value = element.GetCurrentPropertyValue(int(value_value_property_id))
        if raw_value is None:
            text = ""
        elif isinstance(raw_value, str):
            text = raw_value
        else:
            raise RuntimeError("focused UI Automation Value is not a string")
        if len(text) > _MAX_TEXT_CHARS:
            raise RuntimeError(
                f"focused UI Automation text exceeds the {_MAX_TEXT_CHARS}-character evidence bound"
            )
        text_length = len(text)
        text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()

        post_element = recheck_fn()
        if not post_element:
            raise RuntimeError("focused UI Automation text target disappeared after Value read")
        post = _WindowsAutomationTextStateReader._cached_identity(
            post_element,
            runtime_id_property_id=runtime_id_property_id,
            automation_id_property_id=automation_id_property_id,
            is_password_property_id=is_password_property_id,
            is_value_pattern_available_property_id=is_value_pattern_available_property_id,
            value_is_read_only_property_id=value_is_read_only_property_id,
        )
        _WindowsAutomationTextStateReader._require_safe_edit(post)
        if tuple(post["runtime_id"]) != tuple(pre["runtime_id"]):
            raise RuntimeError("focused UI Automation RuntimeId changed during text-state read")
        if int(post["process_id"]) != int(pre["process_id"]):
            raise RuntimeError("focused UI Automation process changed during text-state read")

        process_id = int(post["process_id"])
        try:
            import psutil

            process_name = str(psutil.Process(process_id).name() or "").strip()
        except Exception as exc:
            raise RuntimeError("focused UI Automation text process name is unavailable") from exc
        if not process_name:
            raise RuntimeError("focused UI Automation text process name is unavailable")

        return FocusedAutomationTextObservation(
            runtime_id=tuple(int(value) for value in post["runtime_id"]),
            process_id=process_id,
            process_name=process_name,
            framework_id=str(post["framework_id"]),
            control_type=int(post["control_type"]),
            class_name=str(post["class_name"]),
            automation_id=str(post["automation_id"]),
            native_window_handle=int(post["native_window_handle"]),
            is_enabled=bool(post["is_enabled"]),
            is_keyboard_focusable=bool(post["is_keyboard_focusable"]),
            has_keyboard_focus=bool(post["has_keyboard_focus"]),
            is_offscreen=bool(post["is_offscreen"]),
            is_password=bool(post["is_password"]),
            is_value_pattern_available=bool(post["is_value_pattern_available"]),
            value_is_read_only=bool(post["value_is_read_only"]),
            text_length=text_length,
            text_sha256=text_sha256,
            captured_at=utc_now(),
            source="windows-uia-focused-edit-value-digest",
        )


class NativeFocusedAutomationTextSense:
    """Read privacy-safe current state for one focused writable UIA Edit.

    This Sense is separate from ``NativeAutomationElementSense`` so the normal
    structural UIA observation remains cached-property-only. It refuses password,
    read-only, disabled, offscreen, unfocused and non-Edit targets. Dynamic Value
    is read transiently only after those guards pass; callers receive only target
    identity plus text length and SHA-256. The Sense has no mutation method and
    does not make its evidence execution authority by itself.
    """

    def __init__(self, *, probe_fn: FocusedAutomationTextProbeFn | None = None):
        self.probe_fn = probe_fn
        self._native_reader: _WindowsAutomationTextStateReader | None = None
        self._native_lock = threading.Lock()

    def probe(self) -> FocusedAutomationTextObservation:
        if self.probe_fn is not None:
            observation = self.probe_fn()
        else:
            observation = self._reader().probe_focused()
        return self._validate(observation)

    def _reader(self) -> _WindowsAutomationTextStateReader:
        if os.name != "nt":
            raise RuntimeError("focused UI Automation text-state Sense is available only on Windows")
        if self._native_reader is None:
            with self._native_lock:
                if self._native_reader is None:
                    self._native_reader = _WindowsAutomationTextStateReader()
        return self._native_reader

    @staticmethod
    def digest_text(text: str) -> str:
        return hashlib.sha256(str(text).encode("utf-8")).hexdigest()

    @staticmethod
    def _validate(
        observation: FocusedAutomationTextObservation,
    ) -> FocusedAutomationTextObservation:
        if not isinstance(observation, FocusedAutomationTextObservation):
            raise TypeError(
                "focused UI Automation text probe must return FocusedAutomationTextObservation"
            )
        if not observation.runtime_id or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in observation.runtime_id
        ):
            raise ValueError("focused UI Automation text probe returned no opaque RuntimeId")
        if int(observation.process_id) <= 0:
            raise ValueError("focused UI Automation text probe returned an invalid process id")
        if not str(observation.process_name or "").strip():
            raise ValueError("focused UI Automation text probe returned no process name")
        if int(observation.control_type) != _UIA_EDIT_CONTROL_TYPE_ID:
            raise ValueError("focused UI Automation text probe is limited to Edit controls")
        if len(str(observation.automation_id or "")) > _MAX_AUTOMATION_ID_CHARS:
            raise ValueError("focused UI Automation text probe returned an oversized AutomationId")
        if not observation.is_enabled or not observation.is_keyboard_focusable:
            raise ValueError("focused UI Automation text probe requires an enabled focusable Edit")
        if not observation.has_keyboard_focus or observation.is_offscreen:
            raise ValueError("focused UI Automation text probe requires a focused onscreen Edit")
        if observation.is_password:
            raise ValueError("focused UI Automation text probe refuses password controls")
        if not observation.is_value_pattern_available:
            raise ValueError("focused UI Automation text probe requires ValuePattern")
        if observation.value_is_read_only:
            raise ValueError("focused UI Automation text probe refuses read-only controls")
        if not 0 <= int(observation.text_length) <= _MAX_TEXT_CHARS:
            raise ValueError("focused UI Automation text probe returned an invalid text length")
        digest = str(observation.text_sha256 or "").strip().lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("focused UI Automation text probe returned an invalid SHA-256 digest")
        return observation
