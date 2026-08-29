from __future__ import annotations

"""Read-only resident ownership for self-maintenance health evidence.

This layer does not repair source, grant maintenance authority, or mutate a
running installation. It makes the already durable health/task evidence part of
the formal resident subject so the existing status control surface can inspect
what ZN has observed about itself across restarts.
"""

from typing import Any

from .browser_work_resident import BrowserWorkResidentRuntime
from .health_observation import ResidentHealthJournal


class HealthAwareResidentRuntime(BrowserWorkResidentRuntime):
    """Final resident composition with durable self-health inspection."""

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.health = ResidentHealthJournal(self.store)

    def status(self) -> dict[str, Any]:
        data = super().status()
        data["resident_health"] = self.health.snapshot()
        data["maintenance_tasks"] = self.health.maintenance_tasks()
        return data
