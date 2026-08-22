from __future__ import annotations

import unittest

from agent.kernel.terminal import TerminalRequest, ZNLocalTerminal


class _CompletingPty:
    def __init__(
        self,
        *,
        exit_code: int = 0,
        complete_on_write: bool = False,
        complete_on_resize: bool = False,
    ):
        self.pid = 5252
        self._alive = True
        self._exit_code = exit_code
        self.complete_on_write = complete_on_write
        self.complete_on_resize = complete_on_resize
        self.closed = False
        self.writes: list[bytes] = []
        self.resizes: list[tuple[int, int]] = []

    def is_alive(self) -> bool:
        return self._alive and not self.closed

    def read(self, timeout: float = 0.2) -> bytes | None:
        return b"" if self.is_alive() else None

    def write(self, data: bytes) -> None:
        self.writes.append(bytes(data))
        if self.complete_on_write:
            self._alive = False

    def resize(self, cols: int, rows: int) -> None:
        self.resizes.append((cols, rows))
        if self.complete_on_resize:
            self._alive = False

    def exit_code(self) -> int | None:
        return None if self.is_alive() else self._exit_code

    def close(self) -> None:
        self.closed = True
        self._alive = False


class _Factory:
    def __init__(self, pty: _CompletingPty):
        self.pty = pty

    def __call__(self, argv, *, cwd, env, cols, rows):
        return self.pty


class CompletedPtyCleanupTests(unittest.TestCase):
    def test_write_stdin_finalizes_session_that_completes_during_write(self):
        pty = _CompletingPty(exit_code=7, complete_on_write=True)
        terminal = ZNLocalTerminal(pty_factory=_Factory(pty))
        started = terminal.execute(
            TerminalRequest(command="interactive", pty=True, background=True)
        )
        session_id = started.session_id or ""

        result = terminal.write_stdin(session_id, "finish\n")

        self.assertEqual(result.status, "completed")
        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, 7)
        self.assertEqual(pty.writes, [b"finish\n"])
        self.assertTrue(pty.closed)
        with self.assertRaises(KeyError):
            terminal.poll(session_id)

    def test_resize_finalizes_session_that_completes_during_resize(self):
        pty = _CompletingPty(exit_code=0, complete_on_resize=True)
        terminal = ZNLocalTerminal(pty_factory=_Factory(pty))
        started = terminal.execute(
            TerminalRequest(command="interactive", pty=True, background=True)
        )
        session_id = started.session_id or ""

        result = terminal.resize(session_id, cols=120, rows=44)

        self.assertEqual(result.status, "completed")
        self.assertTrue(result.success)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(pty.resizes, [(120, 44)])
        self.assertTrue(pty.closed)
        with self.assertRaises(KeyError):
            terminal.poll(session_id)

    def test_late_interaction_observes_completed_session_without_touching_pty(self):
        pty = _CompletingPty(exit_code=0)
        terminal = ZNLocalTerminal(pty_factory=_Factory(pty))
        started = terminal.execute(
            TerminalRequest(command="interactive", pty=True, background=True)
        )
        session_id = started.session_id or ""
        pty._alive = False

        result = terminal.write_stdin(session_id, "too-late")

        self.assertEqual(result.status, "completed")
        self.assertTrue(result.success)
        self.assertEqual(pty.writes, [])
        self.assertTrue(pty.closed)
        with self.assertRaises(KeyError):
            terminal.resize(session_id, cols=80, rows=24)


if __name__ == "__main__":
    unittest.main()
