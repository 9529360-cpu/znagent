from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.windows_companion_work_context import (
    bind_windows_companion_work_context,
    bounded_windows_companion_work_context,
)
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


_CONTEXT_KEY = "windows_companion_start_context"


def _frame(**overrides):
    values = {
        "frame_version": "windows-companion-frame:v1",
        "fingerprint": "a" * 64,
        "session_fingerprint": "b" * 64,
        "power_fingerprint": "c" * 64,
        "network_fingerprint": "d" * 64,
        "display_fingerprint": "e" * 64,
        "foreground_fingerprint": "f" * 64,
        "foreground_process_id": 1234,
        "foreground_process_name": "fixture.exe",
        "foreground_window_handle": 987654,
        "monitor_count": 2,
        "has_non_loopback_network": True,
        "ac_status": "online",
        "input_desktop_openable": True,
        "observed_at": "2026-09-15T12:00:00Z",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _Graph:
    def __init__(self, frame=None, *, error: Exception | None = None):
        self.frame = frame if frame is not None else _frame()
        self.error = error
        self.calls = 0

    def companion_frame(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.frame


class WindowsCompanionWorkContextTests(unittest.TestCase):
    def test_projection_is_bounded_historical_evidence_without_hwnd_authority(self) -> None:
        context = bounded_windows_companion_work_context(_frame())

        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context["frame_version"], "windows-companion-frame:v1")
        self.assertEqual(context["foreground"]["process_id"], 1234)
        self.assertEqual(context["foreground"]["process_name"], "fixture.exe")
        self.assertEqual(context["monitor_count"], 2)
        self.assertTrue(context["network_available"])
        self.assertFalse(context["execution_authority"])
        self.assertTrue(context["fresh_revalidation_required"])
        self.assertNotIn("window_handle", repr(context))
        self.assertNotIn("987654", repr(context))
        self.assertNotIn("title", repr(context))
        self.assertNotIn("class_name", repr(context))
        self.assertNotIn("clipboard", repr(context))

    def test_binding_replaces_spoofed_caller_context_with_fresh_resident_frame(self) -> None:
        payload = {
            _CONTEXT_KEY: {
                "foreground": {"process_name": "spoof.exe"},
                "execution_authority": True,
            },
            "caller_field": "preserved",
        }
        graph = _Graph()

        bound = bind_windows_companion_work_context(
            payload,
            device_capabilities=graph,
        )

        self.assertEqual(graph.calls, 1)
        self.assertIs(bound, payload[_CONTEXT_KEY])
        self.assertEqual(payload["caller_field"], "preserved")
        self.assertEqual(bound["foreground"]["process_name"], "fixture.exe")
        self.assertFalse(bound["execution_authority"])
        self.assertNotIn("spoof.exe", repr(payload))

    def test_unavailable_or_invalid_frame_removes_spoof_without_blocking_work(self) -> None:
        for graph in (
            _Graph(error=RuntimeError("foreground disappeared")),
            _Graph(_frame(foreground_process_id=None)),
            _Graph(_frame(fingerprint="not-a-fingerprint")),
        ):
            with self.subTest(graph=graph):
                payload = {_CONTEXT_KEY: {"execution_authority": True}}
                bound = bind_windows_companion_work_context(
                    payload,
                    device_capabilities=graph,
                )
                self.assertIsNone(bound)
                self.assertNotIn(_CONTEXT_KEY, payload)

    def test_product_work_start_persists_exact_bounded_start_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                graph = _Graph()
                resident.device_capabilities = graph
                ledger = RecoveryBoundedWorkLedger(resident)
                ledger.create_thread(thread_id="work-windows-start-context")

                _, event = ledger.start(
                    "work-windows-start-context",
                    "keep this Work bound to its starting desktop context",
                    payload={
                        _CONTEXT_KEY: {
                            "foreground": {"process_name": "spoof.exe"},
                            "execution_authority": True,
                        },
                        "caller_field": "preserved",
                    },
                )
                persisted = resident.store.get_event(event.event_id)
                self.assertIsNotNone(persisted)
                assert persisted is not None

                context = persisted.payload.get(_CONTEXT_KEY)
                self.assertIsInstance(context, dict)
                self.assertEqual(context["fingerprint"], "a" * 64)
                self.assertEqual(context["foreground"]["process_name"], "fixture.exe")
                self.assertFalse(context["execution_authority"])
                self.assertTrue(context["fresh_revalidation_required"])
                self.assertEqual(persisted.payload.get("caller_field"), "preserved")
                self.assertNotIn("foreground_window_handle", repr(context))
                self.assertNotIn("spoof.exe", repr(persisted.payload))
            finally:
                resident.store.close()

    def test_active_steering_captures_a_fresh_context_for_the_new_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                graph = _Graph()
                resident.device_capabilities = graph
                control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
                control.ledger.create_thread(thread_id="work-windows-steer-context")

                _, original = control.start(
                    "work-windows-steer-context",
                    "build the first bounded plan",
                    payload={"caller_field": "original"},
                )
                first = resident.store.get_event(original.event_id)
                self.assertIsNotNone(first)
                assert first is not None
                first_context = first.payload.get(_CONTEXT_KEY)
                self.assertIsInstance(first_context, dict)
                assert isinstance(first_context, dict)
                self.assertEqual(first_context["fingerprint"], "a" * 64)

                graph.frame = _frame(
                    fingerprint="1" * 64,
                    foreground_fingerprint="9" * 64,
                    foreground_process_id=5678,
                    foreground_process_name="steered.exe",
                    foreground_window_handle=123456,
                    observed_at="2026-09-15T12:01:00Z",
                )
                _, steered = control.start(
                    "ui-ingress",
                    "继续刚才，先把计划改成新的目标。",
                    payload={"caller_field": "steered"},
                )
                self.assertNotEqual(steered.event_id, original.event_id)

                persisted = resident.store.get_event(steered.event_id)
                self.assertIsNotNone(persisted)
                assert persisted is not None
                context = persisted.payload.get(_CONTEXT_KEY)
                self.assertIsInstance(context, dict)
                assert isinstance(context, dict)
                self.assertEqual(graph.calls, 2)
                self.assertEqual(context["fingerprint"], "1" * 64)
                self.assertEqual(context["components"]["foreground"], "9" * 64)
                self.assertEqual(context["foreground"]["process_id"], 5678)
                self.assertEqual(context["foreground"]["process_name"], "steered.exe")
                self.assertEqual(persisted.payload.get("caller_field"), "steered")
                self.assertNotEqual(context["fingerprint"], first_context["fingerprint"])
                self.assertNotIn("foreground_window_handle", repr(context))
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
