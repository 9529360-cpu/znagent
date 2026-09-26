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


def public_error_text(value: Any, *, limit: int = _MAX_PUBLIC_ERROR_TEXT) -> str:
    """Return one bounded line with common credential forms redacted."""

    text = " ".join(str(value or "").strip().split())
    text = _URL_USERINFO.sub(r"\1<redacted-userinfo>@", text)
    text = _QUERY_SECRET.sub(lambda match: f"{match.group(1)}<redacted>", text)
    text = _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}=<redacted>",
        text,
    )
    text = _AUTHORIZATION_VALUE.sub("<redacted-authorization>", text)
    text = _SECRET_TOKEN.sub("<redacted>", text)
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
