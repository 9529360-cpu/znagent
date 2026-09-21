from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime


class PresentationBodyTests(unittest.TestCase):
    def test_existing_resident_body_owns_pptx_create_and_inspect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "zn.db",
            )
            try:
                destination = root / "brief.pptx"
                created = resident.body.act(
                    "create_pptx_from_outline",
                    event_id="ppt-body-create",
                    destination_path=str(destination),
                    title="ZN Brief",
                    subtitle="Body-owned PPTX",
                    slides=[{"title": "Status", "bullets": ["Ready", "Verified"]}],
                )
                self.assertTrue(created.success, created.error)
                self.assertTrue(created.data["verified"])
                self.assertEqual(created.data["slide_count"], 2)

                inspected = resident.body.act(
                    "inspect_pptx",
                    event_id="ppt-body-inspect",
                    path=str(destination),
                )
                self.assertTrue(inspected.success, inspected.error)
                self.assertTrue(inspected.data["ready"])
                self.assertEqual(
                    [slide["texts"] for slide in inspected.data["slides"]],
                    [
                        ["ZN Brief", "Body-owned PPTX"],
                        ["Status", "Ready", "Verified"],
                    ],
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
