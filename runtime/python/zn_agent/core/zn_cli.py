"""Thin terminal CLI for the ZN resident: ``zn work ...`` / ``zn approval ...``.

This module is deliberately a thin client, not a second control plane. It
reads the resident endpoint file published by
:mod:`zn_agent.core.resident_server` (``<ZN home>/kernel/resident-endpoint.json``),
authenticates with the per-process session secret, and forwards one JSON-RPC
call per command to the already-existing Daemon RPC methods
(``work_list`` / ``work_get`` / ``work_create`` / ``work_submit`` /
``approval_list`` / ``approval_decide`` / ``memory_list`` / ``team_list``). All policy, execution, approval and
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
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .home import get_zn_home
from .cli_format import kv, section, status_word
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


def _one_line(value: Any, *, limit: int = 120) -> str:
    """Collapse untrusted text to one printable line for terminal output."""

    text = str(value or "")
    text = "".join(char if char.isprintable() else " " for char in text)
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: max(0, limit - 1)].rstrip() + "…"
    return text


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int
    secret: str
    path: Path


def _default_endpoint_path() -> Path:
    return get_zn_home() / "kernel" / "resident-endpoint.json"


def _pid_is_dead(pid: int) -> bool:
    """True only when the OS positively reports the pid does not exist.

    POSIX reports a dead pid as ``ProcessLookupError`` (ESRCH). Windows
    reports it as ``OSError`` with ``winerror == 87``
    (ERROR_INVALID_PARAMETER from OpenProcess). Any other failure --
    notably access denied for a live process owned by someone else -- is
    inconclusive and treated as alive; the connect attempt below decides.
    """

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    except OSError as exc:
        return getattr(exc, "winerror", None) == 87
    return False


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
        raise CliError(
            f"resident endpoint not found at {path}: the ZN resident does not "
            "appear to be running (start the resident first; the desktop app "
            "starts one, or run zn-resident)"
        ) from None
    except (OSError, ValueError) as exc:
        raise CliError(
            f"resident endpoint at {path} is not readable as JSON: {exc}"
        ) from None
    if not isinstance(payload, dict):
        raise CliError(f"resident endpoint at {path} is not a JSON object")

    version = payload.get("version")
    if version is not None and version != 2:
        raise CliError(
            f"unsupported resident endpoint version {version!r} at {path}: "
            "this CLI only speaks endpoint version 2"
        )
    transport = payload.get("transport")
    if transport is not None and transport != "tcp":
        raise CliError(
            f"unsupported resident endpoint transport {transport!r} at {path}"
        )
    host = str(payload.get("host") or "").strip().lower()
    if host not in _LOOPBACK_HOSTS:
        raise CliError(
            f"refusing to connect to non-loopback resident host {host!r} "
            f"from endpoint {path}: the resident control plane is loopback-only"
        )
    if host == "localhost":
        host = "127.0.0.1"
    try:
        port = int(payload.get("port") or 0)
    except (TypeError, ValueError):
        raise CliError(f"resident endpoint at {path} has an invalid port") from None
    if not 0 < port < 65536:
        raise CliError(
            f"resident endpoint at {path} has an invalid port {payload.get('port')!r}"
        )
    auth = payload.get("authentication")
    if not isinstance(auth, dict) or auth.get("scheme") != _ENDPOINT_AUTH_SCHEME:
        raise CliError(
            f"resident endpoint at {path} does not carry the expected "
            f"authentication scheme {_ENDPOINT_AUTH_SCHEME!r}"
        )
    secret = auth.get("secret")
    if not isinstance(secret, str) or len(secret) < 32:
        raise CliError(
            f"resident endpoint at {path} has a missing or too-short session secret"
        )
    pid = payload.get("pid")
    if isinstance(pid, int) and pid > 0 and pid != os.getpid() and _pid_is_dead(pid):
        raise CliError(
            f"resident endpoint at {path} is stale: the resident process "
            f"(pid {pid}) no longer exists"
        )
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
            raise CliError(
                "could not reach the ZN resident at "
                f"{self.endpoint.host}:{self.endpoint.port}: {exc} "
                "(the endpoint file may be stale; restart the resident)"
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
                    raise CliError(
                        "resident authentication failed: "
                        f"{auth.get('error') or 'unknown reason'} "
                        "(the endpoint file may be stale; restart the resident)"
                    )
                self._send(
                    raw_conn,
                    {"id": request_id, "method": method, "params": params or {}},
                )
                response = self._read(stream, f"RPC {method!r}")
        except CliError:
            raise
        except (OSError, TimeoutError) as exc:
            raise CliError(
                f"lost connection to the ZN resident during {method!r}: {exc}"
            ) from None
        if not response.get("ok"):
            raise CliError(
                f"resident rejected {method!r}: {response.get('error') or 'unknown error'}"
            )
        return response.get("result")

    @staticmethod
    def _send(conn, payload: dict[str, Any]) -> None:
        conn.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))

    @staticmethod
    def _read(stream, what: str) -> dict[str, Any]:
        raw = stream.readline()
        if not raw:
            raise CliError(
                f"resident closed the connection without a response to {what}"
            )
        if not isinstance(raw, (bytes, bytearray)):
            raise CliError(
                f"resident returned a non-bytes response to {what}"
            )
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise CliError(f"resident returned invalid JSON for {what}: {exc}") from None
        if not isinstance(parsed, dict):
            raise CliError(f"resident returned a non-object response for {what}")
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


def _client(args: argparse.Namespace) -> ResidentClient:
    endpoint = load_endpoint(getattr(args, "endpoint", None))
    return ResidentClient(endpoint, timeout=args.timeout)


def _emit(args: argparse.Namespace, result: Any, *, human: str) -> None:
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(human)


def _cmd_work_list(args: argparse.Namespace) -> int:
    result = _client(args).call("work_list", {"limit": args.limit})
    if not isinstance(result, list):
        raise CliError(f"resident returned an unexpected work_list result: {result!r}")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    if not result:
        print("no work threads")
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
        raise CliError(f"resident returned an unexpected work_get result: {result!r}")
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
            print(
                f"[{message.get('created_at') or '-'}] {message.get('role') or '?'}: "
                f"{_one_line(message.get('text'), limit=500)}"
            )
    else:
        print("(no messages)")
    return 0


def _cmd_work_submit(args: argparse.Namespace) -> int:
    client = _client(args)
    thread_id = args.thread_id
    if not thread_id:
        created = client.call(
            "work_create",
            {"title": args.title or args.task[:100]},
        )
        if not isinstance(created, dict) or not created.get("id"):
            raise CliError(
                f"resident returned an unexpected work_create result: {created!r}"
            )
        thread_id = str(created["id"])
    result = client.call(
        "work_submit",
        {"thread_id": thread_id, "task": args.task},
    )
    if not isinstance(result, dict):
        raise CliError(
            f"resident returned an unexpected work_submit result: {result!r}"
        )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    thread = result.get("thread") if isinstance(result.get("thread"), dict) else {}
    run = result.get("run") if isinstance(result.get("run"), dict) else {}
    print(
        f"submitted to thread {thread_id}"
        + (f"  ({_one_line(thread.get('title'), limit=60)})" if thread.get("title") else "")
    )
    if result.get("recovery_required"):
        print("recovery required: the work was recorded and needs a recovery step")
    elif run:
        print(
            f"run event={run.get('event_id') or '-'}  success={run.get('success')}  "
            f"cancelled={run.get('cancelled')}  path={run.get('execution_path') or '-'}  "
            f"model_invocations={run.get('model_invocations')}"
        )
        if run.get("response"):
            print(_one_line(run.get("response"), limit=500))
    return 0


def _format_approval_card(item: dict[str, Any]) -> str:
    return (
        f"{item.get('request_id') or '?'}  [{status_word(item.get('status') or '?')}]  "
        f"{item.get('action_kind') or '?'}  target={_one_line(item.get('target'), limit=60)}  "
        f"scope={_one_line(item.get('scope'), limit=40)}  "
        f"expires={item.get('expires_at') or '-'}"
    )


def _cmd_approval_list(args: argparse.Namespace) -> int:
    result = _client(args).call("approval_list", {})
    if not isinstance(result, dict):
        raise CliError(
            f"resident returned an unexpected approval_list result: {result!r}"
        )
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
        for item in items:
            if isinstance(item, dict):
                print(_format_approval_card(item))
    if not shown:  # pragma: no cover - argparse restricts --status choices
        raise CliError(f"unknown approval status filter: {wanted!r}")
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
        raise CliError(
            f"resident returned an unexpected approval_decide result: {result!r}"
        )
    request = result["request"]
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    print(
        f"{request.get('request_id') or args.request_id}  "
        f"status={request.get('status') or '?'}  decision={request.get('decision') or decision}"
    )
    return 0


def _cmd_memory_list(args: argparse.Namespace) -> int:
    result = _client(args).call("memory_list", {"limit": args.limit})
    if not isinstance(result, list):
        raise CliError(f"resident returned an unexpected memory_list result: {result!r}")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    if not result:
        print("no remembered facts")
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
        raise CliError(f"resident returned an unexpected team_list result: {result!r}")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    if not result:
        print("no active teams")
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
        raise CliError(
            f"resident returned an unexpected remember result: {result!r}"
        )
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
        raise CliError(
            f"resident returned an unexpected forget result: {result!r}"
        )
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
        raise CliError(
            f"resident returned an unexpected memory_export result: {result!r}"
        )
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
        raise CliError(
            f"resident returned an unexpected memory_import result: {result!r}"
        )
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
    text = _one_line(entry.get("text"), limit=200)
    if text:
        line += f"\n    {text}"
    return line


def _cmd_team_timeline(args: argparse.Namespace) -> int:
    result = _client(args).call("team_timeline", {"thread_id": args.thread_id})
    if not isinstance(result, dict) or not isinstance(result.get("entries"), list):
        raise CliError(
            f"resident returned an unexpected team_timeline result: {result!r}"
        )
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
        raise CliError(
            f"resident returned an unexpected work_cancel result: {result!r}"
        )
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
        raise CliError(f"resident returned an unexpected connector_status result: {result!r}")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"connector mount report (daemon, {result.get('generated_at') or 'unknown time'})")
    failed = 0
    for item in result["connectors"]:
        if not isinstance(item, dict):
            continue
        if item.get("approved") and not item.get("mounted"):
            state = "FAILED "
            failed += 1
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
        raise CliError(f"resident returned an unexpected connector_reload result: {result!r}")
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
        raise CliError(
            f"resident returned an unexpected autonomy_list result: {result!r}"
        )
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
        raise CliError(
            f"resident returned an unexpected autonomy_get result: {result!r}"
        )
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
        raise CliError(
            f"resident returned an unexpected autonomy_set result: {result!r}"
        )
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
        raise CliError(
            f"resident returned an unexpected suggestions_list result: {result!r}"
        )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    if not result:
        print("no suggestions")
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
        raise CliError(
            f"resident returned an unexpected suggestions_dismiss result: {result!r}"
        )
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
        raise CliError(f"resident returned an unexpected {method} result: {result!r}")
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
        raise CliError(f"resident returned an unexpected goal_list result: {result!r}")
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
        if not item.get("approved"):
            state = "off    "
            reason = "not approved in connectors.yaml (default off)"
        elif mount.get("mounted") is True:
            state = "mounted"
            reason = str(mount.get("reason") or "")
        elif mount.get("mounted") is False:
            state = "FAILED "
            reason = str(mount.get("reason") or "")
        else:
            state = "pending"
            reason = str(item.get("readiness") or "will mount on next daemon start")
        print(
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
            print(f"reachable   {identity}  {latency}")
        else:
            print(f"unreachable {identity}  {_one_line(result.detail, limit=160)}")
    print(f"{report.reachable_count} of {len(report.results)} route(s) reachable")
    return 0 if report.any_reachable else 1


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
    sub = parser.add_subparsers(dest="command", metavar="command")

    chat = sub.add_parser(
        "chat",
        help="talk to ZN interactively (same as running zn with no command)",
    )
    chat.set_defaults(func=_cmd_chat)

    work = sub.add_parser("work", help="list, inspect, or submit resident work")
    work_sub = work.add_subparsers(dest="work_command", metavar="subcommand", required=True)

    work_list = work_sub.add_parser("list", help="list work threads")
    work_list.add_argument(
        "--limit", type=lambda v: _require_positive_int(v, name="--limit", maximum=100),
        default=24,
    )
    work_list.add_argument("--json", action="store_true", help="print raw JSON")
    work_list.set_defaults(func=_cmd_work_list)

    work_get = work_sub.add_parser("get", help="show one work thread")
    work_get.add_argument("--thread-id", type=lambda v: _require_non_empty(v, name="--thread-id"), required=True)
    work_get.add_argument(
        "--message-limit",
        type=lambda v: _require_positive_int(v, name="--message-limit", maximum=500),
        default=120,
    )
    work_get.add_argument("--json", action="store_true", help="print raw JSON")
    work_get.set_defaults(func=_cmd_work_get)

    work_submit = work_sub.add_parser("submit", help="submit a task to a work thread")
    work_submit.add_argument("--thread-id", default=None,
                             help="existing thread id; omitted = create a new thread")
    work_submit.add_argument("--title", default=None,
                             help="title for a newly created thread")
    work_submit.add_argument("--task", type=lambda v: _require_non_empty(v, name="--task"), required=True)
    work_submit.add_argument("--json", action="store_true", help="print raw JSON")
    work_submit.set_defaults(func=_cmd_work_submit)

    work_cancel = work_sub.add_parser("cancel", help="cancel an active work event")
    work_cancel.add_argument("--thread-id", type=lambda v: _require_non_empty(v, name="--thread-id"), required=True)
    work_cancel.add_argument("--event-id", type=lambda v: _require_non_empty(v, name="--event-id"), required=True)
    work_cancel.add_argument("--json", action="store_true", help="print raw JSON")
    work_cancel.set_defaults(func=_cmd_work_cancel)

    approval = sub.add_parser("approval", help="list or decide approval cards")
    approval_sub = approval.add_subparsers(
        dest="approval_command", metavar="subcommand", required=True
    )

    approval_list = approval_sub.add_parser("list", help="list approval cards")
    approval_list.add_argument(
        "--status",
        choices=["pending", "denied", "expired", "applied", "all"],
        default="pending",
        help="which cards to show (default: pending)",
    )
    approval_list.add_argument("--json", action="store_true", help="print raw JSON")
    approval_list.set_defaults(func=_cmd_approval_list)

    approval_decide = approval_sub.add_parser(
        "decide", help="decide one pending approval card"
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

    memory = sub.add_parser("memory", help="inspect durable memory")
    memory_sub = memory.add_subparsers(
        dest="memory_command", metavar="subcommand", required=True
    )

    memory_list = memory_sub.add_parser("list", help="list remembered fact keys")
    memory_list.add_argument(
        "--limit", type=lambda v: _require_positive_int(v, name="--limit", maximum=200),
        default=20,
    )
    memory_list.add_argument("--json", action="store_true", help="print raw JSON")
    memory_list.set_defaults(func=_cmd_memory_list)

    memory_remember = memory_sub.add_parser("remember", help="store one durable fact")
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

    memory_forget = memory_sub.add_parser("forget", help="forget one durable fact")
    memory_forget.add_argument("--key", type=lambda v: _require_non_empty(v, name="--key"), required=True)
    memory_forget.add_argument(
        "--yes",
        action="store_true",
        help="skip the interactive confirmation (without it, forgetting requires a typed yes)",
    )
    memory_forget.add_argument("--json", action="store_true", help="print raw JSON")
    memory_forget.set_defaults(func=_cmd_memory_forget)

    memory_export = memory_sub.add_parser(
        "export", help="export all remembered facts to a versioned JSON file"
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
        "import", help="restore facts from a memory export file"
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

    team_list = team_sub.add_parser("list", help="list active project teams")
    team_list.add_argument(
        "--limit", type=lambda v: _require_positive_int(v, name="--limit", maximum=200),
        default=20,
    )
    team_list.add_argument("--json", action="store_true", help="print raw JSON")
    team_list.set_defaults(func=_cmd_team_list)

    team_timeline = team_sub.add_parser("timeline", help="show the team timeline of a work thread")
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
        "check", help="probe configured model routes (local, no resident needed)"
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
        "list", help="list known connectors (local, no resident needed)"
    )
    connector_list.add_argument("--json", action="store_true", help="print raw JSON")
    connector_list.set_defaults(func=_cmd_connector_list)

    connector_status = connector_sub.add_parser(
        "status", help="show connector mount status"
    )
    connector_status.add_argument("--json", action="store_true", help="print raw JSON")
    connector_status.set_defaults(func=_cmd_connector_status)

    connector_reload = connector_sub.add_parser(
        "reload", help="hot-reload connectors.yaml (no daemon restart)"
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
        "list", help="list explicit per-domain autonomy levels"
    )
    autonomy_list.add_argument("--json", action="store_true", help="print raw JSON")
    autonomy_list.set_defaults(func=_cmd_autonomy_list)

    autonomy_get = autonomy_sub.add_parser(
        "get", help="show the autonomy level of one domain"
    )
    autonomy_get.add_argument(
        "domain",
        type=lambda v: _require_non_empty(v, name="domain"),
        help="policy domain, e.g. recurring.interval or connector.weather",
    )
    autonomy_get.add_argument("--json", action="store_true", help="print raw JSON")
    autonomy_get.set_defaults(func=_cmd_autonomy_get)

    autonomy_set = autonomy_sub.add_parser(
        "set", help="set the autonomy level of one domain (audited)"
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
        "list", help="list active suggestions"
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
        "dismiss", help="dismiss one suggestion by key"
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
        "list", help="list self-drive goals (read-only)"
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
        "status", help="show self-drive status (read-only)"
    )
    goal_status.add_argument("--json", action="store_true", help="print raw JSON")
    goal_status.set_defaults(func=_cmd_goal_status)
    return parser


def run(argv: list[str] | None = None) -> int:
    """Parse argv and run one command. Returns a process exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if not hasattr(args, "func"):
        # TERM-1: bare `zn` is the front door -- it opens the interactive
        # chat REPL instead of printing help at the user.
        args.func = _cmd_chat
    try:
        return int(args.func(args))
    except CliError as exc:
        print(f"zn: error: {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 1


def main(argv: list[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
