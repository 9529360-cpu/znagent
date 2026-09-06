from __future__ import annotations

import unittest

from zn_agent.core.worker_context_boundary import (
    WorkerContextBoundaryError,
    WorkerContextPack,
)


class WorkerContextBoundaryTests(unittest.TestCase):
    def tearDown(self) -> None:
        WorkerContextPack.set_classification_hook(None)

    @staticmethod
    def _pack(**overrides):
        values = {
            "root_goal_summary": "root goal",
            "work_item_objective": "bounded delegated objective",
            "acceptance_criteria": ("observable evidence exists",),
            "plan_version": 2,
            "relevant_evidence": ({"kind": "accepted_effect", "result": "verified"},),
            "artifact_refs": ({"kind": "workspace", "path": "C:/work"},),
            "tool_scope": ("workspace.read",),
            "authority_scope": ("workspace_read",),
            "forbidden_actions": ("workspace_write",),
            "expected_result_schema": {"type": "object", "properties": {"action": {"type": "string"}}},
        }
        values.update(overrides)
        return WorkerContextPack(**values)

    def test_pack_serializes_only_declared_boundary_with_provenance_and_classification(self) -> None:
        payload = self._pack().to_dict()
        self.assertEqual(payload["plan_version"], 2)
        self.assertEqual(payload["data_classification"], "private")
        self.assertEqual(payload["provenance"]["source"], "resident_work_ledger")
        self.assertEqual(payload["provenance"]["boundary"], "worker_context_pack_v1")
        self.assertNotIn("transcript", payload)
        self.assertNotIn("memory", payload)
        self.assertNotIn("self_model", payload)
        self.assertNotIn("credentials", payload)

    def test_nested_sensitive_keys_are_rejected_not_only_top_level(self) -> None:
        pack = self._pack(
            relevant_evidence=(
                {"kind": "nested", "metadata": {"credentials": {"api_key": "hidden"}}},
            )
        )
        with self.assertRaisesRegex(WorkerContextBoundaryError, "forbidden sensitive key"):
            pack.to_dict()

    def test_secret_like_values_are_rejected_even_under_allowed_keys(self) -> None:
        pack = self._pack(
            relevant_evidence=({"kind": "source", "result": "Bearer abcdefghijklmnopqrstuvwxyz012345"},)
        )
        with self.assertRaisesRegex(WorkerContextBoundaryError, "secret-like value"):
            pack.to_dict()

    def test_recursive_depth_item_string_and_total_size_limits_fail_closed(self) -> None:
        too_deep = {"a": {"b": {"c": {"d": {"e": {"f": {"g": "x"}}}}}}}
        with self.assertRaisesRegex(WorkerContextBoundaryError, "nesting is too deep"):
            self._pack(expected_result_schema=too_deep).to_dict()

        with self.assertRaisesRegex(WorkerContextBoundaryError, "exceeds item limit"):
            self._pack(artifact_refs=tuple({"kind": "url", "url": str(i)} for i in range(13))).to_dict()

        with self.assertRaisesRegex(WorkerContextBoundaryError, "string exceeds limit"):
            self._pack(root_goal_summary="x" * (WorkerContextPack.MAX_STRING_CHARS + 1)).to_dict()

        # Many individually legal strings can still exceed the final recursive
        # serialized byte budget; the boundary checks both dimensions.
        evidence = tuple(
            {"kind": f"effect-{i}", "result": "x" * 1800}
            for i in range(8)
        )
        schema = {f"field_{i}": "y" * 1800 for i in range(20)}
        with self.assertRaisesRegex(WorkerContextBoundaryError, "serialized size limit"):
            self._pack(relevant_evidence=evidence, expected_result_schema=schema).to_dict()

    def test_classification_hook_can_tighten_route_facing_label(self) -> None:
        WorkerContextPack.set_classification_hook(
            lambda payload, current: "cloud_denied" if current == "private" else current
        )
        payload = self._pack().to_dict()
        self.assertEqual(payload["data_classification"], "cloud_denied")

    def test_invalid_classification_fails_closed(self) -> None:
        with self.assertRaisesRegex(WorkerContextBoundaryError, "classification is invalid"):
            self._pack(data_classification="anything-goes").to_dict()


if __name__ == "__main__":
    unittest.main(verbosity=2)
