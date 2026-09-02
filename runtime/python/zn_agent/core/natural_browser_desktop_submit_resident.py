from __future__ import annotations

"""Compatibility import for the retired browser-to-desktop Resident layer."""

from .natural_file_work_resident import NaturalFileWorkResidentRuntime

NaturalBrowserDesktopSubmitResidentRuntime = NaturalFileWorkResidentRuntime

__all__ = ["NaturalBrowserDesktopSubmitResidentRuntime"]
