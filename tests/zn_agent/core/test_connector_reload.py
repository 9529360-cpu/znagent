from __future__ import annotations

"""Q10: connector hot reload.

``connector_reload`` RPC re-reads ``connectors.yaml``, diffs it against
the live mount report, and applies only the delta — no daemon restart.
Acceptance, one test each:

1. enabling a connector then reloading mounts it;
2. disabling a connector then reloading unmounts it (tools detach);
3. a broken whitelist fails the reload but leaves the daemon and the
   other connectors untouched (fail closed);
4. a single connector's mount failure is recorded explicitly in the
   mount report without affecting the rest.
"""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.connector_autoattach import read_mount_report
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.open_meteo_connector import GEOCODING_ACTION_ID
from zn_agent.core.web_search_connector import (
    DEFAULT_INSTANCES,
    action_id_for_instance,
)


def _write_config(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


class ReloadTests(unittest.TestCase):
    """The real daemon reload path: ResidentRpcServer.connector_reload."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config_path = self.root / "connectors.yaml"
        _write_config(
            self.config_path,
            "connectors:\n  fx_rates:\n    enabled: true\n",
        )
        self._old_env = dict(os.environ)
        os.environ["ZN_CONNECTORS_CONFIG_PATH"] = str(self.config_path)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._old_env)
        self.tmp.cleanup()

    def _make_server(self) -> ResidentRpcServer:
        from zn_agent.core.provider_bridge import (
            build_resident_runtime_from_existing_stack,
        )

        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=self.root / "kernel.db",
        )
        return ResidentRpcServer(
            resident=resident,
            input_stream=io.StringIO(),
            output_stream=io.StringIO(),
        )

    def _reload(self, server: ResidentRpcServer) -> dict:
        return server.handle(
            {"id": "q10", "method": "connector_reload", "params": {}}
        )["result"]

    def _close(self, server: ResidentRpcServer) -> None:
        server.connector_report.detach_all()
        server.resident.store.close()

    @staticmethod
    def _by_name(result: dict) -> dict:
        return {c["name"]: c for c in result["connectors"]}

    def test_reload_mounts_newly_enabled_connector(self) -> None:
        server = self._make_server()
        try:
            fabric = server.resident.action_fabric
            self.assertIsNone(fabric.descriptor(GEOCODING_ACTION_ID))
            _write_config(
                self.config_path,
                "connectors:\n"
                "  fx_rates:\n    enabled: true\n"
                "  weather:\n    enabled: true\n",
            )
            result = self._reload(server)
            self.assertTrue(result["reload_ok"], result.get("error"))
            by_name = self._by_name(result)
            self.assertTrue(by_name["weather"]["approved"])
            self.assertTrue(by_name["weather"]["mounted"])
            self.assertTrue(by_name["fx_rates"]["mounted"])
            # The tools are on the resident's own Fabric now.
            self.assertIsNotNone(fabric.descriptor(GEOCODING_ACTION_ID))
            # The persisted mount report reflects the reload.
            payload = read_mount_report()
            self.assertIsNotNone(payload)
            self.assertTrue(self._by_name(payload)["weather"]["mounted"])
        finally:
            self._close(server)

    def test_reload_unmounts_disabled_connector(self) -> None:
        _write_config(
            self.config_path,
            "connectors:\n"
            "  fx_rates:\n    enabled: true\n"
            "  weather:\n    enabled: true\n",
        )
        server = self._make_server()
        try:
            fabric = server.resident.action_fabric
            self.assertIsNotNone(fabric.descriptor(GEOCODING_ACTION_ID))
            _write_config(
                self.config_path,
                "connectors:\n  fx_rates:\n    enabled: true\n",
            )
            result = self._reload(server)
            self.assertTrue(result["reload_ok"], result.get("error"))
            by_name = self._by_name(result)
            self.assertFalse(by_name["weather"]["approved"])
            self.assertFalse(by_name["weather"]["mounted"])
            self.assertTrue(by_name["fx_rates"]["mounted"])
            # Detach really removed the tools from the Fabric.
            self.assertIsNone(fabric.descriptor(GEOCODING_ACTION_ID))
        finally:
            self._close(server)

    def test_reload_bad_config_keeps_daemon_and_mounts(self) -> None:
        _write_config(
            self.config_path,
            "connectors:\n  weather:\n    enabled: true\n",
        )
        server = self._make_server()
        try:
            fabric = server.resident.action_fabric
            self.assertIsNotNone(fabric.descriptor(GEOCODING_ACTION_ID))
            _write_config(self.config_path, "connectors:\n  weather: true\n")
            result = self._reload(server)
            # Fail closed: the reload reports failure, nothing was
            # detached or mounted, the old report stays live.
            self.assertFalse(result["reload_ok"])
            self.assertIn("whitelist failed to load", str(result.get("error")))
            by_name = self._by_name(result)
            self.assertTrue(by_name["weather"]["mounted"])
            self.assertIsNotNone(fabric.descriptor(GEOCODING_ACTION_ID))
            # The daemon is still healthy: a fixed config reloads fine.
            _write_config(
                self.config_path,
                "connectors:\n  weather:\n    enabled: true\n",
            )
            again = self._reload(server)
            self.assertTrue(again["reload_ok"], again.get("error"))
            self.assertTrue(self._by_name(again)["weather"]["mounted"])
        finally:
            self._close(server)

    def test_reload_single_connector_failure_recorded(self) -> None:
        _write_config(
            self.config_path,
            "connectors:\n  weather:\n    enabled: true\n",
        )
        server = self._make_server()
        try:
            fabric = server.resident.action_fabric
            # caldav: 42 is not a mapping -> the calendar wire raises.
            _write_config(
                self.config_path,
                "connectors:\n"
                "  weather:\n    enabled: true\n"
                "  calendar:\n    enabled: true\n    caldav: 42\n",
            )
            result = self._reload(server)
            self.assertTrue(result["reload_ok"], result.get("error"))
            by_name = self._by_name(result)
            self.assertTrue(by_name["calendar"]["approved"])
            self.assertFalse(by_name["calendar"]["mounted"])
            self.assertIn(
                "calendar.caldav must be a mapping",
                by_name["calendar"]["reason"],
            )
            # The other connectors are unaffected.
            self.assertTrue(by_name["weather"]["mounted"])
            self.assertIsNotNone(fabric.descriptor(GEOCODING_ACTION_ID))
            # The failure is recorded explicitly in the persisted report.
            payload = read_mount_report()
            self.assertIsNotNone(payload)
            failed = self._by_name(payload)["calendar"]
            self.assertFalse(failed["mounted"])
            self.assertIn("calendar.caldav must be a mapping", failed["reason"])
        finally:
            self._close(server)

    def test_reload_changed_config_remounts(self) -> None:
        _write_config(
            self.config_path,
            "connectors:\n  web_search:\n    enabled: true\n",
        )
        server = self._make_server()
        try:
            fabric = server.resident.action_fabric
            old_action = action_id_for_instance(DEFAULT_INSTANCES[0])
            self.assertIsNotNone(fabric.descriptor(old_action))
            new_instance = "https://search.example.com"
            _write_config(
                self.config_path,
                "connectors:\n"
                "  web_search:\n"
                "    enabled: true\n"
                f"    instances: [{new_instance}]\n",
            )
            result = self._reload(server)
            self.assertTrue(result["reload_ok"], result.get("error"))
            by_name = self._by_name(result)
            self.assertTrue(by_name["web_search"]["mounted"])
            self.assertIn("1 configured SearXNG instance(s)", by_name["web_search"]["reason"])
            # Remount replaced the tools: the new instance is wired and
            # the old default instance's tools are gone (no duplicates).
            self.assertIsNotNone(
                fabric.descriptor(action_id_for_instance(new_instance))
            )
            self.assertIsNone(fabric.descriptor(old_action))
        finally:
            self._close(server)

    def test_reload_rejects_params(self) -> None:
        server = self._make_server()
        try:
            with self.assertRaises(ValueError):
                server.handle(
                    {"id": "q10-params", "method": "connector_reload", "params": {"x": 1}}
                )
        finally:
            self._close(server)


class ReloadCliTests(unittest.TestCase):
    def test_connector_reload_parser(self) -> None:
        from zn_agent.core.zn_cli import _cmd_connector_reload, build_parser

        parser = build_parser()
        args = parser.parse_args(["connector", "reload", "--json"])
        self.assertIs(args.func, _cmd_connector_reload)
        self.assertTrue(args.json)

    def test_connector_reload_daemon_unreachable(self) -> None:
        from zn_agent.core.zn_cli import build_parser

        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("ZN_CONNECTORS_CONFIG_PATH")
            os.environ["ZN_CONNECTORS_CONFIG_PATH"] = str(Path(tmp) / "connectors.yaml")
            try:
                parser = build_parser()
                args = parser.parse_args(
                    [
                        "--endpoint",
                        str(Path(tmp) / "no-such-endpoint.json"),
                        "connector",
                        "reload",
                    ]
                )
                args.timeout = 0.5
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    code = args.func(args)
            finally:
                if old is None:
                    del os.environ["ZN_CONNECTORS_CONFIG_PATH"]
                else:
                    os.environ["ZN_CONNECTORS_CONFIG_PATH"] = old
        self.assertEqual(code, 2)
        self.assertIn("daemon unreachable", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
