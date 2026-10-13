from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zn_agent.core.capability_promotion import (
    describe_capability_source,
    promote_capability,
    test_capability_source,
    validate_capability_source,
)

GOOD = '''"""Demo capability for tests. Trigger: never (test only). Side-effects: none."""

class Cap:
    name = "demo-cap"
    priority = 0
    replay_safe = True
    def match(self, event):
        return 0.0
    def execute(self, event, state):
        return None

def build_capability():
    return Cap()

def self_test():
    return True
'''

NO_BUILDER = """
def something_else():
    pass
"""

SYNTAX_ERROR = "def broken(:\n    pass"

REQUIRED_ARG = """
def build_capability(name):
    return None
"""

NO_EXECUTE = '''"""Bad capability missing execute."""
class Cap:
    name = "bad-cap"
    def match(self, event):
        return 0.0

def build_capability():
    return Cap()
'''

FAILING_SELF_TEST = GOOD.replace("return True", 'return "boom"')

RAISING_SELF_TEST = GOOD.replace(
    "def self_test():\n    return True",
    "def self_test():\n    raise RuntimeError('x')",
)

SLOW_SELF_TEST = GOOD.replace(
    "def self_test():\n    return True",
    "def self_test():\n    import time\n    time.sleep(30)\n    return True",
)


class ValidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def write(self, name, text):
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_good_source_passes(self):
        self.assertEqual(validate_capability_source(self.write("good.py", GOOD)), [])

    def test_syntax_error(self):
        violations = validate_capability_source(self.write("bad.py", SYNTAX_ERROR))
        self.assertTrue(any("syntax" in v for v in violations))

    def test_missing_builder(self):
        violations = validate_capability_source(self.write("nob.py", NO_BUILDER))
        self.assertTrue(any("build_capability" in v for v in violations))

    def test_required_arg_rejected(self):
        violations = validate_capability_source(self.write("arg.py", REQUIRED_ARG))
        self.assertTrue(any("no required arguments" in v for v in violations))

    def test_bad_stem(self):
        violations = validate_capability_source(self.write("Bad Name.py", GOOD))
        self.assertTrue(any("stem" in v for v in violations))

    def test_non_python_rejected(self):
        violations = validate_capability_source(self.write("cap.txt", GOOD))
        self.assertTrue(any(".py" in v for v in violations))

    def test_missing_file(self):
        violations = validate_capability_source(self.tmp / "nope.py")
        self.assertTrue(any("not found" in v for v in violations))

    def test_missing_docstring(self):
        violations = validate_capability_source(
            self.write("nodoc.py", "def build_capability():\n    return None\n")
        )
        self.assertTrue(any("docstring" in v for v in violations))

    def test_describe_extracts_docstring(self):
        path = self.write("good.py", GOOD)
        info = describe_capability_source(path)
        self.assertIn("Demo capability", info["docstring"])
        self.assertIn("build_capability", info["top_level_names"])
        self.assertIn("Cap", info["top_level_names"])

    def test_describe_broken_file(self):
        path = self.write("bad.py", SYNTAX_ERROR)
        info = describe_capability_source(path)
        self.assertIsNone(info["docstring"])


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def write(self, name, text):
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_good_capability(self):
        report = test_capability_source(self.write("good.py", GOOD))
        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["name"], "demo-cap")

    def test_missing_execute(self):
        report = test_capability_source(self.write("bad.py", NO_EXECUTE))
        self.assertFalse(report["ok"])
        self.assertTrue(any("execute" in i for i in report["issues"]))

    def test_failing_self_test(self):
        report = test_capability_source(self.write("st.py", FAILING_SELF_TEST))
        self.assertFalse(report["ok"])
        self.assertTrue(any("self_test" in i for i in report["issues"]))

    def test_raising_self_test(self):
        report = test_capability_source(self.write("st2.py", RAISING_SELF_TEST))
        self.assertFalse(report["ok"])

    def test_timeout(self):
        report = test_capability_source(
            self.write("slow.py", SLOW_SELF_TEST), timeout_seconds=2
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any("timed out" in i for i in report["issues"]))


class PromoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.promoted = self.tmp / "promoted"

    def candidate(self, text, name="cand.py"):
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_promote_good(self):
        report = promote_capability(
            self.candidate(GOOD), promoted_root=self.promoted
        )
        self.assertTrue(report.promoted, report.problems())
        self.assertEqual(report.capability_name, "demo-cap")
        self.assertIn("Demo capability", report.description or "")
        self.assertTrue((self.promoted / "cand.py").is_file())

    def test_promote_bad_validate(self):
        report = promote_capability(
            self.candidate(NO_BUILDER, "bad.py"), promoted_root=self.promoted
        )
        self.assertFalse(report.promoted)
        self.assertTrue(report.violations)
        self.assertFalse((self.promoted / "bad.py").exists())

    def test_promote_bad_test(self):
        report = promote_capability(
            self.candidate(NO_EXECUTE, "bad2.py"), promoted_root=self.promoted
        )
        self.assertFalse(report.promoted)
        self.assertTrue(report.test_issues)

    def test_idempotent_same_content(self):
        first = promote_capability(
            self.candidate(GOOD, "idem.py"), promoted_root=self.promoted
        )
        second = promote_capability(
            self.candidate(GOOD, "idem.py"), promoted_root=self.promoted
        )
        self.assertTrue(first.promoted and second.promoted)

    def test_collision_different_content_refused(self):
        promote_capability(
            self.candidate(GOOD, "clash.py"), promoted_root=self.promoted
        )
        other = GOOD.replace("demo-cap", "other-cap")
        report = promote_capability(
            self.candidate(other, "clash.py"), promoted_root=self.promoted
        )
        self.assertFalse(report.promoted)
        self.assertTrue(any("different content" in v for v in report.violations))


if __name__ == "__main__":
    unittest.main()
