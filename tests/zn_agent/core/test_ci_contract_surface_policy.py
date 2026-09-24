from __future__ import annotations

import py_compile
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


_RETIRED_FRAGMENT = bytes.fromhex("653265").decode("ascii")
_NUMBERED_STORY = re.compile(rf"{_RETIRED_FRAGMENT}[-_]?\d+", re.IGNORECASE)
_ACTIVE_TEXT_SUFFIXES = {".md", ".py", ".ps1", ".js", ".mjs", ".ts", ".tsx", ".yml", ".yaml"}


_PATH_SCOPES = (".github/workflows", "runtime/python/zn_agent/core", "tests/zn_agent", "docs")
_TEXT_SCOPES = (*_PATH_SCOPES, ".agent", ".github/scripts", "AGENTS.md", "ZN.md")


def _active_paths(root: Path, scopes: tuple[str, ...]) -> list[Path]:
    """Scan tracked and new source, not ignored build/cache leftovers.

    Tracked paths remain in scope even if an ignore rule would hide a new file
    at that location. Non-ignored untracked source is included before commit.
    NUL-delimited output preserves spaces and Unicode on Windows as well.
    Git errors fail the guard rather than silently returning an empty tree.
    """
    output = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "--cached", "--others",
         "--exclude-standard", "-z", "--", *scopes],
        timeout=30,
    )
    relative_paths = {
        raw.decode("utf-8", errors="surrogateescape")
        for raw in output.split(b"\0") if raw
    }
    paths = [root / relative for relative in sorted(relative_paths)]
    # A deleted tracked file is absent from the working tree, not stale source.
    return [path for path in paths if path.exists() or path.is_symlink()]


class CiContractSurfacePolicyTests(unittest.TestCase):
    """Keep active product and CI surfaces capability/contract-owned."""

    @staticmethod
    def _root() -> Path:
        return Path(__file__).resolve().parents[3]

    def test_retired_story_namespace_is_absent_from_active_paths(self) -> None:
        root = self._root()
        offenders: list[str] = []
        for path in _active_paths(root, _PATH_SCOPES):
            relative = path.relative_to(root).as_posix()
            parts = [part.casefold() for part in path.relative_to(root).parts]
            if (
                _RETIRED_FRAGMENT in relative.casefold()
                or _NUMBERED_STORY.search(relative)
                or _RETIRED_FRAGMENT in parts
            ):
                offenders.append(relative)
        self.assertEqual(offenders, [], "retired scenario paths remain:\n" + "\n".join(offenders))

    def test_active_sources_do_not_reference_numbered_story_ids(self) -> None:
        root = self._root()
        candidates = _active_paths(root, _TEXT_SCOPES)
        offenders: list[str] = []
        for path in candidates:
            if not path.is_file() or path.suffix.lower() not in _ACTIVE_TEXT_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8")
            if _NUMBERED_STORY.search(text):
                offenders.append(path.relative_to(root).as_posix())
        self.assertEqual(
            offenders,
            [],
            "retired scenario terminology remains in active sources:\n" + "\n".join(offenders),
        )

    def test_required_automatic_gates_are_contract_named(self) -> None:
        root = self._root()
        workflows = root / ".github" / "workflows"
        required = (
            "zn-managed-browser-contract.yml",
            "zn-windows-interactive-contract.yml",
            "zn-work-recovery-contract.yml",
            "zn-atomic-overwrite-contract.yml",
        )
        for name in required:
            with self.subTest(name=name):
                path = workflows / name
                self.assertTrue(path.is_file(), f"missing automatic contract gate: {name}")
                text = path.read_text(encoding="utf-8")
                self.assertIn("pull_request:", text)
                self.assertIn("push:", text)


class CiContractPathSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self._git("init", "--quiet")
        (self.root / ".gitignore").write_text(
            "__pycache__/\n*.pyc\n*.pyo\ngenerated/\n", encoding="utf-8"
        )
        self.guard = CiContractSurfacePolicyTests()
        self.guard._root = lambda: self.root

    def _git(self, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True, capture_output=True, timeout=30,
        )

    def _write(self, relative: str, text: str = "value = 1\n") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_deleted_module_bytecode_does_not_pollute_source_guard(self) -> None:
        source = self._write(
            f"runtime/python/zn_agent/core/retired_{_RETIRED_FRAGMENT}37.py"
        )
        cache = Path(py_compile.compile(str(source), doraise=True))
        source.unlink()
        self.assertTrue(cache.is_file(), "exercise real leftover Python bytecode")
        self.assertNotIn(cache, _active_paths(self.root, _PATH_SCOPES))
        self.guard.test_retired_story_namespace_is_absent_from_active_paths()
        self.guard.test_active_sources_do_not_reference_numbered_story_ids()
        self.assertTrue(cache.is_file(), "the guard must not delete developer caches")

    def test_new_untracked_retired_source_is_still_rejected(self) -> None:
        path = self._write(f"tests/zn_agent/retired_{_RETIRED_FRAGMENT}37.py")
        self.assertIn(path, _active_paths(self.root, _PATH_SCOPES))
        with self.assertRaisesRegex(AssertionError, "retired scenario paths"):
            self.guard.test_retired_story_namespace_is_absent_from_active_paths()

    def test_tracked_ignored_content_cannot_hide_from_the_guard(self) -> None:
        path = self._write(
            f"docs/generated/retired_{_RETIRED_FRAGMENT}37.md",
            f"retired marker {_RETIRED_FRAGMENT}37\n",
        )
        self.assertNotIn(path, _active_paths(self.root, _TEXT_SCOPES))
        self._git("add", "-f", "--", path.relative_to(self.root).as_posix())
        self.assertIn(path, _active_paths(self.root, _TEXT_SCOPES))
        with self.assertRaisesRegex(AssertionError, "retired scenario paths"):
            self.guard.test_retired_story_namespace_is_absent_from_active_paths()
        with self.assertRaisesRegex(AssertionError, "retired scenario terminology"):
            self.guard.test_active_sources_do_not_reference_numbered_story_ids()

    def test_new_text_with_spaces_and_unicode_is_scanned_before_commit(self) -> None:
        path = self._write("docs/context \u77e5\u8bc6 notes.md", f"{_RETIRED_FRAGMENT}37\n")
        self.assertIn(path, _active_paths(self.root, _TEXT_SCOPES))
        with self.assertRaisesRegex(AssertionError, "retired scenario terminology"):
            self.guard.test_active_sources_do_not_reference_numbered_story_ids()

    def test_deleted_tracked_file_is_not_read_as_active_source(self) -> None:
        path = self._write(f"docs/retired_{_RETIRED_FRAGMENT}37.md")
        self._git("add", "--", path.relative_to(self.root).as_posix())
        path.unlink()
        self.assertNotIn(path, _active_paths(self.root, _TEXT_SCOPES))
        self.guard.test_retired_story_namespace_is_absent_from_active_paths()
        self.guard.test_active_sources_do_not_reference_numbered_story_ids()


if __name__ == "__main__":
    unittest.main()
