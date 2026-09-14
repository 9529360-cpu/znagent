from __future__ import annotations

import ctypes
import os
import runpy
import subprocess
import sys
import time
import uuid
from ctypes import wintypes


class _ForegroundAnchor:
    _WS_EX_TOOLWINDOW = 0x00000080
    _WS_POPUP = 0x80000000
    _WS_VISIBLE = 0x10000000
    _SW_SHOWNOACTIVATE = 4

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("interactive foreground entry requires Windows")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_api()
        self.hwnd = 0

    def _configure_api(self) -> None:
        self._kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self._kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        self._kernel32.GetCurrentThreadId.argtypes = []
        self._kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        self._user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        ]
        self._user32.CreateWindowExW.restype = wintypes.HWND
        self._user32.DestroyWindow.argtypes = [wintypes.HWND]
        self._user32.DestroyWindow.restype = wintypes.BOOL
        self._user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.ShowWindow.restype = wintypes.BOOL
        self._user32.BringWindowToTop.argtypes = [wintypes.HWND]
        self._user32.BringWindowToTop.restype = wintypes.BOOL
        self._user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self._user32.SetForegroundWindow.restype = wintypes.BOOL
        self._user32.GetForegroundWindow.argtypes = []
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self._user32.AttachThreadInput.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.BOOL,
        ]
        self._user32.AttachThreadInput.restype = wintypes.BOOL

    def create(self) -> None:
        instance = self._kernel32.GetModuleHandleW(None)
        title = f"ZN Interactive Python {uuid.uuid4().hex}"
        hwnd = self._user32.CreateWindowExW(
            self._WS_EX_TOOLWINDOW,
            "STATIC",
            title,
            self._WS_POPUP | self._WS_VISIBLE,
            8,
            8,
            32,
            32,
            None,
            None,
            instance,
            None,
        )
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self.hwnd = int(hwnd)

    def close(self) -> None:
        if self.hwnd:
            self._user32.DestroyWindow(self.hwnd)
            self.hwnd = 0

    def _wait_exact(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if int(self._user32.GetForegroundWindow() or 0) == self.hwnd:
                return True
            time.sleep(0.01)
        return int(self._user32.GetForegroundWindow() or 0) == self.hwnd

    def acquire(self) -> str:
        if not self.hwnd:
            raise RuntimeError("interactive foreground anchor has not been created")
        if int(self._user32.GetForegroundWindow() or 0) == self.hwnd:
            return "already-foreground"

        self._user32.ShowWindow(self.hwnd, self._SW_SHOWNOACTIVATE)
        self._user32.BringWindowToTop(self.hwnd)
        self._user32.SetForegroundWindow(self.hwnd)
        if self._wait_exact(0.35):
            return "direct"

        foreground = int(self._user32.GetForegroundWindow() or 0)
        if not foreground:
            raise RuntimeError("interactive Python bootstrap has no current foreground window")
        foreground_pid = wintypes.DWORD()
        foreground_thread = int(
            self._user32.GetWindowThreadProcessId(
                foreground,
                ctypes.byref(foreground_pid),
            )
            or 0
        )
        current_thread = int(self._kernel32.GetCurrentThreadId() or 0)
        if not foreground_thread or foreground_thread == current_thread:
            raise RuntimeError("interactive Python bootstrap cannot identify a distinct foreground thread")

        if not self._user32.AttachThreadInput(current_thread, foreground_thread, True):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            self._user32.BringWindowToTop(self.hwnd)
            self._user32.SetForegroundWindow(self.hwnd)
            if not self._wait_exact(2.0):
                raise RuntimeError("interactive Python anchor could not become exact foreground")
            return "shared-input-bootstrap"
        finally:
            self._user32.AttachThreadInput(current_thread, foreground_thread, False)


def _run_original(args: list[str]) -> None:
    if not args:
        raise RuntimeError("interactive Python entry requires an original Python command")

    if args[0] == "-m":
        if len(args) < 2 or not args[1]:
            raise RuntimeError("interactive Python entry received -m without a module")
        module = args[1]
        sys.argv = [module, *args[2:]]
        runpy.run_module(module, run_name="__main__", alter_sys=True)
        return

    if args[0].startswith("-"):
        raise RuntimeError(f"unsupported interactive Python invocation mode: {args[0]}")

    script = args[0]
    sys.argv = [script, *args[1:]]
    runpy.run_path(script, run_name="__main__")


def _command_executable(args: tuple[object, ...], kwargs: dict[str, object]) -> str:
    explicit = kwargs.get("executable")
    if isinstance(explicit, (str, os.PathLike)):
        return os.fspath(explicit)
    command = kwargs.get("args")
    if command is None and args:
        command = args[0]
    if isinstance(command, (str, os.PathLike)):
        return os.fspath(command)
    if isinstance(command, (list, tuple)) and command:
        first = command[0]
        if isinstance(first, (str, os.PathLike)):
            return os.fspath(first)
    return ""


def _install_foreground_child_guard(anchor: _ForegroundAnchor) -> None:
    original_popen = subprocess.Popen

    class ForegroundAwarePopen(original_popen):
        def __init__(self, *args: object, **kwargs: object) -> None:
            executable = _command_executable(args, kwargs)
            name = os.path.basename(executable).lower()
            if name in {"powershell.exe", "pwsh.exe"}:
                mode = anchor.acquire()
                print(
                    f"interactive_python.child_foreground_mode={mode}",
                    flush=True,
                )
            super().__init__(*args, **kwargs)

    subprocess.Popen = ForegroundAwarePopen


def main() -> None:
    original_args = list(sys.argv[1:])
    anchor = _ForegroundAnchor()
    try:
        anchor.create()
        mode = anchor.acquire()
        print(f"interactive_python.foreground_mode={mode}", flush=True)
        _install_foreground_child_guard(anchor)
        _run_original(original_args)
    finally:
        anchor.close()


if __name__ == "__main__":
    main()
