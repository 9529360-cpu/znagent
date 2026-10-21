from __future__ import annotations

import unittest

from zn_agent.core.floor_guard import check_diff


def _diff(path: str, body: str, *, old_path: str | None = None) -> str:
    """Build a minimal unified diff for one file from added/removed lines.

    ``body`` lines start with '+', '-', or ' ' (context). ``old_path``
    defaults to ``path``; use '/dev/null' for a new file and pass
    ``path='/dev/null'`` for a deleted file via _diff_deleted.
    """
    old = old_path if old_path is not None else path
    header = (
        f"diff --git a/{old} b/{path}\n"
        f"--- a/{old}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
    )
    return header + body


def _diff_deleted(path: str, body: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        "+++ /dev/null\n"
        "@@ -1 +1 @@\n" + body
    )


def _added(path: str, *lines: str) -> str:
    body = "".join(f"+{line}\n" for line in lines)
    return _diff(path, body)


def _violations(result) -> list[str]:
    return list(result.violations)


class FloorGuardSuppressionTests(unittest.TestCase):
    def test_noqa_flagged(self):
        result = check_diff(_added("a.py", "x = 1  # noqa"))
        self.assertFalse(result.passed)
        self.assertTrue(any("noqa" in v for v in _violations(result)))

    def test_noqa_with_code_flagged(self):
        result = check_diff(_added("a.py", "x = 1  # noqa: F401"))
        self.assertFalse(result.passed)
        self.assertTrue(any("noqa" in v for v in _violations(result)))

    def test_type_ignore_flagged(self):
        result = check_diff(_added("a.py", "x = foo()  # type: ignore[attr-defined]"))
        self.assertFalse(result.passed)
        self.assertTrue(any("type-ignore" in v for v in _violations(result)))

    def test_pylint_disable_flagged(self):
        result = check_diff(_added("a.py", "# pylint: disable=too-many-branches"))
        self.assertFalse(result.passed)
        self.assertTrue(any("pylint" in v for v in _violations(result)))

    def test_nosec_flagged(self):
        result = check_diff(_added("a.py", "os.system(cmd)  # nosec"))
        self.assertFalse(result.passed)
        self.assertTrue(any("nosec" in v for v in _violations(result)))

    def test_eslint_disable_flagged(self):
        result = check_diff(_added("a.ts", "const x = 1; // eslint-disable-next-line"))
        self.assertFalse(result.passed)
        self.assertTrue(any("eslint" in v for v in _violations(result)))

    def test_ts_ignore_flagged(self):
        result = check_diff(_added("a.ts", "// @ts-ignore"))
        self.assertFalse(result.passed)
        self.assertTrue(any("ts-ignore" in v for v in _violations(result)))

    def test_clean_diff_passes(self):
        result = check_diff(_added("a.py", "x = 1", "y = x + 2"))
        self.assertTrue(result.passed, result.violations)
        self.assertEqual(result.violations, ())

    def test_empty_diff_passes(self):
        self.assertTrue(check_diff("").passed)

    def test_prohibition_line_not_flagged(self):
        result = check_diff(
            _added("a.py", "# Do not add a # noqa comment here")
        )
        self.assertTrue(result.passed, result.violations)

    def test_never_use_skip_prohibition_not_flagged(self):
        result = check_diff(
            _added(
                "a.py",
                "# NEVER use pytest.skip() to hide a red test",
            )
        )
        self.assertTrue(result.passed, result.violations)

    def test_pattern_in_string_literal_not_flagged(self):
        result = check_diff(_added("a.py", 'x = "# noqa"'))
        self.assertTrue(result.passed, result.violations)

    def test_pattern_in_docstring_not_flagged(self):
        body = (
            '+"""\n'
            "+Do not use a noqa comment.\n"
            '+"""\n'
            "+x = 1\n"
        )
        result = check_diff(_diff("a.py", body))
        self.assertTrue(result.passed, result.violations)

    def test_markdown_mentions_not_flagged(self):
        result = check_diff(
            _added("docs/notes.md", "Never add `# noqa` to silence the linter.")
        )
        self.assertTrue(result.passed, result.violations)


class FloorGuardSkipTests(unittest.TestCase):
    def test_pytest_mark_skip_flagged(self):
        result = check_diff(_added("test_a.py", "@pytest.mark.skip(reason='flaky')"))
        self.assertFalse(result.passed)
        self.assertTrue(any("skip" in v for v in _violations(result)))

    def test_pytest_mark_skipif_flagged(self):
        result = check_diff(
            _added("test_a.py", "@pytest.mark.skipif(sys.platform == 'win32', reason='x')")
        )
        self.assertFalse(result.passed)

    def test_pytest_skip_call_flagged(self):
        result = check_diff(_added("test_a.py", "    pytest.skip('needs GPU')"))
        self.assertFalse(result.passed)
        self.assertTrue(any("pytest-skip" in v for v in _violations(result)))

    def test_unittest_skip_flagged(self):
        result = check_diff(_added("test_a.py", "@unittest.skip('todo')"))
        self.assertFalse(result.passed)

    def test_js_test_skip_flagged(self):
        result = check_diff(_added("a.test.ts", "  it.skip('flaky', () => {})"))
        self.assertFalse(result.passed)

    def test_js_xit_flagged(self):
        result = check_diff(_added("a.test.ts", "  xit('flaky', () => {})"))
        self.assertFalse(result.passed)

    def test_xfail_is_warning_not_violation(self):
        result = check_diff(
            _added("test_a.py", "@pytest.mark.xfail(strict=True, reason='known bug')")
        )
        self.assertTrue(result.passed, result.violations)
        self.assertTrue(any("xfail" in w for w in result.warnings))


class FloorGuardExceptTests(unittest.TestCase):
    def test_except_pass_same_line_flagged(self):
        result = check_diff(_added("a.py", "except Exception: pass"))
        self.assertFalse(result.passed)
        self.assertTrue(any("except" in v for v in _violations(result)))

    def test_except_pass_next_line_flagged(self):
        body = "+try:\n+    risky()\n+except Exception:\n+    pass\n"
        result = check_diff(_diff("a.py", body))
        self.assertFalse(result.passed)
        self.assertTrue(any("except" in v for v in _violations(result)))

    def test_except_ellipsis_flagged(self):
        result = check_diff(_added("a.py", "except Exception: ..."))
        self.assertFalse(result.passed)

    def test_except_with_handling_passes(self):
        body = (
            "+try:\n"
            "+    risky()\n"
            "+except Exception:\n"
            "+    log_error()\n"
            "+    raise\n"
        )
        result = check_diff(_diff("a.py", body))
        self.assertTrue(result.passed, result.violations)

    def test_bare_except_with_handling_is_warning_only(self):
        body = "+try:\n+    risky()\n+except:\n+    log_error()\n"
        result = check_diff(_diff("a.py", body))
        self.assertTrue(result.passed, result.violations)
        self.assertTrue(any("bare-except" in w for w in result.warnings))


class FloorGuardDeletionTests(unittest.TestCase):
    def test_deleted_test_function_flagged(self):
        body = "-def test_old_behavior():\n-    assert compute() == 1\n"
        result = check_diff(_diff("tests/test_a.py", body))
        self.assertFalse(result.passed)
        self.assertTrue(any("deleted test" in v for v in _violations(result)))

    def test_deleted_assertion_flagged(self):
        body = " def test_kept():\n-    assert compute() == 1\n+    assert compute() == 2\n"
        result = check_diff(_diff("tests/test_a.py", body))
        self.assertFalse(result.passed)
        self.assertTrue(any("deleted test" in v for v in _violations(result)))

    def test_updated_assertion_value_not_flagged(self):
        # Same assertion method, same locked target, new expected value:
        # the lock stands, only the constant changed (e.g. PR #633 widened
        # _ORIENT_HYBRID_CANDIDATES 5 -> 10 and updated the assertion).
        body = (
            " def test_kept(self):\n"
            "-    self.assertEqual(_ORIENT_HYBRID_CANDIDATES, 5)\n"
            "+    self.assertEqual(_ORIENT_HYBRID_CANDIDATES, 10)\n"
        )
        result = check_diff(_diff("tests/test_a.py", body))
        self.assertTrue(result.passed, result.violations)

    def test_assertion_method_change_still_flagged(self):
        # Same target but a different assertion method: the lock itself
        # changed, still a deletion.
        body = (
            " def test_kept(self):\n"
            "-    self.assertEqual(_X, 5)\n"
            "+    self.assertTrue(_X)\n"
        )
        result = check_diff(_diff("tests/test_a.py", body))
        self.assertFalse(result.passed)
        self.assertTrue(any("deleted test" in v for v in _violations(result)))

    def test_assertion_target_change_still_flagged(self):
        # Same method but a different locked target: the lock itself
        # changed, still a deletion.
        body = (
            " def test_kept(self):\n"
            "-    self.assertEqual(_X, 5)\n"
            "+    self.assertEqual(_Y, 5)\n"
        )
        result = check_diff(_diff("tests/test_a.py", body))
        self.assertFalse(result.passed)
        self.assertTrue(any("deleted test" in v for v in _violations(result)))

    def test_assertion_removed_without_replacement_still_flagged(self):
        body = (
            " def test_kept(self):\n"
            "-    self.assertEqual(_X, 5)\n"
            "+    # lock removed\n"
        )
        result = check_diff(_diff("tests/test_a.py", body))
        self.assertFalse(result.passed)
        self.assertTrue(any("deleted test" in v for v in _violations(result)))

    def test_moved_test_not_flagged(self):
        body = "-def test_moved():\n+def test_moved():\n"
        result = check_diff(_diff("tests/test_a.py", body))
        self.assertTrue(result.passed, result.violations)

    def test_deleted_test_file_flagged(self):
        body = "-def test_something():\n-    assert True\n"
        result = check_diff(_diff_deleted("tests/test_gone.py", body))
        self.assertFalse(result.passed)
        self.assertTrue(any("deleted test file" in v for v in _violations(result)))

    def test_renamed_test_file_not_flagged(self):
        deleted = _diff_deleted("tests/test_old.py", "-def test_x():\n-    assert True\n")
        added = _diff(
            "tests/test_new.py",
            "+def test_x():\n+    assert True\n",
            old_path="/dev/null",
        )
        result = check_diff(deleted + added)
        self.assertTrue(result.passed, result.violations)

    def test_removed_production_assert_is_warning_only(self):
        body = "-    assert state is not None\n+    state = ensure_state()\n"
        result = check_diff(_diff("zn_agent/core/work.py", body))
        self.assertTrue(result.passed, result.violations)
        self.assertTrue(any("production assert" in w for w in result.warnings))


class FloorGuardStubTests(unittest.TestCase):
    def test_not_implemented_error_flagged(self):
        result = check_diff(_added("zn_agent/core/work.py", "    raise NotImplementedError"))
        self.assertFalse(result.passed)
        self.assertTrue(any("not-implemented" in v for v in _violations(result)))

    def test_mock_import_in_prod_flagged(self):
        result = check_diff(
            _added("zn_agent/core/work.py", "from unittest.mock import MagicMock")
        )
        self.assertFalse(result.passed)
        self.assertTrue(any("mock-import" in v for v in _violations(result)))

    def test_pass_stub_comment_flagged(self):
        result = check_diff(_added("zn_agent/core/work.py", "    pass  # TODO: stub"))
        self.assertFalse(result.passed)

    def test_stub_in_test_file_not_flagged(self):
        result = check_diff(
            _added("tests/test_a.py", "    raise NotImplementedError")
        )
        self.assertTrue(result.passed, result.violations)

    def test_ellipsis_in_pyi_not_flagged(self):
        result = check_diff(_added("a.pyi", "def f() -> int: ..."))
        self.assertTrue(result.passed, result.violations)

    def test_todo_comment_is_warning_only(self):
        result = check_diff(_added("zn_agent/core/work.py", "# TODO: revisit this branch"))
        self.assertTrue(result.passed, result.violations)
        self.assertTrue(any("todo-marker" in w for w in result.warnings))


class FloorGuardSelfWeakeningTests(unittest.TestCase):
    def test_constraints_rule_removal_flagged(self):
        # Diff marker '-' + file bullet '-' = '- - NEVER ...'.
        body = "- - NEVER delete a failing test to make CI green\n"
        result = check_diff(_diff("CONSTRAINTS.md", body))
        self.assertFalse(result.passed)
        self.assertTrue(any("CONSTRAINTS" in v for v in _violations(result)))

    def test_constraints_rule_addition_passes(self):
        result = check_diff(
            _added("CONSTRAINTS.md", "- NEVER fake evidence in a PR body")
        )
        self.assertTrue(result.passed, result.violations)

    def test_constraints_blanket_pass_flagged(self):
        result = check_diff(
            _added("CONSTRAINTS.md", "Tests may skip a check without approval.")
        )
        self.assertFalse(result.passed)

    def test_constraints_forbidden_phrase_description_passes(self):
        result = check_diff(
            _added(
                "CONSTRAINTS.md",
                "A blanket pass such as tests may skip a check is prohibited.",
            )
        )
        self.assertTrue(result.passed, result.violations)

    def test_floor_guard_pattern_removal_flagged(self):
        body = '-    ("noqa", re.compile(r"#\\s*noqa\\b"), "py"),\n'
        result = check_diff(_diff("runtime/python/zn_agent/core/floor_guard.py", body))
        self.assertFalse(result.passed)
        self.assertTrue(any("self-weakening" in v for v in _violations(result)))

    def test_floor_guard_test_deletion_flagged(self):
        body = "-    def test_noqa_flagged(self):\n"
        result = check_diff(
            _diff("tests/zn_agent/core/test_floor_guard.py", body)
        )
        self.assertFalse(result.passed)

    def test_workflow_invocation_removal_flagged(self):
        body = "-          PYTHONPATH=runtime/python .ci/floor-guard-venv/bin/python scripts/floor_guard.py --diff-file /tmp/floor-guard.diff\n"
        result = check_diff(_diff(".github/workflows/zn-floor-guard.yml", body))
        self.assertFalse(result.passed)
        self.assertTrue(any("CI weakened" in v for v in _violations(result)))


if __name__ == "__main__":
    unittest.main()
