from __future__ import annotations

"""Compatibility import for the retired file-to-desktop-submit Resident layer."""

from .natural_file_work_resident import NaturalFileWorkResidentRuntime

NaturalFileDesktopSubmitResidentRuntime = NaturalFileWorkResidentRuntime

__all__ = ["NaturalFileDesktopSubmitResidentRuntime"]
