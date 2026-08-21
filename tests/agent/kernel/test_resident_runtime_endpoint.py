from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent.kernel.daemon import ResidentRpcServer
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack
from agent.kernel.resident_server import ResidentSocketService, _process_runtime_id


class ResidentRuntimeEndpointTests(unittest.TestCase):
    def test_endpoint_reports_runtime_identity_and_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            endpoint_path = root / "resident-endpoint.json"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            rpc = ResidentRpcServer(resident=resident)
            service = ResidentSocketService(rpc, endpoint_path=endpoint_path)

            try:
                with mock.patch.dict(
                    os.environ,
                    {"ZN_RUNTIME_ID": "runtime-test-123"},
                    clear=False,
                ):
                    service._write_endpoint("127.0.0.1", 43123)

                payload = json.loads(endpoint_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["runtime_id"], "runtime-test-123")
                self.assertEqual(
                    Path(payload["python"]).resolve(),
                    Path(sys.executable).resolve(),
                )
                self.assertEqual(payload["instance_id"], rpc.service.instance_id)
            finally:
                service._remove_owned_endpoint()
                resident.store.close()

    def test_runtime_identity_falls_back_to_manifest_near_portable_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp) / "runtime-n-plus-1"
            python_path = runtime_root / "python" / "cpython" / "bin" / "python3"
            python_path.parent.mkdir(parents=True)
            python_path.write_text("fake python", encoding="utf-8")
            (runtime_root / "runtime.json").write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "product": "ZN",
                        "runtime_id": "runtime-n-plus-1",
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                _process_runtime_id(environ={}, python_executable=python_path),
                "runtime-n-plus-1",
            )


if __name__ == "__main__":
    unittest.main()
