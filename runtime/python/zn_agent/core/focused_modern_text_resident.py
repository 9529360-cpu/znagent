from __future__ import annotations

"""Resident ownership for read-only current text state on modern UIA Edit controls."""

from .automation_text_state_sense import NativeFocusedAutomationTextSense
from .focused_text_entry_resident import FocusedTextEntryResidentRuntime


class FocusedModernTextResidentRuntime(FocusedTextEntryResidentRuntime):
    """Own a privacy-safe modern text-state Sense without widening mutation.

    The inherited ``keyboard_text`` competence remains limited to already-focused
    native Win32 Edit controls. ``automation_text_state`` is read-only evidence
    for a focused writable UIA Edit and is intentionally not consulted as input
    authority by the existing mutation lifecycle.
    """

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.automation_text_state = NativeFocusedAutomationTextSense()
