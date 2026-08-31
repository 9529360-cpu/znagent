from __future__ import annotations

"""Resident recovery ownership for non-replayable interactive terminal input."""

from .action import NativeActionIntent
from .browser_observed_result_recovery_resident import (
    BrowserObservedResultRecoveryResidentRuntime,
)


class TerminalInputRecoveryResidentRuntime(BrowserObservedResultRecoveryResidentRuntime):
    """Classify interactive terminal writes as guarded side effects.

    ``SideEffectAwareBody`` commits a pre-dispatch attempt for stdin writes. The
    resident must classify the same action kinds as guarded too; otherwise a
    restart would turn Body's ``side_effect_uncertain`` result into an ordinary
    action failure instead of the explicit replay-blocking recovery lifecycle.
    """

    _TERMINAL_INPUT_KINDS = frozenset(
        {"terminal_input", "terminal_write", "command_input"}
    )

    @staticmethod
    def _generic_guarded_side_effect(intent: NativeActionIntent) -> bool:
        kind = str(intent.kind or "").strip().lower()
        return bool(
            kind in TerminalInputRecoveryResidentRuntime._TERMINAL_INPUT_KINDS
            or BrowserObservedResultRecoveryResidentRuntime._generic_guarded_side_effect(intent)
        )
