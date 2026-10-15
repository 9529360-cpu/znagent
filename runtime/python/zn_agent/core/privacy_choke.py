from __future__ import annotations

"""CM-3 privacy choke: single-point sanitization for capture-side writes.

Every memory / team-log capture path funnels through :func:`strip_tags`
(the "stripTags" single point) before anything is persisted:

- ``<private>...</private>`` blocks never reach storage. The tag is a
  user convention for "do not record this": the block (and an unclosed
  ``<private>`` tag through end of input) is replaced by a marker.
- Built-in secret patterns are scrubbed: the M15 patterns in
  :mod:`zn_agent.core.error_safety` (assignment, Bearer, URL userinfo,
  query secret, known token shapes) plus PEM blocks, which M15 does not
  cover.
- Callers may register extra patterns with
  :func:`register_custom_pattern` (e.g. project codenames, internal
  hostnames). Custom patterns run after the built-ins.
- A single string field longer than :data:`MAX_FIELD_CHARS` is replaced
  whole -- a pasted dump (key material, logs) must not land in memory
  as a "field". Nested containers are sanitized leaf by leaf.

Fail closed, on by default: there is no opt-in flag and no way to
disable the choke at a capture call site. :func:`strip_tags` itself
never raises: on any internal error it returns the safe marker
``_CHOKE_FAILED`` instead of the original text, so a bug in the
sanitizer can lose a write but can never leak the original.

Opaque credential references (``credential:<kind>[:<id>]`` /
``provider:<name>``, see :mod:`zn_agent.core.credential_isolation`) are
NOT values: they pass through verbatim. A reference carries no part of
the secret and cannot be reversed into it; scrubbing one would break
the M15 reference mechanism.

Egress (W-2 follow-up) reuses the same single point via
:func:`redact_for_egress`: every model-call boundary scrubs its
outbound text (question / context / multi-turn messages) with the same
patterns, ``<private>`` handling and custom patterns. The one
difference is the overlong-field rule: at egress it is disabled
(``max_field_chars=None``), because length is a *storage* rule -- a
pasted dump must not land in memory as a field -- while at egress a
long benign input (a tool result up to 200k chars, an unbounded kernel
context) must still reach the model. Pattern scrubbing is what
prevents leaks at egress; replacing a long legitimate request with a
marker would corrupt the call instead of protecting it.

Explicit limits (same honest boundary as M15): detection is
marker-based. A bare high-entropy string with no marker, or a password
stored without any ``password=``-style marker, is NOT detected. The
choke is a guardrail, not complete secret infra.
"""

import re
import threading
from collections.abc import Mapping
from typing import Any

# CM-3 reuses M15's detection patterns (single source of truth for what
# counts as credential-shaped) but NOT M15's replacements: M15's
# ``scrub_credential_values`` turns ``api_key=SECRET`` into
# ``api_key=<redacted>``, which the ``put_fact`` gate would flag AGAIN
# (the ``key=`` trigger survives). CM-3 replacements drop the ``=``/``:``
# after the key name (``api_key <redacted>``), so scrubbed output is
# storable -- redact-and-continue instead of reject. The gate itself
# (``check_no_credential_value``) is untouched; it stays the backstop
# for any path this choke does not cover.
from .error_safety import (
    _AUTHORIZATION_VALUE,
    _KNOWN_TOKEN_PREFIX,
    _QUERY_SECRET,
    _SECRET_ASSIGNMENT,
    _SECRET_TOKEN,
    _URL_USERINFO,
)

__all__ = [
    "MAX_FIELD_CHARS",
    "clear_custom_patterns",
    "redact_for_egress",
    "register_custom_pattern",
    "strip_tags",
    "stripTags",
]

#: A single string field longer than this is replaced whole (see module doc).
MAX_FIELD_CHARS = 32_768

#: Safe value returned when sanitization itself fails (fail closed).
_CHOKE_FAILED = "[redacted: privacy choke failed]"

#: Marker replacing a ``<private>`` block.
_PRIVATE_MARKER = "[private content removed]"

#: Marker replacing a PEM block.
_PEM_MARKER = "[redacted-private-key-block]"

#: Marker replacing one custom-pattern match.
_CUSTOM_MARKER = "[redacted-custom]"

# <private ...>...</private>, attributes tolerated, case-insensitive.
# (Matched by the depth scanner in _strip_private_blocks.)


# PEM blocks: private keys, certificates, and anything else armored.
# Fail closed: the whole block is replaced, not just the header line.
_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]+-----[\s\S]*?-----END [A-Z0-9 ]+-----"
)

# Opaque credential references pass through verbatim (see module doc).
_REFERENCE_RE = re.compile(
    r"(?:credential:[a-z0-9][a-z0-9._-]{0,31}(?::[A-Za-z0-9._-]{1,64})?"
    r"|provider:[a-z0-9][a-z0-9._-]{0,63})"
)

_custom_lock = threading.Lock()
_custom_patterns: list[tuple[re.Pattern[str], str]] = []


def register_custom_pattern(pattern: str, replacement: str = _CUSTOM_MARKER) -> None:
    """Register an extra redaction pattern (applied after the built-ins).

    ``pattern`` is compiled now, so a bad pattern fails loudly at
    configuration time -- never inside the choke. Callers that need a
    project-specific rule (codename, internal hostname) register it
    once at startup. Use :func:`clear_custom_patterns` in tests.
    """
    compiled = re.compile(pattern)
    with _custom_lock:
        _custom_patterns.append((compiled, str(replacement)))


def clear_custom_patterns() -> None:
    """Remove all registered custom patterns (tests / reconfiguration)."""
    with _custom_lock:
        _custom_patterns.clear()


def _custom_snapshot() -> list[tuple[re.Pattern[str], str]]:
    with _custom_lock:
        return list(_custom_patterns)


def _strip_private_blocks(text: str) -> str:
    """Remove ``<private>`` blocks; unclosed tag swallows the rest.

    A depth scanner (not a regex) so nested tags stay fail closed:
    everything inside the outermost ``<private>`` -- including text
    between a nested close and the outer close -- is dropped. A stray
    closing tag is dropped on its own.
    """
    open_re = re.compile(r"<private\b[^>]*>", re.IGNORECASE)
    close_re = re.compile(r"</private\s*>", re.IGNORECASE)
    out: list[str] = []
    depth = 0
    cursor = 0
    while cursor < len(text):
        open_match = open_re.search(text, cursor)
        close_match = close_re.search(text, cursor)
        if open_match is None and close_match is None:
            if depth == 0:
                out.append(text[cursor:])
            break
        if close_match is not None and (
            open_match is None or close_match.start() < open_match.start()
        ):
            if depth == 0:
                out.append(text[cursor:close_match.start()])
            else:
                depth -= 1
                if depth == 0:
                    out.append(_PRIVATE_MARKER)
            cursor = close_match.end()
        else:
            assert open_match is not None
            if depth == 0:
                out.append(text[cursor:open_match.start()])
            depth += 1
            cursor = open_match.end()
    if depth > 0:
        # Unclosed <private>: the rest was already dropped; close the marker.
        out.append(_PRIVATE_MARKER)
    return "".join(out)


def _scrub_credentials(text: str) -> str:
    """Apply M15's credential patterns with CM-3 (storable) replacements.

    Every replacement is verified by test to NOT match any detection
    pattern again, so scrubbed output passes the ``put_fact`` gate.
    """

    def _assignment(match: re.Match[str]) -> str:
        # Drop the ``=``/``:`` so the gate's assignment pattern cannot
        # re-trigger on the replacement.
        return f"{match.group(1)} <redacted>"

    def _query(match: re.Match[str]) -> str:
        # Group 1 ends with ``=`` (e.g. ``?api_key=``); drop it.
        return f"{match.group(1)[:-1]} <redacted>"

    text = _URL_USERINFO.sub(r"\1<redacted-userinfo>@", text)
    text = _QUERY_SECRET.sub(_query, text)
    text = _SECRET_ASSIGNMENT.sub(_assignment, text)
    text = _AUTHORIZATION_VALUE.sub("<redacted-authorization>", text)
    text = _SECRET_TOKEN.sub("<redacted>", text)
    text = _KNOWN_TOKEN_PREFIX.sub("<redacted>", text)
    return text


def _scrub_segment(segment: str, custom: list[tuple[re.Pattern[str], str]]) -> str:
    """Scrub one non-reference segment: PEM, M15 patterns, custom patterns."""
    segment = _PEM_BLOCK_RE.sub(_PEM_MARKER, segment)
    segment = _scrub_credentials(segment)
    for pattern, replacement in custom:
        try:
            segment = pattern.sub(replacement, segment)
        except Exception:
            # One bad custom pattern must not break the choke (or leak).
            continue
    return segment


def _sanitize_text(
    text: str,
    custom: list[tuple[re.Pattern[str], str]],
    *,
    max_field_chars: int | None = MAX_FIELD_CHARS,
) -> str:
    if max_field_chars is not None and len(text) > max_field_chars:
        # Whole-field replacement: never keep a prefix of an overlong dump.
        return f"[redacted: field exceeded {max_field_chars} chars ({len(text)} chars)]"
    text = _strip_private_blocks(text)
    # Scrub around opaque references; references pass through verbatim.
    parts: list[str] = []
    cursor = 0
    for match in _REFERENCE_RE.finditer(text):
        if match.start() > cursor:
            parts.append(_scrub_segment(text[cursor:match.start()], custom))
        parts.append(match.group(0))
        cursor = match.end()
    if cursor < len(text):
        parts.append(_scrub_segment(text[cursor:], custom))
    return "".join(parts)


def strip_tags(value: Any, *, max_field_chars: int | None = MAX_FIELD_CHARS) -> Any:
    """Sanitize *value* for capture-side persistence. Never raises.

    Strings are scrubbed; mappings / sequences are sanitized leaf by
    leaf (keys included); numbers, booleans and None pass through;
    anything else is stringified and scrubbed. On any internal error
    the safe marker ``_CHOKE_FAILED`` is returned instead of the
    original -- fail closed, never leak.

    ``max_field_chars=None`` disables the whole-field replacement for
    overlong strings (used by :func:`redact_for_egress`); pattern
    scrubbing still applies.
    """
    try:
        return _strip_tags(value, max_field_chars=max_field_chars)
    except Exception:
        return _CHOKE_FAILED


def redact_for_egress(value: Any) -> Any:
    """Sanitize *value* before it is sent to a model / server. Never raises.

    Same single point as :func:`strip_tags` (same patterns, same
    ``<private>`` handling, same fail-closed marker), except the
    overlong-field whole replacement is disabled: a long benign model
    input (tool result, kernel context) must reach the model intact,
    and length alone does not make content secret. Credential-shaped
    content is still scrubbed no matter how long the field is.
    """
    return strip_tags(value, max_field_chars=None)


def _strip_tags(value: Any, *, max_field_chars: int | None) -> Any:
    if isinstance(value, str):
        if max_field_chars is not None and len(value) > max_field_chars:
            return (
                f"[redacted: field exceeded {max_field_chars} chars "
                f"({len(value)} chars)]"
            )
        return _sanitize_text(value, _custom_snapshot(), max_field_chars=max_field_chars)
    if isinstance(value, (bytes, bytearray)):
        # Bytes may hold key material; decode lossily, then scrub as text.
        return _sanitize_text(
            bytes(value).decode("utf-8", errors="replace"),
            _custom_snapshot(),
            max_field_chars=max_field_chars,
        )
    if isinstance(value, Mapping):
        return {
            _strip_tags(key, max_field_chars=max_field_chars): _strip_tags(
                item, max_field_chars=max_field_chars
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_strip_tags(item, max_field_chars=max_field_chars) for item in value]
    if isinstance(value, tuple):
        return tuple(_strip_tags(item, max_field_chars=max_field_chars) for item in value)
    if isinstance(value, (set, frozenset)):
        cleaned = {_strip_tags(item, max_field_chars=max_field_chars) for item in value}
        return frozenset(cleaned) if isinstance(value, frozenset) else cleaned
    if value is None or isinstance(value, (bool, int, float)):
        return value
    # Unknown type: stringify and scrub rather than persist it raw.
    return _sanitize_text(str(value), _custom_snapshot(), max_field_chars=max_field_chars)


# Spec name for the single point (``stripTags``); the canonical Python
# name is :func:`strip_tags`. Both refer to the same function.
stripTags = strip_tags
