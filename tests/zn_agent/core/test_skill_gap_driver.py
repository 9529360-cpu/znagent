from __future__ import annotations

"""M-15: skill-gap auto-trigger inside the Work cognition loop + team path.

Covers: gap -> proposal -> approval card from SkillStore.bind_cognition_context
(mock cognition loop), idempotent re-binds, poll transitions (deny = explicit
block, approve = install, skill becomes referenceable), fail-closed without an
approval path, no-candidate, isolated questions, and the team path
(TeamWorkOwner._skills_block_for proposes instead of swallowing the gap).
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zn_agent.core.approval_cards import ApprovalCardStore
from zn_agent.core.skill_gap import (
    GAP_STATUS_BLOCKED,
    GAP_STATUS_DENIED,
    GAP_STATUS_INSTALLED,
    GAP_STATUS_NO_CANDIDATE,
    GAP_STATUS_PROPOSED,
)
from zn_agent.core.skill_gap_driver import (
    GAP_CONTEXT_KEY,
    SkillGapDriver,
    build_skill_gap_driver,
)
from zn_agent.core.skill_lock import SkillLock
from zn_agent.core.skills import SkillStore
from zn_agent.core.team_work_owner import TeamWorkOwner

SHA_A = "a" * 40

VALID_EXTERNAL_SKILL = """\
---
name: pdf-toolkit
description: Convert and merge PDF documents from the command line. Use when you need to convert pdf documents to images or merge pdf files.
version: 2.1.0
source: external
reviewed: true
reviewed_by: test-harness
allowed-tools: []
---

Convert and merge PDF documents.
"""

NOTES_BUNDLE = """\
---
name: weekly-notes
description: Summarize the weekly progress notes into a short report.
version: 1.0.0
---

Summarize weekly notes.
"""

PDF_QUERY = "convert pdf documents to images"


def _write_bundle(root: Path, name: str, text: str) -> None:
    bundle = root / name
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "skill.md").write_text(text, encoding="utf-8")


def _lock_with_plugin(skills_root: Path, *, name="pdf-toolkit") -> SkillLock:
    lock = SkillLock(skills_root)
    lock.pin(
        name,
        version="2.1.0",
        kind="external",
        sha=SHA_A,
        source=f"git+https://example.com/org/{name}",
    )
    lock.save()
    return SkillLock(skills_root)


def _approval_store(tmp: Path) -> ApprovalCardStore:
    return ApprovalCardStore(str(tmp / "approvals.db"))


def _event(task: str, **payload) -> SimpleNamespace:
    return SimpleNamespace(task=task, payload=dict(payload), event_id="evt-1")


def _request() -> SimpleNamespace:
    return SimpleNamespace(context={}, question="do the thing")


def _fake_fetch(text: str):
    def fetch(source: str, sha: str, dest) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "skill.md").write_text(text, encoding="utf-8")

    return fetch


class _Harness:
    """One tmp dir: skills root + lock, approval store, store, driver."""

    def __init__(self, tmp: Path, *, approval: bool = True, plugin: bool = True,
                 fetch=None):
        self.tmp = tmp
        self.skills_root = tmp / "skills"
        self.skills_root.mkdir(parents=True, exist_ok=True)
        if plugin:
            _lock_with_plugin(self.skills_root)
        self.approval_store = _approval_store(tmp) if approval else None
        self.store = SkillStore(root=self.skills_root)
        self.driver = SkillGapDriver(
            skill_store=self.store,
            approval_store=self.approval_store,
            fetch_skill=fetch or _fake_fetch(VALID_EXTERNAL_SKILL),
        )
        self.store.gap_driver = self.driver

    def bind(self, task: str, **payload) -> SimpleNamespace:
        request = _request()
        return self.store.bind_cognition_context(_event(task, **payload), request)


class WorkCognitionBindTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_gap_opens_card_and_attaches_note(self):
        h = _Harness(self.tmp)
        request = h.bind(PDF_QUERY)
        note = request.context.get(GAP_CONTEXT_KEY)
        self.assertIsNotNone(note)
        self.assertEqual(note["status"], GAP_STATUS_PROPOSED)
        self.assertEqual(note["candidates"], ["pdf-toolkit"])
        self.assertTrue(note["approval_request_id"])
        pending = h.approval_store.pending_requests()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].action_kind, "skill_acquire")
        self.assertTrue(pending[0].scope.startswith("skill-gap:"))
        # The card text names the candidate, the pin and the source.
        self.assertIn("pdf-toolkit", pending[0].value_text)
        self.assertIn(SHA_A[:12], pending[0].value_text)

    def test_repeat_bind_reuses_the_same_card(self):
        h = _Harness(self.tmp)
        first = h.bind(PDF_QUERY).context[GAP_CONTEXT_KEY]
        second = h.bind(PDF_QUERY).context[GAP_CONTEXT_KEY]
        self.assertEqual(first["approval_request_id"], second["approval_request_id"])
        self.assertEqual(first["proposal_id"], second["proposal_id"])
        self.assertEqual(len(h.approval_store.pending_requests()), 1)

    def test_skill_match_means_no_gap_note(self):
        h = _Harness(self.tmp)
        _write_bundle(h.skills_root, "weekly-notes", NOTES_BUNDLE)
        request = h.bind("summarize the weekly progress notes")
        self.assertNotIn(GAP_CONTEXT_KEY, request.context)
        self.assertIn("resident_skills", request.context)

    def test_no_candidate_means_no_card(self):
        h = _Harness(self.tmp, plugin=False)
        request = h.bind(PDF_QUERY)
        note = request.context.get(GAP_CONTEXT_KEY)
        self.assertIsNotNone(note)
        self.assertEqual(note["status"], GAP_STATUS_NO_CANDIDATE)
        self.assertIsNone(note["approval_request_id"])
        self.assertEqual(h.approval_store.pending_requests(), [])

    def test_no_candidate_rechecks_when_approved_source_appears(self):
        h = _Harness(self.tmp, plugin=False)
        first = h.bind(PDF_QUERY).context[GAP_CONTEXT_KEY]
        self.assertEqual(first["status"], GAP_STATUS_NO_CANDIDATE)
        # A human approves a new plugin source in the lockfile; the next
        # cognition round turns the remembered gap into a real proposal.
        _lock_with_plugin(h.skills_root)
        note = h.bind(PDF_QUERY).context[GAP_CONTEXT_KEY]
        self.assertEqual(note["status"], GAP_STATUS_PROPOSED)
        self.assertTrue(note["approval_request_id"])
        self.assertEqual(len(h.approval_store.pending_requests()), 1)
        # Still no candidate -> the original proposal is kept, still no card.
        note2 = h.bind("bake sourdough bread").context[GAP_CONTEXT_KEY]
        self.assertEqual(note2["status"], GAP_STATUS_NO_CANDIDATE)
        self.assertEqual(len(h.approval_store.pending_requests()), 1)

    def test_no_approval_path_is_fail_closed_blocked(self):
        h = _Harness(self.tmp, approval=False)
        request = h.bind(PDF_QUERY)
        note = request.context.get(GAP_CONTEXT_KEY)
        self.assertIsNotNone(note)
        self.assertEqual(note["status"], GAP_STATUS_BLOCKED)
        self.assertTrue(note["block_reason"])
        self.assertIsNone(note["approval_request_id"])

    def test_isolated_question_gets_no_gap_note(self):
        h = _Harness(self.tmp)
        request = h.bind(PDF_QUERY, cognition_question="what is 2+2?")
        self.assertNotIn(GAP_CONTEXT_KEY, request.context)

    def test_empty_task_is_not_a_gap(self):
        h = _Harness(self.tmp)
        request = h.bind("   ")
        self.assertNotIn(GAP_CONTEXT_KEY, request.context)

    def test_no_driver_keeps_previous_behavior(self):
        store = SkillStore(root=self.tmp / "skills")
        request = store.bind_cognition_context(_event(PDF_QUERY), _request())
        self.assertNotIn(GAP_CONTEXT_KEY, request.context)


class MockCognitionLoopTests(unittest.TestCase):
    """Simulate the cognition loop across binds: pending -> deny / approve."""

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_deny_is_an_explicit_block_not_silent(self):
        h = _Harness(self.tmp)
        first = h.bind(PDF_QUERY).context[GAP_CONTEXT_KEY]
        request_id = first["approval_request_id"]
        h.approval_store.decide(request_id, "deny")
        # Next cognition round polls the card: denied -> explicit block.
        note = h.bind(PDF_QUERY).context[GAP_CONTEXT_KEY]
        self.assertEqual(note["status"], GAP_STATUS_DENIED)
        self.assertIn("拒绝", note["interpretation"])
        # Nothing was installed, and no new card is opened afterwards.
        self.assertFalse((h.skills_root / "pdf-toolkit").exists())
        again = h.bind(PDF_QUERY).context[GAP_CONTEXT_KEY]
        self.assertEqual(again["status"], GAP_STATUS_DENIED)
        self.assertEqual(h.approval_store.pending_requests(), [])

    def test_approve_installs_and_skill_becomes_referenceable(self):
        h = _Harness(self.tmp)
        first = h.bind(PDF_QUERY).context[GAP_CONTEXT_KEY]
        request_id = first["approval_request_id"]
        h.approval_store.decide(request_id, "allow_once")
        # Next cognition round polls the card: approved -> install.
        note = h.bind(PDF_QUERY).context[GAP_CONTEXT_KEY]
        self.assertEqual(note["status"], GAP_STATUS_INSTALLED)
        installed = h.skills_root / "pdf-toolkit" / "skill.md"
        self.assertTrue(installed.is_file())
        # The installed skill now matches: the gap is gone, the skill binds.
        request = h.bind(PDF_QUERY)
        self.assertNotIn(GAP_CONTEXT_KEY, request.context)
        self.assertIn("resident_skills", request.context)

    def test_driver_without_skill_store_still_proposes(self):
        # Team-style usage: no SkillStore, detection falls back to the
        # match-list path; the propose -> open-card flow is identical.
        driver = SkillGapDriver(
            skill_store=None,
            approval_store=_approval_store(self.tmp),
            skills_root=self.tmp / "skills2",
            fetch_skill=_fake_fetch(VALID_EXTERNAL_SKILL),
        )
        (self.tmp / "skills2").mkdir(parents=True, exist_ok=True)
        _lock_with_plugin(self.tmp / "skills2")
        request = _request()
        out = driver.on_skill_bind(_event(PDF_QUERY), request)
        note = out.context.get(GAP_CONTEXT_KEY)
        self.assertIsNotNone(note)
        self.assertEqual(note["status"], GAP_STATUS_PROPOSED)


class TeamPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.skills_root = self.tmp / "skills"
        self.skills_root.mkdir(parents=True, exist_ok=True)
        _lock_with_plugin(self.skills_root)
        self.approval_store = _approval_store(self.tmp)

    def _memory(self):
        class _EmptySkillTable:
            def list_skills(self, status=None):
                return []

        return SimpleNamespace(store=_EmptySkillTable())

    def _driver(self, approval_store):
        return SkillGapDriver(
            skill_store=SkillStore(root=self.skills_root),
            approval_store=approval_store,
            fetch_skill=_fake_fetch(VALID_EXTERNAL_SKILL),
        )

    def test_team_gap_proposes_instead_of_swallowing(self):
        owner = TeamWorkOwner(
            ledger=object(),
            memory=self._memory(),
            gap_driver=self._driver(self.approval_store),
        )
        block = owner._skills_block_for(PDF_QUERY)
        # Not swallowed: an advisory proposal block, and a card was opened.
        self.assertTrue(block)
        self.assertIn("能力缺口", block)
        self.assertIn("pdf-toolkit", block)
        pending = self.approval_store.pending_requests()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].action_kind, "skill_acquire")

    def test_team_gap_without_driver_returns_empty(self):
        owner = TeamWorkOwner(ledger=object(), memory=self._memory())
        self.assertEqual(owner._skills_block_for(PDF_QUERY), "")

    def test_team_gap_fail_closed_without_approval_store(self):
        owner = TeamWorkOwner(
            ledger=object(),
            memory=self._memory(),
            gap_driver=self._driver(None),
        )
        block = owner._skills_block_for(PDF_QUERY)
        self.assertTrue(block)
        self.assertIn("能力缺口", block)
        self.assertIn("阻塞", block)

    def test_team_gap_is_idempotent_across_dispatches(self):
        driver = self._driver(self.approval_store)
        owner = TeamWorkOwner(ledger=object(), memory=self._memory(), gap_driver=driver)
        first = owner._skills_block_for(PDF_QUERY)
        second = owner._skills_block_for(PDF_QUERY)
        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(len(self.approval_store.pending_requests()), 1)

    def test_team_owner_for_reuses_driver_across_dispatches(self):
        # One card per gap, not one per dispatch: the resident must reuse
        # the same driver (and its per-query proposal registry) across
        # _team_owner_for calls.
        from zn_agent.core.team_work_resident import TeamWorkResidentRuntime

        stub = SimpleNamespace(
            work_ledger=object(), memory=SimpleNamespace(store=None)
        )
        event = SimpleNamespace(payload={})
        owner1 = TeamWorkResidentRuntime._team_owner_for(stub, event)
        owner2 = TeamWorkResidentRuntime._team_owner_for(stub, event)
        self.assertIs(owner1.gap_driver, owner2.gap_driver)

    def test_brief_block_reflects_terminal_statuses(self):
        from zn_agent.core.skill_gap import detect_skill_gap_from_matches

        driver = self._driver(self.approval_store)
        gap = detect_skill_gap_from_matches(PDF_QUERY, [])
        proposal = driver.propose_gap(gap)
        self.approval_store.decide(proposal.approval_request_id, "deny")
        denied = driver.propose_gap(detect_skill_gap_from_matches(PDF_QUERY, []))
        block = driver.render_brief_block(denied)
        self.assertEqual(denied.status, GAP_STATUS_DENIED)
        self.assertIn("已拒绝", block)
        self.assertNotIn("待人工批准", block)

        driver2 = self._driver(self.approval_store)
        proposal2 = driver2.propose_gap(
            detect_skill_gap_from_matches("merge pdf files quickly", [])
        )
        self.approval_store.decide(proposal2.approval_request_id, "allow_once")
        installed = driver2.propose_gap(
            detect_skill_gap_from_matches("merge pdf files quickly", [])
        )
        self.assertEqual(installed.status, GAP_STATUS_INSTALLED)
        block2 = driver2.render_brief_block(installed)
        self.assertIn("已批准并安装", block2)
        self.assertNotIn("待人工批准", block2)


class BuildDriverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_build_driver_without_store_path_fail_closes(self):
        store = SkillStore(root=self.tmp / "skills")
        driver = build_skill_gap_driver(skill_store=store, store=None)
        self.assertIsNone(driver.approval_store)
        self.assertEqual(driver.skills_root, store.root)

    def test_build_driver_with_store_path_wires_approvals(self):
        store = SkillStore(root=self.tmp / "skills")
        kernel = SimpleNamespace(path=str(self.tmp / "kernel.db"))
        driver = build_skill_gap_driver(skill_store=store, store=kernel)
        self.assertIsNotNone(driver.approval_store)


if __name__ == "__main__":
    unittest.main()
