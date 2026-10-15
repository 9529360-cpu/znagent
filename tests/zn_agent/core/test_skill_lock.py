from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from zn_agent.core.skill_lock import (
    LOCKFILE_NAME,
    SkillLock,
    SkillLockedError,
    check_plugin_updates,
    content_sha256,
    plan_upgrades,
)
from zn_agent.core.skills import SkillStore

from skill_plugin_updates import bump_plugins  # noqa: E402

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40

LOCAL_TEXT_V1 = "---\nname: notes\ndescription: Take notes.\nversion: 1.0.0\n---\n\nTake notes.\n"
LOCAL_TEXT_V2 = "---\nname: notes\ndescription: Take notes.\nversion: 2.0.0\n---\n\nTake better notes.\n"


def _lock_in(tmp: Path) -> SkillLock:
    return SkillLock(tmp)


class LockfileFormatTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_lockfile_records_name_version_sha_pin(self):
        lock = _lock_in(self.root)
        lock.pin("notes", version="1.0.0", content_sha256=content_sha256(LOCAL_TEXT_V1))
        lock.pin("ext-plug", sha=SHA_A, kind="external", source="git+https://example.com/org/plug")
        lock.save()
        raw = json.loads((self.root / LOCKFILE_NAME).read_text(encoding="utf-8"))
        self.assertEqual(raw["version"], 1)
        self.assertTrue(raw["skills"]["notes"]["pinned"])
        self.assertEqual(raw["skills"]["notes"]["version"], "1.0.0")
        self.assertEqual(raw["skills"]["ext-plug"]["sha"], SHA_A)
        self.assertEqual(raw["skills"]["ext-plug"]["kind"], "external")
        # Reload round-trips.
        reloaded = SkillLock(self.root)
        self.assertTrue(reloaded.is_pinned("notes"))
        self.assertEqual(reloaded.entry_for("ext-plug").source, "git+https://example.com/org/plug")

    def test_malformed_lockfile_fails_closed(self):
        (self.root / LOCKFILE_NAME).write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            SkillLock(self.root)

    def test_external_pin_requires_full_sha_and_source(self):
        lock = _lock_in(self.root)
        with self.assertRaises(ValueError):
            lock.pin("ext", sha="abc123", kind="external", source="git+https://example.com/x")
        with self.assertRaises(ValueError):
            lock.pin("ext", sha=SHA_A, kind="external", source="")
        entry = lock.pin("ext", sha=SHA_A, kind="external", source="git+https://example.com/x")
        self.assertTrue(entry.pinned)


class PinEnforcementTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store = SkillStore(self.root)
        self.store.install_skill("notes", LOCAL_TEXT_V1)
        lock = self.store.skill_lock()
        lock.pin(
            "notes",
            version="1.0.0",
            content_sha256=content_sha256(LOCAL_TEXT_V1),
        )
        lock.save()

    def test_pinned_overwrite_refused_and_file_unchanged(self):
        with self.assertRaises(SkillLockedError):
            self.store.install_skill("notes", LOCAL_TEXT_V2)
        self.assertEqual((self.root / "notes" / "skill.md").read_text(encoding="utf-8"), LOCAL_TEXT_V1)
        # Lockfile entry untouched by the refused write.
        self.assertTrue(self.store.skill_lock().is_pinned("notes"))
        self.assertEqual(self.store.skill_lock().entry_for("notes").version, "1.0.0")

    def test_pinned_identical_rewrite_allowed(self):
        path = self.store.install_skill("notes", LOCAL_TEXT_V1)
        self.assertTrue(path.is_file())
        self.assertTrue(self.store.skill_lock().is_pinned("notes"))

    def test_unpin_then_update_succeeds(self):
        lock = self.store.skill_lock()
        lock.unpin("notes")
        lock.save()
        self.store.install_skill("notes", LOCAL_TEXT_V2)
        self.assertEqual((self.root / "notes" / "skill.md").read_text(encoding="utf-8"), LOCAL_TEXT_V2)
        entry = self.store.skill_lock().entry_for("notes")
        self.assertFalse(entry.pinned)
        self.assertEqual(entry.version, "2.0.0")

    def test_unpinned_skill_updates_normally(self):
        self.store.install_skill("other", LOCAL_TEXT_V1)
        self.store.install_skill("other", LOCAL_TEXT_V2)
        self.assertEqual((self.root / "other" / "skill.md").read_text(encoding="utf-8"), LOCAL_TEXT_V2)


class NightlyCheckTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.lock = _lock_in(self.root)
        self.lock.pin("plug-a", sha=SHA_A, kind="external", source="git+https://example.com/a")
        self.lock.pin("plug-b", sha=SHA_B, kind="external", source="git+https://example.com/b")
        self.lock.pin("plug-c", sha=SHA_C, kind="external", source="git+https://example.com/c")
        self.lock.save()

    def test_one_failure_does_not_block_others(self):
        def fetcher(source: str) -> str:
            if source.endswith("/a"):
                return SHA_A  # up to date
            if source.endswith("/b"):
                raise RuntimeError("network down")
            return SHA_A  # plug-c has an update (locked SHA_C -> SHA_A)

        checks = check_plugin_updates(self.lock, fetcher=fetcher)
        by_name = {c.name: c for c in checks}
        self.assertEqual(by_name["plug-a"].status, "up-to-date")
        self.assertEqual(by_name["plug-b"].status, "failed")
        self.assertIn("network down", by_name["plug-b"].error)
        self.assertEqual(by_name["plug-c"].status, "update-available")
        self.assertEqual(by_name["plug-c"].latest_sha, SHA_A)

    def test_plans_only_for_update_available(self):
        def fetcher(source: str) -> str:
            if source.endswith("/a"):
                return SHA_A
            if source.endswith("/b"):
                raise RuntimeError("boom")
            return SHA_A

        plans = plan_upgrades(check_plugin_updates(self.lock, fetcher=fetcher))
        self.assertEqual([p.name for p in plans], ["plug-c"])
        self.assertEqual(plans[0].from_sha, SHA_C)
        self.assertEqual(plans[0].to_sha, SHA_A)

    def test_bump_one_pr_per_plan_and_failure_isolated(self):
        plans = [
            SimpleNamespace(name="plug-c", source="git+https://example.com/c",
                            from_sha=SHA_C, to_sha=SHA_A,
                            branch="work/skill-plugin-bump-plug-c-aaaaaaa", title="bump plug-c"),
            SimpleNamespace(name="plug-d", source="git+https://example.com/d",
                            from_sha=SHA_A, to_sha=SHA_B,
                            branch="work/skill-plugin-bump-plug-d-bbbbbbb", title="bump plug-d"),
        ]
        # plug-d is not in the lockfile: its bump fails, plug-c still bumps.
        self.lock.pin("plug-c", sha=SHA_C, kind="external", source="git+https://example.com/c")
        self.lock.save()
        seen: list[list[str]] = []

        def runner(cmd: list[str]) -> None:
            seen.append(cmd)
            if any("plug-d" in part for part in cmd):
                raise RuntimeError("gh failed for plug-d")

        results = bump_plugins(self.lock, plans, runner=runner, dry_run=False)
        by_name = {r.name: r for r in results}
        self.assertEqual(by_name["plug-c"].status, "bumped")
        self.assertEqual(by_name["plug-d"].status, "failed")
        # plug-c got its own branch + PR commands.
        plug_c_cmds = [c for c in seen if any("plug-c" in part for part in c)]
        self.assertTrue(any(c[0] == "gh" for c in plug_c_cmds))
        # Lockfile actually bumped for plug-c only.
        self.assertEqual(SkillLock(self.root).entry_for("plug-c").sha, SHA_A)

    def test_bump_dry_run_executes_nothing(self):
        plans = [SimpleNamespace(name="plug-c", source="git+https://example.com/c",
                                 from_sha=SHA_C, to_sha=SHA_A,
                                 branch="work/skill-plugin-bump-plug-c-aaaaaaa", title="bump plug-c")]
        called: list[list[str]] = []
        results = bump_plugins(self.lock, plans, runner=called.append, dry_run=True)
        self.assertEqual(results[0].status, "dry-run")
        self.assertEqual(called, [])
        self.assertEqual(SkillLock(self.root).entry_for("plug-c").sha, SHA_C)


if __name__ == "__main__":
    unittest.main()
