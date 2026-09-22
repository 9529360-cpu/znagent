from __future__ import annotations

"""Compatibility surface for the retired current-API-docs scenario module.

Product composition now lives in :mod:`browser_workspace_adaptation_resident`.
These aliases preserve historical imports while callers migrate to the generic
browser-reference + workspace adaptation substrate.
"""

from .browser_workspace_adaptation_resident import (
    BrowserWorkspaceAdaptationDelegatedWorkCoordinator,
    BrowserWorkspaceAdaptationResidentRuntime,
)


CurrentApiDocsDelegatedWorkCoordinator = BrowserWorkspaceAdaptationDelegatedWorkCoordinator
CurrentApiDocsAdaptationResidentRuntime = BrowserWorkspaceAdaptationResidentRuntime

__all__ = [
    "BrowserWorkspaceAdaptationDelegatedWorkCoordinator",
    "BrowserWorkspaceAdaptationResidentRuntime",
    "CurrentApiDocsDelegatedWorkCoordinator",
    "CurrentApiDocsAdaptationResidentRuntime",
]
