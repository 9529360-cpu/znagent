from __future__ import annotations

"""Windows internal-display brightness through the native WMI monitor provider."""

import math
import platform
import time
from dataclasses import dataclass
from typing import Any


class WindowsBrightnessError(RuntimeError):
    """Base error for bounded Windows brightness access."""


class WindowsBrightnessUnavailable(WindowsBrightnessError):
    """Raised when no unique active WMI brightness target exists."""


class WindowsBrightnessDispatchUncertain(WindowsBrightnessError):
    """Raised after WMI dispatch when the outside-world effect cannot be proven."""


_STABLE_WINDOW_SECONDS = 0.25
_VERIFY_TIMEOUT_SECONDS = 1.5
_POLL_INTERVAL_SECONDS = 0.05


@dataclass(frozen=True, slots=True)
class WindowsBrightnessObservation:
    instance_name: str
    level_percent: float


def validate_brightness_percent(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("brightness percent must be a finite number from 0 to 100")
    try:
        level = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("brightness percent must be a finite number from 0 to 100") from exc
    if (
        not math.isfinite(level)
        or level < 0.0
        or level > 100.0
        or not level.is_integer()
    ):
        raise ValueError("brightness percent must be an integer from 0 to 100")
    return level


def read_active_brightness() -> WindowsBrightnessObservation:
    service = _brightness_service()
    rows = tuple(
        row
        for row in _query(
            service,
            "SELECT Active, CurrentBrightness, InstanceName FROM WmiMonitorBrightness",
        )
        if bool(_wmi_property_value(row, "Active"))
    )
    if len(rows) != 1:
        raise WindowsBrightnessUnavailable(
            "Windows brightness requires exactly one active WMI monitor target; "
            f"observed {len(rows)}"
        )
    row = rows[0]
    instance_name = str(_wmi_property_value(row, "InstanceName") or "").strip()
    if not instance_name:
        raise WindowsBrightnessError("active WMI brightness target has no InstanceName")
    level = validate_brightness_percent(_wmi_property_value(row, "CurrentBrightness"))
    return WindowsBrightnessObservation(instance_name, level)


def set_active_brightness(
    level_percent: Any,
    *,
    expected_instance_name: str | None = None,
) -> WindowsBrightnessObservation:
    requested = validate_brightness_percent(level_percent)
    before = read_active_brightness()
    expected = str(expected_instance_name or "").strip()
    if expected and before.instance_name != expected:
        raise WindowsBrightnessUnavailable(
            "active WMI brightness target changed before dispatch"
        )
    service = _brightness_service()
    methods = tuple(
        row
        for row in _query(
            service,
            "SELECT InstanceName FROM WmiMonitorBrightnessMethods",
        )
        if str(_wmi_property_value(row, "InstanceName") or "").strip()
        == before.instance_name
    )
    if len(methods) != 1:
        raise WindowsBrightnessUnavailable(
            "Windows brightness method binding is not unique for the active monitor"
        )
    target = methods[0]
    relpath = str(_wmi_system_property_value(target, "__RELPATH") or "").strip()
    if not relpath:
        raise WindowsBrightnessError("active WMI brightness method has no __RELPATH")

    try:
        method = target.Methods_.Item("WmiSetBrightness")
        parameters = method.InParameters.SpawnInstance_()
        parameters.Properties_.Item("Timeout").Value = 0
        parameters.Properties_.Item("Brightness").Value = int(requested)
    except Exception as exc:
        raise WindowsBrightnessError(
            f"WmiSetBrightness parameters could not be prepared: {type(exc).__name__}: {exc}"
        ) from exc

    try:
        service.ExecMethod(relpath, "WmiSetBrightness", parameters)
    except Exception as exc:
        raise WindowsBrightnessDispatchUncertain(
            "WmiSetBrightness dispatch did not return a trustworthy result: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    return _wait_for_stable_brightness(
        before.instance_name,
        requested,
    )


def _wait_for_stable_brightness(
    expected_instance_name: str,
    requested_level: float,
) -> WindowsBrightnessObservation:
    deadline = time.monotonic() + _VERIFY_TIMEOUT_SECONDS
    matching_since: float | None = None
    last_observed: WindowsBrightnessObservation | None = None
    last_error: Exception | None = None

    while True:
        now = time.monotonic()
        try:
            observed = read_active_brightness()
        except WindowsBrightnessError as exc:
            last_error = exc
            observed = None
        if observed is not None:
            last_observed = observed
            if observed.instance_name != expected_instance_name:
                raise WindowsBrightnessDispatchUncertain(
                    "active WMI brightness target changed after dispatch"
                )
            if abs(observed.level_percent - requested_level) <= 0.5:
                if matching_since is None:
                    matching_since = now
                elif now - matching_since >= _STABLE_WINDOW_SECONDS:
                    return observed
            else:
                matching_since = None

        if now >= deadline:
            if last_observed is not None:
                if (
                    abs(last_observed.level_percent - requested_level) <= 0.5
                    and matching_since is not None
                ):
                    raise WindowsBrightnessDispatchUncertain(
                        "requested brightness was observed but did not remain stable long enough"
                    )
                return last_observed
            detail = (
                f": {type(last_error).__name__}: {last_error}"
                if last_error is not None
                else ""
            )
            raise WindowsBrightnessDispatchUncertain(
                "brightness dispatch completed but no fresh WMI readback was available"
                + detail
            )
        time.sleep(min(_POLL_INTERVAL_SECONDS, max(0.0, deadline - now)))


def _query(service: Any, statement: str) -> tuple[Any, ...]:
    try:
        return tuple(service.ExecQuery(statement))
    except Exception as exc:
        raise WindowsBrightnessError(
            f"Windows WMI brightness query failed: {type(exc).__name__}"
        ) from exc


def _brightness_service():
    if platform.system() != "Windows":
        raise WindowsBrightnessUnavailable(
            "Windows brightness is unavailable on the current platform"
        )
    try:
        from comtypes.client import CoGetObject

        return CoGetObject(r"winmgmts:root/wmi", dynamic=True)
    except Exception as exc:
        raise WindowsBrightnessUnavailable(
            f"Windows WMI brightness provider is unavailable: {type(exc).__name__}"
        ) from exc


def _wmi_property_value(row: Any, name: str) -> Any:
    try:
        for prop in row.Properties_:
            if str(getattr(prop, "Name", "") or "").casefold() == name.casefold():
                return getattr(prop, "Value", None)
    except Exception as exc:
        raise WindowsBrightnessError(
            f"WMI brightness property {name} could not be read"
        ) from exc
    return None


def _wmi_system_property_value(row: Any, name: str) -> Any:
    try:
        for prop in row.SystemProperties_:
            if str(getattr(prop, "Name", "") or "").casefold() == name.casefold():
                return getattr(prop, "Value", None)
    except Exception as exc:
        raise WindowsBrightnessError(
            f"WMI brightness system property {name} could not be read"
        ) from exc
    return None
