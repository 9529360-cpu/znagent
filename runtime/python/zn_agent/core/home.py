from __future__ import annotations

import os
from pathlib import Path


def get_zn_home() -> Path:
    """Return ZN Agent's own persistent home directory.

    ZN state is intentionally independent from the legacy runtime home. The
    legacy stack may still provide tools/providers during migration, but it no
    longer owns the resident agent's identity or durable state.
    """

    explicit = (os.getenv("ZN_AGENT_HOME") or os.getenv("ZN_HOME") or "").strip()
    if explicit:
        return Path(explicit).expanduser()

    if os.name == "nt":
        local = (os.getenv("LOCALAPPDATA") or "").strip()
        if local:
            return Path(local) / "znagent"
    return Path.home() / ".znagent"
