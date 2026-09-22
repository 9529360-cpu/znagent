from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.reflex_intent import (
    ReflexIntentDescriptor,
    ReflexIntentRegistry,
    build_resident_reflex_intents,
)


def _event(task: str, payload=None):
    return SimpleNamespace(
        kind="desktop_user_event",
        task=task,
        payload=payload or {},
    )


class ReflexIntentRegistryTests(unittest.TestCase):
    def test_application_open_resolves_to_semantic_slots_and_action(self) -> None:
        registry = build_resident_reflex_intents()

        result = registry.resolve(_event("打开 Chrome。"))

        self.assertEqual(result.status, "matched")
        self.assertIsNotNone(result.match)
        self.assertEqual(
            result.match.intent_id,
            "windows.application.open",
        )
        self.assertEqual(result.match.slots["application_name"], "Chrome")
        self.assertEqual(
            result.match.action_id,
            "windows.application.launch",
        )

    def test_file_url_or_raw_path_is_not_claimed_by_application_reflex(self) -> None:
        registry = build_resident_reflex_intents()

        for task in (
            "打开 report.pdf",
            "打开 https://example.com",
            r"打开 C:\Windows\notepad.exe",
        ):
            result = registry.resolve(_event(task))
            self.assertEqual(result.status, "no_match", task)

    def test_existing_current_app_cleanup_fast_path_is_indexed(self) -> None:
        registry = build_resident_reflex_intents()
        task = (
            "现在这个软件里面，把这份工作记录整理一下：去掉空行和完全重复的行，"
            "每行首尾空格也去掉，保留原来的顺序，然后保存。"
        )

        result = registry.resolve(_event(task))

        self.assertEqual(result.status, "matched")
        self.assertEqual(
            result.match.intent_id,
            "windows.current_app.text_cleanup",
        )
        self.assertEqual(result.match.slots["field_name"], "工作记录")
        self.assertEqual(result.match.slots["save_button_name"], "保存")
        self.assertIsNone(result.match.action_id)

    def test_existing_workspace_text_edit_fast_path_is_indexed(self) -> None:
        registry = build_resident_reflex_intents()
        task = (
            "找到这里昨天改过、名字像报价的那个 txt，把草稿改成最终版，"
            "保存后再读回来确认"
        )
        result = registry.resolve(
            _event(task, {"workspace_path": r"D:\workspace"})
        )

        self.assertEqual(result.status, "matched")
        self.assertEqual(
            result.match.intent_id,
            "windows.workspace.text_edit",
        )
        self.assertEqual(result.match.slots["name_hint"], "报价")
        self.assertEqual(result.match.slots["old_text"], "草稿")
        self.assertEqual(result.match.slots["new_text"], "最终版")

    def test_equal_priority_collision_fails_closed_as_ambiguous(self) -> None:
        registry = ReflexIntentRegistry()
        for intent_id in ("test.one", "test.two"):
            registry.register(
                ReflexIntentDescriptor(
                    intent_id=intent_id,
                    description=intent_id,
                    required_slots=("value",),
                    priority=50,
                ),
                lambda _event, intent_id=intent_id: {
                    "value": intent_id,
                },
            )

        result = registry.resolve(_event("anything"))

        self.assertEqual(result.status, "ambiguous")
        self.assertIsNone(result.match)
        self.assertEqual(
            tuple(item.intent_id for item in result.candidates),
            ("test.one", "test.two"),
        )

    def test_recognizer_exception_fails_closed_as_no_match(self) -> None:
        registry = ReflexIntentRegistry()
        registry.register(
            ReflexIntentDescriptor(
                intent_id="test.broken",
                description="broken",
            ),
            lambda _event: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        result = registry.resolve(_event("anything"))

        self.assertEqual(result.status, "no_match")


class ProductReflexIntentIntegrationTests(unittest.TestCase):
    def test_final_resident_exposes_same_deterministic_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                ids = tuple(
                    descriptor.intent_id
                    for descriptor in resident.reflex_intents.descriptors()
                )
                self.assertIn("windows.application.open", ids)
                self.assertIn("windows.current_app.text_cleanup", ids)

                result = resident.reflex_intents.resolve(
                    _event("please launch VS Code")
                )
                self.assertEqual(result.status, "matched")
                self.assertEqual(
                    result.match.slots["application_name"],
                    "VS Code",
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
