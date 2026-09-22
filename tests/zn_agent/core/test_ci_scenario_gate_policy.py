from __future__ import annotations

import re
import unittest
from pathlib import Path


class CiScenarioGatePolicyTests(unittest.TestCase):
    """Keep representative E2E stories out of automatic merge/mainline gating."""

    @staticmethod
    def _workflow_name(text: str) -> str:
        for line in text.splitlines():
            if line.startswith("name:"):
                return line.split(":", 1)[1].strip()
        return ""

    @staticmethod
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

    def test_representative_e2e_workflows_are_manual_only(self) -> None:
        root = Path(__file__).resolve().parents[3]
        workflows = root / ".github" / "workflows"

        offenders: list[str] = []
        scenario_ref = re.compile(
            r"tests(?:/|\\|\.)zn_agent(?:/|\\|\.)(?:core|e2e)(?:/|\\|\.)test_e2e",
            re.IGNORECASE,
        )
        numbered_name = re.compile(r"e2e\d+", re.IGNORECASE)

        for path in sorted(workflows.glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            name = self._workflow_name(text)
            has_scenario_identity = bool(
                "E2E" in name.upper()
                or numbered_name.search(path.name)
                or scenario_ref.search(text)
            )
            if not has_scenario_identity:
                continue

            triggers = self._on_block(text)
            if re.search(
                r"^\s{2}(?:pull_request|push):",
                triggers,
                re.MULTILINE,
            ):
                offenders.append(
                    f"{path.relative_to(root).as_posix()}: "
                    "representative E2E must not gate pull_request/push"
                )
            if not re.search(
                r"^\s{2}workflow_dispatch:",
                triggers,
                re.MULTILINE,
            ):
                offenders.append(
                    f"{path.relative_to(root).as_posix()}: "
                    "representative E2E must remain manually runnable"
                )

        self.assertEqual(
            offenders,
            [],
            "CI policy violations:\n" + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
