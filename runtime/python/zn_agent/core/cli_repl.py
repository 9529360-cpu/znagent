"""Interactive chat REPL for the ZN terminal client (TERM-1).

Running ``zn`` with no subcommand (or ``zn chat``) lands here: the user
talks to ZN in natural language instead of memorising subcommands. Each
line the user types is one turn of work on a durable resident Work thread:

* the first turn creates the thread (``work_create``), later turns reuse
  it, so follow-up questions continue the same conversation;
* a turn is driven through the existing async RPC pair ``work_start`` /
  ``work_progress`` -- progress stages and the streamed
  ``assistant_response`` chunks are rendered as they arrive, and the
  finalized thread snapshot supplies the authoritative final answer;
* Ctrl-C during a turn sends ``work_cancel`` for just that event and
  returns to the prompt -- the REPL itself keeps running;
* ``/new`` starts a fresh thread, ``/resume`` attaches the REPL to the
  most recent existing thread (via ``work_list``), ``/history`` re-reads
  the thread via ``work_get``, ``/status`` shows the six-row ``zn status``
  aggregate (read-only, same data contract as ``_cmd_status`` in
  ``zn_cli.py``), ``/approvals`` lists pending approval cards read-only
  and ``/decide <request_id>`` decides one card through a numbered
  option menu (approve once / deny with an optional note / always allow
  / cancel), ``/help`` lists the session commands, ``/exit`` (or Ctrl-D / EOF)
  leaves. The REPL never attaches to an old thread on its own: ``/resume``
  is the only way to pick one up, so a fresh start always begins empty.
  If ``work_list`` fails, ``/resume`` falls back to new-thread behaviour
  with a human-readable note instead of crashing. ``/status`` and
  ``/approvals`` never exit the session: when the resident is
  unreachable they print the T2-6 offline rows (each resident-backed row
  marked unreachable with a human-readable hint) and return to the
  prompt.

No backend semantics are added: every operation is an existing Daemon
RPC, the resident keeps owning execution, approvals and persistence.
Lines starting with ``/`` that are not exact session commands are passed
through as task text untouched, so resident-level slash features (skill
references such as ``/技能名 ...``) keep working exactly like
``zn work submit``.

When stdin is not a TTY (piped input), the REPL reads lines until EOF,
runs each as a turn without printing a prompt, and exits -- scripts can
drive it, and it never blocks waiting for interactive input that cannot
arrive.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Callable, TextIO

from .zn_cli import (
    CliError,
    _APPROVAL_PENDING_HINT,
    _STATUS_DEFAULT_PROBE_TIMEOUT_SECONDS,
    _format_approval_card,
    _format_elapsed_seconds,
)
from .cli_format import colorize, section, status_word, symbol
from .model_check import check_model_routes

__all__ = ["ChatSession", "DEFAULT_POLL_INTERVAL_SECONDS"]


DEFAULT_POLL_INTERVAL_SECONDS = 0.35

_PROMPT = "zn> "

_WELCOME = (
    "ZN 会话模式：直接说话就能交办（回车发送），同一会话里可以接着追问。\n"
    "/help 看会话命令，/resume 回到最近的会话，/new 开新会话，/exit 退出。"
)

_HELP_TEXT = """会话命令（单独一行输入）：
  /new       开新会话（下一句话在新 thread 里交办）
  /resume    回到最近的会话（下一句话接上它的上下文继续说）
  /history   回看当前会话的历史消息
  /status    看 ZN 当前状态（常驻/模型/连接器/待审批/自驱域，同 zn status）
  /approvals 列出待审批的卡片（只读；用 /decide <卡号> 做决定，也可去另一个终端跑 zn approval decide）
  /decide    对一张审批卡做决定（/decide <卡号>：1 批准 / 2 拒绝（可附理由）/ 3 总是允许 / 4 取消）
  /help      显示这份帮助
  /exit      退出会话（Ctrl-D 也可以）
其他任何一行文字都会作为任务发给 ZN；干活时按 Ctrl-C 只取消当前这一轮，会话不退出。"""


def _one_line(value: Any, *, limit: int = 120) -> str:
    """Collapse untrusted text to one printable line for terminal output."""

    text = str(value or "")
    text = "".join(char if char.isprintable() else " " for char in text)
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: max(0, limit - 1)].rstrip() + "…"
    return text


# Roles that carry ZN's own reply in a work thread snapshot: the real
# resident writes role "zn"; some snapshot producers use "assistant".
_REPLY_ROLES = frozenset({"zn", "assistant"})


def _last_assistant_text(snapshot: Any) -> str:
    if not isinstance(snapshot, dict):
        return ""
    messages = snapshot.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") in _REPLY_ROLES:
            return str(message.get("text") or "")
    return ""


def _latest_thread(result: Any) -> tuple[str, str] | None:
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


def _status_lines(client: Any, *, stream: TextIO) -> list[str]:
    """Six-row ZN status aggregate for the REPL (``/status``).

    Same data contract as ``zn status`` (``_cmd_status`` in ``zn_cli.py``,
    read-only verified there): the five resident RPCs ``ping`` / ``status`` /
    ``connector_status`` / ``approval_list`` / ``autonomy_list`` plus the
    local model probe. Rendering reuses the cli_format contract (TTY-gated
    colors/symbols via the *stream* the REPL writes to, T2-1/T2-7) and the
    same row copy/hints, so the REPL and the subcommand never drift apart.

    When the resident is unreachable, every resident-backed row is marked
    unreachable with a human-readable hint (T2-6 offline contract) while
    the local model probe and the local connector evaluation still run --
    and the caller keeps the session alive (``/status`` never exits).
    """
    lines: list[str] = []
    daemon_error = ""

    def _rpc(method: str, params: dict[str, Any] | None = None) -> Any:
        nonlocal daemon_error
        try:
            return client.call(method, params)
        except CliError as exc:
            daemon_error = str(exc)
            return None

    ping_result = _rpc("ping", {})
    summary_result = _rpc("status", {})
    connector_result = _rpc("connector_status", {})
    approval_result = _rpc("approval_list", {})
    autonomy_result = _rpc("autonomy_list")

    # Local probe, like ``zn status``: works without a running resident.
    report = check_model_routes(
        probe_timeout_seconds=_STATUS_DEFAULT_PROBE_TIMEOUT_SECONDS
    )

    def _row(
        label: str,
        text: str,
        *,
        kind: str | None = None,
        hint: str | None = None,
        sym: str | None = None,
    ) -> None:
        # T2-7: unified status glyph, TTY-only via symbol() ("" off-TTY, so
        # piped output keeps its historic bytes). The stream is the REPL's
        # own output stream, not necessarily sys.stdout.
        mark = symbol(sym, stream=stream) if sym else ""
        cell = f"{label:<10} {mark + ' ' if mark else ''}{text}"
        if kind:
            cell = colorize(cell, kind, stream=stream)
        if hint:
            cell += colorize(f"  → {hint}", "dim", stream=stream)
        lines.append(cell)

    lines.append(section("ZN status", stream=stream))

    # resident row
    if isinstance(ping_result, dict):
        pulse = _one_line(ping_result.get("pulse_count"), limit=12)
        if ping_result.get("alive"):
            _row(
                "resident",
                f"{status_word(True, stream=stream)} (pulse_count={pulse})",
                sym="ok",
            )
        else:
            _row(
                "resident",
                status_word("unknown", stream=stream),
                kind="err",
                hint="zn-resident",
                sym="fail",
            )
    else:
        _row(
            "resident",
            f"{status_word('unreachable', stream=stream)} "
            f"({_one_line(daemon_error, limit=90)})",
            kind="err",
            hint="check ZN_HOME, or start the resident service (zn-resident)",
            sym="fail",
        )

    # summary row
    if isinstance(summary_result, dict):
        identity = summary_result.get("identity") or {}
        if not isinstance(identity, dict):
            identity = {}
        dependency = summary_result.get("model_dependency") or {}
        if not isinstance(dependency, dict):
            dependency = {}
        name = _one_line(identity.get("name"), limit=32)
        version = _one_line(identity.get("version"), limit=16)
        invocations = _one_line(dependency.get("model_invocations"), limit=12)
        _row(
            "summary",
            f"{name} v{version} · model_invocations={invocations}",
        )
    else:
        _row("summary", status_word("unreachable", stream=stream), kind="err")

    # model row (local probe)
    if not report.configured:
        _row(
            "model",
            "no model routes configured",
            kind="err",
            hint="zn model check",
            sym="fail",
        )
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
    connector_local = False
    connector_counts: dict[str, Any] = {
        "mounted": None,
        "approved": None,
        "failed": None,
    }
    if isinstance(connector_result, dict) and isinstance(
        connector_result.get("connectors"), list
    ):
        connectors = [
            c for c in connector_result["connectors"] if isinstance(c, dict)
        ]
        connector_counts["mounted"] = sum(1 for c in connectors if c.get("mounted"))
        connector_counts["approved"] = sum(
            1 for c in connectors if c.get("approved")
        )
        connector_counts["failed"] = sum(
            1 for c in connectors if c.get("approved") and not c.get("mounted")
        )
    else:
        connector_local = True
        try:
            from .connector_autoattach import evaluate_connector_status

            items = evaluate_connector_status()
        except Exception as exc:
            connector_counts["config_error"] = _one_line(str(exc), limit=200)
            items = []
        approved_items = [
            i for i in items if isinstance(i, dict) and i.get("approved")
        ]
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

    counts = connector_counts
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
    if isinstance(approval_result, dict) and isinstance(
        approval_result.get("pending"), list
    ):
        pending = len(approval_result["pending"])
    else:
        pending = None
    if pending is None:
        _row(
            "approvals",
            status_word("unreachable", stream=stream),
            kind="err",
            sym="fail",
        )
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
    if isinstance(autonomy_result, list):
        domains = sum(1 for item in autonomy_result if isinstance(item, dict))
    else:
        domains = None
    if domains is None:
        _row("autonomy", status_word("unreachable", stream=stream), kind="err")
    else:
        _row(
            "autonomy", f"{domains} explicit domain(s)", hint="zn autonomy list"
        )

    return lines


class ChatSession:
    """One interactive conversation against the resident, over a client.

    ``client`` is any object with ``call(method, params)`` semantics
    matching :class:`zn_agent.core.zn_cli.ResidentClient` (raising
    :class:`CliError` on failure). Input/output streams and the sleep
    function are injectable for tests.
    """

    def __init__(
        self,
        client: Any,
        *,
        input_fn: Callable[[str], str] | None = None,
        out: TextIO | None = None,
        err: TextIO | None = None,
        interactive: bool | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self._input_fn = input_fn
        self.out = out if out is not None else sys.stdout
        self.err = err if err is not None else sys.stderr
        if interactive is None:
            try:
                interactive = bool(sys.stdin.isatty())
            except Exception:
                interactive = False
        self.interactive = interactive
        self.poll_interval = max(0.0, float(poll_interval))
        self._sleep = sleep_fn
        self.thread_id: str | None = None

    # -- output helpers -------------------------------------------------

    def _say(self, text: str = "") -> None:
        print(text, file=self.out, flush=True)

    def _write(self, text: str) -> None:
        self.out.write(text)
        self.out.flush()

    def _error(self, message: str, *, hint: str | None = None) -> None:
        print(f"zn: {message}", file=self.err, flush=True)
        if hint:
            print(f"下一步：{hint}", file=self.err, flush=True)

    # -- main loop --------------------------------------------------------

    def run(self) -> int:
        if self.interactive:
            self._say(_WELCOME)
        while True:
            try:
                line = self._read_line()
            except KeyboardInterrupt:
                self._say("\n（这一轮输入已中断；/exit 退出，会话还在。）")
                continue
            if line is None:  # EOF / Ctrl-D
                if self.interactive:
                    self._say("")
                return 0
            text = line.strip()
            if not text:
                continue
            if text in ("/exit", "/quit"):
                return 0
            if text == "/new":
                self.thread_id = None
                self._say("好，开新会话：下一句话会是新会话的第一句。")
                continue
            if text == "/resume":
                self._resume_latest()
                continue
            if text == "/history":
                self._show_history()
                continue
            if text == "/help":
                self._say(_HELP_TEXT)
                continue
            if text == "/status":
                self._show_status()
                continue
            if text == "/approvals":
                self._show_pending_approvals()
                continue
            if text == "/decide":
                self._decide_approval("")
                continue
            if text.startswith("/decide "):
                self._decide_approval(text[len("/decide "):])
                continue
            self._run_turn(text)

    def _read_line(self) -> str | None:
        prompt = _PROMPT if self.interactive else ""
        read = self._input_fn if self._input_fn is not None else input
        try:
            return read(prompt)
        except EOFError:
            return None

    # -- session commands -------------------------------------------------

    def _resume_latest(self) -> None:
        """Attach to the most recent thread, if the resident has one (``/resume``).

        Only the newest snapshot from ``work_list`` is read; the limit of 1
        keeps the RPC cheap. On failure the session falls back to
        new-thread behaviour -- the pre-existing thread (if any) is left
        untouched and the next turn just creates a new thread as usual.
        """
        try:
            result = self.client.call("work_list", {"limit": 1})
        except CliError as exc:
            self._error(
                f"最近的会话没恢复出来（work_list failed）：{exc}",
                hint="确认 ZN 常驻进程还在运行，再试一次 /resume；直接说话会开一个新会话。",
            )
            return
        latest = _latest_thread(result)
        if latest is None:
            self._say("（还没有历史会话——先跟 ZN 说句话，开一个新会话吧。）")
            return
        thread_id, title = latest
        if thread_id == self.thread_id:
            self._say(f"· 已经在最近的会话里了（{thread_id}），继续说话就行。")
            return
        self.thread_id = thread_id
        title_text = f"「{title}」" if title else ""
        self._say(
            f"· 回到了最近的会话{title_text}（{thread_id}）：下一句话接着它的上下文说。"
        )

    def _show_history(self) -> None:
        if self.thread_id is None:
            self._say("（还没有会话记录——先跟 ZN 说句话吧。）")
            return
        try:
            result = self.client.call(
                "work_get",
                {"thread_id": self.thread_id, "message_limit": 50},
            )
        except CliError as exc:
            self._error(
                f"历史没读出来：{exc}",
                hint="确认 ZN 常驻进程还在运行，再试一次 /history。",
            )
            return
        if not isinstance(result, dict):
            self._error("历史没读出来：ZN 返回了意料之外的结果。")
            return
        messages = result.get("messages")
        if not isinstance(messages, list) or not messages:
            self._say("（这个会话还没有消息。）")
            return
        for message in messages:
            if not isinstance(message, dict):
                continue
            self._say(
                f"[{message.get('created_at') or '-'}] "
                f"{message.get('role') or '?'}: "
                f"{_one_line(message.get('text'), limit=500)}"
            )

    def _show_status(self) -> None:
        """Show the six-row status aggregate (``/status`` ↔ ``zn status``).

        Read-only over the session client's RPCs; when the resident is
        unreachable the offline rows are printed (T2-6) and the session
        simply continues.
        """
        for line in _status_lines(self.client, stream=self.out):
            self._say(line)

    def _show_pending_approvals(self) -> None:
        """List pending approval cards, one card each (``/approvals``).

        Read-only: cards reuse the ``zn approval list`` card renderer.
        Deciding stays in the ``zn approval decide`` subcommand -- only a
        guidance line is printed, never an interactive prompt. With no
        pending cards the command stays silent (no session noise).
        """
        try:
            result = self.client.call("approval_list", {})
        except CliError as exc:
            self._error(
                f"待审批的卡片没列出来：{exc}",
                hint=(
                    "确认 ZN 常驻进程还在运行，再试一次 /approvals；"
                    "或在另一个终端跑 zn approval list。"
                ),
            )
            return
        pending = result.get("pending") if isinstance(result, dict) else None
        cards = (
            [item for item in pending if isinstance(item, dict)]
            if isinstance(pending, list)
            else []
        )
        if not cards:
            return
        for card in cards:
            self._say(_format_approval_card(card))
        self._say(colorize(f"  {_APPROVAL_PENDING_HINT}", "dim", stream=self.out))

    _DECIDE_MENU = (
        "给这张卡做个决定，输入数字：\n"
        "  1) 批准（只批准这一次）\n"
        "  2) 拒绝（可以附理由）\n"
        "  3) 总是允许（以后同类请求自动批准）\n"
        "  4) 取消"
    )

    _DECIDE_LABELS = {
        "allow_once": "已批准",
        "deny": "已拒绝",
        "always_allow": "已设为总是允许",
    }

    def _decide_approval(self, request_id: str) -> None:
        """Decide one approval card through a numbered menu
        (``/decide <request_id>``).

        The card is rendered with the shared ``zn approval list`` card
        renderer, so the decision is made on the same detail ``/approvals``
        and ``zn approval show`` display. The decision goes through the
        existing ``approval_decide`` RPC with the same params ``zn
        approval decide`` sends -- including the AP-1 note channel
        (denial feedback only, passed straight to the daemon); nothing is
        auto-approved and the card is never bypassed. Ctrl-C only leaves
        the option menu: the card stays pending. The choice is read
        through ``_read_line``, so piped mode behaves like a TTY.
        """
        request_id = request_id.strip()
        if not request_id:
            self._error(
                "/decide 缺了审批卡的编号 (missing request_id)",
                hint="先用 /approvals 列出待审批的卡片，再用 /decide <request_id> 做决定。",
            )
            return
        try:
            result = self.client.call("approval_list", {})
        except CliError as exc:
            self._error(
                f"审批卡没拿到 (approval_list failed)：{exc}",
                hint=f"确认 ZN 常驻进程还在运行，再试一次 /decide {request_id}。",
            )
            return
        pending = result.get("pending") if isinstance(result, dict) else None
        cards = (
            [item for item in pending if isinstance(item, dict)]
            if isinstance(pending, list)
            else []
        )
        card = next(
            (
                item
                for item in cards
                if str(item.get("request_id")) == request_id
            ),
            None,
        )
        if card is None:
            self._error(
                f"没找到待审批的卡片 {request_id} (approval card not found)",
                hint="卡号用 /approvals 复制；这张卡可能已经被处理过了。",
            )
            return
        self._say(_format_approval_card(card))
        chosen = self._choose_decision()
        if chosen is None:
            return  # cancelled or Ctrl-C: the card stays pending
        decision, note = chosen
        params: dict[str, Any] = {
            "request_id": request_id,
            "decision": decision,
        }
        if decision == "deny" and note.strip():
            # AP-1 note channel: denial feedback only. Notes are only ever
            # collected for denials, so the AP-1 warn-and-drop case for
            # approvals cannot occur here; the params match
            # `zn approval decide` byte for byte.
            params["note"] = note.strip()
        try:
            decided = self.client.call("approval_decide", params)
        except CliError as exc:
            self._error(
                f"决定没发出去 (approval_decide failed)：{exc}",
                hint="确认 ZN 常驻进程还在运行，再试一次这张卡的 /decide。",
            )
            return
        if not isinstance(decided, dict) or not isinstance(
            decided.get("request"), dict
        ):
            self._error(
                "决定返回了意料之外的结果 "
                "(unexpected approval_decide result)。"
            )
            return
        label = self._DECIDE_LABELS[decision]
        note_text = (
            f"（理由：{_one_line(note.strip(), limit=60)}）"
            if decision == "deny" and note.strip()
            else ""
        )
        self._say(f"· {request_id}：{label}{note_text}")

    def _choose_decision(self) -> tuple[str, str] | None:
        """Read the numbered decision; ``None`` means the user cancelled
        or Ctrl-C'd out.

        Non-numeric input re-asks; Ctrl-C only leaves this menu (no
        ``approval_decide`` RPC is ever sent, the card stays pending).
        """
        self._say(self._DECIDE_MENU)
        while True:
            try:
                raw = self._read_line()
            except KeyboardInterrupt:
                self._say("\n（已退出选项；这张卡还在待审批里。）")
                return None
            if raw is None:  # EOF: piped input ended -- nothing decided
                return None
            choice = raw.strip()
            if choice == "4":
                self._say("取消了，这张卡还在待审批里。")
                return None
            if choice in ("1", "3"):
                return ("allow_once", "") if choice == "1" else (
                    "always_allow",
                    "",
                )
            if choice == "2":
                reason = self._ask_denial_reason()
                if reason is None:
                    return None
                return "deny", reason
            self._say("只认 1 到 4 的数字，再选一次（Ctrl-C 退出选项）。")

    def _ask_denial_reason(self) -> str | None:
        """Read the optional denial reason; ``None`` means Ctrl-C/EOF."""
        self._say("拒绝理由（可空，直接回车跳过）：")
        try:
            raw = self._read_line()
        except KeyboardInterrupt:
            self._say("\n（已退出选项；这张卡还在待审批里。）")
            return None
        if raw is None:  # EOF: piped input ended -- nothing decided
            return None
        return raw

    # -- one turn of work ---------------------------------------------------

    def _run_turn(self, task: str) -> None:
        # WK-DUR: client-side wall time for this round (monotonic around the
        # whole turn; printed at the end, TTY and piped alike).
        turn_started = time.monotonic()
        try:
            if self.thread_id is None:
                created = self.client.call("work_create", {"title": task[:100]})
                if not isinstance(created, dict) or not created.get("id"):
                    self._error(
                        "这一轮没发出去：ZN 没有返回新会话的 id。",
                        hint="可以再试一次；一直这样就先退出来用 zn work list 看常驻进程状态。",
                    )
                    return
                self.thread_id = str(created["id"])
                self._say(f"· 新会话 {self.thread_id}")
            started = self.client.call(
                "work_start", {"thread_id": self.thread_id, "task": task}
            )
        except CliError as exc:
            self._error(
                f"这一轮没发出去：{exc}",
                hint="确认 ZN 常驻进程在运行（另一个终端跑 zn work list 能通），再把这句话发一次。",
            )
            return
        if not isinstance(started, dict) or not isinstance(
            started.get("progress"), dict
        ):
            self._error(
                "这一轮没发出去：ZN 返回了意料之外的 work_start 结果。",
                hint="可以再试一次这句话。",
            )
            return
        progress: dict[str, Any] = started["progress"]
        snapshot = started.get("thread")
        event_id = str(progress.get("event_id") or "")
        if not event_id:
            self._error(
                "这一轮没发出去：ZN 没有返回这一轮的 event_id。",
                hint="可以再试一次这句话。",
            )
            return

        streamed = ""
        last_stage_line: str | None = None
        interrupted = False
        try:
            while True:
                # Dedupe on the rendered line itself: progress fields the
                # user never sees (next_action, counters) change far more
                # often than the stage text and must not re-print it.
                stage_line = self._stage_line(progress)
                if stage_line is not None and stage_line != last_stage_line:
                    last_stage_line = stage_line
                    self._say(stage_line)
                response = progress.get("assistant_response")
                if isinstance(response, str) and len(response) > len(streamed):
                    self._write(response[len(streamed):])
                    streamed = response
                if progress.get("finalized"):
                    break
                if progress.get("terminal") and progress.get("error"):
                    break
                self._sleep(self.poll_interval)
                result = self.client.call(
                    "work_progress",
                    {"thread_id": self.thread_id, "event_id": event_id},
                )
                if isinstance(result, dict):
                    if isinstance(result.get("progress"), dict):
                        progress = result["progress"]
                    if isinstance(result.get("thread"), dict):
                        snapshot = result["thread"]
        except KeyboardInterrupt:
            interrupted = True
        except CliError as exc:
            if streamed:
                self._write("\n")
            self._error(
                f"跟 ZN 的连接断了，这一轮的状态没跟完：{exc}",
                hint="这一轮可能还在 ZN 那边继续跑；重连后用 /history 回看，或用 zn work list 查。",
            )
            return

        if streamed:
            self._write("\n")
        if interrupted:
            self._cancel_turn(event_id)
            return
        if progress.get("status") == "cancelled" or progress.get("stage") == "cancelled":
            self._say("这一轮被取消了。会话还在，继续说话就行。")
            return
        if progress.get("terminal") and progress.get("error") and not progress.get("finalized"):
            self._error(
                f"这一轮没能完成：{_one_line(progress.get('error'), limit=200)}",
                hint="可以换个说法再试一次，或 /new 开个新会话。",
            )
            return
        final_text = _last_assistant_text(snapshot)
        if final_text:
            if not streamed:
                self._say(final_text)
            elif final_text.startswith(streamed):
                remainder = final_text[len(streamed):].strip()
                if remainder:
                    self._say(remainder)
            elif final_text != streamed:
                # The streamed draft was superseded by a different final
                # answer; the durable message wins.
                self._say(final_text)
        elif not streamed:
            self._say("（这一轮完成了，没有文字回复；/history 可以回看会话记录。）")
        # WK-DUR: every completed turn says how long it took, TTY and piped
        # alike (fact line, not decoration).
        self._say(
            f"这一轮用了 {_format_elapsed_seconds(time.monotonic() - turn_started)} 秒。"
        )

    def _stage_line(self, progress: dict[str, Any]) -> str | None:
        stage = str(progress.get("stage") or "")
        if stage in ("complete", "failed", "cancelled"):
            return None
        if stage == "queued":
            return "· 已收到，排队等 ZN 处理…"
        if stage == "waiting_for_user":
            return (
                "· 需要你批准一个操作：在另一个终端跑 zn approval list 看卡片，"
                "处理完这边会自动继续（Ctrl-C 取消这一轮）。"
            )
        if stage == "side_effect_recovery":
            return (
                "· 有一步的外部结果不确定，需要人工确认才能继续"
                "（Ctrl-C 可以取消这一轮）。"
            )
        if stage == "cancelling":
            return "· 正在取消…"
        thought = progress.get("thought")
        focus = (
            _one_line(thought.get("focus"), limit=80)
            if isinstance(thought, dict)
            else ""
        )
        return f"· 处理中：{focus}…" if focus else "· 处理中…"

    def _cancel_turn(self, event_id: str) -> None:
        try:
            self.client.call(
                "work_cancel",
                {"thread_id": self.thread_id, "event_id": event_id},
            )
        except CliError as exc:
            self._error(
                f"取消没发出去：{exc}",
                hint=(
                    "这一轮可能还在 ZN 那边跑；手动取消："
                    f"zn work cancel --thread-id {self.thread_id} --event-id {event_id}"
                ),
            )
            return
        self._say("已取消这一轮。会话还在，继续说话就行。")
