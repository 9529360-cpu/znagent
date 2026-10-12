from __future__ import annotations

import unittest

from zn_agent.core.document_chunking import (
    chunk_document_text,
    chunk_elements,
    chunk_table,
    detect_header_row,
    split_sentences,
)
from zn_agent.core.document_ir import Element


class SentenceSplitTests(unittest.TestCase):
    def test_chinese_boundaries(self):
        sentences = split_sentences("第一句。第二句！第三句？")
        self.assertEqual(sentences, ["第一句。", "第二句！", "第三句？"])

    def test_latin_boundaries(self):
        sentences = split_sentences("Hello world. How are you? Fine!")
        self.assertEqual(len(sentences), 3)

    def test_soft_line_break_merged(self):
        sentences = split_sentences("这是第一行\n这是第二行。")
        self.assertEqual(sentences, ["这是第一行 这是第二行。"])

    def test_hard_break_after_terminal_kept(self):
        sentences = split_sentences("第一句。\n第二句。")
        self.assertEqual(sentences, ["第一句。", "第二句。"])


class HeaderDetectionTests(unittest.TestCase):
    def test_first_row_default(self):
        self.assertEqual(detect_header_row([["Name", "Age"], ["Alice", "30"]]), 0)

    def test_numeric_first_row_veto(self):
        rows = [["30", "25"], ["Name", "Age"], ["Alice", "30"]]
        self.assertEqual(detect_header_row(rows), 1)

    def test_empty_rows(self):
        self.assertEqual(detect_header_row([]), 0)


class TableChunkTests(unittest.TestCase):
    def _table(self, nrows: int) -> Element:
        rows = [["Name", "Age", "City"]] + [
            [f"person{i}", str(20 + i), f"city{i}"] for i in range(nrows)
        ]
        return Element(type="table", meta={"rows": rows})

    def test_header_repeated_in_every_chunk(self):
        chunks = chunk_table(self._table(30), target_chars=120)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertTrue(chunk.splitlines()[0].startswith("Name | Age | City"))

    def test_no_rows_lost(self):
        table = self._table(10)
        chunks = chunk_table(table, target_chars=200)
        joined = "\n".join(chunks)
        for i in range(10):
            self.assertIn(f"person{i}", joined)


class ElementChunkTests(unittest.TestCase):
    def test_greedy_merge_to_target(self):
        elements = [Element(type="paragraph", text=f"句子{i}。" * 20) for i in range(6)]
        chunks = chunk_elements(elements, target_chars=120, min_chars=10)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks[:-1]:
            # Merged chunks approach the target without wildly overshooting.
            self.assertLessEqual(len(chunk), 400)

    def test_short_chunks_dropped(self):
        elements = [
            Element(type="paragraph", text="很长的内容。" * 60),
            Element(type="paragraph", text="短"),
        ]
        chunks = chunk_elements(elements, target_chars=200, min_chars=50)
        self.assertTrue(all(len(c) >= 50 for c in chunks))
        self.assertNotIn("短", "\n".join(chunks))

    def test_heading_starts_new_chunk(self):
        elements = [
            Element(type="paragraph", text="正文一。" * 30),
            Element(type="heading", text="标题", meta={"level": 1}),
            Element(type="paragraph", text="正文二。" * 30),
        ]
        chunks = chunk_elements(elements, target_chars=500, min_chars=10)
        heading_chunks = [c for c in chunks if "## 标题" in c]
        self.assertEqual(len(heading_chunks), 1)

    def test_rune_not_byte_counting(self):
        # 100 CJK chars = 300 bytes in UTF-8; must count as 100.
        text = "中" * 100
        chunks = chunk_document_text(text, target_chars=120, min_chars=10)
        self.assertEqual(len(chunks), 1)

    def test_table_chunk_keeps_header(self):
        elements = [
            Element(type="paragraph", text="intro"),
            Element(
                type="table",
                meta={"rows": [["A", "B"]] + [[str(i), str(i)] for i in range(20)]},
            ),
        ]
        chunks = chunk_elements(elements, target_chars=80, min_chars=10)
        table_chunks = [c for c in chunks if "A | B" in c]
        self.assertGreaterEqual(len(table_chunks), 2)


if __name__ == "__main__":
    unittest.main()
