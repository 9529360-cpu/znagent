from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.kernel.body import NativeBody
from agent.kernel.terminal import TerminalRequest, TerminalResult, ZNLocalTerminal


class _FakePty:
    def __init__(self, *, pid: int = 4242, exit_code: int | None = 0):
        self.pid = pid
        self._alive = True
        self._exit_code = exit_code
        self.reads: list[bytes | None] = []
        self.writes: list[bytes] = []
        self.resizes: list[tuple[int, int]] = []
        self.closed = False
        self.marker = ""

    def is_alive(self) -> bool:
        return self._alive and not self.closed

    def read(self, timeout: float = 0.2) -> bytes | None:
        if self.reads:
            value = self.reads.pop(0)
            if value is None:
                self._alive = False
            return value
        return b"" if self.is_alive() else None

    def write(self, data: bytes) -> None:
        self.writes.append(bytes(data))

    def resize(self, cols: int, rows: int) -> None:
        self.resizes.append((cols, rows))

    def exit_code(self) -> int | None:
        return self._exit_code if not self.is_alive() else None

    def close(self) -> None:
        self.closed = True
        self._alive = False


class _PtyFactory:
    def __init__(self, pty: _FakePty):
        self.pty = pty
        self.calls: list[dict] = []

    def __call__(self, argv, *, cwd, env, cols, rows):
        script = str(argv[-1])
        match = re.search(r"(__ZN_CWD_[0-9a-f]+__)", script)
        if match:
            self.pty.marker = match.group(1)
        self.calls.append(
            {
                "argv": list(argv),
                "cwd": cwd,
                "env": dict(env),
                "cols": cols,
                "rows": rows,
            }
        )
        return self.pty


class ZNInteractiveTerminalTests(unittest.TestCase):
    def test_background_pty_returns_session_and_scrubs_inherited_secrets(self):
        pty = _FakePty()
        factory = _PtyFactory(pty)
        terminal = ZNLocalTerminal(pty_factory=factory)
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "do-not-leak", "PYTHONPATH": "/resident/import/root"},
            clear=False,
        ):
            result = terminal.execute(
                TerminalRequest(
                    command="printf ready",
                    pty=True,
                    background=True,
                    cols=132,
                    rows=40,
                    env={"EXPLICIT_VALUE": "ok"},
                )
            )

        self.assertTrue(result.success)
        self.assertEqual(result.status, "running")
        self.assertTrue((result.session_id or "").startswith("pty-"))
        self.assertEqual(result.pid, 4242)
        call = factory.calls[0]
        self.assertEqual((call["cols"], call["rows"]), (132, 40))
        self.assertNotIn("OPENAI_API_KEY", call["env"])
        self.assertNotIn("PYTHONPATH", call["env"])
        self.assertEqual(call["env"]["EXPLICIT_VALUE"], "ok")
        self.assertTrue(pty.marker)

    def test_interactive_stdin_and_resize_use_same_session(self):
        pty = _FakePty()
        terminal = ZNLocalTerminal(pty_factory=_PtyFactory(pty))
        started = terminal.execute(
            TerminalRequest(command="cat", pty=True, background=True)
        )
        session_id = started.session_id or ""

        written = terminal.write_stdin(session_id, "hello\n")
        resized = terminal.resize(session_id, cols=100, rows=31)

        self.assertEqual(pty.writes, [b"hello\n"])
        self.assertEqual(pty.resizes, [(100, 31)])
        self.assertEqual(written.session_id, session_id)
        self.assertEqual(resized.session_id, session_id)
        self.assertEqual(written.status, "running")

    def test_poll_drains_output_strips_marker_and_updates_context_cwd(self):
        pty = _FakePty(exit_code=0)
        terminal = ZNLocalTerminal(pty_factory=_PtyFactory(pty))
        with tempfile.TemporaryDirectory() as tmp:
            child = Path(tmp) / "child"
            child.mkdir()
            started = terminal.execute(
                TerminalRequest(
                    command="pwd",
                    context_id="interactive",
                    workdir=tmp,
                    pty=True,
                    background=True,
                )
            )
            marker = pty.marker
            pty.reads.extend(
                [
                    f"terminal-output\r\n{marker}{child}\r\n".encode(),
                    None,
                ]
            )

            result = terminal.poll(started.session_id or "")

            self.assertEqual(result.status, "completed")
            self.assertTrue(result.success)
            self.assertEqual(result.exit_code, 0)
            self.assertIn("terminal-output", result.output)
            self.assertNotIn(marker, result.output)
            self.assertEqual(Path(result.cwd or "").resolve(), child.resolve())
            self.assertEqual(
                Path(terminal.context_cwd("interactive") or "").resolve(),
                child.resolve(),
            )
            self.assertTrue(pty.closed)

    def test_stop_closes_and_forgets_interactive_session(self):
        pty = _FakePty()
        terminal = ZNLocalTerminal(pty_factory=_PtyFactory(pty))
        started = terminal.execute(
            TerminalRequest(command="sleep 999", pty=True, background=True)
        )
        session_id = started.session_id or ""

        stopped = terminal.stop(session_id)

        self.assertEqual(stopped.status, "stopped")
        self.assertFalse(stopped.success)
        self.assertTrue(pty.closed)
        with self.assertRaises(KeyError):
            terminal.poll(session_id)

    def test_large_pty_stream_is_bounded_and_keeps_final_cwd_marker(self):
        pty = _FakePty(exit_code=0)
        terminal = ZNLocalTerminal(pty_factory=_PtyFactory(pty))
        with tempfile.TemporaryDirectory() as tmp:
            started = terminal.execute(
                TerminalRequest(
                    command="large-output",
                    context_id="large",
                    workdir=tmp,
                    pty=True,
                    background=True,
                    max_output_chars=256,
                )
            )
            marker = pty.marker
            pty.reads.extend(
                [
                    b"a" * 9000
                    + f"\n{marker}{tmp}\n".encode(),
                    None,
                ]
            )

            result = terminal.poll(started.session_id or "")

            self.assertTrue(result.truncated)
            self.assertLessEqual(len(result.output), 256)
            self.assertNotIn(marker, result.output)
            self.assertEqual(Path(result.cwd or "").resolve(), Path(tmp).resolve())

    def test_foreground_pty_completes_with_observed_exit_code(self):
        pty = _FakePty(exit_code=7)
        factory = _PtyFactory(pty)

        original_call = factory.__call__

        def configured_factory(argv, *, cwd, env, cols, rows):
            spawned = original_call(argv, cwd=cwd, env=env, cols=cols, rows=rows)
            spawned.reads.extend([b"failed-output", None])
            return spawned

        terminal = ZNLocalTerminal(pty_factory=configured_factory)
        result = terminal.execute(
            TerminalRequest(command="exit 7", pty=True, timeout=1.0)
        )

        self.assertEqual(result.status, "completed")
        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, 7)
        self.assertEqual(result.output, "failed-output")
        self.assertTrue(pty.closed)


class _FakeTerminalService:
    def __init__(self):
        self.input_calls = []
        self.resize_calls = []

    def write_stdin(self, session_id, data):
        self.input_calls.append((session_id, data))
        return TerminalResult(
            status="running",
            command="interactive",
            success=True,
            session_id=session_id,
        )

    def resize(self, session_id, *, cols, rows):
        self.resize_calls.append((session_id, cols, rows))
        return TerminalResult(
            status="running",
            command="interactive",
            success=True,
            session_id=session_id,
        )


class NativeBodyInteractiveTerminalTests(unittest.TestCase):
    def test_body_exposes_terminal_input_and_resize_actions(self):
        fake = _FakeTerminalService()
        body = NativeBody()
        with patch("agent.kernel.body.get_zn_local_terminal", return_value=fake):
            written = body.act(
                "terminal_input",
                session_id="pty-1",
                data="yes\n",
            )
            resized = body.act(
                "terminal_resize",
                session_id="pty-1",
                cols=120,
                rows=44,
            )

        self.assertTrue(written.success)
        self.assertTrue(resized.success)
        self.assertEqual(fake.input_calls, [("pty-1", "yes\n")])
        self.assertEqual(fake.resize_calls, [("pty-1", 120, 44)])
        self.assertEqual(written.data["session_id"], "pty-1")


if __name__ == "__main__":
    unittest.main()
