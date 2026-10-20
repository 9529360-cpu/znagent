from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core import KernelStore
from zn_agent.core.action_execution import (
    ActionExecutionRuntime,
    ActionRequest,
)
from zn_agent.core.action_fabric import ActionFabricRegistry
from zn_agent.core.approval_cards import ApprovalCardStore, ApprovalGate
from zn_agent.core.body import NativeBody
from zn_agent.core.doc_artifacts_connector import (
    DOCX_ACTION_ID,
    PDF_ACTION_ID,
    PPTX_ACTION_ID,
    XLSX_ACTION_ID,
    DocArtifactError,
    attach_doc_artifact_tools,
    build_docx_bytes,
    build_pdf_bytes_from_markdown,
    build_pptx_bytes,
    build_xlsx_bytes,
    register_doc_artifacts_runtime,
    render_docx_template,
    render_pptx_template,
    render_xlsx_template,
    verify_docx,
    verify_pdf,
    verify_pptx,
    verify_xlsx,
    write_docx,
    write_pdf_from_markdown,
    write_pptx,
    write_xlsx,
)
from zn_agent.core.skill_evals import eval_skills_root

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_SKILLS_ROOT = REPO_ROOT / "skills"


def _approval_runtime(tmp: Path, fabric, body):
    store = ApprovalCardStore(str(tmp / "approvals.db"))
    runtime = ActionExecutionRuntime(
        fabric, body, approval_gate=ApprovalGate(store)
    )
    return runtime, store


_DOCX_CONTENT = {
    "title": "Quarterly report",
    "author": "ZN",
    "summary": "Everything is on track.",
    "sections": [
        {"heading": "Intro", "paragraphs": ["First.", "Second."]},
        {"heading": "Details", "paragraphs": ["More detail here."]},
    ],
    "tables": [
        {
            "caption": "KPIs",
            "headers": ["metric", "value"],
            "rows": [["uptime", "99.9%"], ["latency", "12ms"]],
        }
    ],
}

_XLSX_CONTENT = {
    "sheets": [
        {
            "name": "Sales",
            "headers": ["region", "amount", "closed"],
            "rows": [["north", 1200.5, True], ["south", 800, False]],
        },
        {
            "name": "Notes",
            "headers": ["note"],
            "rows": [["hello"], [None]],
        },
    ]
}

_PPTX_CONTENT = {
    "title": "Briefing",
    "subtitle": "October 2026",
    "slides": [
        {"title": "Agenda", "bullets": ["one", "two", "three"]},
        {"title": "Notes", "body": "A single paragraph body."},
    ],
    "closing": "Thanks!",
}

_MARKDOWN = """\
# Report title

Opening paragraph with **bold** emphasis.

## Findings

- first finding
- second finding

1. step one
2. step two

| metric | value |
| --- | --- |
| uptime | 99.9% |

```
$ echo hello
hello
```

---

Closing paragraph.
"""


class DocxGenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_and_verify_round_trip(self):
        data, report = build_docx_bytes(_DOCX_CONTENT)
        self.assertTrue(data.startswith(b"PK"))
        self.assertEqual(report["table_count"], 1)
        self.assertEqual(report["tables"], [{"rows": 2, "cols": 2}])
        target = self.root / "report.docx"
        target.write_bytes(data)
        observed = verify_docx(target, report)
        self.assertEqual(observed["table_count"], 1)
        self.assertEqual(observed["tables"], [{"rows": 2, "cols": 2}])

    def test_write_docx_creates_and_verifies(self):
        artifact = write_docx(_DOCX_CONTENT, self.root, "out.docx")
        self.assertTrue(artifact.path.is_file())
        self.assertGreater(artifact.byte_size, 1000)

    def test_output_name_suffix_appended(self):
        artifact = write_docx(_DOCX_CONTENT, self.root, "no-suffix")
        self.assertEqual(artifact.path.name, "no-suffix.docx")

    def test_traversal_name_is_explicit(self):
        with self.assertRaises(DocArtifactError) as ctx:
            write_docx(_DOCX_CONTENT, self.root, "../evil.docx")
        self.assertIn("plain filename", str(ctx.exception))

    def test_wrong_suffix_is_explicit(self):
        with self.assertRaises(DocArtifactError):
            write_docx(_DOCX_CONTENT, self.root, "evil.txt")

    def test_empty_title_is_explicit(self):
        content = dict(_DOCX_CONTENT, title="  ")
        with self.assertRaises(DocArtifactError) as ctx:
            build_docx_bytes(content)
        self.assertIn("'title'", str(ctx.exception))

    def test_mismatched_table_row_is_explicit(self):
        content = {
            "title": "t",
            "tables": [{"headers": ["a"], "rows": [["1", "2"]]}],
        }
        with self.assertRaises(DocArtifactError) as ctx:
            build_docx_bytes(content)
        self.assertIn("must match", str(ctx.exception))

    def test_missing_output_dir_is_explicit(self):
        with self.assertRaises(DocArtifactError):
            write_docx(
                _DOCX_CONTENT, self.root / "does-not-exist", "out.docx"
            )

    def test_corrupt_file_fails_verification(self):
        target = self.root / "broken.docx"
        target.write_bytes(b"not a zip at all")
        with self.assertRaises(DocArtifactError) as ctx:
            verify_docx(target, {"table_count": 0, "tables": []})
        self.assertIn("not a readable .docx", str(ctx.exception))

    def test_table_count_mismatch_is_explicit(self):
        target = self.root / "one-table.docx"
        data, report = build_docx_bytes(_DOCX_CONTENT)
        target.write_bytes(data)
        bad_expected = dict(report, table_count=3, tables=[])
        with self.assertRaises(DocArtifactError) as ctx:
            verify_docx(target, bad_expected)
        self.assertIn("expected 3 tables, found 1", str(ctx.exception))

    def test_oversized_table_is_explicit(self):
        content = {
            "title": "t",
            "tables": [
                {
                    "headers": ["a"],
                    "rows": [["x"] for _ in range(1001)],
                }
            ],
        }
        with self.assertRaises(DocArtifactError) as ctx:
            build_docx_bytes(content)
        self.assertIn("too many rows", str(ctx.exception))

    def test_unknown_template_is_explicit(self):
        with self.assertRaises(DocArtifactError) as ctx:
            render_docx_template("fancy", {})
        self.assertIn("unknown docx template", str(ctx.exception))

    def test_report_template_passes_data_through(self):
        spec = render_docx_template(
            "report",
            {
                "title": "T",
                "sections": [{"heading": "H", "paragraphs": ["p"]}],
            },
        )
        self.assertEqual(spec["title"], "T")
        data, _ = build_docx_bytes(spec)
        self.assertTrue(data.startswith(b"PK"))


class XlsxGenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_and_verify_round_trip(self):
        data, report = build_xlsx_bytes(_XLSX_CONTENT)
        self.assertTrue(data.startswith(b"PK"))
        self.assertEqual(
            [sheet["name"] for sheet in report["sheets"]],
            ["Sales", "Notes"],
        )
        target = self.root / "data.xlsx"
        target.write_bytes(data)
        observed = verify_xlsx(target, report)
        self.assertEqual(
            observed["sheets"][0]["data_rows"], 2
        )
        self.assertEqual(observed["sheets"][1]["data_rows"], 2)

    def test_write_xlsx_creates_and_verifies(self):
        artifact = write_xlsx(_XLSX_CONTENT, self.root, "out.xlsx")
        self.assertTrue(artifact.path.is_file())

    def test_value_types_preserved(self):
        from openpyxl import load_workbook

        artifact = write_xlsx(_XLSX_CONTENT, self.root, "types.xlsx")
        workbook = load_workbook(str(artifact.path))
        try:
            sheet = workbook["Sales"]
            self.assertEqual(sheet["B2"].value, 1200.5)
            self.assertIs(sheet["C2"].value, True)
        finally:
            workbook.close()

    def test_forbidden_sheet_name_is_explicit(self):
        content = {
            "sheets": [{"name": "a/b", "headers": ["h"], "rows": []}]
        }
        with self.assertRaises(DocArtifactError) as ctx:
            build_xlsx_bytes(content)
        self.assertIn("forbidden", str(ctx.exception))

    def test_long_sheet_name_is_explicit(self):
        content = {
            "sheets": [{"name": "x" * 32, "headers": ["h"], "rows": []}]
        }
        with self.assertRaises(DocArtifactError):
            build_xlsx_bytes(content)

    def test_duplicate_sheet_name_is_explicit(self):
        content = {
            "sheets": [
                {"name": "dup", "headers": ["h"], "rows": []},
                {"name": "dup", "headers": ["h"], "rows": []},
            ]
        }
        with self.assertRaises(DocArtifactError) as ctx:
            build_xlsx_bytes(content)
        self.assertIn("duplicate", str(ctx.exception))

    def test_mismatched_row_is_explicit(self):
        content = {
            "sheets": [{"name": "s", "headers": ["a", "b"], "rows": [["1"]]}]
        }
        with self.assertRaises(DocArtifactError):
            build_xlsx_bytes(content)

    def test_corrupt_file_fails_verification(self):
        target = self.root / "broken.xlsx"
        target.write_bytes(b"garbage")
        with self.assertRaises(DocArtifactError) as ctx:
            verify_xlsx(target, {"sheets": []})
        self.assertIn("not a readable .xlsx", str(ctx.exception))

    def test_sheet_mismatch_is_explicit(self):
        target = self.root / "one.xlsx"
        data, report = build_xlsx_bytes(_XLSX_CONTENT)
        target.write_bytes(data)
        bad = {"sheets": [{"name": "Other", "header_cols": 1, "data_rows": 0}]}
        with self.assertRaises(DocArtifactError) as ctx:
            verify_xlsx(target, bad)
        self.assertIn("do not match", str(ctx.exception))

    def test_unknown_template_is_explicit(self):
        with self.assertRaises(DocArtifactError):
            render_xlsx_template("fancy", {})


class PptxGenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_and_verify_round_trip(self):
        data, report = build_pptx_bytes(_PPTX_CONTENT)
        self.assertTrue(data.startswith(b"PK"))
        # title slide + 2 content slides + closing slide
        self.assertEqual(report["slide_count"], 4)
        target = self.root / "deck.pptx"
        target.write_bytes(data)
        observed = verify_pptx(target, report)
        self.assertEqual(observed["slide_count"], 4)

    def test_write_pptx_without_closing(self):
        content = dict(_PPTX_CONTENT)
        content.pop("closing")
        artifact = write_pptx(content, self.root, "deck.pptx")
        self.assertTrue(artifact.path.is_file())
        self.assertEqual(artifact.report["slide_count"], 3)

    def test_bullets_and_body_together_is_explicit(self):
        content = {
            "title": "t",
            "slides": [
                {"title": "s", "bullets": ["a"], "body": "b"},
            ],
        }
        with self.assertRaises(DocArtifactError) as ctx:
            build_pptx_bytes(content)
        self.assertIn("either 'bullets' or 'body'", str(ctx.exception))

    def test_slide_without_content_is_explicit(self):
        content = {"title": "t", "slides": [{"title": "s"}]}
        with self.assertRaises(DocArtifactError):
            build_pptx_bytes(content)

    def test_empty_title_is_explicit(self):
        with self.assertRaises(DocArtifactError):
            build_pptx_bytes({"title": " ", "slides": []})

    def test_corrupt_file_fails_verification(self):
        target = self.root / "broken.pptx"
        target.write_bytes(b"garbage")
        with self.assertRaises(DocArtifactError) as ctx:
            verify_pptx(target, {"slide_count": 0})
        self.assertIn("not a readable .pptx", str(ctx.exception))

    def test_slide_count_mismatch_is_explicit(self):
        target = self.root / "deck.pptx"
        data, report = build_pptx_bytes(_PPTX_CONTENT)
        target.write_bytes(data)
        with self.assertRaises(DocArtifactError) as ctx:
            verify_pptx(target, {"slide_count": 99, "title": "Briefing"})
        self.assertIn("expected 99 slides, found 4", str(ctx.exception))

    def test_unknown_template_is_explicit(self):
        with self.assertRaises(DocArtifactError):
            render_pptx_template("fancy", {})

    def test_deck_template_passes_data_through(self):
        spec = render_pptx_template(
            "briefing_deck",
            {"title": "T", "slides": [{"title": "S", "body": "b"}]},
        )
        data, report = build_pptx_bytes(spec)
        self.assertTrue(data.startswith(b"PK"))
        self.assertEqual(report["slide_count"], 2)


class PdfGenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_and_verify_round_trip(self):
        data, report = build_pdf_bytes_from_markdown(
            _MARKDOWN, title="Test report"
        )
        self.assertTrue(data.startswith(b"%PDF-"))
        self.assertTrue(data.rstrip().endswith(b"%%EOF"))
        self.assertGreaterEqual(report["page_count"], 1)
        self.assertIn(b"Test report", data)
        self.assertIn(b"Report title", data)
        target = self.root / "report.pdf"
        target.write_bytes(data)
        observed = verify_pdf(target, report)
        self.assertEqual(observed["page_count"], report["page_count"])

    def test_long_document_paginates(self):
        markdown = "# Long\n\n" + ("Paragraph with some words. " * 40 + "\n\n") * 12
        data, report = build_pdf_bytes_from_markdown(markdown)
        self.assertGreater(report["page_count"], 1)
        target = self.root / "long.pdf"
        target.write_bytes(data)
        observed = verify_pdf(target, report)
        self.assertEqual(observed["page_count"], report["page_count"])

    def test_table_and_code_render(self):
        data, _ = build_pdf_bytes_from_markdown(_MARKDOWN)
        self.assertIn(b"uptime", data)
        self.assertIn(b"echo hello", data)

    def test_cjk_fails_explicitly(self):
        with self.assertRaises(DocArtifactError) as ctx:
            build_pdf_bytes_from_markdown("# 你好世界")
        message = str(ctx.exception)
        self.assertIn("not representable", message)
        self.assertIn("doc.generate_docx", message)

    def test_table_without_separator_is_explicit(self):
        with self.assertRaises(DocArtifactError) as ctx:
            build_pdf_bytes_from_markdown("| a |\n| b |\n")
        self.assertIn("separator row", str(ctx.exception))

    def test_table_row_mismatch_is_explicit(self):
        with self.assertRaises(DocArtifactError) as ctx:
            build_pdf_bytes_from_markdown(
                "| a | b |\n| --- | --- |\n| 1 |\n"
            )
        self.assertIn("has 1 cells but the header has 2", str(ctx.exception))

    def test_unclosed_fence_is_explicit(self):
        with self.assertRaises(DocArtifactError) as ctx:
            build_pdf_bytes_from_markdown("```\ncode never ends")
        self.assertIn("never closed", str(ctx.exception))

    def test_empty_markdown_is_explicit(self):
        with self.assertRaises(DocArtifactError):
            build_pdf_bytes_from_markdown("   \n  ")

    def test_non_pdf_bytes_fail_verification(self):
        target = self.root / "fake.pdf"
        target.write_bytes(b"definitely not a pdf")
        with self.assertRaises(DocArtifactError) as ctx:
            verify_pdf(target, {"page_count": 1})
        self.assertIn("missing %PDF-", str(ctx.exception))

    def test_page_count_mismatch_is_explicit(self):
        data, report = build_pdf_bytes_from_markdown(_MARKDOWN)
        target = self.root / "report.pdf"
        target.write_bytes(data)
        with self.assertRaises(DocArtifactError) as ctx:
            verify_pdf(target, {"page_count": report["page_count"] + 5})
        self.assertIn("expected", str(ctx.exception))

    def test_truncated_pdf_is_explicit(self):
        data, _ = build_pdf_bytes_from_markdown(_MARKDOWN)
        target = self.root / "truncated.pdf"
        target.write_bytes(data[: len(data) // 2])
        with self.assertRaises(DocArtifactError) as ctx:
            verify_pdf(target, {"page_count": 1})
        self.assertIn("truncated", str(ctx.exception))


class DocArtifactAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.outdir = self.root / "artifacts"
        self.outdir.mkdir()
        self.fabric = ActionFabricRegistry()
        self.body = NativeBody(
            store=KernelStore(self.root / "kernel.db")
        )
        self.attachment = attach_doc_artifact_tools(
            self.fabric, self.body, output_dir=str(self.outdir)
        )

    def tearDown(self):
        self.attachment.detach()
        self.body.store.close()
        self.tmp.cleanup()

    def _runtime(self):
        runtime, store = _approval_runtime(self.root, self.fabric, self.body)
        register_doc_artifacts_runtime(runtime, output_dir=str(self.outdir))
        return runtime, store

    def test_all_four_actions_registered_with_effect_classes(self):
        for action_id in (
            DOCX_ACTION_ID,
            XLSX_ACTION_ID,
            PPTX_ACTION_ID,
            PDF_ACTION_ID,
        ):
            descriptor = self.fabric.descriptor(action_id)
            self.assertIsNotNone(descriptor, action_id)
            self.assertEqual(descriptor.effect_class, "reversible_side_effect")
            self.assertIn("approval:production_change", descriptor.tags)

    def test_detach_removes_everything(self):
        self.attachment.detach()
        for action_id in (
            DOCX_ACTION_ID,
            XLSX_ACTION_ID,
            PPTX_ACTION_ID,
            PDF_ACTION_ID,
        ):
            self.assertIsNone(self.fabric.descriptor(action_id))

    def test_probe_unavailable_without_output_dir(self):
        fabric = ActionFabricRegistry()
        body = NativeBody(store=KernelStore(self.root / "k2.db"))
        attachment = attach_doc_artifact_tools(fabric, body)
        try:
            availability = fabric.availability(DOCX_ACTION_ID)
            self.assertFalse(availability.available)
            self.assertIn("no output directory", availability.reason)
        finally:
            attachment.detach()
            body.store.close()

    def _approve(self, store):
        pending = store.pending_requests()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].action_kind, "production_change")
        store.decide(pending[0].request_id, "allow_once")

    def test_docx_write_denied_never_touches_disk(self):
        runtime, store = self._runtime()
        target = self.outdir / "denied.docx"
        execution = runtime.execute(
            ActionRequest(
                DOCX_ACTION_ID,
                {
                    "output_name": "denied.docx",
                    "template_data": _DOCX_CONTENT,
                },
                event_id="evt-docx-deny-1",
            )
        )
        self.assertFalse(execution.success)
        self.assertIn("approval_required", execution.error or "")
        pending = store.pending_requests()
        store.decide(pending[0].request_id, "deny")
        retry = runtime.execute(
            ActionRequest(
                DOCX_ACTION_ID,
                {
                    "output_name": "denied.docx",
                    "template_data": _DOCX_CONTENT,
                },
                event_id="evt-docx-deny-1",
            )
        )
        self.assertFalse(retry.success)
        self.assertFalse(target.exists())

    def test_docx_write_allowed_generates_and_verifies(self):
        runtime, store = self._runtime()
        args = {
            "output_name": "approved.docx",
            "template_data": _DOCX_CONTENT,
        }
        first = runtime.execute(
            ActionRequest(DOCX_ACTION_ID, args, event_id="evt-docx-allow-1")
        )
        self.assertFalse(first.success)
        self._approve(store)
        second = runtime.execute(
            ActionRequest(DOCX_ACTION_ID, args, event_id="evt-docx-allow-1")
        )
        self.assertTrue(second.success, second.error)
        self.assertTrue(second.verification.verified, second.verification.reason)
        data = second.body_result.data
        self.assertEqual(data["tool"], "generate_docx")
        self.assertTrue(Path(data["path"]).is_file())
        verification = data["verification"]
        self.assertEqual(
            verification["observed"]["table_count"],
            verification["expected"]["table_count"],
        )

    def test_xlsx_write_allowed_generates_and_verifies(self):
        runtime, store = self._runtime()
        args = {
            "output_name": "approved.xlsx",
            "template_data": _XLSX_CONTENT,
        }
        first = runtime.execute(
            ActionRequest(XLSX_ACTION_ID, args, event_id="evt-xlsx-allow-1")
        )
        self.assertFalse(first.success)
        self._approve(store)
        second = runtime.execute(
            ActionRequest(XLSX_ACTION_ID, args, event_id="evt-xlsx-allow-1")
        )
        self.assertTrue(second.success, second.error)
        self.assertTrue(second.verification.verified)

    def test_pptx_write_allowed_generates_and_verifies(self):
        runtime, store = self._runtime()
        args = {
            "output_name": "approved.pptx",
            "template_data": _PPTX_CONTENT,
        }
        first = runtime.execute(
            ActionRequest(PPTX_ACTION_ID, args, event_id="evt-pptx-allow-1")
        )
        self.assertFalse(first.success)
        self._approve(store)
        second = runtime.execute(
            ActionRequest(PPTX_ACTION_ID, args, event_id="evt-pptx-allow-1")
        )
        self.assertTrue(second.success, second.error)
        self.assertTrue(second.verification.verified)

    def test_pdf_write_allowed_generates_and_verifies(self):
        runtime, store = self._runtime()
        args = {
            "output_name": "approved.pdf",
            "markdown": _MARKDOWN,
            "title": "Approved PDF",
        }
        first = runtime.execute(
            ActionRequest(PDF_ACTION_ID, args, event_id="evt-pdf-allow-1")
        )
        self.assertFalse(first.success)
        self._approve(store)
        second = runtime.execute(
            ActionRequest(PDF_ACTION_ID, args, event_id="evt-pdf-allow-1")
        )
        self.assertTrue(second.success, second.error)
        self.assertTrue(second.verification.verified)
        data = second.body_result.data
        self.assertEqual(
            data["verification"]["observed"]["page_count"],
            data["verification"]["expected"]["page_count"],
        )

    def test_write_validates_inputs_after_approval(self):
        runtime, store = self._runtime()
        before = sorted(path.name for path in self.outdir.iterdir())
        args = {
            "output_name": "bad.docx",
            "template_data": {"title": "  ", "sections": []},
        }
        first = runtime.execute(
            ActionRequest(DOCX_ACTION_ID, args, event_id="evt-docx-bad-1")
        )
        self.assertFalse(first.success)
        self._approve(store)
        second = runtime.execute(
            ActionRequest(DOCX_ACTION_ID, args, event_id="evt-docx-bad-1")
        )
        self.assertFalse(second.success)
        self.assertIn("non-empty 'title'", second.error or "")
        self.assertEqual(
            sorted(path.name for path in self.outdir.iterdir()), before
        )

    def test_replay_of_completed_write_is_refused(self):
        kind = self.fabric.descriptor(DOCX_ACTION_ID).body_action_kind
        args = {
            "output_name": "replay.docx",
            "template_data": _DOCX_CONTENT,
        }
        first = self.body.act(kind, event_id="evt-replay-1", **args)
        self.assertTrue(first.success, first.error)
        second = self.body.act(kind, event_id="evt-replay-1", **args)
        self.assertFalse(second.success)
        self.assertIn("replay refused", second.error or "")

    def test_traversal_name_never_writes(self):
        kind = self.fabric.descriptor(PDF_ACTION_ID).body_action_kind
        result = self.body.act(
            kind,
            event_id="evt-traversal-1",
            output_name="../../escape.pdf",
            markdown="hi",
        )
        self.assertFalse(result.success)
        self.assertIn("plain filename", result.error or "")
        self.assertFalse((self.root / "escape.pdf").exists())


class DocArtifactSkillEvalTests(unittest.TestCase):
    def test_repo_doc_artifacts_skill_passes_skill_evals(self):
        report = eval_skills_root(REPO_SKILLS_ROOT)
        doc_artifacts = [
            item
            for item in report.tier1
            if item.skill_name == "doc-artifacts"
        ]
        self.assertEqual(len(doc_artifacts), 1, report.to_dict())
        self.assertTrue(doc_artifacts[0].passed, doc_artifacts[0].violations)
        self.assertTrue(report.tier2.passed, report.to_dict()["tier2"])
        self.assertTrue(report.passed, report.to_dict())


if __name__ == "__main__":
    unittest.main()
