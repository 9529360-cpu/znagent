"""Terminal presentation primitives for the ``zn`` CLI (T2-1, TERM-2 foundation).

Single formatting home for terminal output in ``zn_cli.py``: semantic
colors, symbols, ``key=value`` pairs, aligned tables, section headers, and
a status-word vocabulary.

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

Status-word vocabulary (T2-7; the rules live in :data:`_STATUS_VOCAB`):

- ``ok`` family (green): ``allowed``, ``allow_once`` (shown "allowed"),
  ``always_allow`` (shown "always allow"), ``approved_once`` (shown
  "approved"), ``applied``, ``active``, ``success``, ``yes``, ``True``
  (shown "ok").
- ``warn`` family (yellow): ``pending`` -- needs a human decision or
  attention.
- ``err`` family (red): ``denied``, ``deny`` (shown "denied"),
  ``rejected``, ``failed``, ``False`` (shown "failed"), ``unreachable``,
  ``no``.
- ``dim`` family (gray): ``expired``, ``finalized``, ``cancelled``,
  ``unknown`` -- terminal or informational states that stay quiet.
- Unknown values pass through as ``str(value)`` unchanged; the
  vocabulary never invents a word.

Symbols (T2-7): the whole CLI uses four glyphs, always selected through
:func:`symbol` so the rules below apply everywhere. Callers never embed
a glyph literal.

- success ``✓`` (``symbol("ok")``), failure ``✗`` (``symbol("fail")``),
  warning ``!`` (``symbol("warn")``), in-progress ``…``
  (``symbol("pending")``).
- :func:`status_symbol` maps a status value to its glyph through the
  color family above: ok-family -> ``✓``, err-family -> ``✗``,
  warn-family -> ``!``. Dim-family values and unknown values take no
  glyph.
- A *pending* status value maps to ``!`` (it waits on a human); the
  ``…`` glyph is reserved for in-progress spinners such as the
  ``zn work submit`` watcher.
- Symbols are a TTY-only affordance: on non-color streams ``symbol()``
  returns ``""`` so piped/script output never changes.
- Windows console encoding: every glyph lives in the BMP. When the
  target stream's encoding cannot render a glyph (Windows ``cp936``
  cannot encode ``✓``/``✗``), the whole table degrades to ASCII --
  ``OK`` / ``FAIL`` / ``!`` / ``...`` -- detected from the encoding of
  the stream the glyph is written to (``sys.stdout.encoding`` when the
  caller passes no stream). Degradation is all-or-nothing so a line
  never mixes ``✓`` with ``FAIL``; an unrecognised codec name is treated
  as cannot-render (fail-safe to ASCII).
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
    "status_symbol",
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

# T2-7: ASCII fallback for consoles whose encoding cannot render the BMP
# glyphs above (e.g. Windows cp936). Selected by ``symbol()`` when the
# target stream's encoding fails to encode any Unicode glyph.
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
    """Report the stdout encoding.

    Kept as the explicit ``sys.stdout.encoding`` probe (per the T2-7
    spec); :func:`symbol` consults the encoding of the actual target
    stream, which is ``sys.stdout`` unless the caller passes a stream.
    """
    encoding = getattr(sys.stdout, "encoding", None)
    return str(encoding or "utf-8")


def _stream_encoding(stream: TextIO | None = None) -> str:
    """Encoding of the stream a glyph would be written to.

    ``sys.stdout.encoding`` when *stream* is None; otherwise the passed
    stream's ``encoding`` attribute. Falls back to ``"utf-8"`` when the
    stream reports nothing (e.g. a test stand-in without an encoding).
    """
    if stream is None:
        return _detect_stdout_encoding()
    encoding = getattr(stream, "encoding", None)
    return str(encoding or "utf-8")


def _symbol_table(stream: TextIO | None = None) -> dict[str, str]:
    """Pick the glyph table for *stream* (T2-7).

    Unicode when the stream's encoding renders every glyph; the ASCII
    table otherwise (e.g. Windows ``cp936`` cannot encode ``✓``/``✗``).
    All-or-nothing on purpose: a mixed ``✓``/``FAIL`` line is worse than
    a uniform ASCII line. An unrecognised codec name fails safe to ASCII.
    """
    encoding = _stream_encoding(stream)
    for glyph in _UNICODE_SYMBOLS.values():
        try:
            glyph.encode(encoding, errors="strict")
        except (UnicodeEncodeError, LookupError):
            return _ASCII_SYMBOLS
    return _UNICODE_SYMBOLS


def symbol(name: str, *, stream: TextIO | None = None,
           environ: Mapping[str, str] | None = None) -> str:
    """Glyph for *name* (``ok`` / ``fail`` / ``warn`` / ``pending``).

    TTY-only affordance: returns ``""`` when color is not allowed, so
    non-TTY output is never polluted with symbols scripts cannot parse.
    On color-allowed streams the table is encoding-aware (T2-7): consoles
    whose encoding cannot render the Unicode glyphs (e.g. Windows
    ``cp936``) get the ASCII table (``OK``/``FAIL``/``!``/``...``).
    Unknown names return "".
    """
    if not use_color(stream=stream, environ=environ):
        return ""
    return _symbol_table(stream).get(name, "")


# Status value -> symbol name, derived from the _STATUS_VOCAB color family:
# ok-family gets ✓, err-family ✗, warn-family !. Dim-family values
# (expired/finalized/cancelled/unknown) are quiet terminal states and take
# no glyph.
_SYMBOL_BY_FAMILY = {
    "ok": "ok",
    "warn": "warn",
    "err": "fail",
}


def status_symbol(value: Any, *, stream: TextIO | None = None,
                  environ: Mapping[str, str] | None = None) -> str:
    """Glyph for a status *value* (T2-7), or ``""`` when it takes none.

    Maps through the :data:`_STATUS_VOCAB` color family: ok-family ->
    ``✓``, err-family -> ``✗``, warn-family -> ``!``. Dim-family values
    (``expired``, ``finalized``, ``cancelled``, ``unknown``) and unknown
    values get no glyph. Non-color streams get ``""``, like
    :func:`symbol`.
    """
    entry = _STATUS_VOCAB.get(value)
    if entry is None:
        return ""
    name = _SYMBOL_BY_FAMILY.get(entry[1])
    if name is None:
        return ""
    return symbol(name, stream=stream, environ=environ)
