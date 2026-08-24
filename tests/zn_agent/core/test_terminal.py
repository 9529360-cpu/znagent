from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.terminal import (
    TerminalRequest,
    ZNLocalTerminal,
    _bounded_output,
    _resolve_safe_cwd,
)


class ZNLocalTerminalTests(unittest.TestCase):
    def setUp(self):
        self.terminal = ZNLocalTerminal()

    def test_foreground_command_returns_real_exit_code_and_output(self):
        result = self.terminal.execute(TerminalRequest(command="printf 'hello-zn'"))
        self.assertTrue(result.success)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output, "hello-zn")
        self.assertEqual(result.status, "completed")

    def test_nonzero_exit_is_observed_not_masked_by_cwd_marker(self):
        result = self.terminal.execute(TerminalRequest(command="printf 'bad'; exit 7"))
        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, 7)
        self.assertEqual(result.output, "bad")

    def test_context_remembers_observed_cwd_across_fresh_shell_processes(self):
        with tempfile.TemporaryDirectory() as tmp:
            child = Path(tmp) / "child"
            child.mkdir()
            first = self.terminal.execute(
                TerminalRequest(
                    command=f'cd "{child.as_posix()}"',
                    context_id="ctx",
                    workdir=tmp,
                )
            )
            self.assertTrue(first.success)
            second = self.terminal.execute(
                TerminalRequest(command="pwd -W" if os.name == "nt" else "pwd -P", context_id="ctx")
            )
            self.assertTrue(second.success)
            self.assertEqual(Path(second.cwd or "").resolve(), child.resolve())
            self.assertEqual(Path(second.output.strip()).resolve(), child.resolve())

    def test_inherited_provider_secret_is_scrubbed_but_explicit_env_is_allowed(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "inherited-secret"}, clear=False):
            hidden = self.terminal.execute(
                TerminalRequest(command="printf '%s' \"${OPENAI_API_KEY-unset}\"")
            )
            explicit = self.terminal.execute(
                TerminalRequest(
                    command="printf '%s' \"${OPENAI_API_KEY-unset}\"",
                    env={"OPENAI_API_KEY": "explicit-secret"},
                )
            )
        self.assertEqual(hidden.output, "unset")
        self.assertEqual(explicit.output, "explicit-secret")

    def test_timeout_kills_foreground_process_tree(self):
        result = self.terminal.execute(
            TerminalRequest(command="sleep 5", timeout=0.1)
        )
        self.assertFalse(result.success)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.status, "timeout")

    def test_background_process_can_be_polled_to_completion(self):
        started = self.terminal.execute(
            TerminalRequest(command="printf 'background-ok'", background=True)
        )
        self.assertTrue(started.success)
        self.assertEqual(started.status, "running")
        self.assertTrue(started.session_id)

        final = None
        for _ in range(100):
            final = self.terminal.poll(started.session_id or "")
            if final.status != "running":
                break
            time.sleep(0.02)
        self.assertIsNotNone(final)
        self.assertEqual(final.status, "completed")
        self.assertTrue(final.success)
        self.assertEqual(final.output, "background-ok")

    def test_output_is_bounded_head_and_tail(self):
        rendered, truncated = _bounded_output("a" * 1000 + "z" * 1000, 256)
        self.assertTrue(truncated)
        self.assertLessEqual(len(rendered), 256)
        self.assertTrue(rendered.startswith("a"))
        self.assertTrue(rendered.endswith("z"))

    def test_missing_workdir_falls_back_to_existing_ancestor(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "gone" / "deeper"
            resolved = _resolve_safe_cwd(str(missing))
            self.assertEqual(Path(resolved).resolve(), Path(tmp).resolve())


if __name__ == "__main__":
    unittest.main()
