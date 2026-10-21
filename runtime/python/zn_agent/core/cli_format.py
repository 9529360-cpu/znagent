"""Terminal presentation primitives for the ``zn`` CLI (T2-1, TERM-2 foundation).

Single formatting home for terminal output in ``zn_cli.py`` and the
TERM-1 REPL: semantic colors, symbols, ``key=value`` pairs, aligned
tables, section headers, and a status-word vocabulary.

Rules (fail-closed, script-safe):

- A stream is colored only when :func:`use_color` says so: the stream is a
  TTY, ``NO_COLOR`` is unset (any value disables), and ``TERM`` is not
  ``dumb``.
- Non-TTY / ``NO_COLOR`` / ``TERM=dumb`` output is plain text and stays
  byte-identical to the historic output, so scripts that parse ``zn``
  output keep working. ``--json`` output never goes through this module.
- Everything here is defensive about untrusted text: colorize AFTER the
  caller has already sanitized the string (see ``_one_line`` in
  ``zn_cli.py``); escape codes are fixed constants, never built from
  user data.

Extension point for T2-7 (Windows console encoding downgrade):

- :func:`symbol` currently returns the Unicode glyph in color mode and the
  empty string otherwise. T2-7 will switch its selection to be encoding
  aware -- ``cp936``/non-UTF consoles fall back to the ASCII table --
  using :func:`_detect_stdout_encoding` plus the ``_ASCII_SYMBOLS`` table
  below. Callers will not change; only the selection logic inside
  :func:`symbol` does.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Mapping, TextIO

__all__ = [
    "is_tty",
    "use_color",
    "colorize",
    "section",
    "kv",
    "table",
    "status_word",
    "symbol",
    "COLOR_OK",
    "COLOR_WARN",
    "COLOR_ERR",
    "COLOR_DIM",
]

# Semantic colors: success green / warning yellow / failure red / dimmed gray.
COLOR_OK = "\033[32m"
COLOR_WARN = "\033[33m"
COLOR_ERR = "\033[31m"
COLOR_DIM = "\033[2m"
_COLOR_RESET = "\033[0m"

_COLORS = {
    "ok": COLOR_OK,
    "warn": COLOR_WARN,
    "err": COLOR_ERR,
    "dim": COLOR_DIM,
}

# Symbols are a TTY-only affordance: in non-color mode ``symbol()`` returns
# "", so piped/script output never contains glyphs it cannot parse or show.
_UNICODE_SYMBOLS = {
    "ok": "✓",
    "fail": "✗",
    "warn": "!",
    "pending": "…",
}

# T2-7 extension point: ASCII fallback for consoles whose encoding cannot
# render the BMP glyphs above (e.g. Windows cp936). Not selected by
# ``symbol()`` yet -- T2-7 adds the encoding-aware selection.
_ASCII_SYMBOLS = {
    "ok": "OK",
    "fail": "FAIL",
    "warn": "!",
    "pending": "...",
}


def is_tty(stream: TextIO | None = None) -> bool:
    """True when *stream* (default ``sys.stdout``) is an interactive terminal."""
    target = stream if stream is not None else sys.stdout
    isatty = getattr(target, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except (OSError, ValueError):
        return False


def use_color(stream: TextIO | None = None, environ: Mapping[str, str] | None = None) -> bool:
    """True when color/ANSI output is allowed for *stream*.

    Colored only when the stream is a TTY, ``NO_COLOR`` is unset (any value
    disables, per the NO_COLOR convention), and ``TERM`` is not ``dumb``.
    """
    env = environ if environ is not None else os.environ
    if not is_tty(stream):
        return False
    if "NO_COLOR" in env:
        return False
    if env.get("TERM") == "dumb":
        return False
    return True


def colorize(text: str, kind: str, *, stream: TextIO | None = None,
             environ: Mapping[str, str] | None = None) -> str:
    """Wrap *text* in the semantic color *kind* when color is allowed.

    *kind* is one of ``ok`` / ``warn`` / ``err`` / ``dim``. When color is
    not allowed (or *kind* is unknown), *text* is returned unchanged.
    """
    code = _COLORS.get(kind)
    if code is None or not use_color(stream=stream, environ=environ):
        return text
    return f"{code}{text}{_COLOR_RESET}"


def section(label: str, count: int | None = None, *,
            stream: TextIO | None = None,
            environ: Mapping[str, str] | None = None) -> str:
    """Section header in the existing ``zn`` style: ``--- label (n) ---``.

    Follows the long-standing ``approval list`` header so old output
    habits (and scripts grepping the dashes) keep working.
    """
    head = f"--- {label} ({count}) ---" if count is not None else f"--- {label} ---"
    return colorize(head, "dim", stream=stream, environ=environ)


def kv(key: str, value: Any) -> str:
    """One ``key=value`` pair; byte-stable in every mode."""
    return f"{key}={value}"


def table(rows: list[list[Any]], headers: list[str] | None = None) -> str:
    """Column-aligned plain table; no colors, safe for pipes and scripts.

    Each row must have the same number of cells. Column widths are the
    widest cell in that column; cells are left-aligned and separated by
    two spaces. *headers*, when given, render as the first row with a
    ``---`` underline row beneath.
    """
    data: list[list[str]] = [[str(cell) for cell in row] for row in rows]
    if headers is not None:
        header = [str(cell) for cell in headers]
        data = [header] + [["-" * len(cell) for cell in header]] + data
    widths = [0] * max((len(row) for row in data), default=0)
    for row in data:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    lines = []
    for row in data:
        padded = [cell.ljust(widths[index]) for index, cell in enumerate(row)]
        lines.append("  ".join(padded).rstrip())
    return "\n".join(lines)


# Status-word vocabulary: canonical word + semantic color per value.
# Unknown values pass through unchanged (fail-closed: never invent a word).
_STATUS_VOCAB: dict[Any, tuple[str, str]] = {
    True: ("ok", "ok"),
    False: ("failed", "err"),
    "yes": ("yes", "ok"),
    "no": ("no", "err"),
    "ok": ("ok", "ok"),
    "failed": ("failed", "err"),
    "success": ("success", "ok"),
    "pending": ("pending", "warn"),
    "allowed": ("allowed", "ok"),
    "allow_once": ("allowed", "ok"),
    "always_allow": ("always allow", "ok"),
    "approved_once": ("approved", "ok"),
    "denied": ("denied", "err"),
    "deny": ("denied", "err"),
    "rejected": ("rejected", "err"),
    "expired": ("expired", "dim"),
    "applied": ("applied", "ok"),
    "active": ("active", "ok"),
    "finalized": ("finalized", "dim"),
    "cancelled": ("cancelled", "dim"),
    "unreachable": ("unreachable", "err"),
    "unknown": ("unknown", "dim"),
}


def status_word(value: Any, *, stream: TextIO | None = None,
                environ: Mapping[str, str] | None = None) -> str:
    """Map a status value to its canonical word, colored when allowed.

    ``True`` -> ``ok``, ``False`` -> ``failed``; known status enums map to
    their vocabulary word (see ``_STATUS_VOCAB``); anything else is
    returned as ``str(value)`` unchanged. Non-color mode always returns
    the plain word.
    """
    entry = _STATUS_VOCAB.get(value)
    if entry is None:
        return str(value)
    word, kind = entry
    return colorize(word, kind, stream=stream, environ=environ)


def _detect_stdout_encoding() -> str:
    """Report the stdout encoding (T2-7 extension point).

    Today this is only consulted in tests. T2-7 will use it inside
    :func:`symbol` to select :data:`_ASCII_SYMBOLS` when the console
    encoding (e.g. Windows ``cp936``) cannot render the Unicode glyphs.
    """
    encoding = getattr(sys.stdout, "encoding", None)
    return str(encoding or "utf-8")


def symbol(name: str, *, stream: TextIO | None = None,
           environ: Mapping[str, str] | None = None) -> str:
    """Glyph for *name* (``ok`` / ``fail`` / ``warn`` / ``pending``).

    TTY-only affordance: returns the Unicode glyph when color is allowed,
    the empty string otherwise -- so non-TTY output is never polluted with
    symbols scripts cannot parse. Unknown names return "".
    """
    if not use_color(stream=stream, environ=environ):
        return ""
    return _UNICODE_SYMBOLS.get(name, "")
