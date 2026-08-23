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
