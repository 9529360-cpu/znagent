from __future__ import annotations

"""Resident composition with durable health observation.

Health state is diagnostic evidence for the same long-lived Resident. It does not
create a separate maintenance subject, repair workflow, repository authority, or
publication path.
"""

import hashlib
from typing import Any

from .browser_work_resident import BrowserWorkResidentRuntime
from .cognitive_failure import classify_cognitive_failure
from .foreground_window_sense import ForegroundWindowObservation
from .health_observation import ResidentHealthJournal
from .models import ModelRoute


class HealthAwareResidentRuntime(BrowserWorkResidentRuntime):
    """Resident composition with durable self-health inspection."""

    _FOREGROUND_WINDOW_HEALTH_ORGAN = "sense:foreground_window"
    _KNOWN_BODY_ACTION_KINDS = frozenset(
        {
            "sense",
            "inspect_path",
            "path",
            "read_text",
            "read_file",
            "write_text",
            "write_file",
            "list_directory",
            "list_dir",
            "process_state",
            "process",
            "pointer_state",
            "pointer_move",
            "pointer_click",
            "git_state",
            "git",
            "git_diff",
            "command",
            "terminal",
            "shell",
            "terminal_poll",
            "command_poll",
            "terminal_stop",
            "command_stop",
            "terminal_input",
            "terminal_write",
            "command_input",
            "terminal_resize",
            "command_resize",
            "browser_navigate",
            "browser_observe",
            "browser_close",
        }
    )

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.health = ResidentHealthJournal(self.store)
        self._install_cognitive_resource_health_observer()
        self._install_body_dispatch_health_observer()

    def status(self) -> dict[str, Any]:
        data = super().status()
        data["resident_health"] = self.health.snapshot()
        return data

    def _install_cognitive_resource_health_observer(self) -> None:
        """Bind provider observation and routing evidence after health exists."""

        observer = self._observe_cognitive_resource_health
        setattr(self.kernel, "resource_health_observer", observer)
        factory = getattr(self.kernel, "worker_factory", None)
        setter = getattr(factory, "set_health_observer", None)
        if callable(setter):
            try:
                setter(observer)
            except Exception:
                pass

        resolver = self._resolve_cognitive_resource_health
        setattr(self.kernel, "resource_health_resolver", resolver)
        router = getattr(self.kernel, "router", None)
        route_setter = getattr(router, "set_health_resolver", None)
        if callable(route_setter):
            try:
                route_setter(resolver)
            except Exception:
                pass

    def _observe_cognitive_resource_health(
        self,
        route: ModelRoute,
        error: BaseException | None,
    ) -> None:
        organ = self._cognitive_resource_health_organ(route)
        if error is None:
            self.health.record_success(organ)
            return

        disposition = classify_cognitive_failure(error)
        if disposition is not None and not disposition.affects_route_health:
            # A provider can reject this exact request while remaining a healthy
            # route. Do not let request pressure/policy/input poison the durable
            # circuit used by ModelRouter for later independent cognition.
            return

        self.health.record_failure(
            organ,
            error,
            failure_class=(
                disposition.failure_class
                if disposition is not None
                else None
            ),
        )

    def _resolve_cognitive_resource_health(self, route: ModelRoute) -> dict[str, Any] | None:
        """Return resident-owned health/runtime evidence for Router eligibility."""

        durable = self.health.get(self._cognitive_resource_health_organ(route))
        discovery = getattr(self, "local_inference", None)
        route_health = getattr(discovery, "route_health", None)
        dynamic = None
        if callable(route_health):
            try:
                dynamic = route_health(route)
            except Exception:
                dynamic = None
        if not isinstance(dynamic, dict):
            return durable
        if not isinstance(durable, dict):
            return dict(dynamic)
        return {**durable, **dynamic}

    @staticmethod
    def _cognitive_resource_health_organ(route: ModelRoute) -> str:
        """Use a stable privacy-safe route identity without persisting model text."""

        raw_provider = str(route.provider or "unknown").strip().lower() or "unknown"
        provider = "".join(
            char if char.isalnum() else "-" for char in raw_provider
        ).strip("-")[:32] or "unknown"
        digest = hashlib.sha256()
        digest.update(b"zn-cognitive-health-route-v1\x00")
        digest.update(raw_provider.encode("utf-8", errors="replace"))
        digest.update(b"\x00")
        digest.update(str(route.route_id or "").encode("utf-8", errors="replace"))
        return f"cognition:{provider}:{digest.hexdigest()[:16]}"

    def _install_body_dispatch_health_observer(self) -> None:
        """Observe real Body dispatch exceptions before NativeBody flattens them."""

        body = getattr(self, "body", None)
        dispatch = getattr(body, "_dispatch", None)
        if body is None or not callable(dispatch):
            return
        if bool(getattr(body, "_zn_health_dispatch_observer_installed", False)):
            return

        def observed_dispatch(action, started):
            organ = self._body_health_organ(getattr(action, "kind", ""))
            try:
                result = dispatch(action, started)
            except Exception as exc:
                try:
                    self.health.record_failure(organ, exc)
                except Exception:
                    pass
                raise

            if bool(getattr(result, "success", False)):
                try:
                    self.health.record_success(organ)
                except Exception:
                    pass
            return result

        setattr(body, "_dispatch", observed_dispatch)
        setattr(body, "_zn_health_dispatch_observer_installed", True)

    @classmethod
    def _body_health_organ(cls, kind: str) -> str:
        """Keep known Body kinds readable and arbitrary caller strings private."""

        normalized = str(kind or "").strip().lower()
        if normalized in cls._KNOWN_BODY_ACTION_KINDS:
            return f"body:{normalized}"
        digest = hashlib.sha256()
        digest.update(b"zn-body-health-kind-v1\x00")
        digest.update(normalized.encode("utf-8", errors="replace"))
        return f"body:action-{digest.hexdigest()[:16]}"

    def _probe_foreground_window(
        self,
    ) -> tuple[ForegroundWindowObservation | None, str | None]:
        """Observe the active foreground-window Sense at its real call boundary."""
        sense = getattr(self, "foreground_window", None)
        if sense is None or not callable(getattr(sense, "probe", None)):
            return None, "resident-owned foreground window Sense is unavailable"
        try:
            observed = sense.probe()
        except Exception as exc:
            try:
                self.health.record_failure(self._FOREGROUND_WINDOW_HEALTH_ORGAN, exc)
            except Exception:
                pass
            return None, f"{type(exc).__name__}: {exc}"

        try:
            self.health.record_success(self._FOREGROUND_WINDOW_HEALTH_ORGAN)
        except Exception:
            pass
        return observed, None
