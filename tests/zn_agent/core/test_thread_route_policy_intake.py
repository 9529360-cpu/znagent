from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.models import ModelRoute, WorkerResult
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.route_policy_intake import infer_thread_route_policy
from zn_agent.core.router import NoRouteAvailable
from zn_agent.core.runtime import ZNKernelRuntime
from zn_agent.core.store import KernelStore


class _CaptureWorker:
    def __init__(self, factory, route):
        self.factory = factory
        self.route = route

    def run(self, goal, kernel_context):
        self.factory.routes.append(self.route.route_id)
        return WorkerResult(
            success=True,
            response=self.route.route_id,
            verification_passed=True,
            metrics={"model_invoked": True},
        )


class _CaptureFactory:
    def __init__(self):
        self.routes: list[str] = []

    def create(self, route):
        return _CaptureWorker(self, route)


class ThreadRoutePolicyIntakeTests(unittest.TestCase):
    def test_explicit_chinese_project_allowlist_maps_local_and_gpt(self) -> None:
        self.assertEqual(
            infer_thread_route_policy("这个项目只能给本地模型和 GPT 看，其他模型不要接触。"),
            {"allowed_providers": ["openai"], "allow_local": True},
        )

    def test_local_only_statement_becomes_local_data_policy(self) -> None:
        self.assertEqual(
            infer_thread_route_policy("这个项目只允许本地模型处理。"),
            {"data_classification": "local_only"},
        )

    def test_unknown_model_in_exclusive_local_list_stays_ambiguous(self) -> None:
        self.assertIsNone(
            infer_thread_route_policy("这个项目只允许本地模型和 FutureModel 处理。")
        )

    def test_clear_provider_denial_is_recognized(self) -> None:
        self.assertEqual(
            infer_thread_route_policy("不要让 Claude 接触这个项目。"),
            {"denied_providers": ["anthropic"]},
        )

    def test_preference_language_does_not_invent_policy(self) -> None:
        self.assertIsNone(infer_thread_route_policy("这个任务 GPT 可能更擅长，优先考虑一下。"))
        self.assertIsNone(infer_thread_route_policy("本地模型速度挺快。"))

    @staticmethod
    def _bind_research_request(resident, *, task: str, payload: dict | None = None):
        ledger = resident.work_ledger
        thread = ledger.get_thread("privacy-thread") or ledger.create_thread(
            thread_id="privacy-thread",
            title="Private project",
        )
        request = SimpleNamespace(
            request_id="original",
            required_capabilities=("research", "reasoning"),
            context={},
            question="perform research cognition",
        )
        event = SimpleNamespace(
            task=task,
            payload={
                "work_thread_id": thread.thread_id,
                **dict(payload or {}),
            },
        )
        return resident._bind_work_route_policy(event, request)

    @staticmethod
    def _run_request(tmp: str, request, factory):
        routes = [
            ModelRoute(
                "anthropic-high",
                "anthropic",
                "claude",
                {"research": 1.0, "reasoning": 1.0},
                reliability=1.0,
                metadata={"local": False},
            ),
            ModelRoute(
                "openai-medium",
                "openai",
                "gpt",
                {"research": 0.7, "reasoning": 0.7},
                reliability=0.7,
                metadata={"local": False},
            ),
            ModelRoute(
                "local-low",
                "ollama",
                "local",
                {"research": 0.2, "reasoning": 0.2},
                reliability=0.2,
                metadata={"local": True},
            ),
        ]
        kernel = ZNKernelRuntime(
            store=KernelStore(Path(tmp) / "router.db"),
            routes=routes,
            worker_factory=factory,
            max_attempts=1,
        )
        try:
            return kernel.run_goal(
                request.question,
                required_capabilities=request.required_capabilities,
                metadata={"cognition_request": {"context": request.context}},
                max_attempts_override=1,
                goal_id="goal-thread-policy",
            )
        finally:
            kernel.store.close()

    def test_explicit_empty_provider_allowlist_rejects_all_nonlocal_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            factory = _CaptureFactory()
            kernel = ZNKernelRuntime(
                store=KernelStore(Path(tmp) / "empty-allowlist.db"),
                routes=[
                    ModelRoute(
                        "otherwise-eligible",
                        "openai",
                        "gpt",
                        {"research": 1.0, "reasoning": 1.0},
                        reliability=1.0,
                        metadata={"local": False},
                    )
                ],
                worker_factory=factory,
                max_attempts=1,
            )
            try:
                with self.assertRaisesRegex(NoRouteAvailable, "outside user allowlist"):
                    kernel.run_goal(
                        "perform research cognition",
                        required_capabilities=("research", "reasoning"),
                        metadata={
                            "cognition_request": {
                                "context": {"route_policy": {"allowed_providers": []}}
                            }
                        },
                        max_attempts_override=1,
                        goal_id="goal-empty-allowlist",
                    )
                self.assertEqual(factory.routes, [])
            finally:
                kernel.store.close()

    def test_natural_language_policy_persists_across_resident_restart_and_blocks_other_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "resident.db"
            first = build_resident_runtime(config={"model": {}}, store_path=db)
            try:
                request = self._bind_research_request(
                    first,
                    task="这个项目只能给本地模型和 GPT 看，其他模型不要接触。",
                )
                self.assertEqual(
                    request.context["route_policy"],
                    {"allowed_providers": ["openai"], "allow_local": True},
                )
                thread = first.work_ledger.get_thread("privacy-thread")
                self.assertIsNotNone(thread)
                assert thread is not None
                self.assertEqual(thread.metadata["route_policy"], request.context["route_policy"])
            finally:
                first.store.close()

            second = build_resident_runtime(config={"model": {}}, store_path=db)
            try:
                inherited = self._bind_research_request(
                    second,
                    task="继续做这个项目的调研。",
                )
                self.assertEqual(
                    inherited.context["route_policy"],
                    {"allowed_providers": ["openai"], "allow_local": True},
                )
                factory = _CaptureFactory()
                result = self._run_request(tmp, inherited, factory)
                self.assertTrue(result.assessment.success)
                self.assertEqual(result.goal.route_id, "openai-medium")
                self.assertEqual(factory.routes, ["openai-medium"])
            finally:
                second.store.close()

    def test_local_exception_can_win_when_openai_lacks_required_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "resident.db"
            resident = build_resident_runtime(config={"model": {}}, store_path=db)
            try:
                request = self._bind_research_request(
                    resident,
                    task="这个项目只能给本地模型和 GPT 看，其他模型不要接触。",
                )
                factory = _CaptureFactory()
                kernel = ZNKernelRuntime(
                    store=KernelStore(Path(tmp) / "local-router.db"),
                    routes=[
                        ModelRoute(
                            "openai-coding-only",
                            "openai",
                            "gpt-code",
                            {"coding": 1.0, "reasoning": 1.0},
                            metadata={"local": False},
                        ),
                        ModelRoute(
                            "local-research",
                            "ollama",
                            "local-research",
                            {"research": 0.4, "reasoning": 0.4},
                            metadata={"local": True},
                        ),
                        ModelRoute(
                            "anthropic-research",
                            "anthropic",
                            "claude",
                            {"research": 1.0, "reasoning": 1.0},
                            metadata={"local": False},
                        ),
                    ],
                    worker_factory=factory,
                    max_attempts=1,
                )
                try:
                    result = kernel.run_goal(
                        request.question,
                        required_capabilities=request.required_capabilities,
                        metadata={"cognition_request": {"context": request.context}},
                        max_attempts_override=1,
                        goal_id="goal-local-exception",
                    )
                finally:
                    kernel.store.close()
                self.assertEqual(result.goal.route_id, "local-research")
                self.assertEqual(factory.routes, ["local-research"])
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
