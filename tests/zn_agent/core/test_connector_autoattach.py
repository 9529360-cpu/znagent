from __future__ import annotations

import importlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from zn_agent.core import KernelStore
from zn_agent.core.action_execution import ActionExecutionRuntime, ActionRequest
from zn_agent.core.action_fabric import ActionFabricRegistry
from zn_agent.core.body import NativeBody
from zn_agent.core.connector_autoattach import (
    CONNECTOR_REGISTRY,
    DESCRIPTORS_BY_NAME,
    ConnectorMountReport,
    attach_approved_connectors,
    connector_config_path,
    describe_registry,
    evaluate_connector_status,
    load_connector_whitelist,
    mount_report_path,
    read_mount_report,
    write_mount_report,
)
from zn_agent.core.credential_isolation import CredentialValueDetected
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.mail_connector import LIST_ACTION_ID as MAIL_LIST_ACTION_ID
from zn_agent.core.mail_connector import MailError
from zn_agent.core.open_meteo_connector import (
    FORECAST_ACTION_ID,
    GEOCODING_ACTION_ID,
)
from zn_agent.core.web_search_connector import (
    DEFAULT_INSTANCES,
    action_id_for_instance,
)


def _write_config(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _mount_env(config_path: Path) -> dict[str, str]:
    return {"ZN_CONNECTORS_CONFIG_PATH": str(config_path)}


class RegistryTests(unittest.TestCase):
    def test_twelve_connectors_cover_r1_to_r12(self) -> None:
        self.assertEqual(len(CONNECTOR_REGISTRY), 12)
        self.assertEqual(len(DESCRIPTORS_BY_NAME), 12)
        self.assertEqual(
            [d.r_series for d in CONNECTOR_REGISTRY],
            [f"R{i}" for i in range(1, 13)],
        )

    def test_modules_and_entry_points_resolve(self) -> None:
        for descriptor in CONNECTOR_REGISTRY:
            module = importlib.import_module(descriptor.module_name)
            for fn_name in descriptor.attach_functions:
                self.assertTrue(
                    callable(getattr(module, fn_name, None)),
                    f"{descriptor.name}.{fn_name}",
                )
            if descriptor.register_function is not None:
                self.assertTrue(
                    callable(getattr(module, descriptor.register_function, None)),
                    f"{descriptor.name}.{descriptor.register_function}",
                )

    def test_describe_registry_shape(self) -> None:
        described = describe_registry()
        self.assertEqual(len(described), 12)
        names = [entry["name"] for entry in described]
        self.assertEqual(names, [d.name for d in CONNECTOR_REGISTRY])
        for entry in described:
            self.assertTrue(entry["planes"], entry["name"])
            for plane in entry["planes"]:
                self.assertIn(plane, ("read", "write"))
            self.assertIsInstance(entry["requires_credentials"], bool)


class WhitelistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _load(self, text: str | None) -> dict:
        path = self.root / "connectors.yaml"
        if text is not None:
            _write_config(path, text)
        return load_connector_whitelist(path)

    def test_missing_file_is_default_off(self) -> None:
        self.assertEqual(load_connector_whitelist(self.root / "nope.yaml"), {})

    def test_empty_file_is_default_off(self) -> None:
        self.assertEqual(self._load(""), {})

    def test_enabled_entry_parses(self) -> None:
        whitelist = self._load(
            "connectors:\n  weather:\n    enabled: true\n  mail:\n    enabled: false\n"
        )
        self.assertTrue(whitelist["weather"]["enabled"])
        self.assertFalse(whitelist["mail"]["enabled"])

    def test_unknown_connector_name_rejected(self) -> None:
        with self.assertRaises(ValueError) as caught:
            self._load("connectors:\n  frobnicate:\n    enabled: true\n")
        self.assertIn("unknown connector 'frobnicate'", str(caught.exception))

    def test_non_mapping_entry_rejected(self) -> None:
        with self.assertRaises(ValueError) as caught:
            self._load("connectors:\n  weather: true\n")
        self.assertIn("must be a mapping", str(caught.exception))

    def test_string_enabled_rejected(self) -> None:
        with self.assertRaises(ValueError) as caught:
            self._load('connectors:\n  weather:\n    enabled: "true"\n')
        self.assertIn("'enabled' must be true/false", str(caught.exception))

    def test_unknown_top_level_key_rejected(self) -> None:
        with self.assertRaises(ValueError) as caught:
            self._load("allowlist:\n  weather:\n    enabled: true\n")
        self.assertIn("unknown connector config keys", str(caught.exception))

    def test_wrong_version_rejected(self) -> None:
        with self.assertRaises(ValueError) as caught:
            self._load("version: 2\nconnectors:\n  weather:\n    enabled: true\n")
        self.assertIn("unsupported connector config version", str(caught.exception))

    def test_credential_shaped_value_refused(self) -> None:
        with self.assertRaises(CredentialValueDetected):
            self._load(
                "connectors:\n  mail:\n    enabled: true\n"
                "    account:\n      token: 'Bearer abcdefgh12345678'\n"
            )

    def test_credential_reference_allowed(self) -> None:
        whitelist = self._load(
            "connectors:\n  mail:\n    enabled: true\n"
            "    account:\n      credential_ref: 'provider:mail'\n"
        )
        self.assertEqual(
            whitelist["mail"]["account"]["credential_ref"], "provider:mail"
        )

    def test_config_path_follows_daemon_config(self) -> None:
        env = {"ZN_CONFIG_PATH": str(self.root / "custom" / "config.yaml")}
        self.assertEqual(
            connector_config_path(environ=env),
            self.root / "custom" / "connectors.yaml",
        )
        self.assertEqual(
            mount_report_path(environ=env),
            self.root / "custom" / "connectors-status.json",
        )

    def test_config_path_env_override(self) -> None:
        env = {"ZN_CONNECTORS_CONFIG_PATH": "~/x/connectors.yaml"}
        self.assertEqual(
            connector_config_path(environ=env),
            Path("~/x/connectors.yaml").expanduser(),
        )


class MountTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.fabric = ActionFabricRegistry()
        self.body = NativeBody(
            store=KernelStore(Path(self.tmp.name) / "kernel.db")
        )

    def tearDown(self) -> None:
        self.body.store.close()
        self.tmp.cleanup()

    def test_default_off_mounts_nothing(self) -> None:
        report = attach_approved_connectors(self.fabric, self.body, whitelist={})
        self.assertEqual(report.approved_count, 0)
        self.assertEqual(report.mounted_count, 0)
        for attempt in report.attempts:
            self.assertFalse(attempt.approved)
            self.assertFalse(attempt.mounted)
            self.assertIn("default off", attempt.reason)

    def test_weather_and_web_search_mount(self) -> None:
        report = attach_approved_connectors(
            self.fabric,
            self.body,
            whitelist={"weather": {"enabled": True}, "web_search": {"enabled": True}},
        )
        by_name = {a.name: a for a in report.attempts}
        self.assertTrue(by_name["weather"].mounted)
        self.assertTrue(by_name["web_search"].mounted)
        self.assertIn("read-only", by_name["weather"].reason)
        self.assertIsNotNone(self.fabric.descriptor(GEOCODING_ACTION_ID))
        self.assertIsNotNone(self.fabric.descriptor(FORECAST_ACTION_ID))
        self.assertIsNotNone(
            self.fabric.descriptor(action_id_for_instance(DEFAULT_INSTANCES[0]))
        )
        report.detach_all()

    def test_unapproved_connector_not_mounted(self) -> None:
        report = attach_approved_connectors(
            self.fabric, self.body, whitelist={"weather": {"enabled": True}}
        )
        by_name = {a.name: a for a in report.attempts}
        self.assertFalse(by_name["maps"].mounted)
        self.assertIsNone(self.fabric.descriptor("rest.osm_nominatim.geocode_address"))
        report.detach_all()

    def test_mail_without_account_reports_not_configured(self) -> None:
        report = attach_approved_connectors(
            self.fabric, self.body, whitelist={"mail": {"enabled": True}}
        )
        by_name = {a.name: a for a in report.attempts}
        attempt = by_name["mail"]
        self.assertTrue(attempt.mounted)
        self.assertIn("no mail account configured", attempt.reason)
        # The connector's own honest path: the tool is registered but refuses.
        self.assertIsNotNone(self.fabric.descriptor(MAIL_LIST_ACTION_ID))
        runtime = ActionExecutionRuntime(self.fabric, self.body)
        execution = runtime.execute(
            ActionRequest(MAIL_LIST_ACTION_ID, {}, event_id="evt-r13-mail-1")
        )
        self.assertFalse(execution.success)
        self.assertIn("no mail account configured", (execution.error or ""))
        report.detach_all()

    def test_mount_failure_is_recorded_not_raised(self) -> None:
        report = attach_approved_connectors(
            self.fabric,
            self.body,
            whitelist={"web_search": {"enabled": True, "instances": []}},
        )
        by_name = {a.name: a for a in report.attempts}
        attempt = by_name["web_search"]
        self.assertTrue(attempt.approved)
        self.assertFalse(attempt.mounted)
        self.assertIn("WebSearchError", attempt.reason)
        report.detach_all()

    def test_travel_queries_mounts_both_providers(self) -> None:
        report = attach_approved_connectors(
            self.fabric, self.body, whitelist={"travel_queries": {"enabled": True}}
        )
        by_name = {a.name: a for a in report.attempts}
        self.assertTrue(by_name["travel_queries"].mounted)
        self.assertIsNotNone(
            self.fabric.descriptor("rest.opensky_flights.get_departures")
        )
        self.assertIsNotNone(
            self.fabric.descriptor("rest.openprices_prices.query_prices")
        )
        report.detach_all()

    def test_report_serializes(self) -> None:
        report = attach_approved_connectors(
            self.fabric, self.body, whitelist={"weather": {"enabled": True}}
        )
        payload = report.to_dict()
        self.assertEqual(payload["approved"], 1)
        self.assertEqual(payload["mounted"], 1)
        self.assertEqual(len(payload["connectors"]), 12)
        # Round-trips through JSON (what the daemon persists/serves).
        json.dumps(payload)
        report.detach_all()


class MountReportFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_write_skipped_when_nothing_approved(self) -> None:
        report = ConnectorMountReport.empty("nope")
        self.assertIsNone(
            write_mount_report(report, self.root / "connectors-status.json")
        )
        self.assertFalse((self.root / "connectors-status.json").exists())

    def test_write_and_read_roundtrip(self) -> None:
        report = ConnectorMountReport(
            generated_at="2026-10-21T00:00:00+00:00",
            config_path=str(self.root / "connectors.yaml"),
            attempts=[],
        )
        from zn_agent.core.connector_autoattach import ConnectorMountAttempt

        report.attempts.append(
            ConnectorMountAttempt(
                name="weather",
                r_series="R1",
                approved=True,
                mounted=True,
                reason="attached",
                planes=("read",),
                requires_credentials=False,
            )
        )
        path = write_mount_report(report, self.root / "connectors-status.json")
        self.assertIsNotNone(path)
        loaded = read_mount_report(self.root / "connectors-status.json")
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded["mounted"], 1)
        self.assertEqual(loaded["connectors"][0]["name"], "weather")

    def test_corrupt_report_reads_as_absent(self) -> None:
        path = self.root / "connectors-status.json"
        path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(read_mount_report(path))
        self.assertIsNone(read_mount_report(self.root / "missing.json"))


class EvaluateStatusTests(unittest.TestCase):
    def test_offline_evaluation(self) -> None:
        status = evaluate_connector_status(
            whitelist={"weather": {"enabled": True}, "mail": {"enabled": True}},
            report=None,
        )
        by_name = {item["name"]: item for item in status}
        self.assertTrue(by_name["weather"]["approved"])
        self.assertIsNone(by_name["weather"]["readiness"])
        self.assertTrue(by_name["mail"]["approved"])
        self.assertIn("no mail account configured", by_name["mail"]["readiness"] or "")
        self.assertFalse(by_name["maps"]["approved"])
        self.assertIsNone(by_name["maps"]["last_mount"])

    def test_merges_last_daemon_report(self) -> None:
        fake_report = {
            "generated_at": "2026-10-21T00:00:00+00:00",
            "connectors": [
                {"name": "weather", "mounted": True, "reason": "attached"},
                {"name": "mail", "mounted": False, "reason": "MailError: boom"},
            ],
        }
        status = evaluate_connector_status(
            whitelist={"weather": {"enabled": True}, "mail": {"enabled": True}},
            report=fake_report,
        )
        by_name = {item["name"]: item for item in status}
        self.assertEqual(by_name["weather"]["last_mount"]["mounted"], True)
        self.assertEqual(by_name["mail"]["last_mount"]["mounted"], False)
        self.assertEqual(
            by_name["weather"]["last_mount_at"], "2026-10-21T00:00:00+00:00"
        )


class DaemonHookTests(unittest.TestCase):
    """The real daemon startup path: ResidentRpcServer mounts the whitelist."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config_path = self.root / "connectors.yaml"
        _write_config(
            self.config_path,
            "connectors:\n"
            "  weather:\n    enabled: true\n"
            "  web_search:\n    enabled: true\n"
            "  mail:\n    enabled: true\n",
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

    def test_daemon_start_mounts_approved_connectors(self) -> None:
        server = self._make_server()
        try:
            by_name = {a.name: a for a in server.connector_report.attempts}
            self.assertTrue(by_name["weather"].mounted)
            self.assertTrue(by_name["web_search"].mounted)
            self.assertTrue(by_name["mail"].mounted)
            self.assertIn("no mail account configured", by_name["mail"].reason)
            self.assertFalse(by_name["maps"].mounted)
            # The tools are on the resident's own Fabric now.
            fabric = server.resident.action_fabric
            self.assertIsNotNone(fabric.descriptor(GEOCODING_ACTION_ID))
            self.assertIsNotNone(
                fabric.descriptor(action_id_for_instance(DEFAULT_INSTANCES[0]))
            )
        finally:
            server.connector_report.detach_all()
            server.resident.store.close()

    def test_corrupt_whitelist_keeps_daemon_up_with_explicit_report(self) -> None:
        _write_config(self.config_path, "connectors:\n  weather: true\n")
        server = self._make_server()
        try:
            by_name = {a.name: a for a in server.connector_report.attempts}
            self.assertFalse(by_name["weather"].mounted)
            self.assertIn("whitelist failed to load", by_name["weather"].reason)
            # Nothing was mounted: the fabric has no connector tools.
            self.assertIsNone(
                server.resident.action_fabric.descriptor(GEOCODING_ACTION_ID)
            )
        finally:
            server.connector_report.detach_all()
            server.resident.store.close()

    def test_connector_status_rpc(self) -> None:
        server = self._make_server()
        try:
            result = server.handle(
                {"id": "r13-1", "method": "connector_status", "params": {}}
            )["result"]
            self.assertEqual(result["mounted"], 3)
            self.assertEqual(result["approved"], 3)
            by_name = {c["name"]: c for c in result["connectors"]}
            self.assertTrue(by_name["weather"]["mounted"])
            self.assertFalse(by_name["maps"]["approved"])
            with self.assertRaises(ValueError):
                server.handle(
                    {"id": "r13-2", "method": "connector_status", "params": {"x": 1}}
                )
        finally:
            server.connector_report.detach_all()
            server.resident.store.close()

    def test_status_file_written_next_to_config(self) -> None:
        server = self._make_server()
        try:
            status_path = self.root / "connectors-status.json"
            self.assertTrue(status_path.exists())
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["mounted"], 3)
        finally:
            server.connector_report.detach_all()
            server.resident.store.close()


class CliTests(unittest.TestCase):
    def test_connector_list(self) -> None:
        from zn_agent.core.zn_cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["connector", "list", "--json"])
        buf = io.StringIO()
        import contextlib

        with contextlib.redirect_stdout(buf):
            code = args.func(args)
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(len(payload), 12)
        self.assertEqual(payload[0]["name"], "weather")

    def test_connector_status_offline_config_error(self) -> None:
        import contextlib

        from zn_agent.core.zn_cli import build_parser

        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "connectors.yaml"
            bad.write_text("connectors:\n  nope:\n    enabled: true\n", encoding="utf-8")
            old = os.environ.get("ZN_CONNECTORS_CONFIG_PATH")
            os.environ["ZN_CONNECTORS_CONFIG_PATH"] = str(bad)
            try:
                parser = build_parser()
                args = parser.parse_args(
                    ["--endpoint", str(Path(tmp) / "no-such-endpoint.json"),
                     "connector", "status"]
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
        self.assertEqual(code, 3)
        self.assertIn("connector config error", buf.getvalue())

    def test_connector_status_offline_fallback(self) -> None:
        from zn_agent.core.zn_cli import build_parser

        parser = build_parser()
        args = parser.parse_args(
            ["--endpoint", str(Path(tempfile.gettempdir()) / "no-such-endpoint.json"),
             "connector", "status"]
        )
        args.timeout = 0.5
        buf = io.StringIO()
        import contextlib

        with contextlib.redirect_stdout(buf):
            code = args.func(args)
        self.assertEqual(code, 0)
        self.assertIn("daemon unreachable", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
