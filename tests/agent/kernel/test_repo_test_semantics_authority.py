from __future__ import annotations

import unittest

from agent.kernel.repo_test_semantics import test_source_directly_imports_target


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


if __name__ == "__main__":
    unittest.main()
