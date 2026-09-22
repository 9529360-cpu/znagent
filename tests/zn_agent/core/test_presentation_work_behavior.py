from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.models import ModelRoute, WorkerResult
from zn_agent.core.presentation_document import inspect_pptx
from zn_agent.core.presentation_spec import presentation_visible_texts
from zn_agent.core.provider_bridge import build_resident_runtime


class _Worker:
    def __init__(self, factory):
        self.factory = factory

    def run(self, goal, kernel_context):
        self.factory.calls += 1
        if not self.factory.responses:
            return WorkerResult(
                success=False,
                response="",
                verification_passed=False,
                error="fixture queue exhausted",
                metrics={"model_invoked": True},
            )
        return WorkerResult(
            success=True,
            response=self.factory.responses.pop(0),
            verification_passed=True,
            metrics={"model_invoked": True},
        )


class _Factory:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def create(self, route):
        return _Worker(self)


def _slide(index, title, *, layout="title-bullets", bullets=None, body="", diagram=None):
    value = {
        "id": f"slide-{index}",
        "layout": layout,
        "title": title,
        "body": body,
        "bullets": list(bullets or []),
        "image_artifact_id": "",
    }
    if diagram is not None:
        value["diagram"] = diagram
    return value


class PresentationWorkBehaviorTests(unittest.TestCase):
    def test_create_targeted_edits_export_and_reopen_same_work(self) -> None:
        initial = {
            "version": 1,
            "deck_id": "deck-fixture",
            "title": "ZN Product",
            "theme": "dark-tech",
            "slides": [
                _slide(1, "ZN", layout="title", body="General assistant"),
                _slide(2, "One Resident", bullets=["One Resident", "One Work"]),
                _slide(3, "Structure", bullets=["Body", "Senses", "CognitiveResources"]),
                _slide(4, "Desktop", layout="title-body", body="Real workstation"),
                _slide(5, "Cognition", bullets=["Bounded calls", "Explicit authority"]),
                _slide(6, "Verification", bullets=["Fresh readback", "Fail closed", "No fake success"]),
                _slide(7, "Surfaces", bullets=["Desktop", "Browser", "Files"]),
                _slide(8, "Evolution", layout="title-body", body="Grow from real tasks"),
            ],
        }
        edit_three = _slide(
            3,
            "Architecture",
            layout="architecture",
            diagram={
                "nodes": [
                    {"id": "resident", "label": "Resident"},
                    {"id": "work", "label": "Work"},
                    {"id": "sense", "label": "Sense"},
                    {"id": "body", "label": "Body"},
                ],
                "edges": [
                    {"from": "resident", "to": "work"},
                    {"from": "work", "to": "sense"},
                    {"from": "work", "to": "body"},
                ],
            },
        )
        edit_six = _slide(6, "Verification", bullets=["Fresh readback", "Fail closed"])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident = build_resident_runtime(config={"model": {}}, store_path=root / "kernel.db")
            try:
                factory = _Factory([
                    json.dumps(initial),
                    json.dumps(edit_three),
                    json.dumps(edit_six),
                ])
                resident.kernel.reconfigure_resources(
                    routes=[ModelRoute(
                        route_id="fixture",
                        provider="fixture",
                        model="fixture",
                        capabilities={"general": 1.0, "language_understanding": 1.0},
                    )],
                    worker_factory=factory,
                    max_attempts=1,
                    resource_status={"available": True, "error": None},
                )
                ledger = resident.work_ledger
                ledger.create_thread(thread_id="slides", title="Slides")
                ledger.attach_workspace("slides", root)

                _, create = ledger.submit("slides", "帮我做一份 8 页 ZN 产品介绍 PPT，深色科技风。")
                self.assertTrue(create.success, create.response)
                artifacts = ledger.list_artifacts("slides", limit=16)
                deck = next(item for item in artifacts if item.kind == "presentation")
                stable_id = deck.artifact_id
                before = json.loads(deck.content)

                _, third = ledger.submit("slides", "第三页改成架构图。")
                self.assertTrue(third.success, third.response)
                after_third = json.loads(next(
                    item for item in ledger.list_artifacts("slides", limit=16)
                    if item.kind == "presentation"
                ).content)
                self.assertEqual(after_third["slides"][2]["layout"], "architecture")
                self.assertEqual(
                    [before["slides"][i] for i in range(8) if i != 2],
                    [after_third["slides"][i] for i in range(8) if i != 2],
                )

                _, sixth = ledger.submit("slides", "第六页精简。")
                self.assertTrue(sixth.success, sixth.response)
                after_sixth = json.loads(next(
                    item for item in ledger.list_artifacts("slides", limit=16)
                    if item.kind == "presentation"
                ).content)
                self.assertEqual(
                    [after_third["slides"][i] for i in range(8) if i != 5],
                    [after_sixth["slides"][i] for i in range(8) if i != 5],
                )
                self.assertLess(
                    len(after_sixth["slides"][5]["bullets"]),
                    len(after_third["slides"][5]["bullets"]),
                )

                _, exported_run = ledger.submit("slides", "导出 PPTX。")
                self.assertTrue(exported_run.success, exported_run.response)
                artifacts = ledger.list_artifacts("slides", limit=16)
                presentations = [item for item in artifacts if item.kind == "presentation"]
                self.assertEqual(len(presentations), 1)
                self.assertEqual(presentations[0].artifact_id, stable_id)
                exported = next(
                    item for item in artifacts
                    if item.metadata.get("mode") == "presentation_export"
                )
                reopened = inspect_pptx(exported.path)
                self.assertTrue(reopened["ready"], reopened)
                self.assertEqual(reopened["slide_count"], 8)
                self.assertEqual(
                    [slide["texts"] for slide in reopened["slides"]],
                    presentation_visible_texts(after_sixth),
                )
                self.assertEqual(factory.calls, 3)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
