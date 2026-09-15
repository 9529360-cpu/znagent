from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

import psutil

import test_windows_interactive_user_browser_bridge as bridge_fixture_module
import test_windows_interactive_user_browser_extension as extension_fixture_module


_TITLE = "ZN E2E25 Browser Launch Diagnostic"
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


def _preexisting_provider_pids(executable: Path) -> list[int]:
    expected_name = executable.name.casefold()
    found: list[int] = []
    for process in psutil.process_iter(["pid", "name"]):
        try:
            if str(process.info.get("name") or "").casefold() == expected_name:
                found.append(int(process.info.get("pid") or 0))
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    return sorted(pid for pid in found if pid > 0)


def _capture_fixture_launch(*, provider: str, executable: Path, fixture, fixture_kind: str) -> dict[str, object]:
    repo_root = Path(__file__).resolve().parents[3]
    preexisting_pids = _preexisting_provider_pids(executable)
    captured_process: subprocess.Popen[str] | None = None
    real_popen = subprocess.Popen

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
        subprocess.Popen = diagnostic_popen  # type: ignore[assignment]
        try:
            fixture.start()
        except Exception as exc:  # Diagnostic lane records the original fixture failure.
            launch_error = exc
        finally:
            subprocess.Popen = real_popen  # type: ignore[assignment]

        root_exit_code = None
        root_pid = None
        if captured_process is not None:
            root_pid = int(captured_process.pid)
            root_exit_code = captured_process.poll()
            if root_exit_code is not None:
                stdout, stderr = captured_process.communicate(timeout=2.0)

        evidence: dict[str, object] = {
            "provider": provider,
            "fixture_kind": fixture_kind,
            "preexisting_provider_pids": preexisting_pids,
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
        print(
            "ZN_E2E25_BROWSER_LAUNCH_DIAGNOSTIC="
            + json.dumps(evidence, ensure_ascii=False, sort_keys=True),
            flush=True,
        )
        return evidence
    finally:
        subprocess.Popen = real_popen  # type: ignore[assignment]
        fixture.close()


class E2E25BrowserLaunchDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        bridge_fixture_module.WindowsInteractiveUserBrowserBridgeProviderE2ETests._require_input_desktop()
        cls.browsers = bridge_fixture_module._find_installed_browsers()
        cls.repo_root = Path(__file__).resolve().parents[3]
        cls.extension = cls.repo_root / "apps" / "desktop" / "browser-extension"

    def _candidate(self, provider: str) -> Path:
        candidates = [
            executable
            for current_provider, executable in self.browsers
            if current_provider == provider
        ]
        if not candidates:
            self.skipTest(f"zn-interactive has no stable {provider} installation to diagnose")
        return candidates[0]

    def _extension_fixture(self, provider: str, executable: Path):
        fixture = extension_fixture_module._ExtensionBrowserFixture(
            provider,
            executable,
            "about:blank",
            self.extension,
            window_title_marker=f"{_TITLE} {provider}",
        )
        fixture.page.write_text(
            "<!doctype html><html><head><title>"
            + f"{_TITLE} {provider}"
            + "</title></head><body>diagnostic</body></html>",
            encoding="utf-8",
        )
        fixture.url = fixture.page.as_uri()
        return fixture

    def test_01_edge_base_fixture_records_launch_state(self) -> None:
        executable = self._candidate("edge")
        fixture = bridge_fixture_module._IsolatedUserBrowserFixture(
            "edge",
            executable,
            window_title_marker=f"{_TITLE} edge base",
        )
        evidence = _capture_fixture_launch(
            provider="edge",
            executable=executable,
            fixture=fixture,
            fixture_kind="base",
        )
        self.assertIsNotNone(evidence["root_pid"])

    def test_02_edge_extension_fixture_records_launch_state(self) -> None:
        executable = self._candidate("edge")
        evidence = _capture_fixture_launch(
            provider="edge",
            executable=executable,
            fixture=self._extension_fixture("edge", executable),
            fixture_kind="extension",
        )
        self.assertIsNotNone(evidence["root_pid"])

    def test_03_chrome_extension_fixture_records_launch_state(self) -> None:
        executable = self._candidate("chrome")
        evidence = _capture_fixture_launch(
            provider="chrome",
            executable=executable,
            fixture=self._extension_fixture("chrome", executable),
            fixture_kind="extension",
        )
        self.assertIsNotNone(evidence["root_pid"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
