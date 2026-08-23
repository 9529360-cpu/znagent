from __future__ import annotations

import plistlib
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.resident_autostart import (
    _MAC_LABEL,
    _WINDOWS_TASK_NS,
    _launch_agent_payload,
    _linux_unit,
    _resident_argv,
    _windows_task_xml,
)


class ResidentAutostartTests(unittest.TestCase):
    def test_resident_command_pins_python_and_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "ZN Home"
            python = Path(tmp) / "runtime" / "python"
            argv = _resident_argv(home, python)

            self.assertEqual(argv[0], str(python.resolve()))
            self.assertEqual(argv[1:4], ["-m", "zn_agent.core.resident_server", "--home"])
            self.assertEqual(argv[4], str(home.resolve()))

    def test_resident_server_home_option_pins_process_home(self):
        from zn_agent.core import resident_server

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "Pinned Home"
            fake_rpc = object()
            with patch.dict(os.environ, {}, clear=False), patch(
                "zn_agent.core.daemon.ResidentRpcServer", return_value=fake_rpc
            ) as rpc_factory, patch.object(
                resident_server, "ResidentSocketService"
            ) as service_factory:
                service_factory.return_value.serve_forever.return_value = 0
                result = resident_server.main(
                    [
                        "--home",
                        str(home),
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "43210",
                    ]
                )

                self.assertEqual(result, 0)
                self.assertEqual(os.environ["ZN_AGENT_HOME"], str(home.resolve()))
                rpc_factory.assert_called_once_with()
                service_factory.assert_called_once_with(
                    fake_rpc,
                    host="127.0.0.1",
                    port=43210,
                    channel_adapters=(),
                )

    def test_linux_unit_starts_at_login_and_has_bounded_failure_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "ZN Home"
            python = Path(tmp) / "Python Runtime" / "python3"
            unit = _linux_unit(home, python)

            self.assertIn("WantedBy=default.target", unit)
            self.assertIn("Restart=on-failure", unit)
            self.assertIn("RestartSec=5", unit)
            self.assertIn("StartLimitIntervalSec=300", unit)
            self.assertIn("StartLimitBurst=5", unit)
            self.assertIn(str(python.resolve()), unit)
            self.assertIn(str(home.resolve()), unit)
            self.assertIn("zn_agent.core.resident_server", unit)
            self.assertNotIn("agent.kernel.resident_server", unit)
            self.assertNotIn("WorkingDirectory=", unit)

    def test_macos_launch_agent_is_login_loaded_and_restarts_only_after_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "ZN Home"
            python = Path(tmp) / "runtime" / "python3"
            payload = _launch_agent_payload(home, python)
            round_trip = plistlib.loads(plistlib.dumps(payload))

            self.assertEqual(round_trip["Label"], _MAC_LABEL)
            self.assertTrue(round_trip["RunAtLoad"])
            self.assertEqual(round_trip["KeepAlive"], {"SuccessfulExit": False})
            self.assertEqual(round_trip["ThrottleInterval"], 5)
            self.assertEqual(round_trip["ProgramArguments"][0], str(python.resolve()))
            self.assertEqual(
                round_trip["ProgramArguments"][1:3],
                ["-m", "zn_agent.core.resident_server"],
            )
            self.assertEqual(round_trip["ProgramArguments"][-1], str(home.resolve()))
            self.assertNotIn("WorkingDirectory", round_trip)

    def test_windows_task_is_current_user_login_with_bounded_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "ZN Home"
            python = Path(tmp) / "runtime" / "python.exe"
            xml = _windows_task_xml(
                home,
                python,
                user_id="TEST\\resident-user",
            )
            root = ET.fromstring(xml)
            ns = {"t": _WINDOWS_TASK_NS}

            logon_user = root.findtext("t:Triggers/t:LogonTrigger/t:UserId", namespaces=ns)
            run_level = root.findtext("t:Principals/t:Principal/t:RunLevel", namespaces=ns)
            restart_count = root.findtext(
                "t:Settings/t:RestartOnFailure/t:Count",
                namespaces=ns,
            )
            command = root.findtext("t:Actions/t:Exec/t:Command", namespaces=ns)
            arguments = root.findtext("t:Actions/t:Exec/t:Arguments", namespaces=ns)
            working_directory = root.findtext("t:Actions/t:Exec/t:WorkingDirectory", namespaces=ns)

            self.assertEqual(logon_user, "TEST\\resident-user")
            self.assertEqual(run_level, "LeastPrivilege")
            self.assertEqual(restart_count, "5")
            self.assertEqual(command, str(python.resolve()))
            self.assertIn("zn_agent.core.resident_server", arguments or "")
            self.assertNotIn("agent.kernel.resident_server", arguments or "")
            self.assertIn("--home", arguments or "")
            self.assertIn(str(home.resolve()), arguments or "")
            self.assertIsNone(working_directory)


if __name__ == "__main__":
    unittest.main()
