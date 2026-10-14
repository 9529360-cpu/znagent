from __future__ import annotations

"""Privacy-safe error text for process and user-facing control-plane boundaries.

Internal code may keep rich exception objects for diagnosis, health accounting,
and recovery decisions. Text that crosses a Resident RPC/process boundary is a
different trust surface: it must be bounded and must not echo common credential
forms back to the Desktop, channels, or other clients.
"""

import re
from typing import Any


_MAX_PUBLIC_ERROR_TEXT = 1_000

_SECRET_ASSIGNMENT = re.compile(
    r"""(?ix)
    \b(
        api[_ -]?key
        |access[_ -]?token
        |refresh[_ -]?token
        |id[_ -]?token
        |auth[_ -]?token
        |token
        |client[_ -]?secret
        |password
        |passwd
        |secret
        |authorization
    )\b
    \s*[:=]\s*
    (?:(?:bearer|basic)\s+)?
    (?:"[^"]*"|'[^']*'|[^\s,;]+)
    """
)
_AUTHORIZATION_VALUE = re.compile(
    r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"
)
_URL_USERINFO = re.compile(
    r"(?i)(https?://)([^\s/:@]+):([^\s/@]+)@"
)
_QUERY_SECRET = re.compile(
    r"""(?ix)
    ([?&](
        api[_-]?key
        |access[_-]?token
        |refresh[_-]?token
        |id[_-]?token
        |auth[_-]?token
        |token
        |client[_-]?secret
        |password
        |secret
        |authorization
    )=)
    [^&#\s]+
    """
)
_SECRET_TOKEN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{12,}|"
    r"eyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})\b"
)
# Unambiguous vendor token prefixes. These shapes are specific enough that a
# match is treated as a credential value, not ordinary text.
_KNOWN_TOKEN_PREFIX = re.compile(
    r"(?:\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"
    r"|\bgithub_pat_[A-Za-z0-9_]{20,}"
    r"|\bxox[baprs]-[A-Za-z0-9-]{10,}"
    r"|\bAIza[0-9A-Za-z_-]{35}"
    r"|\bAKIA[0-9A-Z]{16})\b"
)
_CREDENTIAL_PATTERNS = (
    _SECRET_ASSIGNMENT,
    _AUTHORIZATION_VALUE,
    _URL_USERINFO,
    _QUERY_SECRET,
    _SECRET_TOKEN,
    _KNOWN_TOKEN_PREFIX,
)


def _scrub_credential_values(text: str) -> str:
    """Apply every credential redaction substitution, without collapsing or truncating."""

    text = _URL_USERINFO.sub(r"\1<redacted-userinfo>@", text)
    text = _QUERY_SECRET.sub(lambda match: f"{match.group(1)}<redacted>", text)
    text = _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}=<redacted>",
        text,
    )
    text = _AUTHORIZATION_VALUE.sub("<redacted-authorization>", text)
    text = _SECRET_TOKEN.sub("<redacted>", text)
    text = _KNOWN_TOKEN_PREFIX.sub("<redacted>", text)
    return text


def contains_credential_value(value: Any) -> bool:
    """Return True when *value* carries a credential-shaped string.

    Detection and redaction share the same patterns, so a value this function
    flags is exactly a value :func:`public_error_text` / :func:`scrub_credential_values`
    would redact. Detection is marker-based (assignment, Bearer, URL userinfo,
    query secret, known token shape): a bare high-entropy string with no marker
    is not detected.
    """

    text = str(value or "")
    if not text.strip():
        return False
    return any(pattern.search(text) for pattern in _CREDENTIAL_PATTERNS)


def scrub_credential_values(value: Any) -> str:
    """Redact credential-shaped substrings, preserving the rest verbatim.

    Unlike :func:`public_error_text` this does not collapse whitespace or
    truncate, so it is safe for log lines that must keep their structure.
    """

    return _scrub_credential_values(str(value or ""))


def public_error_text(value: Any, *, limit: int = _MAX_PUBLIC_ERROR_TEXT) -> str:
    """Return one bounded line with common credential forms redacted."""

    text = " ".join(str(value or "").strip().split())
    text = _scrub_credential_values(text)
    return text[: max(0, int(limit))]


def public_exception_text(
    error: BaseException,
    *,
    limit: int = _MAX_PUBLIC_ERROR_TEXT,
) -> str:
    """Preserve a useful exception class while preventing raw secret echo."""

    exception_type = type(error).__name__[:128] or "Error"
    message_budget = max(0, int(limit) - len(exception_type) - 2)
    message = public_error_text(error, limit=message_budget)
    return f"{exception_type}: {message}" if message else exception_type
