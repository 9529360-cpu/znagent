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

    def test_current_windows_kernel_run_block_forms_execution_authority(self):
        current = (
            "steps:\n"
            "  - name: Run ZN core tests against working tree\n"
            "    shell: powershell\n"
            "    run: |\n"
            "      $env:PYTHONPATH = Join-Path $env:GITHUB_WORKSPACE 'runtime\\python'\n"
            "      & .\\.ci\\runtime-venv\\Scripts\\python.exe -m unittest discover "
            "-s tests/zn_agent/core -p 'test_*.py' -v\n"
        )
        self.assertTrue(ci_source_runs_kernel_unittest_suite(current))
        for changed in (
            current.replace("shell: powershell", "shell: bash"),
            current.replace(".ci\\runtime-venv", ".ci\\other-venv"),
            current.replace("tests/zn_agent/core", "tests/agent"),
            current.replace("'runtime\\python'", "'runtime\\other'"),
            current.replace("      & .\\.ci", "      # & .\\.ci"),
            current.replace("-v\n", "-v\n      Write-Output 'extra'\n"),
        ):
            with self.subTest(changed=changed):
                self.assertFalse(ci_source_runs_kernel_unittest_suite(changed))


if __name__ == "__main__":
    unittest.main()
