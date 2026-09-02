from __future__ import annotations

"""Compatibility import for the retired named-desktop-input Resident layer."""

from .natural_file_work_resident import NaturalFileWorkResidentRuntime

NaturalNamedDesktopInputResidentRuntime = NaturalFileWorkResidentRuntime

__all__ = ["NaturalNamedDesktopInputResidentRuntime"]
