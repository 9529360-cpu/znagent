from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.autonomy_policy import (
    OBSERVE_ONLY,
    REQUIRE_APPROVAL,
    SUGGEST,
    AutonomyPolicyStore,
)
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.provider_bridge import build_resident_runtime_from_existing_stack


class AutonomyRpcTests(unittest.TestCase):
    """T8: daemon autonomy_list/get/set RPCs wired to the policy store."""

    @staticmethod
    def _server(tmp: str):
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=Path(tmp) / "kernel.db",
        )
        server = ResidentRpcServer(
            resident=resident,
            input_stream=io.StringIO(),
            output_stream=io.StringIO(),
        )
        return resident, server

    def _ok(self, server, method, params):
        response = server.handle({"id": "1", "method": method, "params": params})
        self.assertTrue(response["ok"], response)
        return response["result"]

    def test_list_get_set_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, server = self._server(tmp)
            try:
                self.assertEqual(self._ok(server, "autonomy_list", {}), [])

                changed = self._ok(
                    server,
                    "autonomy_set",
                    {"domain": "connector.weather", "level": "suggest"},
                )
                self.assertEqual(changed["domain"], "connector.weather")
                self.assertEqual(changed["level"], "suggest")
                self.assertEqual(changed["old_level"], "require_approval")
                self.assertTrue(changed["updated_at"])

                got = self._ok(
                    server, "autonomy_get", {"domain": "connector.weather"}
                )
                self.assertEqual(
                    got, {"domain": "connector.weather", "level": "suggest"}
                )

                listed = self._ok(server, "autonomy_list", {})
                self.assertEqual(len(listed), 1)
                self.assertEqual(listed[0]["domain"], "connector.weather")
                self.assertEqual(listed[0]["level"], "suggest")
                self.assertTrue(listed[0]["updated_at"])

                # The change is traceable after the fact.
                audit = AutonomyPolicyStore(resident).list_policy_audit()
                self.assertEqual(len(audit), 1)
                self.assertEqual(audit[0]["domain"], "connector.weather")
                self.assertEqual(audit[0]["old_level"], "require_approval")
                self.assertEqual(audit[0]["new_level"], "suggest")
            finally:
                resident.store.close()

    def test_get_unknown_domain_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, server = self._server(tmp)
            try:
                got = self._ok(
                    server, "autonomy_get", {"domain": "connector.never_set"}
                )
                self.assertEqual(
                    got, {"domain": "connector.never_set", "level": "require_approval"}
                )
            finally:
                resident.store.close()

    def test_get_normalizes_and_rejects_bad_domains(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, server = self._server(tmp)
            try:
                got = self._ok(
                    server, "autonomy_get", {"domain": "  Connector.Weather "}
                )
                self.assertEqual(got["domain"], "connector.weather")

                for params in (
                    {},
                    {"domain": ""},
                    {"domain": "*"},
                    {"domain": "connector.*"},
                    {"domain": "connector.weather", "extra": 1},
                ):
                    with self.subTest(params=params):
                        with self.assertRaises(ValueError):
                            server.handle(
                                {"id": "1", "method": "autonomy_get", "params": params}
                            )
            finally:
                resident.store.close()

    def test_set_rejects_illegal_level_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, server = self._server(tmp)
            try:
                with self.assertRaises(ValueError) as caught:
                    server.handle(
                        {
                            "id": "1",
                            "method": "autonomy_set",
                            "params": {"domain": "connector.weather", "level": "yolo"},
                        }
                    )
                self.assertIn("unknown autonomy level", str(caught.exception))
                self.assertEqual(self._ok(server, "autonomy_list", {}), [])
                self.assertEqual(
                    AutonomyPolicyStore(resident).list_policy_audit(), []
                )
            finally:
                resident.store.close()

    def test_set_rejects_wildcard_domain_explicitly(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, server = self._server(tmp)
            try:
                with self.assertRaises(ValueError) as caught:
                    server.handle(
                        {
                            "id": "1",
                            "method": "autonomy_set",
                            "params": {"domain": "connector.*", "level": "suggest"},
                        }
                    )
                self.assertIn("wildcard", str(caught.exception))
                self.assertEqual(self._ok(server, "autonomy_list", {}), [])
            finally:
                resident.store.close()

    def test_set_requires_exact_params(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, server = self._server(tmp)
            try:
                for params in (
                    {},
                    {"domain": "connector.weather"},
                    {"level": "suggest"},
                    {"domain": "connector.weather", "level": "suggest", "x": 1},
                ):
                    with self.subTest(params=params):
                        with self.assertRaises(ValueError):
                            server.handle(
                                {"id": "1", "method": "autonomy_set", "params": params}
                            )
                self.assertEqual(self._ok(server, "autonomy_list", {}), [])
            finally:
                resident.store.close()

    def test_set_level_whitelist_is_strict_but_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, server = self._server(tmp)
            try:
                changed = self._ok(
                    server,
                    "autonomy_set",
                    {"domain": "recurring.interval", "level": "OBSERVE_ONLY"},
                )
                self.assertEqual(changed["level"], "observe_only")
                self.assertEqual(
                    self._ok(server, "autonomy_get", {"domain": "recurring.interval"})[
                        "level"
                    ],
                    "observe_only",
                )
            finally:
                resident.store.close()

    def test_list_rejects_params(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident, server = self._server(tmp)
            try:
                with self.assertRaises(ValueError):
                    server.handle(
                        {
                            "id": "1",
                            "method": "autonomy_list",
                            "params": {"limit": 5},
                        }
                    )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
