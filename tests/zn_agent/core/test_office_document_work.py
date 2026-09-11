from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from docx import Document
from docx.shared import Pt

from zn_agent.core.office_document import inspect_docx, replace_visible_span_across_runs, write_docx_copy


class OfficeDocumentWorkTests(unittest.TestCase):
    @staticmethod
    def _contract(path: Path, *, table_target: bool = False, duplicate: bool = False) -> None:
        doc = Document()
        doc.add_paragraph("合同编号：A-100")
        if table_target:
            table = doc.add_table(rows=2, cols=2)
            table.cell(0, 0).text = "条款"
            table.cell(0, 1).text = "内容"
            paragraph = table.cell(1, 1).paragraphs[0]
        else:
            paragraph = doc.add_paragraph()
        paragraph.add_run("付款日期：")
        year = paragraph.add_run("2026年")
        year.bold = True
        year.font.size = Pt(11)
        month_day = paragraph.add_run("9月15日")
        month_day.italic = True
        if duplicate:
            doc.add_paragraph("付款日期：2026年9月15日")
        doc.add_paragraph("其他条款保持不变。")
        doc.save(path)

    def test_run_local_and_cross_run_replacement_preserve_run_shape(self) -> None:
        doc = Document()
        paragraph = doc.add_paragraph()
        run = paragraph.add_run("付款日期：2026年9月15日；其他")
        run.bold = True
        start = paragraph.text.index("2026")
        replace_visible_span_across_runs(paragraph, start, start + len("2026年9月15日"), "2026年9月20日")
        self.assertEqual(paragraph.text, "付款日期：2026年9月20日；其他")
        self.assertTrue(paragraph.runs[0].bold)

        paragraph = doc.add_paragraph()
        paragraph.add_run("付款日期：")
        year = paragraph.add_run("2026年")
        year.bold = True
        month_day = paragraph.add_run("9月15日")
        month_day.italic = True
        start = paragraph.text.index("2026")
        replace_visible_span_across_runs(paragraph, start, len(paragraph.text), "2026年9月20日")
        self.assertEqual(paragraph.text, "付款日期：2026年9月20日")
        self.assertTrue(paragraph.runs[1].bold)
        self.assertEqual(paragraph.runs[2].text, "")
        self.assertTrue(paragraph.runs[2].italic)

    def test_real_docx_copy_reopens_preserves_source_and_table_cell_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "contract.docx"
            destination = root / "project.docx"
            self._contract(source, table_target=True)
            before = source.read_bytes()
            inspected = inspect_docx(source)
            self.assertTrue(inspected["ready"], inspected)
            self.assertEqual(inspected["payment_date_occurrence_count"], 1)
            self.assertTrue(inspected["payment_date_occurrences"][0]["location"].startswith("table:"))
            result = write_docx_copy(
                source,
                destination,
                replacement_date="2026年9月20日",
                precondition_identity=inspected["identity"],
            )
            self.assertTrue(result["source_unchanged"])
            self.assertTrue(result["destination_reopened"])
            self.assertTrue(result["format_preserved"])
            self.assertEqual(source.read_bytes(), before)
            reopened = Document(destination)
            texts = [
                paragraph.text
                for table in reopened.tables
                for row in table.rows
                for cell in row.cells
                for paragraph in cell.paragraphs
            ]
            self.assertIn("付款日期：2026年9月20日", texts)

    def test_zero_multiple_drift_collision_and_unsupported_structure_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            no_target = root / "none.docx"
            Document().save(no_target)
            self.assertEqual(inspect_docx(no_target)["payment_date_occurrence_count"], 0)

            repeated = root / "repeat.docx"
            self._contract(repeated, duplicate=True)
            repeated_info = inspect_docx(repeated)
            self.assertEqual(repeated_info["payment_date_occurrence_count"], 2)
            with self.assertRaises(ValueError):
                write_docx_copy(
                    repeated,
                    root / "repeat-out.docx",
                    replacement_date="2026年9月20日",
                    precondition_identity=repeated_info["identity"],
                )

            drift = root / "drift.docx"
            self._contract(drift)
            drift_info = inspect_docx(drift)
            doc = Document(drift)
            doc.add_paragraph("外部更新")
            doc.save(drift)
            with self.assertRaisesRegex(RuntimeError, "stale_source_evidence"):
                write_docx_copy(
                    drift,
                    root / "drift-out.docx",
                    replacement_date="2026年9月20日",
                    precondition_identity=drift_info["identity"],
                )
            self.assertFalse((root / "drift-out.docx").exists())

            collision = root / "collision.docx"
            self._contract(collision)
            collision_info = inspect_docx(collision)
            existing = root / "exists.docx"
            existing.write_bytes(b"sentinel")
            with self.assertRaises(FileExistsError):
                write_docx_copy(
                    collision,
                    existing,
                    replacement_date="2026年9月20日",
                    precondition_identity=collision_info["identity"],
                )
            self.assertEqual(existing.read_bytes(), b"sentinel")

            merged = root / "merged.docx"
            doc = Document()
            table = doc.add_table(rows=1, cols=2)
            table.cell(0, 0).merge(table.cell(0, 1)).text = "付款日期：2026年9月15日"
            doc.save(merged)
            blocked = inspect_docx(merged)
            self.assertFalse(blocked["ready"])
            self.assertEqual(blocked["blocker"], "unsupported_document_structure")


if __name__ == "__main__":
    unittest.main()
