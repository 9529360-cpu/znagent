from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from docx import Document

from zn_agent.core.document_spec import document_visible_texts
from zn_agent.core.models import ModelRoute, WorkerResult
from zn_agent.core.office_document import _records, inspect_docx
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


def _section(index, heading, *, paragraphs=None, bullets=None):
    return {
        "id": f"section-{index}",
        "heading": heading,
        "paragraphs": list(paragraphs or []),
        "bullets": list(bullets or []),
    }


class DocumentWorkBehaviorTests(unittest.TestCase):
    def test_create_targeted_edits_export_and_reopen_same_work(self) -> None:
        initial = {
            "version": 1,
            "document_id": "doc-fixture",
            "title": "ZN Product Introduction",
            "subtitle": "One Resident, continuous Work",
            "sections": [
                _section(1, "Positioning", paragraphs=["ZN is a general-purpose personal assistant."]),
                _section(2, "Core capabilities", bullets=["Body", "Senses", "CognitiveResources", "Work"]),
                _section(
                    3,
                    "Working model",
                    paragraphs=[
                        "The same Resident keeps durable Work, combines resources, observes changes, and verifies the real outcome."
                    ],
                ),
                _section(4, "Verification", bullets=["Fresh observation", "Fail closed", "No fake success"]),
                _section(5, "Summary", paragraphs=["Grow product capability from verified real tasks."]),
            ],
        }
        edit_two = _section(
            2,
            "Core capabilities",
            bullets=["Understand the goal", "Act through owned capabilities", "Verify the result"],
        )
        edit_three = _section(
            3,
            "Working model",
            paragraphs=["One Resident owns the Work through verification."],
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resident = build_resident_runtime(config={"model": {}}, store_path=root / "kernel.db")
            try:
                factory = _Factory([
                    json.dumps(initial),
                    json.dumps(edit_two),
                    json.dumps(edit_three),
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
                ledger.create_thread(thread_id="document", title="Document")
                ledger.attach_workspace("document", root)

                _, create = ledger.submit(
                    "document",
                    "Write a ZN product introduction document with sections Positioning, Core capabilities, Working model, Verification, Summary.",
                )
                self.assertTrue(create.success, create.response)
                artifact = next(
                    item for item in ledger.list_artifacts("document", limit=16)
                    if item.kind == "document"
                )
                stable_id = artifact.artifact_id
                before = json.loads(artifact.content)
                self.assertEqual(len(before["sections"]), 5)
                self.assertEqual(artifact.metadata["revision"], 1)

                _, core_edit = ledger.submit(
                    "document",
                    "Change Core capabilities to three points.",
                )
                self.assertTrue(core_edit.success, core_edit.response)
                artifact = next(
                    item for item in ledger.list_artifacts("document", limit=16)
                    if item.kind == "document"
                )
                after_core = json.loads(artifact.content)
                self.assertEqual(artifact.artifact_id, stable_id)
                self.assertEqual(len(after_core["sections"][1]["bullets"]), 3)
                self.assertEqual(before["sections"][0], after_core["sections"][0])
                self.assertEqual(before["sections"][2:], after_core["sections"][2:])
                self.assertEqual(artifact.metadata["revision"], 2)

                _, working_edit = ledger.submit(
                    "document",
                    "Simplify Working model.",
                )
                self.assertTrue(working_edit.success, working_edit.response)
                artifact = next(
                    item for item in ledger.list_artifacts("document", limit=16)
                    if item.kind == "document"
                )
                after_working = json.loads(artifact.content)
                self.assertEqual(
                    [after_core["sections"][i] for i in range(5) if i != 2],
                    [after_working["sections"][i] for i in range(5) if i != 2],
                )
                self.assertLess(
                    sum(len(value) for value in after_working["sections"][2]["paragraphs"]),
                    sum(len(value) for value in after_core["sections"][2]["paragraphs"]),
                )
                self.assertEqual(artifact.metadata["revision"], 3)

                _, exported_run = ledger.submit(
                    "document",
                    "Export current document to DOCX.",
                )
                self.assertTrue(exported_run.success, exported_run.response)
                artifacts = ledger.list_artifacts("document", limit=16)
                documents = [item for item in artifacts if item.kind == "document"]
                self.assertEqual(len(documents), 1)
                self.assertEqual(documents[0].artifact_id, stable_id)
                self.assertEqual(documents[0].metadata["revision"], 3)
                exported = next(
                    item for item in artifacts
                    if item.metadata.get("mode") == "document_export"
                )
                reopened = inspect_docx(exported.path)
                self.assertTrue(reopened["ready"], reopened)
                self.assertEqual(
                    [record["text"] for record in _records(Document(exported.path))],
                    document_visible_texts(after_working),
                )
                self.assertEqual(factory.calls, 3)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
