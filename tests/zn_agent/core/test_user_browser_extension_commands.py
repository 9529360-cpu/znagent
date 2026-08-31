from __future__ import annotations

import hashlib
import tempfile
import threading
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.user_browser_extension_relay import (
    ResidentUserBrowserExtensionRelay,
    UserBrowserExtensionOutcomeUncertain,
)


_URL = "https://example.test/account"
_TARGET = "Account search"
_TEXT = "alice@example.test"
_TAB_ID = 17
_BACKEND_NODE_ID = 41


class _ForbiddenUIA:
    def probe_exact_edit(self, target_name):
        raise AssertionError("extension-authorized USER browser must use semantic grounding")


class _FakeExtensionWorker:
    def __init__(self, relay, *, tab_id: int = _TAB_ID):
        self.relay = relay
        self.tab_id = tab_id
        self.text = ""
        self.commands: list[str] = []
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                command = self.relay.next_command(tab_id=self.tab_id, timeout=0.1)
            except Exception:
                if self.stop_event.is_set() or self.relay.authorized_tab() is None:
                    return
                continue
            if command is None:
                continue
            kind = str(command["kind"])
            self.commands.append(kind)
            try:
                result = self._execute(kind, dict(command.get("payload") or {}))
                self.relay.complete_command(
                    tab_id=self.tab_id,
                    command_id=command["command_id"],
                    result=result,
                )
            except Exception as exc:
                try:
                    self.relay.complete_command(
                        tab_id=self.tab_id,
                        command_id=command["command_id"],
                        error=str(exc),
                    )
                except Exception:
                    return

    def _execute(self, kind: str, payload: dict):
        if kind == "observe_page":
            return {
                "url": _URL,
                "title": "Account",
                "load_state": "complete",
            }
        if kind == "observe_named_textbox":
            self._require_target(payload)
            return self._text_state()
        if kind == "type_named_textbox":
            self._require_target(payload)
            if int(payload.get("expected_backend_node_id") or 0) != _BACKEND_NODE_ID:
                raise AssertionError("backend node authority drifted")
            if self.text:
                raise AssertionError("fake extension refuses replacement")
            requested = str(payload.get("text") or "")
            self.text = requested
            digest = hashlib.sha256(requested.encode("utf-8")).hexdigest()
            return {
                "url_before": _URL,
                "url_after": _URL,
                "target_name": _TARGET,
                "role": "textbox",
                "backend_node_id": _BACKEND_NODE_ID,
                "exact_node_continuity": True,
                "input_sent": True,
                "text_length_before": 0,
                "text_sha256_before": hashlib.sha256(b"").hexdigest(),
                "text_length_after": len(requested),
                "text_sha256_after": digest,
                "expected_text_length": len(requested),
                "expected_text_sha256": digest,
                "expected_utf16_units": len(requested.encode("utf-16-le")) // 2,
            }
        raise AssertionError(kind)

    def _text_state(self):
        return {
            "url": _URL,
            "title": "Account",
            "load_state": "complete",
            "target_name": _TARGET,
            "role": "textbox",
            "backend_node_id": _BACKEND_NODE_ID,
            "text_length": len(self.text),
            "text_utf16_units": len(self.text.encode("utf-16-le")) // 2,
            "text_sha256": hashlib.sha256(self.text.encode("utf-8")).hexdigest(),
        }

    @staticmethod
    def _require_target(payload: dict) -> None:
        if str(payload.get("target_name") or "") != _TARGET:
            raise AssertionError("wrong semantic target")


class UserBrowserExtensionCommandTests(unittest.TestCase):
    def test_dispatched_mutation_is_never_redelivered_when_result_is_lost(self) -> None:
        relay = ResidentUserBrowserExtensionRelay(port=0)
        relay.authorize(tab_id=_TAB_ID, url=_URL, title="Account")
        captured: list[BaseException] = []

        def caller() -> None:
            try:
                relay.request(
                    "type_named_textbox",
                    {
                        "target_name": _TARGET,
                        "text": _TEXT,
                        "expected_backend_node_id": _BACKEND_NODE_ID,
                    },
                    timeout=0.2,
                )
            except BaseException as exc:
                captured.append(exc)

        thread = threading.Thread(target=caller)
        thread.start()
        command = relay.next_command(tab_id=_TAB_ID, timeout=1.0)
        self.assertIsNotNone(command)
        assert command is not None
        self.assertEqual(command["kind"], "type_named_textbox")
        self.assertIsNone(relay.next_command(tab_id=_TAB_ID, timeout=0.05))
        thread.join(timeout=2.0)
        self.assertEqual(len(captured), 1)
        self.assertIsInstance(captured[0], UserBrowserExtensionOutcomeUncertain)
        self.assertFalse(relay.status()["command_in_flight"])

    def test_final_resident_closes_natural_goal_through_extension_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            resident.extension_user_browser._url_checker = lambda url, **kwargs: True
            resident.browser_named_target = _ForbiddenUIA()
            worker = _FakeExtensionWorker(resident.user_browser_extension)
            try:
                authorized = resident.user_browser_extension.authorize(
                    tab_id=_TAB_ID,
                    url=_URL,
                    title="Account",
                )
                self.assertTrue(authorized["authorized"])
                self.assertIs(resident.managed_browser, resident.extension_user_browser)
                worker.start()

                result = resident.submit(
                    "In my current browser, put alice@example.test in Account search.",
                    payload={
                        "resident_goal": {
                            "kind": "user_browser_named_text",
                            "target_name": _TARGET,
                            "text": _TEXT,
                        },
                        "model_policy": "never",
                    },
                )
                self.assertTrue(result.success, result.reason)
                self.assertEqual(result.model_invocations, 0)
                self.assertEqual(worker.text, _TEXT)
                self.assertEqual(worker.commands.count("type_named_textbox"), 1)
                self.assertGreaterEqual(worker.commands.count("observe_named_textbox"), 2)
                self.assertGreaterEqual(worker.commands.count("observe_page"), 2)

                resident.user_browser_extension.revoke(tab_id=_TAB_ID)
                self.assertIsNot(resident.managed_browser, resident.extension_user_browser)
                self.assertFalse(resident.user_browser_extension_status()["authorized"])
            finally:
                worker.stop()
                resident.user_browser_extension.close()
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
