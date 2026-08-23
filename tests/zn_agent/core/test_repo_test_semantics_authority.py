from __future__ import annotations

import unittest

from zn_agent.core.repo_test_semantics import (
    ci_source_runs_kernel_unittest_suite,
    test_source_directly_imports_target,
)


class RepoTestSemanticsAuthorityTests(unittest.TestCase):
    def test_dead_or_nested_import_cannot_form_target_relation(self):
        module = "zn_agent.core.channel"
        for source in (
            "if False:\n    from zn_agent.core.channel import ResidentChannelService\n",
            "def load_later():\n    import zn_agent.core.channel\n",
            "try:\n    from zn_agent.core.channel import ResidentChannelService\nexcept ImportError:\n    pass\n",
        ):
            with self.subTest(source=source):
                self.assertFalse(test_source_directly_imports_target(source, module))

    def test_ci_command_text_without_run_step_cannot_form_execution_authority(self):
        command = (
            "python -m unittest discover -s tests/zn_agent/core "
            "-p 'test_*.py' -v"
        )
        self.assertFalse(
            ci_source_runs_kernel_unittest_suite(
                "name: misleading\ndescription: |\n  " + command + "\n"
            )
        )
        self.assertTrue(
            ci_source_runs_kernel_unittest_suite(
                "name: real\nsteps:\n  - name: kernel\n    run: " + command + "\n"
            )
        )


if __name__ == "__main__":
    unittest.main()
