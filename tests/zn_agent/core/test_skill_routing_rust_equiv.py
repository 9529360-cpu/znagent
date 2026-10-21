"""PERF-1: Rust/Python equivalence for the skill-routing cue matcher.

Pins ``zn_perf_ext.best_cue_for_header`` (Rust) to
``skill_routing._best_cue_for_header_py`` (pure Python reference):
over a fixed corpus of (query, name, description) triples the two must
return the identical best cue, and ``match_skill_headers`` must return
identical matches whether the Rust extension is used or forced off.

The Rust-specific tests only exist when the extension was built
(``rust/build_ext.sh``); without it the file still verifies the fallback
path, so CI stays green with no skip markers.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from zn_agent.core import skill_routing
from zn_agent.core.skill_routing import (
    SkillHeader,
    _best_cue_for_header_py,
    _cue_occurs,
    _normalize,
    match_skill_headers,
)

try:
    from zn_perf_ext import best_cue_for_header as _rust_best_cue
except ImportError:  # extension not built -> fallback path
    _rust_best_cue = None

# (query, skill name, skill description): covers exact, CJK, boundary,
# single-word, empty and no-match cases.
CORPUS: tuple[tuple[str, str, str], ...] = (
    ("do multi-source web research and managing tasks",
     "deep-research", "Use when doing multi-source web research."),
    ("帮我做中文任务管理", "cn-skill", "当需要中文任务管理时用。"),
    ("at least three sources", "deep-research",
     "Use when doing multi-source web research."),
    ("managing", "task-management", "managing tasks for the team"),
    ("run containerization now", "ship-it", "containerization of services"),
    ("run hypercontainerization now", "ship-it", "containerization of services"),
    ("do web researches now", "deep-research", "web research assistant"),
    ("", "some-skill", "does things quietly"),
    ("hello world", "", ""),
    ("查一下明天的天气", "weather-query", "查询天气和气温变化情况"),
    ("remind me to water the plants", "plant-care",
     "Remind the user to water plants every sunday morning"),
    ("WATER THE PLANTS", "plant-care",
     "Remind the user to water plants every sunday morning"),
    ("a", "a", "a"),
    ("ab", "a", "b"),
    ("今日 Berlin 天气如何", "weather-query", "查询 Berlin 天气预报详情"),
    ("deploy to production", "deploy", "deploy the application"),
    ("redeploy to production", "deploy", "deploy the application"),
)


def _headers(names_descs):
    return [
        SkillHeader(name=n, description=d, version="1.0", path=Path("/tmp/x"))
        for n, d in names_descs
    ]


class DispatchEquivalenceTests(unittest.TestCase):
    """Runs with AND without the extension: the dispatched path must equal
    the forced pure-Python path. Compared on (name, cue length): equal-length
    cue ties are hash-order nondeterministic in the Python version itself,
    so the exact cue string is not pinned -- routing (names + order) is."""

    def test_match_headers_identical_with_rust_on_or_off(self):
        headers = _headers([(n, d) for _, n, d in CORPUS])
        queries = [q for q, _, _ in CORPUS]
        dispatched = [match_skill_headers(headers, q) for q in queries]
        saved = skill_routing._RUST_BEST_CUE
        try:
            skill_routing._RUST_BEST_CUE = None
            forced_py = [match_skill_headers(headers, q) for q in queries]
        finally:
            skill_routing._RUST_BEST_CUE = saved
        for query, a, b in zip(queries, dispatched, forced_py):
            self.assertEqual(
                [(m.header.name, len(m.cue)) for m in a],
                [(m.header.name, len(m.cue)) for m in b],
                f"dispatch mismatch for query {query!r}",
            )


if _rust_best_cue is not None:
    class RustEquivalenceTests(unittest.TestCase):
        """Defined only when zn_perf_ext was built (no skip markers)."""

        def test_best_cue_matches_python_over_corpus(self):
            # Tie-tolerant: equal-length occurring cues are equivalent (the
            # Python version's set iteration is hash-order nondeterministic).
            mismatches = []
            for query, name, description in CORPUS:
                nq, nn, nd = (_normalize(query), _normalize(name),
                              _normalize(description))
                expected = _best_cue_for_header_py(nq, SkillHeader(
                    name=name, description=description, version="1.0",
                    path=Path("/tmp/x")))
                got = _rust_best_cue(nq, nn, nd)
                if got == expected:
                    continue
                tie = (len(got) == len(expected)
                       and _cue_occurs(nq, got) and _cue_occurs(nq, expected))
                if not tie:
                    mismatches.append((query, name, description, expected, got))
            self.assertEqual(mismatches, [],
                             f"Rust/Python cue mismatches: {mismatches[:5]}")

        def test_match_headers_rust_equals_python_end_to_end(self):
            headers = _headers([(n, d) for _, n, d in CORPUS])
            queries = [q for q, _, _ in CORPUS]
            saved = skill_routing._RUST_BEST_CUE
            try:
                skill_routing._RUST_BEST_CUE = None
                expected = [match_skill_headers(headers, q) for q in queries]
                skill_routing._RUST_BEST_CUE = _rust_best_cue
                got = [match_skill_headers(headers, q) for q in queries]
            finally:
                skill_routing._RUST_BEST_CUE = saved
            for query, a, b in zip(queries, expected, got):
                self.assertEqual(
                    [(m.header.name, len(m.cue)) for m in a],
                    [(m.header.name, len(m.cue)) for m in b],
                    f"Rust end-to-end mismatch for query {query!r}",
                )

        def test_seeded_differential_fuzz(self):
            # 300 deterministic adversarial cases (CJK, symbols, case edges).
            import random

            rng = random.Random(20261021)
            latin = ["web", "research", "task", "manage", "deploy", "weather",
                     "multi-source", "containerization", "a", "ab", "ß", "İ",
                     "123", "_x", "co-op", "Über", "naïve"]
            cjk = ["中文", "任务", "管理", "天气", "查询", "预报", "详情", "明日"]
            sym = ["-", "_", ".", "@", "#"]

            def rand_word():
                r = rng.random()
                if r < 0.5:
                    return rng.choice(latin)
                if r < 0.8:
                    return "".join(rng.choice(cjk)
                                   for _ in range(rng.randint(1, 5)))
                return rng.choice(latin) + rng.choice(sym) + rng.choice(latin)

            real_mismatches = []
            for _ in range(300):
                query = " ".join(rand_word() for _ in range(rng.randint(0, 8)))
                name = "-".join(rand_word() for _ in range(rng.randint(1, 3)))
                description = " ".join(rand_word()
                                       for _ in range(rng.randint(1, 20)))
                nq, nn, nd = (_normalize(query), _normalize(name),
                              _normalize(description))
                header = SkillHeader(name=name, description=description,
                                     version="1.0", path=Path("/tmp/x"))
                py = _best_cue_for_header_py(nq, header)
                rs = _rust_best_cue(nq, nn, nd)
                if py == rs:
                    continue
                tie = (len(py) == len(rs)
                       and _cue_occurs(nq, py) and _cue_occurs(nq, rs))
                if not tie:
                    real_mismatches.append((query, name, description, py, rs))
            self.assertEqual(real_mismatches, [],
                             f"real Rust/Python divergences: {real_mismatches[:3]}")
else:
    class RustEquivalenceTests(unittest.TestCase):
        """Extension absent (CI / clean installs): document that the
        pure-Python path is the active product path."""

        def test_fallback_is_active_without_extension(self):
            self.assertIsNone(skill_routing._RUST_BEST_CUE)


if __name__ == "__main__":
    unittest.main()
