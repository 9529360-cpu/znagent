from __future__ import annotations

"""R13: daemon-level auto-attachment of approved R-series connectors.

The R1..R12 connectors each expose ``attach_*_tools(fabric, body, ...)``
entry points, but until this module nothing on the product path called
them: the tools only existed when host test code attached them by hand
(``docs/ZN-IMPLEMENTATION-STATUS.md`` closes five R-series sections with
"daemon-level auto-attachment is a later R-series step").

This module closes that gap:

- :data:`CONNECTOR_REGISTRY` is the declarative registry: connector name
  -> module -> attach/register function names -> whether it needs
  credentials -> read/write planes.
- :func:`load_connector_whitelist` reads the host-owned whitelist
  (``connectors.yaml`` next to the daemon config). The whitelist is
  default-off: only entries with ``enabled: true`` are mounted.
- :func:`attach_approved_connectors` mounts every approved connector onto
  a Fabric/Body pair at daemon start. A connector whose credentials are
  missing is still attached: each connector's own tools stay registered
  and report their explicit "not configured" error at call time (the
  existing per-connector honest path — nothing here invents a new one).
  A mount failure never takes down the daemon; it is recorded explicitly
  in the report instead of being silently skipped.
- :func:`write_mount_report` persists the last daemon-start report next
  to the config so ``zn connector status`` can show ground truth even
  when the daemon is down.
- Q10: :func:`reload_approved_connectors` hot-reloads the whitelist
  without restarting the daemon. It re-reads ``connectors.yaml``,
  diffs it against the live report, and only mounts newly enabled
  connectors, detaches removed ones, and remounts changed ones. A
  whitelist that fails to load/validate aborts the whole reload (fail
  closed): nothing is detached or mounted and the old report stays
  live. Per-connector mount failures are recorded in the report and
  never affect the other connectors or the daemon.

Raw secrets never belong in ``connectors.yaml``: the loader refuses
credential-shaped values (see :mod:`zn_agent.core.credential_isolation`).
Credential references (``provider:mail`` style) are opaque and allowed;
the secrets themselves resolve from the host credential store at call
time, exactly as each connector already does.
"""

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .config import zn_config_path
from .credential_isolation import check_no_credential_value
from .home import get_zn_home

CONNECTOR_CONFIG_ENV = "ZN_CONNECTORS_CONFIG_PATH"
CONNECTOR_STATUS_ENV = "ZN_CONNECTORS_STATUS_PATH"
CONNECTOR_CONFIG_FILENAME = "connectors.yaml"
CONNECTOR_STATUS_FILENAME = "connectors-status.json"
WHITELIST_VERSION = 1


# ---------------------------------------------------------------------------
# Declarative registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConnectorDescriptor:
    """One R-series connector as the daemon sees it."""

    name: str
    r_series: str
    title: str
    module_name: str
    attach_functions: tuple[str, ...]
    register_function: str | None
    requires_credentials: bool
    planes: tuple[str, ...]


CONNECTOR_REGISTRY: tuple[ConnectorDescriptor, ...] = (
    ConnectorDescriptor(
        name="weather",
        r_series="R1",
        title="Weather (Open-Meteo)",
        module_name="zn_agent.core.open_meteo_connector",
        attach_functions=("attach_open_meteo_tools",),
        register_function=None,
        requires_credentials=False,
        planes=("read",),
    ),
    ConnectorDescriptor(
        name="web_search",
        r_series="R2",
        title="Web search (SearXNG)",
        module_name="zn_agent.core.web_search_connector",
        attach_functions=("attach_web_search_tools",),
        register_function=None,
        requires_credentials=False,
        planes=("read",),
    ),
    ConnectorDescriptor(
        name="rss_feeds",
        r_series="R3",
        title="RSS/Atom feeds",
        module_name="zn_agent.core.rss_feed_connector",
        attach_functions=("attach_rss_tools",),
        register_function=None,
        requires_credentials=False,
        planes=("read", "write"),
    ),
    ConnectorDescriptor(
        name="maps",
        r_series="R4",
        title="Maps (OpenStreetMap)",
        module_name="zn_agent.core.osm_maps_connector",
        attach_functions=("attach_osm_maps_tools",),
        register_function=None,
        requires_credentials=False,
        planes=("read",),
    ),
    ConnectorDescriptor(
        name="calendar",
        r_series="R5",
        title="Calendar (ICS / CalDAV)",
        module_name="zn_agent.core.calendar_connector",
        attach_functions=("attach_calendar_tools",),
        register_function="register_calendar_runtime",
        requires_credentials=False,
        planes=("read", "write"),
    ),
    ConnectorDescriptor(
        name="mail",
        r_series="R6",
        title="Mail (IMAP/SMTP)",
        module_name="zn_agent.core.mail_connector",
        attach_functions=("attach_mail_tools",),
        register_function="register_mail_runtime",
        requires_credentials=True,
        planes=("read", "write"),
    ),
    ConnectorDescriptor(
        name="fx_rates",
        r_series="R7",
        title="FX rates",
        module_name="zn_agent.core.fx_rates_connector",
        attach_functions=("attach_fx_rates_tools",),
        register_function=None,
        requires_credentials=False,
        planes=("read",),
    ),
    ConnectorDescriptor(
        name="doc_artifacts",
        r_series="R8",
        title="Document artifacts",
        module_name="zn_agent.core.doc_artifacts_connector",
        attach_functions=("attach_doc_artifact_tools",),
        register_function="register_doc_artifacts_runtime",
        requires_credentials=False,
        planes=("read", "write"),
    ),
    ConnectorDescriptor(
        name="media_generation",
        r_series="R9",
        title="Media generation",
        module_name="zn_agent.core.media_generation_connector",
        attach_functions=("attach_media_generation_tools",),
        register_function="register_media_generation_runtime",
        requires_credentials=True,
        planes=("write",),
    ),
    ConnectorDescriptor(
        name="messaging",
        r_series="R10",
        title="Messaging",
        module_name="zn_agent.core.messaging_connector",
        attach_functions=("attach_messaging_tools",),
        register_function="register_messaging_runtime",
        requires_credentials=True,
        planes=("read", "write"),
    ),
    ConnectorDescriptor(
        name="device_health",
        r_series="R11",
        title="Device & health data",
        module_name="zn_agent.core.device_health_connector",
        attach_functions=("attach_device_health_tools",),
        register_function=None,
        requires_credentials=False,
        planes=("read",),
    ),
    ConnectorDescriptor(
        name="travel_queries",
        r_series="R12",
        title="Travel & shopping queries",
        module_name="zn_agent.core.travel_shopping_connector",
        attach_functions=("attach_opensky_tools", "attach_openprices_tools"),
        register_function=None,
        requires_credentials=False,
        planes=("read",),
    ),
)

DESCRIPTORS_BY_NAME: dict[str, ConnectorDescriptor] = {
    descriptor.name: descriptor for descriptor in CONNECTOR_REGISTRY
}


# ---------------------------------------------------------------------------
# Paths and whitelist loading
# ---------------------------------------------------------------------------


def connector_config_path(
    *,
    environ: Mapping[str, str] | None = None,
    home: str | Path | None = None,
) -> Path:
    """Resolve the connector whitelist path; it follows the daemon config."""
    env = environ if environ is not None else os.environ
    explicit = str(env.get(CONNECTOR_CONFIG_ENV) or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return zn_config_path(environ=environ, home=home).parent / CONNECTOR_CONFIG_FILENAME


def mount_report_path(
    *,
    environ: Mapping[str, str] | None = None,
    home: str | Path | None = None,
) -> Path:
    """Resolve the daemon mount-report path (next to the whitelist)."""
    env = environ if environ is not None else os.environ
    explicit = str(env.get(CONNECTOR_STATUS_ENV) or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return connector_config_path(environ=environ, home=home).parent / CONNECTOR_STATUS_FILENAME


def load_connector_whitelist(
    path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Load and strictly validate the connector whitelist.

    Returns ``{connector_name: entry_dict}``. A missing file means the
    default: everything off. Unknown connector names, non-mapping
    entries, non-boolean ``enabled`` flags, unknown top-level keys, a
    wrong ``version``, and credential-shaped values are all explicit
    errors — a whitelist typo must never silently change what the
    daemon mounts.
    """
    config_path = Path(path).expanduser() if path is not None else connector_config_path(environ=environ)
    if not config_path.exists():
        return {}
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"connector config must be a mapping: {config_path}")
    unknown_top = set(raw) - {"version", "connectors"}
    if unknown_top:
        raise ValueError(
            "unknown connector config keys: "
            + ", ".join(sorted(unknown_top))
            + f" ({config_path})"
        )
    version = raw.get("version", WHITELIST_VERSION)
    if version != WHITELIST_VERSION:
        raise ValueError(
            f"unsupported connector config version {version!r} "
            f"(expected {WHITELIST_VERSION}): {config_path}"
        )
    entries = raw.get("connectors") or {}
    if not isinstance(entries, dict):
        raise ValueError(f"connector config 'connectors' must be a mapping: {config_path}")
    # Raw secrets must never live in the whitelist; credential references
    # (provider:mail style) are opaque and pass this check.
    check_no_credential_value(entries, where="config:connectors")
    whitelist: dict[str, dict[str, Any]] = {}
    for name, entry in entries.items():
        descriptor = DESCRIPTORS_BY_NAME.get(str(name))
        if descriptor is None:
            raise ValueError(
                f"unknown connector {str(name)!r} in {config_path}; "
                "known: " + ", ".join(d.name for d in CONNECTOR_REGISTRY)
            )
        if not isinstance(entry, dict):
            raise ValueError(
                f"connector {str(name)!r} entry must be a mapping with "
                f"explicit 'enabled: true' ({config_path})"
            )
        enabled = entry.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError(
                f"connector {str(name)!r} 'enabled' must be true/false "
                f"({config_path})"
            )
        whitelist[descriptor.name] = dict(entry)
    return whitelist


# ---------------------------------------------------------------------------
# Mount report
# ---------------------------------------------------------------------------


@dataclass
class ConnectorMountAttempt:
    name: str
    r_series: str
    approved: bool
    mounted: bool
    reason: str
    planes: tuple[str, ...]
    requires_credentials: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "r_series": self.r_series,
            "approved": self.approved,
            "mounted": self.mounted,
            "reason": self.reason,
            "planes": list(self.planes),
            "requires_credentials": self.requires_credentials,
        }


def _detach_quietly(attachment: Any) -> bool:
    """Detach one attachment handle; False when the teardown itself fails.

    A failing detach is reported, never raised: one connector's broken
    teardown must not block the others (floor-guard-safe quiet helper).
    """
    detach = getattr(attachment, "detach", None)
    if not callable(detach):
        return True
    try:
        detach()
    except Exception:
        return False
    return True


@dataclass
class ConnectorMountReport:
    generated_at: str
    config_path: str
    attempts: list[ConnectorMountAttempt] = field(default_factory=list)
    # Attachment handles keyed by connector name (for selective detach on
    # hot reload); never serialized.
    attachments_by_name: dict[str, list[Any]] = field(default_factory=dict, repr=False)
    # The whitelist entry each connector was mounted with (change
    # detection for hot reload); never serialized.
    mounted_config: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)

    @classmethod
    def empty(cls, reason: str) -> "ConnectorMountReport":
        report = cls(
            generated_at=datetime.now(timezone.utc).isoformat(),
            config_path="",
        )
        for descriptor in CONNECTOR_REGISTRY:
            report.attempts.append(
                ConnectorMountAttempt(
                    name=descriptor.name,
                    r_series=descriptor.r_series,
                    approved=False,
                    mounted=False,
                    reason=reason,
                    planes=descriptor.planes,
                    requires_credentials=descriptor.requires_credentials,
                )
            )
        return report

    @property
    def approved_count(self) -> int:
        return sum(1 for attempt in self.attempts if attempt.approved)

    @property
    def mounted_count(self) -> int:
        return sum(1 for attempt in self.attempts if attempt.mounted)

    def detach_all(self) -> None:
        self.detach_connectors(list(self.attachments_by_name))

    def detach_connectors(self, names: list[str]) -> None:
        """Detach (and forget) the named connectors' attachment handles.

        A failing detach never aborts the loop: one connector's broken
        teardown must not block the others.
        """
        for name in names:
            for attachment in self.attachments_by_name.pop(name, []):
                _detach_quietly(attachment)
            self.mounted_config.pop(name, None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "config_path": self.config_path,
            "approved": self.approved_count,
            "mounted": self.mounted_count,
            "connectors": [attempt.to_dict() for attempt in self.attempts],
        }


def write_mount_report(
    report: ConnectorMountReport,
    path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    """Persist the daemon-start mount report; None when nothing was approved.

    The file is a convenience cache for the daemon-down case (``zn
    connector status`` falls back to it). The in-memory report served
    over the ``connector_status`` RPC stays authoritative.
    """
    if report.approved_count == 0:
        return None
    report_path = Path(path).expanduser() if path is not None else mount_report_path(environ=environ)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    tmp_path = report_path.with_name(f".{report_path.name}.tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, report_path)
    return report_path


def read_mount_report(
    path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    """Read the last daemon-start mount report, or None when absent/corrupt.

    A corrupt file is reported as absent: it is only a cache, and a
    corrupt cache must never break observability.
    """
    report_path = Path(path).expanduser() if path is not None else mount_report_path(environ=environ)
    try:
        raw = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


# ---------------------------------------------------------------------------
# Per-connector wiring: config checks + attach logic
# ---------------------------------------------------------------------------


@dataclass
class _WireContext:
    fabric: Any
    body: Any
    executor: Any | None
    credential_store: Any | None
    handles: list[Any] = field(default_factory=list)


def _optional_str(cfg: Mapping[str, Any], key: str) -> str | None:
    value = str(cfg.get(key) or "").strip()
    return value or None


def _check_web_search(cfg: Mapping[str, Any]) -> str | None:
    if "instances" not in cfg:
        return None
    instances = cfg.get("instances")
    if isinstance(instances, str) or not isinstance(instances, (list, tuple)):
        return "web_search.instances must be a list of base URLs"
    if not [item for item in instances if str(item or "").strip()]:
        return "web_search.instances is empty: the attach refuses an empty instance list"
    return None


def _check_calendar(cfg: Mapping[str, Any]) -> str | None:
    if _optional_str(cfg, "ics_path") or cfg.get("caldav"):
        return None
    return (
        "no calendar.ics_path or calendar.caldav section: calendar reads "
        "report unconfigured until one is set"
    )


def _check_mail(cfg: Mapping[str, Any]) -> str | None:
    if cfg.get("account"):
        return None
    return (
        "no mail.account section: mail tools stay registered but report "
        "'no mail account configured'"
    )


def _check_media_generation(cfg: Mapping[str, Any]) -> str | None:
    return (
        "no media provider wired (deploy-time step): media tools report "
        "'not configured'"
    )


def _check_messaging(cfg: Mapping[str, Any]) -> str | None:
    if cfg.get("account"):
        return None
    return (
        "no messaging.account section: messaging tools stay registered but "
        "report 'no messaging account configured'"
    )


_CHECKS: dict[str, Callable[[Mapping[str, Any]], str | None]] = {
    "web_search": _check_web_search,
    "calendar": _check_calendar,
    "mail": _check_mail,
    "media_generation": _check_media_generation,
    "messaging": _check_messaging,
}


def _wire_weather(ctx: _WireContext, cfg: Mapping[str, Any]) -> str:
    from .open_meteo_connector import attach_open_meteo_tools

    ctx.handles.append(attach_open_meteo_tools(ctx.fabric, ctx.body))
    return "attached (geocoding + forecast tools, read-only)"


def _wire_web_search(ctx: _WireContext, cfg: Mapping[str, Any]) -> str:
    from .web_search_connector import DEFAULT_INSTANCES, attach_web_search_tools

    if "instances" not in cfg:
        ctx.handles.append(attach_web_search_tools(ctx.fabric, ctx.body))
        return (
            f"attached ({len(DEFAULT_INSTANCES)} default SearXNG "
            "instance(s), read-only)"
        )
    urls = [str(item).strip() for item in cfg.get("instances") or []]
    urls = [url for url in urls if url]
    ctx.handles.append(
        attach_web_search_tools(ctx.fabric, ctx.body, instances=urls)
    )
    return f"attached ({len(urls)} configured SearXNG instance(s), read-only)"


def _wire_rss_feeds(ctx: _WireContext, cfg: Mapping[str, Any]) -> str:
    from .rss_feed_connector import RssSubscriptionStore, attach_rss_tools

    raw_path = _optional_str(cfg, "store_path")
    store_path = Path(raw_path).expanduser() if raw_path else get_zn_home() / "rss-feeds.json"
    store = RssSubscriptionStore(store_path)
    # No approved_write_tools: subscription writes stay unregistered until
    # the host approves them per tool (R3 contract, unchanged).
    ctx.handles.append(attach_rss_tools(ctx.fabric, ctx.body, store=store))
    return (
        f"attached (store {store_path}; subscription writes unregistered "
        "without per-tool host approval)"
    )


def _wire_maps(ctx: _WireContext, cfg: Mapping[str, Any]) -> str:
    from .osm_maps_connector import attach_osm_maps_tools

    ctx.handles.append(attach_osm_maps_tools(ctx.fabric, ctx.body))
    return "attached (Nominatim + Overpass tools, read-only)"


def _wire_calendar(ctx: _WireContext, cfg: Mapping[str, Any]) -> str:
    from .calendar_connector import (
        CalDavConfig,
        attach_calendar_tools,
        register_calendar_runtime,
    )

    ics_path = _optional_str(cfg, "ics_path")
    caldav_cfg = cfg.get("caldav")
    caldav = None
    if caldav_cfg:
        if not isinstance(caldav_cfg, Mapping):
            raise ValueError("calendar.caldav must be a mapping")
        caldav_cfg = dict(caldav_cfg)
        if "password" in caldav_cfg:
            # Raw secrets never live in the whitelist; CalDAV passwords are
            # a deploy-time credential step, not a YAML value.
            raise ValueError(
                "calendar.caldav.password is not allowed in connectors.yaml: "
                "CalDAV credentials are wired at deploy time"
            )
        caldav = CalDavConfig(**caldav_cfg)
    ctx.handles.append(
        attach_calendar_tools(ctx.fabric, ctx.body, ics_path=ics_path, caldav=caldav)
    )
    if ctx.executor is not None:
        register_calendar_runtime(ctx.executor, ics_path=ics_path, caldav=caldav)
    if ics_path:
        return f"attached (ICS {ics_path})"
    if caldav is not None:
        return "attached (CalDAV; credentials wire at deploy time)"
    return "attached"


def _wire_mail(ctx: _WireContext, cfg: Mapping[str, Any]) -> str:
    from .mail_connector import (
        MailAccountConfig,
        attach_mail_tools,
        register_mail_runtime,
    )

    account_cfg = cfg.get("account")
    account = MailAccountConfig(**dict(account_cfg)) if account_cfg else None
    ctx.handles.append(
        attach_mail_tools(
            ctx.fabric,
            ctx.body,
            config=account,
            credential_store=ctx.credential_store,
        )
    )
    if ctx.executor is not None:
        register_mail_runtime(
            ctx.executor, config=account, credential_store=ctx.credential_store
        )
    if account is None:
        return "attached"
    return "attached (credentials resolve from the credential store at call time)"


def _wire_fx_rates(ctx: _WireContext, cfg: Mapping[str, Any]) -> str:
    from .fx_rates_connector import attach_fx_rates_tools

    ctx.handles.append(attach_fx_rates_tools(ctx.fabric, ctx.body))
    return "attached (latest/historical/convert tools, read-only)"


def _wire_doc_artifacts(ctx: _WireContext, cfg: Mapping[str, Any]) -> str:
    from .doc_artifacts_connector import (
        attach_doc_artifact_tools,
        register_doc_artifacts_runtime,
    )

    output_dir = _optional_str(cfg, "output_dir")
    ctx.handles.append(
        attach_doc_artifact_tools(ctx.fabric, ctx.body, output_dir=output_dir)
    )
    if ctx.executor is not None:
        register_doc_artifacts_runtime(ctx.executor, output_dir=output_dir)
    return "attached (document generation tools, approval-gated writes)"


def _wire_media_generation(ctx: _WireContext, cfg: Mapping[str, Any]) -> str:
    from .media_generation_connector import (
        attach_media_generation_tools,
        register_media_generation_runtime,
    )

    output_dir = _optional_str(cfg, "output_dir")
    # provider=None: the connector's own honest path — tools stay
    # registered and report "not configured" until a provider is wired at
    # deploy time. R13 does not invent a provider.
    ctx.handles.append(
        attach_media_generation_tools(
            ctx.fabric, ctx.body, provider=None, output_dir=output_dir
        )
    )
    if ctx.executor is not None:
        register_media_generation_runtime(ctx.executor, output_dir=output_dir)
    return "attached"


def _wire_messaging(ctx: _WireContext, cfg: Mapping[str, Any]) -> str:
    from .messaging_connector import (
        MessagingAccountConfig,
        attach_messaging_tools,
        register_messaging_runtime,
    )

    account_cfg = cfg.get("account")
    account = MessagingAccountConfig(**dict(account_cfg)) if account_cfg else None
    ctx.handles.append(
        attach_messaging_tools(
            ctx.fabric,
            ctx.body,
            config=account,
            credential_store=ctx.credential_store,
        )
    )
    if ctx.executor is not None:
        register_messaging_runtime(
            ctx.executor, config=account, credential_store=ctx.credential_store
        )
    if account is None:
        return "attached"
    return "attached (credentials resolve from the credential store at call time)"


def _wire_device_health(ctx: _WireContext, cfg: Mapping[str, Any]) -> str:
    from .device_health_connector import attach_device_health_tools

    health_path = _optional_str(cfg, "health_path")
    ctx.handles.append(
        attach_device_health_tools(ctx.fabric, ctx.body, health_path=health_path)
    )
    if health_path:
        return f"attached (default export {health_path}, read-only local)"
    return "attached (no default health_path: pass path per call, read-only local)"


def _wire_travel_queries(ctx: _WireContext, cfg: Mapping[str, Any]) -> str:
    from .travel_shopping_connector import (
        attach_openprices_tools,
        attach_opensky_tools,
    )

    ctx.handles.append(attach_opensky_tools(ctx.fabric, ctx.body))
    ctx.handles.append(attach_openprices_tools(ctx.fabric, ctx.body))
    return "attached (OpenSky flights + Open Prices tools, read-only query-only)"


_WIRES: dict[str, Callable[[_WireContext, Mapping[str, Any]], str]] = {
    "weather": _wire_weather,
    "web_search": _wire_web_search,
    "rss_feeds": _wire_rss_feeds,
    "maps": _wire_maps,
    "calendar": _wire_calendar,
    "mail": _wire_mail,
    "fx_rates": _wire_fx_rates,
    "doc_artifacts": _wire_doc_artifacts,
    "media_generation": _wire_media_generation,
    "messaging": _wire_messaging,
    "device_health": _wire_device_health,
    "travel_queries": _wire_travel_queries,
}


# ---------------------------------------------------------------------------
# Mount loop
# ---------------------------------------------------------------------------


def _not_approved_attempt(descriptor: ConnectorDescriptor) -> ConnectorMountAttempt:
    return ConnectorMountAttempt(
        name=descriptor.name,
        r_series=descriptor.r_series,
        approved=False,
        mounted=False,
        reason="not approved in connectors.yaml (default off)",
        planes=descriptor.planes,
        requires_credentials=descriptor.requires_credentials,
    )


def _mount_one(
    descriptor: ConnectorDescriptor,
    cfg: Mapping[str, Any],
    ctx: _WireContext,
    report: ConnectorMountReport,
) -> None:
    """Wire one approved connector; failures are recorded, never raised.

    New attachment handles are attributed to the connector by name so a
    later hot reload can detach exactly this connector.
    """
    check = _CHECKS.get(descriptor.name)
    readiness = check(cfg) if check is not None else None
    wire = _WIRES[descriptor.name]
    before = len(ctx.handles)
    try:
        note = wire(ctx, cfg)
    except Exception as exc:
        # Recorded in the mount report; never silently swallowed.
        report.attempts.append(
            ConnectorMountAttempt(
                name=descriptor.name,
                r_series=descriptor.r_series,
                approved=True,
                mounted=False,
                reason=f"{type(exc).__name__}: {exc}",
                planes=descriptor.planes,
                requires_credentials=descriptor.requires_credentials,
            )
        )
        return
    if readiness:
        note = f"{note}; {readiness}"
    report.attachments_by_name.setdefault(descriptor.name, []).extend(
        ctx.handles[before:]
    )
    report.mounted_config[descriptor.name] = dict(cfg)
    report.attempts.append(
        ConnectorMountAttempt(
            name=descriptor.name,
            r_series=descriptor.r_series,
            approved=True,
            mounted=True,
            reason=note,
            planes=descriptor.planes,
            requires_credentials=descriptor.requires_credentials,
        )
    )


def attach_approved_connectors(
    fabric: Any,
    body: Any,
    *,
    whitelist: Mapping[str, Mapping[str, Any]] | None = None,
    executor: Any | None = None,
    credential_store: Any | None = None,
    config_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ConnectorMountReport:
    """Mount every whitelisted connector onto the Fabric/Body pair.

    Only entries with ``enabled: true`` are mounted (default off). A
    connector whose static check reports "not configured" is still
    attached — its tools stay registered and report the connector's own
    explicit "not configured" error at call time. A mount failure is
    recorded in the report with its exception; it never propagates, so
    one bad connector cannot take down the daemon.
    """
    if whitelist is None:
        resolved_path = (
            Path(config_path).expanduser()
            if config_path is not None
            else connector_config_path(environ=environ)
        )
        loaded = load_connector_whitelist(resolved_path, environ=environ)
        config_path_str = str(resolved_path)
    else:
        loaded = {name: dict(entry) for name, entry in whitelist.items()}
        config_path_str = str(config_path) if config_path is not None else ""
    ctx = _WireContext(
        fabric=fabric,
        body=body,
        executor=executor,
        credential_store=credential_store,
    )
    report = ConnectorMountReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        config_path=config_path_str,
    )
    for descriptor in CONNECTOR_REGISTRY:
        entry = loaded.get(descriptor.name)
        approved = isinstance(entry, Mapping) and entry.get("enabled") is True
        if not approved:
            report.attempts.append(_not_approved_attempt(descriptor))
            continue
        cfg: Mapping[str, Any] = entry if isinstance(entry, Mapping) else {}
        _mount_one(descriptor, cfg, ctx, report)
    return report


def reload_approved_connectors(
    report: ConnectorMountReport,
    fabric: Any,
    body: Any,
    *,
    executor: Any | None = None,
    credential_store: Any | None = None,
    config_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ConnectorMountReport:
    """Hot-reload the connector whitelist: re-read, diff, apply only the delta.

    Only connectors whose approval or config entry changed are touched:
    newly enabled connectors are mounted, removed ones are detached, and
    changed ones are detached and remounted; untouched connectors keep
    their live handles. A single connector's mount failure is recorded
    in the returned report and never affects the others or the daemon.

    Raises :class:`ValueError` when the whitelist fails to load or
    validate — in that case nothing is detached or mounted (fail closed)
    and the caller keeps the old report and the existing mounts.
    """
    resolved_path = (
        Path(config_path).expanduser()
        if config_path is not None
        else connector_config_path(environ=environ)
    )
    loaded = load_connector_whitelist(resolved_path, environ=environ)
    ctx = _WireContext(
        fabric=fabric,
        body=body,
        executor=executor,
        credential_store=credential_store,
    )
    new_report = ConnectorMountReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        config_path=str(resolved_path),
    )
    old_attempts = {attempt.name: attempt for attempt in report.attempts}
    for descriptor in CONNECTOR_REGISTRY:
        entry = loaded.get(descriptor.name)
        approved = isinstance(entry, Mapping) and entry.get("enabled") is True
        old_attempt = old_attempts.get(descriptor.name)
        was_mounted = old_attempt is not None and old_attempt.mounted
        old_cfg = report.mounted_config.get(descriptor.name)
        if (
            approved
            and was_mounted
            and old_cfg is not None
            and isinstance(entry, Mapping)
            and dict(entry) == old_cfg
        ):
            # Unchanged: carry the live attempt, handles, and config over.
            new_report.attempts.append(old_attempt)
            handles = report.attachments_by_name.get(descriptor.name)
            if handles:
                new_report.attachments_by_name[descriptor.name] = handles
            new_report.mounted_config[descriptor.name] = old_cfg
            continue
        if was_mounted:
            # Removed or changed: detach the old handles first, so a
            # failed remount never leaves both the old and the new live.
            report.detach_connectors([descriptor.name])
        if not approved:
            new_report.attempts.append(_not_approved_attempt(descriptor))
            continue
        cfg: Mapping[str, Any] = dict(entry) if isinstance(entry, Mapping) else {}
        _mount_one(descriptor, cfg, ctx, new_report)
    return new_report


# ---------------------------------------------------------------------------
# Observability: registry listing + status evaluation
# ---------------------------------------------------------------------------


def describe_registry() -> list[dict[str, Any]]:
    """Describe every known connector (for ``zn connector list``)."""
    return [
        {
            "name": descriptor.name,
            "r_series": descriptor.r_series,
            "title": descriptor.title,
            "module": descriptor.module_name,
            "attach_functions": list(descriptor.attach_functions),
            "register_function": descriptor.register_function,
            "requires_credentials": descriptor.requires_credentials,
            "planes": list(descriptor.planes),
        }
        for descriptor in CONNECTOR_REGISTRY
    ]


def evaluate_connector_status(
    *,
    whitelist: Mapping[str, Mapping[str, Any]] | None = None,
    report: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate connector status without needing a running daemon.

    Merges the whitelist (what *would* mount) with the last daemon-start
    mount report when one exists (what *did* mount). Used by ``zn
    connector status`` when the daemon is unreachable.
    """
    if whitelist is None:
        whitelist = load_connector_whitelist(environ=environ)
    if report is None:
        report = read_mount_report(environ=environ)
    last_mount: dict[str, dict[str, Any]] = {}
    generated_at: str | None = None
    if isinstance(report, Mapping):
        generated_at = report.get("generated_at") if isinstance(report.get("generated_at"), str) else None
        connectors = report.get("connectors")
        if isinstance(connectors, list):
            for item in connectors:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    last_mount[str(item["name"])] = {
                        "mounted": item.get("mounted"),
                        "reason": item.get("reason"),
                    }
    status: list[dict[str, Any]] = []
    for descriptor in CONNECTOR_REGISTRY:
        entry = whitelist.get(descriptor.name)
        approved = isinstance(entry, Mapping) and entry.get("enabled") is True
        cfg: Mapping[str, Any] = entry if isinstance(entry, Mapping) else {}
        check = _CHECKS.get(descriptor.name)
        readiness = check(cfg) if (approved and check is not None) else None
        mount = last_mount.get(descriptor.name)
        status.append(
            {
                "name": descriptor.name,
                "r_series": descriptor.r_series,
                "title": descriptor.title,
                "planes": list(descriptor.planes),
                "requires_credentials": descriptor.requires_credentials,
                "approved": approved,
                "readiness": readiness,
                "last_mount": mount,
                "last_mount_at": generated_at,
            }
        )
    return status
