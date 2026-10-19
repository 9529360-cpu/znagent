from __future__ import annotations

"""M-13: capability gap -> acquisition proposal -> install only on approval."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.approval_cards import (
    APPROVAL_KINDS,
    ApprovalCardStore,
    validate_approval_kind,
)
from zn_agent.core.skill_gap import (
    APPROVAL_KIND_SKILL_ACQUIRE,
    GAP_STATUS_APPROVED,
    GAP_STATUS_BLOCKED,
    GAP_STATUS_DENIED,
    GAP_STATUS_INSTALLED,
    GAP_STATUS_INSTALL_FAILED,
    GAP_STATUS_NO_CANDIDATE,
    GAP_STATUS_PROPOSED,
    PluginCandidate,
    approved_plugin_entries,
    build_proposal,
    default_fetch_plugin,
    detect_skill_gap,
    detect_skill_gap_from_matches,
    install_approved_skill,
    match_candidates,
    open_gap_approval,
    poll_gap_approval,
)
from zn_agent.core.skill_lock import LOCKFILE_NAME, SkillLock, content_sha256
from zn_agent.core.skill_routing import SkillRouter
from zn_agent.core.skills import SkillStore

SHA_A = "a" * 40
SHA_B = "b" * 40

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

UNREVIEWED_EXTERNAL_SKILL = """\
---
name: pdf-toolkit
description: Convert and merge PDF documents from the command line. Use when you need to convert pdf documents to images or merge pdf files.
version: 2.1.0
source: external
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


def _write_bundle(root: Path, name: str, text: str) -> Path:
    bundle = root / name
    bundle.mkdir(parents=True, exist_ok=True)
    path = bundle / "skill.md"
    path.write_text(text, encoding="utf-8")
    return path


def _approval_store(tmp: Path) -> ApprovalCardStore:
    return ApprovalCardStore(str(tmp / "approvals.db"))


def _lock_with_plugin(tmp: Path, *, name="pdf-toolkit", pinned=True,
                       kind="external", sha=SHA_A,
                       source="git+https://example.com/org/pdf-toolkit") -> SkillLock:
    lock = SkillLock(tmp)
    entry_kwargs = {"version": "2.1.0", "kind": kind, "source": source}
    if kind == "external":
        entry_kwargs["sha"] = sha
    lock.pin(name, **entry_kwargs)
    if not pinned:
        lock.entries[name].pinned = False
    lock.save()
    return SkillLock(tmp)


class ApprovalKindTests(unittest.TestCase):
    def test_skill_acquire_kind_registered(self):
        self.assertIn(APPROVAL_KIND_SKILL_ACQUIRE, APPROVAL_KINDS)
        self.assertEqual(validate_approval_kind("skill_acquire"), "skill_acquire")


class DetectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_no_skill_route_is_a_gap(self):
        router = SkillRouter(self.tmp)
        result = router.route("convert pdf documents to images")
        self.assertTrue(result.no_skill)
        gap = detect_skill_gap("convert pdf documents to images", result)
        self.assertIsNotNone(gap)
        self.assertEqual(gap.query, "convert pdf documents to images")
        self.assertEqual(gap.status, GAP_STATUS_PROPOSED)

    def test_matched_route_is_not_a_gap(self):
        _write_bundle(self.tmp, "weekly-notes", NOTES_BUNDLE)
        router = SkillRouter(self.tmp)
        result = router.route("summarize the weekly progress notes")
        self.assertFalse(result.no_skill)
        self.assertIsNone(detect_skill_gap("summarize the weekly progress notes", result))

    def test_empty_query_is_not_a_gap(self):
        router = SkillRouter(self.tmp)
        result = router.route("   ")
        self.assertIsNone(detect_skill_gap("   ", result))
        self.assertIsNone(detect_skill_gap_from_matches("", []))

    def test_none_route_result_is_not_a_gap(self):
        self.assertIsNone(detect_skill_gap("convert pdf documents", None))

    def test_match_list_path(self):
        self.assertIsNotNone(detect_skill_gap_from_matches("do pdf things", []))
        self.assertIsNone(detect_skill_gap_from_matches("do pdf things", ["x"]))


class SkillStoreSeamTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_store_detects_gap_on_work_skill_path(self):
        store = SkillStore(root=self.tmp)
        gap = store.detect_skill_gap("convert pdf documents to images")
        self.assertIsNotNone(gap)
        self.assertEqual(gap.status, GAP_STATUS_PROPOSED)

    def test_store_no_gap_when_skill_matches(self):
        _write_bundle(self.tmp, "weekly-notes", NOTES_BUNDLE)
        store = SkillStore(root=self.tmp)
        self.assertIsNone(store.detect_skill_gap("summarize the weekly progress notes"))


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_only_pinned_external_entries_are_approved_sources(self):
        lock = _lock_with_plugin(self.tmp)
        lock.pin("local-notes", version="1.0.0", kind="local")
        lock.pin("unpinned-ext", version="1.0.0", kind="external",
                 sha=SHA_B, source="git+https://example.com/org/other")
        lock.entries["unpinned-ext"].pinned = False
        lock.save()
        approved = approved_plugin_entries(SkillLock(self.tmp))
        self.assertEqual([entry.name for entry in approved], ["pdf-toolkit"])

    def test_malformed_sha_entry_is_not_approved(self):
        lock = SkillLock(self.tmp)
        lock.entries["bad-sha"] = lock.pin(
            "bad-sha", version="1.0.0", kind="external",
            sha=SHA_A, source="git+https://example.com/org/bad")
        lock.entries["bad-sha"].sha = "not-a-sha"
        lock.save()
        self.assertEqual(approved_plugin_entries(SkillLock(self.tmp)), [])

    def test_name_cue_matching_finds_candidate(self):
        lock = _lock_with_plugin(self.tmp)
        gap = detect_skill_gap_from_matches("convert pdf documents to images", [])
        candidates = match_candidates(gap, approved_plugin_entries(lock))
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].name, "pdf-toolkit")
        self.assertEqual(candidates[0].locked_sha, SHA_A)
        self.assertTrue(candidates[0].risk_notes)

    def test_unrelated_query_finds_no_candidate(self):
        lock = _lock_with_plugin(self.tmp)
        gap = detect_skill_gap_from_matches("bake sourdough bread", [])
        self.assertEqual(match_candidates(gap, approved_plugin_entries(lock)), [])

    def test_compact_name_fallback_matches(self):
        # No shared word token ("my-tool" -> tokens "my","tool" are usable,
        # but the query has no spaces): the compact-name fallback matches.
        lock = SkillLock(self.tmp)
        lock.pin("my-tool", version="1.0.0", kind="external", sha=SHA_A,
                 source="git+https://example.com/org/my-tool")
        lock.save()
        gap = detect_skill_gap_from_matches("please install mytool for me", [])
        candidates = match_candidates(gap, approved_plugin_entries(SkillLock(self.tmp)))
        self.assertEqual([c.name for c in candidates], ["my-tool"])

    def test_short_name_tokens_are_skipped(self):
        # All tokens shorter than 3 chars -> no cues -> never a candidate.
        lock = SkillLock(self.tmp)
        lock.pin("ai", version="1.0.0", kind="external", sha=SHA_A,
                 source="git+https://example.com/org/ai")
        lock.save()
        gap = detect_skill_gap_from_matches("use ai for this", [])
        self.assertEqual(
            match_candidates(gap, approved_plugin_entries(SkillLock(self.tmp))), [])

    def test_empty_source_entry_is_not_approved(self):
        # pin() itself refuses an empty source; simulate a hand-edited
        # lockfile entry to exercise the defense-in-depth filter.
        from zn_agent.core.skill_lock import LockEntry

        lock = SkillLock(self.tmp)
        lock.entries["no-source"] = LockEntry(
            name="no-source", version="1.0.0", kind="external",
            sha=SHA_A, pinned=True, source="",
        )
        lock.save()
        self.assertEqual(approved_plugin_entries(SkillLock(self.tmp)), [])

    def test_build_proposal_syncs_gap_status(self):
        lock = _lock_with_plugin(self.tmp)
        gap = detect_skill_gap_from_matches("convert pdf documents to images", [])
        proposal = build_proposal(
            gap, match_candidates(gap, approved_plugin_entries(lock)))
        self.assertEqual(proposal.status, GAP_STATUS_PROPOSED)
        self.assertEqual(gap.status, GAP_STATUS_PROPOSED)
        store = _approval_store(self.tmp)
        lock = _lock_with_plugin(self.tmp)
        gap = detect_skill_gap_from_matches("bake sourdough bread", [])
        proposal = build_proposal(gap, match_candidates(gap, approved_plugin_entries(lock)))
        self.assertEqual(proposal.status, GAP_STATUS_NO_CANDIDATE)
        self.assertEqual(proposal.candidates, ())
        opened = open_gap_approval(store, proposal)
        self.assertIsNone(opened.approval_request_id)
        self.assertEqual(opened.status, GAP_STATUS_NO_CANDIDATE)
        # No card was created.
        self.assertEqual(store.pending_requests(), [])


class ApprovalFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = _approval_store(self.tmp)
        self.lock = _lock_with_plugin(self.tmp)

    def _proposal(self):
        gap = detect_skill_gap_from_matches("convert pdf documents to images", [])
        candidates = match_candidates(gap, approved_plugin_entries(self.lock))
        self.assertTrue(candidates)
        return build_proposal(gap, candidates)

    def test_open_creates_skill_acquire_card(self):
        proposal = self._proposal()
        opened = open_gap_approval(self.store, proposal)
        self.assertIsNotNone(opened.approval_request_id)
        request = self.store.get_request(opened.approval_request_id)
        self.assertEqual(request.action_kind, "skill_acquire")
        self.assertEqual(request.status, "pending")
        self.assertIn("pdf-toolkit", request.value_text)
        self.assertIn("能力缺口", request.value_text)

    def test_poll_pending_stays_proposed(self):
        proposal = open_gap_approval(self.store, self._proposal())
        polled = poll_gap_approval(self.store, proposal)
        self.assertEqual(polled.status, GAP_STATUS_PROPOSED)

    def test_approve_then_poll(self):
        proposal = open_gap_approval(self.store, self._proposal())
        self.store.decide(proposal.approval_request_id, "allow_once")
        polled = poll_gap_approval(self.store, proposal)
        self.assertEqual(polled.status, GAP_STATUS_APPROVED)

    def test_deny_blocks_explicitly(self):
        proposal = open_gap_approval(self.store, self._proposal())
        self.store.decide(proposal.approval_request_id, "deny")
        polled = poll_gap_approval(self.store, proposal)
        self.assertEqual(polled.status, GAP_STATUS_DENIED)

    def test_no_approval_path_fails_closed(self):
        proposal = self._proposal()
        opened = open_gap_approval(object(), proposal)
        self.assertEqual(opened.status, GAP_STATUS_BLOCKED)
        self.assertIsNone(opened.approval_request_id)
        self.assertIn("fail-closed", opened.block_reason)

    def test_reopen_after_decision_does_not_clobber(self):
        proposal = open_gap_approval(self.store, self._proposal())
        first_id = proposal.approval_request_id
        # Double-open while pending: idempotent, no second card.
        reopened = open_gap_approval(self.store, proposal)
        self.assertEqual(reopened.approval_request_id, first_id)
        self.assertEqual(len(self.store.pending_requests()), 1)
        # Decide, then re-open: the recorded decision stands.
        self.store.decide(first_id, "allow_once")
        poll_gap_approval(self.store, proposal)
        self.assertEqual(proposal.status, GAP_STATUS_APPROVED)
        open_gap_approval(self.store, proposal)
        self.assertEqual(proposal.status, GAP_STATUS_APPROVED)
        self.assertEqual(proposal.approval_request_id, first_id)

    def test_expired_card_blocks(self):
        from datetime import datetime, timedelta, timezone

        proposal = open_gap_approval(self.store, self._proposal())
        future = datetime.now(timezone.utc) + timedelta(days=2)
        self.store.expire_overdue(now=future)
        polled = poll_gap_approval(self.store, proposal)
        self.assertEqual(polled.status, GAP_STATUS_DENIED)

    def test_poll_unknown_request_is_noop(self):
        proposal = self._proposal()
        proposal.approval_request_id = "does-not-exist"
        polled = poll_gap_approval(self.store, proposal)
        self.assertEqual(polled.status, GAP_STATUS_PROPOSED)
        self.assertEqual(polled.approval_request_id, "does-not-exist")

    def test_card_shows_sha_pin_and_source(self):
        proposal = open_gap_approval(self.store, self._proposal())
        request = self.store.get_request(proposal.approval_request_id)
        self.assertIn(SHA_A[:12], request.value_text)
        self.assertIn("git+https://example.com/org/pdf-toolkit", request.value_text)


class InstallGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = _approval_store(self.tmp)
        self.lock = _lock_with_plugin(self.tmp)
        self.skills_root = self.tmp / "skills"
        self.fetch_calls: list[tuple[str, str]] = []

    def _approved_proposal(self):
        gap = detect_skill_gap_from_matches("convert pdf documents to images", [])
        candidates = match_candidates(gap, approved_plugin_entries(self.lock))
        proposal = build_proposal(gap, candidates)
        open_gap_approval(self.store, proposal)
        self.store.decide(proposal.approval_request_id, "allow_once")
        return poll_gap_approval(self.store, proposal)

    def _denied_proposal(self):
        gap = detect_skill_gap_from_matches("convert pdf documents to images", [])
        candidates = match_candidates(gap, approved_plugin_entries(self.lock))
        proposal = build_proposal(gap, candidates)
        open_gap_approval(self.store, proposal)
        self.store.decide(proposal.approval_request_id, "deny")
        return poll_gap_approval(self.store, proposal)

    def _fake_fetch(self, text: str):
        def fetch(source: str, sha: str, dest) -> None:
            self.fetch_calls.append((source, sha))
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "skill.md").write_text(text, encoding="utf-8")
        return fetch

    def test_install_refused_without_approval(self):
        gap = detect_skill_gap_from_matches("convert pdf documents to images", [])
        candidates = match_candidates(gap, approved_plugin_entries(self.lock))
        proposal = build_proposal(gap, candidates)  # never opened, never approved
        result = install_approved_skill(
            proposal, candidates[0], skills_root=self.skills_root,
            fetch_skill=self._fake_fetch(VALID_EXTERNAL_SKILL),
        )
        self.assertFalse(result.success)
        self.assertEqual(self.fetch_calls, [])
        self.assertFalse((self.skills_root / "pdf-toolkit").exists())

    def test_denied_proposal_never_installs(self):
        proposal = self._denied_proposal()
        candidate = proposal.candidates[0]
        result = install_approved_skill(
            proposal, candidate, skills_root=self.skills_root,
            fetch_skill=self._fake_fetch(VALID_EXTERNAL_SKILL),
        )
        self.assertFalse(result.success)
        self.assertEqual(self.fetch_calls, [])
        self.assertFalse((self.skills_root / "pdf-toolkit").exists())

    def test_approved_install_validates_locks_and_activates(self):
        proposal = self._approved_proposal()
        candidate = proposal.candidates[0]
        result = install_approved_skill(
            proposal, candidate, skills_root=self.skills_root,
            fetch_skill=self._fake_fetch(VALID_EXTERNAL_SKILL),
        )
        self.assertTrue(result.success, result.reason)
        self.assertEqual(proposal.status, GAP_STATUS_INSTALLED)
        installed = self.skills_root / "pdf-toolkit" / "skill.md"
        self.assertTrue(installed.is_file())
        # Lockfile: pinned external entry at the approved SHA.
        lock = SkillLock(self.skills_root)
        entry = lock.entries["pdf-toolkit"]
        self.assertTrue(entry.pinned)
        self.assertEqual(entry.kind, "external")
        self.assertEqual(entry.sha, SHA_A)
        self.assertEqual(entry.content_sha256, content_sha256(VALID_EXTERNAL_SKILL))
        # The installed skill is routable through the normal path.
        router = SkillRouter(self.skills_root)
        self.assertIsNotNone(router.activate("pdf-toolkit"))
        self.assertFalse(router.route("convert pdf documents").no_skill)

    def test_install_fails_closed_on_validation(self):
        proposal = self._approved_proposal()
        candidate = proposal.candidates[0]
        result = install_approved_skill(
            proposal, candidate, skills_root=self.skills_root,
            fetch_skill=self._fake_fetch(UNREVIEWED_EXTERNAL_SKILL),
        )
        self.assertFalse(result.success)
        self.assertIn("reviewed", result.reason)
        self.assertEqual(proposal.status, GAP_STATUS_INSTALL_FAILED)
        # Nothing persisted: no bundle, no lockfile entry.
        self.assertFalse((self.skills_root / "pdf-toolkit").exists())
        self.assertFalse((self.skills_root / LOCKFILE_NAME).exists())

    def test_install_refuses_overwriting_pinned_skill(self):
        _write_bundle(self.skills_root, "pdf-toolkit", VALID_EXTERNAL_SKILL)
        lock = SkillLock(self.skills_root)
        lock.pin("pdf-toolkit", version="9.9.9", kind="external",
                 sha=SHA_A, source="git+https://example.com/org/pdf-toolkit",
                 content_sha256=content_sha256("different-bytes"))
        lock.save()
        proposal = self._approved_proposal()
        candidate = proposal.candidates[0]
        result = install_approved_skill(
            proposal, candidate, skills_root=self.skills_root,
            fetch_skill=self._fake_fetch(VALID_EXTERNAL_SKILL),
        )
        self.assertFalse(result.success)
        self.assertIn("pinned", result.reason)
        # Existing bundle untouched.
        self.assertEqual(
            (self.skills_root / "pdf-toolkit" / "skill.md").read_text(encoding="utf-8"),
            VALID_EXTERNAL_SKILL,
        )

    def test_rogue_candidate_rejected_despite_approval(self):
        # "Approve A, install B": the candidate installed must be one of the
        # proposal's own candidates (name + source + SHA). A rogue candidate
        # with a different source/SHA is refused and never fetched.
        proposal = self._approved_proposal()
        rogue = PluginCandidate(
            name="pdf-toolkit",
            source="git+https://evil.example.net/org/trojan",
            locked_sha="c" * 40,
        )
        result = install_approved_skill(
            proposal, rogue, skills_root=self.skills_root,
            fetch_skill=self._fake_fetch(VALID_EXTERNAL_SKILL),
        )
        self.assertFalse(result.success)
        self.assertIn("not one of this proposal's approved candidates", result.reason)
        self.assertEqual(self.fetch_calls, [])
        self.assertFalse((self.skills_root / "pdf-toolkit").exists())
        self.assertEqual(proposal.status, GAP_STATUS_INSTALL_FAILED)

    def test_malformed_candidate_sha_rejected(self):
        proposal = self._approved_proposal()
        bad = PluginCandidate(
            name="pdf-toolkit",
            source="git+https://example.com/org/pdf-toolkit",
            locked_sha="abc",
        )
        # Smuggle it past the binding check so the SHA gate is exercised.
        proposal.candidates = proposal.candidates + (bad,)
        result = install_approved_skill(
            proposal, bad, skills_root=self.skills_root,
            fetch_skill=self._fake_fetch(VALID_EXTERNAL_SKILL),
        )
        self.assertFalse(result.success)
        self.assertIn("pin", result.reason)
        self.assertEqual(self.fetch_calls, [])
        self.assertEqual(proposal.status, GAP_STATUS_INSTALL_FAILED)

    def test_unpinned_existing_bundle_is_updated(self):
        # Update semantics, pinned down: an existing UNPINNED bundle with
        # different content is replaced and re-pinned (not refused).
        _write_bundle(self.skills_root, "pdf-toolkit", NOTES_BUNDLE.replace(
            "name: weekly-notes", "name: pdf-toolkit"))
        proposal = self._approved_proposal()
        result = install_approved_skill(
            proposal, proposal.candidates[0], skills_root=self.skills_root,
            fetch_skill=self._fake_fetch(VALID_EXTERNAL_SKILL),
        )
        self.assertTrue(result.success, result.reason)
        self.assertEqual(
            (self.skills_root / "pdf-toolkit" / "skill.md").read_text(encoding="utf-8"),
            VALID_EXTERNAL_SKILL,
        )
        self.assertTrue(SkillLock(self.skills_root).entries["pdf-toolkit"].pinned)

    def test_event_ids_flow_into_gap_and_card(self):
        from types import SimpleNamespace

        event = SimpleNamespace(
            event_id="evt-123",
            payload={"work_thread_id": "thread-9"},
        )
        store = SkillStore(root=self.tmp)
        gap = store.detect_skill_gap("convert pdf documents", event=event)
        self.assertIsNotNone(gap)
        self.assertEqual(gap.event_id, "evt-123")
        self.assertEqual(gap.work_thread_id, "thread-9")
        candidates = match_candidates(gap, approved_plugin_entries(self.lock))
        proposal = build_proposal(gap, candidates)
        open_gap_approval(self.store, proposal)
        request = self.store.get_request(proposal.approval_request_id)
        self.assertEqual(request.event_id, "evt-123")

    def test_activation_check_runs_on_staged_copy_before_any_write(self):
        # A bundle whose frontmatter name does not match the approved
        # candidate name validates fine but is not activatable under the
        # candidate name: rejected BEFORE the skills root or lockfile is
        # touched. (Only repo-root skill.md is honored: the router only
        # activates <bundle>/skill.md, so a nested layout could never be
        # activated anyway.)
        mismatched = VALID_EXTERNAL_SKILL.replace("name: pdf-toolkit", "name: other-tool")

        def mismatch_fetch(source: str, sha: str, dest) -> None:
            Path(dest).mkdir(parents=True, exist_ok=True)
            (Path(dest) / "skill.md").write_text(mismatched, encoding="utf-8")

        proposal = self._approved_proposal()
        candidate = proposal.candidates[0]
        result = install_approved_skill(
            proposal, candidate, skills_root=self.skills_root,
            fetch_skill=mismatch_fetch,
        )
        self.assertFalse(result.success)
        self.assertIn("activation", result.reason)
        self.assertEqual(proposal.status, GAP_STATUS_INSTALL_FAILED)
        self.assertFalse((self.skills_root / "pdf-toolkit").exists())
        self.assertFalse((self.skills_root / LOCKFILE_NAME).exists())

    def test_nested_skill_md_is_not_installed(self):
        # skill.md nested one level down is not picked up: the plugin must
        # carry it at the repo root.
        def nested_fetch(source: str, sha: str, dest) -> None:
            nested = Path(dest) / "nested"
            nested.mkdir(parents=True, exist_ok=True)
            (nested / "skill.md").write_text(VALID_EXTERNAL_SKILL, encoding="utf-8")

        proposal = self._approved_proposal()
        result = install_approved_skill(
            proposal, proposal.candidates[0], skills_root=self.skills_root,
            fetch_skill=nested_fetch,
        )
        self.assertFalse(result.success)
        self.assertIn("no skill.md", result.reason)
        self.assertFalse((self.skills_root / "pdf-toolkit").exists())

    def test_failed_install_cleans_explicit_work_dir_staging(self):
        work_dir = self.tmp / "staging"
        proposal = self._approved_proposal()
        candidate = proposal.candidates[0]

        def boom(source: str, sha: str, dest) -> None:
            raise RuntimeError("network down")

        result = install_approved_skill(
            proposal, candidate, skills_root=self.skills_root,
            fetch_skill=boom, work_dir=work_dir,
        )
        self.assertFalse(result.success)
        leftovers = [p for p in work_dir.iterdir()] if work_dir.is_dir() else []
        self.assertEqual(leftovers, [])

    def test_propose_path_never_touches_network(self):
        # The propose path (detect/match/build/open/poll) must never fetch:
        # rig the module-level default fetcher to explode; any regression
        # that calls it here fails loudly instead of hitting the network.
        import zn_agent.core.skill_gap as skill_gap_mod

        real_fetch = skill_gap_mod.default_fetch_plugin

        def boom(source: str, sha: str, dest) -> None:
            raise AssertionError("network fetch called before approval")

        skill_gap_mod.default_fetch_plugin = boom
        try:
            gap = detect_skill_gap_from_matches("convert pdf documents to images", [])
            candidates = match_candidates(gap, approved_plugin_entries(self.lock))
            proposal = build_proposal(gap, candidates)
            open_gap_approval(self.store, proposal)
            poll_gap_approval(self.store, proposal)
        finally:
            skill_gap_mod.default_fetch_plugin = real_fetch
        self.assertEqual(self.fetch_calls, [])

    def test_blocked_card_records_why(self):
        gap = detect_skill_gap_from_matches("convert pdf documents to images", [])
        candidates = match_candidates(gap, approved_plugin_entries(self.lock))
        proposal = build_proposal(gap, candidates)

        class BrokenStore:
            def request_approval(self, **kwargs):
                raise RuntimeError("db is gone")

        opened = open_gap_approval(BrokenStore(), proposal)
        self.assertEqual(opened.status, GAP_STATUS_BLOCKED)
        self.assertIn("db is gone", opened.block_reason)

    def test_poll_storage_error_propagates_instead_of_spinning(self):
        proposal = self._approved_proposal()

        class BrokenStore:
            def get_request(self, request_id):
                raise RuntimeError("db is gone")

        with self.assertRaises(RuntimeError):
            poll_gap_approval(BrokenStore(), proposal)


class DefaultFetchPluginTests(unittest.TestCase):
    """The production fetcher, exercised against a local git repo (no network)."""

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.remote = self.tmp / "remote"
        self.remote.mkdir()
        subprocess.run(["git", "init", "-q", str(self.remote)], check=True)
        subprocess.run(
            ["git", "-C", str(self.remote), "config", "user.email", "t@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.remote), "config", "user.name", "t"], check=True
        )
        (self.remote / "skill.md").write_text(VALID_EXTERNAL_SKILL, encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.remote), "add", "skill.md"], check=True
        )
        subprocess.run(
            ["git", "-C", str(self.remote), "commit", "-qm", "init"], check=True
        )
        proc = subprocess.run(
            ["git", "-C", str(self.remote), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        self.sha = proc.stdout.strip()
        self.assertRegex(self.sha, r"^[0-9a-f]{40}$")

    def test_fetch_pins_exact_sha_and_strips_git(self):
        dest = self.tmp / "stage" / "pdf-toolkit"
        default_fetch_plugin(str(self.remote), self.sha, dest)
        self.assertEqual(
            (dest / "skill.md").read_text(encoding="utf-8"), VALID_EXTERNAL_SKILL
        )
        self.assertFalse((dest / ".git").exists())

    def test_fetch_refuses_existing_dest(self):
        dest = self.tmp / "stage" / "pdf-toolkit"
        dest.mkdir(parents=True)
        with self.assertRaises(RuntimeError):
            default_fetch_plugin(str(self.remote), self.sha, dest)

    def test_fetch_rejects_unresolvable_sha(self):
        dest = self.tmp / "stage2" / "pdf-toolkit"
        with self.assertRaises(RuntimeError):
            default_fetch_plugin(str(self.remote), "d" * 40, dest)
        # The clone succeeded but the pinned checkout failed: the .git
        # strip never ran, so this half-fetched tree is visibly not an
        # install (staging cleanup is the installer's job, tested above).
        self.assertTrue((dest / ".git").is_dir())


if __name__ == "__main__":
    unittest.main()
