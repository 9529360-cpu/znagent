from __future__ import annotations

"""Floor guard (AS-1): "never edit tests to make them pass", mechanically.

The rule that test suppression is forbidden used to live only in prompt
text. This module turns it into a deterministic check over a unified
diff: it flags added lines that suppress, skip, delete, or stub out
tests, and removed lines that weaken the floor itself (CONSTRAINTS.md,
this module, or its CI workflow).

Design notes (deliberate trade-offs, see CONSTRAINTS.md):

- Diff-only. Existing code is grandfathered: only lines this diff adds
  or removes are judged. A suppression that already exists in the repo
  is not flagged until someone touches those lines.
- Violations block (the CI check fails); warnings never block but the
  author must disposition each one in the PR (fix it or record why it
  is acceptable).
- Three exemptions keep the false-positive rate down:
  1. Prohibition lines: a line that *forbids* the pattern ("Do not add
     `# noqa`", "NEVER use pytest.skip") is not a use of the pattern.
  2. String literals: a pattern inside quotes on the same line is
     documentation / test data, not a live suppression.
  3. Triple-quoted strings: docstrings and test fixtures that quote a
     pattern are not live code.
- No allowlist mechanism exists on purpose: there is no exemption list
  anyone could add a file to in order to bypass the guard. The only way
  past a violation is the exception process in CONSTRAINTS.md (recorded
  approval in the PR; the check stays red and a human merges it).
- This module is NOT wired into any runtime path. It runs in CI over
  the PR diff and as a local script. It changes no runtime behaviour.

Exit-code contract lives in ``scripts/floor_guard.py``.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

#: Added-line patterns that count as test suppression. Each entry is
#: (rule id, compiled pattern, file predicate). Patterns are written with
#: escaped dots (``\\.``) so a pattern never matches its own definition
#: line: the definition text contains a backslash where the pattern
#: expects a literal dot.
_SUPPRESSION_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("noqa", re.compile(r"#\s*noqa\b"), "py"),
    ("type-ignore", re.compile(r"#\s*type:\s*ignore\b"), "py"),
    ("pylint-disable", re.compile(r"#\s*pylint:\s*disable\b"), "py"),
    ("nosec-comment", re.compile(r"#\s*nosec\b"), "py"),
    ("nosec-comment", re.compile(r"//\s*nosec\b"), "c"),
    ("eslint-disable", re.compile(r"//\s*eslint-disable\b"), "js"),
    ("ts-ignore", re.compile(r"//\s*@ts-(ignore|nocheck)\b"), "js"),
)

#: Skip markers: the test is not run at all, so a red test can be hidden
#: by adding one line. ``xfail`` is a warning, not a violation: it still
#: runs the test and fails the suite when the test unexpectedly passes
#: under ``strict``.
_SKIP_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("pytest-mark-skip", re.compile(r"@pytest\.mark\.skip(if)?\b"), "py"),
    ("pytest-skip", re.compile(r"\bpytest\.skip\s*\("), "py"),
    ("unittest-skip", re.compile(r"@unittest\.skip(If|Unless)?\b"), "py"),
    (
        "js-test-skip",
        re.compile(r"\b(describe|it|test|suite)\.skip\s*\("),
        "js",
    ),
    ("js-test-x", re.compile(r"\b(xit|xdescribe|fit|fdescribe)\s*\("), "js"),
)

#: Warning-only patterns: suspicious, but legitimate uses exist, so a
#: human dispositions them instead of the guard blocking.
_WARNING_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("pytest-xfail", re.compile(r"\bpytest\.(mark\.)?xfail\s*\("), "py"),
    (
        "unittest-expected-failure",
        re.compile(r"@unittest\.expectedFailure\b"),
        "py",
    ),
    ("pragma-no-cover", re.compile(r"#\s*pragma:\s*no\s+cover\b"), "py"),
    ("istanbul-ignore", re.compile(r"//\s*istanbul\s+ignore\b"), "js"),
)

#: A line that forbids the pattern is a prohibition, not a use of it.
#: Matched before any suppression rule, same line only.
_NEGATION_RE = re.compile(
    r"\b(do\s+not|never|don'?t|must\s+not|cannot|forbidden|prohibited|"
    r"banned|no\s+exception)\b|禁止|不许|不得|不要|切勿|绝不|严禁|没有例外",
    re.IGNORECASE,
)

#: Added lines in CONSTRAINTS.md that grant a blanket pass. Guarded by
#: _NEGATION_RE: a line that *forbids* such a pass ("... is prohibited")
#: is skipped, so the doc can describe the forbidden phrases.
_PERMISSIVE_RE = (
    re.compile(r"(无需|不用|不必).{0,10}(批准|审批)"),
    re.compile(r"(可以|允许).{0,10}(跳过|删除|绕过).{0,10}(测试|断言|检查|守卫|门禁)"),
    re.compile(
        r"\b(may|can|allowed\s+to)\b.{0,30}"
        r"\b(skip|delete|bypass|disable)\b.{0,30}"
        r"\b(test|assertion|check|guard)\b",
        re.IGNORECASE,
    ),
)
_PERMISSIVE_NEGATION_RE = re.compile(
    r"(不|never|not|no)\W{0,5}(可以|may|can|allowed)", re.IGNORECASE
)

#: Removed-line patterns that count as deleting a test or an assertion
#: in a test file. A removed line whose normalized form reappears in the
#: same file's added lines is a move, not a deletion, and is not flagged.
_TEST_DELETE_PATTERNS = (
    re.compile(r"^\s*(async\s+def\s+test_\w+|def\s+test_\w+)"),
    re.compile(r"^\s*assert\b"),
    re.compile(r"^\s*self\.assert\w+\s*\("),
    re.compile(r"^\s*(it|test|describe)\s*\("),
    re.compile(r"^\s*expect\s*\(.*\)\s*\.\s*(to|not)\b"),
    re.compile(r"\bassert\.\w+\s*\("),
)

#: Assertion-update pairing for the deletion check above. Captures
#: ``self.assert<Method>(<target>, ...)`` as (method, target): a removed
#: assertion whose method and locked target reappear in an added line of
#: the same file is an *updated* assertion (new expected value, same
#: lock), not a deletion. A different assertion method or a different
#: locked target is still a deletion -- the lock itself changed. Only
#: the single-line unittest style is paired; bare ``assert`` statements
#: and multi-line assertions keep the stricter behaviour.
_ASSERT_LOCK_RE = re.compile(r"^\s*self\.(assert\w+)\s*\(\s*([^,)]+)")


def _assert_lock_key(line_text: str) -> tuple[str, str] | None:
    """Return the (method, locked-target) pair of a unittest assertion line.

    ``None`` when the line is not a single-line ``self.assert...`` call.
    """
    match = _ASSERT_LOCK_RE.match(line_text)
    if match is None:
        return None
    return (match.group(1), _normalize(match.group(2)))

#: Removed production-code assertions are a warning, not a violation:
#: refactoring sometimes removes a redundant runtime assert.
_PROD_ASSERT_RE = re.compile(r"^\s*assert\b")

#: Stub markers in non-test code. Type stubs (.pyi) are exempt: a lone
#: ellipsis is the whole point of a stub file.
_STUB_PATTERNS = (
    ("not-implemented", re.compile(r"\braise\s+NotImplementedError\b")),
    ("not-implemented-return", re.compile(r"\breturn\s+NotImplemented\b")),
    (
        "pass-stub-comment",
        re.compile(
            r"^\s*pass\s*#.*(stub|todo|placeholder|not\s+implemented|fixme)",
            re.IGNORECASE,
        ),
    ),
    (
        "mock-import-in-prod",
        re.compile(
            r"^\s*(from\s+unittest(\.mock)?\s+import|import\s+unittest\.mock"
            r"|from\s+mock\s+import|import\s+mock\b)"
        ),
    ),
)

#: Stub-adjacent comments in non-test code: warning only, TODOs are a
#: normal workflow. Capped per file (see _cap).
_TODO_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")

#: Rule lines in CONSTRAINTS.md: list items / headings / numbered rules
#: that state a prohibition or a requirement. Removing one is weakening
#: the floor itself.
_CONSTRAINTS_RULE_KEYWORDS = (
    "NEVER",
    "MUST NOT",
    "MUST",
    "REQUIRED",
    "禁止",
    "不许",
    "不得",
    "不要",
    "切勿",
    "绝不",
    "必须",
    "严禁",
)

_PY_EXTS = frozenset({".py"})
_JS_EXTS = frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"})
_C_EXTS = frozenset({".c", ".cpp", ".cc", ".h", ".hpp", ".go", ".rs", ".java", ".rb", ".php", ".cs", ".swift", ".kt"})
_TEST_BASENAMES = ("test_",)
_TEST_SUFFIXES = (".test.", ".spec.")

#: Per-file, per-category cap: report the first N plus a "+M more" note
#: so a big refactor cannot flood the report. Deterministic.
_CAP = 10


@dataclass(frozen=True, slots=True)
class DiffLine:
    """One line of a unified diff. ``kind`` is '+', '-', or ' '."""

    kind: str
    text: str
    new_lineno: int | None = None


@dataclass(slots=True)
class FileDiff:
    """One file's slice of a unified diff."""

    old_path: str
    new_path: str
    lines: list[DiffLine] = field(default_factory=list)
    is_binary: bool = False

    @property
    def is_new(self) -> bool:
        return self.old_path == "/dev/null"

    @property
    def is_deleted(self) -> bool:
        return self.new_path == "/dev/null"

    @property
    def path(self) -> str:
        return self.new_path if not self.is_deleted else self.old_path


@dataclass(frozen=True, slots=True)
class FloorGuardResult:
    """Outcome of :func:`check_diff`.

    ``passed`` is True only when there are no violations. Warnings never
    block, but the author must disposition each one in the PR.
    """

    passed: bool
    violations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _normalize(line: str) -> str:
    return " ".join(line.split())


def _family(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in _PY_EXTS:
        return "py"
    if suffix in _JS_EXTS:
        return "js"
    if suffix in _C_EXTS:
        return "c"
    return ""


def _is_test_file(path: str) -> bool:
    name = Path(path).name
    lowered = path.lower()
    if name.startswith(_TEST_BASENAMES):
        return True
    if any(s in name for s in _TEST_SUFFIXES):
        return True
    return "/tests/" in lowered or "/test/" in lowered or lowered.endswith("/test.py")


def _is_triple_quote_boundary(line: str) -> str | None:
    """Return the triple-quote delimiter this line toggles, if any.

    A line with an odd count of one delimiter opens or closes a
    triple-quoted string. Lines with an even count (open + close on one
    line) toggle nothing.
    """
    for delim in ('"""', "'''"):
        if line.count(delim) % 2 == 1:
            return delim
    return None


def _in_string_before(line: str, pos: int) -> bool:
    """True if ``pos`` sits inside a single-line string literal.

    Heuristic: an odd count of unescaped quotes before the match means
    the match is quoted. Apostrophes in comments ("don't") err toward
    exemption, which is the safe direction for a guard (a missed flag is
    visible in review; a false flag blocks a good PR).
    """
    for quote in ('"', "'"):
        count = 0
        i = 0
        while i < pos:
            if line[i] == quote and (i == 0 or line[i - 1] != "\\"):
                count += 1
            i += 1
        if count % 2 == 1:
            return True
    return False


def _location(path: str, lineno: int | None) -> str:
    return f"{path}:{lineno}" if lineno is not None else path


def _cap(items: list[str], label: str) -> list[str]:
    if len(items) <= _CAP:
        return items
    return items[:_CAP] + [f"... and {len(items) - _CAP} more {label}"]


def parse_unified_diff(diff_text: str) -> list[FileDiff]:
    """Parse unified diff text into per-file line lists.

    Tolerant: hunk headers are optional, missing ``diff --git`` headers
    still yield one file when ``---``/``+++`` pairs are present, and
    binary files are recorded and skipped by the checker.
    """
    files: list[FileDiff] = []
    current: FileDiff | None = None
    new_lineno = 0

    def _ensure_current() -> FileDiff:
        nonlocal current
        if current is None:
            current = FileDiff(old_path="unknown", new_path="unknown")
            files.append(current)
        return current

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            parts = raw.split()
            old = parts[2][2:] if len(parts) > 2 and parts[2].startswith("a/") else parts[2] if len(parts) > 2 else "unknown"
            new = parts[3][2:] if len(parts) > 3 and parts[3].startswith("b/") else parts[3] if len(parts) > 3 else "unknown"
            current = FileDiff(old_path=old, new_path=new)
            files.append(current)
            new_lineno = 0
            continue
        if raw.startswith("Binary files "):
            _ensure_current().is_binary = True
            continue
        if raw.startswith("--- "):
            target = raw[4:].strip().split("\t")[0]
            target = target[2:] if target.startswith("a/") else target
            _ensure_current().old_path = target
            continue
        if raw.startswith("+++ "):
            target = raw[4:].strip().split("\t")[0]
            target = target[2:] if target.startswith("b/") else target
            _ensure_current().new_path = target
            continue
        if raw.startswith("@@ "):
            match = re.search(r"\+(\d+)", raw)
            new_lineno = int(match.group(1)) if match else 0
            continue
        if raw.startswith("\\ "):
            continue
        if raw[:1] in ("+", "-", " "):
            kind = raw[0]
            text = raw[1:]
            lineno: int | None = None
            if kind in ("+", " "):
                new_lineno += 1
                lineno = new_lineno
            _ensure_current().lines.append(DiffLine(kind, text, lineno))
            continue
    return files


def _check_added_line(
    path: str, line: DiffLine, in_triple: bool, violations: list[str], warnings: list[str]
) -> None:
    text = line.text
    loc = _location(path, line.new_lineno)
    snippet = text.strip()[:120]
    family = _family(path)
    if family == "" or in_triple:
        return
    is_test = _is_test_file(path)

    def _exempt(match: re.Match[str]) -> bool:
        if _NEGATION_RE.search(text):
            return True
        return _in_string_before(text, match.start())

    for rule_id, pattern, pattern_family in _SUPPRESSION_PATTERNS:
        if pattern_family != family:
            continue
        match = pattern.search(text)
        if match and not _exempt(match):
            violations.append(f"{loc}: suppression comment ({rule_id}): {snippet}")
            break
    for rule_id, pattern, pattern_family in _SKIP_PATTERNS:
        if pattern_family != family:
            continue
        match = pattern.search(text)
        if match and not _exempt(match):
            violations.append(f"{loc}: skip marker ({rule_id}): {snippet}")
            break
    for rule_id, pattern, pattern_family in _WARNING_PATTERNS:
        if pattern_family != family:
            continue
        match = pattern.search(text)
        if match and not _exempt(match):
            warnings.append(f"{loc}: warning ({rule_id}): {snippet}")
            break

    if not is_test:
        for rule_id, pattern in _STUB_PATTERNS:
            match = pattern.search(text)
            if match and not _exempt(match):
                violations.append(f"{loc}: stub ({rule_id}): {snippet}")
                break
        # Pattern-definition lines (this file's own regex table) name the
        # markers they match; they are not TODO comments in code.
        if (
            _TODO_RE.search(text)
            and not _NEGATION_RE.search(text)
            and "re.compile" not in text
        ):
            warnings.append(f"{loc}: warning (todo-marker): {snippet}")


def _check_except_pairs(
    file_diff: FileDiff, violations: list[str], warnings: list[str]
) -> None:
    """Flag empty ``except: pass`` handlers, same-line or next-line.

    The pair is judged on the new file's line order (added + context
    lines): a diff that completes an empty handler by adding either half
    is flagged. A bare ``except:`` with real handling is a warning only.
    """
    if _family(file_diff.path) != "py":
        return
    new_lines = [ln for ln in file_diff.lines if ln.kind in ("+", " ")]
    for index, line in enumerate(new_lines):
        text = line.text
        if _NEGATION_RE.search(text):
            continue
        loc = _location(file_diff.path, line.new_lineno)
        snippet = text.strip()[:120]
        same_line = re.match(r"^\s*except\b.*:\s*(pass|\.\.\.)\s*(#.*)?$", text)
        if same_line:
            if line.kind == "+":
                violations.append(f"{loc}: empty except handler: {snippet}")
            continue
        if not re.match(r"^\s*except\b.*:\s*(#.*)?$", text):
            continue
        if index + 1 < len(new_lines):
            nxt = new_lines[index + 1]
            if re.match(r"^\s*(pass|\.\.\.)\s*(#.*)?$", nxt.text):
                if line.kind == "+" or nxt.kind == "+":
                    violations.append(
                        f"{loc}: empty except handler: {snippet}"
                    )
                continue
        if re.match(r"^\s*except\s*:", text) and line.kind == "+":
            warnings.append(f"{loc}: warning (bare-except): {snippet}")


def _check_deletions(
    file_diff: FileDiff,
    added_normalized: set[str],
    violations: list[str],
    warnings: list[str],
) -> None:
    path = file_diff.path
    removed = [ln for ln in file_diff.lines if ln.kind == "-"]
    if not removed:
        return
    is_test = _is_test_file(path)
    # Assertion-update pairing: a removed ``self.assert<Method>(<target>,
    # ...)`` whose (method, locked-target) key reappears among this file's
    # added lines is an *updated* assertion (new expected value, same
    # lock), not a deletion. See _ASSERT_LOCK_RE.
    added_locks: set[tuple[str, str]] = set()
    for added_line in file_diff.lines:
        if added_line.kind != "+":
            continue
        lock_key = _assert_lock_key(added_line.text)
        if lock_key is not None:
            added_locks.add(lock_key)
    gone: list[str] = []
    for line in removed:
        normalized = _normalize(line.text)
        if not normalized or normalized in added_normalized:
            continue
        if is_test and any(p.search(line.text) for p in _TEST_DELETE_PATTERNS):
            lock_key = _assert_lock_key(line.text)
            if lock_key is not None and lock_key in added_locks:
                continue
            gone.append(
                f"{path}: deleted test/assertion: {line.text.strip()[:120]}"
            )
        elif not is_test and _PROD_ASSERT_RE.search(line.text):
            warnings.append(
                f"{path}: warning (removed production assert): "
                f"{line.text.strip()[:120]}"
            )
    violations.extend(_cap(gone, "deleted test/assertion lines"))


def _check_self_weakening(
    file_diff: FileDiff,
    added_normalized: set[str],
    violations: list[str],
) -> None:
    path = file_diff.path
    name = Path(path).name
    removed = [ln for ln in file_diff.lines if ln.kind == "-"]
    if name == "CONSTRAINTS.md":
        for line in removed:
            normalized = _normalize(line.text)
            if not normalized or normalized in added_normalized:
                continue
            stripped = line.text.strip()
            is_rule = stripped.startswith(("#", "-", "*", "1.", "2.", "3."))
            if is_rule and any(k in line.text for k in _CONSTRAINTS_RULE_KEYWORDS):
                violations.append(
                    f"{path}: CONSTRAINTS.md rule removed/weakened: "
                    f"{stripped[:120]}"
                )
        for line in file_diff.lines:
            if line.kind != "+":
                continue
            if _NEGATION_RE.search(line.text):
                continue
            if _PERMISSIVE_NEGATION_RE.search(line.text):
                continue
            if any(p.search(line.text) for p in _PERMISSIVE_RE):
                violations.append(
                    f"{_location(path, line.new_lineno)}: CONSTRAINTS.md "
                    f"adds a blanket pass: {line.text.strip()[:120]}"
                )
    elif name == "floor_guard.py":
        for line in removed:
            if "re.compile" in line.text:
                violations.append(
                    f"{path}: floor-guard self-weakening (pattern removed): "
                    f"{line.text.strip()[:120]}"
                )
    elif name == "zn-floor-guard.yml":
        for line in removed:
            if "floor_guard.py" in line.text:
                violations.append(
                    f"{path}: floor-guard CI weakened (invocation removed): "
                    f"{line.text.strip()[:120]}"
                )


def _file_moved(file_diff: FileDiff, all_files: list[FileDiff]) -> bool:
    """True if a deleted test file's content reappears in one added file.

    Two move shapes: same basename added elsewhere (a directory move),
    or a differently-named new test file whose added lines cover every
    removed test/assertion line of the deleted file (a rename with
    content intact). Per-line cross-file matching is deliberately NOT
    used elsewhere: an identical assertion added in another file must
    not excuse deleting one here.
    """
    if not file_diff.is_deleted or not _is_test_file(file_diff.path):
        return False
    removed_tests = {
        _normalize(ln.text)
        for ln in file_diff.lines
        if ln.kind == "-"
        and _normalize(ln.text)
        and any(p.search(ln.text) for p in _TEST_DELETE_PATTERNS)
    }
    for other in all_files:
        if other is file_diff or other.is_deleted:
            continue
        if Path(other.path).name == Path(file_diff.path).name:
            return True
        if not other.is_new or not _is_test_file(other.path):
            continue
        other_added = {
            _normalize(ln.text) for ln in other.lines if ln.kind == "+"
        }
        if removed_tests and removed_tests <= other_added:
            return True
    return False


def _check_file(
    file_diff: FileDiff, all_files: list[FileDiff]
) -> tuple[list[str], list[str]]:
    violations: list[str] = []
    warnings: list[str] = []
    if file_diff.is_binary:
        return violations, warnings
    path = file_diff.path

    added = [ln for ln in file_diff.lines if ln.kind == "+"]
    added_normalized = {_normalize(ln.text) for ln in added if _normalize(ln.text)}

    # Deleted test file: flagged unless its content moved (see _file_moved).
    # A moved file's per-line deletions are covered by the same check.
    is_moved_deleted = (
        file_diff.is_deleted
        and _is_test_file(path)
        and _file_moved(file_diff, all_files)
    )
    if file_diff.is_deleted and _is_test_file(path) and not is_moved_deleted:
        violations.append(f"{path}: deleted test file without replacement")

    # Triple-quote state walks added + context lines (the new file's
    # order); only added lines are judged.
    in_triple: str | None = None
    for line in file_diff.lines:
        if line.kind not in ("+", " "):
            continue
        if _family(path) == "py":
            if in_triple is not None:
                was_inside = True
                if in_triple in line.text and line.text.count(in_triple) % 2 == 1:
                    in_triple = None
            else:
                was_inside = False
                delim = _is_triple_quote_boundary(line.text)
                if delim is not None:
                    in_triple = delim
            if line.kind == "+":
                _check_added_line(path, line, was_inside, violations, warnings)
        elif line.kind == "+":
            _check_added_line(path, line, False, violations, warnings)

    _check_except_pairs(file_diff, violations, warnings)
    if not is_moved_deleted:
        _check_deletions(file_diff, added_normalized, violations, warnings)
    _check_self_weakening(file_diff, added_normalized, violations)
    return violations, warnings


def check_diff(diff_text: str) -> FloorGuardResult:
    """Check one unified diff. Deterministic; no I/O, no network."""
    files = parse_unified_diff(diff_text)
    violations: list[str] = []
    warnings: list[str] = []
    for file_diff in files:
        file_violations, file_warnings = _check_file(file_diff, files)
        violations.extend(file_violations)
        warnings.extend(file_warnings)
    return FloorGuardResult(
        passed=not violations,
        violations=tuple(violations),
        warnings=tuple(warnings),
    )


def check_diff_file(path: Path) -> FloorGuardResult:
    """Check a diff stored in a file (UTF-8; undecodable = violation)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return FloorGuardResult(
            passed=False,
            violations=("diff file is missing or not valid UTF-8",),
        )
    return check_diff(text)


__all__ = [
    "DiffLine",
    "FileDiff",
    "FloorGuardResult",
    "check_diff",
    "check_diff_file",
    "parse_unified_diff",
]
