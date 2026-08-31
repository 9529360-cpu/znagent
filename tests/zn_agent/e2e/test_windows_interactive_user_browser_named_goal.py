from __future__ import annotations

import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from zn_agent.core.automation_text_state_sense import NativeFocusedAutomationTextSense
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime

from test_windows_interactive_user_browser_bridge import (
    _IsolatedUserBrowserFixture,
    _find_installed_browsers,
    WindowsInteractiveUserBrowserBridgeProviderE2ETests,
)


_TARGET_NAME = "Account search"
_TEXT = "alice@example.test"


class _NamedTargetBrowserFixture(_IsolatedUserBrowserFixture):
    """Installed browser page whose requested Edit is visible but initially unfocused."""

    def start(self) -> None:
        self.page.write_text(
            f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>ZN User Browser Bridge E2E</title>
  <style>
    html, body {{ height: 100%; margin: 0; }}
    body {{ display: grid; place-items: center; font-family: sans-serif; }}
    main {{ display: grid; gap: 24px; width: 720px; }}
    button, input {{ padding: 18px; font-size: 24px; }}
  </style>
</head>
<body>
  <main>
    <button id="initial-focus" autofocus>Initial focus</button>
    <input id="account-search" aria-label="{_TARGET_NAME}" type="text" value="" autocomplete="off">
  </main>
</body>
</html>
""",
            encoding="utf-8",
        )
        args = [
            str(self.executable),
            f"--user-data-dir={self.profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-mode",
            f"--app={self.page.as_uri()}",
        ]
        if self.provider == "edge":
            args.insert(4, "--disable-features=msEdgeFirstRunExperience")
        self.process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"{self.provider} exited before named browser fixture opened")
            match = self._find_fixture_window()
            if match is not None:
                self.hwnd, self.window_pid, self.window_title = match
                self.activate()
                return
            time.sleep(0.05)
        raise RuntimeError(f"{self.provider} did not expose named browser fixture in time")


class WindowsInteractiveUserBrowserNamedGoalE2ETests(unittest.TestCase):
    @staticmethod
    def _require_input_desktop() -> None:
        WindowsInteractiveUserBrowserBridgeProviderE2ETests._require_input_desktop()

    def test_real_work_rpc_finds_unfocused_named_edit_then_types_and_verifies(self) -> None:
        self._require_input_desktop()
        browsers = _find_installed_browsers()
        if not browsers:
            self.fail("interactive Windows runner has neither stable Edge nor Chrome")

        provider, executable = browsers[0]
        fixture = _NamedTargetBrowserFixture(provider, executable)
        resident = None
        runtime_tmp = None
        fixture.start()
        try:
            runtime_tmp = tempfile.TemporaryDirectory()
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(runtime_tmp.name) / "kernel.db",
            )
            rpc = ResidentRpcServer(resident=resident)
            fixture.activate()

            named_before = resident.browser_named_target.probe_exact_edit(_TARGET_NAME)
            self.assertFalse(
                named_before.has_keyboard_focus,
                "fixture must prove ZN—not the user/test—has to acquire target focus",
            )

            thread_id = "work-user-browser-named-goal"
            create = rpc.handle(
                {
                    "id": "create",
                    "method": "work_create",
                    "params": {"thread_id": thread_id, "title": "Browser work"},
                }
            )
            self.assertTrue(create["ok"], create)
            task = f'In my current browser, fill "{_TARGET_NAME}" with "{_TEXT}".'
            start = rpc.handle(
                {
                    "id": "start",
                    "method": "work_start",
                    "params": {
                        "thread_id": thread_id,
                        "task": task,
                        "kind": "desktop_user_event",
                        "priority": 0,
                        # This mirrors the real desktop: no resident_goal, body_action
                        # or native_action is supplied. `model_policy` only keeps the
                        # E2E's no-model expectation explicit.
                        "payload": {"model_policy": "never"},
                    },
                }
            )
            self.assertTrue(start["ok"], start)
            progress = start["result"]["progress"]
            event_id = str(progress["event_id"])
            event = resident.store.get_event(event_id)
            self.assertIsNotNone(event)
            self.assertNotIn("resident_goal", event.payload)
            self.assertEqual(event.kind, "desktop_user_event")
            self.assertEqual(event.task, task)

            result = None
            deadline = time.monotonic() + 20.0
            while time.monotonic() < deadline and result is None:
                fixture.activate()
                result = resident.live_once()
                if result is None:
                    time.sleep(0.05)

            self.assertIsNotNone(result, "named user-browser Work did not reach a terminal result")
            self.assertTrue(result.success, result)
            self.assertEqual(result.event.event_id, event_id)
            self.assertEqual(result.model_invocations, 0)

            final_progress = rpc.handle(
                {
                    "id": "progress",
                    "method": "work_progress",
                    "params": {"thread_id": thread_id, "event_id": event_id},
                }
            )
            self.assertTrue(final_progress["ok"], final_progress)
            self.assertTrue(final_progress["result"]["progress"]["terminal"])
            self.assertTrue(final_progress["result"]["progress"]["finalized"])

            named_after = resident.browser_named_target.probe_exact_edit(_TARGET_NAME)
            self.assertTrue(named_after.has_keyboard_focus)
            final_text = resident.automation_text_state.probe()
            self.assertEqual(tuple(final_text.runtime_id), tuple(named_after.runtime_id))
            self.assertEqual(final_text.text_length, len(_TEXT))
            self.assertEqual(
                final_text.text_sha256,
                NativeFocusedAutomationTextSense.digest_text(_TEXT),
            )

            actions = [
                item
                for item in resident.body.recent_actions(80)
                if item.event_id == event_id
            ]
            self.assertEqual(sum(1 for item in actions if item.kind == "pointer_click"), 1)
            self.assertEqual(sum(1 for item in actions if item.kind == "keyboard_text"), 1)

            print(
                "ZN_USER_BROWSER_NAMED_GOAL_EVIDENCE="
                + json.dumps(
                    {
                        "provider": provider,
                        "profile_scope": "isolated-temporary",
                        "ingress": "work_rpc",
                        "goal_source": "ordinary_work",
                        "target_name": _TARGET_NAME,
                        "initially_focused": False,
                        "final_text_chars": final_text.text_length,
                        "pointer_clicks": sum(1 for item in actions if item.kind == "pointer_click"),
                        "keyboard_text_actions": sum(
                            1 for item in actions if item.kind == "keyboard_text"
                        ),
                        "model_invocations": result.model_invocations,
                    },
                    sort_keys=True,
                )
            )
        finally:
            if resident is not None:
                close_browser = getattr(getattr(resident, "managed_browser", None), "close", None)
                if callable(close_browser):
                    close_browser()
                resident.store.close()
            if runtime_tmp is not None:
                runtime_tmp.cleanup()
            fixture.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
