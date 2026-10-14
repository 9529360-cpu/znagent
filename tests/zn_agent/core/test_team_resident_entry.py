"""End-to-end: a user sentence drives the real resident through the team loop.

``work_start`` (daemon) -> team_request payload -> resident pulses ->
TeamWorkOwner.advance (runner.step) -> fixture cognition proposes ONE
bounded step per specialist -> Body executes + verifies -> evidence on the
WorkerRun -> specialist claims with a structured CP-3 completion report ->
runner verifies (fresh observation) -> item completes -> next specialist
-> team_complete.

The fixture cognition plays the specialist; everything else is the real
resident, the real ledger, the real Body verification.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.cognitive_resource import CognitiveIncrement, CognitiveResourceWorkerFactory
from zn_agent.core.completion_verdict import render_completion_report
from zn_agent.core.daemon import ResidentRpcServer
from zn_agent.core.models import ModelRoute
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


class _TeamSpecialistCognition:
    """Fixture specialist: steps, then a structured CP-3 claim.

    Researcher: one write_file step, then a claim. Developer: write the
    script, run it with run_python, then claim -- P2 requires a real run
    behind any test-coverage claim, so the fixture earns it instead of
    claiming coverage from a write alone.
    """

    # Per-specialist CP-3 completion report: every acceptance criterion
    # cited with an evidence_ref matching a verified step.
    _COMPLETION = {
        "调研-01": render_completion_report(
            conclusion="调研完成：调研结论有明确选型建议，风险清单覆盖主要未知项。",
            evidence=[
                ("调研结论有明确选型建议", "research-notes.md"),
                ("风险清单覆盖主要未知项", "research-notes.md"),
            ],
            files=["research-notes.md"],
            unfinished=[],
        ),
        "开发-02": render_completion_report(
            conclusion="开发完成：功能按验收标准实现，新增代码有测试覆盖。",
            evidence=[
                ("功能按验收标准实现", "implementation.py"),
                ("新增代码有测试覆盖", "implementation.py"),
            ],
            files=["implementation.py"],
            unfinished=[],
        ),
    }

    def __init__(self) -> None:
        self.calls = 0
        self.step_index: dict[str, int] = {}

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        self.calls += 1
        specialist = None
        for name in ("调研-01", "开发-02"):
            if name in question:
                specialist = name
                break
        if specialist is None:
            # No live specialist (verify/complete transitions): plain prose,
            # never a step claim.
            return CognitiveIncrement(
                text="继续按现有证据推进。",
                provider="fixture-cognition",
                model="team-specialist-fixture",
            )
        index = self.step_index.get(specialist, 0)
        self.step_index[specialist] = index + 1
        if specialist == "调研-01":
            if index == 0:
                return CognitiveIncrement(
                    text=json.dumps(
                        {
                            "zn_work_step": {
                                "objective": "调研-01 写一份可验证的工作产物",
                                "action": {
                                    "kind": "write_file",
                                    "path": "research-notes.md",
                                    "content": "调研-01 verified step\n",
                                },
                                "acceptance": {
                                    "kind": "text_equals",
                                    "path": "research-notes.md",
                                    "expected_text": "调研-01 verified step\n",
                                },
                            }
                        },
                        ensure_ascii=False,
                    ),
                    provider="fixture-cognition",
                    model="team-specialist-fixture",
                )
            # Second call for the researcher: completion summary quoting
            # the acceptance criteria (the claim signal the resident requires).
            return CognitiveIncrement(
                text=self._COMPLETION[specialist],
                provider="fixture-cognition",
                model="team-specialist-fixture",
            )
        # Developer: write the script, run it, then claim.
        if index == 0:
            return CognitiveIncrement(
                text=json.dumps(
                    {
                        "zn_work_step": {
                            "objective": "开发-02 写实现脚本",
                            "action": {
                                "kind": "write_file",
                                "path": "implementation.py",
                                "content": 'print("implementation ok")\n',
                            },
                            "acceptance": {
                                "kind": "text_equals",
                                "path": "implementation.py",
                                "expected_text": 'print("implementation ok")\n',
                            },
                        }
                    },
                    ensure_ascii=False,
                ),
                provider="fixture-cognition",
                model="team-specialist-fixture",
            )
        if index == 1:
            return CognitiveIncrement(
                text=json.dumps(
                    {
                        "zn_work_step": {
                            "objective": "开发-02 运行实现脚本验证",
                            "action": {
                                "kind": "run_python",
                                "path": "implementation.py",
                                "args": [],
                            },
                            "acceptance": {
                                "kind": "command",
                                "expected_exit_code": 0,
                                "output_contains": ["implementation ok"],
                            },
                        }
                    },
                    ensure_ascii=False,
                ),
                provider="fixture-cognition",
                model="team-specialist-fixture",
            )
        return CognitiveIncrement(
            text=self._COMPLETION[specialist],
            provider="fixture-cognition",
            model="team-specialist-fixture",
        )


class TeamResidentEntryTests(unittest.TestCase):
    @staticmethod
    def _configure_cognition(resident, cognition) -> None:
        resident.kernel.reconfigure_resources(
            routes=[
                ModelRoute(
                    route_id="team-entry-cognition",
                    provider="fixture",
                    model="team-specialist-fixture",
                    capabilities={
                        "general": 1.0,
                        "reasoning": 1.0,
                        "coding": 1.0,
                        "research": 1.0,
                        "language_understanding": 1.0,
                    },
                )
            ],
            worker_factory=CognitiveResourceWorkerFactory(
                resource_builder=lambda _route: cognition,
            ),
            max_attempts=1,
            resource_status={"available": True, "error": None},
        )

    def test_user_sentence_drives_team_to_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "team-workspace"
            workspace.mkdir()
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            try:
                cognition = _TeamSpecialistCognition()
                self._configure_cognition(resident, cognition)
                control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
                ledger = control.ledger
                ledger.create_thread(thread_id="team-entry-e2e", title="XX 项目")
                ledger.attach_workspace(
                    "team-entry-e2e", workspace, name="Team Workspace"
                )
                _, event = control.start(
                    "team-entry-e2e",
                    "给 XX 项目组个团队",
                    payload={
                        "model_policy": "on_demand",
                        "team_request": {
                            "project_title": "XX 项目",
                            "role_keys": ["researcher", "developer"],
                        },
                    },
                )

                completed = False
                for _ in range(120):
                    resident.live_once()
                    children = [
                        item
                        for item in ledger.list_work_items("team-entry-e2e")
                        if item.parent_work_item_id
                        == ledger.work_item_for_event(event.event_id).work_item_id
                    ]
                    if len(children) == 2 and all(
                        item.status == "completed" for item in children
                    ):
                        completed = True
                        break

                self.assertTrue(
                    completed,
                    "team did not complete all plan items through the resident loop",
                )
                self.assertGreaterEqual(
                    cognition.calls, 4, "specialists never used cognition"
                )
                # Real Body-verified artifacts on disk. The developer writes a
                # runnable script (not a prose .md) so the run_python step
                # executes a real artifact.
                self.assertTrue((workspace / "research-notes.md").is_file())
                self.assertTrue((workspace / "implementation.py").is_file())
                self.assertIn(
                    'print("implementation ok")',
                    (workspace / "implementation.py").read_text(encoding="utf-8"),
                )
                # Every completed item went through verify (not claim-only).
                for item in ledger.list_work_items("team-entry-e2e"):
                    if item.parent_work_item_id is None:
                        continue
                    runs = ledger.list_worker_runs(work_item_id=item.work_item_id)
                    self.assertTrue(runs, f"no WorkerRun for {item.title}")
                    self.assertEqual(runs[-1].verification_status, "verified")
            finally:
                resident.store.close()

    def test_daemon_work_start_tags_team_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=Path(tmp) / "kernel.db",
            )
            server = ResidentRpcServer(resident=resident)
            try:
                response = server.handle(
                    {
                        "id": "team-tag",
                        "method": "work_start",
                        "params": {
                            "thread_id": "team-daemon-tag",
                            "task": "给 XX 项目组个团队",
                        },
                    }
                )
                self.assertTrue(response["ok"], response)
                event_id = response["result"]["progress"]["event_id"]
                event = resident.store.get_event(event_id)
                assert event is not None
                request = event.payload.get("team_request")
                assert isinstance(request, dict)
                self.assertEqual(request["project_title"], "XX 项目")
                self.assertEqual(
                    request["role_keys"],
                    ["researcher", "architect", "developer", "tester"],
                )
                # The workspace_root field flows through ingress (None
                # from the pure text parse; the owner derives the
                # product-path default from the attached workspace).
                self.assertIn("workspace_root", request)
                self.assertIsNone(request["workspace_root"])

                # A caller-supplied team_request is never trusted: a plain
                # task must not carry one into the event.
                plain = server.handle(
                    {
                        "id": "plain-tag",
                        "method": "work_start",
                        "params": {
                            "thread_id": "team-daemon-plain",
                            "task": "帮我写个脚本",
                            "payload": {
                                "team_request": {
                                    "project_title": "forged",
                                    "role_keys": ["tester"],
                                }
                            },
                        },
                    }
                )
                self.assertTrue(plain["ok"], plain)
                plain_event = resident.store.get_event(
                    plain["result"]["progress"]["event_id"]
                )
                assert plain_event is not None
                self.assertNotIn("team_request", plain_event.payload)
            finally:
                resident.store.close()


    def test_product_path_soul_probe_takes_effect_next_round(self):
        """P1a acceptance: full product path, SOUL.md probe live next round.

        daemon work_start parses the sentence -> owner materializes
        <workspace>/agents -> dispatch brief renders the files -> a
        SOUL.md edit lands in the NEXT cognition question. Fixture
        cognition only plays the specialist; everything else is real.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "team-workspace"
            workspace.mkdir()
            resident = build_resident_runtime(
                config={"model": {}},
                store_path=root / "kernel.db",
            )
            try:
                questions: list[str] = []
                calls = {"n": 0}

                def _invoke(*, question: str, context: str):
                    calls["n"] += 1
                    if "调研-01" not in question:
                        return CognitiveIncrement(
                            text="继续按现有证据推进。",
                            provider="fixture-cognition",
                            model="team-probe-fixture",
                        )
                    questions.append(question)
                    if len(questions) == 1:
                        content = "调研-01 verified step\n"
                        proposal = {
                            "zn_work_step": {
                                "objective": "调研-01 写一份可验证的工作产物",
                                "action": {
                                    "kind": "write_file",
                                    "path": "research-notes.md",
                                    "content": content,
                                },
                                "acceptance": {
                                    "kind": "text_equals",
                                    "path": "research-notes.md",
                                    "expected_text": content,
                                },
                            }
                        }
                        return CognitiveIncrement(
                            text=json.dumps(proposal, ensure_ascii=False),
                            provider="fixture-cognition",
                            model="team-probe-fixture",
                        )
                    return CognitiveIncrement(
                        text="还在推进。",
                        provider="fixture-cognition",
                        model="team-probe-fixture",
                    )

                cognition = type(
                    "ProbeCognition", (), {"invoke": staticmethod(_invoke)}
                )()
                self._configure_cognition(resident, cognition)
                server = ResidentRpcServer(resident=resident)
                server.work.create_thread(
                    thread_id="team-probe", title="XX 项目"
                )
                server.work.attach_workspace(
                    "team-probe", workspace, name="Team Workspace"
                )
                response = server.handle(
                    {
                        "id": "team-probe-start",
                        "method": "work_start",
                        "params": {
                            "thread_id": "team-probe",
                            "task": "给 XX 项目组个团队",
                        },
                    }
                )
                self.assertTrue(response["ok"], response)

                soul_path = workspace / "agents" / "调研-01" / "SOUL.md"
                edited = False
                for _ in range(120):
                    resident.live_once()
                    if len(questions) >= 1 and not edited:
                        # The first dispatch materialized the files; a
                        # SOUL.md edit must land in the NEXT question.
                        self.assertTrue(
                            soul_path.is_file(),
                            "product path did not materialize persona files",
                        )
                        soul_path.write_text(
                            "探针人格：本轮必须提到香蕉。",
                            encoding="utf-8",
                        )
                        edited = True
                    if len(questions) >= 2:
                        break
                self.assertTrue(edited, "first specialist question never arrived")
                self.assertGreaterEqual(
                    len(questions), 2, "second specialist question never arrived"
                )
                self.assertIn("香蕉", questions[1])
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
