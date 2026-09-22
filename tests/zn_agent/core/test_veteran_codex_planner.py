from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zn_agent.core.veteran_codex_planner import (
    build_codex_planner_prompt,
    disposable_planner_clone,
    run_codex_planner,
    validate_codex_task_plan,
    validate_veteran_planner_input,
)
from zn_agent.core.veteran_engineering import (
    VeteranCodexWorker,
    VeteranSidecarError,
)


def planner_payload() -> dict:
    return {
        "protocol": "veteran-planner-v1",
        "project": {
            "id": "project-1",
            "repoPath": "C:/repo",
            "sourceIdentity": {"head": "abc"},
            "sourceAuthority": {"scope": "checkout"},
        },
        "mission": {
            "goal": "Add a bounded feature.",
            "doneDefinition": "Focused tests pass.",
            "nonGoals": ["Do not release."],
            "riskEnvelope": "medium",
        },
        "projectAwareness": {"runtimeFamilies": ["python"]},
        "projectExperience": [],
    }


class VeteranCodexPlannerTests(unittest.TestCase):
    def test_input_contract_and_prompt_are_bounded(self) -> None:
        safe = validate_veteran_planner_input(planner_payload())
        self.assertEqual(safe["mission"]["goal"], "Add a bounded feature.")
        self.assertEqual(safe["limits"]["maxTasks"], 16)
        prompt = build_codex_planner_prompt(planner_payload())
        self.assertIn("read-only planning phase", prompt)
        self.assertIn("never use '.'", prompt)

        broken = planner_payload()
        broken["protocol"] = "wrong"
        with self.assertRaises(ValueError):
            validate_veteran_planner_input(broken)

    def test_plan_rejects_broad_escape_and_unknown_dependency(self) -> None:
        with self.assertRaises(ValueError):
            validate_codex_task_plan(
                {
                    "tasks": [
                        {
                            "id": "T1",
                            "contract": "change everything",
                            "owner": "repo",
                            "writeSet": ["."],
                            "risk": "low",
                        }
                    ]
                }
            )
        with self.assertRaises(ValueError):
            validate_codex_task_plan(
                {
                    "tasks": [
                        {
                            "id": "T1",
                            "contract": "change app",
                            "owner": "app.py",
                            "dependencies": ["T9"],
                            "writeSet": ["app.py"],
                            "risk": "low",
                        }
                    ]
                }
            )

    def test_plan_normalizes_only_declared_task_surface(self) -> None:
        plan = validate_codex_task_plan(
            {
                "tasks": [
                    {
                        "id": "T1",
                        "contract": "Update app.",
                        "owner": "app.py",
                        "dependencies": [],
                        "writeSet": ["src\\app.py", "src/app.py"],
                        "protectedPaths": ["docs"],
                        "risk": "low",
                        "notes": "bounded",
                        "extra": "ignored",
                    }
                ]
            }
        )
        self.assertEqual(plan["tasks"][0]["writeSet"], ["src/app.py"])
        self.assertEqual(plan["tasks"][0]["protectedPaths"], ["docs"])
        self.assertNotIn("extra", plan["tasks"][0])

    def test_codex_invocation_is_disposable_ephemeral_and_schema_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_repo = root / "source"
            source_repo.mkdir()
            planner_repo = root / "planner-worktree"
            planner_repo.mkdir()
            command = root / "codex.exe"
            command.write_text("fixture", encoding="utf-8")
            home = root / "codex-home"
            home.mkdir()
            worker = VeteranCodexWorker(
                command=command,
                codex_home=home,
                windows_sandbox="unelevated",
            )
            observed: dict[str, object] = {}

            def fake_run(argv, **kwargs):
                observed["argv"] = list(argv)
                observed["kwargs"] = dict(kwargs)
                result_path = Path(argv[argv.index("--output-last-message") + 1])
                result_path.write_text(
                    json.dumps(
                        {
                            "tasks": [
                                {
                                    "id": "T1",
                                    "contract": "Update app.py.",
                                    "owner": "app.py",
                                    "dependencies": [],
                                    "writeSet": ["app.py"],
                                    "risk": "low",
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(argv, 0, "", "")

            class _PlannerClone:
                def __enter__(self):
                    return planner_repo

                def __exit__(self, exc_type, exc, tb):
                    return False

            with (
                patch(
                    "zn_agent.core.veteran_codex_planner.discover_veteran_codex_worker",
                    return_value=worker,
                ),
                patch(
                    "zn_agent.core.veteran_codex_planner.disposable_planner_clone",
                    return_value=_PlannerClone(),
                ),
                patch(
                    "zn_agent.core.veteran_codex_planner.subprocess.run",
                    side_effect=fake_run,
                ),
            ):
                result = run_codex_planner(
                    planner_payload(),
                    cwd=source_repo,
                    env={},
                )

            argv = observed["argv"]
            assert isinstance(argv, list)
            self.assertIn("--sandbox", argv)
            self.assertEqual(argv[argv.index("--sandbox") + 1], "workspace-write")
            self.assertIn("--ephemeral", argv)
            self.assertIn("--ignore-user-config", argv)
            self.assertIn("--ignore-rules", argv)
            self.assertIn("--output-schema", argv)
            self.assertIn('windows.sandbox="unelevated"', argv)
            self.assertEqual(argv[argv.index("-C") + 1], str(planner_repo))
            kwargs = observed["kwargs"]
            assert isinstance(kwargs, dict)
            self.assertEqual(kwargs["cwd"], str(planner_repo))
            prompt = str(kwargs["input"])
            escaped_planner_repo = json.dumps(str(planner_repo), ensure_ascii=False)[1:-1]
            self.assertIn(escaped_planner_repo, prompt)
            self.assertNotIn("C:/repo", prompt)
            self.assertEqual(result["tasks"][0]["writeSet"], ["app.py"])

    def test_non_windows_worker_keeps_true_read_only_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_repo = root / "source"
            source_repo.mkdir()
            command = root / "codex"
            command.write_text("fixture", encoding="utf-8")
            home = root / "codex-home"
            home.mkdir()
            worker = VeteranCodexWorker(
                command=command,
                codex_home=home,
                windows_sandbox=None,
            )
            observed: dict[str, object] = {}

            def fake_run(argv, **kwargs):
                observed["argv"] = list(argv)
                observed["kwargs"] = dict(kwargs)
                result_path = Path(argv[argv.index("--output-last-message") + 1])
                result_path.write_text(
                    json.dumps(
                        {
                            "tasks": [
                                {
                                    "id": "T1",
                                    "contract": "Inspect then update app.py.",
                                    "owner": "app.py",
                                    "dependencies": [],
                                    "writeSet": ["app.py"],
                                    "risk": "low",
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(argv, 0, "", "")

            with (
                patch(
                    "zn_agent.core.veteran_codex_planner.discover_veteran_codex_worker",
                    return_value=worker,
                ),
                patch(
                    "zn_agent.core.veteran_codex_planner.subprocess.run",
                    side_effect=fake_run,
                ),
            ):
                result = run_codex_planner(
                    planner_payload(),
                    cwd=source_repo,
                    env={},
                )

            argv = observed["argv"]
            assert isinstance(argv, list)
            self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
            self.assertNotIn('windows.sandbox="unelevated"', argv)
            self.assertEqual(argv[argv.index("-C") + 1], str(source_repo.resolve()))
            self.assertEqual(result["tasks"][0]["writeSet"], ["app.py"])

    def test_disposable_planner_clone_is_independent_clean_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(
                ["git", "init", "-b", "main"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "zn@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "ZN Test"],
                cwd=repo,
                check=True,
            )
            (repo / "app.py").write_text("print('old')\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-m", "baseline"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

            with disposable_planner_clone(repo) as planner_repo:
                planner_path = str(planner_repo)
                self.assertNotEqual(planner_repo, repo)
                self.assertTrue((planner_repo / ".git").is_dir())
                self.assertEqual(
                    subprocess.run(
                        ["git", "rev-parse", "HEAD"],
                        cwd=planner_repo,
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout.strip(),
                    base,
                )
                self.assertEqual(
                    subprocess.run(
                        ["git", "remote"],
                        cwd=planner_repo,
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout.strip(),
                    "",
                )
                common_dir = subprocess.run(
                    ["git", "rev-parse", "--git-common-dir"],
                    cwd=planner_repo,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                resolved_common = Path(common_dir)
                if not resolved_common.is_absolute():
                    resolved_common = planner_repo / resolved_common
                self.assertEqual(
                    resolved_common.resolve(),
                    (planner_repo / ".git").resolve(),
                )

            self.assertFalse(Path(planner_path).exists())
            self.assertEqual(
                subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=repo,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout,
                "",
            )

            with self.assertRaisesRegex(
                VeteranSidecarError,
                "modified files",
            ):
                with disposable_planner_clone(repo) as planner_repo:
                    mutated_path = str(planner_repo)
                    (planner_repo / "app.py").write_text(
                        "print('planner mutation')\n",
                        encoding="utf-8",
                    )

            self.assertFalse(Path(mutated_path).exists())
            self.assertEqual((repo / "app.py").read_text(encoding="utf-8"), "print('old')\n")
            self.assertEqual(
                subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=repo,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip(),
                base,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
