from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

import psutil

import test_windows_interactive_user_browser_extension as extension_fixture_module
from test_windows_interactive_user_browser_bridge import (
    _find_installed_browsers,
    WindowsInteractiveUserBrowserBridgeProviderE2ETests,
)
from test_windows_interactive_user_browser_extension import _ExtensionBrowserFixture


_TITLE = "ZN E2E25 Edge Launch Diagnostic"
_MAX_CAPTURE_CHARS = 2000


def _bounded_sanitized_text(value: str, *, fixture_root: Path, repo_root: Path) -> str:
    text = str(value or "")
    replacements = (
        (str(fixture_root), "<fixture-root>"),
        (str(repo_root), "<repo-root>"),
        (str(Path.home()), "<user-home>"),
    )
    for raw, replacement in replacements:
        if raw:
            text = text.replace(raw, replacement)
            text = text.replace(raw.replace("\\", "/"), replacement)
    if len(text) > _MAX_CAPTURE_CHARS:
        text = text[-_MAX_CAPTURE_CHARS:]
    return text


def _profile_processes(profile: Path) -> list[dict[str, object]]:
    marker = os.path.normcase(str(profile))
    matches: list[dict[str, object]] = []
    for process in psutil.process_iter(["pid", "ppid", "name", "cmdline"]):
        try:
            command = " ".join(process.info.get("cmdline") or [])
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        if marker not in os.path.normcase(command):
            continue
        matches.append(
            {
                "pid": int(process.info.get("pid") or 0),
                "ppid": int(process.info.get("ppid") or 0),
                "name": str(process.info.get("name") or ""),
            }
        )
    return sorted(matches, key=lambda item: int(item["pid"]))


class E2E25EdgeLaunchDiagnosticTests(unittest.TestCase):
    def test_current_extension_fixture_reports_edge_launch_failure_cause(self) -> None:
        WindowsInteractiveUserBrowserBridgeProviderE2ETests._require_input_desktop()
        edge_candidates = [
            executable
            for provider, executable in _find_installed_browsers()
            if provider == "edge"
        ]
        if not edge_candidates:
            self.fail("zn-interactive has no stable Microsoft Edge installation to diagnose")

        executable = edge_candidates[0]
        repo_root = Path(__file__).resolve().parents[3]
        extension = repo_root / "apps" / "desktop" / "browser-extension"
        fixture = _ExtensionBrowserFixture(
            "edge",
            executable,
            "about:blank",
            extension,
            window_title_marker=_TITLE,
        )
        fixture.page.write_text(
            f"<!doctype html><html><head><title>{_TITLE}</title></head><body>diagnostic</body></html>",
            encoding="utf-8",
        )
        fixture.url = fixture.page.as_uri()

        preexisting_edge_pids = sorted(
            int(process.info["pid"])
            for process in psutil.process_iter(["pid", "name"])
            if str(process.info.get("name") or "").casefold() == "msedge.exe"
        )

        captured_process: subprocess.Popen[str] | None = None
        real_popen = extension_fixture_module.subprocess.Popen

        def diagnostic_popen(*args, **kwargs):
            nonlocal captured_process
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.PIPE
            kwargs["text"] = True
            kwargs["encoding"] = "utf-8"
            kwargs["errors"] = "replace"
            captured_process = real_popen(*args, **kwargs)
            return captured_process

        launch_error: Exception | None = None
        stdout = ""
        stderr = ""
        try:
            extension_fixture_module.subprocess.Popen = diagnostic_popen
            try:
                fixture.start()
            except Exception as exc:  # Diagnostic lane must report the original fixture failure.
                launch_error = exc
            finally:
                extension_fixture_module.subprocess.Popen = real_popen

            root_exit_code = None
            root_pid = None
            if captured_process is not None:
                root_pid = int(captured_process.pid)
                root_exit_code = captured_process.poll()
                if root_exit_code is not None:
                    stdout, stderr = captured_process.communicate(timeout=2.0)

            evidence = {
                "provider": "edge",
                "preexisting_edge_pids": preexisting_edge_pids,
                "root_pid": root_pid,
                "root_exit_code": root_exit_code,
                "fixture_hwnd": int(fixture.hwnd or 0),
                "fixture_window_pid": int(fixture.window_pid or 0),
                "profile_processes": _profile_processes(fixture.profile),
                "launch_error": type(launch_error).__name__ if launch_error else None,
                "launch_error_message": str(launch_error or ""),
                "stdout_tail": _bounded_sanitized_text(
                    stdout,
                    fixture_root=fixture.root,
                    repo_root=repo_root,
                ),
                "stderr_tail": _bounded_sanitized_text(
                    stderr,
                    fixture_root=fixture.root,
                    repo_root=repo_root,
                ),
            }
            encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
            print("ZN_E2E25_EDGE_LAUNCH_DIAGNOSTIC=" + encoded, flush=True)

            if launch_error is not None:
                self.fail("current Edge extension fixture launch failed; diagnostic=" + encoded)
            self.assertNotEqual(int(fixture.hwnd or 0), 0)
            self.assertGreaterEqual(len(evidence["profile_processes"]), 1)
        finally:
            extension_fixture_module.subprocess.Popen = real_popen
            fixture.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
