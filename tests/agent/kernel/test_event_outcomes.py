from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from agent.kernel import CapabilityResult, ExactTaskCapability, ExecutionPath
from agent.kernel.provider_bridge import build_resident_runtime_from_existing_stack


class EventOutcomeTests(unittest.TestCase):
    @staticmethod
    def _resident(db: Path):
        resident = build_resident_runtime_from_existing_stack(
            config={"model": {}},
            store_path=db,
        )
        resident.capabilities.register(
            ExactTaskCapability(
                name="local-race",
                triggers=("race task", "persist outcome"),
                handler=lambda event, state: CapabilityResult(
                    success=True,
                    response=f"done:{event.task}",
                ),
            )
        )
        return resident

    def test_submit_recovers_result_when_background_loop_finishes_event_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = self._resident(Path(tmp) / "kernel.db")
            enqueued = threading.Event()
            original_enqueue = resident.enqueue

            def enqueue_and_signal(*args, **kwargs):
                event = original_enqueue(*args, **kwargs)
                enqueued.set()
                return event

            resident.enqueue = enqueue_and_signal
            result_box = {}
            error_box = {}

            def foreground_submit():
                try:
                    result_box["result"] = resident.submit("race task")
                except Exception as exc:  # pragma: no cover - assertion reports it
                    error_box["error"] = exc

            with resident._cycle_lock:
                thread = threading.Thread(target=foreground_submit)
                thread.start()
                self.assertTrue(enqueued.wait(timeout=2.0))

                background = resident.live_once()
                self.assertIsNotNone(background)
                self.assertTrue(background.success)
                self.assertEqual(background.response, "done:race task")

            thread.join(timeout=2.0)
            self.assertFalse(thread.is_alive())
            self.assertEqual(error_box, {})
            foreground = result_box["result"]
            self.assertTrue(foreground.success)
            self.assertEqual(foreground.response, "done:race task")
            self.assertEqual(foreground.execution_path, ExecutionPath.CAPABILITY)
            self.assertIsNotNone(resident.store.get_event_outcome(foreground.event.event_id))
            resident.store.close()

    def test_action_outcome_survives_resident_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kernel.db"
            first = self._resident(db)
            run = first.submit("persist outcome")
            event_id = run.event.event_id
            first.store.close()

            second = build_resident_runtime_from_existing_stack(
                config={"model": {}},
                store_path=db,
            )
            restored = second.result_for(event_id)

            self.assertIsNotNone(restored)
            self.assertTrue(restored.success)
            self.assertEqual(restored.response, "done:persist outcome")
            self.assertEqual(restored.execution_path, ExecutionPath.CAPABILITY)
            self.assertEqual(restored.model_invocations, 0)
            second.store.close()


if __name__ == "__main__":
    unittest.main()
