from __future__ import annotations

import unittest

from zn_agent.core.action_execution import ActionRequest, build_machine_action_execution_runtime
from zn_agent.core.action_fabric import ActionAvailability, ActionDescriptor, ActionFabricRegistry
from zn_agent.core.body import BodyActionResult
from zn_agent.core.office_native_action import (
    OfficeSessionObservation,
    OfficeValueObservation,
    scalar_digest,
    text_sha256,
)


class _OfficeBody:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.excel_value = "old"
        self.word_text = ""

    def act(self, kind: str, *, event_id: str | None = None, **args):
        self.calls.append((kind, dict(args)))
        return BodyActionResult(
            action_id=f"body-{len(self.calls)}",
            kind=kind,
            success=True,
            data={"dispatch_sent": True, "postcondition_verified": False},
            event_id=event_id,
        )

    @staticmethod
    def _session(kind: str):
        return OfficeSessionObservation(
            office_kind=kind,
            process_id=55,
            process_name="excel.exe" if kind == "excel" else "winword.exe",
            window_handle=66,
            native_window_class="EXCEL7" if kind == "excel" else "_WwG",
            version="16.0",
            document_kind="workbook" if kind == "excel" else "document",
            document_name="redacted-by-caller",
        )

    def observe_excel_cell(self, *, application_id, worksheet_name, cell_address):
        return OfficeValueObservation(
            session=self._session("excel"),
            target={"worksheet_name": worksheet_name, "cell_address": cell_address},
            state=scalar_digest(self.excel_value),
        )

    def observe_word_selection(self, *, application_id):
        return OfficeValueObservation(
            session=self._session("word"),
            target={"selection": "current"},
            state={
                "selection_chars": len(self.word_text),
                "selection_sha256": text_sha256(self.word_text),
                "collapsed": not bool(self.word_text),
            },
        )


def _registry(action_id: str, body_kind: str) -> ActionFabricRegistry:
    registry = ActionFabricRegistry()
    registry.register(
        ActionDescriptor(
            action_id=action_id,
            provider="zn.windows.office",
            description="test Office mutation",
            body_action_kind=body_kind,
            effect_class="reversible_side_effect",
        ),
        availability_probe=lambda descriptor: ActionAvailability(
            descriptor.action_id,
            "available",
            evidence={"source": "test"},
        ),
    )
    return registry


class OfficeActionExecutionTests(unittest.TestCase):
    def test_excel_completion_requires_fresh_nativeom_digest(self) -> None:
        body = _OfficeBody()
        body.excel_value = "new value"
        runtime = build_machine_action_execution_runtime(
            _registry("windows.office.excel.cell.set", "office_excel_cell_set"),
            body,
            device_capabilities=None,
        )
        result = runtime.execute(
            ActionRequest(
                "windows.office.excel.cell.set",
                {
                    "application_id": "app.excel",
                    "worksheet_name": "Sheet1",
                    "cell_address": "B2",
                    "value": "new value",
                },
                event_id="evt-excel",
            )
        )
        self.assertTrue(result.success)
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.observations[-1].source, "office_excel_nativeom_readback")
        self.assertEqual(len(body.calls), 1)

    def test_excel_mismatch_fails_even_when_body_claims_success(self) -> None:
        body = _OfficeBody()
        runtime = build_machine_action_execution_runtime(
            _registry("windows.office.excel.cell.set", "office_excel_cell_set"),
            body,
            device_capabilities=None,
        )
        result = runtime.execute(
            ActionRequest(
                "windows.office.excel.cell.set",
                {
                    "application_id": "app.excel",
                    "worksheet_name": "Sheet1",
                    "cell_address": "B2",
                    "value": "wanted",
                },
                event_id="evt-excel-mismatch",
            )
        )
        self.assertFalse(result.success)
        self.assertEqual(result.status, "failed")
        self.assertNotEqual(
            result.verification.evidence["expected"],
            result.verification.evidence["observed"],
        )

    def test_word_completion_uses_selection_digest_without_raw_text(self) -> None:
        body = _OfficeBody()
        body.word_text = "private Word text"
        runtime = build_machine_action_execution_runtime(
            _registry("windows.office.word.selection.set_text", "office_word_selection_set_text"),
            body,
            device_capabilities=None,
        )
        result = runtime.execute(
            ActionRequest(
                "windows.office.word.selection.set_text",
                {
                    "application_id": "app.word",
                    "text": body.word_text,
                },
                event_id="evt-word",
            )
        )
        self.assertTrue(result.success)
        evidence = result.verification.evidence
        self.assertEqual(
            evidence["expected"]["selection_sha256"],
            text_sha256(body.word_text),
        )
        self.assertNotIn(body.word_text, repr(evidence))


if __name__ == "__main__":
    unittest.main()
