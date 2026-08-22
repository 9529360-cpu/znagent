from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import plistlib
import socket
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Sequence

from .home import get_zn_home


_LINUX_UNIT_NAME = "zn-resident.service"
_MAC_LABEL = "ai.zn.resident"
_WINDOWS_TASK_NAME = "ZN Resident"
_WINDOWS_TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"


def _normalized_home(value: str | Path | None = None) -> Path:
    home = Path(value).expanduser() if value is not None else get_zn_home()
    return home.resolve()


def _runtime_workdir() -> Path:
    # Source checkout: repository root. Installed package: site-packages root.
    return Path(__file__).resolve().parents[2]


def _resident_argv(home: Path, python_executable: str | Path | None = None) -> list[str]:
    python = Path(python_executable or sys.executable).expanduser().resolve()
    return [
        str(python),
        "-m",
        "zn_agent.core.resident_server",
        "--home",
        str(_normalized_home(home)),
    ]


def _systemd_quote(value: str | Path) -> str:
    text = str(value).replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _linux_unit(home: Path, python_executable: str | Path | None = None) -> str:
    argv = _resident_argv(home, python_executable)
    command = " ".join(_systemd_quote(item) for item in argv)
    workdir = _systemd_quote(_runtime_workdir())
    return (
        "[Unit]\n"
        "Description=ZN Resident\n"
        "StartLimitIntervalSec=300\n"
        "StartLimitBurst=5\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={workdir}\n"
        f"ExecStart={command}\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "TimeoutStopSec=10\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _launch_agent_payload(
    home: Path,
    python_executable: str | Path | None = None,
) -> dict[str, object]:
    return {
        "Label": _MAC_LABEL,
        "ProgramArguments": _resident_argv(home, python_executable),
        "WorkingDirectory": str(_runtime_workdir()),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 5,
        "ProcessType": "Background",
    }


def _windows_user_id() -> str:
    username = os.environ.get("USERNAME") or getpass.getuser()
    domain = os.environ.get("USERDOMAIN")
    if domain and "\\" not in username:
        return f"{domain}\\{username}"
    return username


def _windows_task_xml(
    home: Path,
    python_executable: str | Path | None = None,
    *,
    user_id: str | None = None,
) -> bytes:
    ET.register_namespace("", _WINDOWS_TASK_NS)
    q = lambda name: f"{{{_WINDOWS_TASK_NS}}}{name}"
    user = str(user_id or _windows_user_id())
    argv = _resident_argv(home, python_executable)

    task = ET.Element(q("Task"), {"version": "1.4"})
    registration = ET.SubElement(task, q("RegistrationInfo"))
    ET.SubElement(registration, q("Description")).text = "Persistent ZN resident"

    triggers = ET.SubElement(task, q("Triggers"))
    logon = ET.SubElement(triggers, q("LogonTrigger"))
    ET.SubElement(logon, q("Enabled")).text = "true"
    ET.SubElement(logon, q("UserId")).text = user

    principals = ET.SubElement(task, q("Principals"))
    principal = ET.SubElement(principals, q("Principal"), {"id": "Author"})
    ET.SubElement(principal, q("UserId")).text = user
    ET.SubElement(principal, q("LogonType")).text = "InteractiveToken"
    ET.SubElement(principal, q("RunLevel")).text = "LeastPrivilege"

    settings = ET.SubElement(task, q("Settings"))
    ET.SubElement(settings, q("MultipleInstancesPolicy")).text = "IgnoreNew"
    ET.SubElement(settings, q("DisallowStartIfOnBatteries")).text = "false"
    ET.SubElement(settings, q("StopIfGoingOnBatteries")).text = "false"
    ET.SubElement(settings, q("StartWhenAvailable")).text = "true"
    ET.SubElement(settings, q("Enabled")).text = "true"
    ET.SubElement(settings, q("ExecutionTimeLimit")).text = "PT0S"
    restart = ET.SubElement(settings, q("RestartOnFailure"))
    ET.SubElement(restart, q("Interval")).text = "PT1M"
    ET.SubElement(restart, q("Count")).text = "5"

    actions = ET.SubElement(task, q("Actions"), {"Context": "Author"})
    execute = ET.SubElement(actions, q("Exec"))
    ET.SubElement(execute, q("Command")).text = argv[0]
    ET.SubElement(execute, q("Arguments")).text = subprocess.list2cmdline(argv[1:])
    ET.SubElement(execute, q("WorkingDirectory")).text = str(_runtime_workdir())

    return ET.tostring(task, encoding="utf-16", xml_declaration=True)


def _linux_unit_path() -> Path:
    config_home = os.getenv("XDG_CONFIG_HOME")
    root = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return root / "systemd" / "user" / _LINUX_UNIT_NAME


def _mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{_MAC_LABEL}.plist"


def _platform_key() -> str:
    name = platform.system().strip().lower()
    if name == "linux":
        return "linux"
    if name == "darwin":
        return "macos"
    if name == "windows":
        return "windows"
    return name or "unknown"


def _run(command: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [str(item) for item in command],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "command failed").strip()
        raise RuntimeError(f"{' '.join(command)}: {detail}")
    return completed


def _endpoint_path(home: Path) -> Path:
    return _normalized_home(home) / "kernel" / "resident-endpoint.json"


def resident_running(home: Path, *, timeout: float = 0.4) -> bool:
    try:
        payload = json.loads(_endpoint_path(home).read_text(encoding="utf-8"))
        host = str(payload.get("host") or "").strip()
        port = int(payload.get("port") or 0)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    if host not in {"127.0.0.1", "localhost", "::1"} or not (0 < port < 65536):
        return False

    request = b'{"id":"autostart-status","method":"ping","params":{}}\n'
    try:
        with socket.create_connection((host, port), timeout=max(0.05, float(timeout))) as sock:
            sock.settimeout(max(0.05, float(timeout)))
            sock.sendall(request)
            buffer = bytearray()
            while len(buffer) < 8192 and b"\n" not in buffer:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                buffer.extend(chunk)
        line = bytes(buffer).split(b"\n", 1)[0]
        response = json.loads(line.decode("utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    result = response.get("result") if isinstance(response, dict) else None
    return bool(response.get("ok") and isinstance(result, dict) and result.get("alive"))


def autostart_installed(*, system: str | None = None) -> bool:
    target = system or _platform_key()
    if target == "linux":
        return _linux_unit_path().is_file()
    if target == "macos":
        return _mac_plist_path().is_file()
    if target == "windows":
        result = _run(["schtasks", "/Query", "/TN", _WINDOWS_TASK_NAME], check=False)
        return result.returncode == 0
    return False


def install(home: Path) -> None:
    home = _normalized_home(home)
    target = _platform_key()
    running = resident_running(home)

    if target == "linux":
        path = _linux_unit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_linux_unit(home), encoding="utf-8")
        _run(["systemctl", "--user", "daemon-reload"])
        if running:
            _run(["systemctl", "--user", "enable", _LINUX_UNIT_NAME])
        else:
            _run(["systemctl", "--user", "enable", "--now", _LINUX_UNIT_NAME])
        return

    if target == "macos":
        path = _mac_plist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(plistlib.dumps(_launch_agent_payload(home), sort_keys=False))
        if not running:
            domain = f"gui/{os.getuid()}"
            _run(["launchctl", "bootout", f"{domain}/{_MAC_LABEL}"], check=False)
            _run(["launchctl", "bootstrap", domain, str(path)])
        return

    if target == "windows":
        xml = _windows_task_xml(home)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=".xml",
                delete=False,
            ) as handle:
                handle.write(xml)
                temporary_path = Path(handle.name)
            _run(
                [
                    "schtasks",
                    "/Create",
                    "/TN",
                    _WINDOWS_TASK_NAME,
                    "/XML",
                    str(temporary_path),
                    "/F",
                ]
            )
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        if not running:
            _run(["schtasks", "/Run", "/TN", _WINDOWS_TASK_NAME])
        return

    raise RuntimeError(f"resident autostart is not supported on {platform.system() or target}")


def uninstall() -> None:
    target = _platform_key()
    if target == "linux":
        path = _linux_unit_path()
        _run(["systemctl", "--user", "disable", "--now", _LINUX_UNIT_NAME], check=False)
        path.unlink(missing_ok=True)
        _run(["systemctl", "--user", "daemon-reload"], check=False)
        return
    if target == "macos":
        path = _mac_plist_path()
        domain = f"gui/{os.getuid()}"
        _run(["launchctl", "bootout", f"{domain}/{_MAC_LABEL}"], check=False)
        path.unlink(missing_ok=True)
        return
    if target == "windows":
        _run(["schtasks", "/End", "/TN", _WINDOWS_TASK_NAME], check=False)
        _run(["schtasks", "/Delete", "/TN", _WINDOWS_TASK_NAME, "/F"], check=False)
        return
    raise RuntimeError(f"resident autostart is not supported on {platform.system() or target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="zn-resident",
        description="Install or inspect the persistent ZN resident startup entry.",
    )
    parser.add_argument(
        "command",
        choices=("install", "uninstall", "status"),
        nargs="?",
        default="status",
    )
    parser.add_argument(
        "--home",
        default=None,
        help="ZN home directory; defaults to the platform ZN home.",
    )
    args = parser.parse_args(argv)
    home = _normalized_home(args.home)

    try:
        if args.command == "install":
            install(home)
            print(f"ZN resident autostart installed for {home}")
            return 0
        if args.command == "uninstall":
            uninstall()
            print("ZN resident autostart uninstalled")
            return 0

        running = resident_running(home)
        installed = autostart_installed()
        state = "running" if running else "stopped"
        startup = "installed" if installed else "not-installed"
        print(f"ZN resident: {state}; autostart: {startup}; home: {home}")
        return 0
    except RuntimeError as exc:
        print(f"zn-resident: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
