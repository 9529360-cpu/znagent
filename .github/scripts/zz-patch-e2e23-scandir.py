from __future__ import annotations

from pathlib import Path

PRODUCT = Path("runtime/python/zn_agent/core/broad_goal_coding_resident.py")
TEST = Path("tests/zn_agent/core/test_e2e23_command_path_replan.py")

old_block = '''        candidates: dict[str, Path] = {}
        observed_entries = 0
        requested_name = requested.name.casefold()
        try:
            for current, directory_names, file_names in os.walk(
                root_path,
                topdown=True,
                followlinks=False,
            ):
                current_path = Path(current)
                relative_current = current_path.relative_to(root_path)
                depth = len(relative_current.parts)
                if depth >= cls._MAX_PATH_DISCOVERY_DEPTH:
                    directory_names[:] = []
                else:
                    directory_names[:] = [
                        name
                        for name in directory_names
                        if name.casefold() not in cls._PATH_DISCOVERY_PRUNE
                        and cls._plain_discovery_entry(
                            current_path / name,
                            directory=True,
                        )
                    ]

                observed_entries += len(directory_names) + len(file_names)
                if observed_entries > cls._MAX_PATH_DISCOVERY_ENTRIES:
                    return None

                for file_name in file_names:
                    if file_name.casefold() != requested_name:
                        continue
                    candidate = current_path / file_name
                    if not cls._plain_discovery_entry(candidate, directory=False):
                        continue
                    try:
                        resolved = candidate.resolve(strict=True)
                        resolved.relative_to(root_path)
                    except (OSError, RuntimeError, ValueError):
                        continue
                    if not resolved.is_file() or resolved.suffix.casefold() != ".py":
                        continue
                    relative_candidate = resolved.relative_to(root_path).as_posix()
                    candidates[relative_candidate.casefold()] = resolved
                    if len(candidates) > 1:
                        return None
        except (OSError, RuntimeError, ValueError):
            return None
'''

new_block = '''        candidates: dict[str, Path] = {}
        observed_entries = 0
        requested_name = requested.name.casefold()
        pending: list[tuple[Path, int]] = [(root_path, 0)]
        try:
            while pending:
                current_path, depth = pending.pop()
                child_directories: list[Path] = []
                with os.scandir(current_path) as entries:
                    for entry in entries:
                        observed_entries += 1
                        if observed_entries > cls._MAX_PATH_DISCOVERY_ENTRIES:
                            return None

                        entry_path = current_path / entry.name
                        if (
                            depth < cls._MAX_PATH_DISCOVERY_DEPTH
                            and entry.name.casefold() not in cls._PATH_DISCOVERY_PRUNE
                            and cls._plain_discovery_entry(
                                entry_path,
                                directory=True,
                            )
                        ):
                            child_directories.append(entry_path)

                        if entry.name.casefold() != requested_name:
                            continue
                        if not cls._plain_discovery_entry(
                            entry_path,
                            directory=False,
                        ):
                            continue
                        try:
                            resolved = entry_path.resolve(strict=True)
                            resolved.relative_to(root_path)
                        except (OSError, RuntimeError, ValueError):
                            continue
                        if not resolved.is_file() or resolved.suffix.casefold() != ".py":
                            continue
                        relative_candidate = resolved.relative_to(root_path).as_posix()
                        candidates[relative_candidate.casefold()] = resolved
                        if len(candidates) > 1:
                            return None

                for child in sorted(
                    child_directories,
                    key=lambda path: path.name.casefold(),
                    reverse=True,
                ):
                    pending.append((child, depth + 1))
        except (OSError, RuntimeError, ValueError):
            return None
'''

product = PRODUCT.read_text(encoding="utf-8")
if product.count(old_block) != 1:
    raise SystemExit(f"expected one os.walk discovery block, found {product.count(old_block)}")
PRODUCT.write_text(product.replace(old_block, new_block), encoding="utf-8", newline="\n")

anchor = "\n\nclass E2E23CommandPathReplanTests(unittest.TestCase):\n"
regression = r'''

    def test_discovery_entry_budget_stops_scandir_incrementally(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for index in range(6):
                (root / f"noise-{index}.txt").write_text("noise\n", encoding="utf-8")

            real_scandir = os.scandir
            observed_entries = 0

            class CountingScandir:
                def __init__(self, path) -> None:
                    self._inner = real_scandir(path)

                def __enter__(self):
                    self._inner.__enter__()
                    return self

                def __exit__(self, exc_type, exc, traceback):
                    return self._inner.__exit__(exc_type, exc, traceback)

                def __iter__(self):
                    return self

                def __next__(self):
                    nonlocal observed_entries
                    entry = next(self._inner)
                    observed_entries += 1
                    return entry

            with (
                patch.object(
                    BroadGoalCodingResidentRuntime,
                    "_MAX_PATH_DISCOVERY_ENTRIES",
                    3,
                ),
                patch(
                    "zn_agent.core.broad_goal_coding_resident.os.scandir",
                    side_effect=lambda path: CountingScandir(path),
                ),
            ):
                self.assertIsNone(
                    BroadGoalCodingResidentRuntime._resolve_workspace_python_script(
                        root,
                        Path("expected/probe.py"),
                    )
                )

            self.assertEqual(
                observed_entries,
                4,
                "bounded discovery must stop on the first entry beyond the budget",
            )
'''

test = TEST.read_text(encoding="utf-8")
if test.count(anchor) != 1:
    raise SystemExit(f"expected one E2E23 class anchor, found {test.count(anchor)}")
if "test_discovery_entry_budget_stops_scandir_incrementally" in test:
    raise SystemExit("incremental scandir regression already exists")
TEST.write_text(test.replace(anchor, regression + anchor), encoding="utf-8", newline="\n")
