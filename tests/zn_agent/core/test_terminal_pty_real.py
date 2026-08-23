from __future__ import annotations

import os
import time
import unittest

from zn_agent.core.terminal import TerminalRequest, ZNLocalTerminal


@unittest.skipIf(os.name == "nt", "POSIX ptyprocess smoke runs on POSIX CI")
class RealPosixPtySmokeTests(unittest.TestCase):
    def test_foreground_real_pty_observes_output_and_exit_code(self):
        terminal = ZNLocalTerminal()
        result = terminal.execute(
            TerminalRequest(
                command="printf 'real-pty-ok'",
                pty=True,
                timeout=3.0,
            )
        )
        self.assertEqual(result.status, "completed")
        self.assertTrue(result.success)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("real-pty-ok", result.output)

    def test_background_real_pty_accepts_stdin_and_finishes(self):
        terminal = ZNLocalTerminal()
        started = terminal.execute(
            TerminalRequest(
                command="IFS= read -r line; printf 'got:%s' \"$line\"",
                pty=True,
                background=True,
            )
        )
        self.assertEqual(started.status, "running")
        session_id = started.session_id or ""

        # write_stdin is itself an observation boundary. A fast child may exit
        # while the write is being drained; in that case write_stdin returns the
        # terminal result and correctly reclaims the completed PTY immediately.
        # Poll only while the returned state says the session is still running.
        final = terminal.write_stdin(session_id, "hello-pty\n")
        for _ in range(100):
            if final.status != "running":
                break
            time.sleep(0.02)
            final = terminal.poll(session_id)

        self.assertEqual(final.status, "completed")
        self.assertTrue(final.success)
        self.assertEqual(final.exit_code, 0)
        self.assertIn("got:hello-pty", final.output)


if __name__ == "__main__":
    unittest.main()
