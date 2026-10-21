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
* ``/new`` starts a fresh thread, ``/history`` re-reads the thread via
  ``work_get``, ``/help`` lists the session commands, ``/exit`` (or
  Ctrl-D / EOF) leaves.

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

from .zn_cli import CliError

__all__ = ["ChatSession", "DEFAULT_POLL_INTERVAL_SECONDS"]


DEFAULT_POLL_INTERVAL_SECONDS = 0.35

_PROMPT = "zn> "

_WELCOME = (
    "ZN 会话模式：直接说话就能交办（回车发送），同一会话里可以接着追问。\n"
    "/help 看会话命令，/new 开新会话，/exit 退出。"
)

_HELP_TEXT = """会话命令（单独一行输入）：
  /new       开新会话（下一句话在新 thread 里交办）
  /history   回看当前会话的历史消息
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
            if text == "/history":
                self._show_history()
                continue
            if text == "/help":
                self._say(_HELP_TEXT)
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

    # -- one turn of work ---------------------------------------------------

    def _run_turn(self, task: str) -> None:
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
