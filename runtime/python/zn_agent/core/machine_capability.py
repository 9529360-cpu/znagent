from __future__ import annotations

"""Deterministic Windows machine/application awareness owned by ZN's Body/Senses.

This module deliberately contains no model calls, agent lifecycle, router, planner,
or new persistence universe.  Installed software may be cached for a bounded TTL;
processes, top-level windows and foreground state are always observed fresh.
"""

import ctypes
import hashlib
import json
import os
import platform
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Sequence

import psutil

from .models import utc_now

ResolutionStatus = Literal["resolved", "ambiguous", "not_installed"]
LaunchKind = Literal["executable", "shell_item", "aumid", "unavailable"]


@dataclass(frozen=True, slots=True)
class ApplicationInventoryCandidate:
    source: str
    source_id: str
    display_name: str
    executable_path: str | None = None
    identity_paths: tuple[str, ...] = ()
    package_identity: str | None = None
    aumid: str | None = None
    version: str | None = None
    publisher: str | None = None
    install_location: str | None = None
    launch_kind: LaunchKind = "unavailable"
    launch_target: str | None = None
    observed_at: str = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class InstalledApplication:
    app_id: str
    display_name: str
    canonical_name: str
    executable_path: str | None
    package_identity: str | None
    aumid: str | None
    version: str | None
    publisher: str | None
    launch_kind: LaunchKind
    launch_target: str | None
    capabilities: tuple[str, ...]
    observed_at: str
    evidence_source: tuple[str, ...]

    @property
    def launchable(self) -> bool:
        return self.launch_kind != "unavailable" and bool(self.launch_target)


@dataclass(frozen=True, slots=True)
class ApplicationResolution:
    query: str
    status: ResolutionStatus
    application: InstalledApplication | None = None
    candidates: tuple[InstalledApplication, ...] = ()


@dataclass(frozen=True, slots=True)
class RunningProcessObservation:
    process_id: int
    process_name: str
    executable_path: str | None
    aumid: str | None
    package_identity: str | None
    created_at_epoch: float | None
    resolved_app_id: str | None
    observed_at: str
    source: str = "windows-process"


@dataclass(frozen=True, slots=True)
class ApplicationWindowObservation:
    hwnd: int
    process_id: int
    title: str
    class_name: str
    visible: bool
    foreground: bool
    resolved_app_id: str | None
    observed_at: str
    source: str = "windows-user32"


@dataclass(frozen=True, slots=True)
class ForegroundApplicationObservation:
    window: ApplicationWindowObservation
    process: RunningProcessObservation | None
    application: InstalledApplication | None
    observed_at: str


@dataclass(frozen=True, slots=True)
class AssociationObservation:
    association: str
    executable_path: str | None
    friendly_application_name: str | None
    resolved_app_id: str | None
    observed_at: str
    source: str = "windows-assoc-query"


@dataclass(frozen=True, slots=True)
class GpuObservation:
    name: str
    pnp_device_id: str | None
    observed_at: str
    source: str = "windows-wmi"


@dataclass(frozen=True, slots=True)
class MachineHardwareObservation:
    operating_system: str
    os_release: str
    os_version: str
    architecture: str
    logical_processors: int | None
    physical_processors: int | None
    ram_total_bytes: int
    ram_available_bytes: int
    storage_root: str
    storage_total_bytes: int
    storage_free_bytes: int
    gpus: tuple[GpuObservation, ...]
    observed_at: str
    source: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeviceCapabilitySnapshot:
    applications: tuple[InstalledApplication, ...]
    running_processes: tuple[RunningProcessObservation, ...]
    windows: tuple[ApplicationWindowObservation, ...]
    foreground: ForegroundApplicationObservation | None
    observed_at: str


@dataclass(frozen=True, slots=True)
class _ApplicationProfile:
    canonical_name: str
    executable_names: tuple[str, ...] = ()
    aumid_contains: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ("generic_application",)


_PROFILES = (
    _ApplicationProfile("Google Chrome", ("chrome.exe",), aliases=("chrome", "google chrome"), capabilities=("generic_application", "browser", "web_navigation")),
    _ApplicationProfile("Microsoft Edge", ("msedge.exe",), ("microsoft.microsoftedge",), ("edge", "microsoft edge"), ("generic_application", "browser", "web_navigation")),
    _ApplicationProfile("Mozilla Firefox", ("firefox.exe",), aliases=("firefox", "mozilla firefox"), capabilities=("generic_application", "browser", "web_navigation")),
    _ApplicationProfile("Visual Studio Code", ("code.exe",), aliases=("vs code", "vscode", "visual studio code"), capabilities=("generic_application", "code_editor")),
    _ApplicationProfile("Visual Studio", ("devenv.exe",), aliases=("visual studio",), capabilities=("generic_application", "code_editor", "ide")),
    _ApplicationProfile("Notepad", ("notepad.exe",), ("windowsnotepad",), ("notepad", "记事本"), ("generic_application", "text_editor")),
    _ApplicationProfile("Microsoft Excel", ("excel.exe",), aliases=("excel", "microsoft excel"), capabilities=("generic_application", "spreadsheet", "office")),
    _ApplicationProfile("Microsoft Word", ("winword.exe",), aliases=("word", "microsoft word"), capabilities=("generic_application", "document_editor", "office")),
    _ApplicationProfile("Microsoft PowerPoint", ("powerpnt.exe",), aliases=("powerpoint", "microsoft powerpoint"), capabilities=("generic_application", "presentation", "office")),
    _ApplicationProfile("Microsoft Outlook", ("outlook.exe", "olk.exe"), aliases=("outlook", "microsoft outlook"), capabilities=("generic_application", "communication", "email", "office")),
    _ApplicationProfile("Microsoft Teams", ("ms-teams.exe", "teams.exe"), ("msteams",), ("teams", "microsoft teams"), ("generic_application", "communication", "meeting")),
    _ApplicationProfile("WeChat", ("wechat.exe", "weixin.exe"), aliases=("wechat", "weixin", "微信"), capabilities=("generic_application", "communication", "messaging")),
    _ApplicationProfile("Windows Terminal", ("windowsterminal.exe", "wt.exe"), ("microsoft.windowsterminal",), ("terminal", "windows terminal", "wt"), ("generic_application", "terminal", "shell")),
    _ApplicationProfile("PowerShell", ("powershell.exe", "pwsh.exe"), aliases=("powershell", "pwsh"), capabilities=("generic_application", "terminal", "shell")),
    _ApplicationProfile("Command Prompt", ("cmd.exe",), aliases=("cmd", "command prompt", "命令提示符"), capabilities=("generic_application", "terminal", "shell")),
    _ApplicationProfile("Adobe Acrobat Reader", ("acrord32.exe", "acrobat.exe"), aliases=("acrobat", "adobe reader", "acrobat reader"), capabilities=("generic_application", "pdf_reader")),
    _ApplicationProfile("SumatraPDF", ("sumatrapdf.exe",), aliases=("sumatrapdf", "sumatra pdf"), capabilities=("generic_application", "pdf_reader")),
    _ApplicationProfile("Microsoft Paint", ("mspaint.exe",), aliases=("paint", "mspaint", "画图"), capabilities=("generic_application", "image_editor")),
    _ApplicationProfile("Ollama", ("ollama.exe",), aliases=("ollama",), capabilities=("generic_application", "local_inference_runtime")),
    _ApplicationProfile("LM Studio", ("lm studio.exe", "lmstudio.exe"), aliases=("lm studio", "lmstudio"), capabilities=("generic_application", "local_inference_runtime")),
)
_PROFILE_BY_EXE = {name.casefold(): profile for profile in _PROFILES for name in profile.executable_names}


class WindowsSoftwareInventory:
    """Collect software evidence from several native Windows sources.

    No individual registry location is treated as an authoritative universe.
    Failure of one source is merely absence of evidence from that source.
    """

    def __init__(self, *, max_candidates: int = 6000) -> None:
        self.max_candidates = max(128, int(max_candidates))

    def collect(self) -> list[ApplicationInventoryCandidate]:
        if platform.system() != "Windows":
            return self._path_candidates(min(self.max_candidates, 1024))
        rows: list[ApplicationInventoryCandidate] = []
        for collector in (
            self._start_menu_candidates,
            self._app_paths_candidates,
            self._apps_folder_candidates,
            self._uninstall_candidates,
            self._path_candidates,
            self._known_program_files_fallback,
        ):
            if len(rows) >= self.max_candidates:
                break
            try:
                rows.extend(collector(self.max_candidates - len(rows)))
            except Exception:
                continue
        return rows[: self.max_candidates]

    def _start_menu_candidates(self, limit: int) -> list[ApplicationInventoryCandidate]:
        roots = _existing_paths((
            Path(os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs")),
            Path(os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs")),
        ))
        try:
            from comtypes.client import CreateObject
            shell = CreateObject("WScript.Shell", dynamic=True)
        except Exception:
            return []
        out: list[ApplicationInventoryCandidate] = []
        for root in roots:
            for shortcut in sorted(root.rglob("*.lnk"), key=lambda item: str(item).casefold()):
                if len(out) >= limit:
                    return out
                try:
                    link = shell.CreateShortcut(str(shortcut))
                    target = _clean_path(getattr(link, "TargetPath", None))
                    arguments = str(getattr(link, "Arguments", "") or "").strip()
                except Exception:
                    continue
                executable = target if target and Path(target).is_file() else None
                aumid = _aumid_from_shell_arguments(arguments)
                out.append(ApplicationInventoryCandidate(
                    source="start_menu", source_id=str(shortcut), display_name=shortcut.stem,
                    executable_path=executable, identity_paths=(executable,) if executable else (),
                    aumid=aumid, launch_kind="aumid" if aumid else "shell_item",
                    launch_target=aumid or str(shortcut),
                ))
        return out

    def _app_paths_candidates(self, limit: int) -> list[ApplicationInventoryCandidate]:
        try:
            import winreg
        except ImportError:
            return []
        out: list[ApplicationInventoryCandidate] = []
        base = r"Software\Microsoft\Windows\CurrentVersion\App Paths"
        views = [0, getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0)]
        for hive_name, hive in (("hkcu", winreg.HKEY_CURRENT_USER), ("hklm", winreg.HKEY_LOCAL_MACHINE)):
            for view in dict.fromkeys(views):
                try:
                    root = winreg.OpenKey(hive, base, 0, winreg.KEY_READ | view)
                except OSError:
                    continue
                with root:
                    index = 0
                    while len(out) < limit:
                        try:
                            sub_name = winreg.EnumKey(root, index)
                        except OSError:
                            break
                        index += 1
                        try:
                            with winreg.OpenKey(root, sub_name) as sub:
                                target = _clean_path(winreg.QueryValueEx(sub, None)[0])
                        except OSError:
                            continue
                        if not target or not Path(target).is_file():
                            continue
                        out.append(ApplicationInventoryCandidate(
                            source="app_paths", source_id=f"{hive_name}:{view}:{sub_name}",
                            display_name=Path(target).stem or Path(sub_name).stem,
                            executable_path=target, identity_paths=(target,),
                            launch_kind="executable", launch_target=target,
                        ))
        return out

    def _apps_folder_candidates(self, limit: int) -> list[ApplicationInventoryCandidate]:
        try:
            from comtypes.client import CreateObject
            shell = CreateObject("Shell.Application", dynamic=True)
            folder = shell.NameSpace("shell:AppsFolder")
            items = folder.Items() if folder is not None else None
            count = int(items.Count) if items is not None else 0
        except Exception:
            return []
        out: list[ApplicationInventoryCandidate] = []
        for index in range(min(count, limit)):
            try:
                item = items.Item(index)
                display = str(getattr(item, "Name", "") or "").strip()
                raw_path = str(getattr(item, "Path", "") or "").strip()
                aumid = _shell_property(item, "System.AppUserModel.ID")
                package = _shell_property(item, "System.AppUserModel.PackageFullName") or _shell_property(item, "System.AppUserModel.PackageFamilyName")
            except Exception:
                continue
            if not display:
                continue
            executable = _clean_path(raw_path)
            if executable and not Path(executable).is_file():
                executable = None
            if not aumid and raw_path.lower().startswith("shell:appsfolder\\"):
                aumid = raw_path.split("\\", 1)[1].strip() or None
            kind: LaunchKind = "aumid" if aumid else "executable" if executable else "unavailable"
            out.append(ApplicationInventoryCandidate(
                source="apps_folder", source_id=aumid or raw_path or f"{index}:{display}",
                display_name=display, executable_path=executable,
                identity_paths=(executable,) if executable else (), package_identity=package,
                aumid=aumid, launch_kind=kind, launch_target=aumid or executable,
            ))
        return out

    def _uninstall_candidates(self, limit: int) -> list[ApplicationInventoryCandidate]:
        try:
            import winreg
        except ImportError:
            return []
        out: list[ApplicationInventoryCandidate] = []
        base = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
        views = [0, getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0)]
        for hive_name, hive in (("hkcu", winreg.HKEY_CURRENT_USER), ("hklm", winreg.HKEY_LOCAL_MACHINE)):
            for view in dict.fromkeys(views):
                try:
                    root = winreg.OpenKey(hive, base, 0, winreg.KEY_READ | view)
                except OSError:
                    continue
                with root:
                    index = 0
                    while len(out) < limit:
                        try:
                            sub_name = winreg.EnumKey(root, index)
                        except OSError:
                            break
                        index += 1
                        try:
                            with winreg.OpenKey(root, sub_name) as sub:
                                display = _reg_string(sub, "DisplayName")
                                version = _reg_string(sub, "DisplayVersion")
                                publisher = _reg_string(sub, "Publisher")
                                location = _clean_path(_reg_string(sub, "InstallLocation"))
                                icon = _display_icon_path(_reg_string(sub, "DisplayIcon"))
                        except OSError:
                            continue
                        if not display:
                            continue
                        out.append(ApplicationInventoryCandidate(
                            source="uninstall_registry", source_id=f"{hive_name}:{view}:{sub_name}",
                            display_name=display, identity_paths=(icon,) if icon else (),
                            version=version, publisher=publisher, install_location=location,
                        ))
        return out

    def _path_candidates(self, limit: int) -> list[ApplicationInventoryCandidate]:
        out: list[ApplicationInventoryCandidate] = []
        seen: set[str] = set()
        for raw in str(os.environ.get("PATH") or "").split(os.pathsep):
            directory = Path(_clean_path(raw) or "")
            if not directory.is_dir():
                continue
            try:
                entries = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
            except OSError:
                continue
            for entry in entries:
                if len(out) >= limit:
                    return out
                if not entry.is_file() or entry.suffix.casefold() != ".exe":
                    continue
                normalized = _normalize_path(entry)
                if normalized in seen:
                    continue
                seen.add(normalized)
                out.append(ApplicationInventoryCandidate(
                    source="path", source_id=normalized, display_name=entry.stem,
                    executable_path=str(entry), identity_paths=(str(entry),),
                    launch_kind="executable", launch_target=str(entry),
                ))
        return out

    def _known_program_files_fallback(self, limit: int) -> list[ApplicationInventoryCandidate]:
        if platform.system() != "Windows":
            return []
        roots = _existing_paths((
            Path(os.path.expandvars(r"%ProgramFiles%")),
            Path(os.path.expandvars(r"%ProgramFiles(x86)%")),
            Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs")),
        ))
        known = set(_PROFILE_BY_EXE)
        out: list[ApplicationInventoryCandidate] = []
        seen: set[str] = set()
        for root in roots:
            root_depth = len(root.parts)
            for current, dirs, files in os.walk(root):
                if len(Path(current).parts) - root_depth >= 4:
                    dirs[:] = []
                for name in sorted(files, key=str.casefold):
                    if len(out) >= limit:
                        return out
                    if name.casefold() not in known:
                        continue
                    path = str(Path(current) / name)
                    normalized = _normalize_path(path)
                    if normalized in seen:
                        continue
                    seen.add(normalized)
                    out.append(ApplicationInventoryCandidate(
                        source="program_files_fallback", source_id=normalized,
                        display_name=Path(name).stem, executable_path=path,
                        identity_paths=(path,), launch_kind="executable", launch_target=path,
                    ))
        return out


class WindowsAssociationResolver:
    ASSOCSTR_EXECUTABLE = 2
    ASSOCSTR_FRIENDLYAPPNAME = 4
    ASSOCF_IS_PROTOCOL = 0x00001000

    def query(self, association: str, graph: "DeviceCapabilityGraph") -> AssociationObservation:
        value = str(association or "").strip()
        if not value:
            raise ValueError("association must not be empty")
        if platform.system() != "Windows":
            return AssociationObservation(value, None, None, None, utc_now())
        flags = self.ASSOCF_IS_PROTOCOL if _looks_like_protocol(value) else 0
        executable = self._query_string(value, self.ASSOCSTR_EXECUTABLE, flags)
        friendly = self._query_string(value, self.ASSOCSTR_FRIENDLYAPPNAME, flags)
        app = graph.application_for_executable(executable) if executable else None
        return AssociationObservation(value, executable, friendly, app.app_id if app else None, utc_now())

    @staticmethod
    def _query_string(association: str, string_kind: int, flags: int) -> str | None:
        from ctypes import wintypes
        shlwapi = ctypes.WinDLL("Shlwapi", use_last_error=True)
        fn = shlwapi.AssocQueryStringW
        fn.argtypes = [wintypes.DWORD, ctypes.c_int, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        fn.restype = ctypes.c_long
        size = wintypes.DWORD(0)
        fn(flags, string_kind, association, None, None, ctypes.byref(size))
        if size.value <= 1:
            return None
        buffer = ctypes.create_unicode_buffer(size.value)
        if int(fn(flags, string_kind, association, None, buffer, ctypes.byref(size))) != 0:
            return None
        value = buffer.value.strip()
        return _clean_path(value) if string_kind == WindowsAssociationResolver.ASSOCSTR_EXECUTABLE else value or None


class DeviceCapabilityGraph:
    CACHE_SCHEMA = 1

    def __init__(
        self,
        *,
        inventory_provider: Callable[[], Iterable[ApplicationInventoryCandidate]] | None = None,
        process_provider: Callable[[], Iterable[dict[str, Any]]] | None = None,
        window_provider: Callable[[], Iterable[dict[str, Any]]] | None = None,
        cache_path: str | Path | None = None,
        inventory_ttl_seconds: float = 300.0,
    ) -> None:
        self._inventory_provider = inventory_provider or WindowsSoftwareInventory().collect
        self._process_provider = process_provider
        self._window_provider = window_provider
        self._cache_path = Path(cache_path) if cache_path else _default_cache_path()
        self._ttl = max(0.0, float(inventory_ttl_seconds))
        self._applications: tuple[InstalledApplication, ...] = ()
        self._inventory_monotonic = 0.0
        self._associations = WindowsAssociationResolver()

    def installed_applications(self, *, force_refresh: bool = False) -> tuple[InstalledApplication, ...]:
        now = time.monotonic()
        if not force_refresh and self._applications and now - self._inventory_monotonic <= self._ttl:
            return self._applications
        if not force_refresh and not self._applications:
            cached = self._read_cache()
            if cached:
                self._applications = cached
                self._inventory_monotonic = now
                return cached
        self._applications = tuple(_reconcile_candidates(tuple(self._inventory_provider())))
        self._inventory_monotonic = now
        self._write_cache(self._applications)
        return self._applications

    def application_by_id(self, app_id: str, *, force_refresh: bool = False) -> InstalledApplication | None:
        wanted = str(app_id or "").strip()
        return next((app for app in self.installed_applications(force_refresh=force_refresh) if app.app_id == wanted), None)

    def application_for_executable(self, executable_path: str | None) -> InstalledApplication | None:
        normalized = _normalize_path(executable_path)
        matches = [app for app in self.installed_applications() if normalized and _normalize_path(app.executable_path) == normalized]
        return matches[0] if len(matches) == 1 else None

    def resolve_application(self, query: str, *, force_refresh: bool = False) -> ApplicationResolution:
        raw = " ".join(str(query or "").strip().split())
        wanted = _normalize_name(raw)
        if not wanted:
            return ApplicationResolution(raw, "not_installed")
        apps = self.installed_applications(force_refresh=force_refresh)
        exact = _unique_apps(app for app in apps if wanted in _aliases(app))
        if len(exact) == 1:
            return ApplicationResolution(raw, "resolved", exact[0])
        if len(exact) > 1:
            return ApplicationResolution(raw, "ambiguous", candidates=tuple(exact))
        partial: list[InstalledApplication] = []
        if len(wanted) >= 2:
            for app in apps:
                if any(alias.startswith(wanted) or wanted.startswith(alias) or (len(wanted) >= 4 and wanted in alias) for alias in _aliases(app)):
                    partial.append(app)
        partial = _unique_apps(partial)
        if len(partial) == 1:
            return ApplicationResolution(raw, "resolved", partial[0])
        if len(partial) > 1:
            return ApplicationResolution(raw, "ambiguous", candidates=tuple(partial))
        return ApplicationResolution(raw, "not_installed")

    def running_processes(self) -> tuple[RunningProcessObservation, ...]:
        apps = self.installed_applications()
        raw_rows = list(self._process_provider()) if self._process_provider else _native_processes()
        observed = utc_now()
        rows: list[RunningProcessObservation] = []
        for raw in raw_rows:
            pid = int(raw.get("process_id") or raw.get("pid") or 0)
            if pid <= 0:
                continue
            executable = _clean_path(raw.get("executable_path") or raw.get("exe"))
            aumid = _text(raw.get("aumid"))
            package = _text(raw.get("package_identity"))
            app = _process_app(apps, executable, aumid, package)
            rows.append(RunningProcessObservation(
                pid, str(raw.get("process_name") or raw.get("name") or "").strip(), executable,
                aumid, package, _float(raw.get("created_at_epoch") or raw.get("create_time")),
                app.app_id if app else None, observed,
            ))
        return tuple(sorted(rows, key=lambda row: row.process_id))

    def windows(self, *, processes: Sequence[RunningProcessObservation] | None = None) -> tuple[ApplicationWindowObservation, ...]:
        process_rows = tuple(processes) if processes is not None else self.running_processes()
        by_pid = {row.process_id: row for row in process_rows}
        raw_rows = list(self._window_provider()) if self._window_provider else _native_windows()
        observed = utc_now()
        rows: list[ApplicationWindowObservation] = []
        for raw in raw_rows:
            hwnd = int(raw.get("hwnd") or 0)
            pid = int(raw.get("process_id") or raw.get("pid") or 0)
            if hwnd <= 0 or pid <= 0:
                continue
            process = by_pid.get(pid)
            rows.append(ApplicationWindowObservation(
                hwnd, pid, str(raw.get("title") or ""), str(raw.get("class_name") or ""),
                bool(raw.get("visible", True)), bool(raw.get("foreground", False)),
                process.resolved_app_id if process else None, observed,
            ))
        return tuple(sorted(rows, key=lambda row: (not row.foreground, row.process_id, row.hwnd)))

    def application_runtime(self, application: InstalledApplication) -> tuple[tuple[RunningProcessObservation, ...], tuple[ApplicationWindowObservation, ...]]:
        processes = tuple(row for row in self.running_processes() if row.resolved_app_id == application.app_id)
        pids = {row.process_id for row in processes}
        windows = tuple(row for row in self.windows(processes=processes) if row.process_id in pids and row.resolved_app_id == application.app_id)
        return processes, windows

    def foreground_application(self) -> ForegroundApplicationObservation | None:
        processes = self.running_processes()
        windows = self.windows(processes=processes)
        window = next((row for row in windows if row.foreground), None)
        if window is None:
            return None
        process = next((row for row in processes if row.process_id == window.process_id), None)
        app = self.application_by_id(window.resolved_app_id or "") if window.resolved_app_id else None
        return ForegroundApplicationObservation(window, process, app, utc_now())

    def snapshot(self, *, force_inventory_refresh: bool = False) -> DeviceCapabilitySnapshot:
        apps = self.installed_applications(force_refresh=force_inventory_refresh)
        processes = self.running_processes()
        windows = self.windows(processes=processes)
        window = next((row for row in windows if row.foreground), None)
        foreground = None
        if window is not None:
            process = next((row for row in processes if row.process_id == window.process_id), None)
            app = next((item for item in apps if item.app_id == window.resolved_app_id), None) if window.resolved_app_id else None
            foreground = ForegroundApplicationObservation(window, process, app, utc_now())
        return DeviceCapabilitySnapshot(apps, processes, windows, foreground, utc_now())

    def file_association(self, extension: str) -> AssociationObservation:
        value = str(extension or "").strip()
        return self._associations.query(value if value.startswith(".") else "." + value, self)

    def protocol_handler(self, protocol: str) -> AssociationObservation:
        return self._associations.query(str(protocol or "").strip().lower().rstrip(":"), self)

    def hardware(self) -> MachineHardwareObservation:
        memory = psutil.virtual_memory()
        root = Path.home().anchor or os.path.abspath(os.sep)
        disk = shutil.disk_usage(root)
        gpus = _native_gpus()
        return MachineHardwareObservation(
            platform.system(), platform.release(), platform.version(), platform.machine(),
            psutil.cpu_count(logical=True), psutil.cpu_count(logical=False),
            int(memory.total), int(memory.available), str(root), int(disk.total), int(disk.free),
            gpus, utc_now(), ("python-platform", "psutil") + (("windows-wmi",) if gpus else ()),
        )

    def _read_cache(self) -> tuple[InstalledApplication, ...]:
        path = self._cache_path
        if path is None or self._ttl <= 0:
            return ()
        try:
            if time.time() - path.stat().st_mtime > self._ttl:
                return ()
            raw = json.loads(path.read_text(encoding="utf-8"))
            if int(raw.get("schema") or 0) != self.CACHE_SCHEMA or not isinstance(raw.get("applications"), list):
                return ()
            return tuple(_application_from_dict(item) for item in raw["applications"][:7000] if isinstance(item, dict))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return ()

    def _write_cache(self, applications: Sequence[InstalledApplication]) -> None:
        path = self._cache_path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(path.suffix + ".tmp")
            temp.write_text(json.dumps({"schema": self.CACHE_SCHEMA, "written_at": utc_now(), "applications": [asdict(app) for app in applications[:7000]]}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            os.replace(temp, path)
        except OSError:
            pass


def _reconcile_candidates(candidates: Sequence[ApplicationInventoryCandidate]) -> list[InstalledApplication]:
    parents = list(range(len(candidates)))
    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index
    def union(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b:
            parents[b] = a
    owners: dict[str, int] = {}
    for index, candidate in enumerate(candidates):
        for key in _stable_keys(candidate):
            if key in owners:
                union(index, owners[key])
            else:
                owners[key] = index
    groups: dict[int, list[ApplicationInventoryCandidate]] = {}
    for index, candidate in enumerate(candidates):
        groups.setdefault(find(index), []).append(candidate)

    # Metadata-only uninstall rows are attached only with unique path containment
    # plus exact display evidence; strings alone never merge application identity.
    for root in list(groups):
        rows = groups.get(root, [])
        if not rows or any(_stable_keys(row) for row in rows):
            continue
        metadata = rows[0]
        location = _normalize_path(metadata.install_location)
        if metadata.source != "uninstall_registry" or not location:
            continue
        matches: list[int] = []
        for other_root, other_rows in groups.items():
            if other_root == root:
                continue
            if not any(_within(_normalize_path(row.executable_path), location) for row in other_rows if row.executable_path):
                continue
            if any(_normalize_name(row.display_name) == _normalize_name(metadata.display_name) for row in other_rows):
                matches.append(other_root)
        if len(matches) == 1:
            groups[matches[0]].extend(rows)
            groups.pop(root, None)
    apps = [_merge_group(rows) for rows in groups.values() if rows]
    return sorted(apps, key=lambda app: (app.canonical_name.casefold(), app.app_id))


def _merge_group(rows: Sequence[ApplicationInventoryCandidate]) -> InstalledApplication:
    ordered = sorted(rows, key=_priority)
    executable = _first_path(row.executable_path for row in ordered)
    aumid = _first(row.aumid for row in ordered)
    package = _first(row.package_identity for row in ordered)
    profile = _profile(executable, aumid, package)
    display = next((row.display_name.strip() for row in ordered if row.display_name.strip()), "Application")
    launch = next((row for row in ordered if row.launch_kind != "unavailable" and str(row.launch_target or "").strip()), None)
    kind: LaunchKind = launch.launch_kind if launch else "unavailable"
    target = str(launch.launch_target).strip() if launch and launch.launch_target else None
    return InstalledApplication(
        _app_id(aumid, executable, kind, target, "|".join(sorted(f"{row.source}:{row.source_id}" for row in rows))),
        display, profile.canonical_name if profile else display, executable, package, aumid,
        _first(row.version for row in ordered), _first(row.publisher for row in ordered), kind, target,
        profile.capabilities if profile else ("generic_application",),
        max((row.observed_at for row in rows), default=utc_now()), tuple(sorted({row.source for row in rows})),
    )


def _stable_keys(candidate: ApplicationInventoryCandidate) -> tuple[str, ...]:
    keys: list[str] = []
    if candidate.aumid:
        keys.append("aumid:" + candidate.aumid.casefold())
    for path in (candidate.executable_path, *candidate.identity_paths):
        normalized = _normalize_path(path)
        if normalized:
            keys.append("file:" + normalized)
    if candidate.launch_kind == "executable":
        normalized = _normalize_path(candidate.launch_target)
        if normalized:
            keys.append("launch-exe:" + normalized)
    elif candidate.launch_kind == "aumid" and candidate.launch_target:
        keys.append("launch-aumid:" + candidate.launch_target.casefold())
    elif candidate.launch_kind == "shell_item":
        normalized = _normalize_path(candidate.launch_target)
        if normalized:
            keys.append("shell-item:" + normalized)
    return tuple(dict.fromkeys(keys))


def _priority(candidate: ApplicationInventoryCandidate) -> tuple[int, str, str]:
    rank = {"start_menu": 0, "apps_folder": 1, "app_paths": 2, "uninstall_registry": 3, "program_files_fallback": 4, "path": 5}.get(candidate.source, 9)
    return rank, candidate.display_name.casefold(), candidate.source_id.casefold()


def _app_id(aumid: str | None, executable: str | None, kind: LaunchKind, target: str | None, fallback: str) -> str:
    if aumid:
        anchor = "aumid:" + aumid.casefold()
    elif executable:
        anchor = "exe:" + _normalize_path(executable)
    elif target:
        anchor = f"launch:{kind}:" + (_normalize_path(target) if kind == "shell_item" else target.casefold())
    else:
        anchor = "evidence:" + fallback
    return "app-" + hashlib.sha256(anchor.encode("utf-8", errors="replace")).hexdigest()[:24]


def _profile(executable: str | None, aumid: str | None, package: str | None) -> _ApplicationProfile | None:
    if executable and Path(executable).name.casefold() in _PROFILE_BY_EXE:
        return _PROFILE_BY_EXE[Path(executable).name.casefold()]
    identity = " ".join(value for value in (aumid, package) if value).casefold()
    return next((profile for profile in _PROFILES if identity and any(marker.casefold() in identity for marker in profile.aumid_contains)), None)


def _aliases(app: InstalledApplication) -> set[str]:
    aliases = {_normalize_name(app.display_name), _normalize_name(app.canonical_name)}
    if app.executable_path:
        aliases.add(_normalize_name(Path(app.executable_path).stem))
    if app.aumid:
        aliases.add(_normalize_name(app.aumid))
        if "!" in app.aumid:
            aliases.add(_normalize_name(app.aumid.rsplit("!", 1)[-1]))
    profile = _profile(app.executable_path, app.aumid, app.package_identity)
    if profile:
        aliases.update(_normalize_name(alias) for alias in profile.aliases)
    return {alias for alias in aliases if alias}


def _process_app(apps: Sequence[InstalledApplication], executable: str | None, aumid: str | None, package: str | None) -> InstalledApplication | None:
    normalized = _normalize_path(executable)
    if normalized:
        matches = [app for app in apps if _normalize_path(app.executable_path) == normalized]
        if len(matches) == 1:
            return matches[0]
    if aumid:
        matches = [app for app in apps if app.aumid and app.aumid.casefold() == aumid.casefold()]
        if len(matches) == 1:
            return matches[0]
    if package:
        matches = [app for app in apps if app.package_identity and app.package_identity.casefold() == package.casefold()]
        if len(matches) == 1:
            return matches[0]
    return None


def _native_processes() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for process in psutil.process_iter(attrs=["pid", "name", "exe", "create_time"]):
        try:
            info = process.info
            pid = int(info.get("pid") or 0)
            if pid <= 0:
                continue
            aumid, package = _windows_process_identity(pid) if platform.system() == "Windows" else (None, None)
            rows.append({"pid": pid, "name": info.get("name"), "exe": info.get("exe"), "create_time": info.get("create_time"), "aumid": aumid, "package_identity": package})
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
            continue
    return rows


def _windows_process_identity(pid: int) -> tuple[str | None, str | None]:
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    handle = open_process(0x1000, False, int(pid))
    if not handle:
        return None, None
    try:
        return _process_string(kernel32.GetApplicationUserModelId, handle), _process_string(kernel32.GetPackageFullName, handle)
    except (AttributeError, OSError):
        return None, None
    finally:
        kernel32.CloseHandle(handle)


def _process_string(function: Any, handle: Any) -> str | None:
    from ctypes import wintypes
    function.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.UINT), wintypes.LPWSTR]
    function.restype = ctypes.c_long
    size = wintypes.UINT(0)
    function(handle, ctypes.byref(size), None)
    if size.value <= 1:
        return None
    buffer = ctypes.create_unicode_buffer(size.value)
    return buffer.value.strip() or None if int(function(handle, ctypes.byref(size), buffer)) == 0 else None


def _native_windows() -> list[dict[str, Any]]:
    if platform.system() != "Windows":
        return []
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    foreground = int(user32.GetForegroundWindow() or 0)
    rows: list[dict[str, Any]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return True
        length = int(user32.GetWindowTextLengthW(hwnd))
        title = ctypes.create_unicode_buffer(max(1, length + 1))
        user32.GetWindowTextW(hwnd, title, len(title))
        klass = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, klass, len(klass))
        rows.append({"hwnd": int(hwnd), "pid": int(pid.value), "title": title.value, "class_name": klass.value, "visible": True, "foreground": int(hwnd) == foreground})
        return True
    callback_fn = callback_type(callback)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    if not user32.EnumWindows(callback_fn, 0):
        error = ctypes.get_last_error()
        if error:
            raise OSError(error, "EnumWindows failed")
    return rows


def _native_gpus() -> tuple[GpuObservation, ...]:
    if platform.system() != "Windows":
        return ()
    try:
        from comtypes.client import CoGetObject
        service = CoGetObject(r"winmgmts:root\cimv2", dynamic=True)
        controllers = list(
            service.ExecQuery(
                "SELECT Name, PNPDeviceID FROM Win32_VideoController"
            )
        )
    except Exception:
        return ()
    observed = utc_now()
    rows: list[GpuObservation] = []
    for controller in controllers:
        name = _wmi_property_text(controller, "Name")
        pnp = _wmi_property_text(controller, "PNPDeviceID") or None
        if name:
            rows.append(GpuObservation(name, pnp, observed))
    return tuple(rows)


def _wmi_property_text(row: Any, name: str) -> str:
    """Read one SWbemObject property across comtypes dynamic-binding versions."""

    try:
        value = getattr(row, name)
    except Exception:
        value = None
    text = str(value or "").strip()
    if text:
        return text
    try:
        for prop in row.Properties_:
            if str(getattr(prop, "Name", "") or "").casefold() == name.casefold():
                return str(getattr(prop, "Value", "") or "").strip()
    except Exception:
        return ""
    return ""


def _application_from_dict(raw: dict[str, Any]) -> InstalledApplication:
    kind = str(raw.get("launch_kind") or "unavailable")
    if kind not in {"executable", "shell_item", "aumid", "unavailable"}:
        kind = "unavailable"
    return InstalledApplication(
        str(raw.get("app_id") or ""), str(raw.get("display_name") or ""), str(raw.get("canonical_name") or raw.get("display_name") or ""),
        _text(raw.get("executable_path")), _text(raw.get("package_identity")), _text(raw.get("aumid")), _text(raw.get("version")), _text(raw.get("publisher")),
        kind, _text(raw.get("launch_target")), tuple(str(item) for item in raw.get("capabilities") or ()),
        str(raw.get("observed_at") or utc_now()), tuple(str(item) for item in raw.get("evidence_source") or ()),
    )  # type: ignore[arg-type]


def _default_cache_path() -> Path | None:
    try:
        from .home import get_zn_home
        return get_zn_home() / "cache" / "device-capability-v1.json"
    except Exception:
        return None


def _shell_property(item: Any, name: str) -> str | None:
    try:
        return _text(item.ExtendedProperty(name))
    except Exception:
        return None


def _reg_string(key: Any, name: str) -> str | None:
    try:
        import winreg
        return _text(winreg.QueryValueEx(key, name)[0])
    except OSError:
        return None


def _display_icon_path(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.startswith('"'):
        end = raw.find('"', 1)
        raw = raw[1:end] if end > 1 else raw.strip('"')
    else:
        raw = re.sub(r",\s*-?\d+\s*$", "", raw)
    path = _clean_path(raw)
    return path if path and Path(path).is_file() else None


def _aumid_from_shell_arguments(arguments: str) -> str | None:
    match = re.search(r"shell:AppsFolder\\([^\s\"]+)", str(arguments or ""), re.I)
    return match.group(1).strip() if match else None


def _normalize_name(value: Any) -> str:
    text = " ".join(str(value or "").strip().casefold().split())
    text = re.sub(r"[._\-/\\]+", " ", text)
    return " ".join(text.split())


def _clean_path(value: Any) -> str | None:
    text = str(value or "").strip().strip('"')
    return os.path.expandvars(os.path.expanduser(text)) if text else None


def _normalize_path(value: Any) -> str:
    path = _clean_path(value)
    return os.path.normcase(os.path.normpath(os.path.abspath(path))).casefold() if path else ""


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _first(values: Iterable[str | None]) -> str | None:
    return next((value for value in (_text(item) for item in values) if value), None)


def _first_path(values: Iterable[str | None]) -> str | None:
    fallback = None
    for value in values:
        path = _clean_path(value)
        if not path:
            continue
        fallback = fallback or path
        if Path(path).is_file():
            return path
    return fallback


def _unique_apps(apps: Iterable[InstalledApplication]) -> list[InstalledApplication]:
    unique = {app.app_id: app for app in apps}
    return sorted(unique.values(), key=lambda app: (app.canonical_name.casefold(), app.app_id))


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _within(path: str, root: str) -> bool:
    if not path or not root:
        return False
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def _existing_paths(values: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for value in values:
        normalized = _normalize_path(value)
        if normalized and normalized not in seen and value.is_dir():
            seen.add(normalized)
            result.append(value)
    return result


def _looks_like_protocol(value: str) -> bool:
    text = str(value or "").strip().lower().rstrip(":")
    return bool(text) and not text.startswith(".") and bool(re.fullmatch(r"[a-z][a-z0-9+.-]*", text))
