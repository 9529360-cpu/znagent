from __future__ import annotations

"""Resident checkpoint seam for the ZN-owned Telegram adapter.

Telegram's Bot API offset is transport state, not cognition. This tiny subclass
lets the resident channel supervisor persist and restore that offset without
pushing database ownership into the Telegram transport itself.
"""

from typing import Any, Mapping

from .telegram_channel import TelegramBotApiChannel


class ResidentTelegramBotApiChannel(TelegramBotApiChannel):
    def checkpoint(self) -> dict[str, Any]:
        return {"offset": int(self.offset)}

    def restore_checkpoint(self, checkpoint: Mapping[str, Any] | None) -> None:
        if not isinstance(checkpoint, Mapping):
            return
        try:
            offset = int(checkpoint.get("offset") or 0)
        except (TypeError, ValueError):
            return
        if offset > self._offset:
            self._offset = offset
