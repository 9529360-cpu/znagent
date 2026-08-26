from __future__ import annotations

"""ZN-owned browser session, action, authority and evidence contracts.

Browser engines and providers are replaceable Body resources. These contracts keep
session identity, permission, target binding and completion evidence resident-owned
so local Chromium, cloud providers and the user's existing browser can converge on
one semantic boundary without becoming ZN's control plane.
"""

import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Protocol
from urllib.parse import urlsplit

from .models import utc_now


class BrowserPlane(str, Enum):
    MANAGED = "managed"
    USER = "user"


class BrowserActionKind(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    FOCUS = "focus"
    TYPE_TEXT = "type_text"
    PRESS = "press"
    SELECT_OPTION = "select_option"
    CHECK = "check"
    UNCHECK = "uncheck"
    WAIT = "wait"
    BACK = "back"
    FORWARD = "forward"
    RELOAD = "reload"


class BrowserTargetKind(str, Enum):
    PAGE = "page"
    ELEMENT = "element"
    ACCESSIBILITY_NODE = "accessibility_node"
    VISUAL_REGION = "visual_region"
    DESKTOP_ELEMENT = "desktop_element"


_NAVIGATION_ACTIONS = frozenset(
    {
        BrowserActionKind.NAVIGATE,
        BrowserActionKind.BACK,
        BrowserActionKind.FORWARD,
        BrowserActionKind.RELOAD,
    }
)
_PAGE_INTERACTION_ACTIONS = frozenset(
    {
        BrowserActionKind.CLICK,
        BrowserActionKind.FOCUS,
        BrowserActionKind.PRESS,
        BrowserActionKind.SELECT_OPTION,
        BrowserActionKind.CHECK,
        BrowserActionKind.UNCHECK,
    }
)


@dataclass(frozen=True, slots=True)
class BrowserSessionIdentity:
    session_id: str
    plane: BrowserPlane
    provider: str
    created_at: str = field(default_factory=utc_now)
    browser_name: str = ""
    browser_version: str = ""
    profile_scope: str = "ephemeral"

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("browser session_id must not be empty")
        if not self.provider.strip():
            raise ValueError("browser provider must not be empty")
        if self.profile_scope not in {"ephemeral", "managed_persistent", "user_existing"}:
            raise ValueError("unsupported browser profile_scope")
        if self.plane is BrowserPlane.USER and self.profile_scope != "user_existing":
            raise ValueError("user browser sessions must use user_existing profile_scope")
        if self.plane is BrowserPlane.MANAGED and self.profile_scope == "user_existing":
            raise ValueError("managed browser sessions cannot claim a user profile")

    @classmethod
    def create(
        cls,
        *,
        plane: BrowserPlane,
        provider: str,
        browser_name: str = "",
        browser_version: str = "",
        profile_scope: str | None = None,
    ) -> "BrowserSessionIdentity":
        resolved_scope = profile_scope or (
            "user_existing" if plane is BrowserPlane.USER else "ephemeral"
        )
        return cls(
            session_id=f"browser-{uuid.uuid4().hex[:16]}",
            plane=plane,
            provider=provider,
            browser_name=browser_name,
            browser_version=browser_version,
            profile_scope=resolved_scope,
        )


@dataclass(frozen=True, slots=True)
class BrowserPermissionContext:
    allow_navigation: bool = False
    allow_page_interaction: bool = False
    allow_text_entry: bool = False
    allow_downloads: bool = False
    allow_uploads: bool = False
    allow_clipboard: bool = False
    allow_sensitive_fields: bool = False
    allow_private_network: bool = False
    allowed_origins: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized: list[str] = []
        for raw in self.allowed_origins:
            origin = _normalize_origin(raw)
            if not origin:
                raise ValueError(f"invalid browser allowed origin: {raw!r}")
            normalized.append(origin)
        if len(set(normalized)) != len(normalized):
            raise ValueError("browser allowed_origins must not contain duplicates")
        object.__setattr__(self, "allowed_origins", tuple(normalized))

    def allows_origin(self, url: str) -> bool:
        if not self.allowed_origins:
            return True
        origin = _normalize_origin(url)
        return bool(origin and origin in self.allowed_origins)

    def allows_action(self, kind: BrowserActionKind) -> bool:
        if kind in _NAVIGATION_ACTIONS:
            return bool(self.allow_navigation)
        if kind is BrowserActionKind.TYPE_TEXT:
            return bool(self.allow_page_interaction and self.allow_text_entry)
        if kind in _PAGE_INTERACTION_ACTIONS:
            return bool(self.allow_page_interaction)
        if kind is BrowserActionKind.WAIT:
            return True
        return False


@dataclass(frozen=True, slots=True)
class BrowserTarget:
    session_id: str
    page_id: str
    kind: BrowserTargetKind
    target_id: str
    observed_at: str
    url: str = ""
    frame_id: str = ""
    role: str = ""
    name: str = ""
    selector_hint: str = ""

    def __post_init__(self) -> None:
        if not self.session_id.strip() or not self.page_id.strip():
            raise ValueError("browser target requires session_id and page_id")
        if not self.target_id.strip():
            raise ValueError("browser target_id must not be empty")
        if not self.observed_at.strip():
            raise ValueError("browser target observed_at must not be empty")


@dataclass(frozen=True, slots=True)
class BrowserObservation:
    session: BrowserSessionIdentity
    page_id: str
    captured_at: str
    url: str
    title: str
    load_state: str
    target: BrowserTarget | None = None
    viewport: tuple[int, int] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.page_id.strip():
            raise ValueError("browser observation page_id must not be empty")
        if not self.captured_at.strip():
            raise ValueError("browser observation captured_at must not be empty")
        if self.target is not None and self.target.session_id != self.session.session_id:
            raise ValueError("browser target session does not match observation session")
        if self.target is not None and self.target.page_id != self.page_id:
            raise ValueError("browser target page does not match observation page")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BrowserAction:
    action_id: str
    session_id: str
    kind: BrowserActionKind
    created_at: str
    page_id: str = ""
    target: BrowserTarget | None = None
    args: dict[str, Any] = field(default_factory=dict)
    expected: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.action_id.strip() or not self.session_id.strip():
            raise ValueError("browser action requires action_id and session_id")
        if self.target is not None and self.target.session_id != self.session_id:
            raise ValueError("browser action target belongs to a different session")
        if self.target is not None and self.page_id and self.target.page_id != self.page_id:
            raise ValueError("browser action target belongs to a different page")

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        kind: BrowserActionKind,
        page_id: str = "",
        target: BrowserTarget | None = None,
        args: dict[str, Any] | None = None,
        expected: dict[str, Any] | None = None,
    ) -> "BrowserAction":
        return cls(
            action_id=f"browser-action-{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            kind=kind,
            created_at=utc_now(),
            page_id=page_id,
            target=target,
            args=dict(args or {}),
            expected=dict(expected or {}),
        )


@dataclass(frozen=True, slots=True)
class BrowserActionAuthority:
    action_id: str
    session_id: str
    issued_at: str
    observation_captured_at: str
    permission: BrowserPermissionContext
    target_id: str = ""
    page_id: str = ""

    def __post_init__(self) -> None:
        if not self.action_id.strip() or not self.session_id.strip():
            raise ValueError("browser action authority requires action/session identity")
        if not self.observation_captured_at.strip():
            raise ValueError("browser authority requires fresh observation identity")

    @classmethod
    def from_observation(
        cls,
        action: BrowserAction,
        observation: BrowserObservation,
        permission: BrowserPermissionContext,
    ) -> "BrowserActionAuthority":
        authority = cls(
            action_id=action.action_id,
            session_id=action.session_id,
            issued_at=utc_now(),
            observation_captured_at=observation.captured_at,
            permission=permission,
            target_id=action.target.target_id if action.target is not None else "",
            page_id=action.page_id or observation.page_id,
        )
        authority.validate_current(action, observation, permission)
        return authority

    def validate_current(
        self,
        action: BrowserAction,
        observation: BrowserObservation,
        permission: BrowserPermissionContext,
    ) -> None:
        if self.action_id != action.action_id:
            raise ValueError("browser authority belongs to a different action")
        if self.session_id != action.session_id:
            raise ValueError("browser authority belongs to a different session")
        if self.permission != permission:
            raise ValueError("browser authority permission does not match current permission")
        if not permission.allows_action(action.kind):
            raise ValueError(f"browser action is not permitted: {action.kind.value}")
        if self.observation_captured_at != observation.captured_at:
            raise ValueError("browser action authority is stale")

        _require_action_matches_observation(action, observation)

        expected_page_id = action.page_id or observation.page_id
        if self.page_id != expected_page_id:
            raise ValueError("browser authority belongs to a different page")
        expected_target_id = action.target.target_id if action.target is not None else ""
        if self.target_id != expected_target_id:
            raise ValueError("browser authority target does not match current action target")


@dataclass(frozen=True, slots=True)
class BrowserEffectEvidence:
    action_id: str
    session_id: str
    observed_at: str
    success: bool
    page_id: str = ""
    url_before: str = ""
    url_after: str = ""
    target_id: str = ""
    postcondition: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.action_id.strip() or not self.session_id.strip():
            raise ValueError("browser effect evidence requires action/session identity")
        if self.success and self.error:
            raise ValueError("successful browser effect evidence cannot carry an error")
        if not self.success and not self.error:
            raise ValueError("failed browser effect evidence requires an error")


class BrowserAdapter(Protocol):
    name: str
    plane: BrowserPlane

    def open_session(
        self,
        *,
        permission: BrowserPermissionContext | None = None,
        headless: bool = True,
    ) -> BrowserSessionIdentity: ...

    def close_session(self, session_id: str) -> None: ...

    def observe(self, session_id: str, *, page_id: str = "") -> BrowserObservation: ...

    def act(
        self,
        action: BrowserAction,
        authority: BrowserActionAuthority,
    ) -> BrowserEffectEvidence: ...


def _require_action_matches_observation(
    action: BrowserAction,
    observation: BrowserObservation,
) -> None:
    if action.session_id != observation.session.session_id:
        raise ValueError("browser action and observation sessions do not match")
    if action.page_id and action.page_id != observation.page_id:
        raise ValueError("browser action and observation pages do not match")
    if action.target is None:
        return

    current = observation.target
    if current is None:
        raise ValueError("browser target action requires a current target observation")
    if action.target.page_id != observation.page_id:
        raise ValueError("browser action target belongs to a different observed page")
    if action.target.target_id != current.target_id:
        raise ValueError("browser target changed before authority was formed")
    if action.target.kind is not current.kind:
        raise ValueError("browser target kind changed before authority was formed")
    if action.target.frame_id != current.frame_id:
        raise ValueError("browser target frame changed before authority was formed")
    if action.target.observed_at != current.observed_at:
        raise ValueError("browser target evidence is stale")


def _normalize_origin(value: str) -> str:
    try:
        parsed = urlsplit(str(value or "").strip())
        scheme = str(parsed.scheme or "").lower()
        host = str(parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except (TypeError, ValueError):
        return ""
    if scheme not in {"http", "https"} or not host:
        return ""
    default = (scheme == "http" and port in {None, 80}) or (
        scheme == "https" and port in {None, 443}
    )
    suffix = "" if default else f":{port}"
    return f"{scheme}://{host}{suffix}"
