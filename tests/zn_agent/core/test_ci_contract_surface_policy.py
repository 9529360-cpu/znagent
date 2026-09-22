from __future__ import annotations

import re
import unittest
from pathlib import Path


_RETIRED_FRAGMENT = bytes.fromhex("653265").decode("ascii")
_NUMBERED_STORY = re.compile(rf"{_RETIRED_FRAGMENT}[-_]?\d+", re.IGNORECASE)
_ACTIVE_TEXT_SUFFIXES = {".md", ".py", ".ps1", ".js", ".mjs", ".ts", ".tsx", ".yml", ".yaml"}


class CiContractSurfacePolicyTests(unittest.TestCase):
    """Keep active product and CI surfaces capability/contract-owned."""

    @staticmethod
    def _root() -> Path:
        return Path(__file__).resolve().parents[3]

    def test_retired_story_namespace_is_absent_from_active_paths(self) -> None:
        root = self._root()
        scan_roots = (
            root / ".github" / "workflows",
            root / "runtime" / "python" / "zn_agent" / "core",
            root / "tests" / "zn_agent",
            root / "docs",
        )
        offenders: list[str] = []
        for scan_root in scan_roots:
            if not scan_root.exists():
                continue
            for path in scan_root.rglob("*"):
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
        candidates = [
            root / ".agent" / "HANDOFF.md",
            *list((root / "docs").rglob("*")),
            *list((root / "runtime" / "python" / "zn_agent" / "core").rglob("*")),
            *list((root / ".github" / "workflows").rglob("*")),
        ]
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
            "numbered scenario identifiers remain in active sources:\n" + "\n".join(offenders),
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


if __name__ == "__main__":
    unittest.main()
