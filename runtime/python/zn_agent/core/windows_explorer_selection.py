from __future__ import annotations

"""Read-only semantic selection sense for the exact foreground File Explorer window.

The Windows shell already owns Explorer selection truth. ZN reads that semantic
state through Shell.Application and binds it to the exact current foreground HWND;
it does not infer selection from pixels, keyboard state or UI Automation focus.

The public observation is transient authority-free evidence. Callers that persist
it must redact ``path`` and ``name`` themselves. This module never mutates Explorer.
"""

import ctypes
import os
import stat as stat_module
import threading
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Iterable, Mapping

from .models import utc_now
from .windows_foreground_companion import (
    NativeWindowsForegroundCompanionSense,
    WindowsForegroundCompanionObservation,
)

SelectionProbe = Callable[[int], Iterable[str]]
StatProbe = Callable[[str], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class WindowsExplorerSelectionObservation:
    platform_supported: bool
    explorer_foreground: bool
    available: bool
    disposition: str
    process_id: int | None
    window_handle: int | None
    selected_count: int
    path: str | None
    name: str | None
    size_bytes: int | None
    mtime_ns: int | None
    device: int | None
    inode: int | None
    observed_at: str
    source: tuple[str, ...]


class NativeWindowsExplorerSelectionSense:
    """Observe one exact local regular file selected in foreground Explorer."""

    def __init__(
        self,
        *,
        foreground_sense: NativeWindowsForegroundCompanionSense | None = None,
        selection_probe: SelectionProbe | None = None,
        stat_probe: StatProbe | None = None,
    ) -> None:
        self._foreground_sense = foreground_sense or NativeWindowsForegroundCompanionSense()
        self._selection_probe = selection_probe or _native_shell_selection_probe
        self._stat_probe = stat_probe or _native_file_stat_probe
        self._native_defaults = selection_probe is None and stat_probe is None

    def probe(self) -> WindowsExplorerSelectionObservation:
        if os.name != "nt" and self._native_defaults:
            return _unavailable(
                platform_supported=False,
                disposition="unsupported_platform",
                source=("unsupported-platform",),
            )

        try:
            foreground = self._foreground_sense.probe()
        except Exception:
            return _unavailable(
                platform_supported=os.name == "nt" or not self._native_defaults,
                disposition="foreground_unavailable",
                source=("foreground-window-unavailable",),
            )
        if not foreground.available or not foreground.window_handle or not foreground.process_id:
            return _from_foreground(
                foreground,
                explorer_foreground=False,
                available=False,
                disposition="foreground_unavailable",
                source=("foreground-window",),
            )

        process_name = str(foreground.process_name or "").strip().casefold()
        if Path(process_name).name != "explorer.exe":
            return _from_foreground(
                foreground,
                explorer_foreground=False,
                available=False,
                disposition="foreground_not_explorer",
                source=("foreground-window",),
            )

        try:
            raw_paths = tuple(str(value or "") for value in self._selection_probe(int(foreground.window_handle)))
        except Exception:
            return _from_foreground(
                foreground,
                explorer_foreground=True,
                available=False,
                disposition="selection_unavailable",
                source=("foreground-window", "shell-application-selected-items"),
            )

        selected_count = len(raw_paths)
        if selected_count == 0:
            return _from_foreground(
                foreground,
                explorer_foreground=True,
                available=False,
                disposition="no_selection",
                selected_count=0,
                source=("foreground-window", "shell-application-selected-items"),
            )
        if selected_count != 1:
            return _from_foreground(
                foreground,
                explorer_foreground=True,
                available=False,
                disposition="multiple_selection",
                selected_count=selected_count,
                source=("foreground-window", "shell-application-selected-items"),
            )

        path = _validated_local_windows_path(raw_paths[0])
        if path is None:
            return _from_foreground(
                foreground,
                explorer_foreground=True,
                available=False,
                disposition="selection_not_local_file_path",
                selected_count=1,
                source=("foreground-window", "shell-application-selected-items"),
            )

        try:
            file_state = self._stat_probe(path)
        except Exception:
            file_state = {}
        if not isinstance(file_state, Mapping) or file_state.get("regular_file") is not True:
            return _from_foreground(
                foreground,
                explorer_foreground=True,
                available=False,
                disposition="selection_not_regular_file",
                selected_count=1,
                source=("foreground-window", "shell-application-selected-items", "file-stat"),
            )

        size_bytes = _nonnegative_int(file_state.get("size_bytes"))
        mtime_ns = _nonnegative_int(file_state.get("mtime_ns"))
        device = _nonnegative_int(file_state.get("device"))
        inode = _nonnegative_int(file_state.get("inode"))
        if size_bytes is None or mtime_ns is None:
            return _from_foreground(
                foreground,
                explorer_foreground=True,
                available=False,
                disposition="file_metadata_unavailable",
                selected_count=1,
                source=("foreground-window", "shell-application-selected-items", "file-stat"),
            )

        return WindowsExplorerSelectionObservation(
            platform_supported=True,
            explorer_foreground=True,
            available=True,
            disposition="selected_local_file",
            process_id=int(foreground.process_id),
            window_handle=int(foreground.window_handle),
            selected_count=1,
            path=path,
            name=PureWindowsPath(path).name,
            size_bytes=size_bytes,
            mtime_ns=mtime_ns,
            device=device,
            inode=inode,
            observed_at=utc_now(),
            source=("foreground-window", "shell-application-selected-items", "file-stat"),
        )


def same_explorer_file_selection(
    first: WindowsExplorerSelectionObservation,
    second: WindowsExplorerSelectionObservation,
) -> bool:
    """Return whether two fresh reads prove the same selected file identity/state."""

    if not first.available or not second.available:
        return False
    return (
        first.process_id == second.process_id
        and first.window_handle == second.window_handle
        and first.selected_count == second.selected_count == 1
        and _windows_path_key(first.path) == _windows_path_key(second.path)
        and first.size_bytes == second.size_bytes
        and first.mtime_ns == second.mtime_ns
        and first.device == second.device
        and first.inode == second.inode
    )


def _from_foreground(
    foreground: WindowsForegroundCompanionObservation,
    *,
    explorer_foreground: bool,
    available: bool,
    disposition: str,
    selected_count: int = 0,
    source: tuple[str, ...],
) -> WindowsExplorerSelectionObservation:
    return WindowsExplorerSelectionObservation(
        platform_supported=bool(foreground.platform_supported),
        explorer_foreground=explorer_foreground,
        available=available,
        disposition=disposition,
        process_id=int(foreground.process_id) if foreground.process_id else None,
        window_handle=int(foreground.window_handle) if foreground.window_handle else None,
        selected_count=max(0, int(selected_count)),
        path=None,
        name=None,
        size_bytes=None,
        mtime_ns=None,
        device=None,
        inode=None,
        observed_at=utc_now(),
        source=source,
    )


def _unavailable(
    *,
    platform_supported: bool,
    disposition: str,
    source: tuple[str, ...],
) -> WindowsExplorerSelectionObservation:
    return WindowsExplorerSelectionObservation(
        platform_supported=platform_supported,
        explorer_foreground=False,
        available=False,
        disposition=disposition,
        process_id=None,
        window_handle=None,
        selected_count=0,
        path=None,
        name=None,
        size_bytes=None,
        mtime_ns=None,
        device=None,
        inode=None,
        observed_at=utc_now(),
        source=source,
    )


def _validated_local_windows_path(raw: str) -> str | None:
    value = str(raw or "").strip()
    if not value or "\x00" in value or len(value) > 32767:
        return None
    normalized = value.replace("/", "\\")
    lowered = normalized.casefold()
    if normalized.startswith("\\\\") or lowered.startswith("\\\\?\\unc\\"):
        return None
    path = PureWindowsPath(normalized)
    if not path.drive or not path.root:
        return None
    return str(path)


def _windows_path_key(value: str | None) -> str | None:
    if not value:
        return None
    return str(PureWindowsPath(value)).replace("/", "\\").casefold()


def _nonnegative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def _native_file_stat_probe(path: str) -> Mapping[str, Any]:
    observed = os.stat(path, follow_symlinks=True)
    return {
        "regular_file": stat_module.S_ISREG(observed.st_mode),
        "size_bytes": int(observed.st_size),
        "mtime_ns": int(observed.st_mtime_ns),
        "device": int(observed.st_dev),
        "inode": int(observed.st_ino),
    }


def _native_shell_selection_probe(hwnd: int) -> tuple[str, ...]:
    """Read SelectedItems from the exact Shell.Application window in a fresh STA."""

    if os.name != "nt" or int(hwnd) <= 0:
        return ()

    result: list[tuple[str, ...]] = []
    errors: list[BaseException] = []

    def worker() -> None:
        initialized = False
        try:
            ole32 = ctypes.OleDLL("ole32")
            ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            ole32.CoInitializeEx.restype = ctypes.c_long
            hr = int(ole32.CoInitializeEx(None, 0x2))  # COINIT_APARTMENTTHREADED
            if hr not in (0, 1):  # S_OK / S_FALSE
                raise OSError(f"CoInitializeEx failed: {hr}")
            initialized = True

            from comtypes.client import CreateObject

            shell = CreateObject("Shell.Application", dynamic=True)
            windows = shell.Windows()
            exact = None
            for index in range(int(windows.Count)):
                candidate = windows.Item(index)
                try:
                    candidate_hwnd = int(candidate.HWND)
                except Exception:
                    continue
                if candidate_hwnd == int(hwnd):
                    if exact is not None:
                        raise RuntimeError("multiple Shell windows matched the exact foreground HWND")
                    exact = candidate
            if exact is None:
                raise RuntimeError("foreground Explorer HWND is not present in Shell.Application")

            selected = exact.Document.SelectedItems()
            paths: list[str] = []
            for index in range(int(selected.Count)):
                item = selected.Item(index)
                value = str(getattr(item, "Path", "") or "").strip()
                if value:
                    paths.append(value)
            result.append(tuple(paths))
        except BaseException as exc:  # confined worker transports the failure
            errors.append(exc)
        finally:
            if initialized:
                try:
                    ctypes.OleDLL("ole32").CoUninitialize()
                except Exception:
                    pass

    thread = threading.Thread(target=worker, name="zn-explorer-selection", daemon=True)
    thread.start()
    thread.join(timeout=2.0)
    if thread.is_alive():
        raise TimeoutError("Shell.Application selection probe timed out")
    if errors:
        raise RuntimeError("Shell.Application selection probe failed") from errors[0]
    return result[0] if result else ()
