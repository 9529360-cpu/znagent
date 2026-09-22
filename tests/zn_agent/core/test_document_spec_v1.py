from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from docx import Document

from zn_agent.core.document_spec import document_visible_texts, normalize_document_spec
from zn_agent.core.office_document import _records, create_docx_from_spec, inspect_docx


def document_spec() -> dict:
    return {
        "version": 1,
        "document_id": "doc-test-zn",
        "title": "ZN Product Introduction",
        "subtitle": "One Resident, continuous Work",
        "sections": [
            {
                "id": "section-1",
                "heading": "Positioning",
                "paragraphs": ["ZN is a general-purpose personal assistant."],
                "bullets": [],
            },
            {
                "id": "section-2",
                "heading": "Core capabilities",
                "paragraphs": [],
                "bullets": ["Body", "Senses", "CognitiveResources"],
            },
            {
                "id": "section-3",
                "heading": "Working model",
                "paragraphs": ["The same Resident owns one durable Work from request through verification."],
                "bullets": [],
            },
            {
                "id": "section-4",
                "heading": "Verification",
                "paragraphs": [],
                "bullets": ["Fresh observation", "Fail closed on ambiguity"],
            },
            {
                "id": "section-5",
                "heading": "Summary",
                "paragraphs": ["Grow concrete product capability from real tasks."],
                "bullets": [],
            },
        ],
    }


class DocumentSpecV1Tests(unittest.TestCase):
    def test_bounded_document_normalizes(self) -> None:
        value = normalize_document_spec(document_spec())
        self.assertEqual(value["document_id"], "doc-test-zn")
        self.assertEqual(len(value["sections"]), 5)
        self.assertEqual(value["sections"][1]["id"], "section-2")

    def test_document_dsl_expansion_is_rejected(self) -> None:
        value = document_spec()
        value["sections"][0]["table"] = [["a", "b"]]
        with self.assertRaisesRegex(ValueError, "exactly id, heading, paragraphs and bullets"):
            normalize_document_spec(value)

    def test_export_reopens_with_current_spec_text(self) -> None:
        value = normalize_document_spec(document_spec())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "zn-document.docx"
            result = create_docx_from_spec(path, spec=value)
            self.assertTrue(result["verified"])
            reopened = inspect_docx(path)
            self.assertTrue(reopened["ready"], reopened)
            self.assertEqual(
                [record["text"] for record in _records(Document(path))],
                document_visible_texts(value),
            )


if __name__ == "__main__":
    unittest.main()
