"""Thin terminal CLI for the ZN resident: ``zn work ...`` / ``zn approval ...``.

This module is deliberately a thin client, not a second control plane. It
reads the resident endpoint file published by
:mod:`zn_agent.core.resident_server` (``<ZN home>/kernel/resident-endpoint.json``),
authenticates with the per-process session secret, and forwards one JSON-RPC
call per command to the already-existing Daemon RPC methods
(``work_list`` / ``work_get`` / ``work_create`` / ``work_submit`` /
``approval_list`` / ``approval_decide`` / ``approval_rule_delete`` /
``approval_undo`` / ``memory_list`` / ``team_list`` /
``routine_list`` / ``routine_get`` / ``routine_runs`` / ``routine_pause`` /
``routine_resume`` / ``diary_list`` / ``diary_get``). All policy, execution, approval and
persistence decisions stay server-side.

Running ``zn`` with no subcommand (or ``zn chat``) opens the interactive
chat REPL (:mod:`zn_agent.core.cli_repl`, TERM-1): natural-language turns
on one durable work thread, driven entirely through the same existing
RPC surface (``work_create`` / ``work_start`` / ``work_progress`` /
``work_cancel`` / ``work_get``).

``zn model check`` and ``zn skill usage`` / ``zn skill prune`` are local
commands too: ``model check`` reads the locally configured cognitive routes
(the same resolution the resident uses) and runs one bounded minimal probe
per route, so the model channel can be verified before/without a running
resident; the ``skill`` commands read the local skills root through the T2
read-only query surface (usage_count / last_used / zero-hit / dormant
lists) and never write or delete. ``zn skill prune`` is always a dry run:
deleting a dormant skill still needs human confirmation and is not wired
into the CLI. The model probe never prints credentials: only route
identities and scrubbed failure reasons are reported.

Fail-closed rules:

* Unknown commands, missing/invalid arguments, and conflicting decision
  flags are rejected by argument parsing (exit code 2) before any RPC is sent.
* A missing, malformed, stale, or non-loopback endpoint is refused without
  connecting (exit code 1).
* A refused connection, an authentication failure, a timeout, or an RPC
  ``ok: false`` response is reported as a readable error on stderr with a
  non-zero exit code. The CLI never prints a success message for a failed
  call and never retries a decision: ``approval decide`` is sent at most
  once per invocation.
* Errors are humanized (T2-5): each failure maps to a "what happened +
  what to do next" message (``zn: error:`` prefix, exit 1; exit 2 for bad
  arguments stays). Raw server payloads never print by default; they only
  appear with ``--verbose`` or ``ZN_DEBUG=1``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .home import get_zn_home
from .cli_format import colorize, kv, section, status_symbol, status_word, symbol, use_color
from .model_check import (
    DEFAULT_PROBE_TIMEOUT_SECONDS,
    check_model_routes,
    format_no_config_hint,
)

__all__ = ["CliError", "ResidentClient", "build_parser", "main", "run"]


DEFAULT_TIMEOUT_SECONDS = 120.0
_ENDPOINT_AUTH_SCHEME = "session-secret-v1"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class CliError(Exception):
    """A user-facing CLI failure: reported as ``zn: error: ...``, exit 1."""


# --- T2-5: humanized error copy -------------------------------------------
# Every failure the CLI can hit before (or without) a usable resident is
# mapped here to a "what happened + what to do next" message in plain
# language. The ``zn: error:`` prefix and the exit-code contract (1 =
# business failure, 2 = bad arguments) are unchanged; only the copy is
# humanized. Raw server payloads are never dumped by default: they only
# print when the user passes ``--verbose`` or sets ``ZN_DEBUG=1``.

_SHOW_ERROR_DETAILS = False


def _set_error_details(verbose: bool) -> None:
    """Enable raw error details for this process (``--verbose``)."""
    global _SHOW_ERROR_DETAILS
    _SHOW_ERROR_DETAILS = bool(verbose)


def _error_details_visible() -> bool:
    return _SHOW_ERROR_DETAILS or os.environ.get("ZN_DEBUG") == "1"


_ERROR_COPY: dict[str, tuple[str, str]] = {
    # key: (lead-line template, next-step template; "" = no next step)
    "endpoint_missing": (
        "ZN 常驻服务没在运行（does not appear to be running；或 ZN home 不对）："
        "找不到 endpoint 文件 (endpoint not found)：{path}",
        "下一步：检查 ZN_HOME 是否正确，或启动常驻服务（zn-resident）",
    ),
    "endpoint_unreadable": (
        "ZN 常驻服务没在运行（或 ZN home 不对）：endpoint 文件损坏，"
        "无法解析为 JSON (not readable as JSON)：{path}（{detail}）",
        "下一步：检查 ZN_HOME 是否正确，或重启常驻服务重建 endpoint 文件",
    ),
    "endpoint_not_object": (
        "ZN 常驻服务没在运行（或 ZN home 不对）：endpoint 文件内容不是 "
        "JSON 对象：{path}",
        "下一步：检查 ZN_HOME 是否正确，或重启常驻服务重建 endpoint 文件",
    ),
    "endpoint_bad_version": (
        "CLI 与常驻服务版本不一致：endpoint 版本为 {version!r}，"
        "本 CLI 只支持版本 2（{path}）",
        "下一步：升级 ZN 到最新版本后重试",
    ),
    "endpoint_bad_transport": (
        "endpoint 文件中的传输方式不受支持：{transport!r}（{path}）",
        "下一步：重启常驻服务重建 endpoint 文件",
    ),
    "endpoint_non_loopback": (
        "拒绝连接：resident 控制面只允许本机（non-loopback），endpoint 文件中的主机 "
        "{host} 不是本机地址（{path}）",
        "下一步：检查 endpoint 文件是否被篡改，或检查 ZN_HOME 是否正确",
    ),
    "endpoint_bad_port": (
        "ZN 常驻服务没在运行（或 ZN home 不对）：endpoint 文件中的端口"
        "非法：{port!r}（{path}）",
        "下一步：检查 ZN_HOME 是否正确，或重启常驻服务重建 endpoint 文件",
    ),
    "endpoint_bad_auth": (
        "endpoint 文件中的认证方式不受支持：{scheme!r}（{path}）",
        "下一步：重启常驻服务重建 endpoint 文件",
    ),
    "endpoint_bad_secret": (
        "endpoint 文件中的会话密钥缺失或过短 (secret)（{path}）",
        "下一步：重启常驻服务重建 endpoint 文件",
    ),
    "endpoint_stale": (
        "endpoint 文件已过期 (stale)：记录的 resident 进程（pid {pid}）已不"
        "存在（{path}）",
        "下一步：重启常驻服务（zn-resident）",
    ),
    "connect_failed": (
        "连不上 ZN 常驻服务（could not reach {host}:{port}）：{detail}",
        "下一步：服务可能正在启动，稍后重试；若持续失败，检查 ZN_HOME "
        "是否正确或重启常驻服务",
    ),
    "connection_lost": (
        "与 ZN 常驻服务的连接在请求中途断开（{method}）：{detail}",
        "下一步：稍后重试；若持续失败，重启常驻服务",
    ),
    "auth_failed": (
        "resident 认证失败：{detail}",
        "下一步：endpoint 文件可能已过期，重启常驻服务（zn-resident）",
    ),
    "rpc_rejected": (
        "服务端返回错误（{method}）：{detail}",
        "",
    ),
    "response_closed": (
        "服务在返回响应前关闭了连接（{what}）",
        "下一步：稍后重试；若持续失败，重启常驻服务",
    ),
    "response_not_bytes": (
        "服务返回了无法解析的响应（{what}）：不是字节流",
        "下一步：重启常驻服务；若持续出现请反馈",
    ),
    "response_bad_json": (
        "服务返回了无法解析的响应（{what}）：不是合法 JSON（{detail}）",
        "下一步：重启常驻服务；若持续出现请反馈",
    ),
    "response_not_object": (
        "服务返回了无法解析的响应（{what}）：不是 JSON 对象",
        "下一步：重启常驻服务；若持续出现请反馈",
    ),
    "unexpected_result": (
        "服务返回了无法识别的结果（unexpected {method} result；版本可能不一致）",
        "下一步：升级 ZN 到最新版本；若已是最新版本请反馈",
    ),
}


def _cli_error(key: str, **fields: Any) -> CliError:
    """Build a humanized :class:`CliError` from the mapping table."""
    lead, next_step = _ERROR_COPY[key]
    message = lead.format(**fields)
    if next_step:
        message = f"{message}\n{next_step}"
    return CliError(message)


def _unexpected_result(method: str, result: Any) -> CliError:
    """Humanized error for a server result the CLI cannot interpret.

    The raw payload only prints with ``--verbose`` / ``ZN_DEBUG=1`` so a
    version-skewed resident can never flood the terminal with a raw dict.
    """
    err = _cli_error("unexpected_result", method=method)
    if _error_details_visible():
        return CliError(f"{err}\n原始内容：{result!r}")
    return err


def _one_line(value: Any, *, limit: int = 120) -> str:
    """Collapse untrusted text to one printable line for terminal output."""

    text = str(value or "")
    text = "".join(char if char.isprintable() else " " for char in text)
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: max(0, limit - 1)].rstrip() + "…"
    return text


_LONG_TEXT_MAX_LINES = 60  # T2-4: TTY pagination threshold for long text bodies


def _long_text(
    value: Any, *, max_lines: int = _LONG_TEXT_MAX_LINES, overflow_suffix: str = ""
) -> str:
    """Render untrusted long text for terminal output, keeping line structure.

    Unlike :func:`_one_line`, newlines survive: replies stay readable as
    written. Control characters are still neutralized (newlines and tabs
    pass through; anything else unprintable becomes a space) so resident
    text can never mangle the terminal.

    Pagination rule (T2-4): text longer than *max_lines* lines is shown in
    full whenever the output may be consumed by a script -- non-TTY,
    ``NO_COLOR``, or ``TERM=dumb`` -- so content is never silently dropped.
    Only on a real human terminal (:func:`use_color`) is the body cut to the
    first *max_lines* lines, followed by an overflow note; *overflow_suffix*
    lets the caller point the note at the full source (e.g. the command
    that shows the complete text).
    """
    raw_lines = str(value or "").split("\n")
    lines = [
        "".join(ch if ch == "\t" or ch.isprintable() else " " for ch in raw).rstrip()
        for raw in raw_lines
    ]
    # A trailing newline must not inflate the line count ("60 lines\\n" is 60).
    while lines and not lines[-1]:
        lines.pop()
    if len(lines) <= max_lines or not use_color():
        return "\n".join(lines)
    note = f"…（全文共 {len(lines)} 行，仅显示前 {max_lines} 行{overflow_suffix}）"
    return "\n".join(lines[:max_lines]) + "\n" + note


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int
    secret: str
    path: Path


def _default_endpoint_path() -> Path:
    return get_zn_home() / "kernel" / "resident-endpoint.json"


def _windows_pid_in_process_snapshot(pid: int) -> bool | None:
    """Second-opinion liveness check on Windows via the Toolhelp process list.

    ``os.kill(pid, 0)`` on Windows is ``OpenProcess`` under the hood, and a
    confirmed CI false positive showed it reporting a live pid as dead
    (``OSError`` with ``winerror == 87``). The Toolhelp snapshot enumerates
    the kernel's process list without opening the target, so a pid present
    here is definitively alive regardless of what ``OpenProcess`` said.

    Returns True when the pid is listed, False when it is definitively
    absent, None when the snapshot could not be taken (the caller then falls
    back to the ``os.kill`` verdict) or on non-Windows platforms.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes

        TH32CS_SNAPPROCESS = 0x00000002

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.c_ulong),
                ("cntUsage", ctypes.c_ulong),
                ("th32ProcessID", ctypes.c_ulong),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", ctypes.c_ulong),
                ("cntThreads", ctypes.c_ulong),
                ("th32ParentProcessID", ctypes.c_ulong),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.c_ulong),
                ("szExeFile", ctypes.c_wchar * 260),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_snapshot = kernel32.CreateToolhelp32Snapshot
        create_snapshot.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
        create_snapshot.restype = ctypes.c_void_p
        process_first = kernel32.Process32FirstW
        process_first.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32)]
        process_first.restype = ctypes.c_bool
        process_next = kernel32.Process32NextW
        process_next.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32)]
        process_next.restype = ctypes.c_bool
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_bool

        snapshot = create_snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            return None
        try:
            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
            listed = process_first(snapshot, ctypes.byref(entry))
            while listed:
                if entry.th32ProcessID == pid:
                    return True
                listed = process_next(snapshot, ctypes.byref(entry))
            return False
        finally:
            close_handle(snapshot)
    except Exception:
        return None


def _pid_is_dead(pid: int) -> bool:
    """True only when the OS positively reports the pid does not exist.

    POSIX reports a dead pid as ``ProcessLookupError`` (ESRCH). Windows
    reports it as ``OSError`` with ``winerror == 87``
    (ERROR_INVALID_PARAMETER from OpenProcess). Any other failure --
    notably access denied for a live process owned by someone else -- is
    inconclusive and treated as alive; the connect attempt below decides.

    Windows caveat: ``OpenProcess`` has a confirmed false positive where it
    reports a live pid as dead (winerror 87). On a dead verdict the Toolhelp
    process snapshot gets the final word: a pid present in the snapshot is
    alive, so the stale-endpoint verdict is withheld and the real connection
    attempt decides instead.
    """

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        dead_signal = True
    except PermissionError:
        return False
    except OSError as exc:
        dead_signal = getattr(exc, "winerror", None) == 87
        if not dead_signal:
            return False
    else:
        return False
    if _windows_pid_in_process_snapshot(pid) is True:
        # Spurious winerror 87: the kernel's process list still has this pid.
        return False
    return True


def load_endpoint(
    explicit: str | None = None, *, environ: dict[str, str] | None = None
) -> Endpoint:
    """Load and validate the resident endpoint file. Fail closed on any defect."""

    env = environ if environ is not None else os.environ
    raw_path = (explicit or "").strip() or (env.get("ZN_RESIDENT_ENDPOINT") or "").strip()
    path = Path(raw_path).expanduser() if raw_path else _default_endpoint_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise _cli_error("endpoint_missing", path=path) from None
    except (OSError, ValueError) as exc:
        raise _cli_error("endpoint_unreadable", path=path, detail=exc) from None
    if not isinstance(payload, dict):
        raise _cli_error("endpoint_not_object", path=path)

    version = payload.get("version")
    if version is not None and version != 2:
        raise _cli_error("endpoint_bad_version", version=version, path=path)
    transport = payload.get("transport")
    if transport is not None and transport != "tcp":
        raise _cli_error("endpoint_bad_transport", transport=transport, path=path)
    host = str(payload.get("host") or "").strip().lower()
    if host not in _LOOPBACK_HOSTS:
        raise _cli_error("endpoint_non_loopback", host=host, path=path)
    if host == "localhost":
        host = "127.0.0.1"
    try:
        port = int(payload.get("port") or 0)
    except (TypeError, ValueError):
        raise _cli_error(
            "endpoint_bad_port", port=payload.get("port"), path=path
        ) from None
    if not 0 < port < 65536:
        raise _cli_error("endpoint_bad_port", port=payload.get("port"), path=path)
    auth = payload.get("authentication")
    if not isinstance(auth, dict) or auth.get("scheme") != _ENDPOINT_AUTH_SCHEME:
        raise _cli_error(
            "endpoint_bad_auth",
            scheme=auth.get("scheme") if isinstance(auth, dict) else auth,
            path=path,
        )
    secret = auth.get("secret")
    if not isinstance(secret, str) or len(secret) < 32:
        raise _cli_error("endpoint_bad_secret", path=path)
    pid = payload.get("pid")
    if isinstance(pid, int) and pid > 0 and pid != os.getpid() and _pid_is_dead(pid):
        raise _cli_error("endpoint_stale", pid=pid, path=path)
    return Endpoint(host=host, port=port, secret=secret, path=path)


class ResidentClient:
    """One-shot authenticated JSON-RPC client over the resident socket."""

    def __init__(
        self,
        endpoint: Endpoint,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        connect_fn=None,
    ):
        self.endpoint = endpoint
        self.timeout = max(0.1, float(timeout))
        self._connect_fn = connect_fn or socket.create_connection

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        request_id = f"zn-cli-{time.time_ns()}"
        try:
            raw_conn = self._connect_fn(
                (self.endpoint.host, self.endpoint.port), timeout=self.timeout
            )
        except (OSError, TimeoutError) as exc:
            raise _cli_error(
                "connect_failed",
                host=self.endpoint.host,
                port=self.endpoint.port,
                detail=exc,
            ) from None
        try:
            if hasattr(raw_conn, "makefile"):
                stream = raw_conn.makefile("rb")
            else:  # pragma: no cover - defensive; create_connection returns sockets
                stream = raw_conn
            with raw_conn:
                raw_conn.settimeout(self.timeout)
                self._send(
                    raw_conn,
                    {"id": f"{request_id}-auth", "method": "authenticate",
                     "params": {"secret": self.endpoint.secret}},
                )
                auth = self._read(stream, "authentication")
                if not auth.get("ok"):
                    raise _cli_error(
                        "auth_failed",
                        detail=auth.get("error") or "unknown reason",
                    )
                self._send(
                    raw_conn,
                    {"id": request_id, "method": method, "params": params or {}},
                )
                response = self._read(stream, f"RPC {method!r}")
        except CliError:
            raise
        except (OSError, TimeoutError) as exc:
            raise _cli_error("connection_lost", method=method, detail=exc) from None
        if not response.get("ok"):
            raise _cli_error(
                "rpc_rejected",
                method=method,
                detail=response.get("error") or "unknown error",
            )
        return response.get("result")

    @staticmethod
    def _send(conn, payload: dict[str, Any]) -> None:
        conn.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))

    @staticmethod
    def _read(stream, what: str) -> dict[str, Any]:
        raw = stream.readline()
        if not raw:
            raise _cli_error("response_closed", what=what)
        if not isinstance(raw, (bytes, bytearray)):
            raise _cli_error("response_not_bytes", what=what)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise _cli_error("response_bad_json", what=what, detail=exc) from None
        if not isinstance(parsed, dict):
            raise _cli_error("response_not_object", what=what)
        return parsed


def _require_positive_int(value: str, *, name: str, maximum: int) -> int:
    try:
        parsed = int(value, 10)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{name} must be an integer") from None
    if parsed < 1 or parsed > maximum:
        raise argparse.ArgumentTypeError(f"{name} must be between 1 and {maximum}")
    return parsed


def _require_positive_float(value: str, *, name: str, maximum: float) -> float:
    try:
        parsed = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{name} must be a number") from None
    if not parsed > 0 or parsed > maximum:
        raise argparse.ArgumentTypeError(f"{name} must be between 0 and {maximum:g}")
    return parsed


def _require_non_empty(value: str, *, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise argparse.ArgumentTypeError(f"{name} must not be empty")
    return text


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _require_date(value: str, *, name: str) -> str:
    """Validate a ``YYYY-MM-DD`` date argument (e.g. for ``diary get``).

    argparse surfaces an :class:`argparse.ArgumentTypeError` as a usage
    error (exit 2) with the offending value, matching the other
    ``_require_*`` validators. The strict shape check comes first so
    values like ``20261022`` or ``2026-1-1`` are rejected even though
    ``date.fromisoformat`` would accept some of them on newer Pythons;
    the real calendar check (no Feb 30) comes second.
    """
    text = str(value or "").strip()
    try:
        valid = bool(_DATE_RE.match(text)) and date.fromisoformat(text)
    except ValueError:
        valid = False
    if not valid:
        raise argparse.ArgumentTypeError(
            f"{name} must be YYYY-MM-DD (e.g. 2026-10-22), got {text!r}"
        )
    return text


def _client(args: argparse.Namespace) -> ResidentClient:
    endpoint = load_endpoint(getattr(args, "endpoint", None))
    return ResidentClient(endpoint, timeout=args.timeout)


def _emit(args: argparse.Namespace, result: Any, *, human: str) -> None:
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(human)


# --- T3-4: "what next" hint for empty results --------------------------------
# An empty listing prints its "no ..." line and, on a real human terminal
# only, one dim follow-up line naming the most useful next command.
# ``--json`` branches return before any empty print, and ``use_color()`` is
# false on pipes, under ``NO_COLOR``, or on ``TERM=dumb``, so script
# consumers never see this line. Hint copy stays in Chinese like the T2-5
# error copy; the historic "no ..." lines are untouched (script-safe).
_EMPTY_RESULT_HINTS: dict[str, str] = {
    "work_list": "下一步：交办第一件事，运行 `zn work submit --task \"…\"`",
    "memory_list": "下一步：记住一件关于你的事，运行 `zn memory remember --key \"…\" --value \"…\"`",
    "team_list": "下一步：交办一件事，团队会在任务里自动组建，运行 `zn work submit --task \"…\"`",
    "suggestions_list": "下一步：看看 ZN 都会什么，运行 `zn help`",
    "routine_list": "下一步：跟 ZN 说一句话就能创建例行任务，比如「每天早上 8 点提醒我看今天的日程」",
    "diary_list": "下一步：日记是 ZN 在聊天里每天自动写的，跟它说「今天写了日记吗」就能看到",
    "approval_rules_list": "下一步：对一张卡用 `zn approval decide --request-id <id> --always-allow` 就会自动建一条规则",
    "approval_list": "下一步：审批卡由 ZN 在需要你确认时自动发出，先看看自动批准规则，运行 `zn approval rules list`",
}


def _print_empty_hint(kind: str) -> None:
    """Print the one-line "what next" hint for an empty human-mode listing."""
    hint = _EMPTY_RESULT_HINTS.get(kind)
    if hint and use_color():
        print(colorize(f"  {hint}", "dim"))


# --- D2: "what next" hint when pending cards are on screen -------------------
# When `zn approval list` shows at least one pending card in the current
# view, name the next step (look at a card, then decide). TTY-only via the
# same ``use_color()`` gate as ``_print_empty_hint``; the ``--json`` branch
# returns earlier, so piped / script output stays byte-stable. Copy follows
# the ``zn approval show`` decide guidance and T2-5 Chinese wording.
_APPROVAL_PENDING_HINT = (
    "下一步：先用 `zn approval show <request_id>` 看一张卡的详情，"
    "再用 `zn approval decide --request-id <id> --allow` 批准（或 `--deny` 拒绝）"
)


def _print_pending_hint() -> None:
    """Print the one-line D2 next-step hint for a non-empty approval view."""
    if use_color():
        print(colorize(f"  {_APPROVAL_PENDING_HINT}", "dim"))


def _cmd_work_list(args: argparse.Namespace) -> int:
    result = _client(args).call("work_list", {"limit": args.limit})
    if not isinstance(result, list):
        raise _unexpected_result("work_list", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    if not result:
        print("no work threads")
        _print_empty_hint("work_list")
        return 0
    for item in result:
        if not isinstance(item, dict):
            continue
        active = item.get("active_run") or {}
        active_event = active.get("event_id") if isinstance(active, dict) else None
        messages = item.get("messages")
        count = len(messages) if isinstance(messages, list) else 0
        print(
            f"{item.get('id') or '?'}  {_one_line(item.get('title'), limit=60)}  "
            f"updated={_one_line(item.get('updated_at'))}  messages={count}  "
            f"active={'yes:' + str(active_event) if active_event else 'no'}"
        )
    return 0


def _cmd_work_get(args: argparse.Namespace) -> int:
    result = _client(args).call(
        "work_get",
        {"thread_id": args.thread_id, "message_limit": args.message_limit},
    )
    if not isinstance(result, dict):
        raise _unexpected_result("work_get", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"{result.get('id') or args.thread_id}  {_one_line(result.get('title'), limit=80)}")
    print(f"created={result.get('created_at') or '-'}  updated={result.get('updated_at') or '-'}")
    messages = result.get("messages")
    if isinstance(messages, list) and messages:
        for message in messages:
            if not isinstance(message, dict):
                continue
            # T2-4: message bodies keep their line structure (this is the
            # full-text view `zn work submit` points at); long bodies
            # paginate on TTY only, never on non-TTY/NO_COLOR.
            print(f"[{message.get('created_at') or '-'}] {message.get('role') or '?'}:")
            body = _long_text(message.get("text"))
            if body:
                print("\n".join(f"  {line}" for line in body.splitlines()))
    else:
        print("(no messages)")
    return 0


# T2-2: `zn work submit` streams progress while the (unchanged, blocking)
# work_submit RPC runs on a background thread. Polling only *observes* via
# the read-only work_get (active_run discovery) and work_progress RPCs and
# never changes what the resident does; the submit RPC stays the source of
# truth for the final result. Presentation uses the cli_format contract only.
_WORK_SUBMIT_GRACE_SECONDS = 0.5  # runs finishing faster skip the display
_WORK_POLL_INTERVAL_SECONDS = 1.0  # TTY status-line refresh cadence
_WORK_POLL_RPC_TIMEOUT_SECONDS = 30.0  # per-call timeout for progress polls
_WORK_NONTTY_HEARTBEAT_SECONDS = 30.0  # piped/NO_COLOR heartbeat cadence


def _submit_work_blocking(
    client: ResidentClient,
    thread_id: str,
    task: str,
    box: dict[str, Any],
    done: threading.Event,
) -> None:
    """Run the blocking work_submit RPC; stash result/error for the watcher."""
    try:
        box["result"] = client.call(
            "work_submit", {"thread_id": thread_id, "task": task}
        )
    except Exception as exc:  # surfaced by the main thread, never swallowed
        box["error"] = exc
    finally:
        done.set()


def _progress_summary(
    progress: dict[str, Any],
    elapsed_s: float,
    *,
    stream=None,
    environ=None,
) -> str:
    """One-line human summary of a work_progress payload (T2-2).

    Uses only the cli_format contract (symbol/colorize/status_word/kv):
    non-color streams degrade to the plain words by themselves.
    """
    stage = progress.get("stage") or progress.get("status") or "working"
    parts = [kv("stage", status_word(stage, stream=stream, environ=environ))]
    next_action = _one_line(progress.get("next_action"), limit=80)
    if next_action:
        parts.append(next_action)
    invocations = progress.get("model_invocations")
    if isinstance(invocations, int) and not isinstance(invocations, bool):
        parts.append(kv("model_invocations", invocations))
    head = symbol("pending", stream=stream, environ=environ)
    head = f"{head} " if head else ""
    working = colorize("working", "dim", stream=stream, environ=environ)
    return f"{head}{working} {int(elapsed_s)}s  " + "  ".join(parts)


def _watch_work_submit(
    *,
    progress_client: ResidentClient,
    thread_id: str,
    done: threading.Event,
    args: argparse.Namespace,
    print_head,
) -> str | None:
    """Poll work_progress while the background work_submit RPC runs.

    Best-effort display only: any polling failure stops the watching, and the
    blocking work_submit RPC remains the source of truth for the outcome.
    Returns the thread title discovered via work_get (if any).
    """
    tty = use_color()
    stream = sys.stdout
    start = time.monotonic()
    deadline = start + args.timeout
    event_id: str | None = None
    discovered_title: str | None = None
    last_stage: str | None = None
    status_len = 0
    last_heartbeat = -_WORK_NONTTY_HEARTBEAT_SECONDS  # first tick prints
    try:
        while not done.is_set():
            now = time.monotonic()
            if now >= deadline:
                break
            elapsed = now - start
            try:
                if event_id is None:
                    snapshot = progress_client.call(
                        "work_get", {"thread_id": thread_id, "message_limit": 1}
                    )
                    if isinstance(snapshot, dict):
                        title = snapshot.get("title")
                        if isinstance(title, str) and title.strip():
                            discovered_title = title
                            print_head(title)
                        active = snapshot.get("active_run")
                        if isinstance(active, dict):
                            eid = active.get("event_id")
                            if isinstance(eid, str) and eid.strip():
                                event_id = eid.strip()
                    if event_id is None:
                        if done.wait(0.5):
                            break
                        continue
                presult = progress_client.call(
                    "work_progress",
                    {"thread_id": thread_id, "event_id": event_id},
                )
                progress = (
                    presult.get("progress") if isinstance(presult, dict) else None
                )
                if not isinstance(progress, dict):
                    break
            except CliError:
                break  # watching is best-effort; the submit RPC decides
            stage = str(progress.get("stage") or progress.get("status") or "working")
            if tty:
                if last_stage is not None and stage != last_stage:
                    stream.write("\r" + " " * status_len + "\r")
                    stream.write(
                        f"stage: {status_word(last_stage, stream=stream)} -> "
                        f"{status_word(stage, stream=stream)}\n"
                    )
                    stream.flush()
                    status_len = 0
                last_stage = stage
                line = _progress_summary(progress, elapsed, stream=stream)
                stream.write("\r" + line + " " * max(0, status_len - len(line)))
                stream.flush()
                status_len = len(line)
            else:
                last_stage = stage
                if elapsed - last_heartbeat >= _WORK_NONTTY_HEARTBEAT_SECONDS:
                    last_heartbeat = elapsed
                    print(
                        f"progress thread={thread_id} event={event_id} "
                        f"{_progress_summary(progress, elapsed, stream=stream)}",
                        file=stream,
                    )
            if progress.get("finalized"):
                break
            if progress.get("terminal") and progress.get("error"):
                break
            done.wait(_WORK_POLL_INTERVAL_SECONDS if tty else 1.0)
    except KeyboardInterrupt:
        # Stop watching only: the run keeps going on the resident, and the
        # user cancels it explicitly with `zn work cancel` if wanted.
        where = f"thread={thread_id}" + (f" event={event_id}" if event_id else "")
        hint = (
            f"zn work cancel --thread-id {thread_id} --event-id {event_id}"
            if event_id
            else f"zn work get --thread-id {thread_id}"
        )
        raise CliError(
            f"interrupted: stopped watching progress; the work keeps running "
            f"on the resident ({where}); use '{hint}' to stop it"
        ) from None
    if tty and status_len:
        stream.write("\r" + " " * status_len + "\r")
        stream.flush()
    return discovered_title


def _print_work_submit_result(result: dict[str, Any], thread_id: str) -> None:
    """Final human summary of a work_submit result (pre-T2-2 format kept)."""
    thread = result.get("thread") if isinstance(result.get("thread"), dict) else {}
    run = result.get("run") if isinstance(result.get("run"), dict) else {}
    if result.get("recovery_required"):
        print("recovery required: the work was recorded and needs a recovery step")
    elif run:
        print(
            f"run event={run.get('event_id') or '-'}  success={run.get('success')}  "
            f"cancelled={run.get('cancelled')}  path={run.get('execution_path') or '-'}  "
            f"model_invocations={run.get('model_invocations')}"
        )
        if run.get("response"):
            # T2-4: the reply keeps its line structure instead of being
            # crushed to one line. Long replies paginate to 60 lines on a
            # human terminal (with a pointer to the full text); non-TTY /
            # NO_COLOR output always stays complete for scripts.
            print(
                _long_text(
                    run.get("response"),
                    overflow_suffix=f"；全文见 `zn work get --thread-id {thread_id}`",
                )
            )


def _cmd_work_submit(args: argparse.Namespace) -> int:
    endpoint = load_endpoint(getattr(args, "endpoint", None))
    client = ResidentClient(endpoint, timeout=args.timeout)
    thread_id = args.thread_id
    title = args.title
    if not thread_id:
        created = client.call(
            "work_create",
            {"title": args.title or args.task[:100]},
        )
        if not isinstance(created, dict) or not created.get("id"):
            raise _unexpected_result("work_create", created)
        thread_id = str(created["id"])
        created_title = created.get("title")
        if isinstance(created_title, str) and created_title.strip():
            title = created_title
    if args.json:
        result = client.call(
            "work_submit",
            {"thread_id": thread_id, "task": args.task},
        )
        if not isinstance(result, dict):
            raise _unexpected_result("work_submit", result)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    head_printed = False

    def print_head(head_title) -> None:
        nonlocal head_printed
        if head_printed:
            return
        head_printed = True
        suffix = (
            f"  ({_one_line(head_title, limit=60)})"
            if isinstance(head_title, str) and head_title.strip()
            else ""
        )
        print(f"submitted to thread {thread_id}{suffix}")

    if args.thread_id is None:
        # New thread: the title is already known from work_create.
        print_head(title)
    # The blocking submit RPC runs on a background thread with its historic
    # semantics; the main thread only watches progress via work_progress.
    box: dict[str, Any] = {}
    done = threading.Event()
    progress_client = ResidentClient(
        endpoint, timeout=min(_WORK_POLL_RPC_TIMEOUT_SECONDS, args.timeout)
    )
    worker = threading.Thread(
        target=_submit_work_blocking,
        args=(client, thread_id, args.task, box, done),
        name="zn-work-submit",
        daemon=True,
    )
    worker.start()
    try:
        finished_fast = done.wait(_WORK_SUBMIT_GRACE_SECONDS)
    except KeyboardInterrupt:
        raise CliError(
            "interrupted: stopped watching progress; the work keeps running "
            f"on the resident (thread={thread_id}); use "
            f"'zn work get --thread-id {thread_id}' to check on it"
        ) from None
    if not finished_fast:
        _watch_work_submit(
            progress_client=progress_client,
            thread_id=thread_id,
            done=done,
            args=args,
            print_head=print_head,
        )
    # The submit RPC is the source of truth: wait for it, then report.
    try:
        worker.join()
    except KeyboardInterrupt:
        raise CliError(
            "interrupted: stopped watching progress; the work keeps running "
            f"on the resident (thread={thread_id}); use "
            f"'zn work get --thread-id {thread_id}' to check on it"
        ) from None
    if "error" in box:
        raise box["error"]
    result = box.get("result")
    if not isinstance(result, dict):
        raise _unexpected_result("work_submit", result)
    if not head_printed:
        thread = result.get("thread") if isinstance(result.get("thread"), dict) else {}
        print_head(thread.get("title"))
    _print_work_submit_result(result, thread_id)
    return 0


def _parse_approval_time(value: Any) -> datetime | None:
    """Parse an approval ``created_at``/``expires_at`` timestamp, or None."""
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _approval_waited_duration(item: dict[str, Any], now: datetime | None = None) -> str:
    """How long a pending approval card has been waiting (``""`` when unknown).

    ``now`` is injectable for tests; otherwise wall-clock UTC is used.
    """
    if str(item.get("status") or "") != "pending":
        return ""
    created = _parse_approval_time(item.get("created_at"))
    if created is None:
        return ""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    seconds = int((moment - created).total_seconds())
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return f"{seconds}s"
    minutes, _ = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def _format_approval_card(
    item: dict[str, Any], now: datetime | None = None
) -> str:
    """Two-line approval card (T2-3): headline + indented detail line.

    Headline: ``<request_id> [<status>] <action_kind>`` (status colored via
    the cli_format contract on TTY; a status glyph is prepended on TTY
    via ``status_symbol`` -- non-TTY output stays byte-identical).
    Detail line: ``target= scope= expires=`` plus ``waited=`` for pending
    cards with a known ``created_at``. Non-TTY/NO_COLOR output is plain
    text.
    """
    status = item.get("status") or "?"
    mark = status_symbol(status)
    head = (
        f"{mark + ' ' if mark else ''}"
        f"{item.get('request_id') or '?'}  "
        f"[{status_word(status)}]  "
        f"{item.get('action_kind') or '?'}"
    )
    detail = [
        kv("target", _one_line(item.get("target"), limit=60)),
        kv("scope", _one_line(item.get("scope"), limit=40)),
        kv("expires", item.get("expires_at") or "-"),
    ]
    duration = _approval_waited_duration(item, now=now)
    if duration:
        detail.append(kv("waited", duration))
    return head + "\n" + "  " + "  ".join(detail)


def _format_approval_detail(item: dict[str, Any], now: datetime | None = None) -> str:
    """Full detail view of one approval card (``zn approval show``).

    Renders every field the ``approval_list`` RPC already returns, skipping
    empty ones; labels are plain Chinese text, the status word follows the
    cli_format contract (colored only on TTY, glyph prepended on TTY).
    """
    request_id = str(item.get("request_id") or "?")
    status = item.get("status") or "?"
    mark = status_symbol(status)
    kind = _one_line(item.get("action_kind"), limit=40) or "?"
    lines = [f"{mark + ' ' if mark else ''}审批卡 {request_id}  [{status_word(status)}]  {kind}"]
    rows: list[tuple[str, str]] = []
    for label, key in (
        ("目标", "target"),
        ("范围", "scope"),
        ("来源", "source"),
        ("关联事件", "event_id"),
    ):
        value = _one_line(item.get(key), limit=120)
        if value:
            rows.append((label, value))
    created = _parse_approval_time(item.get("created_at"))
    if created is not None:
        stamp = _one_line(item.get("created_at"), limit=40)
        duration = _approval_waited_duration(item, now=now)
        if duration:
            stamp = f"{stamp}（已等待 {duration}）"
        rows.append(("创建时间", stamp))
    expires = _one_line(item.get("expires_at"), limit=40)
    if expires:
        rows.append(("失效时间", expires))
    decision = _one_line(item.get("decision"), limit=40)
    if decision:
        rows.append(("决定", decision))
    decided_at = _one_line(item.get("decided_at"), limit=40)
    if decided_at:
        rows.append(("决定时间", decided_at))
    value_text = _one_line(item.get("value_text"), limit=200)
    if value_text:
        rows.append(("内容摘要", value_text))
    approved_command = _one_line(item.get("approved_command"), limit=200)
    if approved_command:
        rows.append(("用户编辑过的命令", approved_command))
    diff_text = str(item.get("diff_text") or "")
    if diff_text:
        diff_lines = diff_text.splitlines()
        preview = "\n".join(f"    {line}" for line in diff_lines[:15])
        if len(diff_lines) > 15:
            preview += f"\n    （已截断，共 {len(diff_lines)} 行）"
        rows.append(("diff 预览", "\n" + preview))
    review_note = _one_line(item.get("review_note"), limit=200)
    if review_note:
        rows.append(("备注", review_note))
    if item.get("previous_captured"):
        rows.append(("撤销快照", "有（可撤销）"))
    if item.get("undone"):
        rows.append(("已撤销", "是"))
    for label, value in rows:
        lines.append(f"  {label}：{value}")
    lines.append(
        f"  下一步：用 'zn approval decide --request-id {request_id} --allow' 批准，"
        "或 '--deny' 拒绝"
    )
    return "\n".join(lines)


def _find_approval_card(result: dict[str, Any], request_id: str) -> dict[str, Any] | None:
    """Locate one card by ``request_id`` in an ``approval_list`` result."""
    for key in ("pending", "denied", "expired", "applied"):
        items = result.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and str(item.get("request_id") or "") == request_id:
                return item
    return None


def _cmd_approval_show(args: argparse.Namespace) -> int:
    wanted = str(args.request_id)
    result = _client(args).call("approval_list", {})
    if not isinstance(result, dict):
        raise _unexpected_result("approval_list", result)
    item = _find_approval_card(result, wanted)
    if item is None:
        raise CliError(
            f"找不到审批卡 '{wanted}'。"
            "用 'zn approval list --status all' 看看现有的卡片。"
        )
    if args.json:
        print(json.dumps(item, ensure_ascii=False, indent=2, default=str))
        return 0
    print(_format_approval_detail(item))
    return 0


def _cmd_approval_list(args: argparse.Namespace) -> int:
    result = _client(args).call("approval_list", {})
    if not isinstance(result, dict):
        raise _unexpected_result("approval_list", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    wanted = args.status
    sections = (
        ("pending", "pending"),
        ("denied", "denied"),
        ("expired", "expired"),
        ("applied", "applied"),
    )
    shown = False
    any_items = False
    pending_shown = False
    for key, label in sections:
        if wanted != "all" and wanted != key:
            continue
        items = result.get(key)
        if not isinstance(items, list):
            continue
        print(section(label, len(items)))
        shown = True
        if not items:
            print("(none)")
            continue
        any_items = True
        for item in items:
            if isinstance(item, dict):
                print(_format_approval_card(item))
                if key == "pending":
                    pending_shown = True
    if not shown:  # pragma: no cover - argparse restricts --status choices
        raise CliError(f"unknown approval status filter: {wanted!r}")
    if not any_items:
        # D1: empty approval list names the most useful next step, like the
        # other T3-4 lists. TTY-only (use_color), so piped/JSON output is
        # byte-stable for scripts.
        _print_empty_hint("approval_list")
    elif pending_shown:
        # D2: the current view shows at least one pending card; name the
        # next step. TTY-only like the D1/T3-4 hints, so --status views
        # without pending cards (denied/expired/applied) stay unchanged.
        _print_pending_hint()
    return 0


_DECISION_FLAGS = {
    "allow": "allow_once",
    "deny": "deny",
    "always_allow": "always_allow",
}


def _cmd_approval_decide(args: argparse.Namespace) -> int:
    chosen = [name for name in _DECISION_FLAGS if getattr(args, name, False)]
    if len(chosen) != 1:  # pragma: no cover - argparse enforces exactly one
        raise CliError(
            "approval decide requires exactly one of --allow, --deny, --always-allow"
        )
    decision = _DECISION_FLAGS[chosen[0]]
    result = _client(args).call(
        "approval_decide",
        {"request_id": args.request_id, "decision": decision},
    )
    if not isinstance(result, dict) or not isinstance(result.get("request"), dict):
        raise _unexpected_result("approval_decide", result)
    request = result["request"]
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    print(
        f"{request.get('request_id') or args.request_id}  "
        f"status={request.get('status') or '?'}  decision={request.get('decision') or decision}"
    )
    return 0


# --- T11: `zn approval rules ...` / `zn approval undo` -----------------------
# Terminal face for the daemon's approval rule list/delete and the
# one-click undo of an applied (consumed) approval. Rules list rides the
# ``"rules"`` payload of the existing ``approval_list`` RPC; rule delete
# and undo call ``approval_rule_delete`` / ``approval_undo``. No new
# daemon RPC, no daemon.py changes. Rule *creation* is intentionally not
# duplicated here: ``zn approval decide --always-allow`` is the existing
# path that creates an auto-allow rule. ``approval_reconsider_denied``
# belongs to a different family (denied cards, not consumed changes) and
# stays on the chat path; it is a follow-up candidate, not this slice.
#
# Offline contract (T2-6 style, like diary/routine): every command exits 0
# when the resident is unreachable and prints a human note; delete/undo
# never claim a mutation happened offline. Server-side rejections
# (RPC ok:false) surface as humanized errors (T2-5), exit 1.

_APPROVAL_T11_RPC_REJECTED_PREFIX = _ERROR_COPY["rpc_rejected"][0].split("{method}")[0]


def _approval_t11_rpc(
    args: argparse.Namespace, method: str, params: dict[str, Any]
) -> tuple[bool, Any]:
    """Call one approval-sidecar RPC, classifying failures.

    Returns ``(True, result)`` on success, or ``(False, error_text)`` when
    the call never got a usable answer from the resident (missing / bad
    endpoint, connection, auth or transport problems) -- the offline path.
    A server-side rejection (``ok: false``) re-raises as :class:`CliError`
    so the humanized ``rpc_rejected`` copy reaches stderr with exit 1.
    """
    try:
        return True, _client(args).call(method, params)
    except CliError as exc:
        text = str(exc)
        if text.startswith(_APPROVAL_T11_RPC_REJECTED_PREFIX):
            raise
        return False, text


def _approval_t11_offline(
    args: argparse.Namespace,
    error: str,
    *,
    unavailable: str,
    json_payload: dict[str, Any],
) -> int:
    """T2-6-style offline rendering for the T11 commands: exit 0.

    *unavailable* names what could not be done ("看不到审批规则列表",
    "没有撤销任何变更", ...). Never claims a mutation happened.
    """
    if args.json:
        print(
            json.dumps(
                {
                    "daemon_reachable": False,
                    "daemon_error": _one_line(error, limit=200),
                    **json_payload,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 0
    print(f"常驻服务未运行（unreachable）：{unavailable}")
    print("下一步：检查 ZN_HOME 是否正确，或启动常驻服务（zn-resident）")
    return 0


def _format_approval_rule_line(item: dict[str, Any]) -> str:
    """One-line list row for an approval rule: id + effect + kind + scope."""
    rule_id = _one_line(item.get("rule_id"), limit=24) or "?"
    effect = str(item.get("effect") or "?")
    # ``auto_allow`` is the always-allow word from the T2-7 vocabulary;
    # anything else passes through unchanged (fail-closed).
    effect_word = status_word("always_allow" if effect == "auto_allow" else effect)
    kind = _one_line(item.get("action_kind"), limit=24) or "?"
    line = f"{rule_id}  [{effect_word}]  {kind}"
    scope = _one_line(item.get("scope"), limit=60)
    if scope:
        line += f"  scope={scope}"
    return line


def _cmd_approval_rules_list(args: argparse.Namespace) -> int:
    ok, payload = _approval_t11_rpc(args, "approval_list", {})
    if not ok:
        return _approval_t11_offline(
            args,
            payload,
            unavailable="看不到审批规则列表",
            json_payload={"rules": []},
        )
    if not isinstance(payload, dict):
        raise _unexpected_result("approval_list", payload)
    rules = payload.get("rules")
    if not isinstance(rules, list):
        raise _unexpected_result("approval_list", rules)
    if args.json:
        print(json.dumps(rules, ensure_ascii=False, indent=2, default=str))
        return 0
    if not rules:
        print("no approval rules")
        _print_empty_hint("approval_rules_list")
        return 0
    print(section("approval rules", len(rules)))
    for item in rules:
        if isinstance(item, dict):
            print(_format_approval_rule_line(item))
    return 0


def _unknown_approval_rule_error(exc: CliError, rule_id: str) -> CliError:
    """Swap the raw server ``ValueError: unknown approval rule`` for human copy.

    The daemon answers ``ok: false`` with ``ValueError: unknown approval
    rule`` (see the ``approval_rule_delete`` dispatch in daemon.py); this
    turns it into "not found + where to look". Any other error is
    returned unchanged.
    """
    if "unknown approval rule" in str(exc):
        return CliError(
            f"找不到审批规则 '{rule_id}'（unknown approval rule）。"
            "用 'zn approval rules list' 看看现有的规则。"
        )
    return exc


def _cmd_approval_rules_delete(args: argparse.Namespace) -> int:
    rule_id = str(args.rule_id)
    try:
        ok, payload = _approval_t11_rpc(
            args, "approval_rule_delete", {"rule_id": rule_id}
        )
    except CliError as exc:
        raise _unknown_approval_rule_error(exc, rule_id)
    if not ok:
        return _approval_t11_offline(
            args,
            payload,
            unavailable=f"没有删除任何审批规则（'{rule_id}' 还在）",
            json_payload={"deleted": False, "rule_id": rule_id},
        )
    if not isinstance(payload, dict) or payload.get("deleted") is not True:
        raise _unexpected_result("approval_rule_delete", payload)
    if args.json:
        print(
            json.dumps(
                {"deleted": True, "rule_id": rule_id},
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 0
    print(f"已删除审批规则 {rule_id}（deleted）：这条自动放行规则不再生效")
    return 0


def _humanize_undo_error(exc: CliError, request_id: str) -> CliError:
    """Turn the ``approval_undo`` server rejections into human copy (T2-5).

    The daemon raises ValueError with one English reason per failure mode
    (see ``undo_approved_change`` in approval_review.py); each becomes a
    Chinese lead line with the English fragment kept in parentheses so the
    server contract stays greppable. Unknown errors pass through.
    """
    text = str(exc)
    if "unknown approval request" in text:
        return CliError(
            f"找不到审批卡 '{request_id}'（unknown approval request）。"
            "用 'zn approval list --status applied' 看看可撤销的已执行申请。"
        )
    if "only an applied (consumed) approval can be undone" in text:
        return CliError(
            f"这张卡还不能撤销（only consumed approvals can be undone）：'{request_id}' "
            "不是已执行的申请。只有已执行（applied）的变更才能撤销。"
        )
    if "already undone" in text:
        return CliError(f"这条变更已经撤销过了（already undone）：'{request_id}'。")
    if "no undo snapshot" in text:
        return CliError(
            f"这条变更没有可用的撤销快照（no undo snapshot）：'{request_id}'，无法回滚。"
        )
    if "only workspace file changes can be undone" in text or "escapes the workspace" in text:
        return CliError(
            f"这条变更不在工作区文件范围内，无法撤销（not a workspace file change）：'{request_id}'。"
        )
    return exc


def _cmd_approval_undo(args: argparse.Namespace) -> int:
    request_id = str(args.request_id)
    try:
        ok, payload = _approval_t11_rpc(
            args, "approval_undo", {"request_id": request_id}
        )
    except CliError as exc:
        raise _humanize_undo_error(exc, request_id)
    if not ok:
        return _approval_t11_offline(
            args,
            payload,
            unavailable=f"没有撤销任何变更（'{request_id}' 保持原样）",
            json_payload={"undone": False, "request_id": request_id},
        )
    if not isinstance(payload, dict):
        raise _unexpected_result("approval_undo", payload)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    path = _one_line(payload.get("path"), limit=80)
    note = _one_line(payload.get("note"), limit=120)
    checkpoint = _one_line(payload.get("pre_undo_checkpoint_id"), limit=40)
    if payload.get("restored"):
        head = f"{request_id}  已撤销（undone）：文件已恢复到变更前状态"
    else:
        head = f"{request_id}  无需改动（already at pre-change state）：文件本来就是变更前的样子"
    lines = [head]
    if path:
        lines.append(f"  文件：{path}")
    if note:
        lines.append(f"  说明：{note}")
    if checkpoint:
        lines.append(f"  兜底检查点：{checkpoint}（撤销前已自动备份）")
    print("\n".join(lines))
    return 0


def _cmd_memory_list(args: argparse.Namespace) -> int:
    result = _client(args).call("memory_list", {"limit": args.limit})
    if not isinstance(result, list):
        raise _unexpected_result("memory_list", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    if not result:
        print("no remembered facts")
        _print_empty_hint("memory_list")
        return 0
    for item in result:
        if not isinstance(item, dict):
            continue
        aliases = item.get("aliases")
        alias_text = (
            ", ".join(_one_line(alias, limit=40) for alias in aliases)
            if isinstance(aliases, list) and aliases
            else "-"
        )
        print(
            f"{_one_line(item.get('key'), limit=60)}  {kv('tier', _one_line(item.get('tier')))}  "
            f"{kv('sensitivity', _one_line(item.get('sensitivity') or 'normal'))}  "
            f"aliases={alias_text}  {kv('updated', _one_line(item.get('updated_at')))}"
        )
    return 0


def _cmd_team_list(args: argparse.Namespace) -> int:
    result = _client(args).call("team_list", {"limit": args.limit})
    if not isinstance(result, list):
        raise _unexpected_result("team_list", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    if not result:
        print("no active teams")
        _print_empty_hint("team_list")
        return 0
    for item in result:
        if not isinstance(item, dict):
            continue
        roster = item.get("roster")
        roster_text = (
            ", ".join(_one_line(member, limit=40) for member in roster)
            if isinstance(roster, list) and roster
            else "-"
        )
        print(
            f"{_one_line(item.get('team_id'), limit=40)}  "
            f"status={_one_line(item.get('status'))}  roster={roster_text}"
        )
        objective = _one_line(item.get("project_title"), limit=80)
        if objective:
            print(f"  objective: {objective}")
    return 0


def _cmd_memory_remember(args: argparse.Namespace) -> int:
    params: dict[str, Any] = {"key": args.key, "value": args.value}
    if args.sensitivity is not None:
        # Only sent when the user picked a tier: omitting it lets the
        # resident keep an existing fact's sensitivity (Q11 semantics).
        params["sensitivity"] = args.sensitivity
    result = _client(args).call("remember", params)
    if not isinstance(result, dict) or not result.get("saved"):
        raise _unexpected_result("remember", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    sensitivity = args.sensitivity or "unchanged"
    print(f"saved memory key={result.get('key') or args.key}  sensitivity={sensitivity}")
    return 0


def _cmd_memory_forget(args: argparse.Namespace) -> int:
    if not args.yes:
        try:
            answer = input(
                f"forget memory key {args.key!r}? this cannot be undone [y/N]: "
            )
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print(f"aborted: memory key {args.key!r} was NOT forgotten")
            return 1
    result = _client(args).call("forget", {"key": args.key})
    if not isinstance(result, dict) or not result.get("forgotten"):
        raise _unexpected_result("forget", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"forgot memory key={result.get('key') or args.key}")
    return 0


def _cmd_memory_export(args: argparse.Namespace) -> int:
    # The export file lands on the resident machine (path is resolved
    # server-side); the result tells the user where it went.
    result = _client(args).call("memory_export", {"path": args.out})
    if not isinstance(result, dict) or not isinstance(result.get("exported"), int):
        raise _unexpected_result("memory_export", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"exported {result['exported']} facts → {result.get('file')}")
    return 0


def _cmd_memory_import(args: argparse.Namespace) -> int:
    result = _client(args).call(
        "memory_import", {"path": args.in_file, "overwrite": args.overwrite}
    )
    if not isinstance(result, dict) or not isinstance(result.get("imported"), int):
        raise _unexpected_result("memory_import", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    print(
        f"imported={result['imported']}  skipped={result['skipped']}  "
        f"overwritten={result['overwritten']}"
    )
    return 0


def _format_timeline_entry(entry: dict[str, Any]) -> str:
    at = _one_line(entry.get("at") or "-", limit=19)
    kind = _one_line(entry.get("kind") or "message", limit=16)
    author = _one_line(entry.get("from_author") or entry.get("author") or "?", limit=32)
    line = f"[{at}] {kind} {author}"
    to_author = _one_line(entry.get("to_author"), limit=32)
    if to_author:
        line += f" -> {to_author}"
    item_title = _one_line(entry.get("item_title"), limit=60)
    if item_title:
        line += f"  {item_title}"
    body = _long_text(entry.get("text"))
    if body:
        line += "\n" + "\n".join(f"    {text_line}" for text_line in body.splitlines())
    return line


def _cmd_team_timeline(args: argparse.Namespace) -> int:
    result = _client(args).call("team_timeline", {"thread_id": args.thread_id})
    if not isinstance(result, dict) or not isinstance(result.get("entries"), list):
        raise _unexpected_result("team_timeline", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    team_id = result.get("team_id") or "-"
    members = result.get("members")
    member_text = (
        ", ".join(_one_line(member, limit=32) for member in members)
        if isinstance(members, list) and members
        else "-"
    )
    print(f"team timeline  team={team_id}  members={member_text}  thread={args.thread_id}")
    entries = result["entries"]
    if not entries:
        print("(no timeline entries)")
        return 0
    for entry in entries:
        if isinstance(entry, dict):
            print(_format_timeline_entry(entry))
    return 0


def _cmd_work_cancel(args: argparse.Namespace) -> int:
    result = _client(args).call(
        "work_cancel",
        {"thread_id": args.thread_id, "event_id": args.event_id},
    )
    if not isinstance(result, dict) or not isinstance(result.get("progress"), dict):
        raise _unexpected_result("work_cancel", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    progress = result["progress"]
    print(
        f"cancelled event={args.event_id} on thread={args.thread_id}  "
        f"state={_one_line(progress.get('state') or progress.get('status') or '?')}"
    )
    cancelled = progress.get("cancelled")
    if cancelled is not None:
        print(f"  cancelled={cancelled}")
    reason = _one_line(progress.get("reason"), limit=120)
    if reason:
        print(f"  reason: {reason}")
    return 0


def _cmd_connector_list(args: argparse.Namespace) -> int:
    """List the known R-series connectors. Local only, no resident RPC."""

    from .connector_autoattach import describe_registry

    registry = describe_registry()
    if args.json:
        print(json.dumps(registry, ensure_ascii=False, indent=2, default=str))
        return 0
    for entry in registry:
        planes = "+".join(entry["planes"])
        creds = "credentials" if entry["requires_credentials"] else "keyless"
        print(
            f"{entry['r_series']:4} {entry['name']:16} {_one_line(entry['title'], limit=34):36} "
            f"{planes:10} {creds}"
        )
    return 0


def _cmd_connector_status(args: argparse.Namespace) -> int:
    """Show connector mount status: live daemon report, else local evaluation."""

    try:
        result = _client(args).call("connector_status", {})
    except CliError as exc:
        return _cmd_connector_status_offline(args, str(exc))
    if not isinstance(result, dict) or not isinstance(result.get("connectors"), list):
        raise _unexpected_result("connector_status", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"connector mount report (daemon, {result.get('generated_at') or 'unknown time'})")
    failed = 0
    for item in result["connectors"]:
        if not isinstance(item, dict):
            continue
        # T2-7: unified state glyph on TTY; the state words stay untouched
        # so off-TTY output keeps its historic bytes.
        if item.get("approved") and not item.get("mounted"):
            state, mark = "FAILED ", symbol("fail")
            failed += 1
        elif item.get("mounted"):
            state, mark = "mounted", symbol("ok")
        else:
            state, mark = "off    ", ""
        print(
            f"{mark + ' ' if mark else ''}"
            f"{_one_line(item.get('r_series'), limit=4):4} "
            f"{_one_line(item.get('name'), limit=16):16} "
            f"{state}  {_one_line(item.get('reason'), limit=100)}"
        )
    print(
        f"{result.get('mounted', 0)} of {result.get('approved', 0)} approved connector(s) mounted"
    )
    return 1 if failed else 0


def _cmd_connector_reload(args: argparse.Namespace) -> int:
    """Hot-reload connectors.yaml on the running daemon (no restart)."""

    try:
        result = _client(args).call("connector_reload", {})
    except CliError as exc:
        print(
            "daemon unreachable; connector reload needs a running daemon "
            f"({_one_line(str(exc), limit=120)})"
        )
        return 2
    if not isinstance(result, dict) or not isinstance(result.get("connectors"), list):
        raise _unexpected_result("connector_reload", result)
    failed = sum(
        1
        for item in result["connectors"]
        if isinstance(item, dict) and item.get("approved") and not item.get("mounted")
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        if result.get("reload_ok"):
            print(
                "connector reload ok "
                f"({result.get('generated_at') or 'unknown time'})"
            )
        else:
            print(
                "connector reload failed: "
                f"{_one_line(result.get('error'), limit=200)}"
            )
        for item in result["connectors"]:
            if not isinstance(item, dict):
                continue
            if item.get("approved") and not item.get("mounted"):
                state = "FAILED "
            elif item.get("mounted"):
                state = "mounted"
            else:
                state = "off    "
            print(
                f"{_one_line(item.get('r_series'), limit=4):4} "
                f"{_one_line(item.get('name'), limit=16):16} "
                f"{state}  {_one_line(item.get('reason'), limit=100)}"
            )
        print(
            f"{result.get('mounted', 0)} of {result.get('approved', 0)} "
            "approved connector(s) mounted"
        )
    if not result.get("reload_ok"):
        # Fail closed: the whitelist did not parse, so nothing changed.
        return 3
    return 1 if failed else 0


def _cmd_autonomy_list(args: argparse.Namespace) -> int:
    result = _client(args).call("autonomy_list")
    if not isinstance(result, list):
        raise _unexpected_result("autonomy_list", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    if not result:
        print(
            "no explicit autonomy policy entries "
            "(every domain defaults to require_approval)"
        )
        return 0
    for item in result:
        if not isinstance(item, dict):
            continue
        print(
            f"{_one_line(item.get('domain'), limit=48):48} "
            f"{_one_line(item.get('level'), limit=20):20} "
            f"updated={_one_line(item.get('updated_at'), limit=40)}"
        )
    return 0


def _cmd_autonomy_get(args: argparse.Namespace) -> int:
    result = _client(args).call("autonomy_get", {"domain": args.domain})
    if not isinstance(result, dict) or "level" not in result:
        raise _unexpected_result("autonomy_get", result)
    _emit(
        args,
        result,
        human=f"{_one_line(result.get('domain'), limit=48)}: "
        f"{_one_line(result.get('level'), limit=20)}",
    )
    return 0


def _cmd_autonomy_set(args: argparse.Namespace) -> int:
    result = _client(args).call(
        "autonomy_set", {"domain": args.domain, "level": args.level}
    )
    if not isinstance(result, dict) or "level" not in result:
        raise _unexpected_result("autonomy_set", result)
    _emit(
        args,
        result,
        human=(
            f"autonomy set: {_one_line(result.get('domain'), limit=48)} = "
            f"{_one_line(result.get('level'), limit=20)} "
            f"(was {_one_line(result.get('old_level'), limit=20)})"
        ),
    )
    return 0


def _cmd_suggestions_list(args: argparse.Namespace) -> int:
    result = _client(args).call("suggestions_list", {"limit": args.limit})
    if not isinstance(result, list):
        raise _unexpected_result("suggestions_list", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    if not result:
        print("no suggestions")
        _print_empty_hint("suggestions_list")
        return 0
    for item in result:
        if not isinstance(item, dict):
            continue
        print(
            f"{_one_line(item.get('key'), limit=64):64} "
            f"[{_one_line(item.get('kind'), limit=20)}] "
            f"{_one_line(item.get('title'), limit=80)}"
        )
    return 0


def _cmd_suggestions_dismiss(args: argparse.Namespace) -> int:
    result = _client(args).call("suggestions_dismiss", {"key": args.key})
    if not isinstance(result, dict) or not result.get("dismissed"):
        raise _unexpected_result("suggestions_dismiss", result)
    _emit(
        args,
        result,
        human=(
            f"dismissed suggestion {_one_line(result.get('key'), limit=64)} "
            f"(hidden until {_one_line(result.get('expires_at'), limit=40)})"
        ),
    )
    return 0


def _goal_result_or_not_installed(
    args: argparse.Namespace, result: Any, method: str
) -> dict[str, Any]:
    """Unwrap a goal_* RPC result; print an honest message when disabled.

    Returns the enabled dict, or raises CliError (printed to stderr, exit 1)
    when self-drive is not installed. In --json mode the raw payload is
    printed before the error so machines still get parseable JSON.
    """
    if not isinstance(result, dict) or "enabled" not in result:
        raise _unexpected_result(method, result)
    if not result.get("enabled"):
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        raise CliError(_one_line(result.get("reason") or "self-drive is not installed"))
    return result


def _cmd_goal_list(args: argparse.Namespace) -> int:
    result = _client(args).call("goal_list", {"limit": args.limit})
    result = _goal_result_or_not_installed(args, result, "goal_list")
    goals = result.get("goals")
    if not isinstance(goals, list):
        raise _unexpected_result("goal_list", result)
    if args.json:
        print(json.dumps(goals, ensure_ascii=False, indent=2, default=str))
        return 0
    if not goals:
        print("no self-drive goals")
        return 0
    for item in goals:
        if not isinstance(item, dict):
            continue
        blocked = _one_line(item.get("blocked_reason"), limit=64)
        blocked_suffix = f" [blocked: {blocked}]" if blocked else ""
        print(
            f"{_one_line(item.get('intention_id'), limit=24):24} "
            f"{_one_line(item.get('status'), limit=12):12} "
            f"{_one_line(item.get('origin'), limit=16):16} "
            f"{_one_line(item.get('objective'), limit=72)}{blocked_suffix}"
        )
    return 0


def _cmd_goal_status(args: argparse.Namespace) -> int:
    result = _client(args).call("goal_status", {})
    result = _goal_result_or_not_installed(args, result, "goal_status")
    goals = result.get("goals") if isinstance(result.get("goals"), list) else []
    errors = result.get("recent_errors") if isinstance(result.get("recent_errors"), list) else []
    notes = result.get("recent_notes") if isinstance(result.get("recent_notes"), list) else []
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    active = [g for g in goals if isinstance(g, dict) and g.get("status") == "active"]
    print(f"self-drive: {len(goals)} goal(s), {len(active)} active")
    for goal in active:
        print(
            f"  active: {_one_line(goal.get('intention_id'), limit=24)} — "
            f"{_one_line(goal.get('objective'), limit=80)}"
        )
    print(f"recent errors: {len(errors)}")
    for error in errors[:3]:
        print(f"  - {_one_line(error, limit=100)}")
    print(f"recent notes: {len(notes)}")
    return 0


# --- T9: `zn routine ...` --------------------------------------------------
# Terminal face for the daemon's routine_* RPCs (already dispatched in
# daemon.py ``_routine_result``): list / get / runs are read-only,
# pause / resume are the only mutations in this slice. propose / edit /
# confirm / delete / test_run stay on the chat path and are NOT exposed
# here. No new daemon RPC, no daemon.py changes.
#
# Offline contract (T2-6 style): every command exits 0 when the resident is
# unreachable and still prints a human note (what is unavailable + how to
# start the resident). pause / resume never print a success line offline:
# they report that nothing was changed (fail-closed: no false success).
# A server-side rejection (RPC ok:false, e.g. "unknown routine") is NOT
# swallowed: it surfaces as a humanized error on stderr, exit 1.

_ROUTINE_RPC_REJECTED_PREFIX = _ERROR_COPY["rpc_rejected"][0].split("{method}")[0]


def _routine_rpc(
    args: argparse.Namespace, method: str, params: dict[str, Any]
) -> tuple[bool, Any]:
    """Call one ``routine_*`` RPC, classifying failures.

    Returns ``(True, result)`` on success, or ``(False, error_text)`` when
    the call never got a usable answer from the resident (missing / bad
    endpoint, connection, auth or transport problems) -- the offline path.
    A server-side rejection (``ok: false``) re-raises as :class:`CliError`
    so the humanized ``rpc_rejected`` copy reaches stderr with exit 1.
    """
    try:
        return True, _client(args).call(method, params)
    except CliError as exc:
        text = str(exc)
        if text.startswith(_ROUTINE_RPC_REJECTED_PREFIX):
            raise
        return False, text


def _unknown_routine_error(exc: CliError, routine_id: str) -> CliError:
    """Swap the raw server ``KeyError: unknown routine`` for human copy.

    The daemon answers ``ok: false`` with ``KeyError: unknown routine:
    <id>`` (see ``RoutineManager.snapshot`` / ``_require``); this turns it
    into "not found + where to look". Any other error is returned
    unchanged.
    """
    if "unknown routine" in str(exc):
        return CliError(
            f"找不到例行任务 '{routine_id}'。"
            "用 'zn routine list' 看看现有的例行任务。"
        )
    return exc


def _routine_offline(
    args: argparse.Namespace,
    error: str,
    *,
    unavailable: str,
    json_payload: dict[str, Any],
) -> int:
    """T2-6-style offline rendering for routine commands: exit 0.

    *unavailable* names what could not be done ("看不到例行任务列表",
    "没有暂停任何例行任务", ...). Never claims a mutation happened.
    """
    if args.json:
        print(
            json.dumps(
                {
                    "daemon_reachable": False,
                    "daemon_error": _one_line(error, limit=200),
                    **json_payload,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 0
    print(f"常驻服务未运行（unreachable）：{unavailable}")
    print("下一步：检查 ZN_HOME 是否正确，或启动常驻服务（zn-resident）")
    return 0


def _format_routine_line(item: dict[str, Any]) -> str:
    """One-line list row: id + status word (+ TTY glyph) + schedule + title."""
    routine_id = _one_line(item.get("routine_id"), limit=24) or "?"
    status = item.get("status") or "?"
    mark = status_symbol(status)
    head = f"{mark + ' ' if mark else ''}{routine_id}  [{status_word(status)}]"
    schedule = _one_line(item.get("schedule_description"), limit=60)
    title = _one_line(item.get("title"), limit=60)
    line = f"{head}  {schedule}  {title}" if schedule else f"{head}  {title}"
    if status == "paused":
        reason = _one_line(item.get("paused_reason"), limit=60)
        if reason:
            line += f"  （暂停原因：{reason}）"
    return line


def _format_routine_run_line(run: dict[str, Any]) -> str:
    """One-line run-history row for ``zn routine runs`` / ``routine get``."""
    run_id = _one_line(run.get("run_id"), limit=20) or "?"
    status = run.get("status") or "?"
    mark = status_symbol(status)
    trigger = _one_line(run.get("trigger_kind"), limit=16) or "?"
    started = _one_line(run.get("started_at"), limit=30) or "-"
    finished = _one_line(run.get("finished_at"), limit=30)
    span = f"{started} → {finished}" if finished else f"{started} → 进行中"
    note = _one_line(run.get("failure_reason") or run.get("summary"), limit=80)
    line = (
        f"{mark + ' ' if mark else ''}{run_id}  [{status_word(status)}]  "
        f"{trigger}  {span}"
    )
    if note:
        line += f"  {note}"
    return line


def _format_routine_detail(item: dict[str, Any]) -> str:
    """Full detail view of one routine (``zn routine get``).

    Two-segment style like the approval detail card: headline row, then
    indented label rows for every non-empty field the ``routine_get`` RPC
    already returns, then the recent runs.
    """
    routine_id = str(item.get("routine_id") or "?")
    status = item.get("status") or "?"
    mark = status_symbol(status)
    schedule = _one_line(item.get("schedule_description"), limit=80)
    head = f"{mark + ' ' if mark else ''}例行任务 {routine_id}  [{status_word(status)}]"
    if schedule:
        head += f"  {schedule}"
    lines = [head]
    rows: list[tuple[str, str]] = []
    for label, key, limit in (
        ("任务", "task", 200),
        ("负责人", "owner", 40),
        ("计划", "schedule_spec", 120),
        ("时区", "timezone", 40),
        ("输入来源", "input_source", 120),
        ("期望结果", "expected_result", 200),
        ("审批边界", "approval_boundary", 120),
        ("缺失数据策略", "missing_data_policy", 120),
        ("上次运行", "last_run_at", 40),
        ("创建时间", "created_at", 40),
    ):
        value = _one_line(item.get(key), limit=limit)
        if value:
            rows.append((label, value))
    if status == "paused":
        reason = _one_line(item.get("paused_reason"), limit=120)
        if reason:
            rows.append(("暂停原因", reason))
    for label, value in rows:
        lines.append(f"  {label}：{value}")
    runs = item.get("recent_runs")
    if isinstance(runs, list) and runs:
        lines.append(f"  最近运行（{len(runs)}）：")
        for run in runs:
            if isinstance(run, dict):
                lines.append(f"    {_format_routine_run_line(run)}")
    return "\n".join(lines)


def _cmd_routine_list(args: argparse.Namespace) -> int:
    ok, payload = _routine_rpc(args, "routine_list", {"limit": args.limit})
    if not ok:
        return _routine_offline(
            args,
            payload,
            unavailable="看不到例行任务列表",
            json_payload={"routines": []},
        )
    routines = payload
    if not isinstance(routines, list):
        raise _unexpected_result("routine_list", routines)
    if args.json:
        print(json.dumps(routines, ensure_ascii=False, indent=2, default=str))
        return 0
    if not routines:
        print("no routines")
        _print_empty_hint("routine_list")
        return 0
    print(section("routines", len(routines)))
    for item in routines:
        if isinstance(item, dict):
            print(_format_routine_line(item))
    return 0


def _cmd_routine_get(args: argparse.Namespace) -> int:
    try:
        ok, payload = _routine_rpc(
            args, "routine_get", {"routine_id": args.routine_id}
        )
    except CliError as exc:
        raise _unknown_routine_error(exc, args.routine_id) from None
    if not ok:
        return _routine_offline(
            args,
            payload,
            unavailable="看不到例行任务详情",
            json_payload={"routine": None},
        )
    result = payload
    if not isinstance(result, dict) or not result:
        raise _unexpected_result("routine_get", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    print(_format_routine_detail(result))
    return 0


def _cmd_routine_runs(args: argparse.Namespace) -> int:
    try:
        ok, payload = _routine_rpc(
            args,
            "routine_runs",
            {"routine_id": args.routine_id, "limit": args.limit},
        )
    except CliError as exc:
        raise _unknown_routine_error(exc, args.routine_id) from None
    if not ok:
        return _routine_offline(
            args,
            payload,
            unavailable="看不到运行历史",
            json_payload={"routine_id": args.routine_id, "runs": []},
        )
    runs = payload
    if not isinstance(runs, list):
        raise _unexpected_result("routine_runs", runs)
    if args.json:
        print(json.dumps(runs, ensure_ascii=False, indent=2, default=str))
        return 0
    print(section("routine runs", len(runs)))
    if not runs:
        print("(none)")
        return 0
    for run in runs:
        if isinstance(run, dict):
            print(_format_routine_run_line(run))
    return 0


def _cmd_routine_pause(args: argparse.Namespace) -> int:
    params: dict[str, Any] = {"routine_id": args.routine_id}
    if args.reason:
        params["reason"] = args.reason
    try:
        ok, payload = _routine_rpc(args, "routine_pause", params)
    except CliError as exc:
        raise _unknown_routine_error(exc, args.routine_id) from None
    if not ok:
        return _routine_offline(
            args,
            payload,
            unavailable="没有暂停任何例行任务",
            json_payload={"changed": False, "routine": None},
        )
    result = payload
    if not isinstance(result, dict) or not result:
        raise _unexpected_result("routine_pause", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    status = result.get("status") or "paused"
    mark = status_symbol(status)
    print(
        f"{mark + ' ' if mark else ''}例行任务 {args.routine_id} "
        f"已暂停 [{status_word(status)}]"
    )
    reason = _one_line(result.get("paused_reason"), limit=200)
    if reason:
        print(f"  原因：{reason}")
    return 0


def _cmd_routine_resume(args: argparse.Namespace) -> int:
    try:
        ok, payload = _routine_rpc(
            args, "routine_resume", {"routine_id": args.routine_id}
        )
    except CliError as exc:
        raise _unknown_routine_error(exc, args.routine_id) from None
    if not ok:
        return _routine_offline(
            args,
            payload,
            unavailable="没有恢复任何例行任务",
            json_payload={"changed": False, "routine": None},
        )
    result = payload
    if not isinstance(result, dict) or not result:
        raise _unexpected_result("routine_resume", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    status = result.get("status") or "active"
    mark = status_symbol(status)
    print(
        f"{mark + ' ' if mark else ''}例行任务 {args.routine_id} "
        f"已恢复 [{status_word(status)}]"
    )
    return 0


# --- T10: `zn diary ...` ---------------------------------------------------
# Terminal face for the daemon's diary_* read-only RPCs (already dispatched
# in daemon.py: ``diary_list`` -- inventory newest first, ``diary_get`` --
# one entry by date, null result when the date has no entry). No new daemon
# RPC, no daemon.py changes.
#
# Offline contract (T2-6 style, same as the T9 read-only commands): both
# commands exit 0 when the resident is unreachable and print an honest note
# naming what is unavailable + the start hint. A missing entry (the daemon
# answers null, not a rejection) is NOT an offline case: it surfaces as a
# humanized "not found" error on stderr, exit 1. diary_write stays on the
# chat path and is deliberately NOT exposed here.

_DIARY_RPC_REJECTED_PREFIX = _ERROR_COPY["rpc_rejected"][0].split("{method}")[0]


def _diary_rpc(
    args: argparse.Namespace, method: str, params: dict[str, Any]
) -> tuple[bool, Any]:
    """Call one ``diary_*`` RPC, classifying failures.

    Returns ``(True, result)`` on success, or ``(False, error_text)`` when
    the call never got a usable answer from the resident (missing / bad
    endpoint, connection, auth or transport problems) -- the offline path.
    A server-side rejection (``ok: false``) re-raises as :class:`CliError`
    so the humanized ``rpc_rejected`` copy reaches stderr with exit 1.
    """
    try:
        return True, _client(args).call(method, params)
    except CliError as exc:
        text = str(exc)
        if text.startswith(_DIARY_RPC_REJECTED_PREFIX):
            raise
        return False, text


def _diary_offline(
    args: argparse.Namespace,
    error: str,
    *,
    unavailable: str,
    json_payload: dict[str, Any],
) -> int:
    """T2-6-style offline rendering for diary commands: exit 0.

    *unavailable* names what could not be done ("看不到日记列表",
    "看不到某天的日记", ...). Nothing is claimed to have happened.
    """
    if args.json:
        print(
            json.dumps(
                {
                    "daemon_reachable": False,
                    "daemon_error": _one_line(error, limit=200),
                    **json_payload,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 0
    print(f"常驻服务未运行（unreachable）：{unavailable}")
    print("下一步：检查 ZN_HOME 是否正确，或启动常驻服务（zn-resident）")
    return 0


def _format_diary_line(item: dict[str, Any]) -> str:
    """One-line list row: date + item count + one-line text excerpt."""
    entry_date = _one_line(item.get("date"), limit=12) or "?"
    line = entry_date
    count = item.get("item_count")
    if isinstance(count, int):
        line += f"  （{count} 条素材）"
    text = _one_line(item.get("text"), limit=72)
    if text:
        line += f"  {text}"
    return line


def _format_diary_detail(item: dict[str, Any]) -> str:
    """Full detail view of one diary entry (``zn diary get``).

    Headline row (date), then indented label rows for the fields the
    ``diary_get`` RPC already returns, then the body rendered with
    :func:`_long_text` so line structure survives (T2-4 rule).
    """
    entry_date = _one_line(item.get("date"), limit=12) or "?"
    lines = [f"日记 {entry_date}"]
    count = item.get("item_count")
    if isinstance(count, int):
        lines.append(f"  素材数：{count}")
    created = _one_line(item.get("created_at"), limit=40)
    if created:
        lines.append(f"  写于：{created}")
    text = str(item.get("text") or "")
    if text.strip():
        lines.append("  正文：")
        body = _long_text(
            text,
            overflow_suffix=f"，运行 `zn diary get --date {entry_date} --json` 看全文",
        )
        for body_line in body.split("\n"):
            lines.append(f"  {body_line}")
    return "\n".join(lines)


def _cmd_diary_list(args: argparse.Namespace) -> int:
    ok, payload = _diary_rpc(args, "diary_list", {"limit": args.limit})
    if not ok:
        return _diary_offline(
            args,
            payload,
            unavailable="看不到日记列表",
            json_payload={"entries": []},
        )
    entries = payload
    if not isinstance(entries, list):
        raise _unexpected_result("diary_list", entries)
    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2, default=str))
        return 0
    if not entries:
        print("no diary entries")
        _print_empty_hint("diary_list")
        return 0
    print(section("diary entries", len(entries)))
    for item in entries:
        if isinstance(item, dict):
            print(_format_diary_line(item))
    return 0


def _cmd_diary_get(args: argparse.Namespace) -> int:
    ok, payload = _diary_rpc(args, "diary_get", {"date": args.date})
    if not ok:
        return _diary_offline(
            args,
            payload,
            unavailable=f"看不到 {args.date} 的日记",
            json_payload={"date": args.date, "entry": None},
        )
    if payload is None:
        # The daemon answers null (not a rejection) when the date has no
        # entry: humanized "not found", exit 1. The English fragment keeps
        # the server contract greppable; the next line points at the list.
        raise CliError(
            f"找不到 {args.date} 的日记（no diary entry for that date）。"
            "用 'zn diary list' 看看 ZN 写过哪些日记。"
        )
    result = payload
    if not isinstance(result, dict) or not result:
        raise _unexpected_result("diary_get", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    print(_format_diary_detail(result))
    return 0


# --- T2-6: `zn status` aggregate -----------------------------------------
# One-screen ZN health: resident liveness, status summary, model channel,
# connector mounts, pending approvals, autonomy envelope. Read-only: only
# the existing daemon RPCs (ping / status / connector_status /
# approval_list / autonomy_list) plus the local model-route probe
# (model_check.py) are used; no new daemon RPC. When the resident is not
# running, the daemon rows are marked unreachable while the local rows
# (model probe, connector config evaluation) still report. Always exit 0:
# this is a dashboard, not a health gate.

_STATUS_DEFAULT_PROBE_TIMEOUT_SECONDS = 5.0


def _cmd_status(args: argparse.Namespace) -> int:
    """Show the six-row ZN status aggregate (plus ``--json``)."""

    data: dict[str, Any] = {}
    daemon_error = ""

    def _rpc(method: str, params: dict[str, Any] | None = None) -> Any:
        nonlocal daemon_error
        try:
            return _client(args).call(method, params)
        except CliError as exc:
            daemon_error = str(exc)
            return None

    ping_result = _rpc("ping", {})
    summary_result = _rpc("status", {})
    connector_result = _rpc("connector_status", {})
    approval_result = _rpc("approval_list", {})
    autonomy_result = _rpc("autonomy_list")
    daemon_reachable = not daemon_error
    data["daemon_reachable"] = daemon_reachable
    if daemon_error:
        data["daemon_error"] = daemon_error

    # --- resident liveness (ping, daemon.py) -----------------------------
    if isinstance(ping_result, dict):
        pulse = ping_result.get("pulse_count")
        data["resident"] = {
            "alive": bool(ping_result.get("alive")),
            "pulse_count": pulse,
        }
    else:
        data["resident"] = None

    # --- status summary (status RPC) --------------------------------------
    if isinstance(summary_result, dict):
        identity = summary_result.get("identity") or {}
        if not isinstance(identity, dict):
            identity = {}
        dependency = summary_result.get("model_dependency") or {}
        if not isinstance(dependency, dict):
            dependency = {}
        data["summary"] = {
            "identity": {
                "name": identity.get("name"),
                "version": identity.get("version"),
            },
            "model_invocations": dependency.get("model_invocations"),
        }
    else:
        data["summary"] = None

    # --- model channel (local probe, model_check.py) ----------------------
    report = check_model_routes(probe_timeout_seconds=args.probe_timeout)
    data["model"] = report.to_dict()

    # --- connectors (daemon report, else local config evaluation) ---------
    connector_local = False
    connector_counts: dict[str, Any] = {
        "mounted": None,
        "approved": None,
        "failed": None,
    }
    if isinstance(connector_result, dict) and isinstance(
        connector_result.get("connectors"), list
    ):
        connectors = [c for c in connector_result["connectors"] if isinstance(c, dict)]
        connector_counts["mounted"] = sum(1 for c in connectors if c.get("mounted"))
        connector_counts["approved"] = sum(1 for c in connectors if c.get("approved"))
        connector_counts["failed"] = sum(
            1 for c in connectors if c.get("approved") and not c.get("mounted")
        )
        data["connectors"] = {**connector_counts, "local_evaluation": False}
    else:
        connector_local = True
        try:
            from .connector_autoattach import evaluate_connector_status

            items = evaluate_connector_status()
        except Exception as exc:
            connector_counts["config_error"] = _one_line(str(exc), limit=200)
            items = []
        approved_items = [i for i in items if isinstance(i, dict) and i.get("approved")]
        connector_counts["mounted"] = sum(
            1
            for i in approved_items
            if isinstance(i.get("last_mount"), dict)
            and i["last_mount"].get("mounted") is True
        )
        connector_counts["approved"] = len(approved_items)
        connector_counts["failed"] = sum(
            1
            for i in approved_items
            if isinstance(i.get("last_mount"), dict)
            and i["last_mount"].get("mounted") is False
        )
        data["connectors"] = {**connector_counts, "local_evaluation": True}

    # --- pending approvals (approval_list) --------------------------------
    if isinstance(approval_result, dict) and isinstance(
        approval_result.get("pending"), list
    ):
        data["approvals"] = {"pending": len(approval_result["pending"])}
    else:
        data["approvals"] = {"pending": None}

    # --- non-default autonomy domains (autonomy_list) ----------------------
    if isinstance(autonomy_result, list):
        data["autonomy"] = {
            "explicit_domains": sum(1 for item in autonomy_result if isinstance(item, dict))
        }
    else:
        data["autonomy"] = {"explicit_domains": None}

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return 0

    print(section("ZN status"))

    def _row(
        label: str, text: str, *, kind: str | None = None, hint: str | None = None,
        sym: str | None = None,
    ) -> None:
        # T2-7: unified status glyph, TTY-only via symbol() ("" off-TTY, so
        # piped output keeps its historic bytes).
        mark = symbol(sym) if sym else ""
        cell = f"{label:<10} {mark + ' ' if mark else ''}{text}"
        if kind:
            cell = colorize(cell, kind)
        if hint:
            cell += colorize(f"  → {hint}", "dim")
        print(cell)

    # resident row
    if data["resident"] is not None:
        alive = data["resident"]["alive"]
        pulse = _one_line(data["resident"]["pulse_count"], limit=12)
        if alive:
            _row("resident", f"{status_word(True)} (pulse_count={pulse})", sym="ok")
        else:
            _row("resident", status_word("unknown"), kind="err", hint="zn-resident", sym="fail")
    else:
        _row(
            "resident",
            f"{status_word('unreachable')} ({_one_line(daemon_error, limit=90)})",
            kind="err",
            hint="check ZN_HOME, or start the resident service (zn-resident)",
            sym="fail",
        )

    # summary row
    if data["summary"] is not None:
        identity = data["summary"]["identity"]
        name = _one_line(identity.get("name"), limit=32)
        version = _one_line(identity.get("version"), limit=16)
        invocations = _one_line(data["summary"]["model_invocations"], limit=12)
        _row(
            "summary",
            f"{name} v{version} · model_invocations={invocations}",
        )
    else:
        _row("summary", status_word("unreachable"), kind="err")

    # model row (local probe, works without a running resident)
    if not report.configured:
        _row("model", "no model routes configured", kind="err", hint="zn model check", sym="fail")
    else:
        reached = report.reachable_count
        total = len(report.results)
        if reached:
            _row("model", f"{reached} of {total} route(s) reachable", sym="ok")
        else:
            _row(
                "model",
                f"{reached} of {total} route(s) reachable",
                kind="err",
                hint="zn model check",
                sym="fail",
            )

    # connector row
    counts = data["connectors"]
    if counts.get("config_error"):
        _row(
            "connectors",
            f"config error: {counts['config_error']}",
            kind="err",
            hint="check connectors.yaml",
            sym="fail",
        )
    elif connector_local:
        approved, failed = counts["approved"], counts["failed"]
        if failed:
            _row(
                "connectors",
                f"{approved} approved, {failed} failed (local config evaluation)",
                kind="err",
                hint="zn connector status",
                sym="fail",
            )
        else:
            _row(
                "connectors",
                f"{approved} approved (local config evaluation)",
                hint="zn connector status",
                sym="ok",
            )
    else:
        mounted, approved, failed = (
            counts["mounted"],
            counts["approved"],
            counts["failed"],
        )
        if failed:
            _row(
                "connectors",
                f"{mounted} of {approved} mounted, {failed} failed",
                kind="err",
                hint="zn connector status",
                sym="fail",
            )
        else:
            _row("connectors", f"{mounted} of {approved} mounted", sym="ok")

    # approvals row
    pending = data["approvals"]["pending"]
    if pending is None:
        _row("approvals", status_word("unreachable"), kind="err", sym="fail")
    elif pending:
        _row(
            "approvals",
            f"{pending} pending",
            kind="warn",
            hint="zn approval list",
            sym="warn",
        )
    else:
        _row("approvals", "none pending")

    # autonomy row
    domains = data["autonomy"]["explicit_domains"]
    if domains is None:
        _row("autonomy", status_word("unreachable"), kind="err")
    else:
        _row("autonomy", f"{domains} explicit domain(s)", hint="zn autonomy list")

    return 0


def _cmd_connector_status_offline(args: argparse.Namespace, error: str) -> int:
    """Local config evaluation when the daemon is unreachable."""

    from .connector_autoattach import evaluate_connector_status

    try:
        status = evaluate_connector_status()
    except ValueError as exc:
        print(f"connector config error: {_one_line(str(exc), limit=200)}")
        return 3
    if args.json:
        print(
            json.dumps(
                {"daemon_reachable": False, "daemon_error": error, "connectors": status},
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 0
    print(f"daemon unreachable ({_one_line(error, limit=90)}); showing local config evaluation")
    for item in status:
        mount = item.get("last_mount") or {}
        # T2-7: unified state glyph on TTY; state words stay untouched so
        # off-TTY output keeps its historic bytes.
        if not item.get("approved"):
            state, mark = "off    ", ""
            reason = "not approved in connectors.yaml (default off)"
        elif mount.get("mounted") is True:
            state, mark = "mounted", symbol("ok")
            reason = str(mount.get("reason") or "")
        elif mount.get("mounted") is False:
            state, mark = "FAILED ", symbol("fail")
            reason = str(mount.get("reason") or "")
        else:
            state, mark = "pending", symbol("warn")
            reason = str(item.get("readiness") or "will mount on next daemon start")
        print(
            f"{mark + ' ' if mark else ''}"
            f"{_one_line(item.get('r_series'), limit=4):4} "
            f"{_one_line(item.get('name'), limit=16):16} "
            f"{state}  {_one_line(reason, limit=100)}"
        )
    return 0


def _skill_store():
    """Local skill store for the read-only ``skill`` commands (no RPC)."""

    from .skills import SkillStore

    return SkillStore()


def _cmd_skill_usage(args: argparse.Namespace) -> int:
    """Show per-skill body-load usage stats. Local only, no resident RPC.

    Reuses the T2 read-only query surface (:meth:`SkillStore.list_skill_usage`
    and :meth:`SkillStore.dormant_skills`): usage_count / last_used, the
    zero-hit (never loaded) case, and the long-dormant list. Never records,
    never writes, never deletes.
    """

    store = _skill_store()
    dormant_days = args.dormant_days
    dormant_names = {
        item.name for item in store.dormant_skills(dormant_days=dormant_days)
    }
    rows = [
        {
            "name": item.name,
            "usage_count": item.usage_count,
            "last_used": item.last_used or None,
            "never_used": item.never_used,
            "dormant": item.name in dormant_names,
        }
        for item in store.list_skill_usage()
    ]
    if args.json:
        print(
            json.dumps(
                {"dormant_days": dormant_days, "skills": rows},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if not rows:
        print("no skills discovered")
        return 0
    print(f"skill usage (dormant = body unused for > {dormant_days} days):")
    for row in rows:
        last = row["last_used"] or "never"
        flags = "dormant" if row["dormant"] else ""
        print(
            f"{_one_line(row['name'], limit=32):32} "
            f"uses={row['usage_count']:<6} "
            f"last_used={_one_line(last, limit=32):32} "
            f"{flags}"
        )
    return 0


def _cmd_skill_prune(args: argparse.Namespace) -> int:
    """List dormant skill candidates. Always dry-run: never deletes anything.

    Deletion still needs human confirmation and is deliberately not wired
    into this command; passing ``--no-dry-run`` is refused outright.
    """

    if not args.dry_run:
        raise CliError(
            "refusing to prune skills: deleting a dormant skill needs human "
            "confirmation; rerun without --no-dry-run to list the candidates"
        )
    store = _skill_store()
    dormant_days = args.dormant_days
    dormant = store.dormant_skills(dormant_days=dormant_days)
    rows = [
        {
            "name": item.name,
            "usage_count": item.usage_count,
            "last_used": item.last_used or None,
        }
        for item in dormant
    ]
    if args.json:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "deleted": [],
                    "dormant_days": dormant_days,
                    "dormant": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if not rows:
        print(
            f"no dormant skills (all bodies used within the last "
            f"{dormant_days} days); nothing to prune"
        )
        return 0
    print(
        f"dry-run: nothing deleted; {len(rows)} dormant skill(s) "
        f"(body unused for > {dormant_days} days):"
    )
    for row in rows:
        print(
            f"{_one_line(row['name'], limit=32):32} "
            f"uses={row['usage_count']:<6} "
            f"last_used={_one_line(row['last_used'] or 'never', limit=32):32}"
        )
    print(
        "deleting a dormant skill needs human confirmation; "
        "this command only lists candidates"
    )
    return 0


def _cmd_chat(args: argparse.Namespace) -> int:
    """Open the interactive chat REPL (TERM-1) on the resident endpoint."""

    from .cli_repl import ChatSession

    return ChatSession(_client(args)).run()


def _cmd_model_check(args: argparse.Namespace) -> int:
    """Probe the locally configured model routes. Local only, no resident RPC."""

    report = check_model_routes(probe_timeout_seconds=args.probe_timeout)
    if not report.configured:
        print(format_no_config_hint())
        if report.config_error:
            print(f"configuration error: {_one_line(report.config_error)}")
        return 3
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, default=str))
        return 0 if report.any_reachable else 1
    for result in report.results:
        identity = (
            f"{_one_line(result.route_id, limit=40)} "
            f"({_one_line(result.provider, limit=24)}/"
            f"{_one_line(result.model, limit=60)})"
        )
        if result.reachable:
            latency = (
                f"{result.latency_seconds:.2f}s"
                if result.latency_seconds is not None
                else "?"
            )
            # T2-7: unified ok/fail glyph on TTY; the words stay so scripts
            # grepping "reachable"/"unreachable" keep working off-TTY.
            mark = symbol("ok")
            print(f"{mark + ' ' if mark else ''}reachable   {identity}  {latency}")
        else:
            mark = symbol("fail")
            print(f"{mark + ' ' if mark else ''}unreachable {identity}  {_one_line(result.detail, limit=160)}")
    print(f"{report.reachable_count} of {len(report.results)} route(s) reachable")
    return 0 if report.any_reachable else 1


def _cmd_help(args: argparse.Namespace) -> int:
    """Print the scenario-organized help overview. Pure local, works offline."""
    print(render_help_text())
    return 0


# T3-1: scenario-organized `zn help`. Static copy only; never touches the
# resident. Each row is (command path, one-line human blurb, copy-pasteable
# example). Every command path is validated against build_parser() by
# tests/zn_agent/core/test_zn_help.py so copy drift fails loudly instead of
# going stale.
_HELP_SECTIONS: tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...] = (
    (
        "交办",
        (
            (
                "work submit",
                "交办一件事给 ZN，常驻服务去执行",
                'zn work submit --task "把 downloads 里昨天的发票整理成一张表"',
            ),
            (
                "work list",
                "看看 ZN 手上正在干的活",
                "zn work list",
            ),
            (
                "work get",
                "看某件事的进展和结果",
                "zn work get --thread-id <id>",
            ),
            (
                "work cancel",
                "停掉一件正在干的活",
                "zn work cancel --thread-id <id> --event-id <id>",
            ),
            (
                "chat",
                "直接跟 ZN 对话交办（交互模式）",
                "zn chat",
            ),
        ),
    ),
    (
        "审批",
        (
            (
                "approval list",
                "看等你拍板的申请卡",
                "zn approval list",
            ),
            (
                "approval show",
                "先看清一张卡的内容再拍板",
                "zn approval show <id>",
            ),
            (
                "approval decide",
                "批准或拒绝一张卡",
                "zn approval decide --request-id <id> --allow",
            ),
        ),
    ),
    (
        "审批规则与撤销",
        (
            (
                "approval rules list",
                "看有哪些自动放行规则",
                "zn approval rules list",
            ),
            (
                "approval rules delete",
                "收回一条自动放行规则",
                "zn approval rules delete <rule-id>",
            ),
            (
                "approval undo",
                "撤销一次已执行的批准变更（文件回滚）",
                "zn approval undo <request-id>",
            ),
        ),
    ),
    (
        "记忆",
        (
            (
                "memory list",
                "看看 ZN 都记着哪些事",
                "zn memory list",
            ),
            (
                "memory remember",
                "让 ZN 记住一件事",
                'zn memory remember --key "公司 wifi 密码" --value "xxxx"',
            ),
            (
                "memory forget",
                "让 ZN 忘掉一件事（默认要手动确认）",
                'zn memory forget --key "公司 wifi 密码" --yes',
            ),
            (
                "memory export",
                "把记忆备份成文件",
                "zn memory export --out ~/memory-backup.json",
            ),
            (
                "memory import",
                "从备份文件恢复记忆",
                "zn memory import --in ~/memory-backup.json",
            ),
        ),
    ),
    (
        "团队与自驱",
        (
            (
                "team list",
                "看有哪些项目团队在干活",
                "zn team list",
            ),
            (
                "team timeline",
                "看某件事的团队进展时间线",
                "zn team timeline --thread-id <id>",
            ),
            (
                "goal list",
                "看 ZN 的自驱目标清单",
                "zn goal list",
            ),
            (
                "goal status",
                "看 ZN 自驱的当前状态",
                "zn goal status",
            ),
        ),
    ),
    (
        "例行任务",
        (
            (
                "routine list",
                "看有哪些例行任务在跑",
                "zn routine list",
            ),
            (
                "routine get",
                "看某条例行任务的详情",
                "zn routine get <id>",
            ),
            (
                "routine runs",
                "看某条例行任务的运行历史",
                "zn routine runs <id>",
            ),
            (
                "routine pause",
                "暂停一条例行任务",
                "zn routine pause <id>",
            ),
            (
                "routine resume",
                "恢复一条被暂停的例行任务",
                "zn routine resume <id>",
            ),
        ),
    ),
    (
        "日记",
        (
            (
                "diary list",
                "看 ZN 写过哪些日记（最新在前）",
                "zn diary list",
            ),
            (
                "diary get",
                "看某天的日记正文",
                "zn diary get --date 2026-10-22",
            ),
            (
                "diary get",
                "看某天日记的原始内容（脚本用）",
                "zn diary get --date 2026-10-22 --json",
            ),
        ),
    ),
    (
        "日常",
        (
            (
                "suggestions list",
                "看 ZN 给你的建议",
                "zn suggestions list",
            ),
            (
                "autonomy list",
                "看 ZN 在各领域的自主权设置",
                "zn autonomy list",
            ),
            (
                "connector status",
                "看连接器挂载得正不正常",
                "zn connector status",
            ),
            (
                "model check",
                "检查模型通道通不通",
                "zn model check",
            ),
            (
                "status",
                "一屏看 ZN 的整体状态（服务/模型/审批/连接器）",
                "zn status",
            ),
        ),
    ),
)


def render_help_text(*, stream=None, environ=None) -> str:
    """Render the scenario help overview as plain text.

    Local only: no daemon connection. Section headers reuse the
    ``cli_format.section`` style (``--- title (n) ---``), so TTY coloring
    follows the same NO_COLOR / non-TTY rules as the rest of the CLI.
    """
    lines: list[str] = ["ZN 能帮你干的事（按场景）", ""]
    for title, rows in _HELP_SECTIONS:
        lines.append(section(title, len(rows), stream=stream, environ=environ))
        for command, blurb, example in rows:
            lines.append(f"  {command}")
            lines.append(f"    {blurb}")
            lines.append(f"    例：{example}")
        lines.append("")
    lines.append("细看某条命令：zn <命令> --help，例如 zn work submit --help")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zn",
        description="ZN terminal client: talk to ZN through the running "
        "resident. The resident owns all execution. Run with no command "
        "(or `zn chat`) to open the interactive conversation.",
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        help="resident endpoint file (default: $ZN_RESIDENT_ENDPOINT or "
        "<ZN home>/kernel/resident-endpoint.json)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"seconds to wait for the resident per RPC (default {DEFAULT_TIMEOUT_SECONDS:g})",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="show raw server details in error output (same as ZN_DEBUG=1)",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    # T3-1: scenario-organized help overview; pure local, no daemon.
    # T3-2: every leaf subcommand carries runnable examples in epilog.
    help_cmd = sub.add_parser(
        "help",
        help="按场景看 ZN 能帮你干的事（离线可用）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn help",
    )
    help_cmd.set_defaults(func=_cmd_help)

    chat = sub.add_parser(
        "chat",
        help="talk to ZN interactively (same as running zn with no command)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn chat",
    )
    chat.set_defaults(func=_cmd_chat)

    work = sub.add_parser("work", help="list, inspect, or submit resident work")
    work_sub = work.add_subparsers(dest="work_command", metavar="subcommand", required=True)

    work_list = work_sub.add_parser(
        "list",
        help="list work threads",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn work list\n"
        "  zn work list --limit 5",
    )
    work_list.add_argument(
        "--limit", type=lambda v: _require_positive_int(v, name="--limit", maximum=100),
        default=24,
    )
    work_list.add_argument("--json", action="store_true", help="print raw JSON")
    work_list.set_defaults(func=_cmd_work_list)

    work_get = work_sub.add_parser(
        "get",
        help="show one work thread",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn work get --thread-id <thread-id>\n"
        "  zn work get --thread-id <thread-id> --message-limit 20",
    )
    work_get.add_argument("--thread-id", type=lambda v: _require_non_empty(v, name="--thread-id"), required=True)
    work_get.add_argument(
        "--message-limit",
        type=lambda v: _require_positive_int(v, name="--message-limit", maximum=500),
        default=120,
    )
    work_get.add_argument("--json", action="store_true", help="print raw JSON")
    work_get.set_defaults(func=_cmd_work_get)

    work_submit = work_sub.add_parser(
        "submit",
        help="submit a task to a work thread",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn work submit --task \"把 downloads 里昨天的发票整理成一张表\"\n"
        "  zn work submit --thread-id <thread-id> --task \"继续，把明细也加上\"",
    )
    work_submit.add_argument("--thread-id", default=None,
                             help="existing thread id; omitted = create a new thread")
    work_submit.add_argument("--title", default=None,
                             help="title for a newly created thread")
    work_submit.add_argument("--task", type=lambda v: _require_non_empty(v, name="--task"), required=True)
    work_submit.add_argument("--json", action="store_true", help="print raw JSON")
    work_submit.set_defaults(func=_cmd_work_submit)

    work_cancel = work_sub.add_parser(
        "cancel",
        help="cancel an active work event",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn work cancel --thread-id <thread-id> --event-id <event-id>",
    )
    work_cancel.add_argument("--thread-id", type=lambda v: _require_non_empty(v, name="--thread-id"), required=True)
    work_cancel.add_argument("--event-id", type=lambda v: _require_non_empty(v, name="--event-id"), required=True)
    work_cancel.add_argument("--json", action="store_true", help="print raw JSON")
    work_cancel.set_defaults(func=_cmd_work_cancel)

    approval = sub.add_parser(
        "approval",
        help="list, show, decide or undo approval cards; manage auto-allow rules",
    )
    approval_sub = approval.add_subparsers(
        dest="approval_command", metavar="subcommand", required=True
    )

    approval_list = approval_sub.add_parser(
        "list",
        help="list approval cards",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn approval list\n"
        "  zn approval list --status all",
    )
    approval_list.add_argument(
        "--status",
        choices=["pending", "denied", "expired", "applied", "all"],
        default="pending",
        help="which cards to show (default: pending)",
    )
    approval_list.add_argument("--json", action="store_true", help="print raw JSON")
    approval_list.set_defaults(func=_cmd_approval_list)

    approval_decide = approval_sub.add_parser(
        "decide",
        help="decide one pending approval card",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn approval decide --request-id <request-id> --allow\n"
        "  zn approval decide --request-id <request-id> --deny",
    )
    approval_decide.add_argument(
        "--request-id",
        type=lambda v: _require_non_empty(v, name="--request-id"),
        required=True,
    )
    decision = approval_decide.add_mutually_exclusive_group(required=True)
    decision.add_argument("--allow", action="store_true", help="approve this request once")
    decision.add_argument("--deny", action="store_true", help="deny this request")
    decision.add_argument(
        "--always-allow",
        action="store_true",
        help="approve and remember an auto-allow rule for future requests",
    )
    approval_decide.add_argument("--json", action="store_true", help="print raw JSON")
    approval_decide.set_defaults(func=_cmd_approval_decide)

    approval_show = approval_sub.add_parser(
        "show",
        help="show one approval card with full detail",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn approval show <request-id>",
    )
    approval_show.add_argument(
        "request_id",
        type=lambda v: _require_non_empty(v, name="request_id"),
        help="the approval card id, as printed by 'zn approval list'",
    )
    approval_show.add_argument("--json", action="store_true", help="print raw JSON")
    approval_show.set_defaults(func=_cmd_approval_show)

    # T11: approval rules + undo. Rule creation is not exposed here: it rides
    # the existing `zn approval decide --always-allow` path.
    approval_rules = approval_sub.add_parser(
        "rules",
        help="manage auto-allow approval rules",
    )
    approval_rules_sub = approval_rules.add_subparsers(
        dest="approval_rules_command", metavar="subcommand", required=True
    )

    approval_rules_list = approval_rules_sub.add_parser(
        "list",
        help="list approval rules",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn approval rules list\n"
        "  zn approval rules list --json",
    )
    approval_rules_list.add_argument("--json", action="store_true", help="print raw JSON")
    approval_rules_list.set_defaults(func=_cmd_approval_rules_list)

    approval_rules_delete = approval_rules_sub.add_parser(
        "delete",
        help="delete an approval rule",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn approval rules delete <rule-id>",
    )
    approval_rules_delete.add_argument(
        "rule_id",
        type=lambda v: _require_non_empty(v, name="rule_id"),
        help="the rule id, as printed by 'zn approval rules list'",
    )
    approval_rules_delete.add_argument("--json", action="store_true", help="print raw JSON")
    approval_rules_delete.set_defaults(func=_cmd_approval_rules_delete)

    approval_undo = approval_sub.add_parser(
        "undo",
        help="undo an applied (consumed) approval",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn approval undo <request-id>",
    )
    approval_undo.add_argument(
        "request_id",
        type=lambda v: _require_non_empty(v, name="request_id"),
        help="the approval card id, as printed by 'zn approval list --status applied'",
    )
    approval_undo.add_argument("--json", action="store_true", help="print raw JSON")
    approval_undo.set_defaults(func=_cmd_approval_undo)

    memory = sub.add_parser("memory", help="inspect durable memory")
    memory_sub = memory.add_subparsers(
        dest="memory_command", metavar="subcommand", required=True
    )

    memory_list = memory_sub.add_parser(
        "list",
        help="list remembered fact keys",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn memory list\n"
        "  zn memory list --limit 50",
    )
    memory_list.add_argument(
        "--limit", type=lambda v: _require_positive_int(v, name="--limit", maximum=200),
        default=20,
    )
    memory_list.add_argument("--json", action="store_true", help="print raw JSON")
    memory_list.set_defaults(func=_cmd_memory_list)

    memory_remember = memory_sub.add_parser(
        "remember",
        help="store one durable fact",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn memory remember --key user.timezone --value \"Europe/Berlin\"\n"
        "  zn memory remember --key wifi.password --value \"...\" --sensitivity sensitive",
    )
    memory_remember.add_argument("--key", type=lambda v: _require_non_empty(v, name="--key"), required=True)
    memory_remember.add_argument("--value", type=lambda v: _require_non_empty(v, name="--value"), required=True)
    memory_remember.add_argument(
        "--sensitivity",
        choices=["normal", "sensitive", "non_retainable"],
        default=None,
        help="sensitivity tier (default: keep the existing fact's tier)",
    )
    memory_remember.add_argument("--json", action="store_true", help="print raw JSON")
    memory_remember.set_defaults(func=_cmd_memory_remember)

    memory_forget = memory_sub.add_parser(
        "forget",
        help="forget one durable fact",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn memory forget --key <key>\n"
        "  zn memory forget --key <key> --yes",
    )
    memory_forget.add_argument("--key", type=lambda v: _require_non_empty(v, name="--key"), required=True)
    memory_forget.add_argument(
        "--yes",
        action="store_true",
        help="skip the interactive confirmation (without it, forgetting requires a typed yes)",
    )
    memory_forget.add_argument("--json", action="store_true", help="print raw JSON")
    memory_forget.set_defaults(func=_cmd_memory_forget)

    memory_export = memory_sub.add_parser(
        "export",
        help="export all remembered facts to a versioned JSON file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn memory export --out ~/memory-backup.json",
    )
    memory_export.add_argument(
        "--out",
        type=lambda v: _require_non_empty(v, name="--out"),
        required=True,
        help="destination file path (resolved on the resident machine)",
    )
    memory_export.add_argument("--json", action="store_true", help="print raw JSON")
    memory_export.set_defaults(func=_cmd_memory_export)

    memory_import = memory_sub.add_parser(
        "import",
        help="restore facts from a memory export file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn memory import --in ~/memory-backup.json\n"
        "  zn memory import --in ~/memory-backup.json --overwrite",
    )
    memory_import.add_argument(
        "--in",
        dest="in_file",
        type=lambda v: _require_non_empty(v, name="--in"),
        required=True,
        help="export file path (resolved on the resident machine)",
    )
    memory_import.add_argument(
        "--overwrite",
        action="store_true",
        help="replace facts whose keys already exist (default: skip conflicts)",
    )
    memory_import.add_argument("--json", action="store_true", help="print raw JSON")
    memory_import.set_defaults(func=_cmd_memory_import)

    team = sub.add_parser("team", help="inspect project teams")
    team_sub = team.add_subparsers(
        dest="team_command", metavar="subcommand", required=True
    )

    team_list = team_sub.add_parser(
        "list",
        help="list active project teams",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn team list\n"
        "  zn team list --limit 10",
    )
    team_list.add_argument(
        "--limit", type=lambda v: _require_positive_int(v, name="--limit", maximum=200),
        default=20,
    )
    team_list.add_argument("--json", action="store_true", help="print raw JSON")
    team_list.set_defaults(func=_cmd_team_list)

    team_timeline = team_sub.add_parser(
        "timeline",
        help="show the team timeline of a work thread",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn team timeline --thread-id <thread-id>",
    )
    team_timeline.add_argument(
        "--thread-id",
        type=lambda v: _require_non_empty(v, name="--thread-id"),
        required=True,
        help="work thread the team runs in (the team_timeline RPC is thread-scoped)",
    )
    team_timeline.add_argument("--json", action="store_true", help="print raw JSON")
    team_timeline.set_defaults(func=_cmd_team_timeline)

    skill = sub.add_parser("skill", help="inspect skill usage statistics")
    skill_sub = skill.add_subparsers(
        dest="skill_command", metavar="subcommand", required=True
    )

    skill_usage = skill_sub.add_parser(
        "usage",
        help="show per-skill usage stats (local, read-only, no resident needed)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn skill usage\n"
        "  zn skill usage --dormant-days 60",
    )
    skill_usage.add_argument(
        "--dormant-days",
        type=lambda v: _require_positive_int(
            v, name="--dormant-days", maximum=3650
        ),
        default=30,
        help="skills unused longer than this are flagged dormant (default 30)",
    )
    skill_usage.add_argument("--json", action="store_true", help="print raw JSON")
    skill_usage.set_defaults(func=_cmd_skill_usage)

    skill_prune = skill_sub.add_parser(
        "prune",
        help="list dormant skill candidates (dry-run only, never deletes)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn skill prune",
    )
    skill_prune.add_argument(
        "--dormant-days",
        type=lambda v: _require_positive_int(
            v, name="--dormant-days", maximum=3650
        ),
        default=30,
        help="skills unused longer than this are listed as dormant (default 30)",
    )
    skill_prune.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="list candidates without deleting (default); --no-dry-run is refused",
    )
    skill_prune.add_argument("--json", action="store_true", help="print raw JSON")
    skill_prune.set_defaults(func=_cmd_skill_prune)

    model = sub.add_parser("model", help="check the local model channel")
    model_sub = model.add_subparsers(
        dest="model_command", metavar="subcommand", required=True
    )

    model_check = model_sub.add_parser(
        "check",
        help="probe configured model routes (local, no resident needed)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn model check\n"
        "  zn model check --probe-timeout 10",
    )
    model_check.add_argument(
        "--probe-timeout",
        type=lambda v: _require_positive_float(
            v, name="--probe-timeout", maximum=300.0
        ),
        default=DEFAULT_PROBE_TIMEOUT_SECONDS,
        help="max seconds to wait per route probe "
        f"(default {DEFAULT_PROBE_TIMEOUT_SECONDS:g})",
    )
    model_check.add_argument("--json", action="store_true", help="print raw JSON")
    model_check.set_defaults(func=_cmd_model_check)

    connector = sub.add_parser("connector", help="inspect connector auto-attachment")
    connector_sub = connector.add_subparsers(
        dest="connector_command", metavar="subcommand", required=True
    )

    connector_list = connector_sub.add_parser(
        "list",
        help="list known connectors (local, no resident needed)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn connector list",
    )
    connector_list.add_argument("--json", action="store_true", help="print raw JSON")
    connector_list.set_defaults(func=_cmd_connector_list)

    connector_status = connector_sub.add_parser(
        "status",
        help="show connector mount status",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn connector status",
    )
    connector_status.add_argument("--json", action="store_true", help="print raw JSON")
    connector_status.set_defaults(func=_cmd_connector_status)

    connector_reload = connector_sub.add_parser(
        "reload",
        help="hot-reload connectors.yaml (no daemon restart)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn connector reload",
    )
    connector_reload.add_argument("--json", action="store_true", help="print raw JSON")
    connector_reload.set_defaults(func=_cmd_connector_reload)

    autonomy = sub.add_parser(
        "autonomy", help="inspect or change the autonomy envelope"
    )
    autonomy_sub = autonomy.add_subparsers(
        dest="autonomy_command", metavar="subcommand", required=True
    )

    autonomy_list = autonomy_sub.add_parser(
        "list",
        help="list explicit per-domain autonomy levels",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn autonomy list",
    )
    autonomy_list.add_argument("--json", action="store_true", help="print raw JSON")
    autonomy_list.set_defaults(func=_cmd_autonomy_list)

    autonomy_get = autonomy_sub.add_parser(
        "get",
        help="show the autonomy level of one domain",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn autonomy get recurring.interval\n"
        "  zn autonomy get connector.weather",
    )
    autonomy_get.add_argument(
        "domain",
        type=lambda v: _require_non_empty(v, name="domain"),
        help="policy domain, e.g. recurring.interval or connector.weather",
    )
    autonomy_get.add_argument("--json", action="store_true", help="print raw JSON")
    autonomy_get.set_defaults(func=_cmd_autonomy_get)

    autonomy_set = autonomy_sub.add_parser(
        "set",
        help="set the autonomy level of one domain (audited)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn autonomy set recurring.interval suggest\n"
        "  zn autonomy set connector.weather require_approval",
    )
    autonomy_set.add_argument(
        "domain",
        type=lambda v: _require_non_empty(v, name="domain"),
        help="policy domain, e.g. recurring.interval or connector.weather "
        "(no wildcards)",
    )
    autonomy_set.add_argument(
        "level",
        type=lambda v: _require_non_empty(v, name="level"),
        help="one of: observe_only, suggest, prepare, execute_reversible, "
        "require_approval",
    )
    autonomy_set.add_argument("--json", action="store_true", help="print raw JSON")
    autonomy_set.set_defaults(func=_cmd_autonomy_set)

    suggestions = sub.add_parser(
        "suggestions", help="inspect or dismiss resident suggestions"
    )
    suggestions_sub = suggestions.add_subparsers(
        dest="suggestions_command", metavar="subcommand", required=True
    )

    suggestions_list = suggestions_sub.add_parser(
        "list",
        help="list active suggestions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn suggestions list\n"
        "  zn suggestions list --limit 5",
    )
    suggestions_list.add_argument(
        "--limit",
        type=lambda v: _require_positive_int(v, name="--limit", maximum=50),
        default=8,
        help="max suggestions to show (default 8)",
    )
    suggestions_list.add_argument("--json", action="store_true", help="print raw JSON")
    suggestions_list.set_defaults(func=_cmd_suggestions_list)

    suggestions_dismiss = suggestions_sub.add_parser(
        "dismiss",
        help="dismiss one suggestion by key",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn suggestions dismiss --key <key>",
    )
    suggestions_dismiss.add_argument(
        "--key",
        required=True,
        type=lambda v: _require_non_empty(v, name="--key"),
        help="suggestion key to dismiss",
    )
    suggestions_dismiss.add_argument(
        "--json", action="store_true", help="print raw JSON"
    )
    suggestions_dismiss.set_defaults(func=_cmd_suggestions_dismiss)

    goal = sub.add_parser(
        "goal", help="inspect the resident's self-drive (M-14) goals"
    )
    goal_sub = goal.add_subparsers(
        dest="goal_command", metavar="subcommand", required=True
    )

    goal_list = goal_sub.add_parser(
        "list",
        help="list self-drive goals (read-only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn goal list\n"
        "  zn goal list --limit 20",
    )
    goal_list.add_argument(
        "--limit",
        type=lambda v: _require_positive_int(v, name="--limit", maximum=200),
        default=50,
        help="max goals to show (default 50)",
    )
    goal_list.add_argument("--json", action="store_true", help="print raw JSON")
    goal_list.set_defaults(func=_cmd_goal_list)

    goal_status = goal_sub.add_parser(
        "status",
        help="show self-drive status (read-only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn goal status",
    )
    goal_status.add_argument("--json", action="store_true", help="print raw JSON")
    goal_status.set_defaults(func=_cmd_goal_status)

    # T9: routines -- read + pause/resume. propose/edit stay on the chat path.
    routine = sub.add_parser(
        "routine", help="inspect or pause/resume the resident's routines"
    )
    routine_sub = routine.add_subparsers(
        dest="routine_command", metavar="subcommand", required=True
    )

    routine_list = routine_sub.add_parser(
        "list",
        help="list routines (read-only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn routine list\n"
        "  zn routine list --limit 20",
    )
    routine_list.add_argument(
        "--limit",
        type=lambda v: _require_positive_int(v, name="--limit", maximum=200),
        default=20,
        help="max routines to show (default 20)",
    )
    routine_list.add_argument("--json", action="store_true", help="print raw JSON")
    routine_list.set_defaults(func=_cmd_routine_list)

    routine_get = routine_sub.add_parser(
        "get",
        help="show one routine in detail (read-only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn routine get routine-abc123",
    )
    routine_get.add_argument(
        "routine_id",
        type=lambda v: _require_non_empty(v, name="routine_id"),
        help="routine id, e.g. routine-abc123",
    )
    routine_get.add_argument("--json", action="store_true", help="print raw JSON")
    routine_get.set_defaults(func=_cmd_routine_get)

    routine_runs = routine_sub.add_parser(
        "runs",
        help="show a routine's run history (read-only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn routine runs routine-abc123\n"
        "  zn routine runs routine-abc123 --limit 5",
    )
    routine_runs.add_argument(
        "routine_id",
        type=lambda v: _require_non_empty(v, name="routine_id"),
        help="routine id, e.g. routine-abc123",
    )
    routine_runs.add_argument(
        "--limit",
        type=lambda v: _require_positive_int(v, name="--limit", maximum=100),
        default=20,
        help="max runs to show (default 20)",
    )
    routine_runs.add_argument("--json", action="store_true", help="print raw JSON")
    routine_runs.set_defaults(func=_cmd_routine_runs)

    routine_pause = routine_sub.add_parser(
        "pause",
        help="pause one routine (audited server-side)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn routine pause routine-abc123\n"
        '  zn routine pause routine-abc123 --reason "出差一周"',
    )
    routine_pause.add_argument(
        "routine_id",
        type=lambda v: _require_non_empty(v, name="routine_id"),
        help="routine id, e.g. routine-abc123",
    )
    routine_pause.add_argument(
        "--reason",
        default=None,
        help="optional pause reason recorded with the routine",
    )
    routine_pause.add_argument("--json", action="store_true", help="print raw JSON")
    routine_pause.set_defaults(func=_cmd_routine_pause)

    routine_resume = routine_sub.add_parser(
        "resume",
        help="resume a paused routine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn routine resume routine-abc123",
    )
    routine_resume.add_argument(
        "routine_id",
        type=lambda v: _require_non_empty(v, name="routine_id"),
        help="routine id, e.g. routine-abc123",
    )
    routine_resume.add_argument("--json", action="store_true", help="print raw JSON")
    routine_resume.set_defaults(func=_cmd_routine_resume)

    # T10: diary -- read-only terminal face for the resident's daily diary.
    # diary_write stays on the chat path. T3-2: epilog examples live on
    # each leaf parser like every other command.
    diary = sub.add_parser(
        "diary", help="read the resident's daily diary entries"
    )
    diary_sub = diary.add_subparsers(
        dest="diary_command", metavar="subcommand", required=True
    )

    diary_list = diary_sub.add_parser(
        "list",
        help="list diary entries, newest first (read-only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn diary list\n"
        "  zn diary list --limit 20",
    )
    diary_list.add_argument(
        "--limit",
        type=lambda v: _require_positive_int(v, name="--limit", maximum=100),
        default=20,
        help="max entries to show (default 20)",
    )
    diary_list.add_argument("--json", action="store_true", help="print raw JSON")
    diary_list.set_defaults(func=_cmd_diary_list)

    diary_get = diary_sub.add_parser(
        "get",
        help="show one diary entry by date (read-only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn diary get --date 2026-10-22",
    )
    diary_get.add_argument(
        "--date",
        required=True,
        type=lambda v: _require_date(v, name="--date"),
        help="entry date in YYYY-MM-DD, e.g. 2026-10-22",
    )
    diary_get.add_argument("--json", action="store_true", help="print raw JSON")
    diary_get.set_defaults(func=_cmd_diary_get)

    # T2-6: one-screen aggregate; read-only, reuses existing daemon RPCs.
    # T3-2: epilog examples live on this leaf parser like every other command.
    status_cmd = sub.add_parser(
        "status",
        help="one-screen ZN status: resident, model, connectors, approvals, autonomy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn status\n"
        "  zn status --probe-timeout 10",
    )
    status_cmd.add_argument(
        "--probe-timeout",
        type=lambda v: _require_positive_float(
            v, name="--probe-timeout", maximum=300.0
        ),
        default=_STATUS_DEFAULT_PROBE_TIMEOUT_SECONDS,
        help="max seconds to wait per model route probe "
        f"(default {_STATUS_DEFAULT_PROBE_TIMEOUT_SECONDS:g}; the model channel "
        "is probed locally, so this works without a running resident)",
    )
    status_cmd.add_argument("--json", action="store_true", help="print raw JSON")
    status_cmd.set_defaults(func=_cmd_status)
    return parser


# T3-3: first-run onboarding hint. Per-process one-shot; never persisted to
# disk -- the "fresh home" condition converges naturally once the resident
# has created its kernel data, so the hint fades away on its own.
_FIRST_RUN_HINT_SHOWN = False

_FIRST_RUN_HINT_LINES = (
    "① 直接运行 `zn` 开口说话交办（已支持交互对话）",
    "② `zn work submit --task \"…\"` 从命令行交办",
    "③ `zn help` 查看全部能干的事",
)


def _zn_home_is_fresh() -> bool:
    """Read-only first-run probe.

    True only when the ZN home holds no resident data yet: neither
    ``<home>/kernel/resident-endpoint.json`` nor the ``<home>/kernel`` data
    directory exists. Never writes anything.
    """
    try:
        endpoint_path = _default_endpoint_path()
    except Exception:
        return False
    return not endpoint_path.exists() and not endpoint_path.parent.is_dir()


def _maybe_print_first_run_hint(args: argparse.Namespace) -> None:
    """Append the T3-3 three-line onboarding hint to stdout.

    Fires only when the ZN home is fresh (no resident data), the call is
    interactive (stdout is a TTY and ``--json`` was not passed), and only
    once per process. The individual ``_cmd_*`` handlers stay unaware of
    this; the tail of :func:`run` owns it.
    """
    global _FIRST_RUN_HINT_SHOWN
    if _FIRST_RUN_HINT_SHOWN:
        return
    if getattr(args, "json", False):
        return
    stdout = sys.stdout
    isatty = getattr(stdout, "isatty", None)
    if not callable(isatty) or not isatty():
        return
    if not _zn_home_is_fresh():
        return
    _FIRST_RUN_HINT_SHOWN = True
    for line in _FIRST_RUN_HINT_LINES:
        print(line, file=stdout)


def run(argv: list[str] | None = None) -> int:
    """Parse argv and run one command. Returns a process exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)
    _set_error_details(getattr(args, "verbose", False))
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if not hasattr(args, "func"):
        # TERM-1: bare `zn` is the front door -- it opens the interactive
        # chat REPL instead of printing help at the user.
        args.func = _cmd_chat
    try:
        code = int(args.func(args))
    except CliError as exc:
        print(f"zn: error: {exc}", file=sys.stderr)
        code = 1
    except BrokenPipeError:
        # stdout is gone; nothing more can be printed.
        return 1
    # T3-3: first-run onboarding hint (fresh home + interactive only).
    _maybe_print_first_run_hint(args)
    return code


def main(argv: list[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
