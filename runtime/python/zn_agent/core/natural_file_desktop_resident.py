from __future__ import annotations

"""Compatibility import for the retired file-to-desktop Resident layer.

Desktop value transfer is now owned by ``NaturalFileWorkResidentRuntime`` as one
shared typed task path. Keep the historical symbol temporarily so tests and
callers do not break merely because the task-specific inheritance layer exited
production composition.
"""

from .natural_file_work_resident import NaturalFileWorkResidentRuntime

_BROWSER_PROCESS_NAMES = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe"}

NaturalFileDesktopResidentRuntime = NaturalFileWorkResidentRuntime

__all__ = ["NaturalFileDesktopResidentRuntime", "_BROWSER_PROCESS_NAMES"]
