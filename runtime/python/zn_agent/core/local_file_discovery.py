from __future__ import annotations

import ctypes
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping

from .capabilities import CallableCapability
from .file_identity import observe_file_identity
from .models import CapabilityResult
from .path_context import canonical_host_path, resolved_within

_CAPABILITY_NAME = "local_file_discovery"
_MAX_SCAN_ENTRIES = 20_000
_MAX_RESULTS = 8
_MAX_DEPTH = 12

_SCOPE_MARKERS: dict[str, tuple[str, ...]] = {
    "downloads": (
        "下载目录",
        "下载文件夹",
        "下载的",
        "downloads",
        "download folder",
        "downloads folder",
    ),
    "documents": (
        "文档目录",
        "文档文件夹",
        "我的文档",
        "documents",
        "documents folder",
    ),
    "desktop": ("桌面", "desktop"),
}
_EXTENSION_MARKERS: dict[str, tuple[str, ...]] = {
    ".pdf": ("pdf",),
    ".docx": ("docx", "word"),
    ".doc": ("doc",),
    ".xlsx": ("xlsx", "excel"),
    ".xls": ("xls",),
    ".txt": ("txt", "文本文件", "文本"),
}
_SEARCH_RE = re.compile(
    r"(?:帮我|请)?\s*(?:找(?:到|一下)?|查找|搜索|定位)|"
    r"\b(?:find|locate|search(?:\s+for)?|look\s+for)\b",
    re.I,
)
_ABOUT_RE = re.compile(
    r"关于\s*(?P<q>[^，,。；;]{1,80}?)(?=\s*(?:的\s*)?"
    r"(?:pdf|docx?|word|xlsx?|excel|txt|文件|文档)(?:\s|[，,。；;]|$))",
    re.I,
)
_ENGLISH_STOP_RE = re.compile(
    r"\b(?:find|locate|search(?:\s+for)?|look\s+for|my|the|in|from|"
    r"downloads?|documents?|desktop|yesterday|file|document|about)\b",
    re.I,
)
_IGNORED_DIRS = frozenset(
    {".git", ".svn", "node_modules", "__pycache__", ".cache", "temp", "tmp"}
)
_KNOWN_FOLDER_IDS = {
    "downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
}
_COINIT_APARTMENTTHREADED = 0x2
_RPC_E_CHANGED_MODE = 0x80010106


def _initialize_com_for_known_folder(ole32) -> bool:
    """Ensure the calling thread can use the Windows Known Folder COM API.

    Returns whether this call successfully incremented COM initialization and
    therefore must be balanced with CoUninitialize. A different existing
    apartment is still usable, but must not be uninitialized by this function.
    """

    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    ole32.CoInitializeEx.restype = ctypes.c_long
    status = int(ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED))
    code = status & 0xFFFFFFFF
    if status in {0, 1}:
        return True
    if code == _RPC_E_CHANGED_MODE:
        return False
    raise OSError(f"CoInitializeEx failed with HRESULT 0x{code:08X}")



@dataclass(frozen=True, slots=True)
class LocalFileSearchRequest:
    scope: str
    query: str
    extensions: tuple[str, ...] = ()
    modified_date: str | None = None


@dataclass(frozen=True, slots=True)
class LocalFileCandidate:
    path: str
    name: str
    modified_at: str
    size_bytes: int
    score: int


@dataclass(frozen=True, slots=True)
class LocalFileSearchResult:
    request: LocalFileSearchRequest
    root: str
    candidates: tuple[LocalFileCandidate, ...]
    scanned_entries: int
    matched_count: int
    complete: bool


def parse_local_file_search_request(event_or_task) -> LocalFileSearchRequest | None:
    if hasattr(event_or_task, "task"):
        event = event_or_task
        kind = str(getattr(event, "kind", "") or "").strip().lower()
        if kind not in {"desktop_user_event", "user_task"}:
            return None
        payload = getattr(event, "payload", None) or {}
        if payload.get("body_action") or payload.get("native_action"):
            return None
        task = str(getattr(event, "task", "") or "")
    else:
        task = str(event_or_task or "")

    text = " ".join(task.strip().split())
    if not text or _SEARCH_RE.search(text) is None:
        return None
    lowered = text.casefold()
    scopes = [
        scope
        for scope, markers in _SCOPE_MARKERS.items()
        if any(marker.casefold() in lowered for marker in markers)
    ]
    if len(scopes) != 1:
        return None

    extensions = tuple(
        sorted(
            ext
            for ext, markers in _EXTENSION_MARKERS.items()
            if any(_marker_present(lowered, marker) for marker in markers)
        )
    )
    modified_date = None
    if "昨天" in text or re.search(r"\byesterday\b", lowered):
        modified_date = (
            datetime.now().astimezone().date() - timedelta(days=1)
        ).isoformat()

    about = _ABOUT_RE.search(text)
    query = about.group("q").strip() if about is not None else _extract_residual_query(text)
    if not query:
        return None
    return LocalFileSearchRequest(
        scope=scopes[0],
        query=query,
        extensions=extensions,
        modified_date=modified_date,
    )


def _marker_present(lowered: str, marker: str) -> bool:
    raw = marker.casefold()
    if raw.isascii() and raw.replace(".", "").isalnum():
        return (
            re.search(rf"(?<![a-z0-9]){re.escape(raw)}(?![a-z0-9])", lowered)
            is not None
        )
    return raw in lowered


def _extract_residual_query(text: str) -> str:
    query = text
    phrases = (
        "帮我",
        "请",
        "找到",
        "找一下",
        "找",
        "查找",
        "搜索",
        "定位",
        "我",
        "昨天",
        "下载目录里面",
        "下载目录里",
        "下载目录",
        "下载文件夹里面",
        "下载文件夹里",
        "下载文件夹",
        "下载的",
        "文档目录里面",
        "文档目录里",
        "文档目录",
        "文档文件夹里面",
        "文档文件夹里",
        "文档文件夹",
        "我的文档",
        "桌面上的",
        "桌面上",
        "桌面",
        "文件",
        "文档",
        "那个",
        "那份",
        "关于",
    )
    for phrase in phrases:
        query = query.replace(phrase, " ")
    query = _ENGLISH_STOP_RE.sub(" ", query)
    for markers in _EXTENSION_MARKERS.values():
        for marker in markers:
            if marker.isascii():
                query = re.sub(
                    rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])",
                    " ",
                    query,
                    flags=re.I,
                )
            else:
                query = query.replace(marker, " ")
    query = re.sub(r"[“”\"'‘’（）()\[\]{}，,。；;：:]+", " ", query)
    query = " ".join(query.split())
    return query.strip(" 的里上")


class _Guid(ctypes.Structure):
    _fields_ = (
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    )

    @classmethod
    def parse(cls, value: str) -> "_Guid":
        raw = uuid.UUID(value).bytes_le
        result = cls()
        result.Data1 = int.from_bytes(raw[0:4], "little")
        result.Data2 = int.from_bytes(raw[4:6], "little")
        result.Data3 = int.from_bytes(raw[6:8], "little")
        result.Data4[:] = raw[8:16]
        return result


def _windows_known_folder(folder_id: str) -> Path | None:
    if os.name != "nt":
        return None
    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(_Guid),
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole32.CoTaskMemFree.restype = None
        ole32.CoUninitialize.argtypes = []
        ole32.CoUninitialize.restype = None
        uninitialize = _initialize_com_for_known_folder(ole32)
        guid = _Guid.parse(folder_id)
        pointer = ctypes.c_void_p()
        try:
            status = int(
                shell32.SHGetKnownFolderPath(
                    ctypes.byref(guid),
                    0,
                    None,
                    ctypes.byref(pointer),
                )
            )
            if status != 0 or not pointer.value:
                return None
            return Path(ctypes.wstring_at(pointer.value))
        finally:
            if pointer.value:
                ole32.CoTaskMemFree(pointer)
            if uninitialize:
                ole32.CoUninitialize()
    except (AttributeError, OSError, ValueError):
        return None


def default_local_file_roots() -> dict[str, Path]:
    profile = str(os.environ.get("USERPROFILE") or "").strip()
    home = Path(profile).expanduser() if profile else Path.home()
    fallback = {
        "downloads": home / "Downloads",
        "documents": home / "Documents",
        "desktop": home / "Desktop",
    }
    return {
        scope: _windows_known_folder(folder_id) or fallback[scope]
        for scope, folder_id in _KNOWN_FOLDER_IDS.items()
    }


class LocalFileDiscovery:
    def __init__(
        self,
        *,
        roots: Mapping[str, str | Path] | None = None,
        max_scan_entries: int = _MAX_SCAN_ENTRIES,
        max_results: int = _MAX_RESULTS,
        max_depth: int = _MAX_DEPTH,
    ) -> None:
        source = roots or default_local_file_roots()
        self._roots = {
            str(scope): canonical_host_path(path)
            for scope, path in source.items()
        }
        self.max_scan_entries = max(1, int(max_scan_entries))
        self.max_results = max(1, int(max_results))
        self.max_depth = max(0, int(max_depth))

    def scope_available(self, scope: str) -> bool:
        root = self._roots.get(scope)
        try:
            return bool(root is not None and root.is_dir())
        except OSError:
            return False

    def search(self, request: LocalFileSearchRequest) -> LocalFileSearchResult:
        root = self._roots.get(request.scope)
        if root is None:
            raise ValueError(f"unsupported local file scope: {request.scope}")
        try:
            root = canonical_host_path(root).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RuntimeError(
                f"local file scope is unavailable: {type(exc).__name__}"
            ) from exc
        if not root.is_dir():
            raise RuntimeError("local file scope is not a directory")

        scanned = 0
        matched_count = 0
        complete = True
        matches: list[LocalFileCandidate] = []
        stack: list[tuple[Path, int]] = [(root, 0)]

        while stack:
            directory, depth = stack.pop()
            try:
                iterator = os.scandir(directory)
            except OSError:
                complete = False
                continue
            with iterator:
                for entry in iterator:
                    scanned += 1
                    if scanned > self.max_scan_entries:
                        complete = False
                        stack.clear()
                        break
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if _ignored_dir(entry.name):
                                continue
                            if depth < self.max_depth:
                                stack.append((Path(entry.path), depth + 1))
                            else:
                                complete = False
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                    except OSError:
                        complete = False
                        continue

                    path = Path(entry.path)
                    if (
                        request.extensions
                        and path.suffix.casefold() not in request.extensions
                    ):
                        continue
                    score = _query_score(path.stem, request.query)
                    if score <= 0:
                        continue
                    inside = resolved_within(root, path)
                    if inside is None:
                        continue
                    identity = observe_file_identity(inside, max_hash_bytes=0)
                    if not _stable_regular_file(identity):
                        continue
                    modified = _identity_local_datetime(identity)
                    if modified is None:
                        continue
                    if (
                        request.modified_date
                        and modified.date().isoformat() != request.modified_date
                    ):
                        continue
                    matched_count += 1
                    matches.append(
                        LocalFileCandidate(
                            path=str(inside),
                            name=inside.name,
                            modified_at=modified.isoformat(),
                            size_bytes=int(identity.get("size_bytes") or 0),
                            score=score,
                        )
                    )

        matches.sort(
            key=lambda item: (
                item.score,
                item.modified_at,
                item.name.casefold(),
            ),
            reverse=True,
        )
        return LocalFileSearchResult(
            request=request,
            root=str(root),
            candidates=tuple(matches[: self.max_results]),
            scanned_entries=scanned,
            matched_count=matched_count,
            complete=complete,
        )


def _ignored_dir(name: str) -> bool:
    lowered = str(name or "").casefold()
    return bool(
        not lowered
        or lowered in _IGNORED_DIRS
        or lowered.startswith(".")
        or lowered.startswith("$")
    )


def _query_score(stem: str, query: str) -> int:
    name = _search_text(stem)
    wanted = _search_text(query)
    if not name or not wanted:
        return 0
    if wanted in name:
        return 3
    tokens = [token for token in wanted.split() if token]
    if tokens and all(token in name for token in tokens):
        return 2
    return 0


def _search_text(value: str) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[^\w\u3400-\u9fff]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _stable_regular_file(identity: Mapping[str, object]) -> bool:
    return bool(
        identity.get("observable") is True
        and identity.get("stable") is True
        and identity.get("exists") is True
        and identity.get("type") == "file"
    )


def _identity_local_datetime(
    identity: Mapping[str, object],
) -> datetime | None:
    try:
        seconds = int(identity.get("mtime_ns") or 0) / 1_000_000_000
        return datetime.fromtimestamp(seconds).astimezone()
    except (OSError, OverflowError, TypeError, ValueError):
        return None


def render_local_file_search_result(
    result: LocalFileSearchResult,
) -> str:
    request = result.request
    scope_name = {
        "downloads": "下载目录",
        "documents": "文档目录",
        "desktop": "桌面",
    }.get(request.scope, request.scope)
    if not result.complete:
        return (
            f"我在{scope_name}的安全扫描达到 "
            f"{result.scanned_entries - 1} 个条目上限；"
            "当前结果不完整，我不会把它当成完整本机搜索。"
            "请缩小目录或查询条件。"
        )
    if not result.candidates:
        date_text = (
            f"、修改日期为 {request.modified_date}"
            if request.modified_date
            else ""
        )
        ext_text = (
            f"、类型为 {'/'.join(request.extensions)}"
            if request.extensions
            else ""
        )
        return (
            f"我已完整扫描{scope_name}，没有找到名称匹配“{request.query}”"
            f"{date_text}{ext_text}的文件。"
        )
    header = f"找到 {result.matched_count} 个本机文件匹配“{request.query}”"
    if result.matched_count <= len(result.candidates):
        header += "："
    else:
        header += f"，先列前 {len(result.candidates)} 个："
    rows = [f"- {item.path}" for item in result.candidates]
    return header + "\n" + "\n".join(rows)


def build_local_file_discovery_capability(
    *,
    roots: Mapping[str, str | Path] | None = None,
):
    discovery = LocalFileDiscovery(roots=roots)

    def matcher(event) -> float:
        request = parse_local_file_search_request(event)
        if request is None or not discovery.scope_available(request.scope):
            return 0.0
        return 0.98

    def handler(event, _state):
        request = parse_local_file_search_request(event)
        if request is None:
            return CapabilityResult(
                success=False,
                error="local file search request no longer matches",
            )
        try:
            result = discovery.search(request)
        except Exception as exc:
            return CapabilityResult(
                success=False,
                error=(
                    "local file discovery failed: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )
        response = render_local_file_search_result(result)
        if not result.complete:
            return CapabilityResult(
                success=True,
                response=response,
                verification_passed=False,
                data={
                    "scope": request.scope,
                    "query": request.query,
                    "complete": False,
                    "scanned_entries": result.scanned_entries - 1,
                },
            )
        return CapabilityResult(
            success=True,
            response=response,
            verification_passed=True,
            data={
                "scope": request.scope,
                "query": request.query,
                "complete": True,
                "matched_count": result.matched_count,
                "paths": [item.path for item in result.candidates],
            },
        )

    return CallableCapability(
        name=_CAPABILITY_NAME,
        matcher=matcher,
        handler=handler,
        priority=100,
        replay_safe=True,
    )
