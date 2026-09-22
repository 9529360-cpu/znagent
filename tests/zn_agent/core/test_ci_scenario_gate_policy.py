from __future__ import annotations

import re
import unittest
from pathlib import Path


class CiScenarioGatePolicyTests(unittest.TestCase):
    """Keep representative E2E stories out of normal pull-request gating."""

    def test_numbered_e2e_workflows_are_not_pull_request_gates(self) -> None:
        root = Path(__file__).resolve().parents[3]
        workflows = root / ".github" / "workflows"

        offenders: list[str] = []
        scenario_ref = re.compile(
            r"tests(?:/|\\|\.)zn_agent(?:/|\\|\.)e2e(?:/|\\|\.)test_e2e",
            re.IGNORECASE,
        )
        numbered_name = re.compile(r"e2e\d+", re.IGNORECASE)

        for path in sorted(workflows.glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            has_scenario_identity = bool(
                numbered_name.search(path.name) or scenario_ref.search(text)
            )
            if has_scenario_identity and re.search(
                r"(?m)^\s*pull_request\s*:",
                text,
            ):
                offenders.append(path.relative_to(root).as_posix())

        self.assertEqual(
            offenders,
            [],
            "Representative numbered E2E workflows must be post-merge/manual, "
            "not pull-request merge gates: " + ", ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
