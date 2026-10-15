"""W-3 Spec-first workflow: spec before implementation, enforced by gates.

Unit tests pin the spec templates (fresh template fails the gate), the
two label gates (ready-to-spec for writing a spec, ready-to-implement
for starting implementation), the gap-shaped blocked reason, and the
disk loader (missing files are missing, hostile slugs stay inside the
workspace). Resident tests drive the real loop: a spec-bound team with
no approved spec makes zero specialist calls and writes nothing; a
complete, labelled spec unblocks work and reaches the specialist's
question; fixing the spec on disk unblocks without any resume
ceremony; and with Plan Mode also on, the spec gate runs before any
plan proposal.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.cognitive_resource import (
    CognitiveIncrement,
    CognitiveResourceWorkerFactory,
)
from zn_agent.core.models import ModelRoute
from zn_agent.core.provider_bridge import build_resident_runtime
from zn_agent.core.recovery_bounded_work import RecoveryBoundedWorkLedger
from zn_agent.core.spec_first import (
    LABEL_READY_TO_IMPLEMENT,
    LABEL_READY_TO_SPEC,
    SPEC_GATE_STATE_KEY,
    SPEC_PLACEHOLDER,
    can_start_spec,
    check_implementation_gate,
    load_spec_files,
    normalize_labels,
    parse_spec_labels,
    render_spec_templates,
    spec_dir_rel_path,
    spec_prompt_excerpt,
    spec_slug,
    spec_slug_from_event,
)
from zn_agent.core.work_restore_control import RestoreAwareWorkControl


def _body(text: str) -> str:
    """A section body long enough to count as filled."""
    return f"{text}，覆盖目标、边界与验收，写满二十字以上才算填完。"


def _complete_spec_files() -> dict[str, str]:
    return {
        "PRODUCT.md": "\n".join(
            [
                "# Spec：演示功能",
                "",
                "## 背景",
                "",
                _body("用户需要一份可验证的演示产物"),
                "",
                "## 目标",
                "",
                _body("产出一份调研笔记并通过验收"),
                "",
                "## 范围",
                "",
                _body("只写 research/notes.md 一个文件"),
                "",
                "## 非目标",
                "",
                _body("不碰工作台、不改配置、不发消息"),
                "",
                "## 验收",
                "",
                _body("文件存在且内容与验收完全一致"),
                "",
            ]
        ),
        "TECH.md": "\n".join(
            [
                "# Spec（技术）：演示功能",
                "",
                "<!-- SPEC LABELS: ready-to-implement -->",
                "",
                "## 方案",
                "",
                _body("专员写 research/notes.md，Body 校验文本相等"),
                "",
                "## 改动点",
                "",
                _body("新增 research/notes.md 一个文件"),
                "",
                "## 验收",
                "",
                _body("跑 text_equals 验收，失败不认领"),
                "",
                "## 风险",
                "",
                _body("专员可能偏离范围，需按 spec 验收"),
                "",
            ]
        ),
    }


class SpecSlugTests(unittest.TestCase):
    def test_slug_sanitized(self):
        self.assertEqual(spec_slug("demo feature"), "demo-feature")
        self.assertEqual(spec_slug("a/b c"), "a-b-c")
        self.assertEqual(spec_slug(""), "")

    def test_dir_path(self):
        self.assertEqual(spec_dir_rel_path("demo"), "specs/demo")

    def test_slug_from_event(self):
        event = SimpleNamespace(
            payload={"team_request": {"spec_slug": "demo feature"}}
        )
        self.assertEqual(spec_slug_from_event(event), "demo-feature")
        self.assertEqual(
            spec_slug_from_event(SimpleNamespace(payload={})), ""
        )
        self.assertEqual(
            spec_slug_from_event(SimpleNamespace(payload={"team_request": {}})),
            "",
        )


class SpecLabelTests(unittest.TestCase):
    def test_normalize_labels(self):
        self.assertEqual(
            normalize_labels(["Ready-To-Spec", " ready-to-spec "]),
            ("ready-to-spec",),
        )
        self.assertEqual(normalize_labels("a, b a"), ("a", "b"))
        self.assertEqual(normalize_labels(None), ())

    def test_parse_spec_labels(self):
        text = (
            "前文\n<!-- SPEC LABELS: ready-to-implement, draft -->\n"
            "<!-- SPEC LABELS: ready-to-spec -->"
        )
        self.assertEqual(
            parse_spec_labels(text),
            ("ready-to-implement", "draft", "ready-to-spec"),
        )
        self.assertEqual(parse_spec_labels("没有标记"), ())
        self.assertEqual(parse_spec_labels(None), ())

    def test_can_start_spec_needs_ready_to_spec(self):
        allowed, _ = can_start_spec([LABEL_READY_TO_SPEC])
        self.assertTrue(allowed)
        allowed, reason = can_start_spec([])
        self.assertFalse(allowed)
        self.assertIn(LABEL_READY_TO_SPEC, reason)
        # Gate 2's label does not authorize gate 1.
        allowed, reason = can_start_spec([LABEL_READY_TO_IMPLEMENT])
        self.assertFalse(allowed)
        self.assertIn(LABEL_READY_TO_SPEC, reason)


class ImplementationGateTests(unittest.TestCase):
    def test_no_slug_blocked(self):
        allowed, reason = check_implementation_gate(
            slug="", spec_files=_complete_spec_files()
        )
        self.assertFalse(allowed)
        self.assertIn("spec_slug", reason)

    def test_missing_product_blocked(self):
        files = _complete_spec_files()
        del files["PRODUCT.md"]
        allowed, reason = check_implementation_gate(
            slug="demo", spec_files=files
        )
        self.assertFalse(allowed)
        self.assertIn("PRODUCT.md", reason)

    def test_missing_tech_blocked(self):
        files = _complete_spec_files()
        del files["TECH.md"]
        allowed, reason = check_implementation_gate(
            slug="demo", spec_files=files
        )
        self.assertFalse(allowed)
        self.assertIn("TECH.md", reason)

    def test_placeholder_section_blocked_names_section(self):
        files = _complete_spec_files()
        files["PRODUCT.md"] = files["PRODUCT.md"].replace(
            _body("只写 research/notes.md 一个文件"),
            f"{SPEC_PLACEHOLDER}写满本节后再删掉本行。",
        )
        allowed, reason = check_implementation_gate(
            slug="demo", spec_files=files
        )
        self.assertFalse(allowed)
        self.assertIn("范围", reason)

    def test_short_section_blocked(self):
        files = _complete_spec_files()
        files["TECH.md"] = files["TECH.md"].replace(
            _body("专员写 research/notes.md，Body 校验文本相等"), "太短"
        )
        allowed, reason = check_implementation_gate(
            slug="demo", spec_files=files
        )
        self.assertFalse(allowed)
        self.assertIn("方案", reason)

    def test_complete_without_label_blocked(self):
        files = _complete_spec_files()
        files["TECH.md"] = files["TECH.md"].replace(
            "ready-to-implement", "draft"
        )
        allowed, reason = check_implementation_gate(
            slug="demo", spec_files=files
        )
        self.assertFalse(allowed)
        self.assertIn(LABEL_READY_TO_IMPLEMENT, reason)

    def test_complete_with_label_allowed(self):
        allowed, reason = check_implementation_gate(
            slug="demo", spec_files=_complete_spec_files()
        )
        self.assertTrue(allowed)
        self.assertEqual(reason, "")


class SpecTemplateTests(unittest.TestCase):
    def test_fresh_template_fails_gate(self):
        templates = render_spec_templates(
            slug="demo", title="演示功能", goal="产出一份可验证的笔记"
        )
        self.assertEqual(set(templates), {"PRODUCT.md", "TECH.md"})
        self.assertIn(SPEC_PLACEHOLDER, templates["PRODUCT.md"])
        self.assertIn("SPEC LABELS: draft", templates["TECH.md"])
        allowed, _ = check_implementation_gate(
            slug="demo", spec_files=templates
        )
        self.assertFalse(allowed)

    def test_template_has_required_sections(self):
        templates = render_spec_templates(slug="demo", title="演示功能")
        for name in ("背景", "目标", "范围", "非目标", "验收"):
            self.assertIn(f"## {name}", templates["PRODUCT.md"])
        for name in ("方案", "改动点", "验收", "风险"):
            self.assertIn(f"## {name}", templates["TECH.md"])

    def test_prompt_excerpt_carries_goal_and_approach(self):
        excerpt = spec_prompt_excerpt(
            slug="demo", spec_files=_complete_spec_files()
        )
        self.assertIn("产出一份调研笔记", excerpt)
        self.assertIn("专员写 research/notes.md", excerpt)
        self.assertEqual(
            spec_prompt_excerpt(slug="demo", spec_files={}), ""
        )


class LoadSpecFilesTests(unittest.TestCase):
    def test_loads_both_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec_dir = Path(tmp) / "specs" / "demo"
            spec_dir.mkdir(parents=True)
            files = _complete_spec_files()
            for name, text in files.items():
                (spec_dir / name).write_text(text, encoding="utf-8")
            loaded = load_spec_files(tmp, "demo")
            self.assertEqual(loaded, files)

    def test_missing_dir_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_spec_files(tmp, "demo"), {})
            self.assertEqual(load_spec_files("", "demo"), {})

    def test_hostile_slug_stays_inside_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "evil.txt"
            outside.write_text("secret", encoding="utf-8")
            loaded = load_spec_files(tmp, "../../evil")
            self.assertEqual(loaded, {})
            self.assertEqual(outside.read_text(encoding="utf-8"), "secret")


class _ScriptedSpecialist:
    """Fixture cognition: scripted replies per live-specialist call."""

    def __init__(self, *, script: list[str]) -> None:
        self._script = list(script)
        self.specialist_calls = 0
        self.questions: list[str] = []

    def invoke(self, *, question: str, context: str) -> CognitiveIncrement:
        if "调研-01" not in question:
            return CognitiveIncrement(
                text="继续按现有证据推进。",
                provider="fixture-cognition",
                model="team-spec-fixture",
            )
        self.specialist_calls += 1
        self.questions.append(question)
        index = min(self.specialist_calls - 1, len(self._script) - 1)
        return CognitiveIncrement(
            text=self._script[index],
            provider="fixture-cognition",
            model="team-spec-fixture",
        )


class ResidentSpecFirstTests(unittest.TestCase):
    @staticmethod
    def _configure_cognition(resident, cognition) -> None:
        resident.kernel.reconfigure_resources(
            routes=[
                ModelRoute(
                    route_id="team-spec-cognition",
                    provider="fixture",
                    model="team-spec-fixture",
                    capabilities={
                        "general": 1.0,
                        "reasoning": 1.0,
                        "coding": 1.0,
                        "research": 1.0,
                        "language_understanding": 1.0,
                    },
                )
            ],
            worker_factory=CognitiveResourceWorkerFactory(
                resource_builder=lambda _route: cognition,
            ),
            max_attempts=1,
            resource_status={"available": True, "error": None},
        )

    def _start(
        self,
        root: Path,
        cognition,
        *,
        spec_slug_value: str | None,
        plan_mode: bool = False,
        spec_files: dict[str, str] | None = None,
    ):
        workspace = root / "team-workspace"
        workspace.mkdir()
        if spec_files is not None and spec_slug_value:
            spec_dir = workspace / "specs" / spec_slug_value
            spec_dir.mkdir(parents=True)
            for name, text in spec_files.items():
                (spec_dir / name).write_text(text, encoding="utf-8")
        resident = build_resident_runtime(
            config={"model": {}},
            store_path=root / "kernel.db",
        )
        self._configure_cognition(resident, cognition)
        control = RestoreAwareWorkControl(RecoveryBoundedWorkLedger(resident))
        ledger = control.ledger
        ledger.create_thread(thread_id="team-spec-e2e", title="XX 项目")
        ledger.attach_workspace("team-spec-e2e", workspace, name="Team Workspace")
        request: dict = {
            "project_title": "XX 项目",
            "role_keys": ["researcher"],
        }
        if spec_slug_value is not None:
            request["spec_slug"] = spec_slug_value
        if plan_mode:
            request["plan_mode"] = True
        _, event = control.start(
            "team-spec-e2e",
            "给 XX 项目组个团队",
            payload={
                "model_policy": "on_demand",
                "team_request": request,
            },
        )
        return resident, ledger, event, workspace

    @staticmethod
    def _write_step(*, path: str, content: str) -> str:
        return json.dumps(
            {
                "zn_work_step": {
                    "objective": "调研员写一份可验证的工作产物",
                    "action": {
                        "kind": "write_file",
                        "path": path,
                        "content": content,
                    },
                    "acceptance": {
                        "kind": "text_equals",
                        "path": path,
                        "expected_text": content,
                    },
                }
            },
            ensure_ascii=False,
        )

    def test_missing_spec_blocks_before_any_work_step(self):
        """No approved spec -> zero specialist calls, nothing written,
        event stays alive (not terminal) with the spec gate mirrored."""
        cognition = _ScriptedSpecialist(
            script=[self._write_step(path="research/notes.md", content="x\n")]
        )
        with tempfile.TemporaryDirectory() as tmp:
            resident, _, _, workspace = self._start(
                Path(tmp), cognition, spec_slug_value="demo"
            )
            try:
                for _ in range(15):
                    terminal = resident.live_once()
                    self.assertIsNone(
                        terminal, "spec-blocked team must not terminate"
                    )
                self.assertEqual(cognition.specialist_calls, 0)
                self.assertEqual(
                    sorted(p.name for p in workspace.iterdir()), ["agents"]
                )
                state = resident.store.get_working_state()
                gate = state.data.get(SPEC_GATE_STATE_KEY)
                assert isinstance(gate, dict)
                self.assertEqual(gate["status"], "blocked")
                self.assertEqual(gate["slug"], "demo")
                self.assertIn("PRODUCT.md", gate["reason"])
                # Gap-shaped reason (P2b shape, not a new vocabulary).
                self.assertIn("missing", gate["gap"])
                self.assertIn("needed", gate["gap"])
                self.assertIn("impact", gate["gap"])
                self.assertIn("补齐 spec", state.next_action)
            finally:
                resident.store.close()

    def test_approved_spec_unblocks_and_reaches_specialist(self):
        """Complete + labelled spec -> work executes, and the spec
        summary reaches the specialist's question."""
        write = self._write_step(
            path="research/notes.md", content="调研-01 verified step\n"
        )
        cognition = _ScriptedSpecialist(script=[write])
        with tempfile.TemporaryDirectory() as tmp:
            resident, _, _, workspace = self._start(
                Path(tmp),
                cognition,
                spec_slug_value="demo",
                spec_files=_complete_spec_files(),
            )
            try:
                wrote = False
                for _ in range(120):
                    resident.live_once()
                    if (workspace / "research" / "notes.md").exists():
                        wrote = True
                        break
                self.assertTrue(wrote, "work did not proceed with spec")
                self.assertGreater(cognition.specialist_calls, 0)
                self.assertTrue(
                    any(
                        "Spec-first" in question
                        and "产出一份调研笔记" in question
                        for question in cognition.questions
                    ),
                    "spec summary did not reach the specialist",
                )
                state = resident.store.get_working_state()
                self.assertNotIn(SPEC_GATE_STATE_KEY, state.data)
            finally:
                resident.store.close()

    def test_fixing_spec_on_disk_unblocks_without_resume(self):
        """Blocked on a missing spec -> spec files land on disk ->
        next pulses proceed. No resume ceremony: the gate re-reads
        the spec directory every pulse."""
        write = self._write_step(
            path="research/notes.md", content="调研-01 verified step\n"
        )
        cognition = _ScriptedSpecialist(script=[write])
        with tempfile.TemporaryDirectory() as tmp:
            resident, _, _, workspace = self._start(
                Path(tmp), cognition, spec_slug_value="demo"
            )
            try:
                blocked = False
                for _ in range(15):
                    resident.live_once()
                    state = resident.store.get_working_state()
                    if state.data.get(SPEC_GATE_STATE_KEY):
                        blocked = True
                        break
                self.assertTrue(blocked, "team was never spec-blocked")
                spec_dir = workspace / "specs" / "demo"
                spec_dir.mkdir(parents=True)
                for name, text in _complete_spec_files().items():
                    (spec_dir / name).write_text(text, encoding="utf-8")
                wrote = False
                for _ in range(120):
                    resident.live_once()
                    if (workspace / "research" / "notes.md").exists():
                        wrote = True
                        break
                self.assertTrue(
                    wrote, "fixing the spec on disk did not unblock work"
                )
            finally:
                resident.store.close()

    def test_spec_gate_runs_before_plan_mode(self):
        """Spec + Plan Mode together: a missing spec blocks before any
        plan proposal is made -- the spec precedes even the plan."""
        cognition = _ScriptedSpecialist(
            script=[self._write_step(path="research/notes.md", content="x\n")]
        )
        with tempfile.TemporaryDirectory() as tmp:
            resident, _, _, workspace = self._start(
                Path(tmp),
                cognition,
                spec_slug_value="demo",
                plan_mode=True,
            )
            try:
                for _ in range(15):
                    resident.live_once()
                self.assertEqual(cognition.specialist_calls, 0)
                self.assertFalse((workspace / "plans").exists())
                state = resident.store.get_working_state()
                assert isinstance(
                    state.data.get(SPEC_GATE_STATE_KEY), dict
                )
            finally:
                resident.store.close()

    def test_no_slug_means_gate_not_consulted(self):
        """Legacy flow (no spec_slug): the gate stays out of the way --
        no mirror, work proceeds as before."""
        write = self._write_step(
            path="research/notes.md", content="调研-01 verified step\n"
        )
        cognition = _ScriptedSpecialist(script=[write])
        with tempfile.TemporaryDirectory() as tmp:
            resident, _, _, workspace = self._start(
                Path(tmp), cognition, spec_slug_value=None
            )
            try:
                wrote = False
                for _ in range(120):
                    resident.live_once()
                    if (workspace / "research" / "notes.md").exists():
                        wrote = True
                        break
                self.assertTrue(wrote, "legacy flow regressed")
                state = resident.store.get_working_state()
                self.assertNotIn(SPEC_GATE_STATE_KEY, state.data)
            finally:
                resident.store.close()


if __name__ == "__main__":
    unittest.main()
