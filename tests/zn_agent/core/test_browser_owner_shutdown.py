from __future__ import annotations

import threading
import unittest

from zn_agent.core.browser_rpc import _BrowserOwner


class BrowserOwnerShutdownTests(unittest.TestCase):
    def test_close_rejects_new_work_before_provider_cleanup_finishes(self) -> None:
        owner = _BrowserOwner()
        cleanup_started = threading.Event()
        release_cleanup = threading.Event()
        provider_calls: list[tuple[str, int]] = []
        close_errors: list[BaseException] = []

        def cleanup() -> None:
            provider_calls.append(("close", threading.get_ident()))
            cleanup_started.set()
            if not release_cleanup.wait(timeout=5.0):
                raise RuntimeError("test timed out waiting to release browser cleanup")

        def close_owner() -> None:
            try:
                owner.close(cleanup)
            except BaseException as exc:
                close_errors.append(exc)

        closer = threading.Thread(target=close_owner, name="test-browser-close")
        closer.start()
        self.assertTrue(cleanup_started.wait(timeout=5.0))

        with self.assertRaisesRegex(RuntimeError, "owner is closed"):
            owner.call(
                lambda: provider_calls.append(("late-operation", threading.get_ident()))
            )

        release_cleanup.set()
        closer.join(timeout=5.0)
        self.assertFalse(closer.is_alive())
        self.assertEqual(close_errors, [])
        self.assertEqual([name for name, _ in provider_calls], ["close"])

        owner.close(lambda: provider_calls.append(("second-close", threading.get_ident())))
        self.assertEqual([name for name, _ in provider_calls], ["close"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
