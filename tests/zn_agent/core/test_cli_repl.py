"""Tests for the TERM-1 interactive chat REPL (cli_repl + `zn chat`).

Session-logic tests drive :class:`ChatSession` with a scripted stub
client (the same duck-typed ``call(method, params)`` surface the real
``ResidentClient`` exposes). Wiring tests go through ``zn_cli.run`` with
the fake-socket harness pattern from test_zn_cli.py, proving bare ``zn``
and ``zn chat`` both land in the REPL and speak the existing RPCs.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime" / "python"))

from zn_agent.core.cli_repl import ChatSession
from zn_agent.core.zn_cli import CliError, run

_SECRET = "s" * 64


# ---------------------------------------------------------------------------
# Scripted stub client for session-logic tests
# ---------------------------------------------------------------------------


class _StubClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.handlers: dict[str, object] = {}

    def on(self, method, fn):
        self.handlers[method] = fn
        return self

    def call(self, method, params=None):
        params = params or {}
        self.calls.append((method, params))
        fn = self.handlers.get(method)
        if fn is None:
            raise AssertionError(f"unexpected RPC method {method!r}")
        return fn(params)

    def methods(self) -> list[str]:
        return [method for method, _ in self.calls]


class _ScriptedInput:
    """input() stand-in: replays lines, then raises EOFError like Ctrl-D."""

    def __init__(self, lines) -> None:
        self._items = iter(lines)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        try:
            return next(self._items)
        except StopIteration:
            raise EOFError from None


def _input_from(lines):
    return _ScriptedInput(lines)


def _snapshot(thread_id: str, *messages: tuple[str, str]) -> dict:
    return {
        "id": thread_id,
        "messages": [
            {"role": role, "text": text, "created_at": "2026-10-21T10:00:00Z"}
            for role, text in messages
        ],
    }


class _SessionCase(unittest.TestCase):
    def make_session(self, client, lines, *, interactive=True):
        out, err = io.StringIO(), io.StringIO()
        read = _input_from(lines)
        session = ChatSession(
            client,
            input_fn=read,
            out=out,
            err=err,
            interactive=interactive,
            poll_interval=0.0,
            sleep_fn=lambda _seconds: None,
        )
        return session, out, err, read

    def basic_client(self) -> _StubClient:
        """One thread; every turn finalizes on the first progress poll."""

        client = _StubClient()
        client.on("work_create", lambda params: {"id": "thread-1"})

        def start(params):
            return {
                "thread": _snapshot("thread-1"),
                "progress": {
                    "event_id": f"ev-{params['task']}",
                    "stage": "queued",
                    "finalized": False,
                    "terminal": False,
                },
            }

        def progress(params):
            return {
                "progress": {
                    "event_id": params["event_id"],
                    "stage": "complete",
                    "status": "completed",
                    "finalized": True,
                    "terminal": True,
                },
                "thread": _snapshot(
                    "thread-1",
                    ("user", "task"),
                    # The real resident writes its replies with role "zn".
                    ("zn", f"done:{params['event_id']}"),
                ),
            }

        client.on("work_start", start)
        client.on("work_progress", progress)
        return client


class ChatSessionTurnTests(_SessionCase):
    def test_turn_and_followup_share_one_thread(self):
        client = self.basic_client()
        session, out, err, _ = self.make_session(
            client, ["帮我看看天气", "那明天呢"]
        )
        self.assertEqual(session.run(), 0, err.getvalue())
        self.assertEqual(client.methods().count("work_create"), 1)
        starts = [p for m, p in client.calls if m == "work_start"]
        self.assertEqual(len(starts), 2)
        self.assertTrue(all(p["thread_id"] == "thread-1" for p in starts))
        self.assertEqual(starts[0]["task"], "帮我看看天气")
        self.assertEqual(starts[1]["task"], "那明天呢")
        self.assertIn("done:ev-帮我看看天气", out.getvalue())
        self.assertIn("done:ev-那明天呢", out.getvalue())

    def test_streamed_response_prints_delta_then_final_suffix(self):
        client = _StubClient()
        client.on("work_create", lambda params: {"id": "thread-1"})
        client.on(
            "work_start",
            lambda params: {
                "thread": _snapshot("thread-1"),
                "progress": {
                    "event_id": "ev-1",
                    "stage": "processing",
                    "finalized": False,
                    "terminal": False,
                },
            },
        )
        polls = iter(
            [
                {
                    "progress": {
                        "event_id": "ev-1",
                        "stage": "processing",
                        "assistant_response": "你好",
                        "finalized": False,
                        "terminal": False,
                    }
                },
                {
                    "progress": {
                        "event_id": "ev-1",
                        "stage": "complete",
                        "status": "completed",
                        "assistant_response": "你好，我是 ZN",
                        "finalized": True,
                        "terminal": True,
                    },
                    "thread": _snapshot(
                        "thread-1",
                        ("user", "打招呼"),
                        ("assistant", "你好，我是 ZN"),
                    ),
                },
            ]
        )
        client.on("work_progress", lambda params: next(polls))
        session, out, err, _ = self.make_session(client, ["打招呼"])
        self.assertEqual(session.run(), 0, err.getvalue())
        text = out.getvalue()
        # Streamed prefix printed once, final suffix appended, no duplication.
        self.assertEqual(text.count("你好"), 1)
        self.assertIn("你好，我是 ZN", text.replace("\n", ""))

    def test_ctrl_c_cancels_current_turn_and_repl_survives(self):
        client = _StubClient()
        client.on("work_create", lambda params: {"id": "thread-1"})
        starts = {"count": 0}

        def start(params):
            starts["count"] += 1
            if starts["count"] == 1:
                return {
                    "thread": _snapshot("thread-1"),
                    "progress": {
                        "event_id": "ev-1",
                        "stage": "processing",
                        "finalized": False,
                        "terminal": False,
                    },
                }
            return {
                "thread": _snapshot(
                    "thread-1", ("user", params["task"]), ("assistant", "第二件完成")
                ),
                "progress": {
                    "event_id": "ev-2",
                    "stage": "complete",
                    "status": "completed",
                    "finalized": True,
                    "terminal": True,
                },
            }

        def progress(params):
            raise KeyboardInterrupt

        cancelled: list[dict] = []

        def cancel(params):
            cancelled.append(params)
            return {"progress": {"stage": "cancelled", "finalized": True}}

        client.on("work_start", start)
        client.on("work_progress", progress)
        client.on("work_cancel", cancel)
        session, out, err, _ = self.make_session(client, ["干第一件", "干第二件"])
        self.assertEqual(session.run(), 0, err.getvalue())
        self.assertEqual(
            cancelled, [{"thread_id": "thread-1", "event_id": "ev-1"}]
        )
        self.assertIn("已取消这一轮", out.getvalue())
        self.assertIn("第二件完成", out.getvalue())

    def test_ctrl_c_at_prompt_does_not_exit(self):
        client = _StubClient()
        prompts = {"count": 0}

        def read(_prompt: str) -> str:
            prompts["count"] += 1
            if prompts["count"] == 1:
                raise KeyboardInterrupt
            return "/exit"

        out, err = io.StringIO(), io.StringIO()
        session = ChatSession(
            client,
            input_fn=read,
            out=out,
            err=err,
            interactive=True,
            poll_interval=0.0,
            sleep_fn=lambda _s: None,
        )
        self.assertEqual(session.run(), 0)
        self.assertEqual(client.calls, [])
        self.assertIn("会话还在", out.getvalue())

    def test_new_command_switches_thread(self):
        client = _StubClient()
        created = {"count": 0}

        def create(params):
            created["count"] += 1
            return {"id": f"thread-{created['count']}"}

        def start(params):
            return {
                "thread": _snapshot(
                    params["thread_id"],
                    ("user", params["task"]),
                    ("assistant", "ok"),
                ),
                "progress": {
                    "event_id": f"ev-{created['count']}",
                    "stage": "complete",
                    "status": "completed",
                    "finalized": True,
                    "terminal": True,
                },
            }

        client.on("work_create", create)
        client.on("work_start", start)
        session, out, err, _ = self.make_session(
            client, ["第一句", "/new", "第二句"]
        )
        self.assertEqual(session.run(), 0, err.getvalue())
        self.assertEqual(created["count"], 2)
        starts = [p for m, p in client.calls if m == "work_start"]
        self.assertEqual(starts[0]["thread_id"], "thread-1")
        self.assertEqual(starts[1]["thread_id"], "thread-2")
        self.assertIn("开新会话", out.getvalue())

    def test_history_reads_thread_via_work_get(self):
        client = self.basic_client()
        client.on(
            "work_get",
            lambda params: _snapshot(
                "thread-1",
                ("user", "早先的问题"),
                ("assistant", "早先的回答"),
            ),
        )
        session, out, err, _ = self.make_session(client, ["/history", "问一句", "/history"])
        self.assertEqual(session.run(), 0, err.getvalue())
        # First /history happens before any thread exists: no RPC, honest note.
        self.assertIn("还没有会话记录", out.getvalue())
        gets = [p for m, p in client.calls if m == "work_get"]
        self.assertEqual(gets, [{"thread_id": "thread-1", "message_limit": 50}])
        self.assertIn("早先的问题", out.getvalue())
        self.assertIn("早先的回答", out.getvalue())

    def test_noninteractive_reads_lines_until_eof_without_prompt(self):
        client = self.basic_client()
        session, out, err, read = self.make_session(
            client, ["第一件", "第二件"], interactive=False
        )
        self.assertEqual(session.run(), 0, err.getvalue())
        self.assertTrue(all(prompt == "" for prompt in read.prompts))
        starts = [p for m, p in client.calls if m == "work_start"]
        self.assertEqual(len(starts), 2)

    def test_rpc_failure_is_humanized_and_repl_continues(self):
        client = _StubClient()
        client.on("work_create", lambda params: {"id": "thread-1"})
        attempts = {"count": 0}

        def start(params):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise CliError("resident rejected 'work_start': thread busy")
            return {
                "thread": _snapshot(
                    "thread-1", ("user", params["task"]), ("assistant", "第二句答完")
                ),
                "progress": {
                    "event_id": "ev-2",
                    "stage": "complete",
                    "status": "completed",
                    "finalized": True,
                    "terminal": True,
                },
            }

        client.on("work_start", start)
        session, out, err, _ = self.make_session(client, ["第一句", "第二句"])
        self.assertEqual(session.run(), 0)
        self.assertIn("这一轮没发出去", err.getvalue())
        self.assertIn("下一步", err.getvalue())
        self.assertIn("第二句答完", out.getvalue())

    def test_waiting_for_user_stage_prints_approval_hint(self):
        client = _StubClient()
        client.on("work_create", lambda params: {"id": "thread-1"})
        client.on(
            "work_start",
            lambda params: {
                "thread": _snapshot("thread-1"),
                "progress": {
                    "event_id": "ev-1",
                    "stage": "waiting_for_user",
                    "blocked_by": "user_presence_required",
                    "finalized": False,
                    "terminal": False,
                },
            },
        )
        client.on(
            "work_progress",
            lambda params: {
                "progress": {
                    "event_id": "ev-1",
                    "stage": "complete",
                    "status": "completed",
                    "finalized": True,
                    "terminal": True,
                },
                "thread": _snapshot(
                    "thread-1", ("user", "发个邮件"), ("assistant", "已发送")
                ),
            },
        )
        session, out, err, _ = self.make_session(client, ["发个邮件"])
        self.assertEqual(session.run(), 0, err.getvalue())
        self.assertIn("zn approval list", out.getvalue())
        self.assertIn("已发送", out.getvalue())

    def test_unknown_slash_line_is_sent_as_task(self):
        client = self.basic_client()
        session, out, err, _ = self.make_session(client, ["/某个技能 做点事"])
        self.assertEqual(session.run(), 0, err.getvalue())
        starts = [p for m, p in client.calls if m == "work_start"]
        self.assertEqual(starts[0]["task"], "/某个技能 做点事")

    def test_stage_line_not_reprinted_when_only_unseen_fields_change(self):
        client = _StubClient()
        client.on("work_create", lambda params: {"id": "thread-1"})
        client.on(
            "work_start",
            lambda params: {
                "thread": _snapshot("thread-1"),
                "progress": {
                    "event_id": "ev-1",
                    "stage": "processing",
                    "next_action": "step one",
                    "thought": {"focus": "思考中"},
                    "finalized": False,
                    "terminal": False,
                },
            },
        )
        polls = iter(
            [
                {
                    "progress": {
                        "event_id": "ev-1",
                        "stage": "processing",
                        "next_action": "step two",
                        "thought": {"focus": "思考中"},
                        "finalized": False,
                        "terminal": False,
                    }
                },
                {
                    "progress": {
                        "event_id": "ev-1",
                        "stage": "complete",
                        "status": "completed",
                        "finalized": True,
                        "terminal": True,
                    },
                    "thread": _snapshot(
                        "thread-1", ("user", "干活"), ("zn", "干完了")
                    ),
                },
            ]
        )
        client.on("work_progress", lambda params: next(polls))
        session, out, err, _ = self.make_session(client, ["干活"])
        self.assertEqual(session.run(), 0, err.getvalue())
        self.assertEqual(out.getvalue().count("处理中"), 1)
        self.assertIn("干完了", out.getvalue())

    def test_terminal_error_is_humanized(self):
        client = _StubClient()
        client.on("work_create", lambda params: {"id": "thread-1"})
        client.on(
            "work_start",
            lambda params: {
                "thread": _snapshot("thread-1"),
                "progress": {
                    "event_id": "ev-1",
                    "stage": "processing",
                    "finalized": False,
                    "terminal": False,
                },
            },
        )
        client.on(
            "work_progress",
            lambda params: {
                "progress": {
                    "event_id": "ev-1",
                    "stage": "failed",
                    "finalized": False,
                    "terminal": True,
                    "error": "resident event is terminal but no durable "
                    "work outcome is available",
                }
            },
        )
        session, out, err, _ = self.make_session(client, ["会失败的活"])
        self.assertEqual(session.run(), 0)
        self.assertIn("这一轮没能完成", err.getvalue())
        self.assertIn("下一步", err.getvalue())


# ---------------------------------------------------------------------------
# Wiring tests: zn_cli.run() over a fake resident socket
# ---------------------------------------------------------------------------


class _FakeStream:
    def __init__(self) -> None:
        self.lines: list[bytes] = []

    def readline(self) -> bytes:
        if not self.lines:
            return b""
        return self.lines.pop(0)


class _FakeSocket:
    """Speaks the resident newline-JSON protocol against a scripted handler."""

    def __init__(self, handler) -> None:
        self.handler = handler
        self.stream = _FakeStream()
        self.sent: list[dict] = []
        self.closed = False

    def settimeout(self, _timeout) -> None:
        pass

    def makefile(self, _mode):
        return self.stream

    def sendall(self, data: bytes) -> None:
        for line in data.decode("utf-8").splitlines():
            if not line.strip():
                continue
            request = json.loads(line)
            self.sent.append(request)
            if request.get("method") == "authenticate":
                ok = request.get("params", {}).get("secret") == _SECRET
                self.stream.lines.append(
                    json.dumps(
                        {
                            "id": request.get("id"),
                            "ok": ok,
                            "error": None if ok else "authentication failed",
                            "result": {"authenticated": ok},
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                continue
            outcome = self.handler(request.get("method"), request.get("params") or {})
            if isinstance(outcome, Exception):
                raise outcome
            if isinstance(outcome, tuple):
                ok, result, error = outcome
            else:
                ok, result, error = True, outcome, None
            self.stream.lines.append(
                json.dumps(
                    {"id": request.get("id"), "ok": ok, "result": result, "error": error}
                ).encode("utf-8")
                + b"\n"
            )

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False


def _chat_daemon(calls: list):
    def handle(method, params):
        calls.append((method, params))
        if method == "work_create":
            return {"id": "thread-1", "title": params.get("title")}
        if method == "work_start":
            return {
                "thread": {"id": "thread-1", "messages": []},
                "progress": {
                    "event_id": "ev-1",
                    "stage": "queued",
                    "finalized": False,
                    "terminal": False,
                },
            }
        if method == "work_progress":
            return {
                "progress": {
                    "event_id": "ev-1",
                    "stage": "complete",
                    "status": "completed",
                    "finalized": True,
                    "terminal": True,
                },
                "thread": {
                    "id": "thread-1",
                    "messages": [
                        {"role": "user", "text": "打个招呼"},
                        {"role": "assistant", "text": "你好，我是 ZN"},
                    ],
                },
            }
        raise AssertionError(f"unexpected RPC method {method!r}")

    return handle


class ZnChatWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.endpoint_path = Path(self.tmp.name) / "resident-endpoint.json"
        payload = {
            "version": 2,
            "transport": "tcp",
            "host": "127.0.0.1",
            "port": 59999,
            "authentication": {"scheme": "session-secret-v1", "secret": _SECRET},
        }
        self.endpoint_path.write_text(json.dumps(payload), encoding="utf-8")
        self.calls: list = []

    def _run_chat(self, argv, inputs):
        def connect(_address, timeout=None):
            return _FakeSocket(_chat_daemon(self.calls))

        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch("socket.create_connection", side_effect=connect), (
            mock.patch(
                "builtins.input", side_effect=[*inputs, EOFError]
            )
        ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = run(["--endpoint", str(self.endpoint_path), *argv])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_zn_chat_subcommand_runs_repl_over_rpc(self):
        code, out, err = self._run_chat(["chat"], ["打个招呼"])
        self.assertEqual(code, 0, err)
        self.assertIn("你好，我是 ZN", out)
        self.assertEqual(
            [method for method, _ in self.calls],
            ["work_create", "work_start", "work_progress"],
        )

    def test_bare_zn_enters_chat(self):
        code, out, err = self._run_chat([], ["打个招呼"])
        self.assertEqual(code, 0, err)
        self.assertIn("你好，我是 ZN", out)
        self.assertEqual(self.calls[0][0], "work_create")

    def test_chat_without_resident_is_a_readable_error(self):
        missing = Path(self.tmp.name) / "no-such-endpoint.json"
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = run(["--endpoint", str(missing), "chat"])
        self.assertEqual(code, 1)
        self.assertIn("zn: error:", stderr.getvalue())
        self.assertIn("does not appear to be running", stderr.getvalue())


class ChatSessionResumeTests(_SessionCase):
    """/resume: attach the REPL to the most recent existing thread.

    Decision (T15): explicit /resume only, no auto-attach at startup --
    a fresh REPL always begins empty, like ``claude -c`` / Codex
    ``resume --last`` which are opt-in, never default.
    """

    def resume_client(self, *, fail=False, empty=False, malformed=False):
        client = self.basic_client()

        def work_list(params):
            if fail:
                raise CliError("resident down (fake work_list failure)")
            if empty:
                return []
            if malformed:
                return {"oops": True}
            # Newest first, as the daemon orders work_list by updated_at DESC.
            return [
                {"id": "thread-new", "title": "昨天的天气讨论", "messages": []},
                {"id": "thread-old", "title": "更早的事", "messages": []},
            ]

        client.on("work_list", work_list)
        return client

    def test_resume_attaches_most_recent_thread(self):
        client = self.resume_client()
        session, out, err, _ = self.make_session(client, ["/resume"])
        self.assertEqual(session.run(), 0, err.getvalue())
        self.assertEqual(session.thread_id, "thread-new")
        self.assertEqual(client.calls[0], ("work_list", {"limit": 1}))
        text = out.getvalue()
        self.assertIn("thread-new", text)
        self.assertIn("昨天的天气讨论", text)
        self.assertNotIn("thread-old", text)
        self.assertEqual(err.getvalue(), "")

    def test_resume_twice_reports_already_there(self):
        client = self.resume_client()
        session, out, err, _ = self.make_session(client, ["/resume", "/resume"])
        self.assertEqual(session.run(), 0, err.getvalue())
        self.assertEqual(session.thread_id, "thread-new")
        self.assertIn("已经在最近的会话里了", out.getvalue())
        self.assertEqual(client.methods().count("work_list"), 2)

    def test_followup_after_resume_continues_same_thread(self):
        client = self.resume_client()
        session, out, err, _ = self.make_session(client, ["/resume", "那明天呢"])
        self.assertEqual(session.run(), 0, err.getvalue())
        self.assertEqual(client.methods().count("work_create"), 0)
        starts = [p for m, p in client.calls if m == "work_start"]
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0]["thread_id"], "thread-new")
        self.assertEqual(starts[0]["task"], "那明天呢")
        self.assertIn("done:ev-那明天呢", out.getvalue())

    def test_resume_then_new_opens_fresh_thread(self):
        client = self.resume_client()
        session, out, err, _ = self.make_session(client, ["/resume", "/new", "换个话题"])
        self.assertEqual(session.run(), 0, err.getvalue())
        self.assertEqual(client.methods().count("work_create"), 1)
        starts = [p for m, p in client.calls if m == "work_start"]
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0]["thread_id"], "thread-1")
        self.assertIn("开新会话", out.getvalue())

    def test_resume_failure_falls_back_to_new_thread(self):
        client = self.resume_client(fail=True)
        session, out, err, _ = self.make_session(client, ["/resume"])
        self.assertEqual(session.run(), 0, err.getvalue())
        # Falls back to new-thread behaviour: no crash, nothing attached.
        self.assertIsNone(session.thread_id)
        message = err.getvalue()
        self.assertIn("最近的会话没恢复出来", message)
        self.assertIn("work_list", message)

    def test_turn_after_failed_resume_creates_new_thread(self):
        client = self.resume_client(fail=True)
        session, out, err, _ = self.make_session(client, ["/resume", "直接说事"])
        self.assertEqual(session.run(), 0, err.getvalue())
        self.assertEqual(client.methods().count("work_create"), 1)
        starts = [p for m, p in client.calls if m == "work_start"]
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0]["thread_id"], "thread-1")
        self.assertIn("done:ev-直接说事", out.getvalue())

    def test_resume_failure_keeps_existing_thread(self):
        client = self.resume_client(fail=True)
        session, out, err, _ = self.make_session(client, ["先说一句", "/resume"])
        self.assertEqual(session.run(), 0, err.getvalue())
        # A failed /resume must not destroy the live conversation.
        self.assertEqual(session.thread_id, "thread-1")
        self.assertIn("最近的会话没恢复出来", err.getvalue())

    def test_resume_with_empty_history_stays_new(self):
        client = self.resume_client(empty=True)
        session, out, err, _ = self.make_session(client, ["/resume"])
        self.assertEqual(session.run(), 0, err.getvalue())
        self.assertIsNone(session.thread_id)
        self.assertIn("还没有历史会话", out.getvalue())
        self.assertEqual(err.getvalue(), "")

    def test_resume_with_malformed_work_list_result_stays_new(self):
        client = self.resume_client(malformed=True)
        session, out, err, _ = self.make_session(client, ["/resume"])
        self.assertEqual(session.run(), 0, err.getvalue())
        self.assertIsNone(session.thread_id)
        self.assertIn("还没有历史会话", out.getvalue())
        self.assertEqual(err.getvalue(), "")

    def test_piped_input_never_calls_work_list(self):
        # Non-TTY behaviour is unchanged: no auto-attach at startup.
        client = self.resume_client()
        session, out, err, read = self.make_session(
            client, ["管道里的一句"], interactive=False
        )
        self.assertEqual(session.run(), 0, err.getvalue())
        self.assertNotIn("work_list", client.methods())
        self.assertEqual(client.methods().count("work_create"), 1)
        self.assertEqual(read.prompts, ["", ""])  # one read per line plus the EOF read
        self.assertNotIn("ZN 会话模式", out.getvalue())
        self.assertIn("done:ev-管道里的一句", out.getvalue())

    def test_piped_resume_command_still_works(self):
        # Typing /resume explicitly through a pipe is honoured like any line.
        client = self.resume_client()
        session, out, err, _ = self.make_session(
            client, ["/resume"], interactive=False
        )
        self.assertEqual(session.run(), 0, err.getvalue())
        self.assertEqual(session.thread_id, "thread-new")


if __name__ == "__main__":
    unittest.main()
