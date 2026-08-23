from __future__ import annotations

import unittest

from agent.kernel.repo_test_semantics import (
    ci_source_runs_kernel_unittest_suite,
    test_source_directly_imports_target,
)


class RepoTestSemanticsAuthorityTests(unittest.TestCase):
    def test_dead_or_nested_import_cannot_form_target_relation(self):
        module = "agent.kernel.channel"
        for source in (
            "if False:\n    from agent.kernel.channel import ResidentChannelService\n",
            "def load_later():\n    import agent.kernel.channel\n",
            "try:\n    from agent.kernel.channel import ResidentChannelService\nexcept ImportError:\n    pass\n",
        ):
            with self.subTest(source=source):
                self.assertFalse(test_source_directly_imports_target(source, module))

    def test_ci_command_text_without_run_step_cannot_form_execution_authority(self):
        command = (
            "uv run python -m unittest discover -s tests/agent/kernel "
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
