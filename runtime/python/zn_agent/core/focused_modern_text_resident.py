from __future__ import annotations

"""Resident ownership for modern focused text state and managed web browsing."""

from .automation_text_state_sense import NativeFocusedAutomationTextSense
from .focused_text_entry_resident import FocusedTextEntryResidentRuntime
from .managed_browser import PlaywrightManagedBrowser
from .side_effect_body import SideEffectAwareBody


class FocusedModernTextResidentRuntime(FocusedTextEntryResidentRuntime):
    """Own modern read-only text state plus lazy managed external resources.

    The inherited ``keyboard_text`` competence remains limited to already-focused
    native Win32 Edit controls. ``automation_text_state`` is read-only evidence
    for a focused writable UIA Edit and is intentionally not consulted as input
    authority by the existing mutation lifecycle.

    ``managed_browser`` is resident-owned but lazy: constructing or booting ZN
    does not start Chromium and does not require Playwright to be installed.
    Browser engines remain replaceable resources behind ZN-owned browser
    session/action/authority/effect contracts.

    The final active Body remains a ``KeyboardTextBody`` subtype so the typed
    keyboard ownership contract stays intact. This subtype adds only a durable
    pre-dispatch uncertainty boundary for generic command and append side effects;
    richer pointer-click and keyboard-text non-replay contracts remain unchanged.
    """

    def __init__(self, *, kernel, capabilities=None, budget=None):
        super().__init__(kernel=kernel, capabilities=capabilities, budget=budget)
        self.body = SideEffectAwareBody(resident=self)
        self.automation_text_state = NativeFocusedAutomationTextSense()
        self.managed_browser = PlaywrightManagedBrowser()
