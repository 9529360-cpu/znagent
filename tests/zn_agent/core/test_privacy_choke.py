from __future__ import annotations

import inspect
import re
import tempfile
import unittest
from pathlib import Path

from zn_agent.core.credential_isolation import contains_credential_value
from zn_agent.core.memory import Observation, StructuredMemory
from zn_agent.core.privacy_choke import (
    MAX_FIELD_CHARS,
    clear_custom_patterns,
    register_custom_pattern,
    strip_tags,
    stripTags,
)
from zn_agent.core.project_team import assemble_team
from zn_agent.core.store import KernelStore
from zn_agent.core.team_memory import (
    distill_retrospective,
    save_retrospective,
    specialist_memory,
    team_shared_memory,
)
from zn_agent.core.team_timeline import (
    assignee_overrides,
    record_assignee_override,
)
from zn_agent.core import team_memory as team_memory_module
from zn_agent.core import team_timeline as team_timeline_module

# Secrets that must never survive the choke. Each is paired with a
# substring that must ALSO be gone from stored output (the secret
# itself, not just the pattern shape).
SECRET_FIXTURES = [
    ("assignment", "api_key=sk-live-1234567890abcdef", "sk-live-1234567890abcdef"),
    ("bearer", "Authorization: Bearer abcdefgh12345678", "abcdefgh12345678"),
    ("github-token", "token ghp_ABCDEFGHIJKLMNOPQRST", "ghp_ABCDEFGHIJKLMNOPQRST"),
    ("url-userinfo", "https://user:hunter2@example.com/x", "hunter2"),
    ("query-secret", "https://x.com/?api_key=SECRET123", "SECRET123"),
    ("password", 'password = "hunter2"', "hunter2"),
    ("jwt", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signaturepart123456",
     "eyJhbGciOiJIUzI1NiJ9"),
    ("pem", "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg==\n-----END PRIVATE KEY-----",
     "MIIEvQIBADANBg=="),
]


class StripTagsTests(unittest.TestCase):
    def tearDown(self):
        clear_custom_patterns()

    def test_private_block_removed_surrounding_kept(self):
        out = strip_tags("keep <private>do not store</private> after")
        self.assertEqual(out, "keep [private content removed] after")
        self.assertNotIn("do not store", out)

    def test_private_unclosed_swallows_rest(self):
        out = strip_tags("keep <private>secret to end")
        self.assertEqual(out, "keep [private content removed]")
        self.assertNotIn("secret", out)

    def test_private_nested_fully_dropped(self):
        out = strip_tags("a<private>x<private>y</private>z</private>b")
        self.assertEqual(out, "a[private content removed]b")
        for leaked in ("x", "y", "z"):
            self.assertNotIn(leaked, out)

    def test_private_case_insensitive_and_attributes(self):
        out = strip_tags('a <PRIVATE reason="note">SECRET</PRIVATE> b')
        self.assertEqual(out, "a [private content removed] b")
        self.assertNotIn("SECRET", out)

    def test_private_stray_close_dropped(self):
        self.assertEqual(strip_tags("a</private>b"), "ab")

    def test_secrets_redacted_and_storable(self):
        # Scrubbed output must pass the M15 put_fact gate, or the choke
        # would redact-then-reject instead of redact-and-continue.
        for _name, raw, secret in SECRET_FIXTURES:
            out = strip_tags(raw)
            self.assertNotIn(secret, out)
            self.assertFalse(
                contains_credential_value(out),
                f"scrubbed output still trips the M15 gate: {out!r}",
            )

    def test_credential_reference_passes_through(self):
        ref = "credential:api_key:abc123def456"
        self.assertEqual(strip_tags(ref), ref)
        self.assertEqual(strip_tags("use provider:openai here"), "use provider:openai here")

    def test_custom_pattern_registered_and_cleared(self):
        register_custom_pattern(r"ProjectFalcon")
        self.assertEqual(
            strip_tags("codename ProjectFalcon here"), "codename [redacted-custom] here"
        )
        clear_custom_patterns()
        self.assertEqual(strip_tags("codename ProjectFalcon here"), "codename ProjectFalcon here")

    def test_custom_pattern_bad_regex_rejected_at_registration(self):
        with self.assertRaises(re.error):
            register_custom_pattern(r"(unclosed")

    def test_overlong_field_replaced_whole(self):
        out = strip_tags("x" * 100, max_field_chars=10)
        self.assertEqual(out, "[redacted: field exceeded 10 chars (100 chars)]")
        self.assertNotIn("x" * 100, out)
        # Default threshold: a 40k-char field is replaced whole.
        out = strip_tags("y" * (MAX_FIELD_CHARS + 1))
        self.assertTrue(out.startswith("[redacted: field exceeded"))
        self.assertNotIn("y" * 100, out)

    def test_containers_sanitized_leaf_by_leaf(self):
        out = strip_tags({"k": "api_key=zzz", "n": 42, "flag": None, "lst": ["<private>x</private>"]})
        self.assertEqual(out["k"], "api_key <redacted>")
        self.assertEqual(out["n"], 42)
        self.assertIsNone(out["flag"])
        self.assertEqual(out["lst"], ["[private content removed]"])
        self.assertEqual(strip_tags(("a", "password=hunter2")), ("a", "password <redacted>"))

    def test_never_raises_fail_closed(self):
        class Bad:
            def __str__(self):
                raise RuntimeError("boom")

        self.assertEqual(strip_tags(Bad()), "[redacted: privacy choke failed]")
        self.assertEqual(strip_tags({Bad(): "v"}), "[redacted: privacy choke failed]")

    def test_stripTags_alias_is_same_function(self):
        self.assertIs(stripTags, strip_tags)


class MemoryChokeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zn-cm3-"))
        self.store = KernelStore(self.root / "memory.db")
        self.memory = StructuredMemory(self.store)

    def tearDown(self):
        self.store.close()
        clear_custom_patterns()

    def test_remember_redacts_secret_instead_of_rejecting(self):
        # Before CM-3 this raised CredentialValueDetected at the M15 gate.
        self.memory.remember("note", "api_key=sk-live-1234567890abcdef")
        match = self.memory.recall("note")
        assert match is not None
        self.assertEqual(match.value, "api_key <redacted>")
        self.assertNotIn("sk-live", str(match.value))

    def test_remember_redacts_private_block(self):
        self.memory.remember("note", "keep <private>do not store</private> after")
        match = self.memory.recall("note")
        assert match is not None
        self.assertEqual(match.value, "keep [private content removed] after")

    def test_remember_redacts_nested_value_and_alias(self):
        self.memory.remember(
            "config",
            {"endpoint": "https://user:hunter2@example.com/x", "plain": "ok"},
            aliases=("api_key=sk-live-1234567890abcdef",),
        )
        facts = [f for f in self.store.list_facts() if f["key"] == "config"]
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["value"]["endpoint"], "https://<redacted-userinfo>@example.com/x")
        self.assertNotIn("hunter2", str(facts[0]))
        self.assertNotIn("sk-live", str(facts[0]["aliases"]))

    def test_remember_overlong_value_replaced_whole(self):
        self.memory.remember("dump", "z" * (MAX_FIELD_CHARS + 1))
        match = self.memory.recall("dump")
        assert match is not None
        self.assertTrue(str(match.value).startswith("[redacted: field exceeded"))
        self.assertNotIn("z" * 100, str(match.value))

    def test_remember_credential_reference_passes_through(self):
        self.memory.remember("cred", "credential:api_key:abc123def456")
        match = self.memory.recall("cred")
        assert match is not None
        self.assertEqual(match.value, "credential:api_key:abc123def456")

    def test_record_observation_redacts_fields(self):
        key = self.memory.record_observation(
            Observation(
                kind="learned",
                title="auth note",
                facts=["api_key=sk-live-1234567890abcdef"],
                narrative="keep <private>do not store</private> after",
            )
        )
        stored = self.store.get_fact(key)
        assert isinstance(stored, dict)
        self.assertEqual(stored["facts"], ["api_key <redacted>"])
        self.assertEqual(stored["narrative"], "keep [private content removed] after")
        self.assertNotIn("sk-live", str(stored))
        # Recall by the (sanitized) title still works.
        self.assertIsNotNone(self.memory.recall_observation("auth note"))


class TeamChokeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zn-cm3-team-"))
        self.store = KernelStore(self.root / "memory.db")
        self.memory = StructuredMemory(self.store)
        self.team = assemble_team("X", ["researcher", "developer"], team_id="t9")
        self.arch = specialist_memory(self.memory, self.team.members[0])
        self.shared = team_shared_memory(self.memory, "t9")

    def tearDown(self):
        self.store.close()
        clear_custom_patterns()

    def test_team_memory_remember_redacts(self):
        self.arch.remember("note", "token ghp_ABCDEFGHIJKLMNOPQRST")
        match = self.arch.recall("note")
        assert match is not None
        self.assertEqual(match.value, "token <redacted>")
        self.assertNotIn("ghp_", str(match.value))

    def test_save_retrospective_redacts_journal_secrets(self):
        entries = [
            {
                "role": "team:t9:researcher",
                "text": "decided: api_key=sk-live-1234567890abcdef",
                "detail": {"kind": "decision", "team_id": "t9", "author": "researcher"},
            },
            {
                "role": "team:t9:developer",
                "text": "keep <private>do not store</private> after",
                "detail": {"kind": "decision", "team_id": "t9", "author": "developer"},
            },
        ]
        retro = distill_retrospective("t9", entries)
        save_retrospective(self.shared, retro)
        match = self.shared.recall("retrospective")
        assert match is not None
        self.assertNotIn("sk-live", str(match.value))
        self.assertNotIn("do not store", str(match.value))
        self.assertIn("api_key <redacted>", str(match.value))

    def test_record_assignee_override_sanitizes_identifiers(self):
        overrides = record_assignee_override(
            self.memory, "t9", "item-1", "dev<private>secret</private>"
        )
        self.assertNotIn("secret", str(overrides))
        self.assertEqual(assignee_overrides(self.memory, "t9"), overrides)


class NoBypassTests(unittest.TestCase):
    """Tripwire: every direct facts-table write in the owned modules must
    run through the choke. ``consolidate`` re-writes already-sanitized
    values, so it is the only other allowed ``put_fact`` site."""

    def _put_fact_sites(self, module_path: Path) -> dict[str, str]:
        source = module_path.read_text(encoding="utf-8")
        sites: dict[str, str] = {}
        current = "<module>"
        for lineno, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("def ") and line and not line[0].isspace():
                current = stripped[4:].split("(")[0]
            elif stripped.startswith("def ") and line.startswith("    "):
                current = stripped[4:].split("(")[0]
            if "put_fact(" in line and "def put_fact" not in line:
                sites[f"{module_path.name}:{lineno}"] = current
        return sites

    def test_capture_entry_points_call_strip_tags(self):
        for fn in (
            StructuredMemory.remember,
            StructuredMemory.record_observation,
            team_memory_module.TeamMemory.remember,
            team_timeline_module.record_assignee_override,
        ):
            self.assertIn("strip_tags", inspect.getsource(fn), fn.__qualname__)

    def test_no_unchoked_put_fact_in_owned_modules(self):
        core = Path(inspect.getfile(StructuredMemory)).parent
        allowed = {"remember", "record_observation", "consolidate"}
        for name in ("memory.py", "team_memory.py", "team_timeline.py"):
            sites = self._put_fact_sites(core / name)
            for site, enclosing in sites.items():
                self.assertIn(
                    enclosing, allowed,
                    f"unchoked put_fact at {site} in {enclosing}()",
                )
        # team_memory / team_timeline must not write the facts table
        # directly at all -- they go through StructuredMemory.remember.
        for name in ("team_memory.py", "team_timeline.py"):
            self.assertEqual(
                self._put_fact_sites(core / name), {},
                f"{name} must not call put_fact directly",
            )


if __name__ == "__main__":
    unittest.main()
