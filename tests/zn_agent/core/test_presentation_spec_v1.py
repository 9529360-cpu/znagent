from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.presentation_document import create_pptx_from_spec, inspect_pptx
from zn_agent.core.presentation_spec import (
    normalize_presentation_spec,
    presentation_visible_texts,
)


def deck() -> dict:
    slides = [
        {
            "id": "slide-1",
            "layout": "title",
            "title": "ZN Product Introduction",
            "body": "One Resident, one continuous Work",
            "bullets": [],
            "image_artifact_id": "",
        },
        {
            "id": "slide-2",
            "layout": "title-bullets",
            "title": "Product goal",
            "body": "",
            "bullets": ["Natural language to real work", "Reuse existing owners"],
            "image_artifact_id": "",
        },
        {
            "id": "slide-3",
            "layout": "architecture",
            "title": "ZN architecture",
            "body": "",
            "bullets": [],
            "image_artifact_id": "",
            "diagram": {
                "nodes": [
                    {"id": "resident", "label": "Resident"},
                    {"id": "work", "label": "Work"},
                    {"id": "body", "label": "Body"},
                    {"id": "sense", "label": "Sense"},
                ],
                "edges": [
                    {"from": "resident", "to": "work"},
                    {"from": "resident", "to": "body"},
                    {"from": "sense", "to": "resident"},
                ],
            },
        },
    ]
    for index in range(4, 9):
        slides.append(
            {
                "id": f"slide-{index}",
                "layout": "title-bullets",
                "title": f"Capability {index}",
                "body": "",
                "bullets": [f"Point {index}-1", f"Point {index}-2"],
                "image_artifact_id": "",
            }
        )
    return {
        "version": 1,
        "deck_id": "deck-test-zn",
        "title": "ZN Product Introduction",
        "theme": "dark-tech",
        "slides": slides,
    }


class PresentationSpecV1Tests(unittest.TestCase):
    def test_dark_tech_architecture_deck_normalizes(self) -> None:
        normalized = normalize_presentation_spec(deck(), expected_slide_count=8)
        self.assertEqual(normalized["theme"], "dark-tech")
        self.assertEqual(len(normalized["slides"]), 8)
        self.assertEqual(normalized["slides"][2]["layout"], "architecture")
        self.assertEqual(normalized["slides"][5]["id"], "slide-6")

    def test_optional_image_id_null_canonicalizes_to_empty_string(self) -> None:
        value = deck()
        value["slides"][0]["image_artifact_id"] = None
        normalized = normalize_presentation_spec(value)
        self.assertEqual(normalized["slides"][0]["image_artifact_id"], "")

    def test_unknown_layout_is_rejected(self) -> None:
        value = deck()
        value["slides"][1]["layout"] = "chart"
        with self.assertRaisesRegex(ValueError, "unsupported layout"):
            normalize_presentation_spec(value)

    def test_export_reopens_with_current_spec_core_text(self) -> None:
        value = normalize_presentation_spec(deck())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "zn-slides.pptx"
            result = create_pptx_from_spec(path, spec=value)
            self.assertTrue(result["verified"])
            self.assertEqual(result["slide_count"], 8)
            reopened = inspect_pptx(path)
            self.assertTrue(reopened["ready"], reopened)
            self.assertEqual(reopened["slide_count"], 8)
            self.assertEqual(
                [slide["texts"] for slide in reopened["slides"]],
                presentation_visible_texts(value),
            )


if __name__ == "__main__":
    unittest.main()
