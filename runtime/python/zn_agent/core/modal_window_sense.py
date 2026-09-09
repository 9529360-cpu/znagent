from __future__ import annotations

"""Bounded Windows modal-window semantics for the current desktop task.

This module is a read-only Sense.  It establishes an exact blocking relationship
from Win32 ownership plus UI Automation WindowPattern state, and scopes candidate
controls to the exact dialog subtree.  It never decides application authority,
never sends input, and never treats a title string as proof of modality.
"""

import os
import queue
import threading
from dataclasses import dataclass
from typing import Callable

from .models import utc_now


_UIA_BUTTON_CONTROL_TYPE = 50000
_UIA_EDIT_CONTROL_TYPE = 50004
_UIA_TEXT_CONTROL_TYPE = 50020
_WINDOW_INTERACTION_READY = 2
_WINDOW_INTERACTION_BLOCKED_BY_MODAL = 3
_MAX_DIALOG_BUTTONS = 12
_MAX_DIALOG_TEXT_ITEMS = 24
_MAX_NAME_CHARS = 240


@dataclass(frozen=True, slots=True)
class ModalButtonObservation:
    runtime_id: tuple[int, ...]
    dialog_hwnd: int
    process_id: int
    name: str
    class_name: str
    is_enabled: bool
    is_offscreen: bool
    center_x_fraction: float
    center_y_fraction: float


@dataclass(frozen=True, slots=True)
class ModalWindowObservation:
    dialog_hwnd: int
    dialog_process_id: int
    dialog_process_name: str
    dialog_title: str
    dialog_class_name: str
    parent_hwnd: int
    parent_process_id: int
    parent_title: str
    owner_hwnd: int
    root_owner_hwnd: int
    is_modal: bool
    dialog_interaction_state: int
    parent_interaction_state: int
    dialog_visible: bool
    dialog_enabled: bool
    contains_password_edit: bool
    text_names: tuple[str, ...]
    buttons: tuple[ModalButtonObservation, ...]
    captured_at: str
    source: str = "windows-uia-win32-modal"


@dataclass(frozen=True, slots=True)
class ParentWindowRecoveryObservation:
    parent_hwnd: int
    parent_process_id: int
    parent_process_name: str
    parent_title: str
    parent_class_name: str
    parent_interaction_state: int
    visible: bool
    enabled: bool
    foreground: bool
    modal_absent: bool
    wait_for_input_idle: bool
    captured_at: str
    source: str = "windows-uia-win32-modal-recovery"


ModalProbeFn = Callable[[int, int, str], ModalWindowObservation | None]
ParentRecoveryProbeFn = Callable[[int, int, str], ParentWindowRecoveryObservation]


@dataclass(slots=True)
class _ModalRequest:
    kind: str
    parent_hwnd: int
    parent_process_id: int
    parent_process_name: str
    done: threading.Event
    result: ModalWindowObservation | ParentWindowRecoveryObservation | None = None
    error: str | None = None


class _WindowsModalReader:
    _START_TIMEOUT_SECONDS = 10.0
    _PROBE_TIMEOUT_SECONDS = 6.0
    _CONNECTION_TIMEOUT_MS = 1500
    _TRANSACTION_TIMEOUT_MS = 2500
    _WAIT_FOR_INPUT_IDLE_MS = 300
    _CUIAUTOMATION8_CLSID = "{e22ad333-b25f-460c-83d0-0581107395c9}"

    def __init__(self) -> None:
        self._requests: queue.Queue[_ModalRequest] = queue.Queue(maxsize=1)
        self._started = threading.Event()
        self._failure: str | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="zn-uia-modal-window-sense",
            daemon=True,
        )
        self._thread.start()
        if not self._started.wait(self._START_TIMEOUT_SECONDS):
            raise RuntimeError("Windows UI Automation modal worker did not initialize in time")
        if self._failure:
            raise RuntimeError(self._failure)

    def modal(
        self,
        parent_hwnd: int,
        parent_process_id: int,
        parent_process_name: str,
    ) -> ModalWindowObservation | None:
        return self._request(
            "modal",
            parent_hwnd,
            parent_process_id,
            parent_process_name,
        )

    def parent_recovery(
        self,
        parent_hwnd: int,
        parent_process_id: int,
        parent_process_name: str,
    ) -> ParentWindowRecoveryObservation:
        result = self._request(
            "parent_recovery",
            parent_hwnd,
            parent_process_id,
            parent_process_name,
        )
        if not isinstance(result, ParentWindowRecoveryObservation):
            raise RuntimeError("Windows modal recovery probe returned no parent observation")
        return result

    def _request(self, kind: str, hwnd: int, pid: int, process_name: str):
        if self._failure:
            raise RuntimeError(self._failure)
        request = _ModalRequest(
            kind=kind,
            parent_hwnd=int(hwnd),
            parent_process_id=int(pid),
            parent_process_name=str(process_name),
            done=threading.Event(),
        )
        try:
            self._requests.put_nowait(request)
        except queue.Full as exc:
            raise RuntimeError("Windows UI Automation modal worker is busy") from exc
        if not request.done.wait(self._PROBE_TIMEOUT_SECONDS):
            self._failure = "Windows UI Automation modal probe exceeded its bounded timeout"
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
        except Exception as exc:
            self._failure = (
                "Windows UI Automation modal worker initialization failed: "
                f"{type(exc).__name__}: {exc}"
            )
            self._started.set()
            return

        self._started.set()
        while True:
            request = self._requests.get()
            try:
                if request.kind == "modal":
                    request.result = self._probe_modal(
                        automation,
                        client,
                        parent_hwnd=request.parent_hwnd,
                        parent_process_id=request.parent_process_id,
                        parent_process_name=request.parent_process_name,
                    )
                elif request.kind == "parent_recovery":
                    request.result = self._probe_parent_recovery(
                        automation,
                        client,
                        parent_hwnd=request.parent_hwnd,
                        parent_process_id=request.parent_process_id,
                        parent_process_name=request.parent_process_name,
                    )
                else:
                    raise RuntimeError("unknown Windows modal Sense request")
            except Exception as exc:
                request.error = f"{type(exc).__name__}: {exc}"
            finally:
                request.done.set()

    @staticmethod
    def _user32():
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetWindow.restype = wintypes.HWND
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetClassNameW.restype = ctypes.c_int
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.IsWindowEnabled.argtypes = [wintypes.HWND]
        user32.IsWindowEnabled.restype = wintypes.BOOL
        return user32

    @staticmethod
    def _window_pid(user32, hwnd: int) -> int:
        import ctypes
        from ctypes import wintypes

        pid = wintypes.DWORD(0)
        thread_id = int(user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)))
        if thread_id <= 0 or int(pid.value) <= 0:
            raise RuntimeError("window process identity is unavailable")
        return int(pid.value)

    @staticmethod
    def _window_text(user32, hwnd: int) -> str:
        import ctypes

        length = max(0, int(user32.GetWindowTextLengthW(hwnd)))
        buffer = ctypes.create_unicode_buffer(max(1, length + 1))
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return str(buffer.value or "")

    @staticmethod
    def _window_class(user32, hwnd: int) -> str:
        import ctypes

        buffer = ctypes.create_unicode_buffer(256)
        length = int(user32.GetClassNameW(hwnd, buffer, len(buffer)))
        return str(buffer.value or "") if length > 0 else ""

    @staticmethod
    def _window_pattern(element, client):
        raw = element.GetCurrentPattern(client.UIA_WindowPatternId)
        if not raw:
            raise RuntimeError("window does not expose UI Automation WindowPattern")
        return raw.QueryInterface(client.IUIAutomationWindowPattern)

    @classmethod
    def _interaction_state(cls, element, client) -> tuple[bool, int, object]:
        pattern = cls._window_pattern(element, client)
        return bool(pattern.CurrentIsModal), int(pattern.CurrentWindowInteractionState), pattern

    @staticmethod
    def _process_name(pid: int) -> str:
        try:
            import psutil

            name = str(psutil.Process(int(pid)).name() or "").strip()
        except Exception as exc:
            raise RuntimeError("window process name is unavailable") from exc
        if not name:
            raise RuntimeError("window process name is unavailable")
        return name

    @classmethod
    def _probe_modal(
        cls,
        automation,
        client,
        *,
        parent_hwnd: int,
        parent_process_id: int,
        parent_process_name: str,
    ) -> ModalWindowObservation | None:
        user32 = cls._user32()
        if not user32.IsWindow(parent_hwnd):
            raise RuntimeError("exact desktop parent HWND no longer exists")
        actual_parent_pid = cls._window_pid(user32, parent_hwnd)
        actual_parent_name = cls._process_name(actual_parent_pid)
        if (
            actual_parent_pid != int(parent_process_id)
            or actual_parent_name.casefold() != str(parent_process_name).strip().casefold()
        ):
            raise RuntimeError("exact desktop parent HWND/PID process identity changed")

        foreground_hwnd = int(user32.GetForegroundWindow() or 0)
        if not foreground_hwnd:
            raise RuntimeError("Windows did not report a foreground window")
        if foreground_hwnd == int(parent_hwnd):
            return None

        dialog_pid = cls._window_pid(user32, foreground_hwnd)
        dialog_name = cls._process_name(dialog_pid)
        if (
            dialog_pid != int(parent_process_id)
            or dialog_name.casefold() != str(parent_process_name).strip().casefold()
        ):
            raise RuntimeError("foreground interruption is not the admitted parent process")

        owner_hwnd = int(user32.GetWindow(foreground_hwnd, 4) or 0)  # GW_OWNER
        root_owner_hwnd = int(user32.GetAncestor(foreground_hwnd, 3) or 0)  # GA_ROOTOWNER
        if owner_hwnd != int(parent_hwnd) or root_owner_hwnd != int(parent_hwnd):
            raise RuntimeError("foreground same-process window is not exact owned/root-owned modal")

        dialog_element = automation.ElementFromHandle(foreground_hwnd)
        parent_element = automation.ElementFromHandle(parent_hwnd)
        if not dialog_element or not parent_element:
            raise RuntimeError("UI Automation could not bind exact modal/parent HWNDs")
        is_modal, dialog_state, _ = cls._interaction_state(dialog_element, client)
        _, parent_state, _ = cls._interaction_state(parent_element, client)
        visible = bool(user32.IsWindowVisible(foreground_hwnd))
        enabled = bool(user32.IsWindowEnabled(foreground_hwnd))
        if not is_modal:
            raise RuntimeError("owned foreground window does not expose IsModal=true")
        if parent_state != _WINDOW_INTERACTION_BLOCKED_BY_MODAL:
            raise RuntimeError("exact parent is not BlockedByModalWindow")
        if not visible or not enabled:
            raise RuntimeError("exact modal is not visible and enabled")

        buttons = cls._dialog_buttons(
            automation,
            client,
            dialog_element,
            dialog_hwnd=foreground_hwnd,
            process_id=dialog_pid,
        )
        text_names, contains_password = cls._dialog_semantics(
            automation,
            client,
            dialog_element,
            process_id=dialog_pid,
        )
        return ModalWindowObservation(
            dialog_hwnd=foreground_hwnd,
            dialog_process_id=dialog_pid,
            dialog_process_name=dialog_name,
            dialog_title=cls._window_text(user32, foreground_hwnd),
            dialog_class_name=cls._window_class(user32, foreground_hwnd),
            parent_hwnd=int(parent_hwnd),
            parent_process_id=actual_parent_pid,
            parent_title=cls._window_text(user32, parent_hwnd),
            owner_hwnd=owner_hwnd,
            root_owner_hwnd=root_owner_hwnd,
            is_modal=True,
            dialog_interaction_state=dialog_state,
            parent_interaction_state=parent_state,
            dialog_visible=visible,
            dialog_enabled=enabled,
            contains_password_edit=contains_password,
            text_names=text_names,
            buttons=buttons,
            captured_at=utc_now(),
        )

    @classmethod
    def _dialog_buttons(
        cls,
        automation,
        client,
        dialog_element,
        *,
        dialog_hwnd: int,
        process_id: int,
    ) -> tuple[ModalButtonObservation, ...]:
        type_condition = automation.CreatePropertyCondition(
            client.UIA_ControlTypePropertyId,
            _UIA_BUTTON_CONTROL_TYPE,
        )
        process_condition = automation.CreatePropertyCondition(
            client.UIA_ProcessIdPropertyId,
            int(process_id),
        )
        condition = automation.CreateAndCondition(type_condition, process_condition)
        matches = dialog_element.FindAll(client.TreeScope_Descendants, condition)
        count = int(matches.Length)
        if count > _MAX_DIALOG_BUTTONS:
            raise RuntimeError("modal exposes too many Button candidates for bounded recovery")

        user32 = cls._user32()
        width = int(user32.GetSystemMetrics(0)) if hasattr(user32, "GetSystemMetrics") else 0
        height = int(user32.GetSystemMetrics(1)) if hasattr(user32, "GetSystemMetrics") else 0
        if width <= 0 or height <= 0:
            import ctypes

            user32.GetSystemMetrics.argtypes = [ctypes.c_int]
            user32.GetSystemMetrics.restype = ctypes.c_int
            width = int(user32.GetSystemMetrics(0))
            height = int(user32.GetSystemMetrics(1))
        if width <= 0 or height <= 0:
            raise RuntimeError("primary desktop dimensions are unavailable")

        buttons: list[ModalButtonObservation] = []
        for index in range(count):
            element = matches.GetElement(index)
            if not element:
                continue
            name = " ".join(str(element.CurrentName or "").strip().split())
            if not name or len(name) > _MAX_NAME_CHARS:
                continue
            runtime_id = tuple(int(value) for value in element.GetRuntimeId())
            rectangle = element.CurrentBoundingRectangle
            left = float(rectangle.left)
            top = float(rectangle.top)
            right = float(rectangle.right)
            bottom = float(rectangle.bottom)
            center_x = (left + right) / 2.0
            center_y = (top + bottom) / 2.0
            if (
                not runtime_id
                or not bool(element.CurrentIsEnabled)
                or bool(element.CurrentIsOffscreen)
                or not (right > left and bottom > top)
                or not (0 <= center_x < width and 0 <= center_y < height)
            ):
                continue
            buttons.append(
                ModalButtonObservation(
                    runtime_id=runtime_id,
                    dialog_hwnd=int(dialog_hwnd),
                    process_id=int(element.CurrentProcessId),
                    name=name,
                    class_name=str(element.CurrentClassName or ""),
                    is_enabled=True,
                    is_offscreen=False,
                    center_x_fraction=round(center_x / float(width), 6),
                    center_y_fraction=round(center_y / float(height), 6),
                )
            )
        return tuple(buttons)

    @classmethod
    def _dialog_semantics(
        cls,
        automation,
        client,
        dialog_element,
        *,
        process_id: int,
    ) -> tuple[tuple[str, ...], bool]:
        all_descendants = dialog_element.FindAll(
            client.TreeScope_Descendants,
            automation.CreatePropertyCondition(client.UIA_ProcessIdPropertyId, int(process_id)),
        )
        names: list[str] = []
        contains_password = False
        count = min(int(all_descendants.Length), 80)
        for index in range(count):
            element = all_descendants.GetElement(index)
            if not element:
                continue
            control_type = int(element.CurrentControlType)
            if control_type == _UIA_EDIT_CONTROL_TYPE:
                try:
                    contains_password = contains_password or bool(
                        element.GetCurrentPropertyValue(client.UIA_IsPasswordPropertyId)
                    )
                except Exception:
                    contains_password = True
            if control_type != _UIA_TEXT_CONTROL_TYPE:
                continue
            name = " ".join(str(element.CurrentName or "").strip().split())
            if name and len(name) <= _MAX_NAME_CHARS and name not in names:
                names.append(name)
                if len(names) >= _MAX_DIALOG_TEXT_ITEMS:
                    break
        return tuple(names), contains_password

    @classmethod
    def _probe_parent_recovery(
        cls,
        automation,
        client,
        *,
        parent_hwnd: int,
        parent_process_id: int,
        parent_process_name: str,
    ) -> ParentWindowRecoveryObservation:
        user32 = cls._user32()
        if not user32.IsWindow(parent_hwnd):
            raise RuntimeError("exact desktop parent HWND disappeared after modal dismiss")
        pid = cls._window_pid(user32, parent_hwnd)
        process_name = cls._process_name(pid)
        if (
            pid != int(parent_process_id)
            or process_name.casefold() != str(parent_process_name).strip().casefold()
        ):
            raise RuntimeError("exact desktop parent HWND/PID changed after modal dismiss")
        element = automation.ElementFromHandle(parent_hwnd)
        if not element:
            raise RuntimeError("UI Automation could not rebind exact parent HWND")
        _, interaction_state, pattern = cls._interaction_state(element, client)
        foreground = int(user32.GetForegroundWindow() or 0) == int(parent_hwnd)
        visible = bool(user32.IsWindowVisible(parent_hwnd))
        enabled = bool(user32.IsWindowEnabled(parent_hwnd))
        try:
            idle = bool(pattern.WaitForInputIdle(cls._WAIT_FOR_INPUT_IDLE_MS))
        except Exception:
            idle = False
        modal_absent = bool(
            foreground
            and interaction_state == _WINDOW_INTERACTION_READY
            and visible
            and enabled
        )
        return ParentWindowRecoveryObservation(
            parent_hwnd=int(parent_hwnd),
            parent_process_id=pid,
            parent_process_name=process_name,
            parent_title=cls._window_text(user32, parent_hwnd),
            parent_class_name=cls._window_class(user32, parent_hwnd),
            parent_interaction_state=interaction_state,
            visible=visible,
            enabled=enabled,
            foreground=foreground,
            modal_absent=modal_absent,
            wait_for_input_idle=idle,
            captured_at=utc_now(),
        )


class NativeModalWindowSense:
    """Prove one exact current blocking modal or one exact recovered parent."""

    def __init__(
        self,
        *,
        probe_fn: ModalProbeFn | None = None,
        parent_recovery_probe_fn: ParentRecoveryProbeFn | None = None,
    ) -> None:
        self.probe_fn = probe_fn
        self.parent_recovery_probe_fn = parent_recovery_probe_fn
        self._reader: _WindowsModalReader | None = None
        self._lock = threading.Lock()

    def probe(
        self,
        *,
        parent_hwnd: int,
        parent_process_id: int,
        parent_process_name: str,
    ) -> ModalWindowObservation | None:
        hwnd, pid, name = self._parent_identity(
            parent_hwnd,
            parent_process_id,
            parent_process_name,
        )
        observation = (
            self.probe_fn(hwnd, pid, name)
            if self.probe_fn is not None
            else self._native_reader().modal(hwnd, pid, name)
        )
        if observation is None:
            return None
        self._validate_modal(observation, hwnd=hwnd, pid=pid, process_name=name)
        return observation

    def probe_parent_recovery(
        self,
        *,
        parent_hwnd: int,
        parent_process_id: int,
        parent_process_name: str,
    ) -> ParentWindowRecoveryObservation:
        hwnd, pid, name = self._parent_identity(
            parent_hwnd,
            parent_process_id,
            parent_process_name,
        )
        observation = (
            self.parent_recovery_probe_fn(hwnd, pid, name)
            if self.parent_recovery_probe_fn is not None
            else self._native_reader().parent_recovery(hwnd, pid, name)
        )
        if not isinstance(observation, ParentWindowRecoveryObservation):
            raise TypeError("parent recovery probe must return ParentWindowRecoveryObservation")
        if (
            int(observation.parent_hwnd) != hwnd
            or int(observation.parent_process_id) != pid
            or str(observation.parent_process_name or "").strip().casefold() != name.casefold()
        ):
            raise ValueError("parent recovery observation changed exact HWND/PID authority")
        return observation

    def _native_reader(self) -> _WindowsModalReader:
        if os.name != "nt":
            raise RuntimeError("Windows modal Sense is available only on Windows")
        with self._lock:
            if self._reader is None:
                self._reader = _WindowsModalReader()
            return self._reader

    @staticmethod
    def _parent_identity(hwnd: int, pid: int, process_name: str) -> tuple[int, int, str]:
        exact_hwnd = int(hwnd)
        exact_pid = int(pid)
        exact_name = str(process_name or "").strip()
        if exact_hwnd <= 0 or exact_pid <= 0 or not exact_name:
            raise ValueError("modal Sense requires exact current parent HWND/PID/process identity")
        return exact_hwnd, exact_pid, exact_name

    @staticmethod
    def _validate_modal(
        observation: ModalWindowObservation,
        *,
        hwnd: int,
        pid: int,
        process_name: str,
    ) -> None:
        if not isinstance(observation, ModalWindowObservation):
            raise TypeError("modal probe must return ModalWindowObservation")
        if (
            int(observation.parent_hwnd) != hwnd
            or int(observation.parent_process_id) != pid
            or int(observation.dialog_hwnd) <= 0
            or int(observation.dialog_hwnd) == hwnd
            or int(observation.dialog_process_id) != pid
            or str(observation.dialog_process_name or "").strip().casefold()
            != process_name.casefold()
            or int(observation.owner_hwnd) != hwnd
            or int(observation.root_owner_hwnd) != hwnd
            or not observation.is_modal
            or int(observation.parent_interaction_state)
            != _WINDOW_INTERACTION_BLOCKED_BY_MODAL
            or not observation.dialog_visible
            or not observation.dialog_enabled
        ):
            raise ValueError("modal observation did not prove one exact blocking parent relationship")
        for button in observation.buttons:
            if (
                int(button.dialog_hwnd) != int(observation.dialog_hwnd)
                or int(button.process_id) != pid
                or not button.runtime_id
                or not str(button.name or "").strip()
                or not button.is_enabled
                or button.is_offscreen
                or not 0.0 <= float(button.center_x_fraction) <= 1.0
                or not 0.0 <= float(button.center_y_fraction) <= 1.0
            ):
                raise ValueError("modal Button escaped the exact dialog containment contract")


def select_safe_modal_action(
    observation: ModalWindowObservation,
    *,
    user_goal: str,
) -> tuple[ModalButtonObservation | None, str | None]:
    """Return one narrowly safe defer/continue action, otherwise fail closed.

    This is deliberately an effect classifier, not a title matcher.  It is only
    used while one desktop goal is already active, rejects credential/data-loss/
    security prompt semantics, and admits exactly one explicit action whose
    effect is to preserve the current work by dismissing/defering the notice.
    """

    goal = " ".join(str(user_goal or "").strip().split())
    if not goal:
        return None, "safe modal classification requires the current user goal"
    if observation.contains_password_edit:
        return None, "modal contains a password/credential input"

    dialog_text = " ".join(
        [observation.dialog_title, *observation.text_names]
    ).casefold()
    blocker_terms = (
        "保存", "不保存", "放弃更改", "丢弃", "删除", "覆盖", "重置", "恢复出厂",
        "密码", "口令", "恢复代码", "验证码", "凭据", "windows 安全", "安全中心",
        "管理员", "权限提升", "付款", "支付", "购买", "另存为", "文件选择",
        "save changes", "don't save", "discard", "delete", "overwrite", "factory reset",
        "password", "recovery code", "credential", "windows security", "administrator",
        "elevation", "payment", "purchase", "file picker",
    )
    if any(term in dialog_text for term in blocker_terms):
        return None, "modal semantics require a user/business/security decision"

    safe_effect_names = {
        "稍后继续": "defer_notice_continue_work",
        "继续工作": "continue_current_work",
        "关闭提示": "dismiss_notice_continue_work",
        "知道了": "acknowledge_notice_continue_work",
        "remind me later": "defer_notice_continue_work",
        "continue working": "continue_current_work",
        "close notice": "dismiss_notice_continue_work",
        "got it": "acknowledge_notice_continue_work",
    }
    risky_action_terms = (
        "立即更新", "立即安装", "现在更新", "现在安装", "重启", "重新启动", "购买",
        "支付", "删除", "覆盖", "重置", "保存", "不保存", "丢弃",
        "update now", "install now", "restart now", "purchase", "pay", "delete",
        "overwrite", "reset", "save", "don't save", "discard",
    )
    candidates: list[ModalButtonObservation] = []
    for button in observation.buttons:
        normalized = " ".join(str(button.name or "").strip().casefold().split())
        if any(term in normalized for term in risky_action_terms):
            continue
        if normalized in safe_effect_names:
            candidates.append(button)
    if len(candidates) != 1:
        return None, (
            "modal does not expose exactly one deterministic defer/continue action "
            f"(eligible={len(candidates)})"
        )
    return candidates[0], None


def modal_action_still_current(
    admitted: ModalWindowObservation,
    admitted_button: ModalButtonObservation,
    fresh: ModalWindowObservation,
    fresh_button: ModalButtonObservation,
) -> bool:
    return bool(
        int(fresh.dialog_hwnd) == int(admitted.dialog_hwnd)
        and int(fresh.parent_hwnd) == int(admitted.parent_hwnd)
        and int(fresh.owner_hwnd) == int(admitted.owner_hwnd)
        and int(fresh.root_owner_hwnd) == int(admitted.root_owner_hwnd)
        and fresh.is_modal
        and int(fresh.parent_interaction_state) == _WINDOW_INTERACTION_BLOCKED_BY_MODAL
        and tuple(fresh_button.runtime_id) == tuple(admitted_button.runtime_id)
        and int(fresh_button.dialog_hwnd) == int(admitted.dialog_hwnd)
        and str(fresh_button.name or "").strip() == str(admitted_button.name or "").strip()
        and abs(float(fresh_button.center_x_fraction) - float(admitted_button.center_x_fraction)) <= 0.002
        and abs(float(fresh_button.center_y_fraction) - float(admitted_button.center_y_fraction)) <= 0.002
    )


WINDOW_INTERACTION_READY = _WINDOW_INTERACTION_READY
WINDOW_INTERACTION_BLOCKED_BY_MODAL = _WINDOW_INTERACTION_BLOCKED_BY_MODAL
