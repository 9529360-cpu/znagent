"""TEMPORARY diagnostic: capture what os.kill(live_pid, 0) actually does on GH Windows runner.

DELETE BEFORE MERGE. This exists only to gather evidence for the _pid_is_dead()
Windows misdiagnosis (endpoint stale false positive on live pids).
"""

import os
import unittest

from zn_agent.core import zn_cli


@unittest.skipUnless(os.name == "nt", "Windows-only diagnostic")
class TestWinPidDiagnostic(unittest.TestCase):
    def test_diagnose_os_kill_on_live_pid(self):
        live_pid = os.getpid()
        print(f"\n[diag-pid] live_pid={live_pid} os.name={os.name!r}")
        print(f"[diag-pid] sys.version check via os.sys? (skipped)")
        try:
            result = os.kill(live_pid, 0)
            print(f"[diag-pid] os.kill({live_pid}, 0) -> returned {result!r} (no exception)")
        except BaseException as exc:  # noqa: BLE001 - diagnostic must capture everything
            print(
                "[diag-pid] os.kill raised: "
                f"type={type(exc).__module__}.{type(exc).__name__} "
                f"args={exc.args!r} "
                f"errno={getattr(exc, 'errno', '<none>')!r} "
                f"winerror={getattr(exc, 'winerror', '<none>')!r} "
                f"strerror={getattr(exc, 'strerror', '<none>')!r}"
            )
        judged = zn_cli._pid_is_dead(live_pid)
        print(f"[diag-pid] _pid_is_dead({live_pid}) on LIVE pid -> {judged!r}")
        # Always passes: evidence only, no assertions about behavior.
        self.assertTrue(True)

    def test_diagnose_os_kill_on_guaranteed_dead_pid(self):
        # A very high pid is virtually certain not to exist; shows the dead path.
        dead_pid = 2147483646
        print(f"\n[diag-pid] probing guaranteed-dead pid={dead_pid}")
        try:
            result = os.kill(dead_pid, 0)
            print(f"[diag-pid] os.kill({dead_pid}, 0) -> returned {result!r} (no exception)")
        except BaseException as exc:  # noqa: BLE001 - diagnostic must capture everything
            print(
                "[diag-pid] os.kill raised: "
                f"type={type(exc).__module__}.{type(exc).__name__} "
                f"args={exc.args!r} "
                f"errno={getattr(exc, 'errno', '<none>')!r} "
                f"winerror={getattr(exc, 'winerror', '<none>')!r} "
                f"strerror={getattr(exc, 'strerror', '<none>')!r}"
            )
        judged = zn_cli._pid_is_dead(dead_pid)
        print(f"[diag-pid] _pid_is_dead({dead_pid}) on DEAD pid -> {judged!r}")
        self.assertTrue(True)
