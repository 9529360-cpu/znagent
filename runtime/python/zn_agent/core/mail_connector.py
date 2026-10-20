from __future__ import annotations

"""Mail connector (R6): IMAP reading plus approval-gated SMTP sending.

Three read tools become ZN actions on the SAME Fabric/Body capability
path as every other connector (the R1/R2/R3/R5 shape — never a parallel
plugin path, never model-supplied configuration):

* ``mail.imap.list_mailbox`` — the newest N message headers of a mailbox.
* ``mail.imap.read_message`` — one full message: headers, plain-text
  body, and an attachment inventory (binary content is never returned).
* ``mail.imap.search`` — IMAP SEARCH over from/subject/text/date/unseen.

One write tool:

* ``mail.smtp.send_message`` — send one plain-text message via SMTP.
  The descriptor carries an ``approval:send`` tag, so the
  ActionExecutionRuntime opens an approval card before dispatch: a
  denied or undecided send never reaches the SMTP server. After the
  server accepts the message, a copy is appended to the configured Sent
  mailbox over IMAP (best effort, reported honestly), and
  :func:`register_mail_runtime` binds a canonical approval scope plus an
  independent verifier that re-searches the Sent mailbox for the
  message-id — the same shape as the workspace file actions.

Credentials: the account config carries only a ZN credential reference
(e.g. ``provider:mail``). The secret is resolved through the host's
:class:`~zn_agent.core.credentials.CredentialStore` at call time, held
only in locals, and never written to the repository. With no account
configured — or no secret behind the reference — every action raises an
explicit "not configured（未配置）" :class:`MailError` instead of
pretending to work. Real-account authorization is a deploy-time user
step; the shipped code path is proven with mock transports only.

Transport honesty: every stdlib IMAP/SMTP failure becomes a
:class:`MailError` whose message IS the reason. Message parsing is
stdlib ``email`` with per-message tolerance: a malformed message raises
MailError naming the UID, never a raw traceback; a message with no
decodable text keeps ``text_body=""`` rather than an invented summary.
"""

import hashlib
import imaplib
import json
import re
import smtplib
import socket
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from email import message_from_bytes, policy
from email.header import decode_header
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parsedate_to_datetime
from typing import Any, Callable, Mapping, Protocol

from .action_execution import (
    ActionExecutionRuntime,
    ActionObservation,
    ActionRequest,
    ActionVerification,
)
from .action_fabric import (
    ActionAvailability,
    ActionDescriptor,
    ActionFabricRegistry,
)
from .approval_cards import APPROVAL_KINDS
from .body import BodyAction, BodyActionResult, NativeBody
from .credentials import (
    CredentialStore,
    CredentialStoreUnavailable,
    normalize_credential_reference,
)
from .mcp_capability_adapter import mcp_write_replay_identity
from .models import utc_now

__all__ = [
    "APPROVAL_KIND",
    "LIST_ACTION_ID",
    "PROVIDER_ID",
    "READ_ACTION_ID",
    "SEARCH_ACTION_ID",
    "SEND_ACTION_ID",
    "ImapSession",
    "ImapTransport",
    "MailAccountConfig",
    "MailAttachment",
    "MailAttachmentHandle",
    "MailError",
    "MailHeader",
    "MailMessage",
    "SendResult",
    "SmtpTransport",
    "StdlibImapSession",
    "StdlibImapTransport",
    "StdlibSmtpTransport",
    "attach_mail_tools",
    "build_search_criteria",
    "list_mailbox",
    "parse_message_bytes",
    "read_message",
    "register_mail_runtime",
    "search_mail",
    "send_message",
]

PROVIDER_ID = "zn.mail"
#: Approval kind gating SMTP sending. Reuses the existing ``send`` kind
#: (approval_cards: "a sensitive action (send / publish / purchase /
#: delete / production_change)"): no new kind is needed because sending
#: mail is exactly what ``send`` covers.
APPROVAL_KIND = "send"
assert APPROVAL_KIND in APPROVAL_KINDS

LIST_ACTION_ID = "mail.imap.list_mailbox"
READ_ACTION_ID = "mail.imap.read_message"
SEARCH_ACTION_ID = "mail.imap.search"
SEND_ACTION_ID = "mail.smtp.send_message"

_SOURCE_LABEL = "ZN mail connector (IMAP / SMTP)"

_MAX_LIST_LIMIT = 100
_MAX_MESSAGE_BYTES = 5_000_000
_MAX_TEXT_CHARS = 200_000
_MAX_SUBJECT_CHARS = 500
_MAX_BODY_CHARS = 200_000
_MAX_ADDRESS_COUNT = 50
_MAX_HEADER_CHARS = 2_000

_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$"
)
_CRLF_RE = re.compile(r"[\r\n]")
_WS_RE = re.compile(r"\s+")
_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,253}[A-Za-z0-9])?$")


class MailError(Exception):
    """Explicit mail failure: never invent messages, never hide a reason."""


# ---------------------------------------------------------------------------
# Account configuration (credential reference only — never a secret)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MailAccountConfig:
    """One mail account, identified by hosts plus a credential reference.

    ``credential_ref`` is a ZN credential-store reference such as
    ``provider:mail`` (see :mod:`zn_agent.core.credentials`). The actual
    password is resolved from the host's CredentialStore at call time and
    is never stored on this object, in the repository, or in logs.
    """

    imap_host: str
    username: str
    smtp_host: str
    credential_ref: str
    imap_port: int = 993
    smtp_port: int = 587
    imap_ssl: bool = True
    smtp_starttls: bool = True
    sent_mailbox: str = "Sent"
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        for name in ("imap_host", "smtp_host"):
            host = str(getattr(self, name) or "").strip()
            if not host or not _HOST_RE.fullmatch(host):
                raise MailError(f"mail {name} must be a valid hostname, got {getattr(self, name)!r}")
            setattr(self, name, host)
        username = str(self.username or "").strip()
        if not username or _CRLF_RE.search(username):
            raise MailError("mail username must not be empty")
        self.username = username
        for name in ("imap_port", "smtp_port"):
            port = getattr(self, name)
            if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
                raise MailError(f"mail {name} must be an integer 1..65535, got {port!r}")
        mailbox = str(self.sent_mailbox or "").strip()
        if not mailbox or _CRLF_RE.search(mailbox):
            raise MailError("mail sent_mailbox must not be empty")
        self.sent_mailbox = mailbox
        timeout = float(self.timeout_seconds)
        if not 1.0 <= timeout <= 120.0:
            raise MailError("mail timeout_seconds must be between 1 and 120")
        self.timeout_seconds = timeout
        self.credential_ref = normalize_credential_reference(self.credential_ref)


# ---------------------------------------------------------------------------
# Message shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MailHeader:
    """One message's headers, as listed by IMAP."""

    uid: str
    mailbox: str
    from_addr: str
    to_addrs: tuple[str, ...]
    subject: str
    date: datetime | None
    flags: tuple[str, ...]
    size: int


@dataclass(frozen=True, slots=True)
class MailAttachment:
    """One attachment's inventory entry: metadata only, never content."""

    filename: str
    content_type: str
    size: int


@dataclass(slots=True)
class MailMessage:
    """One fully read message: headers plus plain-text body."""

    header: MailHeader
    text_body: str
    attachments: tuple[MailAttachment, ...] = ()
    body_truncated: bool = False


@dataclass(frozen=True, slots=True)
class SendResult:
    """The honest receipt of one SMTP send."""

    message_id: str
    from_addr: str
    to_addrs: tuple[str, ...]
    smtp_response: str
    accepted: bool
    archived_in_sent: bool
    archive_note: str = ""


# ---------------------------------------------------------------------------
# Transport protocols (stdlib implementations below; fakes in tests)
# ---------------------------------------------------------------------------


class ImapSession(Protocol):
    """One authenticated IMAP session; closed by the caller."""

    def list_mailboxes(self) -> list[str]: ...
    def select(self, mailbox: str) -> int: ...
    def search(self, criteria: str) -> list[str]: ...
    def fetch_header(self, uid: str) -> MailHeader: ...
    def fetch_message(self, uid: str) -> MailMessage: ...
    def append(self, mailbox: str, raw: bytes) -> None: ...
    def close(self) -> None: ...


class ImapTransport(Protocol):
    def open_session(
        self,
        *,
        host: str,
        port: int,
        use_ssl: bool,
        username: str,
        password: str,
        timeout_seconds: float,
    ) -> ImapSession: ...


class SmtpTransport(Protocol):
    def send(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        use_starttls: bool,
        timeout_seconds: float,
        from_addr: str,
        to_addrs: tuple[str, ...],
        raw_message: bytes,
    ) -> str:
        """Send one message; return the server's acceptance line.

        Raises MailError when the server refuses or the transport fails.
        """


# ---------------------------------------------------------------------------
# stdlib transports
# ---------------------------------------------------------------------------


def _decode_header_value(raw: str | None) -> str:
    if not raw:
        return ""
    parts: list[str] = []
    for chunk, charset in decode_header(raw):
        if isinstance(chunk, bytes):
            try:
                parts.append(chunk.decode(charset or "utf-8", errors="replace"))
            except LookupError:
                parts.append(chunk.decode("utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return _WS_RE.sub(" ", "".join(parts)).strip()[:_MAX_HEADER_CHARS]


def _address_list(message: Any, field: str) -> tuple[str, ...]:
    values = message.get_all(field, [])
    addrs: list[str] = []
    for value in values:
        text = _decode_header_value(str(value))
        for part in text.split(","):
            addr = part.strip()
            if "<" in addr and ">" in addr:
                addr = addr.rsplit("<", 1)[1].split(">", 1)[0].strip()
            if addr and _EMAIL_RE.fullmatch(addr):
                addrs.append(addr)
    return tuple(addrs)


def parse_message_bytes(raw: bytes, *, uid: str, mailbox: str) -> MailMessage:
    """Parse one raw RFC 822 message into :class:`MailMessage`.

    Per-message tolerance: a message with no decodable text keeps
    ``text_body=""`` instead of an invented summary; anything that is not
    parseable at all raises MailError naming the UID.
    """
    if len(raw) > _MAX_MESSAGE_BYTES:
        raise MailError(
            f"message {uid} in {mailbox!r} exceeds the "
            f"{_MAX_MESSAGE_BYTES}-byte bound; refusing to parse"
        )
    try:
        message = message_from_bytes(raw, policy=policy.default)
    except Exception as exc:
        raise MailError(
            f"message {uid} in {mailbox!r} is not parseable: "
            f"{type(exc).__name__}"
        ) from exc

    from_addrs = _address_list(message, "From")
    from_addr = from_addrs[0] if from_addrs else ""
    subject = _decode_header_value(str(message.get("Subject", "")))
    date_value: datetime | None = None
    date_raw = message.get("Date")
    if date_raw:
        try:
            parsed = parsedate_to_datetime(str(date_raw))
        except (TypeError, ValueError):
            parsed = None
        if parsed is not None:
            date_value = parsed
            if date_value.tzinfo is None:
                date_value = date_value.replace(tzinfo=timezone.utc)

    text = ""
    truncated = False
    body = message.get_body(("plain",))
    if body is None:
        for part in message.walk():
            if part.get_content_type() == "text/plain" and not part.is_multipart():
                body = part
                break
    if body is not None:
        try:
            text = body.get_content()
        except Exception:
            text = ""
    if not isinstance(text, str):
        text = ""
    if len(text) > _MAX_TEXT_CHARS:
        text = text[:_MAX_TEXT_CHARS]
        truncated = True

    attachments: list[MailAttachment] = []
    try:
        for part in message.iter_attachments():
            payload = part.get_content()
            size = len(payload) if isinstance(payload, (bytes, str)) else 0
            attachments.append(
                MailAttachment(
                    filename=str(part.get_filename() or "unnamed"),
                    content_type=str(part.get_content_type()),
                    size=size,
                )
            )
    except Exception:
        attachments = []

    header = MailHeader(
        uid=str(uid),
        mailbox=mailbox,
        from_addr=from_addr,
        to_addrs=_address_list(message, "To"),
        subject=subject,
        date=date_value,
        flags=(),
        size=len(raw),
    )
    return MailMessage(
        header=header, text_body=text, attachments=tuple(attachments),
        body_truncated=truncated,
    )


class StdlibImapSession:
    """An :class:`ImapSession` over stdlib ``imaplib``."""

    def __init__(self, client: imaplib.IMAP4, mailbox: str = "") -> None:
        self._client = client
        self._mailbox = mailbox

    def _check(self, status: str, data: Any, what: str) -> Any:
        if status != "OK":
            detail = ""
            try:
                detail = f": {data[0].decode('utf-8', 'replace')}" if data else ""
            except Exception:
                detail = ""
            raise MailError(f"IMAP {what} failed{detail}")
        return data

    def list_mailboxes(self) -> list[str]:
        try:
            status, data = self._client.list()
        except (imaplib.IMAP4.error, OSError) as exc:
            raise MailError(f"IMAP LIST failed: {type(exc).__name__}: {exc}") from exc
        self._check(status, data, "LIST")
        names: list[str] = []
        for item in data or []:
            try:
                text = item.decode("utf-8", "replace")
            except AttributeError:
                continue
            match = re.search(r'"([^"]+)"\s*$', text)
            if match:
                names.append(match.group(1))
        return names

    def select(self, mailbox: str) -> int:
        try:
            status, data = self._client.select(mailbox, readonly=True)
        except (imaplib.IMAP4.error, OSError) as exc:
            raise MailError(
                f"IMAP SELECT {mailbox!r} failed: {type(exc).__name__}: {exc}"
            ) from exc
        self._check(status, data, f"SELECT {mailbox!r}")
        self._mailbox = mailbox
        try:
            return int(data[0])
        except (TypeError, ValueError, IndexError):
            return 0

    def search(self, criteria: str) -> list[str]:
        try:
            status, data = self._client.uid("SEARCH", None, criteria)
        except (imaplib.IMAP4.error, OSError) as exc:
            raise MailError(f"IMAP SEARCH failed: {type(exc).__name__}: {exc}") from exc
        self._check(status, data, "SEARCH")
        if not data or not data[0]:
            return []
        return [part.decode("ascii") for part in data[0].split()]

    def _fetch_parts(self, uid: str, parts: str) -> list[Any]:
        try:
            status, data = self._client.uid("FETCH", uid, parts)
        except (imaplib.IMAP4.error, OSError) as exc:
            raise MailError(
                f"IMAP FETCH {uid} failed: {type(exc).__name__}: {exc}"
            ) from exc
        return self._check(status, data, f"FETCH {uid}")

    @staticmethod
    def _flags_from(data: list[Any]) -> tuple[str, ...]:
        for item in data:
            if isinstance(item, tuple) and len(item) == 2:
                text = item[0].decode("utf-8", "replace") if isinstance(item[0], bytes) else str(item[0])
                match = re.search(r"FLAGS \(([^)]*)\)", text)
                if match:
                    return tuple(sorted(match.group(1).split()))
        return ()

    def fetch_header(self, uid: str) -> MailHeader:
        data = self._fetch_parts(uid, "(BODY.PEEK[HEADER] FLAGS RFC822.SIZE)")
        raw_header = b""
        size = 0
        for item in data:
            if isinstance(item, tuple) and len(item) == 2:
                spec = (
                    item[0].decode("utf-8", "replace")
                    if isinstance(item[0], bytes)
                    else str(item[0])
                )
                size_match = re.search(r"RFC822\.SIZE (\d+)", spec)
                if size_match:
                    size = int(size_match.group(1))
                if isinstance(item[1], bytes) and "BODY[HEADER]" in spec.upper():
                    raw_header = item[1]
        # Parse the header block as a bodyless message; headers parse
        # standalone, so no synthetic prefix is needed.
        try:
            message = message_from_bytes(raw_header, policy=policy.default)
        except Exception as exc:
            raise MailError(
                f"message {uid} in {self._mailbox!r} has unparseable headers: "
                f"{type(exc).__name__}"
            ) from exc
        return MailHeader(
            uid=str(uid),
            mailbox=self._mailbox,
            from_addr=(_address_list(message, "From") + ("",))[0],
            to_addrs=_address_list(message, "To"),
            subject=_decode_header_value(str(message.get("Subject", ""))),
            date=_parse_date_header(message.get("Date")),
            flags=self._flags_from(data),
            size=size,
        )

    def fetch_message(self, uid: str) -> MailMessage:
        data = self._fetch_parts(uid, "(BODY.PEEK[] FLAGS)")
        raw = b""
        for item in data:
            if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], bytes):
                raw = item[1]
                break
        if not raw:
            raise MailError(f"message {uid} in {self._mailbox!r} came back empty")
        message = parse_message_bytes(raw, uid=uid, mailbox=self._mailbox)
        flags = self._flags_from(data)
        header = message.header
        message.header = MailHeader(
            uid=header.uid,
            mailbox=header.mailbox,
            from_addr=header.from_addr,
            to_addrs=header.to_addrs,
            subject=header.subject,
            date=header.date,
            flags=flags,
            size=len(raw),
        )
        return message

    def append(self, mailbox: str, raw: bytes) -> None:
        try:
            status, data = self._client.append(mailbox, None, None, raw)
        except (imaplib.IMAP4.error, OSError) as exc:
            raise MailError(
                f"IMAP APPEND to {mailbox!r} failed: {type(exc).__name__}: {exc}"
            ) from exc
        self._check(status, data, f"APPEND to {mailbox!r}")

    def close(self) -> None:
        with suppress(Exception):
            self._client.close()
        with suppress(Exception):
            self._client.logout()


def _parse_date_header(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(str(value))
    except (TypeError, ValueError):
        return None
    if parsed is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class StdlibImapTransport:
    """Default :class:`ImapTransport` over stdlib ``imaplib``."""

    def open_session(
        self,
        *,
        host: str,
        port: int,
        use_ssl: bool,
        username: str,
        password: str,
        timeout_seconds: float,
    ) -> ImapSession:
        try:
            if use_ssl:
                client: imaplib.IMAP4 = imaplib.IMAP4_SSL(
                    host, port, timeout=timeout_seconds
                )
            else:
                client = imaplib.IMAP4(host, port, timeout=timeout_seconds)
        except (imaplib.IMAP4.error, OSError, socket.error) as exc:
            raise MailError(
                f"IMAP connect to {host}:{port} failed: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        try:
            client.login(username, password)
        except (imaplib.IMAP4.error, OSError) as exc:
            with suppress(Exception):
                client.logout()
            raise MailError(
                f"IMAP login as {username!r} failed: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        return StdlibImapSession(client)


class StdlibSmtpTransport:
    """Default :class:`SmtpTransport` over stdlib ``smtplib``."""

    def send(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        use_starttls: bool,
        timeout_seconds: float,
        from_addr: str,
        to_addrs: tuple[str, ...],
        raw_message: bytes,
    ) -> str:
        try:
            smtp = smtplib.SMTP(host, port, timeout=timeout_seconds)
        except (smtplib.SMTPException, OSError) as exc:
            raise MailError(
                f"SMTP connect to {host}:{port} failed: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        try:
            smtp.ehlo()
            if use_starttls:
                try:
                    smtp.starttls()
                except smtplib.SMTPException as exc:
                    raise MailError(f"SMTP STARTTLS failed: {exc}") from exc
                smtp.ehlo()
            try:
                smtp.login(username, password)
            except smtplib.SMTPException as exc:
                raise MailError(
                    f"SMTP login as {username!r} failed: {exc}"
                ) from exc
            try:
                refused = smtp.sendmail(from_addr, list(to_addrs), raw_message)
            except smtplib.SMTPException as exc:
                raise MailError(f"SMTP send failed: {exc}") from exc
            if refused:
                names = ", ".join(sorted(refused))
                raise MailError(f"SMTP server refused recipients: {names}")
            code, response = smtp.noop()
            text = response.decode("utf-8", "replace") if isinstance(response, bytes) else str(response)
            return f"{code} {text}".strip()
        finally:
            with suppress(Exception):
                smtp.quit()


# ---------------------------------------------------------------------------
# SEARCH criteria
# ---------------------------------------------------------------------------


def _escape_search_text(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')


def build_search_criteria(
    *,
    from_addr: str | None = None,
    subject: str | None = None,
    text: str | None = None,
    since: str | None = None,
    unseen_only: bool = False,
) -> str:
    """Build an IMAP SEARCH criteria string from structured filters."""
    parts: list[str] = []
    if unseen_only:
        parts.append("UNSEEN")
    if from_addr:
        parts.append(f'FROM "{_escape_search_text(from_addr)}"')
    if subject:
        parts.append(f'SUBJECT "{_escape_search_text(subject)}"')
    if text:
        parts.append(f'TEXT "{_escape_search_text(text)}"')
    if since:
        try:
            day = date.fromisoformat(str(since).strip())
        except ValueError:
            raise MailError(
                f"'since' must be a YYYY-MM-DD date, got {since!r}"
            )
        parts.append(f"SINCE {day.strftime('%d-%b-%Y')}")
    return " ".join(parts) if parts else "ALL"


# ---------------------------------------------------------------------------
# Credential resolution (reference only; secret never persisted)
# ---------------------------------------------------------------------------


def _not_configured(reason: str) -> MailError:
    return MailError(f"mail account is not configured（未配置）: {reason}")


def _resolve_password(
    config: MailAccountConfig | None,
    credential_store: CredentialStore | None,
) -> str:
    if config is None:
        raise _not_configured(
            "no mail account was attached; the host must attach a "
            "MailAccountConfig (authorize once at deploy time)"
        )
    if credential_store is None:
        raise _not_configured(
            f"no credential store is available to resolve {config.credential_ref!r}"
        )
    try:
        secret = credential_store.get(config.credential_ref)
    except CredentialStoreUnavailable as exc:
        raise _not_configured(f"credential store unavailable: {exc}") from exc
    except Exception as exc:
        raise _not_configured(
            f"credential lookup failed: {type(exc).__name__}: {exc}"
        ) from exc
    if not secret:
        raise _not_configured(
            f"no secret behind credential reference {config.credential_ref!r}; "
            "authorize the mail account once at deploy time"
        )
    return secret


def _open_session(
    imap_transport: ImapTransport,
    config: MailAccountConfig,
    credential_store: CredentialStore | None,
) -> ImapSession:
    password = _resolve_password(config, credential_store)
    try:
        return imap_transport.open_session(
            host=config.imap_host,
            port=config.imap_port,
            use_ssl=config.imap_ssl,
            username=config.username,
            password=password,
            timeout_seconds=config.timeout_seconds,
        )
    except MailError:
        raise
    except Exception as exc:
        raise MailError(
            f"IMAP session failed: {type(exc).__name__}: {exc}"
        ) from exc


def _check_limit(limit: Any) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        raise MailError(f"'limit' must be an integer, got {limit!r}")
    if not 1 <= value <= _MAX_LIST_LIMIT:
        raise MailError(f"'limit' must be 1..{_MAX_LIST_LIMIT}, got {value}")
    return value


def _check_mailbox(mailbox: Any) -> str:
    name = str(mailbox or "").strip()
    if not name or _CRLF_RE.search(name):
        raise MailError("'mailbox' must be a non-empty mailbox name")
    return name


# ---------------------------------------------------------------------------
# Core operations (transport-injected; unit-tested with fakes)
# ---------------------------------------------------------------------------


def list_mailbox(
    imap_transport: ImapTransport,
    config: MailAccountConfig | None,
    credential_store: CredentialStore | None,
    *,
    mailbox: str = "INBOX",
    limit: int = 20,
    unseen_only: bool = False,
    since: str | None = None,
) -> list[MailHeader]:
    """Newest-first headers of one mailbox."""
    name = _check_mailbox(mailbox)
    count = _check_limit(limit)
    criteria = build_search_criteria(unseen_only=unseen_only, since=since)
    session = _open_session(imap_transport, config, credential_store)
    try:
        session.select(name)
        uids = session.search(criteria)
        headers = [session.fetch_header(uid) for uid in uids[-count:]]
        headers.reverse()
        return headers
    finally:
        session.close()


def read_message(
    imap_transport: ImapTransport,
    config: MailAccountConfig | None,
    credential_store: CredentialStore | None,
    *,
    mailbox: str = "INBOX",
    uid: str,
) -> MailMessage:
    """One full message by UID."""
    name = _check_mailbox(mailbox)
    uid_text = str(uid or "").strip()
    if not uid_text or _CRLF_RE.search(uid_text):
        raise MailError("'uid' must be a non-empty message UID")
    session = _open_session(imap_transport, config, credential_store)
    try:
        session.select(name)
        return session.fetch_message(uid_text)
    finally:
        session.close()


def search_mail(
    imap_transport: ImapTransport,
    config: MailAccountConfig | None,
    credential_store: CredentialStore | None,
    *,
    mailbox: str = "INBOX",
    from_addr: str | None = None,
    subject: str | None = None,
    text: str | None = None,
    since: str | None = None,
    unseen_only: bool = False,
    limit: int = 20,
) -> list[MailHeader]:
    """Structured search over one mailbox; newest first."""
    name = _check_mailbox(mailbox)
    count = _check_limit(limit)
    criteria = build_search_criteria(
        from_addr=from_addr,
        subject=subject,
        text=text,
        since=since,
        unseen_only=unseen_only,
    )
    session = _open_session(imap_transport, config, credential_store)
    try:
        session.select(name)
        uids = session.search(criteria)
        headers = [session.fetch_header(uid) for uid in uids[-count:]]
        headers.reverse()
        return headers
    finally:
        session.close()


def _check_address(value: Any, *, field_name: str) -> str:
    addr = str(value or "").strip()
    if _CRLF_RE.search(addr) or not _EMAIL_RE.fullmatch(addr):
        raise MailError(f"'{field_name}' must be a valid email address, got {value!r}")
    return addr


def _check_addresses(values: Any, *, field_name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    items = values if isinstance(values, (list, tuple)) else [values]
    return tuple(_check_address(item, field_name=field_name) for item in items)


def send_message(
    smtp_transport: SmtpTransport,
    config: MailAccountConfig | None,
    credential_store: CredentialStore | None,
    *,
    to: Any,
    cc: Any = None,
    bcc: Any = None,
    subject: str,
    body: str,
    from_addr: str | None = None,
    imap_transport: ImapTransport | None = None,
) -> SendResult:
    """Send one plain-text message; returns the server's receipt.

    Bcc recipients travel on the envelope only — never in the headers.
    When ``imap_transport`` is given, a copy is appended to the Sent
    mailbox; the outcome is reported honestly either way.
    """
    if config is None:
        raise _not_configured(
            "no mail account was attached; the host must attach a "
            "MailAccountConfig (authorize once at deploy time)"
        )
    to_addrs = _check_addresses(to, field_name="to")
    if not to_addrs:
        raise MailError("'to' must name at least one recipient")
    cc_addrs = _check_addresses(cc, field_name="cc")
    bcc_addrs = _check_addresses(bcc, field_name="bcc")
    all_recipients = to_addrs + cc_addrs + bcc_addrs
    if len(all_recipients) > _MAX_ADDRESS_COUNT:
        raise MailError(
            f"too many recipients: {len(all_recipients)} > {_MAX_ADDRESS_COUNT}"
        )
    sender = _check_address(from_addr or config.username, field_name="from")
    subject_text = str(subject or "").strip()
    if not subject_text:
        raise MailError("'subject' must not be empty")
    if _CRLF_RE.search(subject_text):
        raise MailError("'subject' must not contain line breaks")
    if len(subject_text) > _MAX_SUBJECT_CHARS:
        raise MailError(
            f"'subject' exceeds {_MAX_SUBJECT_CHARS} characters"
        )
    body_text = str(body or "")
    if len(body_text) > _MAX_BODY_CHARS:
        raise MailError(f"'body' exceeds {_MAX_BODY_CHARS} characters")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(to_addrs)
    if cc_addrs:
        message["Cc"] = ", ".join(cc_addrs)
    message["Subject"] = subject_text
    message_id = make_msgid(domain=config.imap_host)
    message["Message-ID"] = message_id
    message["Date"] = formatdate(localtime=True)
    message.set_content(body_text)

    password = _resolve_password(config, credential_store)
    try:
        response = smtp_transport.send(
            host=config.smtp_host,
            port=config.smtp_port,
            username=config.username,
            password=password,
            use_starttls=config.smtp_starttls,
            timeout_seconds=config.timeout_seconds,
            from_addr=sender,
            to_addrs=all_recipients,
            raw_message=message.as_bytes(),
        )
    except MailError:
        raise
    except Exception as exc:
        raise MailError(
            f"SMTP send failed: {type(exc).__name__}: {exc}"
        ) from exc
    accepted = str(response or "").strip().startswith("250")
    if not accepted:
        raise MailError(f"SMTP server did not accept the message: {response!r}")

    archived = False
    archive_note = ""
    if imap_transport is not None:
        try:
            session = _open_session(imap_transport, config, credential_store)
            try:
                session.append(config.sent_mailbox, message.as_bytes())
                archived = True
            finally:
                session.close()
        except MailError as exc:
            archive_note = f"message was accepted by SMTP but the Sent copy failed: {exc}"

    return SendResult(
        message_id=message_id,
        from_addr=sender,
        to_addrs=to_addrs,
        smtp_response=str(response).strip(),
        accepted=True,
        archived_in_sent=archived,
        archive_note=archive_note,
    )


# ---------------------------------------------------------------------------
# Fabric/Body attachment
# ---------------------------------------------------------------------------


def _body_kind(action_id: str, *, read: bool) -> str:
    digest = hashlib.sha256(action_id.encode("utf-8")).hexdigest()[:24]
    return f"zn_mail_read_{digest}" if read else f"zn_mail_write_{digest}"


def _header_to_dict(header: MailHeader) -> dict[str, Any]:
    return {
        "uid": header.uid,
        "mailbox": header.mailbox,
        "from": header.from_addr,
        "to": list(header.to_addrs),
        "subject": header.subject,
        "date": header.date.isoformat() if header.date else None,
        "flags": list(header.flags),
        "size": header.size,
    }


def _message_to_dict(message: MailMessage) -> dict[str, Any]:
    data = _header_to_dict(message.header)
    data["text_body"] = message.text_body
    data["body_truncated"] = message.body_truncated
    data["attachments"] = [
        {
            "filename": item.filename,
            "content_type": item.content_type,
            "size": item.size,
        }
        for item in message.attachments
    ]
    return data


def _mail_probe(config: MailAccountConfig | None):
    def probe(item) -> ActionAvailability:
        if config is None:
            return ActionAvailability(
                item.action_id,
                "unavailable",
                reason=(
                    "no mail account configured: attach with a "
                    "MailAccountConfig to enable these actions"
                ),
            )
        return ActionAvailability(
            item.action_id,
            "available",
            reason="mail account configured",
            evidence={
                "imap_host": config.imap_host,
                "smtp_host": config.smtp_host,
                "credential_ref": config.credential_ref,
            },
        )

    return probe


class MailAttachmentHandle:
    """Handle returned by :func:`attach_mail_tools`; call detach()."""

    def __init__(
        self,
        fabric: ActionFabricRegistry,
        body: NativeBody,
        kinds: list[tuple[str, bool]],
        action_ids: list[str],
    ) -> None:
        self._fabric = fabric
        self._body = body
        self._kinds = kinds
        self._action_ids = action_ids
        self._detached = False

    @property
    def action_ids(self) -> tuple[str, ...]:
        return tuple(self._action_ids)

    def detach(self) -> None:
        if self._detached:
            return
        self._detached = True
        for action_id in self._action_ids:
            self._fabric.unregister(action_id)
        for kind, was_read in self._kinds:
            if was_read:
                self._body.unregister_external_read_handler(kind)
            else:
                self._body.unregister_external_write_handler(kind)


def attach_mail_tools(
    fabric: ActionFabricRegistry,
    body: NativeBody,
    *,
    config: MailAccountConfig | None = None,
    imap_transport: ImapTransport | None = None,
    smtp_transport: SmtpTransport | None = None,
    credential_store: CredentialStore | None = None,
) -> MailAttachmentHandle:
    """Attach the mail toolset to the Fabric/Body, R1/R5 shape.

    ``config`` carries only a credential reference; the secret is
    resolved from ``credential_store`` at call time. With no account
    configured the actions stay registered but report "not configured"
    instead of pretending to work. Transports default to the stdlib
    IMAP/SMTP implementations; tests inject fakes.
    """
    imap_client: ImapTransport = imap_transport or StdlibImapTransport()
    smtp_client: SmtpTransport = smtp_transport or StdlibSmtpTransport()

    prepared: list[tuple[ActionDescriptor, bool, Callable]] = []

    def _result(
        action: BodyAction, started: str, payload: Mapping[str, Any]
    ) -> BodyActionResult:
        data = dict(payload)
        data["untrusted_external_evidence"] = True
        return BodyActionResult(
            action_id=action.action_id,
            kind=action.kind,
            success=True,
            output=json.dumps(payload, ensure_ascii=False, indent=2),
            data=data,
            event_id=action.event_id,
            started_at=started,
            completed_at=utc_now(),
        )

    # -- list mailbox -----------------------------------------------------
    def call_list(action: BodyAction, started: str) -> BodyActionResult:
        headers = list_mailbox(
            imap_client,
            config,
            credential_store,
            mailbox=str(action.args.get("mailbox") or "INBOX"),
            limit=action.args.get("limit", 20),
            unseen_only=bool(action.args.get("unseen_only", False)),
            since=action.args.get("since"),
        )
        return _result(
            action,
            started,
            {
                "provider_id": PROVIDER_ID,
                "tool": "list_mailbox",
                "source": _SOURCE_LABEL,
                "message_count": len(headers),
                "messages": [_header_to_dict(item) for item in headers],
            },
        )

    prepared.append(
        (
            ActionDescriptor(
                action_id=LIST_ACTION_ID,
                provider=PROVIDER_ID,
                description=(
                    "List the newest message headers of an IMAP mailbox. "
                    "Read-only: never modifies the mailbox."
                ),
                body_action_kind=_body_kind(LIST_ACTION_ID, read=True),
                input_schema={
                    "type": "object",
                    "properties": {
                        "mailbox": {
                            "type": "string",
                            "description": "Mailbox name; defaults to INBOX",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max headers to return (1..100)",
                        },
                        "unseen_only": {
                            "type": "boolean",
                            "description": "Only unread messages",
                        },
                        "since": {
                            "type": "string",
                            "description": "Only messages on/after YYYY-MM-DD",
                        },
                    },
                    "additionalProperties": False,
                },
                effect_class="read_only",
                required_authority=(),
                sensitivity="personal_mail",
                preconditions=("a configured mail account",),
                verification=("headers come from the IMAP server's response",),
                replay_semantics="read_only",
                tags=("mail", "imap", "read_only", "external"),
            ),
            True,
            call_list,
        )
    )

    # -- read message -----------------------------------------------------
    def call_read(action: BodyAction, started: str) -> BodyActionResult:
        message = read_message(
            imap_client,
            config,
            credential_store,
            mailbox=str(action.args.get("mailbox") or "INBOX"),
            uid=action.args.get("uid"),
        )
        return _result(
            action,
            started,
            {
                "provider_id": PROVIDER_ID,
                "tool": "read_message",
                "source": _SOURCE_LABEL,
                "message": _message_to_dict(message),
            },
        )

    prepared.append(
        (
            ActionDescriptor(
                action_id=READ_ACTION_ID,
                provider=PROVIDER_ID,
                description=(
                    "Read one full IMAP message by UID: headers, plain-text "
                    "body, and an attachment inventory. Read-only."
                ),
                body_action_kind=_body_kind(READ_ACTION_ID, read=True),
                input_schema={
                    "type": "object",
                    "required": ["uid"],
                    "properties": {
                        "mailbox": {
                            "type": "string",
                            "description": "Mailbox name; defaults to INBOX",
                        },
                        "uid": {
                            "type": "string",
                            "description": "IMAP UID of the message",
                        },
                    },
                    "additionalProperties": False,
                },
                effect_class="read_only",
                required_authority=(),
                sensitivity="personal_mail",
                preconditions=("a configured mail account",),
                verification=("the message bytes come from the IMAP server",),
                replay_semantics="read_only",
                tags=("mail", "imap", "read_only", "external"),
            ),
            True,
            call_read,
        )
    )

    # -- search -----------------------------------------------------------
    def call_search(action: BodyAction, started: str) -> BodyActionResult:
        headers = search_mail(
            imap_client,
            config,
            credential_store,
            mailbox=str(action.args.get("mailbox") or "INBOX"),
            from_addr=action.args.get("from"),
            subject=action.args.get("subject"),
            text=action.args.get("text"),
            since=action.args.get("since"),
            unseen_only=bool(action.args.get("unseen_only", False)),
            limit=action.args.get("limit", 20),
        )
        return _result(
            action,
            started,
            {
                "provider_id": PROVIDER_ID,
                "tool": "search_mail",
                "source": _SOURCE_LABEL,
                "message_count": len(headers),
                "messages": [_header_to_dict(item) for item in headers],
            },
        )

    prepared.append(
        (
            ActionDescriptor(
                action_id=SEARCH_ACTION_ID,
                provider=PROVIDER_ID,
                description=(
                    "Search one IMAP mailbox by sender, subject, text, date, "
                    "or unread state. Read-only."
                ),
                body_action_kind=_body_kind(SEARCH_ACTION_ID, read=True),
                input_schema={
                    "type": "object",
                    "properties": {
                        "mailbox": {
                            "type": "string",
                            "description": "Mailbox name; defaults to INBOX",
                        },
                        "from": {
                            "type": "string",
                            "description": "Sender address substring",
                        },
                        "subject": {
                            "type": "string",
                            "description": "Subject substring",
                        },
                        "text": {
                            "type": "string",
                            "description": "Free-text search",
                        },
                        "since": {
                            "type": "string",
                            "description": "Messages on/after YYYY-MM-DD",
                        },
                        "unseen_only": {
                            "type": "boolean",
                            "description": "Only unread messages",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max headers to return (1..100)",
                        },
                    },
                    "additionalProperties": False,
                },
                effect_class="read_only",
                required_authority=(),
                sensitivity="personal_mail",
                preconditions=("a configured mail account",),
                verification=("headers come from the IMAP server's response",),
                replay_semantics="read_only",
                tags=("mail", "imap", "read_only", "external"),
            ),
            True,
            call_search,
        )
    )

    # -- send (approval-gated write) --------------------------------------
    def call_send(action: BodyAction, started: str) -> BodyActionResult:
        receipt = send_message(
            smtp_client,
            config,
            credential_store,
            to=action.args.get("to"),
            cc=action.args.get("cc"),
            bcc=action.args.get("bcc"),
            subject=action.args.get("subject"),
            body=action.args.get("body"),
            from_addr=action.args.get("from"),
            imap_transport=imap_client,
        )
        return _result(
            action,
            started,
            {
                "provider_id": PROVIDER_ID,
                "tool": "send_message",
                "source": _SOURCE_LABEL,
                "message_id": receipt.message_id,
                "from": receipt.from_addr,
                "to": list(receipt.to_addrs),
                "smtp_accepted": receipt.accepted,
                "smtp_response": receipt.smtp_response,
                "archived_in_sent": receipt.archived_in_sent,
                "archive_note": receipt.archive_note,
            },
        )

    prepared.append(
        (
            ActionDescriptor(
                action_id=SEND_ACTION_ID,
                provider=PROVIDER_ID,
                description=(
                    "Send one plain-text email via SMTP. "
                    "Requires user approval before dispatch."
                ),
                body_action_kind=_body_kind(SEND_ACTION_ID, read=False),
                input_schema={
                    "type": "object",
                    "required": ["to", "subject", "body"],
                    "properties": {
                        "to": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Recipient addresses",
                        },
                        "cc": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "bcc": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Envelope-only recipients, never in headers"
                            ),
                        },
                        "from": {
                            "type": "string",
                            "description": (
                                "Sender address; defaults to the account user"
                            ),
                        },
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                effect_class="irreversible_side_effect",
                required_authority=("body_action",),
                sensitivity="personal_mail",
                preconditions=("user approved the send via an approval card",),
                postconditions=(
                    "the SMTP server accepted the message; a copy is "
                    "archived in the Sent mailbox"
                ),
                verification=(
                    "fresh re-search of the Sent mailbox contains the "
                    "message-id, or the recorded SMTP acceptance"
                ),
                reversibility="email cannot be unsent; no reversal",
                replay_semantics="verify_before_replay",
                tags=(
                    "mail",
                    "smtp",
                    "mail_send",
                    f"approval:{APPROVAL_KIND}",
                ),
            ),
            False,
            call_send,
        )
    )

    probe = _mail_probe(config)
    probes = {descriptor.action_id: probe for descriptor, _, _ in prepared}

    registered: list[ActionDescriptor] = []
    attached_kinds: list[tuple[str, bool]] = []
    action_ids: list[str] = []
    try:
        for descriptor, was_read, handler in prepared:
            if fabric.descriptor(descriptor.action_id) is not None:
                raise ValueError(
                    "Action Fabric already owns action "
                    f"{descriptor.action_id}"
                )
            assert descriptor.body_action_kind is not None
            kinds = (
                body._external_read_handlers
                if was_read
                else body._external_write_handlers
            )
            if descriptor.body_action_kind in kinds:
                raise ValueError("Body extension identifier collision")

        completed_identities: set[str] = set()

        for descriptor, was_read, handler in prepared:
            kind = descriptor.body_action_kind
            assert kind is not None

            def guarded(
                action: BodyAction,
                started: str,
                *,
                inner=handler,
                action_id=descriptor.action_id,
                tool=descriptor.action_id.split(".")[-1],
                read=was_read,
            ) -> BodyActionResult:
                if not read:
                    identity = mcp_write_replay_identity(
                        provider_id=PROVIDER_ID,
                        tool_name=tool,
                        args=action.args,
                        event_id=action.event_id,
                    )
                    if identity in completed_identities:
                        raise RuntimeError(
                            "mail write replay refused: this exact send "
                            "occurrence already reached its target; do not "
                            "redispatch"
                        )
                    result = inner(action, started)
                    completed_identities.add(identity)
                    return result
                return inner(action, started)

            if was_read:
                body.register_external_read_handler(kind, guarded)
            else:
                body.register_external_write_handler(kind, guarded)
            attached_kinds.append((kind, was_read))
            fabric.register(descriptor, availability_probe=probes[descriptor.action_id])
            registered.append(descriptor)
            action_ids.append(descriptor.action_id)
    except Exception:
        for descriptor in registered:
            fabric.unregister(descriptor.action_id)
        for kind, was_read in attached_kinds:
            if was_read:
                body.unregister_external_read_handler(kind)
            else:
                body.unregister_external_write_handler(kind)
        raise
    return MailAttachmentHandle(fabric, body, attached_kinds, action_ids)


# ---------------------------------------------------------------------------
# Runtime binding: approval scope (workspace_file_actions shape)
# ---------------------------------------------------------------------------


def _send_write_scope(config: MailAccountConfig | None):
    def resolver(args: Mapping[str, Any]) -> tuple[str, str, str]:
        target = config.smtp_host if config else "(no mail account configured)"
        to_addrs = args.get("to")
        if isinstance(to_addrs, (list, tuple)):
            recipients = ", ".join(str(item) for item in to_addrs[:5])
        else:
            recipients = str(to_addrs or "")
        subject = str(args.get("subject") or "").strip()[:80]
        return (
            "mail-smtp",
            target,
            f"send mail to {recipients} with subject {subject!r} via {target}",
        )

    return resolver


def register_mail_runtime(
    runtime: ActionExecutionRuntime,
    *,
    config: MailAccountConfig | None = None,
    imap_transport: ImapTransport | None = None,
    credential_store: CredentialStore | None = None,
) -> None:
    """Bind the approval scope and the send verifier, like the workspace
    file actions do.

    The verifier independently re-observes the Sent mailbox for the
    message-id; when IMAP is unavailable it falls back to the recorded
    SMTP acceptance receipt and says so in the evidence.
    """
    runtime.register_approval_scope(SEND_ACTION_ID, _send_write_scope(config))

    def observe_send(
        request: ActionRequest, result: BodyActionResult | None
    ) -> ActionObservation:
        data = dict((result.data or {}) if result is not None else {})
        message_id = str(data.get("message_id") or "")
        found = False
        via = "receipt"
        if message_id and config is not None and imap_transport is not None:
            try:
                session = _open_session(imap_transport, config, credential_store)
                try:
                    session.select(config.sent_mailbox)
                    criteria = f'HEADER Message-ID "{_escape_search_text(message_id)}"'
                    found = bool(session.search(criteria))
                    via = "sent_research"
                finally:
                    session.close()
            except MailError:
                found = False
        return ActionObservation(
            request.action_id,
            "mail_sent_verification",
            data={
                **data,
                "message_id_found_in_sent": found,
                "verification_via": via,
            },
        )

    def verify_send(
        request: ActionRequest,
        observation: ActionObservation,
        result: BodyActionResult | None,
    ) -> ActionVerification:
        data = dict((result.data or {}) if result is not None else {})
        observation_data = dict(observation.data or {})
        message_id = str(data.get("message_id") or "")
        if not message_id:
            return ActionVerification("failed", "send result carries no message-id")
        if observation_data.get("message_id_found_in_sent"):
            return ActionVerification(
                "verified",
                "fresh Sent mailbox re-search contains the message-id",
            )
        if data.get("smtp_accepted") and str(data.get("smtp_response") or "").startswith("250"):
            return ActionVerification(
                "verified",
                "SMTP server acceptance recorded (250); Sent mailbox "
                "re-search unavailable",
            )
        return ActionVerification(
            "failed",
            "neither the Sent re-search nor an SMTP acceptance confirms the send",
        )

    runtime.register_verification(
        SEND_ACTION_ID,
        observe=observe_send,
        verify=verify_send,
    )
