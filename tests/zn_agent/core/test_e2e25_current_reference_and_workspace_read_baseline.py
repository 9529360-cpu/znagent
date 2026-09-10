from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.current_api_docs_adaptation_resident import (
    CurrentApiDocsAdaptationResidentRuntime,
)
from zn_agent.core.steerable_work import WorkItem
from zn_agent.core.user_browser_extension_relay import AuthorizedUserBrowserTab
from zn_agent.core.worker_context_boundary import (
    WorkerContextBoundaryError,
    WorkerContextPack,
)


_GOAL = "按这个网站的新 API 文档把项目适配一下，然后跑起来确认能用。"


class _Ledger:
    def plan_version(self, _thread_id: str) -> int:
        return 1


class _Relay:
    def __init__(self, current: AuthorizedUserBrowserTab) -> None:
        self.current = current

    def authorized_tab(self):
        return self.current


class E2E25CurrentReferenceAndWorkspaceReadTests(unittest.TestCase):
    @staticmethod
    def _resident() -> CurrentApiDocsAdaptationResidentRuntime:
        resident = CurrentApiDocsAdaptationResidentRuntime.__new__(
            CurrentApiDocsAdaptationResidentRuntime
        )
        resident.work_ledger = _Ledger()
        return resident

    @staticmethod
    def _root() -> SimpleNamespace:
        return SimpleNamespace(
            work_item_id="root",
            work_thread_id="e2e25",
            plan_version=1,
            objective=_GOAL,
        )

    @staticmethod
    def _item(item_id: str, *, status: str, criterion: str) -> WorkItem:
        return WorkItem(
            work_item_id=item_id,
            work_thread_id="e2e25",
            parent_work_item_id="root",
            title=item_id,
            objective=item_id,
            status=status,
            plan_version=1,
            acceptance_criteria=[criterion],
        )

    def test_current_page_research_proposal_is_url_free_and_resident_owned(self) -> None:
        resident = self._resident()
        content = json.dumps(
            {
                "zn_work_step": {
                    "objective": "Read the API documentation currently referenced by the user",
                    "action": {"kind": "research_current_page"},
                    "acceptance": {"kind": "page_read_current_reference"},
                }
            }
        )
        parsed = resident._parse_research_page_step(self._root(), content)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["source_kind"], "current_user_browser_page")
        self.assertNotIn("url", parsed)

        forged = json.dumps(
            {
                "zn_work_step": {
                    "objective": "Try to replace the current page",
                    "action": {
                        "kind": "research_current_page",
                        "url": "https://attacker.invalid/docs",
                    },
                    "acceptance": {"kind": "page_read_current_reference"},
                }
            }
        )
        self.assertIsNone(resident._parse_research_page_step(self._root(), forged))

    def test_current_page_reference_pins_tab_and_authorization_generation(self) -> None:
        resident = self._resident()
        authorized = AuthorizedUserBrowserTab(
            tab_id=41,
            url="https://docs.example.test/api",
            title="API docs",
            attached_at="auth-a",
        )
        relay = _Relay(authorized)
        resident.user_browser_extension = relay
        resident._ensure_user_browser_task_context = lambda _event, _state: {
            "tab_id": 41,
            "attached_at": "auth-a",
            "origin": "https://docs.example.test",
        }
        resident.probe_user_browser_extension_tab = lambda: {
            "tab_id": 41,
            "url": "https://docs.example.test/api?v=2",
            "title": "API v2 docs",
        }
        state = SimpleNamespace(data={})
        event = SimpleNamespace(payload={})

        reference = resident._resolve_current_user_browser_page(event, state)
        self.assertEqual(reference["tab_id"], 41)
        self.assertEqual(reference["attached_at"], "auth-a")
        self.assertEqual(reference["url"], "https://docs.example.test/api?v=2")
        self.assertNotIn("cookie", json.dumps(reference).casefold())
        self.assertNotIn("session", json.dumps(reference).casefold())

        relay.current = AuthorizedUserBrowserTab(
            tab_id=41,
            url="https://docs.example.test/api?v=2",
            title="API v2 docs",
            attached_at="auth-b",
        )
        with self.assertRaisesRegex(RuntimeError, "authorization generation changed"):
            resident._resolve_current_user_browser_page(event, SimpleNamespace(data={}))

    def test_current_page_reference_rejects_cross_origin_and_credential_url(self) -> None:
        resident = self._resident()
        authorized = AuthorizedUserBrowserTab(
            tab_id=7,
            url="https://docs.example.test/api",
            title="API docs",
            attached_at="auth-7",
        )
        resident.user_browser_extension = _Relay(authorized)
        resident._ensure_user_browser_task_context = lambda _event, _state: {
            "tab_id": 7,
            "attached_at": "auth-7",
            "origin": "https://docs.example.test",
        }
        event = SimpleNamespace(payload={})

        resident.probe_user_browser_extension_tab = lambda: {
            "tab_id": 7,
            "url": "https://elsewhere.example.test/api",
        }
        with self.assertRaisesRegex(RuntimeError, "authorization origin"):
            resident._resolve_current_user_browser_page(event, SimpleNamespace(data={}))

        resident.probe_user_browser_extension_tab = lambda: {
            "tab_id": 7,
            "url": "https://user:pass@docs.example.test/api",
        }
        with self.assertRaisesRegex(RuntimeError, "safe HTTP"):
            resident._resolve_current_user_browser_page(event, SimpleNamespace(data={}))

    def test_delegated_coding_reads_existing_workspace_before_any_write(self) -> None:
        resident = self._resident()
        root = self._root()
        research_meta = self._item(
            "research-meta",
            status="completed",
            criterion="delegated_worker_evidence: research/research_current_page",
        )
        accepted_research = SimpleNamespace(
            work_item_id="research-meta",
            executor_kind="research",
            state="completed",
            verification_status="accepted",
        )
        phase = resident._next_worker_phase(root, [research_meta], [accepted_research])
        self.assertEqual(phase, ("coding", "read_workspace_file"))

    def test_root_verification_requires_all_current_plan_phase_and_body_evidence(self) -> None:
        resident = self._resident()
        root = self._root()
        meta_specs = [
            ("research-meta", "research", "research_current_page"),
            ("read-meta", "coding", "read_workspace_file"),
            ("write-meta", "coding", "write_file"),
            ("run-meta", "coding", "run_python"),
            ("review-meta", "review", "run_python"),
        ]
        meta_items = [
            self._item(
                item_id,
                status="completed",
                criterion=f"delegated_worker_evidence: {executor}/{action}",
            )
            for item_id, executor, action in meta_specs
        ]
        runs = [
            SimpleNamespace(
                work_item_id=item_id,
                executor_kind=executor,
                plan_version=1,
                state="completed",
                verification_status="accepted",
            )
            for item_id, executor, _action in meta_specs
        ]
        real_items = [
            self._item("page", status="completed", criterion="page_read: http://127.0.0.1/docs"),
            self._item("read", status="completed", criterion="file_read: client.py"),
            self._item("write", status="completed", criterion="text_equals: client.py"),
            self._item("coding-run", status="completed", criterion="command_exit: 0"),
            self._item("review-run", status="completed", criterion="command_exit: 0"),
        ]
        resident.work_ledger.list_work_items = lambda _thread_id, limit=256: meta_items + real_items
        resident.work_ledger.list_worker_runs = lambda thread_id, limit=256: runs

        complete, reason = resident._e2e25_required_phase_evidence(root)
        self.assertTrue(complete, reason)

        runs[0].verification_status = "execution_failed"
        complete, reason = resident._e2e25_required_phase_evidence(root)
        self.assertFalse(complete)
        self.assertIn("research/research_current_page", reason)

        runs[0].verification_status = "accepted"
        real_items[0].status = "blocked"
        complete, reason = resident._e2e25_required_phase_evidence(root)
        self.assertFalse(complete)
        self.assertIn("page_read", reason)

    def test_workspace_read_parser_rejects_absolute_parent_missing_and_sensitive_paths(self) -> None:
        resident = self._resident()
        root = self._root()
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp).resolve()
            (workspace / "client.py").write_text("ENDPOINT = '/v1/items'\n", encoding="utf-8")
            event = SimpleNamespace(payload={"workspace_path": str(workspace)})

            def proposal(path: str) -> str:
                return json.dumps(
                    {
                        "zn_work_step": {
                            "objective": "Read existing API client",
                            "action": {"kind": "read_workspace_file", "path": path},
                            "acceptance": {"kind": "file_read", "path": path},
                        }
                    }
                )

            parsed = resident._parse_read_workspace_file_step(
                event, root, proposal("client.py")
            )
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed["relative_path"], "client.py")
            self.assertIsNone(
                resident._parse_read_workspace_file_step(event, root, proposal("../client.py"))
            )
            self.assertIsNone(
                resident._parse_read_workspace_file_step(
                    event, root, proposal(str(workspace / "client.py"))
                )
            )
            self.assertIsNone(
                resident._parse_read_workspace_file_step(event, root, proposal("missing.py"))
            )
            self.assertIsNone(
                resident._parse_read_workspace_file_step(event, root, proposal("api_token.txt"))
            )
            self.assertIsNone(
                resident._parse_read_workspace_file_step(event, root, proposal(".git/config"))
            )

    def test_workspace_read_parser_rejects_symlink_escape_when_supported(self) -> None:
        resident = self._resident()
        root = self._root()
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            workspace = Path(tmp).resolve()
            external = Path(outside).resolve() / "outside.py"
            external.write_text("outside = True\n", encoding="utf-8")
            link = workspace / "linked.py"
            try:
                os.symlink(external, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this runner")
            event = SimpleNamespace(payload={"workspace_path": str(workspace)})
            content = json.dumps(
                {
                    "zn_work_step": {
                        "objective": "Read existing source",
                        "action": {"kind": "read_workspace_file", "path": "linked.py"},
                        "acceptance": {"kind": "file_read", "path": "linked.py"},
                    }
                }
            )
            self.assertIsNone(
                resident._parse_read_workspace_file_step(event, root, content)
            )

    def test_worker_context_boundary_rejects_secret_like_workspace_evidence(self) -> None:
        pack = WorkerContextPack(
            root_goal_summary=_GOAL,
            work_item_objective="Read existing client",
            acceptance_criteria=("file_read: client.py",),
            plan_version=1,
            relevant_evidence=(
                {
                    "kind": "accepted_effect",
                    "result": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456",
                },
            ),
            artifact_refs=({"kind": "workspace", "path": "workspace"},),
            tool_scope=("workspace.read",),
            authority_scope=("workspace_read",),
            forbidden_actions=("workspace_write",),
            expected_result_schema={},
        )
        with self.assertRaises(WorkerContextBoundaryError):
            pack.to_dict()

    def test_normal_product_runtime_type_is_the_e2e25_composition_layer(self) -> None:
        from zn_agent.core.provider_bridge import build_resident_runtime

        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"zn_resident": {}, "zn_kernel": {"routes": []}},
                store_path=Path(tmp) / "kernel.db",
            )
            try:
                self.assertIsInstance(
                    resident, CurrentApiDocsAdaptationResidentRuntime
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
