from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from agent.kernel.daemon import ResidentRpcServer
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack
from agent.kernel.resident_server import ResidentSocketService
from agent.kernel.visual_sense import NativeVisualSense, VisualFrame


class PersistentVisualSenseTests(unittest.TestCase):
    @staticmethod
    def _frame(token: str) -> VisualFrame:
        return VisualFrame(
            frame_hash=(token * 64)[:64],
            width=320,
            height=180,
            source="test-screen",
        )

    @staticmethod
    def _structured_frame(
        token: str,
        regions: tuple[str, ...],
        *,
        luminance: float = 0.45,
    ) -> VisualFrame:
        return VisualFrame(
            frame_hash=(token * 64)[:64],
            width=320,
            height=180,
            source="test-structured-screen",
            region_signatures=regions,
            grid_columns=4,
            grid_rows=3,
            mean_luminance=luminance,
        )

    @staticmethod
    def _request(endpoint: dict, method: str, params: dict | None = None) -> dict:
        with socket.create_connection(
            (str(endpoint["host"]), int(endpoint["port"])),
            timeout=3.0,
        ) as client:
            client.settimeout(3.0)
            request = {
                "id": f"visual-{method}-{time.time_ns()}",
                "method": method,
                "params": params or {},
            }
            client.sendall((json.dumps(request) + "\n").encode("utf-8"))
            raw = client.makefile("rb").readline()
            if not raw:
                raise AssertionError("resident endpoint closed without a response")
            return json.loads(raw.decode("utf-8"))

    def test_frame_identity_survives_restart_without_duplicate_initial_percept(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            retina = NativeVisualSense(
                first,
                capture_fn=lambda: self._frame("a"),
                interval_seconds=0.1,
            )

            initial = retina.sample()
            self.assertIsNotNone(initial)
            self.assertTrue(initial.changed)
            first_visual = [
                trace for trace in first.nervous.recent_traces(50)
                if trace.channel == "vision" and trace.source == "resident-retina"
            ]
            self.assertEqual(len(first_visual), 1)
            initial_trace_id = first_visual[0].trace_id
            self.assertFalse(first_visual[0].metadata.get("raw_frame_persisted"))
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            same_retina = NativeVisualSense(
                second,
                capture_fn=lambda: self._frame("a"),
                interval_seconds=0.1,
            )
            unchanged = same_retina.sample()
            self.assertIsNotNone(unchanged)
            self.assertFalse(unchanged.changed)
            visual_after_same = [
                trace for trace in second.nervous.recent_traces(50)
                if trace.channel == "vision" and trace.source == "resident-retina"
            ]
            self.assertEqual([item.trace_id for item in visual_after_same], [initial_trace_id])

            changed_retina = NativeVisualSense(
                second,
                capture_fn=lambda: self._frame("b"),
                interval_seconds=0.1,
            )
            changed = changed_retina.sample()
            self.assertIsNotNone(changed)
            self.assertTrue(changed.changed)
            state = changed_retina.status()
            self.assertEqual(state.last_frame_hash, self._frame("b").frame_hash)
            self.assertEqual(state.sample_count, 3)
            self.assertEqual(state.change_count, 2)
            self.assertEqual(second.store.get_runtime_metrics().model_invocations, 0)
            second.store.close()

    def test_structured_regions_turn_local_change_into_lived_visual_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            base = tuple(f"region-{index}" for index in range(12))
            changed_regions = list(base)
            changed_regions[0] = "region-0-changed"
            changed_regions = tuple(changed_regions)

            retina = NativeVisualSense(
                resident,
                capture_fn=lambda: self._structured_frame(
                    "a",
                    base,
                    luminance=0.40,
                ),
                interval_seconds=0.1,
            )
            initial = retina.sample()
            self.assertIsNotNone(initial)
            self.assertEqual(initial.change_scale, "initial")

            retina.capture_fn = lambda: self._structured_frame(
                "b",
                changed_regions,
                luminance=0.55,
            )
            local = retina.sample()
            self.assertIsNotNone(local)
            self.assertTrue(local.changed)
            self.assertEqual(local.changed_region_indices, (0,))
            self.assertAlmostEqual(local.change_ratio, 1 / 12, places=5)
            self.assertEqual(local.change_scale, "local")
            self.assertAlmostEqual(local.luminance_delta, 0.15, places=5)

            # A raw frame hash may jitter because of cursor/antialiasing noise.
            # If the resident's quantized local structure is unchanged, that
            # noise should not become another lived screen-change event.
            retina.capture_fn = lambda: self._structured_frame(
                "c",
                changed_regions,
                luminance=0.56,
            )
            jitter = retina.sample()
            self.assertIsNotNone(jitter)
            self.assertFalse(jitter.changed)
            self.assertEqual(jitter.change_scale, "none")

            state = retina.status()
            self.assertEqual(state.sample_count, 3)
            self.assertEqual(state.change_count, 2)
            self.assertEqual(state.last_region_signatures, changed_regions)

            visual = [
                trace
                for trace in resident.nervous.recent_traces(100)
                if trace.channel == "vision"
                and trace.source == "resident-retina"
                and trace.metadata.get("change_scale") == "local"
            ]
            self.assertTrue(visual)
            trace = visual[-1]
            self.assertIn("visual_change:local", trace.features)
            self.assertIn("visual_area:top-left", trace.features)
            self.assertIn("luminance:brighter", trace.features)
            self.assertEqual(trace.metadata.get("changed_region_count"), 1)
            self.assertEqual(trace.metadata.get("changed_region_indices"), [0])
            self.assertFalse(trace.metadata.get("raw_frame_persisted"))
            self.assertEqual(resident.store.get_runtime_metrics().model_invocations, 0)
            resident.store.close()

    def test_structured_visual_state_survives_restart_and_filters_raw_hash_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            regions = tuple(f"stable-{index}" for index in range(12))
            first = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            first_retina = NativeVisualSense(
                first,
                capture_fn=lambda: self._structured_frame("a", regions),
                interval_seconds=0.1,
            )
            first_observation = first_retina.sample()
            self.assertIsNotNone(first_observation)
            self.assertTrue(first_observation.changed)
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            restored = NativeVisualSense(
                second,
                capture_fn=lambda: self._structured_frame("b", regions),
                interval_seconds=0.1,
            )
            observation = restored.sample()
            self.assertIsNotNone(observation)
            self.assertFalse(observation.changed)
            self.assertEqual(observation.change_scale, "none")
            state = restored.status()
            self.assertEqual(state.last_region_signatures, regions)
            self.assertEqual(state.sample_count, 2)
            self.assertEqual(state.change_count, 1)
            second.store.close()

    def test_socket_service_sees_screen_before_any_ui_client_connects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            endpoint_path = root / "resident-endpoint.json"
            resident = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            capture_count = 0
            capture_lock = threading.Lock()

            def capture() -> VisualFrame:
                nonlocal capture_count
                with capture_lock:
                    capture_count += 1
                    token = f"{capture_count:064x}"
                return VisualFrame(
                    frame_hash=token,
                    width=320,
                    height=180,
                    source="test-service-screen",
                )

            rpc = ResidentRpcServer(resident=resident, life_interval=0.05)
            service = ResidentSocketService(
                rpc,
                endpoint_path=endpoint_path,
                visual_capture_fn=capture,
                visual_interval=0.1,
            )
            thread = threading.Thread(
                target=service.serve_forever,
                name="test-persistent-vision",
                daemon=True,
            )
            thread.start()

            deadline = time.monotonic() + 5.0
            endpoint = None
            while time.monotonic() < deadline:
                if endpoint is None and endpoint_path.exists():
                    endpoint = json.loads(endpoint_path.read_text(encoding="utf-8"))
                with capture_lock:
                    samples = capture_count
                if endpoint is not None and samples >= 2:
                    break
                time.sleep(0.02)

            self.assertIsNotNone(endpoint)
            with capture_lock:
                self.assertGreaterEqual(capture_count, 2)

            # This neural query is the first UI-like client connection. Visual
            # traces must already exist because sensing belongs to the service.
            neural = self._request(endpoint, "neural", {"limit": 100})
            self.assertTrue(neural["ok"])
            self.assertTrue(
                any(
                    item.get("channel") == "vision"
                    and item.get("source") == "resident-retina"
                    for item in neural["result"]
                )
            )
            self.assertTrue(thread.is_alive())

            shutdown = self._request(endpoint, "shutdown")
            self.assertTrue(shutdown["ok"])
            thread.join(timeout=5.0)
            self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
