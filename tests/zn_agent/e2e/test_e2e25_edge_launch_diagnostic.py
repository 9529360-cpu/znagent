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
_MAX_CAPTURE_CHARS = 4000
_MAX_PROFILE_ENTRIES = 40


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


def _provider_pids(executable: Path) -> list[int]:
    expected_name = executable.name.casefold()
    found: list[int] = []
    for process in psutil.process_iter(["pid", "name"]):
        try:
            if str(process.info.get("name") or "").casefold() == expected_name:
                found.append(int(process.info.get("pid") or 0))
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    return sorted(pid for pid in found if pid > 0)


def _policy_snapshot(provider: str) -> list[dict[str, object]]:
    if os.name != "nt":
        return []
    import winreg

    relative = {
        "edge": r"Software\Policies\Microsoft\Edge",
        "chrome": r"Software\Policies\Google\Chrome",
    }.get(provider)
    if not relative:
        return []

    snapshots: list[dict[str, object]] = []
    roots = (("HKCU", winreg.HKEY_CURRENT_USER), ("HKLM", winreg.HKEY_LOCAL_MACHINE))
    for root_name, root in roots:
        try:
            with winreg.OpenKey(root, relative) as key:
                try:
                    value, value_type = winreg.QueryValueEx(key, "UserDataDir")
                except FileNotFoundError:
                    value, value_type = None, None
        except FileNotFoundError:
            value, value_type = None, None
        snapshots.append(
            {
                "scope": root_name,
                "user_data_dir_present": value is not None,
                "user_data_dir": str(value) if value is not None else None,
                "value_type": int(value_type) if value_type is not None else None,
            }
        )
    return snapshots


def _profile_materialization(profile: Path) -> dict[str, object]:
    entries: list[str] = []
    try:
        for path in sorted(profile.rglob("*"), key=lambda item: str(item).casefold()):
            if len(entries) >= _MAX_PROFILE_ENTRIES:
                break
            try:
                entries.append(path.relative_to(profile).as_posix() + ("/" if path.is_dir() else ""))
            except OSError:
                continue
    except OSError:
        pass
    markers = {
        "local_state": (profile / "Local State").is_file(),
        "singleton_lock": (profile / "SingletonLock").exists(),
        "singleton_cookie": (profile / "SingletonCookie").exists(),
        "singleton_socket": (profile / "SingletonSocket").exists(),
        "default_preferences": (profile / "Default" / "Preferences").is_file(),
        "first_run": (profile / "First Run").exists(),
    }
    return {"markers": markers, "entries": entries, "entry_count_capped": len(entries)}


def _capture_fixture_launch(*, provider: str, executable: Path, fixture, fixture_kind: str) -> dict[str, object]:
    repo_root = Path(__file__).resolve().parents[3]
    preexisting_pids = _provider_pids(executable)
    captured_process: subprocess.Popen[str] | None = None
    captured_args: list[str] = []
    real_popen = subprocess.Popen

    def diagnostic_popen(*args, **kwargs):
        nonlocal captured_process, captured_args
        raw_args = args[0] if args else kwargs.get("args")
        if isinstance(raw_args, (list, tuple)):
            instrumented = [str(item) for item in raw_args]
            if "--enable-logging=stderr" not in instrumented:
                instrumented.insert(1, "--enable-logging=stderr")
            if "--v=1" not in instrumented:
                instrumented.insert(2, "--v=1")
            captured_args = instrumented
            if args:
                args = (instrumented, *args[1:])
            else:
                kwargs["args"] = instrumented
        else:
            captured_args = [str(raw_args)]
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

        post_pids = _provider_pids(executable)
        new_provider_pids = sorted(set(post_pids) - set(preexisting_pids))
        policy = _policy_snapshot(provider)
        for snapshot in policy:
            value = snapshot.get("user_data_dir")
            if value:
                snapshot["user_data_dir"] = _bounded_sanitized_text(
                    str(value), fixture_root=fixture.root, repo_root=repo_root
                )
        evidence: dict[str, object] = {
            "provider": provider,
            "fixture_kind": fixture_kind,
            "executable": _bounded_sanitized_text(
                str(executable), fixture_root=fixture.root, repo_root=repo_root
            ),
            "policy": policy,
            "preexisting_provider_pids": preexisting_pids,
            "post_provider_pids": post_pids,
            "new_provider_pids": new_provider_pids,
            "root_pid": root_pid,
            "root_exit_code": root_exit_code,
            "fixture_hwnd": int(fixture.hwnd or 0),
            "fixture_window_pid": int(fixture.window_pid or 0),
            "profile_processes": _profile_processes(fixture.profile),
            "profile_materialization": _profile_materialization(fixture.profile),
            "launch_error": type(launch_error).__name__ if launch_error else None,
            "launch_error_message": str(launch_error or ""),
            "argv": [
                _bounded_sanitized_text(item, fixture_root=fixture.root, repo_root=repo_root)
                for item in captured_args
            ],
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
