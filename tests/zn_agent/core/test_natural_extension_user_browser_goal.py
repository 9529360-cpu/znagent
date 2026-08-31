from __future__ import annotations

import hashlib
import tempfile
import threading
import unittest
from pathlib import Path

from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.user_browser_extension_adapter import AuthorizedExtensionUserBrowser
from zn_agent.core.user_browser_extension_relay import ResidentUserBrowserExtensionRelay


_URL = "https://example.test/account"
_TARGET = "Account search"
_TEXT = "alice@example.test"
_TARGET_ID = "backend:701"


class _ForbiddenUIA:
    def probe_exact_edit(self, target_name):
        raise AssertionError("authorized extension browser goal must not fall back to Windows UIA")


class NaturalExtensionUserBrowserGoalTests(unittest.TestCase):
    def test_normal_task_uses_authorized_extension_tab_and_resenses_final_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            relay = ResidentUserBrowserExtensionRelay(port=0)
            resident.user_browser_extension = relay
            resident._extension_user_browser = AuthorizedExtensionUserBrowser(relay)
            resident.browser_named_target = _ForbiddenUIA()
            relay.start()
            relay.authorize(tab_id=51, url=_URL, title="Account")

            stop = threading.Event()
            state = {"text": "", "semantic_reads": 0, "mutations": 0}
            worker_error: list[BaseException] = []

            def digest(value: str) -> str:
                return hashlib.sha256(value.encode("utf-8")).hexdigest()

            def extension_worker() -> None:
                try:
                    while not stop.is_set():
                        command = relay.next_command(tab_id=51, wait_seconds=0.1)
                        if command is None:
                            continue
                        kind = command["kind"]
                        args = command["args"]
                        if kind == "probe_current_tab":
                            result = {"tab_id": 51, "url": _URL, "title": "Account"}
                        elif kind == "observe_named_textbox":
                            self.assertEqual(args["target_name"], _TARGET)
                            state["semantic_reads"] += 1
                            value = str(state["text"])
                            result = {
                                "tab_id": 51,
                                "url": _URL,
                                "title": "Account",
                                "target_id": _TARGET_ID,
                                "role": "textbox",
                                "name": _TARGET,
                                "text_length": len(value),
                                "text_sha256": digest(value),
                            }
                        elif kind == "type_named_textbox":
                            self.assertEqual(args["target_name"], _TARGET)
                            self.assertEqual(args["target_id"], _TARGET_ID)
                            self.assertEqual(args["expected_url"], _URL)
                            self.assertEqual(args["text"], _TEXT)
                            before = str(state["text"])
                            self.assertEqual(before, "")
                            state["text"] = _TEXT
                            state["mutations"] += 1
                            result = {
                                "tab_id": 51,
                                "url_before": _URL,
                                "url_after": _URL,
                                "target_id": _TARGET_ID,
                                "input_sent": True,
                                "exact_node_continuity": True,
                                "text_length_before": len(before),
                                "text_sha256_before": digest(before),
                                "text_length_after": len(_TEXT),
                                "text_sha256_after": digest(_TEXT),
                                "expected_text_length": len(_TEXT),
                                "expected_text_sha256": digest(_TEXT),
                                "expected_utf16_units": len(_TEXT.encode("utf-16-le")) // 2,
                                "postcondition": "same_exact_target_text_equals_requested",
                            }
                        else:  # pragma: no cover - deny-by-default relay should prevent this
                            raise AssertionError(f"unexpected extension command: {kind}")
                        relay.complete_command(
                            tab_id=51,
                            command_id=command["command_id"],
                            success=True,
                            result=result,
                            error=None,
                        )
                except BaseException as exc:  # pragma: no cover - asserted below
                    worker_error.append(exc)

            worker = threading.Thread(target=extension_worker, daemon=True)
            worker.start()
            try:
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
                self.assertEqual(state["text"], _TEXT)
                self.assertEqual(state["mutations"], 1)
                self.assertGreaterEqual(state["semantic_reads"], 3)
                authorization = resident.user_browser_authorization()
                self.assertTrue(authorization["authorized"])
                self.assertEqual(authorization["provider"], "zn-extension-user-browser")
                self.assertEqual(authorization["authorization_scope"], "explicit_current_tab")
                self.assertFalse(worker_error, worker_error)
            finally:
                stop.set()
                relay.close()
                worker.join(timeout=2.0)
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
