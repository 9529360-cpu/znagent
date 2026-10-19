from __future__ import annotations

"""M-1: layered Skill registry wired into Resident Work cognition.

The layered registry (host + project) previously had no product-path
caller. When a Work event carries an attached workspace with a ``skills``
directory, cognition binding resolves through the layered registry:
trigger matching over directory entries only, resident summaries in
context, bodies only for matched skills on demand.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from zn_agent.core.models import AgentEvent, CognitionRequest
from zn_agent.core.skills import SkillStore


def _write_skill(
    root: Path,
    name: str,
    *,
    description: str,
    body: str,
    version: str = "1.0.0",
    extra_frontmatter: str = "",
) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    front = (
        f"---\nname: {name}\ndescription: {description}\nversion: {version}\n"
        f"allowed-tools: []\n{extra_frontmatter}---\n\n"
    )
    path = directory / "skill.md"
    path.write_text(front + body, encoding="utf-8")
    return path


def _bind(store: SkillStore, task: str, *, include_bodies: bool = False, **payload):
    event = AgentEvent("event", task, payload=payload)
    request = CognitionRequest("request", "impasse", event.event_id, task)
    bound = store.bind_cognition_context(event, request, include_bodies=include_bodies)
    return bound.context.get("resident_skills")


class LayeredCognitionBindingTests(unittest.TestCase):
    """Project-layer skills reach Work cognition as summaries, never bodies."""

    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.tmp) / "zn_home"
        self.host_skills = self.root / "skills"
        self.workspace = Path(self.tmp) / "workspace"
        self.project_skills = self.workspace / "skills"
        self.workspace.mkdir(parents=True)
        self.store = SkillStore(self.host_skills)
        _write_skill(
            self.host_skills,
            "shared-notes",
            description="Use when writing shared meeting notes for the team.",
            body="HOST-BODY-CANARY shared notes procedure.",
        )
        _write_skill(
            self.host_skills,
            "deploy-check",
            description="Use when verifying a deployment before release.",
            body="HOST-BODY-CANARY deploy check procedure.",
        )
        _write_skill(
            self.project_skills,
            "shared-notes",
            description="Use when writing shared meeting notes for the team in this project.",
            body="PROJECT-BODY-CANARY project notes procedure.",
        )
        _write_skill(
            self.project_skills,
            "project-review",
            description="Use when reviewing pull requests.",
            body="PROJECT-BODY-CANARY review procedure.",
            extra_frontmatter='globs: ["*.md"]\n',
        )

    def _ws(self):
        return {"workspace_path": str(self.workspace)}

    def test_project_skill_bound_as_summary_no_body(self):
        bundle = _bind(
            self.store, "help writing shared meeting notes", **self._ws()
        )
        self.assertIsNotNone(bundle)
        self.assertEqual(bundle["stage"], "resident-summary")
        entry = bundle["skills"][0]
        self.assertEqual(entry["name"], "shared-notes")
        self.assertNotIn("body", entry)
        self.assertIn("when writing shared meeting notes", entry["trigger"])
        dumped = json.dumps(bundle)
        self.assertNotIn("PROJECT-BODY-CANARY", dumped)
        self.assertNotIn("HOST-BODY-CANARY", dumped)
        self.assertIn("project_root", bundle["activation"])

    def test_project_layer_shadows_host_same_name(self):
        bundle = _bind(
            self.store,
            "help writing shared meeting notes",
            include_bodies=True,
            **self._ws(),
        )
        self.assertIsNotNone(bundle)
        by_name = {item["name"]: item for item in bundle["skills"]}
        self.assertIn("PROJECT-BODY-CANARY", by_name["shared-notes"]["body"])
        self.assertNotIn("HOST-BODY-CANARY", by_name["shared-notes"]["body"])

    def test_no_match_binds_nothing_layered(self):
        self.assertIsNone(
            _bind(self.store, "what is the weather today", **self._ws())
        )

    def test_unmatched_skill_body_never_bound_layered(self):
        bundle = _bind(
            self.store, "help writing shared meeting notes", **self._ws()
        )
        self.assertIsNotNone(bundle)
        names = [entry["name"] for entry in bundle["skills"]]
        self.assertNotIn("deploy-check", names)
        self.assertNotIn("project-review", names)
        dumped = json.dumps(bundle)
        self.assertNotIn("deploy check procedure", dumped)
        self.assertNotIn("review procedure", dumped)

    def test_multi_skill_ordering_most_specific_cue_first(self):
        bundle = _bind(
            self.store,
            "please help reviewing pull requests and writing shared meeting notes",
            **self._ws(),
        )
        self.assertIsNotNone(bundle)
        names = [entry["name"] for entry in bundle["skills"]]
        # "writing shared meeting notes" (27 chars) beats
        # "reviewing pull requests" (23 chars): longest cue wins.
        self.assertEqual(names, ["shared-notes", "project-review"])

    def test_globs_filter_applies_in_layered_branch(self):
        matched = _bind(
            self.store,
            "please review the pull requests",
            file_path="notes.md",
            **self._ws(),
        )
        self.assertIsNotNone(matched)
        self.assertEqual(
            [entry["name"] for entry in matched["skills"]], ["project-review"]
        )
        self.assertIsNone(
            _bind(
                self.store,
                "please review the pull requests",
                file_path="notes.py",
                **self._ws(),
            )
        )

    def test_host_only_path_unchanged_without_workspace(self):
        bundle = _bind(self.store, "help verifying a deployment before release")
        self.assertIsNotNone(bundle)
        self.assertEqual(
            [entry["name"] for entry in bundle["skills"]], ["deploy-check"]
        )
        self.assertNotIn("project_root", bundle["activation"])
        # A project-only skill is invisible without its workspace layer.
        self.assertIsNone(_bind(self.store, "please review the pull requests"))

    def test_activate_skill_layered(self):
        activated = self.store.activate_skill(
            "project-review", project_root=self.project_skills
        )
        self.assertIsNotNone(activated)
        assert activated is not None
        self.assertIn("PROJECT-BODY-CANARY", activated.body)
        # Host-only activation cannot see the project layer.
        self.assertIsNone(self.store.activate_skill("project-review"))
        # Nearest layer wins on activation too.
        shadowed = self.store.activate_skill(
            "shared-notes", project_root=self.project_skills
        )
        self.assertIsNotNone(shadowed)
        assert shadowed is not None
        self.assertIn("PROJECT-BODY-CANARY", shadowed.body)


class ResidentCognitionWiringTests(unittest.TestCase):
    """The real Resident's cognition request carries the layered summary."""

    def test_product_resident_binds_project_skill_summary(self):
        from zn_agent.core.provider_bridge import build_resident_runtime

        with tempfile.TemporaryDirectory() as tmp:
            zn_home = Path(tmp) / "zn_home"
            host_skills = zn_home / "skills"
            workspace = Path(tmp) / "workspace"
            project_skills = workspace / "skills"
            workspace.mkdir(parents=True)
            _write_skill(
                host_skills,
                "deploy-check",
                description="Use when verifying a deployment before release.",
                body="HOST-BODY-CANARY deploy check procedure.",
            )
            _write_skill(
                project_skills,
                "project-review",
                description="Use when reviewing pull requests.",
                body="PROJECT-BODY-CANARY review procedure.",
            )
            with mock.patch.dict(
                os.environ, {"ZN_AGENT_HOME": str(zn_home)}, clear=False
            ):
                resident = build_resident_runtime(
                    config={"model": {}}, store_path=Path(tmp) / "kernel.db"
                )
            try:
                event = AgentEvent(
                    "event",
                    "please review the pull requests",
                    payload={"workspace_path": str(workspace)},
                )
                impasse = SimpleNamespace(
                    impasse_id="impasse-1", local_failure=None
                )
                request = resident._build_cognition_request(
                    event, impasse, ("general",)
                )
                bundle = (request.context or {}).get("resident_skills")
                self.assertIsNotNone(bundle)
                assert bundle is not None
                names = [entry["name"] for entry in bundle["skills"]]
                self.assertIn("project-review", names)
                self.assertNotIn("deploy-check", names)
                self.assertNotIn(
                    "PROJECT-BODY-CANARY", json.dumps(bundle)
                )
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
