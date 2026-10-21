from __future__ import annotations

"""Messaging connector (R10): WhatsApp channel adapter plus approval-gated send.

Channel selection (verified 2026-10-21): WhatsApp is the landed channel, via
the **official WhatsApp Cloud API** (``https://graph.facebook.com``) — a plain
HTTPS REST API with a per-app access token plus a phone-number ID. It needs no
local phone pairing, no QR scan, and no browser automation; authorization is a
single deploy-time step (the user creates a Meta app / phone-number ID and
stores the token in ZN's credential store once), so it fits the R-series
"authorize once at deploy time" shape exactly. Local WhatsApp Web bridges
(e.g. whatsapp-web.js style session hijacking) were rejected: they need the
user's phone to stay paired, session files rot, and the unofficial automation
surface risks account bans — the wrong foundation for a resident assistant.

Honest boundary: the WhatsApp Cloud API is **send-centric**. There is no
official "list my chat threads / read history" REST endpoint; inbound messages
arrive as webhook pushes into the deploy-time webhook subscription and then
into ZN's event pipeline. Accordingly the channel abstraction
(:class:`MessagingChannel`) is what the actions speak to, and the shipped
WhatsApp driver implements ``send_text`` over real HTTPS while
``list_threads``/``read_thread`` raise an explicit :class:`MessagingError`
naming the webhook step instead of pretending to read. Reads stay fully
covered by the injected fake channel in tests; a second driver (e.g. Telegram
Bot API, where ``getUpdates`` does expose inbound) can attach later as
``msg.<channel>.*`` actions without changing the approval layer.

Three actions on the SAME Fabric/Body capability path as every other
connector (the R1/R3/R5/R6 shape — never a parallel plugin path, never
model-supplied configuration):

* ``msg.whatsapp.list_threads`` — newest-first conversation threads.
* ``msg.whatsapp.read_thread`` — the newest N messages of one thread.
* ``msg.whatsapp.send_text`` — send one text message to a phone number.
  The descriptor carries an ``approval:send`` tag, so the
  ActionExecutionRuntime opens an approval card before dispatch: a
  denied or undecided send never reaches the channel. The replay guard
  refuses redispatch of an already-completed send (same replay-identity
  machinery as the other connectors), and
  :func:`register_messaging_runtime` binds a canonical approval scope
  plus an independent verifier that re-reads the thread for the
  provider message id, falling back to the recorded provider
  acceptance receipt and saying so.

Credentials: the account config carries only a ZN credential reference
(e.g. ``provider:whatsapp``). The token is resolved through the host's
:class:`~zn_agent.core.credentials.CredentialStore` at call time, held
only in locals, and never written to the repository. With no account
configured — or no secret behind the reference — every action raises an
explicit "not configured（未配置）" :class:`MessagingError` instead of
pretending to work. Real-account authorization is a deploy-time user
step; the shipped code path is proven with a fake channel and a fake
HTTP transport only.

Transport honesty: every HTTP failure becomes a :class:`MessagingError`
whose message IS the reason (status code plus the provider's own error
payload when present). Message ids are never invented: a send that the
provider did not confirm with a message id is a failure.
"""

import hashlib
import json
import re
import urllib.error
import urllib.request
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
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
    "CHANNEL_ID",
    "LIST_ACTION_ID",
    "PROVIDER_ID",
    "READ_ACTION_ID",
    "SEND_ACTION_ID",
    "ChatMessage",
    "ChatThread",
    "HttpTransport",
    "MessagingAccountConfig",
    "MessagingAttachmentHandle",
    "MessagingChannel",
    "MessagingError",
    "SendReceipt",
    "StdlibHttpTransport",
    "WhatsAppCloudChannel",
    "attach_messaging_tools",
    "list_threads",
    "read_thread",
    "register_messaging_runtime",
    "send_text",
]

PROVIDER_ID = "zn.messaging"
#: The one landed channel driver. Future drivers (e.g. ``telegram``) attach
#: as ``msg.<channel>.*`` actions without touching this module's approval
#: layer.
CHANNEL_ID = "whatsapp"
#: Approval kind gating message sending. Reuses the existing ``send`` kind
#: (approval_cards: "a sensitive action (send / publish / purchase /
#: delete / production_change)"): no new kind is needed because sending a
#: message is exactly what ``send`` covers — same as R6's mail send.
APPROVAL_KIND = "send"
assert APPROVAL_KIND in APPROVAL_KINDS

LIST_ACTION_ID = "msg.whatsapp.list_threads"
READ_ACTION_ID = "msg.whatsapp.read_thread"
SEND_ACTION_ID = "msg.whatsapp.send_text"

_SOURCE_LABEL = "ZN messaging connector (WhatsApp Cloud API)"

_MAX_THREAD_LIMIT = 50
_MAX_MESSAGE_LIMIT = 100
_MAX_TEXT_CHARS = 4000
_MAX_PREVIEW_CHARS = 160
_MAX_ID_CHARS = 256

_PHONE_RE = re.compile(r"^\+?[0-9]{7,15}$")
_PHONE_NUMBER_ID_RE = re.compile(r"^[0-9]{5,20}$")
_CRLF_RE = re.compile(r"[\r\n]")
_WS_RE = re.compile(r"\s+")
_BASE_URL_RE = re.compile(r"^https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?$")
_API_VERSION_RE = re.compile(r"^v[0-9]{2,}\.[0-9]+$")


class MessagingError(Exception):
    """Explicit messaging failure: never invent messages, never hide a reason."""


# ---------------------------------------------------------------------------
# Account configuration (credential reference only — never a secret)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MessagingAccountConfig:
    """One messaging account on the WhatsApp Cloud API.

    ``phone_number_id`` is the WhatsApp Business phone-number ID from the
    user's Meta app (not a secret — it travels in the request path).
    ``credential_ref`` is a ZN credential-store reference such as
    ``provider:whatsapp`` for the access token. The token is resolved from
    the host's CredentialStore at call time and never stored on this
    object, in the repository, or in logs.
    """

    phone_number_id: str
    credential_ref: str
    channel: str = CHANNEL_ID
    api_base_url: str = "https://graph.facebook.com"
    api_version: str = "v21.0"
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        channel = str(self.channel or "").strip().lower()
        if channel != CHANNEL_ID:
            raise MessagingError(
                f"messaging channel must be {CHANNEL_ID!r}, got {self.channel!r}"
            )
        self.channel = channel
        phone_id = str(self.phone_number_id or "").strip()
        if not _PHONE_NUMBER_ID_RE.fullmatch(phone_id):
            raise MessagingError(
                "messaging phone_number_id must be the numeric WhatsApp "
                f"Business phone-number ID, got {self.phone_number_id!r}"
            )
        self.phone_number_id = phone_id
        base_url = str(self.api_base_url or "").strip().rstrip("/")
        if not _BASE_URL_RE.fullmatch(base_url):
            raise MessagingError(
                f"messaging api_base_url must be an https origin, got {self.api_base_url!r}"
            )
        self.api_base_url = base_url
        version = str(self.api_version or "").strip()
        if not _API_VERSION_RE.fullmatch(version):
            raise MessagingError(
                f"messaging api_version must look like 'v21.0', got {self.api_version!r}"
            )
        self.api_version = version
        timeout = float(self.timeout_seconds)
        if not 1.0 <= timeout <= 120.0:
            raise MessagingError(
                "messaging timeout_seconds must be between 1 and 120"
            )
        self.timeout_seconds = timeout
        self.credential_ref = normalize_credential_reference(self.credential_ref)


# ---------------------------------------------------------------------------
# Conversation shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChatThread:
    """One conversation thread, newest activity first when listed."""

    thread_id: str
    peer: str
    last_message_preview: str
    last_message_at: datetime | None
    unread_count: int = 0


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One message inside a thread. ``provider_message_id`` is the id the
    provider confirmed for outbound sends; inbound messages carry the
    provider's own id when the channel reports one."""

    message_id: str
    thread_id: str
    direction: str  # "in" | "out"
    sender: str
    text: str
    sent_at: datetime | None
    provider_message_id: str | None = None


@dataclass(frozen=True, slots=True)
class SendReceipt:
    """What the channel confirmed about a send."""

    provider_message_id: str
    recipient: str
    accepted: bool
    provider_response: str


# ---------------------------------------------------------------------------
# Channel abstraction (transport-injected; unit-tested with fakes)
# ---------------------------------------------------------------------------


class MessagingChannel(Protocol):
    """The seam between the ZN actions and one concrete messaging channel.

    Reads and the send share one protocol so a fake channel can prove the
    whole read → draft → approve → send loop end to end in tests.
    """

    def list_threads(self, *, limit: int) -> list[ChatThread]:
        """Newest-activity-first threads."""
        ...

    def read_thread(self, thread_id: str, *, limit: int) -> list[ChatMessage]:
        """Newest-first messages of one thread."""
        ...

    def send_text(self, *, recipient: str, text: str) -> SendReceipt:
        """Send one text message; returns the provider's receipt. Raises
        :class:`MessagingError` when the provider did not confirm."""
        ...


class HttpTransport(Protocol):
    """Minimal injectable HTTP seam for the WhatsApp Cloud driver."""

    def post(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> tuple[int, bytes]:
        """POST a JSON body; returns (status_code, raw_response_body)."""
        ...


class StdlibHttpTransport:
    """Default :class:`HttpTransport` over stdlib ``urllib``."""

    def post(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> tuple[int, bytes]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", **dict(headers)},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=timeout_seconds
            ) as response:
                return int(response.status), response.read()
        except urllib.error.HTTPError as exc:
            with suppress(Exception):
                error_body = exc.read()
            return int(exc.code), error_body
        except (urllib.error.URLError, OSError) as exc:
            raise MessagingError(
                f"WhatsApp Cloud API request failed: {type(exc).__name__}: {exc}"
            ) from exc


def _whatsapp_error_reason(status: int, raw: bytes) -> str:
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        payload = {}
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        detail = error.get("error_data", {}).get("details") or error.get(
            "message"
        )
        code = error.get("code")
        return (
            f"WhatsApp Cloud API rejected the send (HTTP {status}, "
            f"code {code}): {detail}"
        )
    return (
        f"WhatsApp Cloud API rejected the send: HTTP {status} "
        f"with an unreadable body ({len(raw)} bytes)"
    )


class WhatsAppCloudChannel:
    """The landed channel driver: WhatsApp via the official Cloud API.

    ``send_text`` is a real REST call (stdlib ``urllib`` by default, fake
    transports in tests). ``list_threads``/``read_thread`` are honest
    dead ends on purpose: the Cloud API exposes no chat-history read
    endpoint — inbound arrives through the deploy-time webhook
    subscription into ZN's event pipeline, and the error names that
    step instead of faking a history.
    """

    def __init__(
        self,
        config: MessagingAccountConfig,
        credential_store: CredentialStore | None,
        http_transport: HttpTransport | None = None,
    ) -> None:
        self._config = config
        self._credential_store = credential_store
        self._http = http_transport or StdlibHttpTransport()

    @property
    def config(self) -> MessagingAccountConfig:
        return self._config

    def _send_url(self) -> str:
        return (
            f"{self._config.api_base_url}/{self._config.api_version}/"
            f"{self._config.phone_number_id}/messages"
        )

    def _auth_headers(self) -> dict[str, str]:
        token = _resolve_token(self._config, self._credential_store)
        return {"Authorization": f"Bearer {token}"}

    def list_threads(self, *, limit: int) -> list[ChatThread]:
        raise MessagingError(
            "WhatsApp Cloud API exposes no chat-history read endpoint: "
            "inbound messages arrive through the deploy-time webhook "
            "subscription into ZN's event pipeline. Until that webhook is "
            "authorized and wired, list_threads is unavailable on the "
            "whatsapp channel — use the injected channel's own thread "
            "store in tests."
        )

    def read_thread(self, thread_id: str, *, limit: int) -> list[ChatMessage]:
        raise MessagingError(
            "WhatsApp Cloud API exposes no per-thread read endpoint: "
            "inbound messages arrive through the deploy-time webhook "
            "subscription into ZN's event pipeline. Until that webhook is "
            "authorized and wired, read_thread is unavailable on the "
            "whatsapp channel."
        )

    def send_text(self, *, recipient: str, text: str) -> SendReceipt:
        to = _check_recipient(recipient)
        body_text = _check_text(text)
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": body_text},
        }
        try:
            status, raw = self._http.post(
                url=self._send_url(),
                headers=self._auth_headers(),
                payload=payload,
                timeout_seconds=self._config.timeout_seconds,
            )
        except MessagingError:
            raise
        except Exception as exc:
            raise MessagingError(
                f"WhatsApp send transport failed: {type(exc).__name__}: {exc}"
            ) from exc
        if not 200 <= status < 300:
            raise MessagingError(_whatsapp_error_reason(status, raw))
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise MessagingError(
                "WhatsApp Cloud API returned an unreadable success body; "
                f"the send is unconfirmed: {exc}"
            ) from exc
        messages = data.get("messages") if isinstance(data, dict) else None
        message_id = (
            messages[0].get("id")
            if isinstance(messages, list)
            and messages
            and isinstance(messages[0], dict)
            else None
        )
        if not message_id:
            raise MessagingError(
                "WhatsApp Cloud API accepted the request but returned no "
                "message id; the send is unconfirmed"
            )
        return SendReceipt(
            provider_message_id=str(message_id),
            recipient=to,
            accepted=True,
            provider_response=json.dumps(data, ensure_ascii=False)[:500],
        )


# ---------------------------------------------------------------------------
# Credential resolution (reference only; secret never persisted)
# ---------------------------------------------------------------------------


def _not_configured(reason: str) -> MessagingError:
    return MessagingError(
        f"messaging account is not configured（未配置）: {reason}"
    )


def _resolve_token(
    config: MessagingAccountConfig | None,
    credential_store: CredentialStore | None,
) -> str:
    if config is None:
        raise _not_configured(
            "no messaging account was attached; the host must attach a "
            "MessagingAccountConfig (authorize once at deploy time)"
        )
    if credential_store is None:
        raise _not_configured(
            "no credential store is available to resolve "
            f"{config.credential_ref!r}"
        )
    try:
        secret = credential_store.get(config.credential_ref)
    except CredentialStoreUnavailable as exc:
        raise _not_configured(
            f"credential store unavailable: {exc}"
        ) from exc
    except Exception as exc:
        raise _not_configured(
            f"credential lookup failed: {type(exc).__name__}: {exc}"
        ) from exc
    if not secret:
        raise _not_configured(
            f"no secret behind credential reference {config.credential_ref!r}; "
            "authorize the WhatsApp Cloud API token once at deploy time"
        )
    return secret


# ---------------------------------------------------------------------------
# Input validation (before any channel is touched)
# ---------------------------------------------------------------------------


def _check_limit(limit: Any, *, maximum: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        raise MessagingError(f"'limit' must be an integer, got {limit!r}")
    if not 1 <= value <= maximum:
        raise MessagingError(f"'limit' must be 1..{maximum}, got {value}")
    return value


def _check_thread_id(thread_id: Any) -> str:
    value = str(thread_id or "").strip()
    if not value or _CRLF_RE.search(value):
        raise MessagingError("'thread_id' must be a non-empty thread id")
    if len(value) > _MAX_ID_CHARS:
        raise MessagingError("'thread_id' is too long")
    return value


def _check_recipient(recipient: Any) -> str:
    value = _WS_RE.sub("", str(recipient or ""))
    if not _PHONE_RE.fullmatch(value):
        raise MessagingError(
            "'to' must be a phone number in international digits "
            f"(e.g. +4915112345678), got {recipient!r}"
        )
    return value


def _check_text(text: Any) -> str:
    body_text = str(text or "")
    if not body_text.strip():
        raise MessagingError("'text' must not be empty")
    if len(body_text) > _MAX_TEXT_CHARS:
        raise MessagingError(
            f"'text' exceeds {_MAX_TEXT_CHARS} characters"
        )
    return body_text


def _require_channel(
    config: MessagingAccountConfig | None,
    channel: MessagingChannel | None,
    credential_store: CredentialStore | None,
) -> MessagingChannel:
    if config is None:
        raise _not_configured(
            "no messaging account was attached; the host must attach a "
            "MessagingAccountConfig (authorize once at deploy time)"
        )
    if channel is not None:
        return channel
    return WhatsAppCloudChannel(config, credential_store)


def _preview(text: str) -> str:
    collapsed = _WS_RE.sub(" ", str(text or "")).strip()
    if len(collapsed) > _MAX_PREVIEW_CHARS:
        return collapsed[:_MAX_PREVIEW_CHARS] + "…"
    return collapsed


# ---------------------------------------------------------------------------
# Core operations (channel-injected; unit-tested with fakes)
# ---------------------------------------------------------------------------


def list_threads(
    channel: MessagingChannel | None,
    config: MessagingAccountConfig | None,
    credential_store: CredentialStore | None,
    *,
    limit: int = 20,
) -> list[ChatThread]:
    """Newest-activity-first conversation threads."""
    count = _check_limit(limit, maximum=_MAX_THREAD_LIMIT)
    active = _require_channel(config, channel, credential_store)
    try:
        return active.list_threads(limit=count)
    except MessagingError:
        raise
    except Exception as exc:
        raise MessagingError(
            f"list_threads failed: {type(exc).__name__}: {exc}"
        ) from exc


def read_thread(
    channel: MessagingChannel | None,
    config: MessagingAccountConfig | None,
    credential_store: CredentialStore | None,
    *,
    thread_id: str,
    limit: int = 20,
) -> list[ChatMessage]:
    """Newest-first messages of one thread."""
    tid = _check_thread_id(thread_id)
    count = _check_limit(limit, maximum=_MAX_MESSAGE_LIMIT)
    active = _require_channel(config, channel, credential_store)
    try:
        return active.read_thread(tid, limit=count)
    except MessagingError:
        raise
    except Exception as exc:
        raise MessagingError(
            f"read_thread failed: {type(exc).__name__}: {exc}"
        ) from exc


def send_text(
    channel: MessagingChannel | None,
    config: MessagingAccountConfig | None,
    credential_store: CredentialStore | None,
    *,
    to: Any,
    text: Any,
) -> SendReceipt:
    """Send one text message; returns the provider's receipt.

    Every validation runs before the channel is touched, and the receipt
    is only returned when the provider confirmed a message id.
    """
    active = _require_channel(config, channel, credential_store)
    recipient = _check_recipient(to)
    body_text = _check_text(text)
    try:
        return active.send_text(recipient=recipient, text=body_text)
    except MessagingError:
        raise
    except Exception as exc:
        raise MessagingError(
            f"send_text failed: {type(exc).__name__}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Fabric/Body attachment
# ---------------------------------------------------------------------------


def _body_kind(action_id: str, *, read: bool) -> str:
    digest = hashlib.sha256(action_id.encode("utf-8")).hexdigest()[:24]
    return f"zn_messaging_read_{digest}" if read else f"zn_messaging_write_{digest}"


def _thread_to_dict(thread: ChatThread) -> dict[str, Any]:
    return {
        "thread_id": thread.thread_id,
        "peer": thread.peer,
        "last_message_preview": thread.last_message_preview,
        "last_message_at": (
            thread.last_message_at.isoformat() if thread.last_message_at else None
        ),
        "unread_count": thread.unread_count,
    }


def _message_to_dict(message: ChatMessage) -> dict[str, Any]:
    return {
        "message_id": message.message_id,
        "thread_id": message.thread_id,
        "direction": message.direction,
        "sender": message.sender,
        "text": message.text,
        "sent_at": message.sent_at.isoformat() if message.sent_at else None,
        "provider_message_id": message.provider_message_id,
    }


def _messaging_probe(config: MessagingAccountConfig | None):
    def probe(item) -> ActionAvailability:
        if config is None:
            return ActionAvailability(
                item.action_id,
                "unavailable",
                reason=(
                    "no messaging account configured: attach with a "
                    "MessagingAccountConfig to enable these actions"
                ),
            )
        return ActionAvailability(
            item.action_id,
            "available",
            reason="messaging account configured",
            evidence={
                "channel": config.channel,
                "phone_number_id": config.phone_number_id,
                "credential_ref": config.credential_ref,
            },
        )

    return probe


class MessagingAttachmentHandle:
    """Handle returned by :func:`attach_messaging_tools`; call detach()."""

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

def attach_messaging_tools(
    fabric: ActionFabricRegistry,
    body: NativeBody,
    *,
    config: MessagingAccountConfig | None = None,
    channel: MessagingChannel | None = None,
    credential_store: CredentialStore | None = None,
) -> MessagingAttachmentHandle:
    """Attach the messaging toolset to the Fabric/Body, R1/R6 shape.

    ``config`` carries only a credential reference; the token is resolved
    from ``credential_store`` at call time. With no account configured the
    actions stay registered but report "not configured" instead of
    pretending to work. ``channel`` defaults to the WhatsApp Cloud API
    driver; tests inject a fake channel.
    """
    default_channel: MessagingChannel | None = None
    if config is not None and channel is None:
        default_channel = WhatsAppCloudChannel(config, credential_store)

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

    # -- list threads -------------------------------------------------------
    def call_list(action: BodyAction, started: str) -> BodyActionResult:
        threads = list_threads(
            channel or default_channel,
            config,
            credential_store,
            limit=action.args.get("limit", 20),
        )
        return _result(
            action,
            started,
            {
                "provider_id": PROVIDER_ID,
                "tool": "list_threads",
                "source": _SOURCE_LABEL,
                "thread_count": len(threads),
                "threads": [_thread_to_dict(item) for item in threads],
            },
        )

    prepared.append(
        (
            ActionDescriptor(
                action_id=LIST_ACTION_ID,
                provider=PROVIDER_ID,
                description=(
                    "List the newest conversation threads on the messaging "
                    "channel. Read-only: never modifies anything."
                ),
                body_action_kind=_body_kind(LIST_ACTION_ID, read=True),
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Max threads to return (1..50)",
                        },
                    },
                    "additionalProperties": False,
                },
                effect_class="read_only",
                required_authority=(),
                sensitivity="personal_messaging",
                preconditions=("a configured messaging account",),
                verification=("threads come from the channel's response",),
                replay_semantics="read_only",
                tags=("messaging", "whatsapp", "read_only", "external"),
            ),
            True,
            call_list,
        )
    )

    # -- read thread --------------------------------------------------------
    def call_read(action: BodyAction, started: str) -> BodyActionResult:
        messages = read_thread(
            channel or default_channel,
            config,
            credential_store,
            thread_id=action.args.get("thread_id"),
            limit=action.args.get("limit", 20),
        )
        return _result(
            action,
            started,
            {
                "provider_id": PROVIDER_ID,
                "tool": "read_thread",
                "source": _SOURCE_LABEL,
                "thread_id": str(action.args.get("thread_id") or ""),
                "message_count": len(messages),
                "messages": [_message_to_dict(item) for item in messages],
            },
        )

    prepared.append(
        (
            ActionDescriptor(
                action_id=READ_ACTION_ID,
                provider=PROVIDER_ID,
                description=(
                    "Read the newest messages of one conversation thread: "
                    "direction, sender, text, timestamps. Read-only."
                ),
                body_action_kind=_body_kind(READ_ACTION_ID, read=True),
                input_schema={
                    "type": "object",
                    "required": ["thread_id"],
                    "properties": {
                        "thread_id": {
                            "type": "string",
                            "description": "Thread id from list_threads",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max messages to return (1..100)",
                        },
                    },
                    "additionalProperties": False,
                },
                effect_class="read_only",
                required_authority=(),
                sensitivity="personal_messaging",
                preconditions=("a configured messaging account",),
                verification=("messages come from the channel's response",),
                replay_semantics="read_only",
                tags=("messaging", "whatsapp", "read_only", "external"),
            ),
            True,
            call_read,
        )
    )

    # -- send (approval-gated write) ----------------------------------------
    def call_send(action: BodyAction, started: str) -> BodyActionResult:
        receipt = send_text(
            channel or default_channel,
            config,
            credential_store,
            to=action.args.get("to"),
            text=action.args.get("text"),
        )
        return _result(
            action,
            started,
            {
                "provider_id": PROVIDER_ID,
                "tool": "send_text",
                "source": _SOURCE_LABEL,
                "provider_message_id": receipt.provider_message_id,
                "to": receipt.recipient,
                "accepted": receipt.accepted,
                "provider_response": receipt.provider_response,
            },
        )

    prepared.append(
        (
            ActionDescriptor(
                action_id=SEND_ACTION_ID,
                provider=PROVIDER_ID,
                description=(
                    "Send one text message to a phone number on the "
                    "messaging channel. Requires user approval before "
                    "dispatch."
                ),
                body_action_kind=_body_kind(SEND_ACTION_ID, read=False),
                input_schema={
                    "type": "object",
                    "required": ["to", "text"],
                    "properties": {
                        "to": {
                            "type": "string",
                            "description": (
                                "Recipient phone number in international "
                                "digits, e.g. +4915112345678"
                            ),
                        },
                        "text": {
                            "type": "string",
                            "description": "Message text (1..4000 characters)",
                        },
                    },
                    "additionalProperties": False,
                },
                effect_class="irreversible_side_effect",
                required_authority=("body_action",),
                sensitivity="personal_messaging",
                preconditions=("user approved the send via an approval card",),
                postconditions=(
                    "the channel provider accepted the message and "
                    "confirmed a message id"
                ),
                verification=(
                    "fresh re-read of the recipient thread contains the "
                    "provider message id, or the recorded provider "
                    "acceptance receipt"
                ),
                reversibility="a sent message cannot be unsent; no reversal",
                replay_semantics="verify_before_replay",
                tags=(
                    "messaging",
                    "whatsapp",
                    "messaging_send",
                    f"approval:{APPROVAL_KIND}",
                ),
            ),
            False,
            call_send,
        )
    )

    probe = _messaging_probe(config)
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
                            "messaging write replay refused: this exact send "
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
    return MessagingAttachmentHandle(fabric, body, attached_kinds, action_ids)


# ---------------------------------------------------------------------------
# Runtime binding: approval scope (workspace_file_actions shape)
# ---------------------------------------------------------------------------


def _send_write_scope(config: MessagingAccountConfig | None):
    def resolver(args: Mapping[str, Any]) -> tuple[str, str, str]:
        target = (
            config.phone_number_id if config else "(no messaging account configured)"
        )
        recipient = str(args.get("to") or "")
        preview = _preview(str(args.get("text") or ""))
        return (
            "msg-whatsapp",
            target,
            f"send WhatsApp message to {recipient} via {target}: {preview!r}",
        )

    return resolver


def register_messaging_runtime(
    runtime: ActionExecutionRuntime,
    *,
    config: MessagingAccountConfig | None = None,
    channel: MessagingChannel | None = None,
    credential_store: CredentialStore | None = None,
) -> None:
    """Bind the approval scope and the send verifier, like the workspace
    file actions do.

    The verifier independently re-observes the recipient thread for the
    provider message id; when the channel cannot read threads (the
    WhatsApp Cloud driver before its webhook step, or no channel at
    all) it falls back to the recorded provider acceptance receipt and
    says so in the evidence.
    """
    runtime.register_approval_scope(SEND_ACTION_ID, _send_write_scope(config))

    def observe_send(
        request: ActionRequest, result: BodyActionResult | None
    ) -> ActionObservation:
        data = dict((result.data or {}) if result is not None else {})
        message_id = str(data.get("provider_message_id") or "")
        recipient = str(data.get("to") or "")
        found = False
        via = "receipt"
        active = None
        if config is not None:
            active = channel or WhatsAppCloudChannel(config, credential_store)
        if message_id and active is not None and recipient:
            try:
                for thread in active.list_threads(limit=_MAX_THREAD_LIMIT):
                    if thread.peer != recipient:
                        continue
                    for item in active.read_thread(
                        thread.thread_id, limit=_MAX_MESSAGE_LIMIT
                    ):
                        if (
                            item.direction == "out"
                            and item.provider_message_id == message_id
                        ):
                            found = True
                            via = "thread_research"
                            break
                    if found:
                        break
            except MessagingError:
                found = False
        return ActionObservation(
            request.action_id,
            "messaging_sent_verification",
            data={
                **data,
                "message_id_found_in_thread": found,
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
        message_id = str(data.get("provider_message_id") or "")
        if not message_id:
            return ActionVerification("failed", "send result carries no message id")
        if observation_data.get("message_id_found_in_thread"):
            return ActionVerification(
                "verified",
                "fresh thread re-read contains the provider message id",
            )
        if data.get("accepted"):
            return ActionVerification(
                "verified",
                "provider acceptance receipt recorded (message id "
                "confirmed); thread re-read unavailable",
            )
        return ActionVerification(
            "failed",
            "neither the thread re-read nor a provider acceptance "
            "confirms the send",
        )

    runtime.register_verification(
        SEND_ACTION_ID,
        observe=observe_send,
        verify=verify_send,
    )
