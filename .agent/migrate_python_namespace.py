from __future__ import annotations

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
OLD_TESTS = ROOT / "tests" / "agent" / "kernel"
NEW_TESTS = ROOT / "tests" / "zn_agent" / "core"


def replace_text(path: Path, replacements: tuple[tuple[str, str], ...]) -> None:
    text = path.read_text(encoding="utf-8")
    for old, new in replacements:
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    if not OLD_TESTS.is_dir():
        raise SystemExit("expected tests/agent/kernel to exist")
    if NEW_TESTS.exists():
        raise SystemExit("tests/zn_agent/core already exists")

    NEW_TESTS.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(OLD_TESTS), str(NEW_TESTS))

    replacements = (
        ("tests/agent/kernel", "tests/zn_agent/core"),
        ("agent/kernel", "runtime/python/zn_agent/core"),
        ("agent.kernel", "zn_agent.core"),
        ("agent/__init__.py", "runtime/python/zn_agent/__init__.py"),
        ("uv run python -m unittest discover", "python -m unittest discover"),
        (
            'REPO_ROOT / "agent" / "kernel"',
            'REPO_ROOT / "runtime" / "python" / "zn_agent" / "core"',
        ),
        (
            "REPO_ROOT / 'agent' / 'kernel'",
            "REPO_ROOT / 'runtime' / 'python' / 'zn_agent' / 'core'",
        ),
    )
    for path in sorted(NEW_TESTS.rglob("*.py")):
        replace_text(path, replacements)

    # The broad dotted-namespace replacement above must not rewrite assertions
    # that deliberately prove the old runtime command is absent.
    autostart_test = NEW_TESTS / "test_resident_autostart.py"
    text = autostart_test.read_text(encoding="utf-8")
    text = text.replace(
        'self.assertNotIn("zn_agent.core.resident_server", unit)',
        'self.assertNotIn("agent.kernel.resident_server", unit)',
    )
    text = text.replace(
        'self.assertNotIn("zn_agent.core.resident_server", arguments or "")',
        'self.assertNotIn("agent.kernel.resident_server", arguments or "")',
    )
    autostart_test.write_text(text, encoding="utf-8")

    semantics = ROOT / "runtime" / "python" / "zn_agent" / "core" / "repo_test_semantics.py"
    text = semantics.read_text(encoding="utf-8")
    text = text.replace("tests/agent/kernel", "tests/zn_agent/core")
    text = text.replace("agent/kernel", "runtime/python/zn_agent/core")
    text = text.replace("agent.kernel", "zn_agent.core")
    text = text.replace(
        '    "uv",\n    "run",\n    "python",',
        '    "python",',
    )
    text = text.replace("len(target.parts) != 3", "len(target.parts) != 5")
    text = text.replace(
        "PurePosixPath(*target.parts[:2]) != ZN_KERNEL_SOURCE_DIR",
        "PurePosixPath(*target.parts[:4]) != ZN_KERNEL_SOURCE_DIR",
    )
    semantics.write_text(text, encoding="utf-8")

    # Resident-formed repo tests must execute the current working-tree package,
    # never the already-installed copy that happens to host the resident.
    procedural = ROOT / "runtime" / "python" / "zn_agent" / "core" / "procedural_resident.py"
    text = procedural.read_text(encoding="utf-8")
    old = '''                        command = self._targeted_unittest_command(targeted_baseline)\n                        test_observation = self.body.act(\n                            "command",\n                            event_id=event.event_id,\n                            command=command,\n                            workdir=str(targeted_baseline.get("root") or ""),\n                            timeout=float(\n'''
    new = '''                        command = self._targeted_unittest_command(targeted_baseline)\n                        command_env: dict[str, str] = {}\n                        source_root_relative = self._literal_repo_relative_path(\n                            targeted_baseline.get("python_source_root_relative")\n                        )\n                        if source_root_relative:\n                            try:\n                                repo_root = Path(\n                                    str(targeted_baseline.get("root") or "")\n                                ).expanduser().resolve(strict=True)\n                                lexical_source_root = Path(\n                                    os.path.abspath(\n                                        str(repo_root / Path(source_root_relative))\n                                    )\n                                )\n                                source_root = lexical_source_root.resolve(strict=True)\n                                source_root.relative_to(repo_root)\n                                if (\n                                    source_root != lexical_source_root\n                                    or not source_root.is_dir()\n                                ):\n                                    raise ValueError(\n                                        "targeted unittest source root is not one regular repository directory"\n                                    )\n                            except (OSError, RuntimeError, ValueError):\n                                problems.append(\n                                    "targeted unittest working-tree source root no longer resolves safely"\n                                )\n                            else:\n                                command_env["PYTHONPATH"] = str(source_root)\n\n                        if problems:\n                            test_observation = None\n                        else:\n                            test_observation = self.body.act(\n                                "command",\n                                event_id=event.event_id,\n                                command=command,\n                                workdir=str(targeted_baseline.get("root") or ""),\n                                env=command_env,\n                                timeout=float(\n'''
    if old not in text:
        raise SystemExit("targeted unittest execution block changed unexpectedly")
    text = text.replace(old, new, 1)
    # The rest of the verification block consumes a real observation. The
    # source-root failure above is already fail-closed before command execution.
    text = text.replace(
        '''                            ),\n                            max_output_chars=50_000,\n                        )\n                        result_features = normalize_action_result(\n                            asdict(test_observation),\n                            command=command,\n                        )\n''',
        '''                                ),\n                                max_output_chars=50_000,\n                            )\n                        if test_observation is None:\n                            result_features = {\n                                "masked_success": False,\n                                "failure_class": "working_tree_source_unavailable",\n                            }\n                            exit_code = None\n                            timed_out = False\n                            test_verified = False\n                        else:\n                            result_features = normalize_action_result(\n                                asdict(test_observation),\n                                command=command,\n                            )\n                            exit_code = test_observation.data.get("exit_code")\n                            timed_out = bool(test_observation.data.get("timed_out", False))\n                            test_verified = bool(\n                                test_observation.success\n                                and not timed_out\n                                and exit_code == 0\n                                and not bool(result_features.get("masked_success"))\n                                and not result_features.get("failure_class")\n                            )\n''',
        1,
    )
    # Remove the old duplicate exit/test_verified calculation and make the
    # durable marker tolerate the fail-before-execution path.
    old_duplicate = '''                        exit_code = test_observation.data.get("exit_code")\n                        timed_out = bool(test_observation.data.get("timed_out", False))\n                        test_verified = bool(\n                            test_observation.success\n                            and not timed_out\n                            and exit_code == 0\n                            and not bool(result_features.get("masked_success"))\n                            and not result_features.get("failure_class")\n                        )\n'''
    text = text.replace(old_duplicate, "", 1)
    text = text.replace(
        '"action_id": test_observation.action_id,\n                            "verified": test_verified,',
        '"action_id": (test_observation.action_id if test_observation is not None else None),\n                            "verified": test_verified,',
        1,
    )
    text = text.replace(
        '"execution_action_id": test_observation.action_id,',
        '"execution_action_id": (test_observation.action_id if test_observation is not None else None),',
        1,
    )
    procedural.write_text(text, encoding="utf-8")

    workflow = ROOT / ".github" / "workflows" / "zn-ci.yml"
    text = workflow.read_text(encoding="utf-8")
    text = text.replace(
        "          cache-dependency-glob: |\n            uv.lock\n            runtime/python/pyproject.toml",
        "          cache-dependency-glob: runtime/python/pyproject.toml",
    )
    text = text.replace(
        "      - name: Install locked repository test dependencies\n        run: uv sync --frozen --extra dev\n\n",
        "",
    )
    text = text.replace(
        "      - name: Install isolated ZN runtime distribution\n        run: |\n          uv venv .ci/runtime-venv --python 3.12\n          uv pip install --python .ci/runtime-venv/bin/python runtime/python",
        "      - name: Install isolated ZN runtime distribution\n        run: |\n          uv venv .ci/runtime-venv --python 3.12\n          uv pip install --python .ci/runtime-venv/bin/python runtime/python\n          echo \"$GITHUB_WORKSPACE/.ci/runtime-venv/bin\" >> \"$GITHUB_PATH\"",
    )
    text = text.replace(".ci/runtime-venv/bin/python -I -", "python -I -")
    text = text.replace(
        "run: uv run python -m compileall -q agent/kernel",
        "run: python -m compileall -q runtime/python/zn_agent/core",
    )
    text = text.replace(
        "run: uv run python -m unittest discover -s tests/agent/kernel -p 'test_*.py' -v",
        "run: python -m unittest discover -s tests/zn_agent/core -p 'test_*.py' -v",
    )
    workflow.write_text(text, encoding="utf-8")

    temporary_workflow = ROOT / ".github" / "workflows" / "zn-python-namespace-migration.yml"
    if temporary_workflow.exists():
        temporary_workflow.unlink()

    # This script is one-shot and removes itself from the verified migration commit.
    Path(__file__).unlink()


if __name__ == "__main__":
    main()
