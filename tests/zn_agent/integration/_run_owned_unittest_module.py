from __future__ import annotations

"""Run only TestCase classes defined by one interactive Contract module.

Several interactive modules import helper TestCase classes from sibling files.
Plain ``python test_module.py`` lets ``unittest.main()`` discover those imported
classes too, which silently re-runs GUI fixtures and defeats module isolation.
This loader keeps the existing module-by-module workflow but admits only classes
whose ``__module__`` is the file currently being executed.
"""

import importlib.util
import pathlib
import sys
import unittest


def load_owned_tests(path: pathlib.Path) -> unittest.TestSuite:
    path = path.resolve()
    module_name = f"_zn_owned_{path.stem}_{abs(hash(str(path)))}"
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))

    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load test module: {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    owned_classes = 0
    for name in sorted(vars(module)):
        value = getattr(module, name)
        if (
            isinstance(value, type)
            and issubclass(value, unittest.TestCase)
            and value is not unittest.TestCase
            and value.__module__ == module_name
        ):
            suite.addTests(loader.loadTestsFromTestCase(value))
            owned_classes += 1

    if owned_classes == 0:
        raise RuntimeError(f"no TestCase classes defined by test module: {path}")
    return suite


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: _run_owned_unittest_module.py <test-file>", file=sys.stderr)
        return 2
    suite = load_owned_tests(pathlib.Path(argv[1]))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
