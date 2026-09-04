from __future__ import annotations

import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from zn_agent.core.automation_text_state_sense import NativeFocusedAutomationTextSense
from zn_agent.core.cognitive_resource import CognitiveIncrement, CognitiveResourceWorkerFactory
from zn_agent.core.models import ModelRoute
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


class _BrowserGoalProposalResource:
    """Deterministic cognition fixture: understanding only, never browser authority."""

    def __init__(self):
        self.calls = 0

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        self.calls += 1
        return CognitiveIncrement(
            text=json.dumps(
                {
                    "kind": "user_browser_named_text",
                    "target_name": _TARGET_NAME,
                    "text": _TEXT,
                }
            ),
            provider="e2e-cognition",
            model="bounded-language-fixture",
        )


class WindowsInteractiveUserBrowserNamedGoalE2ETests(unittest.TestCase):
    @staticmethod
    def _require_input_desktop() -> None:
        WindowsInteractiveUserBrowserBridgeProviderE2ETests._require_input_desktop()

    def test_natural_work_is_understood_then_finds_types_and_verifies(self) -> None:
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
            cognition = _BrowserGoalProposalResource()
            resident.kernel.reconfigure_resources(
                routes=[
                    ModelRoute(
                        route_id="e2e-browser-language-understanding",
                        provider="fixture",
                        model="bounded-language-fixture",
                        capabilities={"language_understanding": 1.0, "general": 0.8},
                    )
                ],
                worker_factory=CognitiveResourceWorkerFactory(
                    resource_builder=lambda _route: cognition,
                ),
                max_attempts=1,
                resource_status={"available": True, "error": None},
            )
            fixture.activate()

            named_before = resident.browser_named_target.probe_exact_edit(_TARGET_NAME)
            self.assertFalse(
                named_before.has_keyboard_focus,
                "fixture must prove ZN—not the user/test—has to acquire target focus",
            )

            event = resident.enqueue(
                f"In my current browser, put {_TEXT} in {_TARGET_NAME}.",
                kind="desktop_user_event",
                payload={"model_policy": "on_demand"},
            )

            result = None
            deadline = time.monotonic() + 20.0
            while time.monotonic() < deadline and result is None:
                fixture.activate()
                result = resident.live_once()
                if result is None:
                    time.sleep(0.05)

            self.assertIsNotNone(result, "natural user-browser goal did not reach a terminal result")
            self.assertTrue(result.success, result)
            self.assertEqual(result.event.event_id, event.event_id)
            self.assertEqual(result.model_invocations, 1)
            self.assertEqual(cognition.calls, 1)

            persisted = resident.store.get_event(event.event_id)
            self.assertEqual(
                persisted.payload.get("resident_goal"),
                {
                    "kind": "user_browser_named_text",
                    "target_name": _TARGET_NAME,
                    "text": _TEXT,
                },
            )
            understanding = persisted.payload.get("_resident_goal_understanding") or {}
            self.assertEqual(understanding.get("source"), "bounded_cognition_proposal")

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
                if item.event_id == event.event_id
            ]
            self.assertEqual(sum(1 for item in actions if item.kind == "pointer_click"), 1)
            self.assertEqual(sum(1 for item in actions if item.kind == "keyboard_text"), 1)
            progress = resident.store.get_working_state().data.get("resident_goal_progress") or []
            self.assertGreaterEqual(len(progress), 2)

            print(
                "ZN_USER_BROWSER_NATURAL_GOAL_EVIDENCE="
                + json.dumps(
                    {
                        "provider": provider,
                        "profile_scope": "isolated-temporary",
                        "task_ingress": "ordinary-desktop-user-text",
                        "goal_understanding": "bounded-cognition-proposal",
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
