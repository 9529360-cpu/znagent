from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from zn_agent.core.machine_capability import ApplicationInventoryCandidate, DeviceCapabilityGraph
from zn_agent.core.office_com_body import OfficeComAwareBody
from zn_agent.core.office_native_action import (
    OfficeMutationResult,
    OfficeSessionObservation,
    OfficeValueObservation,
    scalar_digest,
    text_sha256,
)
from zn_agent.core.store import KernelStore


class _FakeOfficeAction:
    def __init__(self) -> None:
        self.excel_value = "old"
        self.word_text = ""
        self.mutations: list[dict] = []

    @staticmethod
    def _session(kwargs, kind: str, name: str):
        return OfficeSessionObservation(
            office_kind=kind,
            process_id=kwargs["process_id"],
            process_name=kwargs["process_name"],
            window_handle=kwargs["window_handle"],
            native_window_class={"word": "_WwG", "excel": "EXCEL7", "powerpoint": "mdiClass"}[kind],
            version="16.0",
            document_kind={"word": "document", "excel": "workbook", "powerpoint": "presentation"}[kind],
            document_name=name,
        )

    def session_read(self, **kwargs):
        kind = kwargs["office_kind"]
        return self._session(
            kwargs,
            kind,
            {
                "word": "Confidential Contract.docx",
                "excel": "Private Budget.xlsx",
                "powerpoint": "Board Plan.pptx",
            }[kind],
        )

    def excel_cell_read(self, **kwargs):
        return OfficeValueObservation(
            session=self._session(kwargs, "excel", "Private Budget.xlsx"),
            target={
                "worksheet_name": kwargs["worksheet_name"],
                "cell_address": kwargs["cell_address"],
            },
            state=scalar_digest(self.excel_value),
        )

    def word_selection_read(self, **kwargs):
        return OfficeValueObservation(
            session=self._session(kwargs, "word", "Confidential Contract.docx"),
            target={"selection": "current"},
            state={
                "selection_chars": len(self.word_text),
                "selection_sha256": text_sha256(self.word_text),
                "collapsed": not bool(self.word_text),
            },
        )

    def excel_cell_set(self, **kwargs):
        self.mutations.append({"kind": "excel", **kwargs})
        before = self.excel_cell_read(**kwargs)
        self.excel_value = kwargs["value"]
        after = self.excel_cell_read(**kwargs)
        return OfficeMutationResult(True, True, True, before=before, after=after)

    def word_selection_set_text(self, **kwargs):
        self.mutations.append({"kind": "word", **kwargs})
        before = self.word_selection_read(**kwargs)
        self.word_text = kwargs["text"]
        after = self.word_selection_read(**kwargs)
        return OfficeMutationResult(True, True, True, before=before, after=after)


class OfficeComAwareBodyTests(unittest.TestCase):
    def _fixture(self, tmp: str, *, process_name: str, display_name: str):
        executable = Path(tmp) / process_name
        executable.write_bytes(b"")
        runtime = {
            "processes": [{"pid": 55, "name": process_name, "exe": str(executable)}],
            "windows": [{
                "hwnd": 66,
                "pid": 55,
                "title": display_name,
                "class_name": "Office",
                "visible": True,
                "foreground": True,
            }],
        }
        graph = DeviceCapabilityGraph(
            inventory_provider=lambda: [
                ApplicationInventoryCandidate(
                    source="app_paths",
                    source_id=process_name,
                    display_name=display_name,
                    executable_path=str(executable),
                    identity_paths=(str(executable),),
                    launch_kind="executable",
                    launch_target=str(executable),
                    version="16.0",
                )
            ],
            process_provider=lambda: list(runtime["processes"]),
            window_provider=lambda: list(runtime["windows"]),
            cache_path=Path(tmp) / "apps.json",
            inventory_ttl_seconds=0,
        )
        app = graph.installed_applications(force_refresh=True)[0]
        store = KernelStore(Path(tmp) / "kernel.db")
        office = _FakeOfficeAction()
        body = OfficeComAwareBody(
            store=store,
            device_capabilities=graph,
            office_action=office,
        )
        return store, body, app, runtime, office

    def test_session_read_derives_office_kind_from_foreground_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, body, app, _runtime, _office = self._fixture(
                tmp,
                process_name="POWERPNT.EXE",
                display_name="Microsoft PowerPoint",
            )
            try:
                result = body.act("office_session_read", application_id=app.app_id)
                self.assertTrue(result.success)
                self.assertEqual(result.data["office_kind"], "powerpoint")
                self.assertEqual(result.data["native_window_class"], "mdiClass")
                self.assertEqual(result.data["document_name"], "Board Plan.pptx")
            finally:
                store.close()

    def test_excel_mutation_rejects_native_caller_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, body, app, _runtime, office = self._fixture(
                tmp,
                process_name="EXCEL.EXE",
                display_name="Microsoft Excel",
            )
            try:
                for index, key in enumerate(("hwnd", "pid", "x", "coordinates", body._DISPATCH_MARKER)):
                    with self.subTest(key=key):
                        result = body.act(
                            "office_excel_cell_set",
                            event_id=f"evt-raw-{index}",
                            application_id=app.app_id,
                            worksheet_name="Sheet1",
                            cell_address="B2",
                            value="new",
                            **{key: 1},
                        )
                        self.assertFalse(result.success)
                        self.assertFalse(result.data["dispatch_sent"])
                self.assertEqual(office.mutations, [])
            finally:
                store.close()

    def test_excel_cell_set_is_semantic_guarded_and_redacted(self) -> None:
        secret = "private revenue number"
        with tempfile.TemporaryDirectory() as tmp:
            store, body, app, _runtime, office = self._fixture(
                tmp,
                process_name="EXCEL.EXE",
                display_name="Microsoft Excel",
            )
            try:
                first = body.act(
                    "office_excel_cell_set",
                    event_id="evt-excel",
                    application_id=app.app_id,
                    worksheet_name="Sheet1",
                    cell_address="$b$2",
                    value=secret,
                )
                self.assertTrue(first.success)
                self.assertTrue(first.data["dispatch_sent"])
                self.assertTrue(first.data["postcondition_verified"])
                self.assertEqual(office.excel_value, secret)
                self.assertEqual(len(office.mutations), 1)

                second = body.act(
                    "office_excel_cell_set",
                    event_id="evt-excel",
                    application_id=app.app_id,
                    worksheet_name="Sheet1",
                    cell_address="B2",
                    value=secret,
                )
                self.assertFalse(second.success)
                self.assertTrue(second.data["replay_blocked"])
                self.assertEqual(len(office.mutations), 1)

                with closing(body._connect()) as conn:
                    rows = conn.execute(
                        "SELECT action_json,result_json FROM native_body_actions WHERE event_id=?",
                        ("evt-excel",),
                    ).fetchall()
                persisted = "\n".join(str(row["action_json"]) + str(row["result_json"]) for row in rows)
                self.assertNotIn(secret, persisted)
                self.assertNotIn("Private Budget.xlsx", persisted)
                self.assertIn("value_redacted", persisted)
                self.assertIn("document_name_redacted", persisted)
            finally:
                store.close()

    def test_word_selection_set_text_is_verified_and_redacted(self) -> None:
        secret = "confidential replacement"
        with tempfile.TemporaryDirectory() as tmp:
            store, body, app, _runtime, office = self._fixture(
                tmp,
                process_name="WINWORD.EXE",
                display_name="Microsoft Word",
            )
            try:
                result = body.act(
                    "office_word_selection_set_text",
                    event_id="evt-word",
                    application_id=app.app_id,
                    text=secret,
                )
                self.assertTrue(result.success)
                self.assertEqual(office.word_text, secret)
                self.assertEqual(result.data["after"]["state"]["selection_sha256"], text_sha256(secret))

                with closing(body._connect()) as conn:
                    row = conn.execute(
                        "SELECT action_json,result_json FROM native_body_actions WHERE event_id=? ORDER BY completed_at DESC LIMIT 1",
                        ("evt-word",),
                    ).fetchone()
                persisted = str(row["action_json"]) + str(row["result_json"])
                self.assertNotIn(secret, persisted)
                self.assertNotIn("Confidential Contract.docx", persisted)
                self.assertIn("text_redacted", persisted)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
