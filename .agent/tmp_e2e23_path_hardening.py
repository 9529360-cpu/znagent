from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


owner = Path("runtime/python/zn_agent/core/broad_goal_coding_resident.py")
text = owner.read_text(encoding="utf-8").replace("\r\n", "\n")
text = replace_once(
    text,
    "Windows reparse point before ``os.walk`` may descend through it. The same\n",
    "Windows reparse point before ``os.scandir`` may descend through it. The same\n",
    "scandir docstring",
)
text = replace_once(
    text,
    """            while pending:\n                current_path, depth = pending.pop()\n                with os.scandir(current_path) as entries:\n""",
    """            while pending:\n                current_path, depth = pending.pop()\n                if not cls._plain_discovery_entry(current_path, directory=True):\n                    return None\n                try:\n                    current_path = current_path.resolve(strict=True)\n                    current_path.relative_to(root_path)\n                except (OSError, RuntimeError, ValueError):\n                    return None\n                with os.scandir(current_path) as entries:\n""",
    "queued-directory revalidation",
)
text = replace_once(
    text,
    "                        candidates[relative_candidate.casefold()] = resolved\n",
    "                        candidates[relative_candidate] = resolved\n",
    "case-preserving candidate identity",
)
owner.write_text(text, encoding="utf-8", newline="\n")


tests = Path("tests/zn_agent/core/test_e2e23_command_path_replan.py")
text = tests.read_text(encoding="utf-8").replace("\r\n", "\n")
marker = """    def test_generated_vendor_tree_is_not_accepted_as_replacement_authority(self) -> None:\n"""
added = '''    def test_case_distinct_candidate_paths_remain_ambiguous(self) -> None:\n        with tempfile.TemporaryDirectory() as tmp:\n            root = Path(tmp).resolve()\n            expected = root / "expected" / "probe.py"\n            upper_dir = root / "A"\n            lower_dir = root / "a"\n            upper_file = upper_dir / "probe.py"\n            lower_file = lower_dir / "probe.py"\n\n            class _Entry:\n                def __init__(self, name: str) -> None:\n                    self.name = name\n\n            class _Scandir:\n                def __init__(self, path) -> None:\n                    current = Path(path)\n                    if current == root:\n                        rows = [_Entry("A"), _Entry("a")]\n                    elif current == upper_dir or current == lower_dir:\n                        rows = [_Entry("probe.py")]\n                    else:\n                        rows = []\n                    self._iterator = iter(rows)\n\n                def __enter__(self):\n                    return self\n\n                def __exit__(self, exc_type, exc, tb):\n                    return False\n\n                def __iter__(self):\n                    return self\n\n                def __next__(self):\n                    return next(self._iterator)\n\n            original_resolve = Path.resolve\n            original_is_file = Path.is_file\n\n            def resolve_path(path, strict=False):\n                current = Path(path)\n                if current == expected:\n                    raise FileNotFoundError(str(current))\n                if current in {root, upper_dir, lower_dir, upper_file, lower_file}:\n                    return current\n                return original_resolve(current, strict=strict)\n\n            def is_file(path):\n                current = Path(path)\n                if current in {upper_file, lower_file}:\n                    return True\n                return original_is_file(current)\n\n            def plain_entry(path, *, directory: bool):\n                current = Path(path)\n                if directory:\n                    return current in {root, upper_dir, lower_dir}\n                return current in {upper_file, lower_file}\n\n            with (\n                patch.object(Path, "resolve", new=resolve_path),\n                patch.object(Path, "is_file", new=is_file),\n                patch.object(\n                    BroadGoalCodingResidentRuntime,\n                    "_plain_discovery_entry",\n                    side_effect=plain_entry,\n                ),\n                patch(\n                    "zn_agent.core.broad_goal_coding_resident.os.scandir",\n                    side_effect=_Scandir,\n                ),\n            ):\n                self.assertIsNone(\n                    BroadGoalCodingResidentRuntime._resolve_workspace_python_script(\n                        root,\n                        Path("expected/probe.py"),\n                    )\n                )\n\n    def test_queued_directory_is_revalidated_immediately_before_scanning(self) -> None:\n        with tempfile.TemporaryDirectory() as tmp:\n            root = Path(tmp).resolve()\n            queued = root / "queued"\n            target = queued / "probe.py"\n            queued.mkdir()\n            target.write_text("print('must not discover after replacement')\\n", encoding="utf-8")\n\n            real_lstat = os.lstat\n            reparse_attribute = int(\n                getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x00000400)\n            )\n            queued_lstat_calls = 0\n\n            def lstat_with_stale_queue(path):\n                nonlocal queued_lstat_calls\n                metadata = real_lstat(path)\n                if Path(path) == queued:\n                    queued_lstat_calls += 1\n                    if queued_lstat_calls >= 2:\n                        return SimpleNamespace(\n                            st_mode=metadata.st_mode,\n                            st_file_attributes=reparse_attribute,\n                        )\n                return metadata\n\n            with patch(\n                "zn_agent.core.broad_goal_coding_resident.os.lstat",\n                side_effect=lstat_with_stale_queue,\n            ):\n                self.assertIsNone(\n                    BroadGoalCodingResidentRuntime._resolve_workspace_python_script(\n                        root,\n                        Path("expected/probe.py"),\n                    )\n                )\n            self.assertGreaterEqual(queued_lstat_calls, 2)\n\n'''
text = replace_once(text, marker, added + marker, "path-hardening regressions")
tests.write_text(text, encoding="utf-8", newline="\n")
