from __future__ import annotations

"""On-demand exact Windows Explorer selection for the companion substrate.

This Sense is intentionally separate from ``resident_context_snapshot()`` and the
stable companion frame. Explorer selection paths are sensitive user context: they
may be read when a concrete capability needs the user's current selection, but
they are not ambiently persisted or turned into reusable execution authority.

The native provider accepts only the exact foreground File Explorer window. It
matches that foreground HWND against ``Shell.Application.Windows()`` and reads
``Document.SelectedItems()`` from that one view. Background Explorer windows,
the desktop shell, virtual namespace items, oversized selections and malformed
COM evidence fail closed rather than being guessed or partially returned.
"""

import ntpath
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .foreground_window_sense import NativeForegroundWindowSense
from .models import utc_now

ExplorerSelectionProbe = Callable[[int], Mapping[str, Any]]

_MAX_SELECTED_ITEMS = 16
_MAX_PATH_CHARS = 32767
_MAX_NAME_CHARS = 512
_EXPLORER_WINDOW_CLASSES = frozenset({"cabinetwclass", "explorewclass"})


@dataclass(frozen=True, slots=True)
class WindowsExplorerSelectedItem:
    path: str
    name: str
    is_folder: bool

    @property
    def kind(self) -> str:
        return "directory" if self.is_folder else "file"


@dataclass(frozen=True, slots=True)
class WindowsExplorerSelectionObservation:
    platform_supported: bool
    available: bool
    disposition: str
    foreground_process_id: int | None
    foreground_window_handle: int | None
    selected_count: int
    items: tuple[WindowsExplorerSelectedItem, ...]
    observed_at: str
    source: tuple[str, ...]

    @property
    def single_item(self) -> WindowsExplorerSelectedItem | None:
        return self.items[0] if self.available and self.selected_count == 1 else None


class NativeWindowsExplorerSelectionSense:
    """Read filesystem selection from the exact current Explorer window only."""

    def __init__(
        self,
        *,
        foreground_sense: NativeForegroundWindowSense | None = None,
        selection_probe: ExplorerSelectionProbe | None = None,
    ) -> None:
        self._foreground_sense = foreground_sense or NativeForegroundWindowSense()
        self._selection_probe = selection_probe or _native_explorer_selection_probe
        self._native_default = foreground_sense is None and selection_probe is None

    def probe(self) -> WindowsExplorerSelectionObservation:
        if os.name != "nt" and self._native_default:
            return _unavailable(
                platform_supported=False,
                disposition="unsupported_platform",
                source=("unsupported-platform",),
            )

        try:
            foreground = self._foreground_sense.probe()
        except Exception:
            return _unavailable(
                platform_supported=os.name == "nt" or not self._native_default,
                disposition="foreground_unavailable",
                source=("foreground-window-unavailable",),
            )

        hwnd = int(foreground.window_handle or 0)
        process_id = int(foreground.process_id or 0)
        if hwnd <= 0 or process_id <= 0:
            return _unavailable(
                platform_supported=True,
                disposition="foreground_identity_invalid",
                source=("foreground-window-invalid",),
            )

        if str(foreground.process_name or "").strip().casefold() != "explorer.exe":
            return _unavailable(
                platform_supported=True,
                disposition="foreground_not_explorer",
                process_id=process_id,
                window_handle=hwnd,
                source=("foreground-window", "not-explorer"),
            )
        if str(foreground.class_name or "").strip().casefold() not in _EXPLORER_WINDOW_CLASSES:
            return _unavailable(
                platform_supported=True,
                disposition="foreground_not_explorer_view",
                process_id=process_id,
                window_handle=hwnd,
                source=("foreground-window", "unsupported-explorer-window-class"),
            )

        try:
            raw = self._selection_probe(hwnd)
        except Exception:
            raw = {}
        if not isinstance(raw, Mapping):
            raw = {}
        return _selection_observation(
            raw,
            foreground_process_id=process_id,
            foreground_window_handle=hwnd,
        )


def explorer_selection_changed(
    previous: WindowsExplorerSelectionObservation,
    current: WindowsExplorerSelectionObservation,
) -> bool:
    """Compare exact foreground Explorer selection while ignoring observation time."""

    return any(
        (
            previous.available != current.available,
            previous.disposition != current.disposition,
            previous.foreground_process_id != current.foreground_process_id,
            previous.foreground_window_handle != current.foreground_window_handle,
            previous.selected_count != current.selected_count,
            previous.items != current.items,
        )
    )


def _selection_observation(
    raw: Mapping[str, Any],
    *,
    foreground_process_id: int,
    foreground_window_handle: int,
) -> WindowsExplorerSelectionObservation:
    source = _source_tuple(raw.get("source"), "shell-application-selected-items")
    if raw.get("matched_window") is not True:
        return _unavailable(
            platform_supported=True,
            disposition="foreground_shell_window_not_found",
            process_id=foreground_process_id,
            window_handle=foreground_window_handle,
            source=source,
        )

    count = _nonnegative_int(raw.get("selected_count"))
    if count is None:
        return _unavailable(
            platform_supported=True,
            disposition="selection_count_invalid",
            process_id=foreground_process_id,
            window_handle=foreground_window_handle,
            source=source,
        )
    if count > _MAX_SELECTED_ITEMS:
        return _unavailable(
            platform_supported=True,
            disposition="selection_too_large",
            process_id=foreground_process_id,
            window_handle=foreground_window_handle,
            selected_count=count,
            source=source,
        )

    rows = raw.get("items")
    if not isinstance(rows, (tuple, list)) or len(rows) != count:
        return _unavailable(
            platform_supported=True,
            disposition="selection_items_invalid",
            process_id=foreground_process_id,
            window_handle=foreground_window_handle,
            selected_count=count,
            source=source,
        )

    items: list[WindowsExplorerSelectedItem] = []
    seen_paths: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            return _invalid_selected_item(
                "selection_item_invalid",
                process_id=foreground_process_id,
                window_handle=foreground_window_handle,
                selected_count=count,
                source=source,
            )
        if row.get("is_file_system") is not True:
            return _invalid_selected_item(
                "selection_contains_non_filesystem_item",
                process_id=foreground_process_id,
                window_handle=foreground_window_handle,
                selected_count=count,
                source=source,
            )
        is_folder = row.get("is_folder")
        if not isinstance(is_folder, bool):
            return _invalid_selected_item(
                "selection_item_type_invalid",
                process_id=foreground_process_id,
                window_handle=foreground_window_handle,
                selected_count=count,
                source=source,
            )
        path = _bounded_path(row.get("path"))
        if path is None:
            return _invalid_selected_item(
                "selection_item_path_invalid",
                process_id=foreground_process_id,
                window_handle=foreground_window_handle,
                selected_count=count,
                source=source,
            )
        path_key = ntpath.normcase(path)
        if path_key in seen_paths:
            return _invalid_selected_item(
                "selection_contains_duplicate_item",
                process_id=foreground_process_id,
                window_handle=foreground_window_handle,
                selected_count=count,
                source=source,
            )
        seen_paths.add(path_key)

        name = _bounded_name(row.get("name"), path=path)
        if name is None:
            return _invalid_selected_item(
                "selection_item_name_invalid",
                process_id=foreground_process_id,
                window_handle=foreground_window_handle,
                selected_count=count,
                source=source,
            )
        items.append(
            WindowsExplorerSelectedItem(
                path=path,
                name=name,
                is_folder=is_folder,
            )
        )

    return WindowsExplorerSelectionObservation(
        platform_supported=True,
        available=True,
        disposition="no_selection" if count == 0 else "ready",
        foreground_process_id=foreground_process_id,
        foreground_window_handle=foreground_window_handle,
        selected_count=count,
        items=tuple(items),
        observed_at=utc_now(),
        source=source,
    )


def _native_explorer_selection_probe(hwnd: int) -> Mapping[str, Any]:
    if os.name != "nt" or int(hwnd) <= 0:
        return {}

    import comtypes
    from comtypes.client import CreateObject

    initialized = False
    try:
        comtypes.CoInitialize()
        initialized = True
        shell = CreateObject("Shell.Application", dynamic=True)
        windows = shell.Windows()
        count = _nonnegative_int(getattr(windows, "Count", None))
        if count is None:
            return {
                "matched_window": False,
                "source": ("shell-application-windows", "invalid-window-count"),
            }

        matched = None
        matches = 0
        for index in range(min(count, 128)):
            try:
                window = windows.Item(index)
                window_hwnd = int(getattr(window, "HWND", 0) or 0)
            except Exception:
                continue
            if window_hwnd == int(hwnd):
                matched = window
                matches += 1
        if matched is None or matches != 1:
            return {
                "matched_window": False,
                "source": ("shell-application-windows", "exact-hwnd-match"),
            }

        document = matched.Document
        selected = document.SelectedItems()
        selected_count = _nonnegative_int(getattr(selected, "Count", None))
        if selected_count is None:
            return {
                "matched_window": True,
                "selected_count": None,
                "items": (),
                "source": (
                    "shell-application-windows",
                    "shell-folder-view-selected-items",
                ),
            }
        if selected_count > _MAX_SELECTED_ITEMS:
            return {
                "matched_window": True,
                "selected_count": selected_count,
                "items": (),
                "source": (
                    "shell-application-windows",
                    "shell-folder-view-selected-items",
                ),
            }

        items: list[dict[str, Any]] = []
        for index in range(selected_count):
            item = selected.Item(index)
            items.append(
                {
                    "path": str(getattr(item, "Path", "") or ""),
                    "name": str(getattr(item, "Name", "") or ""),
                    "is_file_system": bool(getattr(item, "IsFileSystem", False)),
                    "is_folder": bool(getattr(item, "IsFolder", False)),
                }
            )
        return {
            "matched_window": True,
            "selected_count": selected_count,
            "items": tuple(items),
            "source": (
                "shell-application-windows",
                "shell-folder-view-selected-items",
            ),
        }
    finally:
        if initialized:
            comtypes.CoUninitialize()


def _invalid_selected_item(
    disposition: str,
    *,
    process_id: int,
    window_handle: int,
    selected_count: int,
    source: tuple[str, ...],
) -> WindowsExplorerSelectionObservation:
    return _unavailable(
        platform_supported=True,
        disposition=disposition,
        process_id=process_id,
        window_handle=window_handle,
        selected_count=selected_count,
        source=source,
    )


def _unavailable(
    *,
    platform_supported: bool,
    disposition: str,
    process_id: int | None = None,
    window_handle: int | None = None,
    selected_count: int = 0,
    source: tuple[str, ...],
) -> WindowsExplorerSelectionObservation:
    return WindowsExplorerSelectionObservation(
        platform_supported=platform_supported,
        available=False,
        disposition=disposition,
        foreground_process_id=process_id,
        foreground_window_handle=window_handle,
        selected_count=max(0, int(selected_count)),
        items=(),
        observed_at=utc_now(),
        source=source,
    )


def _bounded_path(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if not value or value != value.strip() or "\x00" in value or len(value) > _MAX_PATH_CHARS:
        return None
    # IsFileSystem is the primary namespace filter. The absolute drive/UNC check
    # additionally rejects virtual parsing names and drive-relative forms such as
    # ``C:relative.txt`` if a malformed provider ever misreports that bit.
    drive, _tail = ntpath.splitdrive(value)
    if not drive or drive.startswith("::") or not ntpath.isabs(value):
        return None
    return value


def _bounded_name(value: Any, *, path: str) -> str | None:
    if isinstance(value, str):
        name = value.strip()
    else:
        name = ""
    if not name:
        name = ntpath.basename(path.rstrip("\\/"))
    if not name or "\x00" in name or len(name) > _MAX_NAME_CHARS:
        return None
    return name


def _nonnegative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def _source_tuple(value: Any, default: str) -> tuple[str, ...]:
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else (default,)
    if isinstance(value, (tuple, list)):
        rows = tuple(str(item).strip() for item in value if str(item).strip())
        return rows or (default,)
    return (default,)
