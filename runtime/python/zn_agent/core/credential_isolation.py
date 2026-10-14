from __future__ import annotations

"""Credential isolation for ZN-owned durable writes.

Pattern source: Muse pattern M15 ("least knowledge + credential isolation").
This is an original implementation of the mechanism, not a copy of Muse code:
raw credential values must never enter ZN memory, ZN config files, or logs.
Durable state carries only opaque references; the value itself lives only in
the caller's memory or the OS secure store
(see :mod:`zn_agent.core.credentials`).

Enforced rules in this module:

- Memory writes (``KernelStore.put_fact``) and ZN config file writes
  (``save_zn_config``) REJECT credential-shaped values with
  :class:`CredentialValueDetected` (fail closed: nothing is persisted, and the
  exception message never contains the value).
- Log output SCRUBS credential-shaped substrings instead of rejecting them,
  because logging must never crash the app. See
  :class:`CredentialRedactingFilter` and :func:`redact_for_log`.
- A reference (``credential:<kind>[:<id>]`` or ``provider:<name>``) is opaque:
  it carries no part of the value and cannot be reversed into it. ZN provides
  no ref-to-value resolver; resolution happens only in the caller's memory or
  the OS secure store at the moment of use.

Explicit limits (this is a guardrail, not complete credential infra):

- Detection is marker-based and reuses the patterns in
  :mod:`zn_agent.core.error_safety` (assignment, Bearer, URL userinfo, query
  secret, known token shapes). A bare high-entropy string with no marker, or
  a password stored without any ``password=``-style marker, is NOT detected.
- Only the fact-memory write path and the ZN config file write path are
  gated. Other durable writes (event payloads, experience excerpts, Work
  ledger entries) are not gated by this module yet; callers that persist
  user-supplied text there must call :func:`check_no_credential_value`
  themselves.
- Arbitrary user file content (e.g. a user asking ZN to write their own
  ``.env`` file) is the user's explicit action, not ZN persistence of a
  credential, and is deliberately NOT gated by this module.
"""

import logging
import re
import secrets
from collections.abc import Mapping
from typing import Any

from .error_safety import contains_credential_value as _contains_credential_shape
from .error_safety import scrub_credential_values

__all__ = [
    "CredentialValueDetected",
    "CredentialRedactingFilter",
    "check_no_credential_value",
    "contains_credential_value",
    "is_credential_reference",
    "mint_credential_reference",
    "redact_for_log",
]


class CredentialValueDetected(ValueError):
    """A credential-shaped value was refused at a durable-write boundary.

    The message deliberately never contains the value, the key, or any part
    of either: the exception itself may be logged.
    """


_REFERENCE_RE = re.compile(
    r"^(?:credential:[a-z0-9][a-z0-9._-]{0,31}(?::[A-Za-z0-9._-]{1,64})?|provider:[a-z0-9][a-z0-9._-]{0,63})$"
)
_KIND_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
# A mapping key whose value is a reference by position, not a credential value.
_REFERENCE_KEYS = frozenset(
    {"credential_ref", "credential_reference", "credentialref", "reference"}
)


def is_credential_reference(value: Any) -> bool:
    """Return True when *value* is an opaque credential reference, not a value."""

    if not isinstance(value, str):
        return False
    return _REFERENCE_RE.fullmatch(value.strip()) is not None


def mint_credential_reference(kind: str) -> str:
    """Mint a fresh opaque reference for a credential of the given *kind*.

    The reference is random (``secrets.token_hex``) and derived from nothing
    about the value, so it cannot be reversed into the value. Storing the
    value under the reference is the caller's job, via the OS secure store
    (``credentials.KeyringCredentialStore``); this module never sees the value.
    """

    normalized = str(kind or "").strip().lower()
    if not _KIND_RE.fullmatch(normalized):
        raise ValueError("credential reference kind must be [a-z0-9._-] (max 32 chars)")
    return f"credential:{normalized}:{secrets.token_hex(8)}"


def _scan(value: Any, *, key: str = "") -> bool:
    """Recursively detect a credential-shaped string, exempting references."""

    if isinstance(value, str):
        if is_credential_reference(value):
            return False
        if key.strip().lower() in _REFERENCE_KEYS:
            return False
        return _contains_credential_shape(value)
    if isinstance(value, Mapping):
        # Mapping keys are names, not values: only values are scanned.
        return any(_scan(item, key=str(name)) for name, item in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_scan(item, key=key) for item in value)
    return False


def contains_credential_value(value: Any, *, key: str = "") -> bool:
    """Return True when *value* (or anything nested in it) is credential-shaped.

    Opaque references and values stored under a ``credential_ref``-style key
    are not credential values and pass through.
    """

    return _scan(value, key=key)


def check_no_credential_value(value: Any, *, where: str) -> None:
    """Raise :class:`CredentialValueDetected` if *value* is credential-shaped.

    *where* names the write boundary (e.g. ``"memory:fact"``,
    ``"config:file"``). It is the only detail in the exception message, so
    the exception is safe to log.
    """

    if _scan(value):
        raise CredentialValueDetected(
            f"refusing to persist credential-shaped value at {where}"
        )


def redact_for_log(value: Any) -> str:
    """Redact credential-shaped substrings for log/error output (no truncation)."""

    return scrub_credential_values(value)


class CredentialRedactingFilter(logging.Filter):
    """A logging filter that scrubs credential-shaped text before output.

    The filter rewrites the record's message/args in place, so every handler
    attached downstream sees only the scrubbed text. It never raises: if
    scrubbing itself fails, the record is left untouched rather than breaking
    logging.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if record.args:
                try:
                    rendered = record.getMessage()
                except Exception:
                    return True
                record.msg = scrub_credential_values(rendered)
                record.args = ()
            elif isinstance(record.msg, str):
                record.msg = scrub_credential_values(record.msg)
        except Exception:
            return True
        return True
