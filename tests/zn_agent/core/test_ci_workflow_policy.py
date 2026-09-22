from __future__ import annotations

import re
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"


def _workflow_name(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip()
    return ""


def _on_block(text: str) -> str:
    lines = text.splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line == "on:")
    except StopIteration:
        return ""

    body: list[str] = []
    for line in lines[start + 1 :]:
        if line and not line[0].isspace():
            break
        body.append(line)
    return "\n".join(body)


class CiWorkflowPolicyTests(unittest.TestCase):
    def test_representative_e2e_workflows_are_manual_only(self) -> None:
        violations: list[str] = []
        for path in sorted(_WORKFLOWS.glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            name = _workflow_name(text)
            if "E2E" not in name.upper():
                continue

            triggers = _on_block(text)
            if re.search(r"^\s{2}(?:pull_request|push):", triggers, re.MULTILINE):
                violations.append(
                    f"{path.name}: representative E2E must not gate pull_request/push"
                )
            if not re.search(r"^\s{2}workflow_dispatch:", triggers, re.MULTILINE):
                violations.append(
                    f"{path.name}: representative E2E must remain manually runnable"
                )

        self.assertEqual(
            violations,
            [],
            "CI policy violations:\n" + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
