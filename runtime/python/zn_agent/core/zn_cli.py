"""Thin terminal CLI for the ZN resident: ``zn work ...`` / ``zn approval ...``.

This module is deliberately a thin client, not a second control plane. It
reads the resident endpoint file published by
:mod:`zn_agent.core.resident_server` (``<ZN home>/kernel/resident-endpoint.json``),
authenticates with the per-process session secret, and forwards one JSON-RPC
call per command to the already-existing Daemon RPC methods
(``work_list`` / ``work_get`` / ``work_create`` / ``work_submit`` /
``approval_list`` / ``approval_decide`` / ``approval_rule_delete`` /
``approval_undo`` / ``approval_reconsider_denied`` / ``memory_list`` / ``team_list`` /
``routine_list`` / ``routine_get`` / ``routine_runs`` / ``routine_pause`` /
``routine_resume`` / ``routine_propose`` / ``routine_confirm`` /
``routine_edit`` / ``routine_delete`` / ``diary_list`` / ``diary_get``). All policy, execution, approval and
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
from .routine_request import _parse_schedule_clause
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
    # WK-LAST: `zn work submit --last` with no prior thread. The English
    # fragment in parentheses is kept verbatim for scripts/grep (T2-5);
    # the next step points at the exact first-task command.
    "no_work_history": (
        "还没有历史会话（no work history）：ZN 手上没有任何工作记录，续不上",
        "下一步：先交办第一件事，运行 `zn work submit --task \"…\"`"
        "（不带 --last），会开一个新会话",
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
    # GOAL-HINT: goal group (M16) is read-only -- goals are created through
    # chat by the engine itself, so the next step is a spoken sentence.
    "goal_list": "下一步：跟 ZN 说一句话就能立一个自驱目标，比如「帮我盯着新款显卡的降价」",
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
    thread_id = args.thread_id
    if getattr(args, "last", False):
        # WK-LAST2: resolve the newest thread first; the rest of the get
        # path below is untouched (same RPC, same output).
        code, thread_id, title = _resolve_last_work_thread(
            args,
            unavailable="没有取到任何会话（这次查看没有结果）",
            json_payload={"fetched": False},
        )
        if code is not None:
            return code
        _print_last_thread_resolved(
            args, verb="查看", thread_id=thread_id, title=title
        )
    result = _client(args).call(
        "work_get",
        {"thread_id": thread_id, "message_limit": args.message_limit},
    )
    if not isinstance(result, dict):
        raise _unexpected_result("work_get", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"{result.get('id') or thread_id}  {_one_line(result.get('title'), limit=80)}")
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


# --- WK-DUR: client-side elapsed time for work runs --------------------------
# The resident never reports wall-clock duration, so the CLI times the
# blocking RPC itself with ``time.monotonic`` (daemon untouched). Format
# follows Chinese reading habits: one decimal below 10 seconds
# (``用时 3.2 秒``), whole seconds at 10 and above (``用时 12 秒``).
def _format_elapsed_seconds(seconds: float) -> str:
    """Chinese-friendly duration fragment (``"3.2"`` / ``"12"``)."""
    total = max(0.0, float(seconds))
    if round(total, 1) < 10:
        return f"{total:.1f}"
    return str(int(round(total)))


# --- D3: "what next" hint when the submitted run reports failure ---------------
# When `zn work submit` finishes with ``success=False``, the summary line
# alone ("run event=… success=False …") is a dead end for a novice: nothing
# says what to do next. Name the next step: inspect the thread with
# `zn work get --thread-id <thread_id>` to see the failure reason. TTY-only
# via the same ``use_color()`` gate as the T3-4/D2 hints; the ``--json``
# branch of ``_cmd_work_submit`` returns earlier, so piped / script output
# stays byte-stable. Copy follows the T2-5 Chinese wording convention
# ("下一步：" + 人话 + backtick command + （英文技术片段）).
_WORK_SUBMIT_FAILURE_HINT = (
    "下一步：这次交办失败了（success=False），用 "
    "`zn work get --thread-id {thread_id}` 看失败原因"
)


def _print_submit_failure_hint(thread_id: str) -> None:
    """Print the one-line D3 next-step hint for a failed work_submit run."""
    if use_color():
        print(colorize(f"  {_WORK_SUBMIT_FAILURE_HINT.format(thread_id=thread_id)}", "dim"))


def _print_work_submit_result(
    result: dict[str, Any], thread_id: str, elapsed_seconds: float
) -> None:
    """Final human summary of a work_submit result (pre-T2-2 format kept).

    ``elapsed_seconds`` is the client-side wall time of the blocking
    ``work_submit`` RPC (``time.monotonic`` around it); it is always shown --
    a duration is a fact line, not TTY decoration -- while ``--json`` keeps
    its historic byte-stable shape.
    """
    thread = result.get("thread") if isinstance(result.get("thread"), dict) else {}
    run = result.get("run") if isinstance(result.get("run"), dict) else {}
    if result.get("recovery_required"):
        print("recovery required: the work was recorded and needs a recovery step")
    elif run:
        print(
            f"run event={run.get('event_id') or '-'}  success={run.get('success')}  "
            f"cancelled={run.get('cancelled')}  path={run.get('execution_path') or '-'}  "
            f"model_invocations={run.get('model_invocations')}  "
            f"用时 {_format_elapsed_seconds(elapsed_seconds)} 秒"
        )
        if not run.get("success"):
            # D3: the run reports failure (or the result is not success=True);
            # name the next step so the failure is not a dead end.
            _print_submit_failure_hint(thread_id)
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


# --- WK-LAST: `zn work submit --last` ("续最近会话") --------------------------
# Resolve the most recent work thread with one read-only ``work_list``
# probe (``limit=1``) -- the same pattern the REPL's ``/resume`` uses
# (``_resume_latest`` in ``cli_repl.py``; a small local twin here because
# ``cli_repl`` imports ``zn_cli``, so the import would be circular).
# Then the existing submit path runs unchanged with the resolved thread.
# Contracts:
# - T2-1: presentation uses the cli_format contract; the TTY "续上会话" line
#   is plain Chinese copy behind ``use_color()``, no symbols to degrade.
# - T2-5: empty history is a humanized ``CliError`` (English fragment in
#   parentheses kept verbatim, ``_ERROR_COPY["no_work_history"]``).
# - T2-6: a failed probe never claims a submission -- connection/transport
#   problems exit 0 with the honest offline note; a server-side rejection
#   re-raises humanized (exit 1).
# - T2-7 / --json: the TTY line prints only in human non-JSON mode; ``--json``
#   stays byte-for-byte the ``work_submit`` result, and pipes keep the
#   historic output.


def _latest_work_thread(result: Any) -> tuple[str, str] | None:
    """Return ``(thread_id, title)`` of the newest snapshot in a ``work_list`` result.

    ``work_list`` returns snapshots newest-first (``updated_at DESC``), so
    the first entry is the most recent thread. Returns ``None`` when there
    is no usable thread -- empty history or a malformed payload.
    """
    if not isinstance(result, list) or not result:
        return None
    first = result[0]
    if not isinstance(first, dict):
        return None
    thread_id = str(first.get("id") or "").strip()
    if not thread_id:
        return None
    return thread_id, _one_line(first.get("title"), limit=60)


def _cmd_work_submit(args: argparse.Namespace) -> int:
    endpoint = load_endpoint(getattr(args, "endpoint", None))
    client = ResidentClient(endpoint, timeout=args.timeout)
    thread_id = args.thread_id
    title = args.title
    if getattr(args, "last", False):
        # --last: resolve the newest thread first; the rest of the submit
        # path below is untouched (same RPCs, same output).
        try:
            listed = client.call("work_list", {"limit": 1})
        except CliError as exc:
            if str(exc).startswith(_WORK_DRIVE_RPC_REJECTED_PREFIX):
                raise  # server-side rejection: humanized copy, exit 1
            # T2-6: unreachable resident -- exit 0, honestly saying nothing
            # was resumed or submitted.
            return _work_drive_offline(
                args,
                str(exc),
                unavailable="没有续上任何会话（这次任务未交办）",
                json_payload={"resumed": False, "submitted": False},
            )
        if not isinstance(listed, list):
            raise _unexpected_result("work_list", listed)
        latest = _latest_work_thread(listed)
        if latest is None:
            raise _cli_error("no_work_history")  # humanized, exit 1
        thread_id, title = latest
        if use_color() and not args.json:
            # TTY-only one-liner naming the resumed session (T2-1/T2-7);
            # --json and pipes keep the historic byte-stable output.
            title_part = f"「{title}」" if title else ""
            print(f"续上会话{title_part}({thread_id})")
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
    # WK-DUR: client-side wall time around the blocking submit RPC
    # (daemon untouched; time.monotonic, pure client measurement).
    submit_started = time.monotonic()
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
    elapsed_seconds = time.monotonic() - submit_started
    _print_work_submit_result(result, thread_id, elapsed_seconds)
    return 0


# --- WK-LAST2: `zn work get --last` / `zn work cancel --last` -----------------
# The natural follow-up to WK-LAST (`zn work submit --last`): one read-only
# ``work_list`` probe (``limit=1``) resolves the newest thread, then the
# existing get/cancel path runs unchanged with the resolved id. daemon.py is
# untouched -- no new RPC, only the existing work_list/get/cancel paths.
#
# cancel semantics (decided here): ``--last`` only resolves the *thread*;
# ``--event-id`` stays required. Cancelling an event is a destructive
# choice, so the user still names which event to cancel; a bare
# ``zn work cancel --last`` exits 2 (argparse: --event-id is required).
#
# Contracts, all inherited from WK-LAST:
# - T2-5: empty history raises the shared ``_ERROR_COPY["no_work_history"]``
#   copy verbatim (humanized, exit 1). Its next step already points at
#   submitting the first task, which is the correct fix for get/cancel too.
# - T2-6: a failed probe never claims anything -- an unreachable resident
#   exits 0 with the honest offline note naming what was NOT done; a
#   server-side rejection re-raises humanized (exit 1).
# - T2-1/T2-7: the TTY-only one-liner naming the resolved session is plain
#   Chinese behind ``use_color()``; --json and pipes keep historic bytes.
# - argparse mutual exclusion: --last vs --thread-id conflicts exit 2 (the
#   groups are built in build_parser, next to the other work subparsers).


def _resolve_last_work_thread(
    args: argparse.Namespace, *, unavailable: str, json_payload: dict[str, Any]
) -> tuple[int | None, str, str]:
    """Resolve ``--last`` to ``(offline_exit_code, thread_id, title)``.

    *offline_exit_code* is not None only for the T2-6 offline case -- the
    honest note is already printed and the caller must stop with that code
    (0). Server-side rejections re-raise humanized; empty history raises
    the shared humanized copy; a malformed probe payload raises
    ``_unexpected_result("work_list")``.
    """
    endpoint = load_endpoint(getattr(args, "endpoint", None))
    client = ResidentClient(endpoint, timeout=args.timeout)
    try:
        listed = client.call("work_list", {"limit": 1})
    except CliError as exc:
        if str(exc).startswith(_WORK_DRIVE_RPC_REJECTED_PREFIX):
            raise  # server-side rejection: humanized copy, exit 1
        # T2-6: unreachable resident -- exit 0, honestly saying nothing
        # was fetched or cancelled.
        code = _work_drive_offline(
            args, str(exc), unavailable=unavailable, json_payload=json_payload
        )
        return code, "", ""
    if not isinstance(listed, list):
        raise _unexpected_result("work_list", listed)
    latest = _latest_work_thread(listed)
    if latest is None:
        raise _cli_error("no_work_history")  # humanized, exit 1
    thread_id, title = latest
    return None, thread_id, title


def _print_last_thread_resolved(
    args: argparse.Namespace,
    *,
    verb: str,
    thread_id: str,
    title: str,
    suffix: str = "",
) -> None:
    """TTY-only one-liner naming the session ``--last`` resolved to.

    Plain Chinese copy (T2-1/T2-7); suppressed for --json and pipes so the
    historic byte-stable output is unchanged.
    """
    if use_color() and not args.json:
        title_part = f"「{title}」" if title else ""
        print(f"{verb}最近的会话{title_part}({thread_id}){suffix}")


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
    # AP-1: feedback recorded with the decision (--deny --note). Shown
    # only when present, so note-less cards render exactly as before.
    decision_note = _one_line(item.get("decision_note"), limit=200)
    if decision_note:
        rows.append(("决定备注", decision_note))
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
    note = str(args.note or "")
    params: dict[str, Any] = {"request_id": args.request_id, "decision": decision}
    if chosen[0] == "deny":
        # AP-1: feedback is only meaningful on a denial; without a note
        # the RPC params stay byte-identical to the old call shape.
        if note.strip():
            params["note"] = note.strip()
    elif note.strip():
        # AP-1: --note on an approval is warned and dropped, never
        # silently recorded. An audit note on an approval would read like
        # a condition on the allow, which this feature is not; the note
        # channel is the denial feedback from term-design-notes #5.
        print(
            "提醒：--note 只在拒绝（--deny）时记录；本次批准不记录备注，已忽略该参数 "
            "(--note is only recorded with --deny; ignored for approvals)",
            file=sys.stderr,
        )
    result = _client(args).call("approval_decide", params)
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
# path that creates an auto-allow rule. T12 adds the terminal face for
# ``approval_reconsider_denied`` (denied cards: create a fresh pending
# card + audited entry; the denied record is never mutated). Still no new
# daemon RPC and no daemon.py changes: the RPC already exists.
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


def _humanize_reconsider_error(exc: CliError, request_id: str) -> CliError:
    """Turn ``approval_reconsider_denied`` rejections into human copy (T2-5).

    The daemon raises ValueError with one English reason per failure mode
    (see ``reconsider_denied`` in approval_cards.py); each becomes a
    Chinese lead line with the English fragment kept in parentheses so the
    server contract stays greppable. Unknown errors pass through.
    """
    text = str(exc)
    if "unknown approval request" in text:
        return CliError(
            f"找不到审批卡 '{request_id}'（unknown approval request）。"
            "用 'zn approval list --status denied' 看看被拒的申请。"
        )
    if "only denied approval requests can be reconsidered" in text:
        status = "?"
        match = re.search(r"is ([a-z_]+)\s*$", text)
        if match:
            status = status_word(match.group(1))
        return CliError(
            f"这张卡不是被拒的申请，无法重新考虑"
            f"（only denied approval requests can be reconsidered）："
            f"'{request_id}' 当前是 {status}。"
            "只有状态为 denied 的申请才能重新考虑。"
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


# --- T12: `zn approval reconsider <request-id> [--note]` --------------------
# Terminal face for the daemon RPC ``approval_reconsider_denied``: a
# denied card gets a fresh pending card plus an audited
# ``deny_overridden`` entry; the denied record is never mutated. Follows
# the T11 offline contract: unreachable resident -> exit 0 with a human
# note that never claims a mutation; RPC ok:false -> humanized T2-5
# error, exit 1. No daemon changes.


def _cmd_approval_reconsider(args: argparse.Namespace) -> int:
    request_id = str(args.request_id)
    note = str(args.note or "")
    try:
        ok, payload = _approval_t11_rpc(
            args,
            "approval_reconsider_denied",
            {"request_id": request_id, "note": note},
        )
    except CliError as exc:
        raise _humanize_reconsider_error(exc, request_id)
    if not ok:
        return _approval_t11_offline(
            args,
            payload,
            unavailable=f"没有为被拒的申请发起重新考虑（'{request_id}' 保持被拒状态）",
            json_payload={"reconsidered": False, "request_id": request_id},
        )
    if not isinstance(payload, dict) or not isinstance(
        payload.get("request"), dict
    ):
        raise _unexpected_result("approval_reconsider_denied", payload)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    request = payload["request"]
    new_id = _one_line(request.get("request_id"), limit=40) or "?"
    status = status_word(request.get("status") or "pending")
    lines = [
        f"已为被拒的申请发起重新考虑，新审批卡 {new_id} 待审批（{status}）",
        f"  原卡片：{request_id}（denied，记录保持不变）",
    ]
    if note.strip():
        lines.append(f"  说明：{_one_line(note.strip(), limit=120)}")
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


# --- T13: `zn team assign ...` / `zn team handover-done` ----------------------
# Team driving terminal entries. The workbench "做完了" button used to call
# `team_handover_done`; the workbench is gone (desktop removed in #623), so
# the terminal owns these steering actions now. The offline contract is
# T2-6 style (T11/T12): exit 0 + human note when the resident is
# unreachable, never claiming a mutation happened; server-side rejections
# surface humanized (T2-5), exit 1. daemon.py is untouched.

_TEAM_T13_RPC_REJECTED_PREFIX = _ERROR_COPY["rpc_rejected"][0].split("{method}")[0]


def _team_t13_rpc(
    args: argparse.Namespace, method: str, params: dict[str, Any]
) -> tuple[bool, Any]:
    """Call one team-driving RPC, classifying failures.

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
        if text.startswith(_TEAM_T13_RPC_REJECTED_PREFIX):
            raise
        return False, text


def _team_t13_offline(
    args: argparse.Namespace,
    error: str,
    *,
    unavailable: str,
    json_payload: dict[str, Any],
) -> int:
    """T2-6-style offline rendering for the T13 commands: exit 0.

    *unavailable* names what could not be done ("没有为团队指派新的专员",
    "没有放行任何敏感步骤", ...). Never claims a mutation happened.
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


def _humanize_team_thread_error(exc: CliError, thread_id: str) -> CliError:
    """Swap the raw ``unknown work thread`` rejection for human copy.

    Shared by both T13 commands: the daemon answers ``ok: false`` with
    ``ValueError: unknown work thread: '<id>'`` (see the team RPC dispatch
    in daemon.py). Any other error is returned unchanged.
    """
    if "unknown work thread" in str(exc):
        return CliError(
            f"找不到工作线程 '{thread_id}'（unknown work thread）。"
            "用 'zn work list' 看看现有的线程。"
        )
    return exc


def _humanize_assign_error(exc: CliError, thread_id: str) -> CliError:
    """Turn ``team_assign`` server rejections into human copy (T2-5).

    The daemon raises ValueError with one reason per failure mode (see
    ``_team_assign`` in daemon.py): reasons already written in Chinese pass
    through unchanged; English ones get a Chinese lead line with the
    English fragment kept in parentheses. Unknown errors pass through.
    """
    text = str(exc)
    if "unknown work thread" in text:
        return _humanize_team_thread_error(exc, thread_id)
    if "resident has no work ledger" in text:
        return CliError(
            "常驻服务内部缺少工作账本（resident has no work ledger）："
            "暂时无法读取团队计划，稍后重试；若持续出现请重启常驻服务。"
        )
    return exc


def _normalize_specialist(raw: Any) -> str:
    """Strip the optional leading ``@`` from the specialist argument.

    The CLI spells the command ``zn team assign @designer ...``; the
    ``team_assign`` RPC takes the bare member name (the daemon renders the
    ``@`` itself when journaling the assignment).
    """
    name = str(raw or "").strip()
    return name[1:] if name.startswith("@") else name


def _cmd_team_assign(args: argparse.Namespace) -> int:
    thread_id = str(args.thread_id)
    specialist = _normalize_specialist(args.specialist)
    instruction = str(args.instruction or "")
    if not specialist:
        # Only reachable with a bare "@": _require_non_empty already
        # rejected the empty string, so this is an argparse-grade error.
        raise CliError(
            "专员名字不能为空：用法如 zn team assign @设计 "
            "--thread-id <thread-id> \"把首页排版重做一遍\""
        )
    try:
        ok, payload = _team_t13_rpc(
            args,
            "team_assign",
            {
                "thread_id": thread_id,
                "specialist": specialist,
                "instruction": instruction,
            },
        )
    except CliError as exc:
        raise _humanize_assign_error(exc, thread_id)
    if not ok:
        return _team_t13_offline(
            args,
            payload,
            unavailable=f"没有为团队指派新的专员（@{specialist} 的指派未生效）",
            json_payload={
                "assigned": False,
                "thread_id": thread_id,
                "specialist": specialist,
            },
        )
    if not isinstance(payload, dict) or not payload.get("item_id"):
        raise _unexpected_result("team_assign", payload)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    item_title = _one_line(payload.get("item_title"), limit=80) or "?"
    team_id = _one_line(payload.get("team_id"), limit=40) or "-"
    lines = [
        f"已把团队下一项任务指派给 @{specialist}（assigned）",
        f"  任务：{item_title}",
        f"  团队：{team_id}",
    ]
    if instruction.strip():
        lines.append(f"  说明：{_one_line(instruction.strip(), limit=120)}")
    lines.append(
        "  下一步：用 "
        f"'zn team timeline --thread-id {thread_id}' 看指派是否已记入时间线"
    )
    print("\n".join(lines))
    return 0


def _humanize_handover_done_error(exc: CliError, thread_id: str) -> CliError:
    """Turn ``team_handover_done`` server rejections into human copy (T2-5).

    The daemon raises ValueError for an unknown thread and for "no pending
    sensitive step" (see ``_team_handover_done`` in daemon.py); the latter
    is the spec's "no pending -> human refusal, non-zero exit" branch.
    """
    text = str(exc)
    if "unknown work thread" in text:
        return _humanize_team_thread_error(exc, thread_id)
    if "没有待主人完成的敏感步骤" in text:
        return CliError(
            "该团队当前没有待主人完成的敏感步骤（no pending handover）："
            f"线程 '{thread_id}' 无需放行。"
        )
    return exc


def _cmd_team_handover_done(args: argparse.Namespace) -> int:
    thread_id = str(args.thread_id)
    try:
        ok, payload = _team_t13_rpc(
            args, "team_handover_done", {"thread_id": thread_id}
        )
    except CliError as exc:
        raise _humanize_handover_done_error(exc, thread_id)
    if not ok:
        return _team_t13_offline(
            args,
            payload,
            unavailable="没有放行任何敏感步骤",
            json_payload={"resolved": False, "thread_id": thread_id},
        )
    if (
        not isinstance(payload, dict)
        or not payload.get("handover_id")
        or payload.get("status") != "resolved"
    ):
        raise _unexpected_result("team_handover_done", payload)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    handover_id = _one_line(payload.get("handover_id"), limit=40) or "?"
    kind = _one_line(payload.get("kind"), limit=32)
    team_id = _one_line(payload.get("team_id"), limit=40) or "-"
    detail = f"  交接：{handover_id}"
    if kind:
        detail += f"（{kind}）"
    lines = [
        "敏感步骤已放行，团队继续（resolved）",
        detail,
        f"  团队：{team_id}",
    ]
    print("\n".join(lines))
    return 0


# --- D4: humanized error + next-step hint when cancelling a finished run ----
# `zn work cancel` on a run that already ended dies with the server's raw
# ``RuntimeError: work cancellation requires an active Work run`` and names
# no next step. Humanize that one known rejection (Chinese body + the
# English technical snippet in parentheses, T2-5 convention) and print the
# dim next-step hint: the run is over, inspect it with
# `zn work get --thread-id <thread_id>`. The whole special case is TTY-only
# via the same ``use_color()`` gate as the T3-4/D2/D3 hints (``--json`` is
# excluded even on a real terminal): pipes, NO_COLOR and ``--json`` keep
# the historic generic ``rpc_rejected`` error byte-stable. Only the exact
# finished-run signature matches; every other server error travels the
# untouched generic path. Exit 1 still comes from the central ``run()``
# CliError handling, so the exit-code contract is unchanged.
_WORK_CANCEL_FINISHED_SIGNATURE = "RuntimeError: work cancellation requires an active"
_WORK_CANCEL_FINISHED_LEAD = (
    "这个任务已经结束了，取消不了（work cancellation requires an active Work run）"
)
_WORK_CANCEL_FINISHED_HINT = (
    "下一步：活已经结束了，用 `zn work get --thread-id {thread_id}` 看结果"
)
_WORK_CANCEL_REJECTED_PREFIX = _ERROR_COPY["rpc_rejected"][0].format(
    method="work_cancel", detail=""
)


def _work_cancel_finished_run(exc: CliError) -> bool:
    """True when *exc* is the known finished-run ``work_cancel`` rejection.

    Only the generic ``rpc_rejected`` error for ``work_cancel`` whose detail
    starts with ``RuntimeError: work cancellation requires an active``
    (raised by ``work_control`` for a run that already ended) counts;
    anything else keeps the historic generic path.
    """
    text = str(exc)
    if not text.startswith(_WORK_CANCEL_REJECTED_PREFIX):
        return False
    detail = text[len(_WORK_CANCEL_REJECTED_PREFIX):]
    return detail.startswith(_WORK_CANCEL_FINISHED_SIGNATURE)


def _print_cancel_finished_hint(thread_id: str) -> None:
    """Print the one-line D4 next-step hint for cancelling a finished run."""
    if use_color():
        print(colorize(f"  {_WORK_CANCEL_FINISHED_HINT.format(thread_id=thread_id)}", "dim"))


def _cmd_work_cancel(args: argparse.Namespace) -> int:
    thread_id = args.thread_id
    if getattr(args, "last", False):
        # WK-LAST2: --last only resolves the thread; --event-id stays
        # required (see the parser comment). The cancel path below is
        # untouched (same RPC, same output).
        code, thread_id, title = _resolve_last_work_thread(
            args,
            unavailable="没有取消任何会话（这次取消没有执行）",
            json_payload={"cancelled": False},
        )
        if code is not None:
            return code
        _print_last_thread_resolved(
            args,
            verb="取消",
            thread_id=thread_id,
            title=title,
            suffix=f"上的事件 {args.event_id}",
        )
    try:
        result = _client(args).call(
            "work_cancel",
            {"thread_id": thread_id, "event_id": args.event_id},
        )
    except CliError as exc:
        # D4: cancelling a finished run is a known dead end -- humanize it
        # and name the next step on a real human terminal only; pipes /
        # NO_COLOR / --json keep the historic generic error byte-stable,
        # and any other rejection travels the untouched generic path.
        if _work_cancel_finished_run(exc) and use_color() and not args.json:
            _print_cancel_finished_hint(thread_id)
            raise CliError(_WORK_CANCEL_FINISHED_LEAD) from None
        raise
    if not isinstance(result, dict) or not isinstance(result.get("progress"), dict):
        raise _unexpected_result("work_cancel", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    progress = result["progress"]
    print(
        f"cancelled event={args.event_id} on thread={thread_id}  "
        f"state={_one_line(progress.get('state') or progress.get('status') or '?')}"
    )
    cancelled = progress.get("cancelled")
    if cancelled is not None:
        print(f"  cancelled={cancelled}")
    reason = _one_line(progress.get("reason"), limit=120)
    if reason:
        print(f"  reason: {reason}")
    return 0


# --- T14: `zn work resolve-uncertain` ----------------------------------------
# Terminal entry for the daemon's ``work_resolve_uncertain`` RPC
# (daemon.py:626 -> work_control.py:425): an active run's attempt whose side
# effect is uncertain (common after a crash/restart) gets an explicit human
# decision -- ``effect_happened`` (count it as happened, never re-dispatched)
# or ``retry_authorized`` (allow the resident to retry that step once).
# daemon.py is untouched.
#
# Contracts, all inherited from the T12/T13/D4 lineage:
# - T2-5: server rejections surface humanized (Chinese body + the English
#   technical snippet in parentheses). The known dead end is a run that is
#   no longer active -- ``RuntimeError: work uncertain-effect resolution
#   requires an active`` -- which gets a plain-language lead + a TTY-only
#   next-step hint, the same D4 pattern as ``zn work cancel``; unknown
#   event / attempt-checkpoint mismatches get their own human copy. Exit 1
#   still comes from the central ``run()`` CliError handling, so the
#   exit-code contract is unchanged.
# - T2-6: unreachable resident -> exit 0 + an honest note naming what was
#   NOT decided, never claiming a mutation happened.
# - T2-7: TTY-only niceties stay behind ``use_color()``; pipes, NO_COLOR
#   and ``--json`` keep historic bytes.
# T16 note: these two helpers started life as T14-specific names; they are
# behavior-generic (one work-driving RPC call + offline rendering) and are
# shared by T14/T16/T20. Renamed without behavior change.
_WORK_DRIVE_RPC_REJECTED_PREFIX = _ERROR_COPY["rpc_rejected"][0].split("{method}")[0]


def _work_drive_rpc(
    args: argparse.Namespace, method: str, params: dict[str, Any]
) -> tuple[bool, Any]:
    """Call one work-driving RPC, classifying failures.

    Returns ``(True, result)`` on success, or ``(False, error_text)`` when
    the call never got a usable answer from the resident (missing / bad
    endpoint, connection, auth or transport problems) -- the offline path.
    A server-side rejection (``ok: false``) re-raises as :class:`CliError`
    so the humanized ``rpc_rejected`` copy reaches stderr with exit 1.
    """
    try:
        return True, _client(args).call(method, params)
    except CliError as exc:
        if str(exc).startswith(_WORK_DRIVE_RPC_REJECTED_PREFIX):
            raise
        return False, str(exc)


def _work_drive_offline(
    args: argparse.Namespace,
    error: str,
    *,
    unavailable: str,
    json_payload: dict[str, Any],
) -> int:
    """T2-6-style offline rendering for work-driving commands: exit 0.

    *unavailable* names what could not be done ("没有给线程改名").
    Never claims a mutation happened.
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


# D4-style: resolving a finished run's uncertainty is a known dead end --
# the daemon raises ``RuntimeError`` through ``work_control.resolve_uncertain``
# for a run that already ended.
_WORK_RESOLVE_NON_ACTIVE_SIGNATURE = (
    "RuntimeError: work uncertain-effect resolution requires an active"
)
_WORK_RESOLVE_NON_ACTIVE_LEAD = (
    "这个任务已经结束了，裁决不了"
    "（work uncertain-effect resolution requires an active Work run）"
)
_WORK_RESOLVE_NON_ACTIVE_HINT = (
    "下一步：活已经结束了，用 `zn work get --thread-id {thread_id}` 看结果"
)
_WORK_RESOLVE_REJECTED_PREFIX = _ERROR_COPY["rpc_rejected"][0].format(
    method="work_resolve_uncertain", detail=""
)


def _work_resolve_non_active_run(exc: CliError) -> bool:
    """True when *exc* is the known non-active-run rejection.

    Only the generic ``rpc_rejected`` error for ``work_resolve_uncertain``
    whose detail starts with the non-active signature counts; anything else
    keeps its own path.
    """
    text = str(exc)
    if not text.startswith(_WORK_RESOLVE_REJECTED_PREFIX):
        return False
    detail = text[len(_WORK_RESOLVE_REJECTED_PREFIX):]
    return detail.startswith(_WORK_RESOLVE_NON_ACTIVE_SIGNATURE)


def _print_resolve_non_active_hint(thread_id: str) -> None:
    """Print the one-line next-step hint for resolving a finished run."""
    if use_color():
        print(colorize(f"  {_WORK_RESOLVE_NON_ACTIVE_HINT.format(thread_id=thread_id)}", "dim"))


def _humanize_work_resolve_error(
    exc: CliError, args: argparse.Namespace
) -> CliError:
    """Turn ``work_resolve_uncertain`` server rejections into human copy (T2-5).

    The daemon raises ``ValueError("unknown work event for thread")`` when
    the event id is not on the thread, and ``RuntimeError("uncertain event
    resolution ...")`` (store.py) when the attempt id does not match the
    active recovery checkpoint or the event is not waiting on a human
    decision. Anything else travels the untouched generic path.
    """
    text = str(exc)
    thread_id = str(args.thread_id)
    event_id = str(args.event_id)
    if "unknown work event for thread" in text:
        return CliError(
            f"找不到这个工作事件（unknown work event for thread）："
            f"线程 '{thread_id}' 里没有事件 '{event_id}'。"
            f"用 `zn work get --thread-id {thread_id}` 看看。"
        )
    if "uncertain event resolution" in text:
        tail = text.split("uncertain event resolution", 1)[1].strip()
        snippet = "uncertain event resolution" + ((" " + tail) if tail else "")
        return CliError(
            "这次尝试现在不在等待人工裁决的状态"
            f"（{snippet}）："
            f"先用 `zn work get --thread-id {thread_id}` 看事件是否还在等待人工裁决。"
        )
    return exc


_WORK_RESOLVE_DECISIONS = ("effect_happened", "retry_authorized")
_WORK_RESOLVE_DECISION_HUMAN = {
    "effect_happened": "effect_happened（副作用已发生，不再重发）",
    "retry_authorized": "retry_authorized（允许 ZN 重试这一步）",
}
# T14: TTY-only one-liner explaining what an "uncertain side effect" means.
_WORK_RESOLVE_UNCERTAIN_NOTE = (
    "说明：「副作用不确定」是 ZN 发出了外部动作（比如付款、下单、发消息）却没收到"
    "确定的回执（崩溃或重启时常见）——由你来定夺这一步到底算没算发生。"
)


def _cmd_work_resolve_uncertain(args: argparse.Namespace) -> int:
    try:
        ok, payload = _work_drive_rpc(
            args,
            "work_resolve_uncertain",
            {
                "thread_id": args.thread_id,
                "event_id": args.event_id,
                "attempt_id": args.attempt_id,
                "decision": args.decision,
            },
        )
    except CliError as exc:
        # T14/D4: resolving a finished run is a known dead end -- humanize
        # it and name the next step on a real human terminal only; pipes /
        # NO_COLOR / --json keep the historic generic error byte-stable,
        # and any other rejection travels the humanized (T2-5) or generic
        # path. Exit 1 still comes from the central run() CliError handling.
        if _work_resolve_non_active_run(exc) and use_color() and not args.json:
            _print_resolve_non_active_hint(args.thread_id)
            raise CliError(_WORK_RESOLVE_NON_ACTIVE_LEAD) from None
        raise _humanize_work_resolve_error(exc, args)
    if not ok:
        # T2-6: unreachable resident -- exit 0, honestly saying nothing was
        # decided; never claim the decision took effect.
        return _work_drive_offline(
            args,
            payload,
            unavailable="没有裁决任何不确定的副作用（这次裁决未生效）",
            json_payload={
                "resolved": False,
                "thread_id": args.thread_id,
                "event_id": args.event_id,
                "attempt_id": args.attempt_id,
            },
        )
    if not isinstance(payload, dict) or not isinstance(payload.get("progress"), dict):
        raise _unexpected_result("work_resolve_uncertain", payload)
    if args.json:
        # --json passes the RPC result through byte-for-byte (same
        # serialization convention as every other command).
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    if use_color():
        # TTY-only one-liner explaining what "uncertain" means (T14 spec).
        print(_WORK_RESOLVE_UNCERTAIN_NOTE)
    progress = payload["progress"]
    print(
        f"resolved event={args.event_id} attempt={args.attempt_id} "
        f"on thread={args.thread_id}"
    )
    print(
        "  裁决："
        f"{_WORK_RESOLVE_DECISION_HUMAN.get(args.decision, args.decision)}"
    )
    state = _one_line(progress.get("state") or progress.get("status") or "?")
    print(f"  state={state}")
    return 0


# --- T16: `zn work rename` / `zn work attach` --------------------------------
# Terminal entries for the daemon's ``work_rename`` (daemon.py:457) and
# ``work_attach_workspace`` (daemon.py:484) RPCs. daemon.py is untouched.
#
# Contracts, inherited from the T12/T13/T14/D4 lineage:
# - T2-1: presentation uses only the cli_format contract (plain human copy
#   always; TTY niceties behind ``use_color()``).
# - T2-5: server rejections humanized (Chinese body + English technical
#   snippet in parentheses). ``work_rename`` rejects unknown thread ids
#   with ``ValueError("unknown work thread")``. ``work_attach_workspace``
#   also validates the path server-side, but the client pre-checks it first
#   so a typoed path never leaves the terminal.
# - T2-6: unreachable resident -> exit 0 + an honest note naming what was
#   NOT done, never claiming a mutation happened.
# - T2-7: TTY-only hints stay behind ``use_color()``; pipes, NO_COLOR and
#   ``--json`` keep historic bytes.
# - T2-4: ``--json`` prints the RPC result byte-for-byte; exit codes for
#   missing/illegal CLI args come from argparse (exit 2).
# Note the strict RPC schema: ``work_rename`` accepts *exactly*
# {"thread_id", "title"} (the daemon raises otherwise), so the client sends
# exactly those two keys -- asserted in the tests.
_WORK_RENAME_UNKNOWN_THREAD_SIGNATURE = "unknown work thread"


def _humanize_work_rename_error(
    exc: CliError, args: argparse.Namespace
) -> CliError:
    """Turn ``work_rename`` server rejections into human copy (T2-5).

    Unknown thread ids surface as the daemon's
    ``ValueError("unknown work thread")``; anything else travels the
    untouched generic path.
    """
    thread_id = str(args.thread_id)
    if _WORK_RENAME_UNKNOWN_THREAD_SIGNATURE in str(exc):
        return CliError(
            "找不到这个工作线程（unknown work thread）："
            f"线程 '{thread_id}' 不存在。"
            "用 `zn work list` 看看。"
        )
    return exc


def _cmd_work_rename(args: argparse.Namespace) -> int:
    try:
        ok, payload = _work_drive_rpc(
            args,
            "work_rename",
            {"thread_id": args.thread_id, "title": args.title},
        )
    except CliError as exc:
        raise _humanize_work_rename_error(exc, args)
    if not ok:
        # T2-6: unreachable resident -- exit 0, honestly saying the rename
        # did not happen; never claim the thread got a new title.
        return _work_drive_offline(
            args,
            payload,
            unavailable="没有给线程改名（这次改名未生效）",
            json_payload={
                "renamed": False,
                "thread_id": args.thread_id,
                "title": args.title,
            },
        )
    if not isinstance(payload, dict) or not isinstance(payload.get("title"), str):
        raise _unexpected_result("work_rename", payload)
    if args.json:
        # --json passes the RPC result through byte-for-byte (same
        # serialization convention as every other command).
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    new_title = payload["title"]
    print(f"renamed thread={args.thread_id}")
    print(f"  新标题：{new_title}")
    if use_color():
        print(colorize("  用 `zn work list` 确认新标题", "dim"))
    return 0


# The client-side workspace-directory check for `zn work attach` (T16 spec):
# a typoed path must fail before any RPC leaves the terminal, with human
# copy that names what was wrong.
_WORK_ATTACH_NOT_FOUND = (
    "找不到这个目录（path does not exist: {path}）：请检查路径是否输错，"
    "zn work attach 需要一个真实存在的目录。"
)
_WORK_ATTACH_NOT_A_DIR = (
    "这不是一个目录（not a directory: {path}）："
    "zn work attach 需要绑定一个目录，请换一个目录路径。"
)


def _work_attach_checked_path(raw_path: str) -> str:
    """Validate the user's --path locally; raise CliError (exit 1) on failure."""
    candidate = os.path.expanduser(raw_path)
    if not os.path.exists(candidate):
        raise CliError(_WORK_ATTACH_NOT_FOUND.format(path=raw_path))
    if not os.path.isdir(candidate):
        raise CliError(_WORK_ATTACH_NOT_A_DIR.format(path=raw_path))
    return raw_path


_WORK_ATTACH_PATH_UNAVAILABLE_SIGNATURE = "workspace path is unavailable"
_WORK_ATTACH_NOT_DIRECTORY_SIGNATURE = "workspace path is not a directory"


def _humanize_work_attach_error(
    exc: CliError, args: argparse.Namespace
) -> CliError:
    """Turn ``work_attach_workspace`` server rejections into human copy (T2-5).

    The client pre-check makes these rare (a race between the local check
    and the RPC), but they stay humanized: a path the resident cannot reach,
    or one that is not a directory. Anything else travels the generic path.
    """
    text = str(exc)
    path = str(args.path)
    if _WORK_ATTACH_PATH_UNAVAILABLE_SIGNATURE in text:
        return CliError(
            "这个目录常驻服务够不着"
            f"（{_WORK_ATTACH_PATH_UNAVAILABLE_SIGNATURE}）：'{path}'。"
            "请确认目录存在且常驻服务有权限访问。"
        )
    if _WORK_ATTACH_NOT_DIRECTORY_SIGNATURE in text:
        return CliError(
            "这不是一个目录"
            f"（{_WORK_ATTACH_NOT_DIRECTORY_SIGNATURE}）：'{path}'。"
            "zn work attach 需要绑定一个目录。"
        )
    return exc


def _cmd_work_attach(args: argparse.Namespace) -> int:
    # T16 spec: client-side path validation, before any network traffic.
    checked_path = _work_attach_checked_path(args.path)
    try:
        ok, payload = _work_drive_rpc(
            args,
            "work_attach_workspace",
            {"thread_id": args.thread_id, "workspace_path": checked_path},
        )
    except CliError as exc:
        raise _humanize_work_attach_error(exc, args)
    if not ok:
        # T2-6: unreachable resident -- exit 0, honestly saying nothing was
        # attached; never claim the workspace association happened.
        return _work_drive_offline(
            args,
            payload,
            unavailable="没有给线程绑定工作区（这次绑定未生效）",
            json_payload={
                "attached": False,
                "thread_id": args.thread_id,
                "workspace_path": checked_path,
            },
        )
    metadata = payload.get("metadata") if isinstance(payload, dict) else None
    workspace = metadata.get("workspace") if isinstance(metadata, dict) else None
    if not isinstance(workspace, dict) or not isinstance(workspace.get("path"), str):
        raise _unexpected_result("work_attach_workspace", payload)
    if args.json:
        # --json passes the RPC result through byte-for-byte (same
        # serialization convention as every other command).
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"attached workspace to thread={args.thread_id}")
    print(f"  目录：{workspace['path']}")
    name = workspace.get("name")
    if name:
        print(f"  名称：{name}")
    if use_color():
        print(
            colorize(
                f"  用 `zn work get --thread-id {args.thread_id}` 查看绑定的工作区",
                "dim",
            )
        )
    return 0


# --- T20: `zn work detach` ---------------------------------------------------
# Terminal entry for the daemon's ``work_detach_workspace`` (daemon.py:504)
# RPC -- the inverse of T16's ``zn work attach``. daemon.py is untouched.
#
# Contracts, inherited from the T12/T13/T14/D4 lineage (same as T16):
# - T2-1: presentation uses only the cli_format contract (plain human copy
#   always; TTY niceties behind ``use_color()``).
# - T2-5: server rejections humanized (Chinese body + English technical
#   snippet in parentheses). ``work_detach_workspace`` rejects unknown
#   thread ids with ``ValueError("unknown work thread: <id>")``.
# - T2-6: unreachable resident -> exit 0 + an honest note naming what was
#   NOT done, never claiming the workspace was detached.
# - T2-7: TTY-only hints stay behind ``use_color()``; pipes, NO_COLOR and
#   ``--json`` keep historic bytes.
# - T2-4: ``--json`` prints the RPC result byte-for-byte; exit codes for
#   missing/illegal CLI args come from argparse (exit 2).
# Unlike ``zn work attach``, there is no path argument to validate
# client-side: the RPC schema is exactly {"thread_id"} and the client sends
# exactly that one key -- asserted in the tests.
_WORK_DETACH_UNKNOWN_THREAD_SIGNATURE = "unknown work thread"


def _humanize_work_detach_error(
    exc: CliError, args: argparse.Namespace
) -> CliError:
    """Turn ``work_detach_workspace`` server rejections into human copy (T2-5).

    Unknown thread ids surface as the daemon's
    ``ValueError("unknown work thread: <id>")``; anything else travels the
    untouched generic path.
    """
    thread_id = str(args.thread_id)
    if _WORK_DETACH_UNKNOWN_THREAD_SIGNATURE in str(exc):
        return CliError(
            "找不到这个工作线程（unknown work thread）："
            f"线程 '{thread_id}' 不存在。"
            "用 `zn work list` 看看。"
        )
    return exc


def _cmd_work_detach(args: argparse.Namespace) -> int:
    # T20 spec: no client-side validation needed -- the inverse of attach
    # carries no path; the RPC just takes the thread id.
    try:
        ok, payload = _work_drive_rpc(
            args,
            "work_detach_workspace",
            {"thread_id": args.thread_id},
        )
    except CliError as exc:
        raise _humanize_work_detach_error(exc, args)
    if not ok:
        # T2-6: unreachable resident -- exit 0, honestly saying nothing was
        # detached; never claim the workspace association was removed.
        return _work_drive_offline(
            args,
            payload,
            unavailable="没有给线程解绑工作区（这次解绑未生效）",
            json_payload={
                "detached": False,
                "thread_id": args.thread_id,
            },
        )
    if not isinstance(payload, dict) or not isinstance(payload.get("id"), str):
        raise _unexpected_result("work_detach_workspace", payload)
    if args.json:
        # --json passes the RPC result through byte-for-byte (same
        # serialization convention as every other command).
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"detached workspace from thread={args.thread_id}")
    print("  该线程已不再关联工作区目录")
    if use_color():
        print(
            colorize(
                f"  用 `zn work get --thread-id {args.thread_id}` 查看线程状态",
                "dim",
            )
        )
    return 0


# --- T21: `zn work restore-prepare` / `restore-approve` / `restore-application` ---
# Terminal entries for the daemon's ``work_restore_prepare`` (daemon.py:672),
# ``work_restore_approve`` (daemon.py:682) and ``work_restore_application``
# (daemon.py:692) RPCs -- the three-step missing-file restore flow. When a
# work thread's target file went missing (typically after a crash), the
# resident can rebuild it from the exact bytes it retained, but only with
# an explicit human approval in the middle. daemon.py is untouched.
#
# Contracts, inherited from the T12/T13/T14/D4 lineage (same as T16/T20):
# - T2-1: presentation uses only the cli_format contract (plain human copy
#   always; TTY niceties behind ``use_color()``).
# - T2-5: server rejections humanized (Chinese body + English technical
#   snippet in parentheses). The known dead end on non-Windows hosts is the
#   engine's ``RuntimeError("missing-file Work restore application currently
#   requires Windows")`` -- reported honestly as "this machine can't take
#   this path", exit 1, no traceback, no false success claim. Unknown
#   restore point / application ids get their own human copy.
# - T2-6: unreachable resident -> exit 0 + an honest note naming what was
#   NOT done, never claiming the restore was prepared/approved/inspected.
# - T2-7: TTY-only hints stay behind ``use_color()``; pipes, NO_COLOR and
#   ``--json`` keep historic bytes.
# - T2-4: ``--json`` prints the RPC result byte-for-byte; exit codes for
#   missing/illegal CLI args come from argparse (exit 2).
# The RPC schemas are exactly {"thread_id", "restore_point_id"} /
# {"thread_id", "application_id"} / {"application_id"} -- the client sends
# exactly those keys, asserted in the tests.
_WORK_RESTORE_UNKNOWN_THREAD_SIGNATURE = "unknown work thread"
_WORK_RESTORE_UNKNOWN_APPLICATION_SIGNATURE = "unknown Work restore application"
_WORK_RESTORE_UNKNOWN_POINT_SIGNATURE = "unknown Work restore point"
_WORK_RESTORE_WINDOWS_ONLY_SIGNATURE = "currently requires Windows"


def _humanize_work_restore_error(
    exc: CliError, args: argparse.Namespace
) -> CliError:
    """Turn missing-file restore server rejections into human copy (T2-5).

    Unknown thread ids surface as the daemon's
    ``ValueError("unknown work thread: <id>")``; unknown restore points /
    applications as the resident's ``ValueError("unknown Work restore ...")``;
    non-Windows hosts get the engine's ``RuntimeError("... currently requires
    Windows")``. Anything else travels the untouched generic path.
    """
    text = str(exc)
    if _WORK_RESTORE_UNKNOWN_THREAD_SIGNATURE in text:
        thread_id = getattr(args, "thread_id", "") or ""
        return CliError(
            "找不到这个工作线程（unknown work thread）："
            f"线程 '{thread_id}' 不存在。"
            "用 `zn work list` 看看。"
        )
    if _WORK_RESTORE_UNKNOWN_APPLICATION_SIGNATURE in text:
        application_id = getattr(args, "application_id", "") or ""
        return CliError(
            "找不到这个恢复申请（unknown Work restore application）："
            f"申请 '{application_id}' 不存在。"
            "用创建申请时返回的 application_id 再试一次。"
        )
    if _WORK_RESTORE_UNKNOWN_POINT_SIGNATURE in text:
        thread_id = getattr(args, "thread_id", "") or ""
        restore_point_id = getattr(args, "restore_point_id", "") or ""
        return CliError(
            "找不到这个恢复点（unknown Work restore point）："
            f"线程 '{thread_id}' 下没有 id 为 '{restore_point_id}' 的恢复点。"
            "恢复点 id 在守护进程端工作快照的 metadata.restore_points 里，"
            "用 `zn work get --thread-id <id> --json` 查看；"
            "终端目前没有 restore-point 列表子命令。"
        )
    if _WORK_RESTORE_WINDOWS_ONLY_SIGNATURE in text:
        return CliError(
            "缺文件恢复目前只支持 Windows"
            "（missing-file Work restore application currently requires Windows），"
            "这台机器用不了这条路。"
        )
    return exc


def _work_restore_checked_application(method: str, payload: Any) -> dict[str, Any]:
    """Validate the application public-dict shape; humanized on skew."""
    if not isinstance(payload, dict) or not isinstance(payload.get("application_id"), str):
        raise _unexpected_result(method, payload)
    return payload


def _cmd_work_restore_prepare(args: argparse.Namespace) -> int:
    # T21 spec: the RPC schema is exactly {"thread_id", "restore_point_id"}
    # and the client sends exactly those two keys -- asserted in the tests.
    try:
        ok, payload = _work_drive_rpc(
            args,
            "work_restore_prepare",
            {"thread_id": args.thread_id, "restore_point_id": args.restore_point_id},
        )
    except CliError as exc:
        raise _humanize_work_restore_error(exc, args)
    if not ok:
        # T2-6: unreachable resident -- exit 0, honestly saying no restore
        # application was created; never claim the request went out.
        return _work_drive_offline(
            args,
            payload,
            unavailable="没有创建缺文件恢复申请（这次申请未发出）",
            json_payload={
                "prepared": False,
                "thread_id": args.thread_id,
                "restore_point_id": args.restore_point_id,
            },
        )
    app = _work_restore_checked_application("work_restore_prepare", payload)
    if args.json:
        # --json passes the RPC result through byte-for-byte (same
        # serialization convention as every other command).
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    application_id = app["application_id"]
    print(f"restore prepare: 缺文件恢复申请已创建 application={application_id}")
    print(f"  目标文件：{app.get('target_path') or '?'}")
    status = app.get("status") or "?"
    if app.get("requires_user_approval"):
        print(f"  状态：等待审批（{status}）")
    else:
        print(f"  状态：{status}")
    if use_color():
        print(
            colorize(
                f"  用 `zn work restore-approve --thread-id {args.thread_id} "
                f"--application-id {application_id}` 审批",
                "dim",
            )
        )
    return 0


def _cmd_work_restore_approve(args: argparse.Namespace) -> int:
    # T21 spec: the RPC schema is exactly {"thread_id", "application_id"}.
    try:
        ok, payload = _work_drive_rpc(
            args,
            "work_restore_approve",
            {"thread_id": args.thread_id, "application_id": args.application_id},
        )
    except CliError as exc:
        raise _humanize_work_restore_error(exc, args)
    if not ok:
        # T2-6: unreachable resident -- exit 0, honestly saying nothing was
        # approved; never claim the approval happened.
        return _work_drive_offline(
            args,
            payload,
            unavailable="没有审批这个恢复申请（审批未生效）",
            json_payload={
                "approved": False,
                "thread_id": args.thread_id,
                "application_id": args.application_id,
            },
        )
    app = _work_restore_checked_application("work_restore_approve", payload)
    if args.json:
        # --json passes the RPC result through byte-for-byte (same
        # serialization convention as every other command).
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    application_id = app["application_id"]
    print(f"restore approve: 恢复申请已审批 application={application_id}")
    print(f"  状态：{app.get('status') or '?'}")
    error = app.get("error")
    if error:
        print(f"  说明：{_one_line(error, limit=200)}")
    if use_color():
        print(
            colorize(
                f"  用 `zn work restore-application --application-id {application_id}` 查看恢复结果",
                "dim",
            )
        )
    return 0


def _cmd_work_restore_application(args: argparse.Namespace) -> int:
    # T21 spec: the RPC schema is exactly {"application_id"}.
    try:
        ok, payload = _work_drive_rpc(
            args,
            "work_restore_application",
            {"application_id": args.application_id},
        )
    except CliError as exc:
        raise _humanize_work_restore_error(exc, args)
    if not ok:
        # T2-6: unreachable resident -- exit 0, honestly saying the
        # application state was not inspected; never invent a status.
        return _work_drive_offline(
            args,
            payload,
            unavailable="没有查到恢复申请的状态（这次查询未完成）",
            json_payload={"application_id": args.application_id},
        )
    app = _work_restore_checked_application("work_restore_application", payload)
    if args.json:
        # --json passes the RPC result through byte-for-byte (same
        # serialization convention as every other command).
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    application_id = app["application_id"]
    status = str(app.get("status") or "?")
    print(f"restore application: application={application_id}")
    target_path = app.get("target_path")
    if target_path:
        print(f"  目标文件：{target_path}")
    error = app.get("error")
    if status == "completed":
        print("  状态：已完成（completed）——目标文件已恢复")
    elif error:
        print(f"  状态：{status}")
        print(f"  失败原因：{_one_line(error, limit=200)}")
    elif app.get("requires_user_approval"):
        print(f"  状态：等待审批（{status}）")
        if use_color():
            thread_id = app.get("thread_id") or ""
            print(
                colorize(
                    f"  用 `zn work restore-approve --thread-id {thread_id} "
                    f"--application-id {application_id}` 审批",
                    "dim",
                )
            )
    else:
        print(f"  状态：{status}")
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
    else:
        for item in result:
            if not isinstance(item, dict):
                continue
            print(
                f"{_one_line(item.get('key'), limit=64):64} "
                f"[{_one_line(item.get('kind'), limit=20)}] "
                f"{_one_line(item.get('title'), limit=80)}"
            )
    # PC-1: 建议栏尾部顺带呈现最近的主动联系（N-6：不单独立项）。
    # 有记录才显示；无记录时上面输出与原来逐字节一致。
    _print_proactive_contact_recent(args)
    return 0


# --- PC-1: 最近主动联系（建议栏尾部顺带呈现） -------------------------------
# T2-1: 纯数据行，无 TTY-only 修饰——管道与 TTY 看到相同的行；
# T2-7: 不引入任何符号字形，逐行可逐字节断言。
_PROACTIVE_CONTACT_RECENT_LIMIT = 5


def _print_proactive_contact_recent(args: argparse.Namespace) -> None:
    """Append the recent proactive-contact history to the suggestions view.

    The section prints only when records exist; an empty history (or a
    resident that does not know the RPC) leaves the caller output
    byte-identical to before PC-1. The RPC is read-only and never goes
    through maybe_contact, so reading the history consumes no greeting
    opportunity. Failures are skipped deliberately: this is a piggyback
    nicety and must never break the primary suggestions listing
    (e.g. against an older resident).
    """
    try:
        result = _client(args).call(
            "proactive_contact_recent",
            {"limit": _PROACTIVE_CONTACT_RECENT_LIMIT},
        )
    except Exception:
        return
    if not isinstance(result, list) or not result:
        return
    print("最近主动联系：")
    for row in result:
        if not isinstance(row, dict):
            continue
        print(
            f"  {_one_line(row.get('day') or row.get('sent_at'), limit=32)} "
            f"[{_one_line(row.get('kind'), limit=20)}] "
            f"{_one_line(row.get('suggestion_key'), limit=64)}"
        )


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
        _print_empty_hint("goal_list")
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
# pause / resume are the mutations from the T9 slice. T17 adds the
# creation slice: propose (one sentence -> confirmation draft) and
# confirm (validate a possibly user-edited draft, then create).
# edit / delete / test_run stay on the chat path and are NOT exposed
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


# --- T17: `zn routine propose` / `zn routine confirm` -----------------------
# Terminal face for the creation slice of the daemon's routine_* RPCs
# (already dispatched in daemon.py ``_routine_result``): ``propose`` turns
# one sentence into a draft carrying the six confirmations (task, owner,
# input_source, expected_result, approval_boundary, missing_data_policy)
# plus a ``missing`` list naming anything the parser could not figure out;
# ``confirm`` validates a (possibly user-edited) draft and creates the
# routine. No new daemon RPC, no daemon.py changes.
#
# Offline contract (T2-6 style, same as the other routine commands):
# resident unreachable -> exit 0 + an honest note naming what was not done.
# ``confirm`` never claims a routine was created when it was not. A
# server-side rejection (``ok: false``, e.g. an invalid draft) is NOT
# swallowed: it surfaces as a humanized error on stderr, exit 1.

_MISSING_DRAFT_ITEM_HINTS = {
    "schedule": (
        "时间计划还没解析出来：在描述里写清楚什么时候运行，"
        "比如「每天早上8点」「每30分钟」「每周五下午5点」。"
    ),
    "task": (
        "任务内容还没解析出来：说清楚要做什么，比如「提醒我看今天的日程」。"
    ),
}


def _format_routine_draft(draft: dict[str, Any]) -> str:
    """Human card for a ``routine_propose`` draft: the six confirmations."""
    kind = draft.get("schedule_kind") or ""
    cron = _one_line(draft.get("cron_expression"), limit=40)
    interval = draft.get("interval_seconds")
    timezone = _one_line(draft.get("timezone"), limit=40)
    zone = f"（时区 {timezone}）" if timezone else ""
    if kind == "cron" and cron:
        schedule = f"cron {cron}{zone}"
    elif kind == "interval" and isinstance(interval, (int, float)) and interval > 0:
        schedule = f"每 {int(interval)} 秒{zone}"
    else:
        schedule = "（未解析出时间计划）"
    rows = [
        ("任务", _one_line(draft.get("task"), limit=200)),
        ("负责人", _one_line(draft.get("owner"), limit=40)),
        ("计划", schedule),
        ("输入来源", _one_line(draft.get("input_source"), limit=120)),
        ("期望结果", _one_line(draft.get("expected_result"), limit=200)),
        ("审批边界", _one_line(draft.get("approval_boundary"), limit=200)),
        ("缺失数据策略", _one_line(draft.get("missing_data_policy"), limit=40)),
    ]
    lines = ["草稿已生成，请逐项确认："]
    for label, value in rows:
        lines.append(f"  {label}：{value or '（空）'}")
    return "\n".join(lines)


def _format_missing_draft_items(draft: dict[str, Any]) -> list[str]:
    """Human guidance for each name in the draft's ``missing`` list."""
    missing = draft.get("missing")
    if not isinstance(missing, list):
        return []
    hints = []
    for item in missing:
        name = str(item).strip()
        if not name:
            continue
        hints.append(
            _MISSING_DRAFT_ITEM_HINTS.get(
                name, f"「{name}」还没确认：请在草稿 JSON 里补上再确认。"
            )
        )
    return hints


# T2-5: human lead + English technical fragment in parentheses for the
# common propose/confirm server rejections. Anything not listed falls
# through to the generic ``rpc_rejected`` copy (still humanized, exit 1).
_ROUTINE_CREATION_ERROR_COPY: tuple[tuple[str, str], ...] = (
    (
        "routine_propose requires text",
        "请用一句话描述这个例行任务（routine_propose requires text）\n"
        "示例：zn routine propose \"每天早上8点提醒我看日程\"",
    ),
    (
        "routine request must not be empty",
        "请用一句话描述这个例行任务（routine request must not be empty）\n"
        "示例：zn routine propose \"每天早上8点提醒我看日程\"",
    ),
    (
        "routine draft must be an object",
        "草稿必须是 JSON 对象（{...}），现在给的不是对象"
        "（routine draft must be an object）",
    ),
    (
        "routine_confirm requires a draft object",
        "确认需要一段草稿（routine_confirm requires a draft object）："
        "用 --draft-json '<json>' 或 --draft-file <path> 传入",
    ),
    (
        "routine task must not be empty",
        "草稿里没有任务内容（task 为空）（routine task must not be empty）："
        "请补上要做什么，再重新确认",
    ),
    (
        "routine task must be at most 200 characters",
        "草稿里的任务描述太长了，最多 200 字"
        "（routine task must be at most 200 characters）：请精简一下再确认",
    ),
    (
        "routine owner must not be empty",
        "草稿里没有负责人（owner 为空）（routine owner must not be empty）："
        "请填上谁负责这条例行任务",
    ),
    (
        "routine input source must not be empty",
        "草稿里没有输入来源（input_source 为空）"
        "（routine input source must not be empty）：请写清楚数据从哪儿来",
    ),
    (
        "routine expected result must not be empty",
        "草稿里没有期望结果（expected_result 为空）"
        "（routine expected result must not be empty）：请写清楚做完算什么样",
    ),
    (
        "missing-data policy must be one of",
        "缺失数据策略（missing_data_policy）只能是这几个之一"
        "（missing-data policy must be one of: skip / notify / use_last_known）",
    ),
    (
        "routine draft has no parsed schedule",
        "草稿里没有可用的时间计划（routine draft has no parsed schedule）："
        "在描述里写清楚什么时候运行，比如「每天早上8点」，"
        "重新生成草稿后再确认",
    ),
)


def _routine_creation_error(exc: CliError) -> CliError:
    """Swap a common propose/confirm server rejection for human copy.

    The daemon answers ``ok: false`` with a ``ValueError: ...`` whose text
    is matched below; anything else is returned unchanged so the generic
    humanized ``rpc_rejected`` copy stays the fallback.
    """
    text = str(exc)
    for fragment, human in _ROUTINE_CREATION_ERROR_COPY:
        if fragment in text:
            return CliError(human)
    return exc


def _load_routine_draft(args: argparse.Namespace) -> dict[str, Any]:
    """Read the draft for ``zn routine confirm`` from --draft-json/file.

    Raises :class:`CliError` (exit 1) for unreadable files, non-UTF-8
    bytes, bad JSON, or a non-object payload -- all before any RPC leaves
    the terminal.
    """
    if args.draft_file is not None:
        path = args.draft_file
        source = f"草稿文件 '{path}'"
        try:
            raw = Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            raise CliError(
                f"找不到{source}（file not found）：检查路径是否写对；"
                "或先用 `zn routine propose \"…\" --json > draft.json` 生成一份"
            ) from None
        except UnicodeDecodeError:
            raise CliError(
                f"{source}不是 UTF-8 文本（not utf-8）：请用 UTF-8 重新保存"
            ) from None
        except OSError as exc:
            detail = exc.strerror or "read error"
            raise CliError(
                f"读不懂{source}（{detail}）：检查文件权限"
            ) from None
    else:
        raw = args.draft_json
        source = "--draft-json"
    try:
        draft = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CliError(
            f"{source}里的内容不是合法 JSON"
            f"（{exc.msg}，第 {exc.lineno} 行第 {exc.colno} 列）："
            "检查引号和括号是否配对"
        ) from None
    if not isinstance(draft, dict):
        raise CliError(
            f"{source}里的草稿必须是 JSON 对象（{{...}}），"
            f"现在是 {type(draft).__name__}（draft must be an object）"
        )
    return draft


def _cmd_routine_propose(args: argparse.Namespace) -> int:
    text = (args.text or "").strip()
    if not text:
        raise CliError(
            "请用一句话描述这个例行任务。\n"
            "示例：zn routine propose \"每天早上8点提醒我看日程\""
        )
    try:
        ok, payload = _routine_rpc(args, "routine_propose", {"text": text})
    except CliError as exc:
        raise _routine_creation_error(exc) from None
    if not ok:
        return _routine_offline(
            args,
            payload,
            unavailable="没能生成例行任务草稿",
            json_payload={"draft": None},
        )
    draft = payload
    if not isinstance(draft, dict) or not draft:
        raise _unexpected_result("routine_propose", draft)
    if args.json:
        print(json.dumps(draft, ensure_ascii=False, indent=2, default=str))
        return 0
    print(_format_routine_draft(draft))
    for hint in _format_missing_draft_items(draft):
        print(f"  缺项：{hint}")
    if use_color():
        print(
            colorize(
                "  下一步：先用 `zn routine propose \"…\" --json > draft.json` "
                "把草稿存成文件，改好后用 `zn routine confirm --draft-file draft.json` 创建",
                "dim",
            )
        )
    return 0


def _cmd_routine_confirm(args: argparse.Namespace) -> int:
    draft = _load_routine_draft(args)
    try:
        ok, payload = _routine_rpc(args, "routine_confirm", {"draft": draft})
    except CliError as exc:
        raise _routine_creation_error(exc) from None
    if not ok:
        return _routine_offline(
            args,
            payload,
            unavailable="没有创建任何例行任务",
            json_payload={"changed": False, "routine": None},
        )
    result = payload
    if not isinstance(result, dict) or not result.get("routine_id"):
        raise _unexpected_result("routine_confirm", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    routine_id = _one_line(result.get("routine_id"), limit=24)
    status = result.get("status") or "active"
    mark = status_symbol(status)
    print(
        f"{mark + ' ' if mark else ''}例行任务 {routine_id} 已创建 "
        f"[{status_word(status)}]"
    )
    schedule = _one_line(result.get("schedule_description"), limit=80)
    if schedule:
        print(f"  计划：{schedule}")
    task = _one_line(result.get("task"), limit=120)
    if task:
        print(f"  任务：{task}")
    if use_color():
        print(colorize("  下一步：用 `zn routine list` 查看已创建的例行任务", "dim"))
    return 0


# --- T18: `zn routine edit` / `zn routine delete` ---------------------------
# Terminal face for the mutation slice of the daemon's routine_* RPCs
# (already dispatched in daemon.py ``_routine_result``): ``edit`` changes a
# routine's time/content via ``routine_edit`` (params: routine_id + fields),
# ``delete`` removes it via ``routine_delete`` (params: routine_id only).
# No new daemon RPC, no daemon.py changes.
#
# Engaged guard (client-side): a routine with a run in flight -- the
# read-only ``routine_get`` pre-flight shows a "running" entry in
# recent_runs -- refuses edit/delete here with exit 1 and human guidance;
# the mutation RPC is never sent. The daemon enforces the same rule
# server-side (``_reject_if_engaged``), so a missed edge still fails closed;
# the client check exists to fail fast with a better message. Note the
# guidance deliberately says "wait for the run to finish": ``routine_pause``
# is rejected while engaged too, so "pause first" would be wrong advice.
#
# Offline contract (T2-6 style, same as the other routine commands):
# resident unreachable -> exit 0 + an honest note naming what was not done.
# ``delete`` never claims a routine was deleted when it was not. A
# server-side rejection (``ok: false``, e.g. an invalid schedule) is NOT
# swallowed: it surfaces as a humanized error on stderr, exit 1.

# recent_runs statuses that mean "a run is currently executing".
_ROUTINE_ENGAGED_STATUSES = frozenset({"running"})


def _routine_engaged(snapshot: dict[str, Any]) -> bool:
    """True when the snapshot shows a run in flight (the routine is engaged)."""
    runs = snapshot.get("recent_runs") or []
    return any(
        isinstance(run, dict)
        and str(run.get("status")) in _ROUTINE_ENGAGED_STATUSES
        for run in runs
    )


def _reject_routine_engaged(
    action: str, routine_id: str, snapshot: dict[str, Any]
) -> None:
    """Refuse edit/delete while the routine is engaged (T18 guard).

    Raises :class:`CliError` (exit 1) with human guidance; the caller must
    not send any mutation RPC after this raises.
    """
    if not _routine_engaged(snapshot):
        return
    verb = {"edit": "修改", "delete": "删除", "test-run": "试运行"}.get(action, "操作")
    raise CliError(
        f"例行任务 {routine_id} 正在执行中（run in flight），现在不能{verb}。\n"
        f"等这次运行结束后再试：`zn routine runs {routine_id}` 可以看进度。"
    )


def _parse_routine_edit_time(value: str) -> dict[str, Any]:
    """Turn ``--time`` natural language into ``routine_edit`` schedule fields.

    Reuses the same schedule-clause parser the daemon's propose path uses
    (``routine_request._parse_schedule_clause``, same package), so
    ``每天早上8点`` / ``每30分钟`` / ``每周五下午5点`` mean the same thing
    here as they do in ``zn routine propose``. Only schema keys the daemon
    accepts (schedule_kind / interval_seconds / cron_expression / timezone)
    are returned.
    """
    parsed = _parse_schedule_clause(value)
    if parsed is None:
        raise CliError(
            f"没听懂这个时间（could not parse schedule from --time {value!r}）："
            "试试「每天早上8点」「每30分钟」「每周五下午5点」这样的说法。"
        )
    fields, _rest = parsed
    return dict(fields)


def _routine_preflight(args: argparse.Namespace, *, unavailable: str) -> Any:
    """Read-only ``routine_get`` pre-flight shared by edit/delete.

    Returns the routine snapshot dict. An unknown id raises the human
    "not found" error (exit 1); an unreachable resident prints the offline
    note and returns None (the caller must ``return 0`` without claiming
    any mutation happened).
    """
    try:
        ok, payload = _routine_rpc(
            args, "routine_get", {"routine_id": args.routine_id}
        )
    except CliError as exc:
        raise _unknown_routine_error(exc, args.routine_id) from None
    if not ok:
        _routine_offline(
            args,
            payload,
            unavailable=unavailable,
            json_payload={"changed": False, "routine": None},
        )
        return None
    if not isinstance(payload, dict) or not payload:
        raise _unexpected_result("routine_get", payload)
    return payload


def _cmd_routine_edit(args: argparse.Namespace) -> int:
    fields: dict[str, Any] = {}
    if args.time is not None:
        fields.update(_parse_routine_edit_time(args.time))
    if args.content is not None:
        fields["task"] = args.content
    if not fields:
        raise CliError(
            "edit 需要至少改一项（nothing to change）："
            "用 --time 改时间（比如 --time \"每天早上9点\"），"
            "用 --content 改内容（比如 --content \"提醒我看今天的日程\"）。"
        )
    snapshot = _routine_preflight(args, unavailable="没有修改任何例行任务")
    if snapshot is None:
        return 0
    _reject_routine_engaged("edit", args.routine_id, snapshot)
    try:
        ok, payload = _routine_rpc(
            args,
            "routine_edit",
            {"routine_id": args.routine_id, "fields": fields},
        )
    except CliError as exc:
        raise _unknown_routine_error(exc, args.routine_id) from None
    if not ok:
        return _routine_offline(
            args,
            payload,
            unavailable="没有修改任何例行任务",
            json_payload={"changed": False, "routine": None},
        )
    result = payload
    if not isinstance(result, dict) or not result.get("routine_id"):
        raise _unexpected_result("routine_edit", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    routine_id = _one_line(result.get("routine_id"), limit=24)
    status = result.get("status") or "active"
    mark = status_symbol(status)
    print(
        f"{mark + ' ' if mark else ''}例行任务 {routine_id} 已更新 "
        f"[{status_word(status)}]"
    )
    if args.time is not None:
        schedule = _one_line(result.get("schedule_description"), limit=80)
        print(f"  时间：{schedule or args.time}")
    if args.content is not None:
        task = _one_line(result.get("task"), limit=120)
        if task:
            print(f"  内容：{task}")
    return 0


def _cmd_routine_delete(args: argparse.Namespace) -> int:
    snapshot = _routine_preflight(args, unavailable="没有删除任何例行任务")
    if snapshot is None:
        return 0
    _reject_routine_engaged("delete", args.routine_id, snapshot)
    try:
        ok, payload = _routine_rpc(
            args, "routine_delete", {"routine_id": args.routine_id}
        )
    except CliError as exc:
        raise _unknown_routine_error(exc, args.routine_id) from None
    if not ok:
        return _routine_offline(
            args,
            payload,
            unavailable="没有删除任何例行任务",
            json_payload={"changed": False, "routine": None},
        )
    result = payload
    if not isinstance(result, dict) or not result.get("deleted"):
        raise _unexpected_result("routine_delete", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    routine_id = _one_line(result.get("routine_id") or args.routine_id, limit=24)
    print(f"例行任务 {routine_id} 已删除")
    return 0


# --- T19: `zn routine test-run` + `zn routine acknowledge` ------------------
# Terminal face for the daemon's already-wired ``routine_test_run`` /
# ``routine_acknowledge`` RPCs (daemon.py ``_routine_result``; RoutineManager
# test_run / acknowledge). No new daemon RPC, no daemon.py changes.
#
# test-run is REAL execution, not a dry run: the task is handed to Will
# exactly like a scheduled occurrence. The TTY copy says so explicitly;
# the approval boundary is enforced before any execution (awaiting_approval
# returns a held run without executing; denied/expired raises and is
# humanized here). Offline contract (T2-6 style): exit 0 with an honest
# note, never claiming a mutation happened. engaged (a run in flight)
# refuses with the T18 "wait for the run to finish" wording -- a pre-flight
# ``routine_get`` guard, zero mutation RPCs on refusal.

_TEST_RUN_BOUNDARY_MARKER = "blocked by its approval boundary"


def _humanize_test_run_boundary(exc: CliError) -> CliError:
    """Turn a boundary-blocked test-run rejection into human copy (T2-5).

    The daemon raises ``ValueError("routine test run blocked by its approval
    boundary: <reason>")`` when the boundary is denied or expired; this
    becomes a Chinese lead keeping the English technical fragment in
    parentheses. Anything else passes through unchanged.
    """
    text = str(exc)
    if _TEST_RUN_BOUNDARY_MARKER not in text:
        return exc
    reason = text.split(_TEST_RUN_BOUNDARY_MARKER + ":", 1)[1].strip()
    lead = (
        "这次试运行被审批边界拦下了"
        "（routine test run blocked by its approval boundary）"
    )
    return CliError(f"{lead}：{reason}" if reason else lead)


def _cmd_routine_test_run(args: argparse.Namespace) -> int:
    snapshot = _routine_preflight(args, unavailable="没有试运行任何例行任务")
    if snapshot is None:
        return 0
    _reject_routine_engaged("test-run", args.routine_id, snapshot)
    try:
        ok, payload = _routine_rpc(
            args, "routine_test_run", {"routine_id": args.routine_id}
        )
    except CliError as exc:
        raise _humanize_test_run_boundary(
            _unknown_routine_error(exc, args.routine_id)
        ) from None
    if not ok:
        return _routine_offline(
            args,
            payload,
            unavailable="没有试运行任何例行任务",
            json_payload={"changed": False, "run": None},
        )
    result = payload
    if not isinstance(result, dict) or not result.get("run_id"):
        raise _unexpected_result("routine_test_run", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    routine_id = _one_line(result.get("routine_id") or args.routine_id, limit=24)
    run_id = _one_line(result.get("run_id"), limit=20)
    status = str(result.get("status") or "")
    if status == "awaiting_approval":
        print(
            f"例行任务 {routine_id} 的试运行已进入审批等待"
            "（awaiting_approval）：审批还没通过，任务暂不执行。\n"
            "审批通过后，下一个心跳会继续这次试运行。"
        )
        return 0
    mark = status_symbol(status)
    print(
        f"{mark + ' ' if mark else ''}例行任务 {routine_id} 的试运行已启动"
        f"（真执行，不是 dry-run），走和定时触发一样的执行路径；"
        f"运行 id：{run_id}"
    )
    return 0


def _cmd_routine_acknowledge(args: argparse.Namespace) -> int:
    snapshot = _routine_preflight(args, unavailable="没有确认任何例行任务")
    if snapshot is None:
        return 0
    try:
        ok, payload = _routine_rpc(
            args, "routine_acknowledge", {"routine_id": args.routine_id}
        )
    except CliError as exc:
        raise _unknown_routine_error(exc, args.routine_id) from None
    if not ok:
        return _routine_offline(
            args,
            payload,
            unavailable="没有确认任何例行任务",
            json_payload={"changed": False, "routine": None},
        )
    result = payload
    if not isinstance(result, dict) or not result.get("routine_id"):
        raise _unexpected_result("routine_acknowledge", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    routine_id = _one_line(result.get("routine_id") or args.routine_id, limit=24)
    print(f"已确认例行任务 {routine_id}（我看过了）：自动暂停计时器已重置")
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


def _format_diary_detail(
    item: dict[str, Any], *, defaulted_to_today: bool = False
) -> str:
    """Full detail view of one diary entry (``zn diary get``).

    Headline row (date), then indented label rows for the fields the
    ``diary_get`` RPC already returns, then the body rendered with
    :func:`_long_text` so line structure survives (T2-4 rule).
    When the caller omitted ``--date`` and today was defaulted in,
    the headline carries the "（默认今天）" hint so the TTY reader
    knows which date was resolved.
    """
    entry_date = _one_line(item.get("date"), limit=12) or "?"
    headline = f"日记 {entry_date}"
    if defaulted_to_today:
        headline += "（默认今天）"
    lines = [headline]
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
    # DIARY-TODAY: --date is optional; when omitted, resolve to today at
    # command time (not parser-build time) so a long-lived import still
    # gets the right date. daemon.py's diary_get takes only a date string
    # and has no default semantics -- this is purely the CLI-side default.
    defaulted_to_today = not args.date
    date_str = args.date or date.today().isoformat()
    ok, payload = _diary_rpc(args, "diary_get", {"date": date_str})
    if not ok:
        return _diary_offline(
            args,
            payload,
            unavailable=f"看不到 {date_str} 的日记",
            json_payload={"date": date_str, "entry": None},
        )
    if payload is None:
        # The daemon answers null (not a rejection) when the date has no
        # entry: humanized "not found", exit 1. The English fragment keeps
        # the server contract greppable; the next line points at the list.
        raise CliError(
            f"找不到 {date_str} 的日记（no diary entry for that date）。"
            "用 'zn diary list' 看看 ZN 写过哪些日记。"
        )
    result = payload
    if not isinstance(result, dict) or not result:
        raise _unexpected_result("diary_get", result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    print(
        _format_diary_detail(result, defaulted_to_today=defaulted_to_today)
    )
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
                "看今天的日记（默认今天）",
                "zn diary get",
            ),
            (
                "diary get",
                "看某天的日记",
                "zn diary get --date 2026-10-22",
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
        "  zn work get --thread-id <thread-id> --message-limit 20\n"
        "  zn work get --last",
    )
    # WK-LAST2: --last vs --thread-id are mutually exclusive (exit 2).
    get_thread_or_last = work_get.add_mutually_exclusive_group(required=True)
    get_thread_or_last.add_argument(
        "--thread-id",
        type=lambda v: _require_non_empty(v, name="--thread-id"),
        help="work thread id",
    )
    get_thread_or_last.add_argument(
        "--last",
        action="store_true",
        help="show the most recent work thread instead of naming one（看最近会话）",
    )
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
        "  zn work submit --thread-id <thread-id> --task \"继续，把明细也加上\"\n"
        "  zn work submit --last --task \"继续，把明细也加上\"",
    )
    thread_or_last = work_submit.add_mutually_exclusive_group()
    thread_or_last.add_argument("--thread-id", default=None,
                                help="existing thread id; omitted = create a new thread")
    thread_or_last.add_argument("--last", action="store_true",
                                help="submit to the most recent thread instead of a new one（续最近会话）")
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
        "  zn work cancel --thread-id <thread-id> --event-id <event-id>\n"
        "  zn work cancel --last --event-id <event-id>",
    )
    # WK-LAST2: --last vs --thread-id are mutually exclusive (exit 2).
    # --last only resolves the thread; --event-id stays required -- the
    # user still names which event to cancel.
    cancel_thread_or_last = work_cancel.add_mutually_exclusive_group(required=True)
    cancel_thread_or_last.add_argument(
        "--thread-id",
        type=lambda v: _require_non_empty(v, name="--thread-id"),
        help="work thread id",
    )
    cancel_thread_or_last.add_argument(
        "--last",
        action="store_true",
        help="cancel on the most recent work thread instead of naming one（取消最近会话上的事件）",
    )
    work_cancel.add_argument("--event-id", type=lambda v: _require_non_empty(v, name="--event-id"), required=True)
    work_cancel.add_argument("--json", action="store_true", help="print raw JSON")
    work_cancel.set_defaults(func=_cmd_work_cancel)

    work_resolve_uncertain = work_sub.add_parser(
        "resolve-uncertain",
        help="resolve an uncertain side effect of an active work event",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn work resolve-uncertain --thread-id <thread-id> --event-id <event-id> --attempt-id <attempt-id> --decision effect_happened",
    )
    work_resolve_uncertain.add_argument("--thread-id", type=lambda v: _require_non_empty(v, name="--thread-id"), required=True)
    work_resolve_uncertain.add_argument("--event-id", type=lambda v: _require_non_empty(v, name="--event-id"), required=True)
    work_resolve_uncertain.add_argument("--attempt-id", type=lambda v: _require_non_empty(v, name="--attempt-id"), required=True)
    work_resolve_uncertain.add_argument(
        "--decision",
        choices=list(_WORK_RESOLVE_DECISIONS),
        required=True,
        help="人工裁决：effect_happened = 副作用已发生；retry_authorized = 允许重试",
    )
    work_resolve_uncertain.add_argument("--json", action="store_true", help="print raw JSON")
    work_resolve_uncertain.set_defaults(func=_cmd_work_resolve_uncertain)

    work_rename = work_sub.add_parser(
        "rename",
        help="rename a work thread",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn work rename --thread-id <thread-id> --title \"新标题\"",
    )
    work_rename.add_argument("--thread-id", type=lambda v: _require_non_empty(v, name="--thread-id"), required=True)
    work_rename.add_argument("--title", type=lambda v: _require_non_empty(v, name="--title"), required=True)
    work_rename.add_argument("--json", action="store_true", help="print raw JSON")
    work_rename.set_defaults(func=_cmd_work_rename)

    work_attach = work_sub.add_parser(
        "attach",
        help="attach a workspace directory to a work thread",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn work attach --thread-id <thread-id> --path ~/projects/foo",
    )
    work_attach.add_argument("--thread-id", type=lambda v: _require_non_empty(v, name="--thread-id"), required=True)
    work_attach.add_argument(
        "--path",
        type=lambda v: _require_non_empty(v, name="--path"),
        required=True,
        help="workspace directory on this machine",
    )
    work_attach.add_argument("--json", action="store_true", help="print raw JSON")
    work_attach.set_defaults(func=_cmd_work_attach)

    work_detach = work_sub.add_parser(
        "detach",
        help="detach the workspace directory from a work thread",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn work detach --thread-id <thread-id>",
    )
    work_detach.add_argument("--thread-id", type=lambda v: _require_non_empty(v, name="--thread-id"), required=True)
    work_detach.add_argument("--json", action="store_true", help="print raw JSON")
    work_detach.set_defaults(func=_cmd_work_detach)

    work_restore_prepare = work_sub.add_parser(
        "restore-prepare",
        help="prepare a missing-file restore application for a work thread",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn work restore-prepare --thread-id <thread-id> --restore-point-id <restore-point-id>",
    )
    work_restore_prepare.add_argument("--thread-id", type=lambda v: _require_non_empty(v, name="--thread-id"), required=True)
    work_restore_prepare.add_argument(
        "--restore-point-id",
        type=lambda v: _require_non_empty(v, name="--restore-point-id"),
        required=True,
        help="恢复点 id：从 `zn work get --thread-id <id> --json` 输出的 metadata.restore_points 里取（终端目前没有 restore-point 列表子命令）",
    )
    work_restore_prepare.add_argument("--json", action="store_true", help="print raw JSON")
    work_restore_prepare.set_defaults(func=_cmd_work_restore_prepare)

    work_restore_approve = work_sub.add_parser(
        "restore-approve",
        help="approve a pending missing-file restore application",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn work restore-approve --thread-id <thread-id> --application-id <application-id>",
    )
    work_restore_approve.add_argument("--thread-id", type=lambda v: _require_non_empty(v, name="--thread-id"), required=True)
    work_restore_approve.add_argument(
        "--application-id",
        type=lambda v: _require_non_empty(v, name="--application-id"),
        required=True,
        help="restore-prepare 返回的 application_id",
    )
    work_restore_approve.add_argument("--json", action="store_true", help="print raw JSON")
    work_restore_approve.set_defaults(func=_cmd_work_restore_approve)

    work_restore_application = work_sub.add_parser(
        "restore-application",
        help="inspect a missing-file restore application",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn work restore-application --application-id <application-id>",
    )
    work_restore_application.add_argument(
        "--application-id",
        type=lambda v: _require_non_empty(v, name="--application-id"),
        required=True,
        help="restore-prepare 返回的 application_id",
    )
    work_restore_application.add_argument("--json", action="store_true", help="print raw JSON")
    work_restore_application.set_defaults(func=_cmd_work_restore_application)

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
        "  zn approval decide --request-id <request-id> --deny\n"
        '  zn approval decide --request-id <request-id> --deny --note "价格太贵，换方案"',
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
    # AP-1: feedback note, only meaningful with --deny (warned+ignored on
    # approvals).
    approval_decide.add_argument(
        "--note",
        default="",
        help="feedback note recorded with a denial (only meaningful with --deny)",
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

    # T12: reconsider a denied card -> fresh pending card + audited entry.
    approval_reconsider = approval_sub.add_parser(
        "reconsider",
        help="reconsider a denied approval: open a fresh pending card",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn approval reconsider <request-id>\n"
        '  zn approval reconsider <request-id> --note "请再看一次"',
    )
    approval_reconsider.add_argument(
        "request_id",
        type=lambda v: _require_non_empty(v, name="request_id"),
        help="the denied approval card id, as printed by 'zn approval list --status denied'",
    )
    approval_reconsider.add_argument(
        "--note",
        default="",
        help="note recorded in the audit entry (optional)",
    )
    approval_reconsider.add_argument(
        "--json", action="store_true", help="print raw JSON"
    )
    approval_reconsider.set_defaults(func=_cmd_approval_reconsider)

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

    # T13: steer a running team from the terminal. `team_assign` re-points
    # the next pending plan item at a specialist (the workbench "做完了"
    # button used to own the handover half; the workbench is gone since
    # #623). Both call existing daemon RPCs; daemon.py is untouched.
    team_assign = team_sub.add_parser(
        "assign",
        help="assign the team's next pending plan item to a specialist",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        '  zn team assign @设计 --thread-id <thread-id> "把首页排版重做一遍"\n'
        "  zn team assign @qa --thread-id <thread-id> 跑一遍回归测试",
    )
    team_assign.add_argument(
        "specialist",
        type=lambda v: _require_non_empty(v, name="specialist"),
        help="team specialist to assign to; a leading @ is optional (e.g. @设计)",
    )
    team_assign.add_argument(
        "instruction",
        type=lambda v: _require_non_empty(v, name="instruction"),
        help="what the specialist should do with the next pending plan item",
    )
    team_assign.add_argument(
        "--thread-id",
        type=lambda v: _require_non_empty(v, name="--thread-id"),
        required=True,
        help="work thread the team runs in (the team_assign RPC is thread-scoped)",
    )
    team_assign.add_argument("--json", action="store_true", help="print raw JSON")
    team_assign.set_defaults(func=_cmd_team_assign)

    team_handover_done = team_sub.add_parser(
        "handover-done",
        help="resolve the team's pending sensitive handover (owner did the step)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn team handover-done --thread-id <thread-id>",
    )
    team_handover_done.add_argument(
        "--thread-id",
        type=lambda v: _require_non_empty(v, name="--thread-id"),
        required=True,
        help="work thread the team runs in (the team_handover_done RPC is thread-scoped)",
    )
    team_handover_done.add_argument(
        "--json", action="store_true", help="print raw JSON"
    )
    team_handover_done.set_defaults(func=_cmd_team_handover_done)

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
    # T17: creation slice -- propose one sentence -> draft, confirm -> create.
    # T18: mutation slice -- edit time/content, delete.
    routine = sub.add_parser(
        "routine",
        help="draft, create, inspect, edit, delete or pause/resume the resident's routines",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn routine propose \"每天早上8点提醒我看日程\"\n"
        "  zn routine propose \"每30分钟看一次日历\" --json > draft.json\n"
        "  zn routine confirm --draft-file draft.json\n"
        "  zn routine list\n"
        "  zn routine edit --routine-id <id> --time \"每天早上9点\"\n"
        "  zn routine delete --routine-id <id>",
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

    # T17: routine creation slice -- propose / confirm against the already
    # wired routine_propose / routine_confirm RPCs. T3-2: epilog examples
    # live on each leaf parser like every other command.
    routine_propose = routine_sub.add_parser(
        "propose",
        help="draft a routine from one sentence (shows the six confirmations)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn routine propose \"每天早上8点提醒我看日程\"\n"
        "  zn routine propose \"每30分钟看一次日历\" --json",
    )
    routine_propose.add_argument(
        "text",
        help="one-sentence description, e.g. \"每天早上8点提醒我看日程\"",
    )
    routine_propose.add_argument(
        "--json", action="store_true", help="print raw JSON"
    )
    routine_propose.set_defaults(func=_cmd_routine_propose)

    routine_confirm = routine_sub.add_parser(
        "confirm",
        help="create a routine from a (possibly edited) draft",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn routine confirm --draft-file draft.json\n"
        "  zn routine confirm --draft-json '{\"task\": \"提醒我看日程\","
        " \"schedule_kind\": \"cron\", \"cron_expression\": \"0 8 * * *\"}'",
    )
    draft_source = routine_confirm.add_mutually_exclusive_group(required=True)
    draft_source.add_argument(
        "--draft-json",
        default=None,
        help="draft as a JSON object string",
    )
    draft_source.add_argument(
        "--draft-file",
        default=None,
        help="path to a file holding the draft JSON object",
    )
    routine_confirm.add_argument("--json", action="store_true", help="print raw JSON")
    routine_confirm.set_defaults(func=_cmd_routine_confirm)

    # T18: edit / delete against the already-wired routine_edit /
    # routine_delete RPCs. T3-2: epilog examples live on each leaf parser
    # like every other command; every example line starts with "zn " and
    # parses back to this leaf (test_zn_epilog contract).
    routine_edit = routine_sub.add_parser(
        "edit",
        help="change a routine's time and/or content",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        '  zn routine edit --routine-id routine-abc123 --time "每天早上9点"\n'
        '  zn routine edit --routine-id routine-abc123 --time "每30分钟"\n'
        '  zn routine edit --routine-id routine-abc123 --content "提醒我看今天的日程"',
    )
    routine_edit.add_argument(
        "--routine-id",
        type=lambda v: _require_non_empty(v, name="--routine-id"),
        required=True,
        help="routine id, e.g. routine-abc123",
    )
    routine_edit.add_argument(
        "--time",
        type=lambda v: _require_non_empty(v, name="--time"),
        default=None,
        help='new schedule, e.g. "每天早上9点" / "每30分钟" / "每周五下午5点"',
    )
    routine_edit.add_argument(
        "--content",
        type=lambda v: _require_non_empty(v, name="--content"),
        default=None,
        help='new task content, e.g. "提醒我看今天的日程"',
    )
    routine_edit.add_argument("--json", action="store_true", help="print raw JSON")
    routine_edit.set_defaults(func=_cmd_routine_edit)

    routine_delete = routine_sub.add_parser(
        "delete",
        help="delete one routine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n" "  zn routine delete --routine-id routine-abc123",
    )
    routine_delete.add_argument(
        "--routine-id",
        type=lambda v: _require_non_empty(v, name="--routine-id"),
        required=True,
        help="routine id, e.g. routine-abc123",
    )
    routine_delete.add_argument("--json", action="store_true", help="print raw JSON")
    routine_delete.set_defaults(func=_cmd_routine_delete)

    # T19: test-run / acknowledge against the already-wired routine_test_run /
    # routine_acknowledge RPCs. T3-2: epilog examples live on each leaf parser
    # like every other command; every example line starts with "zn " and
    # parses back to this leaf (test_zn_epilog contract).
    routine_test_run = routine_sub.add_parser(
        "test-run",
        help="execute a routine once, right now (real execution, not a dry run)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn routine test-run --routine-id routine-abc123\n"
        "  zn routine test-run --routine-id routine-abc123 --json",
    )
    routine_test_run.add_argument(
        "--routine-id",
        type=lambda v: _require_non_empty(v, name="--routine-id"),
        required=True,
        help="routine id, e.g. routine-abc123",
    )
    routine_test_run.add_argument(
        "--json", action="store_true", help="print raw JSON"
    )
    routine_test_run.set_defaults(func=_cmd_routine_test_run)

    routine_acknowledge = routine_sub.add_parser(
        "acknowledge",
        help="mark a routine as reviewed (resets the auto-pause clock)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  zn routine acknowledge --routine-id routine-abc123\n"
        "  zn routine acknowledge --routine-id routine-abc123 --json",
    )
    routine_acknowledge.add_argument(
        "--routine-id",
        type=lambda v: _require_non_empty(v, name="--routine-id"),
        required=True,
        help="routine id, e.g. routine-abc123",
    )
    routine_acknowledge.add_argument(
        "--json", action="store_true", help="print raw JSON"
    )
    routine_acknowledge.set_defaults(func=_cmd_routine_acknowledge)

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
        "  zn diary get\n"
        "  zn diary get --date 2026-10-22",
    )
    diary_get.add_argument(
        "--date",
        type=lambda v: _require_date(v, name="--date"),
        default=None,
        help="entry date in YYYY-MM-DD, e.g. 2026-10-22 (default: today)",
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
