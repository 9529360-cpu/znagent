"""Thin terminal CLI for the ZN resident: ``zn work ...`` / ``zn approval ...``.

This module is deliberately a thin client, not a second control plane. It
reads the resident endpoint file published by
:mod:`zn_agent.core.resident_server` (``<ZN home>/kernel/resident-endpoint.json``),
authenticates with the per-process session secret, and forwards one JSON-RPC
call per command to the already-existing Daemon RPC methods
(``work_list`` / ``work_get`` / ``work_create`` / ``work_submit`` /
``approval_list`` / ``approval_decide`` / ``memory_list`` / ``team_list``). All policy, execution, approval and
persistence decisions stay server-side.

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
        f"{item.get('request_id') or '?'}  [{item.get('status') or '?'}]  "
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
        print(f"--- {label} ({len(items)}) ---")
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
            f"{_one_line(item.get('key'), limit=60)}  tier={_one_line(item.get('tier'))}  "
            f"aliases={alias_text}  updated={_one_line(item.get('updated_at'))}"
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zn",
        description="ZN terminal client: submit work and decide approvals "
        "through the running resident. The resident owns all execution.",
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
    return parser


def run(argv: list[str] | None = None) -> int:
    """Parse argv and run one command. Returns a process exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help(file=sys.stderr)
        return 2
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
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
