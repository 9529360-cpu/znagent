from __future__ import annotations

"""Privacy-safe Windows companion markers for the existing resident Life loop.

This module intentionally does not create events, Work, notifications, polling
threads or a second Situation store.  It turns the already-bounded current
DeviceCapabilityGraph observations into a tiny durable marker set so the native
Life loop can notice meaningful environment changes between pulses.
"""

from typing import Any, Mapping


_MARKER_ORDER = ("session", "power", "network", "display", "foreground")


def sense_windows_companion_markers(resident: Any) -> tuple[str, ...]:
    """Read fresh bounded companion state, returning no marker on unavailable graphs."""

    graph = getattr(resident, "device_capabilities", None)
    if graph is None:
        return ()

    markers: list[str] = []

    try:
        companion = graph.companion_context()
    except Exception:
        companion = None
    if companion is not None:
        session = companion.session
        markers.append(
            _marker(
                "session",
                {
                    "supported": bool(session.platform_supported),
                    "process_session": session.process_session_id,
                    "active_console": session.active_console_session_id,
                    "attached": session.attached_to_active_console,
                    "remote": session.remote_session,
                    "input_desktop": session.input_desktop_openable,
                },
            )
        )
        power = companion.power
        markers.append(
            _marker(
                "power",
                {
                    "supported": bool(power.platform_supported),
                    "ac": power.ac_status,
                    "battery_present": power.battery_present,
                    # Percentage/lifetime intentionally omitted so normal battery
                    # drain does not become a Situation change every few pulses.
                    "charging": power.battery_charging,
                    "saver": power.battery_saver,
                },
            )
        )
        network = companion.network
        markers.append(
            _marker(
                "network",
                {
                    "supported": bool(network.platform_supported),
                    # Interface counts/names are intentionally omitted. Virtual
                    # adapters churn; Life only needs meaningful availability.
                    "non_loopback": network.has_non_loopback_address,
                    "ipv4": network.has_ipv4,
                    "ipv6": network.has_ipv6,
                },
            )
        )

    try:
        display = graph.display_context()
    except Exception:
        display = None
    if display is not None:
        markers.append(
            _marker(
                "display",
                {
                    "supported": bool(display.platform_supported),
                    "monitors": display.monitor_count,
                    "enumerated": display.enumerated_monitor_count,
                    "primary_count": display.primary_monitor_count,
                    "virtual_left": display.virtual_left,
                    "virtual_top": display.virtual_top,
                    "virtual_width": display.virtual_width,
                    "virtual_height": display.virtual_height,
                    "truncated": bool(display.truncated),
                },
            )
        )

    foreground_reader = getattr(graph, "foreground_companion_context", None)
    if callable(foreground_reader):
        try:
            foreground = foreground_reader()
        except Exception:
            foreground = None
        if foreground is not None:
            monitor = foreground.monitor
            markers.append(
                _marker(
                    "foreground",
                    {
                        "supported": bool(foreground.platform_supported),
                        "available": bool(foreground.available),
                        "pid": foreground.process_id,
                        "process": foreground.process_name,
                        "hwnd": foreground.window_handle,
                        "title_chars": foreground.title_chars,
                        "title_sha256": foreground.title_sha256,
                        "class_chars": foreground.class_name_chars,
                        "class_sha256": foreground.class_name_sha256,
                        "monitor": (
                            None
                            if monitor is None
                            else (
                                monitor.left,
                                monitor.top,
                                monitor.right,
                                monitor.bottom,
                                monitor.primary,
                            )
                        ),
                    },
                )
            )

    by_kind = {_marker_kind(marker): marker for marker in markers}
    return tuple(by_kind[kind] for kind in _MARKER_ORDER if kind in by_kind)


def describe_windows_companion_changes(
    previous: tuple[str, ...],
    current: tuple[str, ...],
) -> tuple[str, ...]:
    """Describe only bounded material categories; never echo hashed/raw context."""

    old = {_marker_kind(marker): marker for marker in previous if _marker_kind(marker)}
    new = {_marker_kind(marker): marker for marker in current if _marker_kind(marker)}
    if not old and not new:
        return ()
    if not old and new:
        return ("Windows companion context acquired",)

    changes: list[str] = []
    labels = {
        "session": "Windows session/input context changed",
        "power": "Windows power context changed",
        "network": "Windows network availability changed",
        "display": "Windows display topology changed",
        "foreground": "Windows foreground context changed",
    }
    for kind in _MARKER_ORDER:
        if old.get(kind) != new.get(kind):
            changes.append(labels[kind])
    return tuple(changes)


def _marker(kind: str, values: Mapping[str, Any]) -> str:
    rows = [f"{key}={_scalar(values[key])}" for key in sorted(values)]
    return f"{kind}:" + "|".join(rows)


def _marker_kind(marker: str) -> str:
    text = str(marker or "")
    kind, separator, _ = text.partition(":")
    if not separator:
        return ""
    return kind if kind in _MARKER_ORDER else ""


def _scalar(value: Any) -> str:
    if value is None:
        return "?"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, tuple):
        return ",".join(_scalar(item) for item in value)
    text = str(value).strip().replace("|", "_").replace("=", "_")
    return text[:260]
